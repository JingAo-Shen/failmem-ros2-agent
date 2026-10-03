"""
Model Capability Screening Runner (FailMem Stage 2).
Evaluates foundational model capability across 24 standalone screening tasks (no cross-task memory).
Evaluates:
  - Config A: Qwen2.5-Coder-7B-Instruct (Direct Structured JSON)
  - Config B: Qwen2.5-Coder-7B-Instruct (CoT / Thinking Mode: <think> reasoning + JSON)

Evaluates Against Engineering Admission Criteria:
  1. Basic Delivery & Tool Calling: 100% completion
  2. Action Schema Validity Rate: >= 95%
  3. Total Task Success Rate: >= 80%
  4. Peak VRAM & Inference Latency within continuous local budget
"""
import sys
import os
import json
import time
import copy
import torch
from pathlib import Path
from typing import Dict, Any, List

from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..agent.planner import AgentPlanner, MAP_ADJACENCY
from ..env.task_env import DeliveryTaskEnv
from ..env.screening_tasks_24 import get_24_screening_tasks, verify_screening_task_feasibility
from ..memory.subgoal_memory_adapter import SubgoalMemoryAdapter


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "model_screening_results.json"


def run_model_screening():
    print("=" * 78)
    print("STARTING 24-TASK MODEL CAPABILITY SCREENING BENCHMARK")
    print("Model: /models/Qwen2.5-Coder-7B-Instruct (GPU CUDA, deterministic)")
    print("=" * 78)

    # 1. First verify feasibility of all 24 tasks
    tasks = get_24_screening_tasks()
    print(f"\n[Verification] Verifying feasibility of {len(tasks)} screening tasks...")
    for t in tasks:
        ok, msg, _ = verify_screening_task_feasibility(t)
        if not ok:
            raise RuntimeError(f"Task {t['task_id']} failed feasibility check: {msg}")
    print("[Verification] All 24 screening tasks 100% verified solvable by oracle.\n")

    configs = [
        {"id": "Config_A_Direct", "name": "Qwen2.5-Coder-7B-Instruct (Direct Structured)", "thinking": False},
        {"id": "Config_B_CoT", "name": "Qwen2.5-Coder-7B-Instruct (CoT Thinking Mode)", "thinking": True},
    ]

    llm = LLMBackend(model_path="/models/Qwen2.5-Coder-7B-Instruct", device="cuda")

    all_config_results = {}
    t_start_total = time.time()

    for cfg in configs:
        cfg_id = cfg["id"]
        cfg_name = cfg["name"]
        thinking_mode = cfg["thinking"]

        print(f"\n>>> Running Screening on: {cfg_name} (thinking={thinking_mode})")
        torch.cuda.reset_peak_memory_stats()
        t_cfg_start = time.time()

        task_runs = []
        total_schema_attempts = 0
        valid_schema_attempts = 0

        for t_idx, task in enumerate(tasks, start=1):
            tid = task["task_id"]
            cat = task["category"]
            t_task_start = time.time()

            adapter = SubgoalMemoryAdapter(injection_mode="none", store_mode="F", adjacency_map=MAP_ADJACENCY)
            adapter.on_task_start(tid, 0)

            runner = AgentRunner(
                llm_backend=llm,
                memory_adapter=adapter,
                max_tool_calls=20,
                max_llm_calls=15,
                run_id=f"screen_{cfg_id}_{tid}",
                use_task_skeleton=True,
            )

            # Patch prompt thinking mode if thinking=True
            if thinking_mode:
                runner.planner.system_prompt_addon = (
                    "Please think carefully inside a `<think>...</think>` block before outputting the final JSON.\n"
                    "Analyze the pending obligations, preconditions, and valid adjacent moves, then produce the JSON."
                )

            task_spec = {
                "task_id": tid,
                "instruction": task["instruction"],
                "env_config": copy.deepcopy(task["env_config"]),
            }

            res = runner.run_task(task_spec, task_index=0, seq_id="screen_bench")
            t_task_wall = time.time() - t_task_start

            # Calculate schema validity
            for trace in res.get("llm_traces", []):
                total_schema_attempts += 1
                if not trace.get("parse_error", False):
                    valid_schema_attempts += 1

            success = bool(res.get("success", False))
            step_count = len(res.get("step_history", []))
            batt = res.get("battery_consumed", 0)

            task_runs.append({
                "task_id": tid,
                "category": cat,
                "success": success,
                "steps": step_count,
                "battery_consumed": batt,
                "sim_time_s": res.get("sim_time_s", 0.0),
                "llm_calls": res.get("llm_calls", 0),
                "wall_time_s": round(t_task_wall, 2),
                "constraint_violations": res.get("constraint_violations", []),
                "step_history": res.get("step_history", []),
            })

            print(f"  [{t_idx:2d}/24] {tid:42s} | Success={str(success):5s} | Steps={step_count:2d} | Batt={batt:2d}% | Wall={t_task_wall:4.1f}s")

        t_cfg_wall = time.time() - t_cfg_start
        peak_vram_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2)

        # Aggregate metrics
        n_tasks = len(task_runs)
        n_success = sum(1 for r in task_runs if r["success"])
        success_rate = round(n_success / n_tasks, 4)

        # Category breakdowns
        cat_summaries = {}
        for c in set(r["category"] for r in task_runs):
            c_runs = [r for r in task_runs if r["category"] == c]
            c_succ = sum(1 for r in c_runs if r["success"])
            cat_summaries[c] = {
                "total": len(c_runs),
                "success": c_succ,
                "success_rate": round(c_succ / len(c_runs), 4),
            }

        schema_valid_rate = round(valid_schema_attempts / max(1, total_schema_attempts), 4)
        basic_delivery_rate = cat_summaries.get("1_basic_delivery", {}).get("success_rate", 0.0)

        meets_admission = (
            basic_delivery_rate >= 1.0 and
            schema_valid_rate >= 0.95 and
            success_rate >= 0.80 and
            peak_vram_mb < 20000
        )

        cfg_summary = {
            "config_id": cfg_id,
            "config_name": cfg_name,
            "thinking_mode": thinking_mode,
            "total_tasks": n_tasks,
            "success_count": n_success,
            "success_rate": success_rate,
            "schema_validity_rate": schema_valid_rate,
            "basic_delivery_completion_rate": basic_delivery_rate,
            "meets_admission_criteria": meets_admission,
            "peak_vram_mb": peak_vram_mb,
            "total_wall_time_s": round(t_cfg_wall, 2),
            "category_breakdown": cat_summaries,
            "task_runs": task_runs,
        }
        all_config_results[cfg_id] = cfg_summary

        print(f"\nSummary for {cfg_id}:")
        print(f"  Overall Success Rate: {n_success}/{n_tasks} ({success_rate*100:.1f}%)")
        print(f"  Schema Valid Rate:    {schema_valid_rate*100:.1f}%")
        print(f"  Basic Delivery Rate:  {basic_delivery_rate*100:.1f}%")
        print(f"  Peak VRAM:            {peak_vram_mb} MB")
        print(f"  Meets Admission:      {meets_admission}")

    # Determine recommended locked configuration
    best_cfg_id = max(all_config_results.keys(), key=lambda k: (all_config_results[k]["success_rate"], all_config_results[k]["schema_validity_rate"]))
    best_cfg = all_config_results[best_cfg_id]

    payload = {
        "benchmark": "24_task_model_screening",
        "total_wall_time_s": round(time.time() - t_start_total, 2),
        "selected_configuration": best_cfg_id,
        "selection_rationale": f"Selected {best_cfg_id} with success_rate={best_cfg['success_rate']*100:.1f}%, schema_validity={best_cfg['schema_validity_rate']*100:.1f}%, peak_vram={best_cfg['peak_vram_mb']}MB.",
        "admission_criteria": {
            "basic_delivery_100pct": best_cfg["basic_delivery_completion_rate"] >= 1.0,
            "schema_validity_ge_95pct": best_cfg["schema_validity_rate"] >= 0.95,
            "success_rate_ge_80pct": best_cfg["success_rate"] >= 0.80,
            "vram_manageable": best_cfg["peak_vram_mb"] < 20000,
        },
        "config_results": all_config_results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("\n" + "=" * 78)
    print(f"MODEL SCREENING COMPLETED. LOCKED BASE MODEL: {best_cfg_id}")
    print(f"Results saved to {OUTPUT_FILE}")
    print("=" * 78)


if __name__ == "__main__":
    run_model_screening()
