"""
Main Held-Out Evaluation Benchmark (96 Runs) for Workstation Multi-Fault Agent.

Tasks: 24 New Held-Out Instances across 4 Transfer Categories
Groups:
  1. Group_B2_plan: Structured facts + multi-step planning
  2. Group_B1_plan: Full raw source trajectories + intervention facts + multi-step planning
  3. Group_Replay: Naive trajectory replay matching observed fault
  4. Group_D_gated: Gated procedural memory (Check -> Defer -> State-Change Re-evaluate -> Execute)

Configuration:
  - Base Model: Qwen/Qwen3-14B-AWQ (CUDA, T=0.0, max_new_tokens=512)
  - Unified Budget: 32 LLM calls, 40 Tool calls, max 4 steps per plan
  - Timeout: 1800.0s protection ceiling (with 300s / 600s / 1800s completion metrics)
  - Randomized group ordering per task with fixed seed (42)
  - Atomic checkpoint / resume per run
"""
import os
import sys
import json
import time
import copy
import random
import gc
from pathlib import Path
from typing import Dict, Any, List

import torch

from .workstation_env import WorkstationEnv, StatusCode
from .heldout_tasks import get_heldout_tasks, generate_heldout_manifest
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
)
from .workstation_agent import WorkstationAgentRunner
from ..agent.llm_backend import LLMBackend


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
HELDOUT_OUTPUT_FILE = RESULTS_DIR / "heldout_96_diagnosis_results.json"
HELDOUT_MANIFEST_FILE = RESULTS_DIR / "heldout_benchmark_manifest.json"
SOURCE_DATA_FILE = RESULTS_DIR / "workstation_benchmark_results.json"
RECOMPILED_FACTS_FILE = RESULTS_DIR / "recompiled_structured_facts.json"
RECOMPILED_MEMS_FILE = RESULTS_DIR / "recompiled_procedural_memories.json"
MODEL_PATH = "/models/Qwen3-14B-AWQ"
RANDOM_SEED = 42


def load_recompiled_stores():
    with open(SOURCE_DATA_FILE, "r", encoding="utf-8") as f:
        src_data = json.load(f)
    raw_source_episodes = src_data.get("phase_a_source_episodes", [])

    with open(RECOMPILED_FACTS_FILE, "r", encoding="utf-8") as f:
        facts_dict = json.load(f)

    with open(RECOMPILED_MEMS_FILE, "r", encoding="utf-8") as f:
        mems_dict = json.load(f)

    fact_store = StructuredFactStore()
    fact_store.verified_transitions = facts_dict.get("verified_transitions", [])
    fact_store.negative_preconditions = facts_dict.get("negative_preconditions", [])
    fact_store.action_preconditions = facts_dict.get("action_preconditions", {})
    fact_store.invalidation_rules = facts_dict.get("invalidation_rules", [])
    fact_store.causal_order_constraints = facts_dict.get("causal_order_constraints", [])
    fact_store.commutative_subsystems = facts_dict.get("commutative_subsystems", [])
    fact_store.total_intervention_tool_calls = facts_dict.get("total_intervention_tool_calls", 0)

    procedural_memories = ProceduralMemoryStore()
    for mid, mdict in mems_dict.get("memories", {}).items():
        procedural_memories.add_memory(ProceduralMemoryItem.from_dict(mdict))

    return raw_source_episodes, fact_store, procedural_memories


def run_heldout_benchmark():
    print("================================================================================")
    print(" FailMem Stage 7: Main Held-Out Evaluation Benchmark (96 Runs)")
    print(f" Model: {MODEL_PATH} (Qwen3-14B-AWQ Direct, GPU T=0.0)")
    print(" Tasks: 24 Held-Out Instances across 4 Transfer Categories")
    print(" Groups: Group_B2_plan, Group_B1_plan, Group_Replay, Group_D_gated")
    print("================================================================================")

    # Save benchmark manifest
    manifest = generate_heldout_manifest()
    with open(HELDOUT_MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[Manifest] Saved benchmark manifest to {HELDOUT_MANIFEST_FILE} (SHA256: {manifest['manifest_sha256'][:16]})")

    raw_source_episodes, fact_store, procedural_memories = load_recompiled_stores()
    print(f"[Init] Loaded {len(raw_source_episodes)} Phase A Source Episodes.")
    print(f"[Init] Loaded {len(fact_store.verified_transitions)} Verified Transitions, {len(fact_store.negative_preconditions)} Negative Facts.")
    print(f"[Init] Loaded {len(procedural_memories.memories)} Validated Procedural Memories.")

    # Load existing results for resume capability
    existing_results = []
    if HELDOUT_OUTPUT_FILE.exists():
        try:
            with open(HELDOUT_OUTPUT_FILE, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                existing_results = saved_data.get("heldout_results", [])
                print(f"[Resume] Found {len(existing_results)} existing run records.")
        except Exception as e:
            print(f"[Resume Warning] Could not parse existing file: {e}")

    done_keys = {(r["group_id"], r["task_id"]) for r in existing_results}

    # Initialize LLM Backend
    llm_backend = LLMBackend(
        model_path=MODEL_PATH,
        device="cuda" if torch.cuda.is_available() else "cpu",
        torch_dtype="float16",
        max_new_tokens=512,
        temperature=0.0,
        enable_thinking=False,
        quantization_format="awq",
        allow_fallback=False,
    )

    tasks = get_heldout_tasks()
    base_groups = ["Group_B2_plan", "Group_B1_plan", "Group_Replay", "Group_D_gated"]

    # Schedule runs with fixed random seed
    rng = random.Random(RANDOM_SEED)
    scheduled_runs = []
    for task in tasks:
        shuffled_groups = list(base_groups)
        rng.shuffle(shuffled_groups)
        for gid in shuffled_groups:
            scheduled_runs.append((task, gid))

    print(f"[Plan] Total scheduled runs: {len(scheduled_runs)} (Remaining: {len(scheduled_runs) - len(done_keys)})")

    run_idx = len(existing_results)
    for task_cfg, group_id in scheduled_runs:
        task_id = task_cfg["task_id"]
        if (group_id, task_id) in done_keys:
            print(f"[Skip] Already completed: {group_id} on {task_id}")
            continue

        run_idx += 1
        print(f"\n[{run_idx}/{len(scheduled_runs)}] Running {group_id} on {task_id} ({task_cfg.get('category')})...")
        
        runner = WorkstationAgentRunner(
            group_id=group_id,
            llm_backend=llm_backend,
            max_llm_calls=32,
            max_tool_calls=40,
            time_limit_s=1800.0,
            allow_fallback=False,
        )

        t_start = time.time()
        result = runner.run_task(
            task_config=task_cfg,
            raw_source_episodes=raw_source_episodes,
            structured_facts=fact_store,
            procedural_memory_store=procedural_memories,
        )
        t_elapsed = round(time.time() - t_start, 2)

        status_str = "SUCCESS" if result["success"] else f"FAILED ({result['termination_reason']})"
        print(f"[{group_id} | {task_id}] Result: {status_str} | Steps: {result['step_count']} | LLM Calls: {result['llm_calls']} | Time: {t_elapsed}s | Latency (300s/600s/1800s): {result['completed_at_300s']}/{result['completed_at_600s']}/{result['completed_at_1800s']}")
        if "Group_D" in group_id:
            print(f"   -> Memory Selected: {result['memory_selected_count']} | Deferred: {result.get('memory_deferred_count', 0)} | Resumed: {result.get('memory_resumed_count', 0)} | Executed: {result['memory_action_executed_count']} | Verified: {result['memory_postcondition_verified_count']} | Invalidated: {result['memory_invalidated_count']}")

        existing_results.append(result)
        done_keys.add((group_id, task_id))

        # Save atomic checkpoint
        checkpoint_data = {
            "metadata": {
                "benchmark_name": "Heldout 96 Benchmark",
                "model_path": MODEL_PATH,
                "device": "cuda",
                "random_seed": RANDOM_SEED,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_runs": len(existing_results),
            },
            "heldout_results": existing_results,
        }
        with open(HELDOUT_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            gc.collect()

    print("\n================================================================================")
    print(" Heldout Main Evaluation Complete. Results saved to:", HELDOUT_OUTPUT_FILE)
    print("================================================================================")


if __name__ == "__main__":
    run_heldout_benchmark()
