"""
Diagnostic Evaluation Benchmarks (Batch 1 & Batch 2, Total 48 Runs).

Instances: 8 Fixed Synthetic Evaluation Instances:
  - 4 Power-failed instances:
      heldout_cat2_tpl2_inst1_power_pneu_combo_a
      heldout_cat3_tpl1_inst1_power_blocks_gripper_sensor_a
      heldout_cat3_tpl2_inst1_double_interlock_load_power_a
      heldout_cat3_tpl3_inst1_multistage_interlock_a
  - 2 Non-power multi-fault instances:
      heldout_cat2_tpl1_inst1_pneu_gripper_combo_a
      heldout_cat2_tpl3_inst1_triple_combo_a
  - 2 Historically irrelevant / partial instances:
      heldout_cat4_tpl1_inst1_controller_counter_overflow
      heldout_cat4_tpl2_inst1_clean_system_sensor_drift_a

Groups:
  - Group_B2_plan
  - Group_Replay
  - Group_D_gated

Batches:
  - Batch 1 (24 runs): enable_constraint_repair_planning = True
  - Batch 2 (24 runs): enable_constraint_repair_planning = False

Goal strings are normalized to remove direct procedural sequence hints:
  goal = "Diagnose workstation, resolve all active faults, verify system safety, and resume production."
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

BATCH1_OUTPUT_FILE = RESULTS_DIR / "batch1_diagnostic_results.json"
BATCH2_OUTPUT_FILE = RESULTS_DIR / "batch2_ablation_results.json"

SOURCE_DATA_FILE = RESULTS_DIR / "workstation_benchmark_results.json"
RECOMPILED_FACTS_FILE = RESULTS_DIR / "recompiled_structured_facts.json"
RECOMPILED_MEMS_FILE = RESULTS_DIR / "recompiled_procedural_memories.json"

MODEL_PATH = "/models/Qwen3-14B-AWQ"
RANDOM_SEED = 42

TARGET_TASK_IDS = [
    "heldout_cat2_tpl2_inst1_power_pneu_combo_a",
    "heldout_cat3_tpl1_inst1_power_blocks_gripper_sensor_a",
    "heldout_cat3_tpl2_inst1_double_interlock_load_power_a",
    "heldout_cat3_tpl3_inst1_multistage_interlock_a",
    "heldout_cat2_tpl1_inst1_pneu_gripper_combo_a",
    "heldout_cat2_tpl3_inst1_triple_combo_a",
    "heldout_cat4_tpl1_inst1_controller_counter_overflow",
    "heldout_cat4_tpl2_inst1_clean_system_sensor_drift_a",
]

TARGET_GROUPS = [
    "Group_B2_plan",
    "Group_Replay",
    "Group_D_gated",
]

CLEAN_GOAL = "Diagnose workstation, resolve all active faults, verify system safety, and resume production."


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


def get_diagnostic_task_configs() -> List[Dict[str, Any]]:
    all_heldout = {t["task_id"]: t for t in get_heldout_tasks()}
    diagnostic_tasks = []
    for tid in TARGET_TASK_IDS:
        task = copy.deepcopy(all_heldout[tid])
        task["original_goal"] = task["goal"]
        task["goal"] = CLEAN_GOAL  # Strip sequence hints
        diagnostic_tasks.append(task)
    return diagnostic_tasks


def run_batch(
    batch_name: str,
    output_file: Path,
    enable_constraint_repair: bool,
    llm_backend: LLMBackend,
    raw_source_episodes: List[Dict[str, Any]],
    fact_store: StructuredFactStore,
    procedural_memories: ProceduralMemoryStore,
):
    print("=" * 80)
    print(f" Running {batch_name} (enable_constraint_repair_planning={enable_constraint_repair})")
    print(f" Target File: {output_file}")
    print("=" * 80)

    existing_results = []
    if output_file.exists():
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                existing_results = saved.get("results", [])
                print(f"[Resume] Found {len(existing_results)} existing records.")
        except Exception as e:
            print(f"[Resume Warning] Could not parse existing results: {e}")

    done_keys = {(r["group_id"], r["task_id"]) for r in existing_results}

    tasks = get_diagnostic_task_configs()

    # Fixed deterministic schedule
    rng = random.Random(RANDOM_SEED)
    scheduled_runs = []
    for task in tasks:
        shuffled_groups = list(TARGET_GROUPS)
        rng.shuffle(shuffled_groups)
        for gid in shuffled_groups:
            scheduled_runs.append((task, gid))

    print(f"[Schedule] Total runs: {len(scheduled_runs)} (Remaining: {len(scheduled_runs) - len(done_keys)})")

    run_idx = len(existing_results)
    for task_cfg, group_id in scheduled_runs:
        task_id = task_cfg["task_id"]
        if (group_id, task_id) in done_keys:
            print(f"[Skip] Already completed: {group_id} on {task_id}")
            continue

        run_idx += 1
        print(f"\n[{batch_name} | {run_idx}/{len(scheduled_runs)}] Running {group_id} on {task_id}...")

        runner = WorkstationAgentRunner(
            group_id=group_id,
            llm_backend=llm_backend,
            max_llm_calls=32,
            max_tool_calls=40,
            time_limit_s=1800.0,
            allow_fallback=False,
            enable_constraint_repair_planning=enable_constraint_repair,
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
        print(f"[{group_id} | {task_id}] Result: {status_str} | Steps: {result['step_count']} | LLM Calls: {result['llm_calls']} | Time: {t_elapsed}s | Latency (300/600/1800s): {result['completed_at_300s']}/{result['completed_at_600s']}/{result['completed_at_1800s']}")
        if "Group_D" in group_id:
            print(f"   -> Memory Selected: {result['memory_selected_count']} | Deferred: {result.get('memory_deferred_count', 0)} | Resumed: {result.get('memory_resumed_count', 0)} | Executed: {result['memory_action_executed_count']} | Verified: {result['memory_postcondition_verified_count']} | Invalidated: {result['memory_invalidated_count']}")

        existing_results.append(result)
        done_keys.add((group_id, task_id))

        # Atomic checkpoint save
        checkpoint_data = {
            "metadata": {
                "batch_name": batch_name,
                "enable_constraint_repair_planning": enable_constraint_repair,
                "model_path": MODEL_PATH,
                "device": "cuda",
                "random_seed": RANDOM_SEED,
                "goal_hint_stripped": True,
                "normalized_goal": CLEAN_GOAL,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_runs": len(existing_results),
            },
            "results": existing_results,
        }

        tmp_file = output_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)
        os.replace(tmp_file, output_file)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            gc.collect()

    print(f"\n[Done] {batch_name} complete. Saved {len(existing_results)} runs to {output_file}\n")


def main():
    print("================================================================================")
    print(" FailMem Diagnostic & Ablation Benchmark Suite (Batch 1 & Batch 2)")
    print(f" Model: {MODEL_PATH} (Qwen3-14B-AWQ, T=0.0, single GPU)")
    print(" Instances: 8 Fixed Held-Out Instances (Goal Hints Stripped)")
    print(" Groups: Group_B2_plan, Group_Replay, Group_D_gated")
    print("================================================================================")

    raw_source_episodes, fact_store, procedural_memories = load_recompiled_stores()
    print(f"[Init] Loaded {len(raw_source_episodes)} Phase A Source Episodes.")
    print(f"[Init] Loaded {len(fact_store.verified_transitions)} Facts, {len(procedural_memories.memories)} Memories.")

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

    # Batch 1: Diagnostic with Constraint Repair Planning
    run_batch(
        batch_name="Batch 1: Diagnostic Benchmark (Repair Planning Enabled)",
        output_file=BATCH1_OUTPUT_FILE,
        enable_constraint_repair=True,
        llm_backend=llm_backend,
        raw_source_episodes=raw_source_episodes,
        fact_store=fact_store,
        procedural_memories=procedural_memories,
    )

    # Batch 2: Ablation with Constraint Repair Planning Disabled
    run_batch(
        batch_name="Batch 2: Ablation Benchmark (Repair Planning Disabled)",
        output_file=BATCH2_OUTPUT_FILE,
        enable_constraint_repair=False,
        llm_backend=llm_backend,
        raw_source_episodes=raw_source_episodes,
        fact_store=fact_store,
        procedural_memories=procedural_memories,
    )


if __name__ == "__main__":
    main()
