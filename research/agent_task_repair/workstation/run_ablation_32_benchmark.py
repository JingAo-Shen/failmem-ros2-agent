"""
Ablation Benchmark (32 Runs) for Workstation Multi-Fault Agent.

Pre-Selected 16 Instances (4 per category):
  - Cat 1:
      heldout_cat1_tpl1_inst1_pneu_high
      heldout_cat1_tpl1_inst2_pneu_extreme
      heldout_cat1_tpl2_inst1_gripper_misaligned_light
      heldout_cat1_tpl3_inst1_sensor_drift_low
  - Cat 2:
      heldout_cat2_tpl1_inst1_pneu_gripper_combo_a
      heldout_cat2_tpl2_inst1_power_pneu_combo_a
      heldout_cat2_tpl3_inst1_triple_combo_a
      heldout_cat2_tpl3_inst2_triple_combo_b
  - Cat 3:
      heldout_cat3_tpl1_inst1_power_blocks_gripper_sensor_a
      heldout_cat3_tpl2_inst1_double_interlock_load_power_a
      heldout_cat3_tpl2_inst2_double_interlock_load_power_b
      heldout_cat3_tpl3_inst1_multistage_interlock_a
  - Cat 4:
      heldout_cat4_tpl1_inst1_controller_counter_overflow
      heldout_cat4_tpl1_inst2_controller_watchdog_fault
      heldout_cat4_tpl2_inst1_clean_system_sensor_drift_a
      heldout_cat4_tpl3_inst1_nominal_startup_standard

Ablation Groups:
  1. Group_D_gated_no_filter: No pre-execution applicability check (retains common execution validation)
  2. Group_D_gated_no_reeval: Defers on condition failure, but never re-evaluates deferred memories on state changes

Configuration:
  - Base Model: Qwen/Qwen3-14B-AWQ (CUDA, T=0.0, max_new_tokens=512)
  - Unified Budget: 32 LLM calls, 40 Tool calls, max 4 steps per plan
  - Timeout: 1800.0s protection ceiling
  - Total: 16 tasks x 2 groups = 32 runs
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
from .heldout_tasks import get_heldout_tasks
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
)
from .workstation_agent import WorkstationAgentRunner
from ..agent.llm_backend import LLMBackend


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
ABLATION_OUTPUT_FILE = RESULTS_DIR / "ablation_32_diagnosis_results.json"
SOURCE_DATA_FILE = RESULTS_DIR / "workstation_benchmark_results.json"
RECOMPILED_FACTS_FILE = RESULTS_DIR / "recompiled_structured_facts.json"
RECOMPILED_MEMS_FILE = RESULTS_DIR / "recompiled_procedural_memories.json"
MODEL_PATH = "/models/Qwen3-14B-AWQ"
RANDOM_SEED = 42

PRESELECTED_16_TASK_IDS = [
    # Cat 1 (4)
    "heldout_cat1_tpl1_inst1_pneu_high",
    "heldout_cat1_tpl1_inst2_pneu_extreme",
    "heldout_cat1_tpl2_inst1_gripper_misaligned_light",
    "heldout_cat1_tpl3_inst1_sensor_drift_low",
    # Cat 2 (4)
    "heldout_cat2_tpl1_inst1_pneu_gripper_combo_a",
    "heldout_cat2_tpl2_inst1_power_pneu_combo_a",
    "heldout_cat2_tpl3_inst1_triple_combo_a",
    "heldout_cat2_tpl3_inst2_triple_combo_b",
    # Cat 3 (4)
    "heldout_cat3_tpl1_inst1_power_blocks_gripper_sensor_a",
    "heldout_cat3_tpl2_inst1_double_interlock_load_power_a",
    "heldout_cat3_tpl2_inst2_double_interlock_load_power_b",
    "heldout_cat3_tpl3_inst1_multistage_interlock_a",
    # Cat 4 (4)
    "heldout_cat4_tpl1_inst1_controller_counter_overflow",
    "heldout_cat4_tpl1_inst2_controller_watchdog_fault",
    "heldout_cat4_tpl2_inst1_clean_system_sensor_drift_a",
    "heldout_cat4_tpl3_inst1_nominal_startup_standard",
]


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


def run_ablation_benchmark():
    print("================================================================================")
    print(" FailMem Stage 8: Ablation Benchmark (32 Runs)")
    print(f" Model: {MODEL_PATH} (Qwen3-14B-AWQ Direct, GPU T=0.0)")
    print(f" Tasks: {len(PRESELECTED_16_TASK_IDS)} Pre-Selected Instances (4 per category)")
    print(" Groups: Group_D_gated_no_filter, Group_D_gated_no_reeval (32 Total Runs)")
    print("================================================================================")

    raw_source_episodes, fact_store, procedural_memories = load_recompiled_stores()

    existing_results = []
    if ABLATION_OUTPUT_FILE.exists():
        try:
            with open(ABLATION_OUTPUT_FILE, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                existing_results = saved_data.get("ablation_results", [])
                print(f"[Resume] Found {len(existing_results)} existing ablation run records.")
        except Exception as e:
            print(f"[Resume Warning] Could not parse existing file: {e}")

    done_keys = {(r["group_id"], r["task_id"]) for r in existing_results}

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

    all_tasks = {t["task_id"]: t for t in get_heldout_tasks()}
    ablation_tasks = [all_tasks[tid] for tid in PRESELECTED_16_TASK_IDS if tid in all_tasks]
    ablation_groups = ["Group_D_gated_no_filter", "Group_D_gated_no_reeval"]

    rng = random.Random(RANDOM_SEED)
    scheduled_runs = []
    for task in ablation_tasks:
        shuffled_groups = list(ablation_groups)
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
        print(f"   -> Memory Selected: {result['memory_selected_count']} | Deferred: {result.get('memory_deferred_count', 0)} | Resumed: {result.get('memory_resumed_count', 0)} | Executed: {result['memory_action_executed_count']} | Verified: {result['memory_postcondition_verified_count']} | Invalidated: {result['memory_invalidated_count']}")

        existing_results.append(result)
        done_keys.add((group_id, task_id))

        checkpoint_data = {
            "metadata": {
                "benchmark_name": "Ablation 32 Benchmark",
                "model_path": MODEL_PATH,
                "device": "cuda",
                "random_seed": RANDOM_SEED,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_runs": len(existing_results),
            },
            "ablation_results": existing_results,
        }
        with open(ABLATION_OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            gc.collect()

    print("\n================================================================================")
    print(" Ablation Evaluation Complete. Results saved to:", ABLATION_OUTPUT_FILE)
    print("================================================================================")


if __name__ == "__main__":
    run_ablation_benchmark()
