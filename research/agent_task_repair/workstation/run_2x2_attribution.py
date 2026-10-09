"""
2x2 Factorial Attribution Benchmark for Group_B2_plan (Total 32 Runs).

Conditions:
  1. NoRecipe_StandardReplan: Clean tool semantics, no recipes; standard replan on 2nd repeat.
  2. NoRecipe_FocusedRepair: Clean tool semantics, no recipes; focused repair prompt on 2nd repeat.
  3. ExpertRecipe_StandardReplan: Expert prompt (tool action chains) + standard goal-directed replan.
  4. ExpertRecipe_FocusedRepair: Expert prompt (tool action chains + Domain Interlock Protocols) + focused repair.

8 Fixed Synthetic Evaluation Instances:
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

Fixed Model & Constraints:
  - Qwen3-14B-AWQ, single GPU, T=0.0, max_new_tokens=512
  - Budget: 32 LLM / 40 Tool / 1800s timeout
  - Clean abstract goal: "Diagnose workstation, resolve all active faults, verify system safety, and resume production."
"""
import os
import sys
import json
import time
import copy
import random
import tempfile
import hashlib
from pathlib import Path
from typing import Dict, Any, List

import torch
import numpy as np

from .workstation_env import WorkstationEnv, StatusCode
from .heldout_tasks import get_heldout_tasks
from .procedural_memory import StructuredFactStore
from .workstation_agent import WorkstationAgentRunner
from ..agent.llm_backend import LLMBackend


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "attribution_2x2_results.json"
MANIFEST_FILE = RESULTS_DIR / "attribution_schedule_manifest.json"

RECOMPILED_FACTS_FILE = RESULTS_DIR / "recompiled_structured_facts.json"
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

CONDITIONS = [
    {
        "condition_name": "NoRecipe_StandardReplan",
        "recipe_mode": "none",
        "replan_mode": "standard",
        "desc": "Clean prompt (no action chains) + standard goal-directed replan",
    },
    {
        "condition_name": "NoRecipe_FocusedRepair",
        "recipe_mode": "none",
        "replan_mode": "focused",
        "desc": "Clean prompt (no action chains) + focused precondition unblocking",
    },
    {
        "condition_name": "ExpertRecipe_StandardReplan",
        "recipe_mode": "expert",
        "replan_mode": "standard",
        "desc": "Expert prompt (tool action chains) + standard goal-directed replan",
    },
    {
        "condition_name": "ExpertRecipe_FocusedRepair",
        "recipe_mode": "expert",
        "replan_mode": "focused",
        "desc": "Expert prompt (tool action chains + Domain Interlock Protocols) + focused repair",
    },
]

CLEAN_GOAL = "Diagnose workstation, resolve all active faults, verify system safety, and resume production."


def load_facts():
    with open(RECOMPILED_FACTS_FILE, "r", encoding="utf-8") as f:
        facts_dict = json.load(f)

    fact_store = StructuredFactStore()
    fact_store.verified_transitions = facts_dict.get("verified_transitions", [])
    fact_store.negative_preconditions = facts_dict.get("negative_preconditions", [])
    fact_store.action_preconditions = facts_dict.get("action_preconditions", {})
    fact_store.invalidation_rules = facts_dict.get("invalidation_rules", [])
    fact_store.causal_order_constraints = facts_dict.get("causal_order_constraints", [])
    fact_store.commutative_subsystems = facts_dict.get("commutative_subsystems", [])
    fact_store.total_intervention_tool_calls = facts_dict.get("total_intervention_tool_calls", 0)
    return fact_store


def get_attribution_tasks() -> List[Dict[str, Any]]:
    all_heldout = {t["task_id"]: t for t in get_heldout_tasks()}
    tasks = []
    for tid in TARGET_TASK_IDS:
        task = copy.deepcopy(all_heldout[tid])
        task["original_goal"] = task["goal"]
        task["goal"] = CLEAN_GOAL
        tasks.append(task)
    return tasks


def save_atomic(data: Dict[str, Any], filepath: Path):
    tmp_dir = filepath.parent
    with tempfile.NamedTemporaryFile("w", dir=tmp_dir, delete=False, encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_name = f.name
    os.replace(tmp_name, filepath)


def main():
    print("=" * 80)
    print(" 2x2 Factorial Attribution Benchmark (32 Runs)")
    print(f" Target Model: {MODEL_PATH} (Qwen3-14B-AWQ, T=0.0)")
    print(f" Conditions: 4 (8 Tasks x 4 = 32 Runs)")
    print("=" * 80)

    fact_store = load_facts()
    tasks = get_attribution_tasks()

    # Load existing results if resuming
    existing_results = []
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                existing_results = saved.get("results", [])
                print(f"[Resume] Found {len(existing_results)} existing records in {OUTPUT_FILE}")
        except Exception as e:
            print(f"[Resume Warning] Could not parse existing results: {e}")

    # Build schedule
    rng = random.Random(RANDOM_SEED)
    scheduled_runs = []
    for task in tasks:
        shuffled_conds = list(CONDITIONS)
        rng.shuffle(shuffled_conds)
        for cond in shuffled_conds:
            scheduled_runs.append((task, cond))

    # Save manifest
    manifest_data = {
        "random_seed": RANDOM_SEED,
        "total_runs": len(scheduled_runs),
        "schedule": [
            {
                "task_id": t["task_id"],
                "condition": c["condition_name"],
                "recipe_mode": c["recipe_mode"],
                "replan_mode": c["replan_mode"],
            }
            for t, c in scheduled_runs
        ],
    }
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

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

    done_keys = {(r["condition"], r["task_id"]) for r in existing_results}
    print(f"[Schedule] Total runs: {len(scheduled_runs)} (Completed: {len(done_keys)}, Remaining: {len(scheduled_runs) - len(done_keys)})")

    run_idx = len(existing_results)
    all_results = list(existing_results)

    for task_cfg, cond in scheduled_runs:
        cond_name = cond["condition_name"]
        task_id = task_cfg["task_id"]
        key = (cond_name, task_id)
        if key in done_keys:
            print(f"[Skip] Already completed: {cond_name} on {task_id}")
            continue

        run_idx += 1
        print(f"\n[{run_idx}/{len(scheduled_runs)}] Running {cond_name} on {task_id}...")

        runner = WorkstationAgentRunner(
            group_id="Group_B2_plan",
            llm_backend=llm_backend,
            max_llm_calls=32,
            max_tool_calls=40,
            time_limit_s=1800.0,
            allow_fallback=False,
            enable_constraint_repair_planning=True,
            recipe_mode=cond["recipe_mode"],
            replan_mode=cond["replan_mode"],
        )

        res = runner.run_task(
            task_config=task_cfg,
            raw_source_episodes=None,
            structured_facts=fact_store,
            procedural_memory_store=None,
        )

        # Consistency assertions
        assert res["condition"] == cond_name, f"Condition mismatch: {res['condition']} != {cond_name}"
        assert res["llm_calls"] == len(res["llm_call_records"]), f"Call count mismatch: {res['llm_calls']} != {len(res['llm_call_records'])}"
        strict_p = sum(r["prompt_tokens"] for r in res["llm_call_records"])
        strict_g = sum(r["generated_tokens"] for r in res["llm_call_records"])
        assert res["total_prompt_tokens"] == strict_p, f"Prompt token mismatch: {res['total_prompt_tokens']} != {strict_p}"
        assert res["total_generated_tokens"] == strict_g, f"Gen token mismatch: {res['total_generated_tokens']} != strict_g"

        succ_str = "SUCCESS" if res["success"] else f"FAILED ({res['termination_reason']})"
        print(f" -> Result: {succ_str} | Steps: {res['step_count']} | LLM Calls: {res['llm_calls']} | Prompt Toks: {res['total_prompt_tokens']} | Gen Toks: {res['total_generated_tokens']} | Wall Time: {res['wall_time_s']}s")

        all_results.append(res)
        done_keys.add(key)

        # Atomic checkpoint
        payload = {
            "metadata": {
                "benchmark": "attribution_2x2_factorial",
                "model": MODEL_PATH,
                "commit_hash": res.get("commit_hash", "a3f4d1f"),
                "total_expected_runs": len(scheduled_runs),
                "total_completed_runs": len(all_results),
                "timestamp": time.time(),
            },
            "conditions": CONDITIONS,
            "results": all_results,
        }
        save_atomic(payload, OUTPUT_FILE)

    print("\n" + "=" * 80)
    print(" 2x2 Factorial Attribution Benchmark Finished! (32 Runs Complete)")
    print("=" * 80)

    # Print summary table
    print("\n--- SUMMARY OF RESULTS ---")
    for cond in CONDITIONS:
        cname = cond["condition_name"]
        c_runs = [r for r in all_results if r["condition"] == cname]
        succ = sum(1 for r in c_runs if r["success"])
        calls = [r["llm_calls"] for r in c_runs]
        p_toks = [r["total_prompt_tokens"] for r in c_runs]
        g_toks = [r["total_generated_tokens"] for r in c_runs]
        errs = [r["tool_errors_count"] for r in c_runs]
        print(f"Condition: {cname:<30} | Success: {succ}/8 ({succ/8*100:.1f}%) | Mean LLM: {np.mean(calls):.2f} | Total Calls: {sum(calls)} | Total Prompt Tok: {sum(p_toks)} | Total Errors: {sum(errs)}")


if __name__ == "__main__":
    main()
