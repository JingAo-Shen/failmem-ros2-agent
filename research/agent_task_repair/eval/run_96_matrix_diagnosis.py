"""
96-Unit Experiment Runner for FailMem Stage 2:
Evaluating Explicit Subgoal-Scoped Memory (G) vs Phase Heuristic Filtering (H)
across 8 Diagnostic Scenarios x 4 Conditions x 3 Runs = 96 Continuation Units.

Conditions:
  - Group A (S1_M0): Skeleton + No Cross-Task Memory
  - Group B (S1_M1): Skeleton + Global Memory Injection
  - Group C (S1_H):  Skeleton + Phase Heuristic Filtering (Baseline M2)
  - Group D (S1_G):  Skeleton + Explicit Subgoal-Scoped Memory Filter
"""
import sys
import os
import json
import time
import copy
from pathlib import Path
from typing import Dict, Any, List, Tuple

from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..agent.planner import MAP_ADJACENCY
from ..env.task_env import DeliveryTaskEnv
from ..env.diagnostic_scenarios_8 import get_8_diagnostic_scenarios, generate_authentic_seed_history
from ..eval.scorer import PilotScorer
from ..memory.subgoal_memory_adapter import SubgoalMemoryAdapter


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "matrix_96_diagnosis_results.json"


def evaluate_dependency_errors(step_history: List[Dict[str, Any]], seed_history: List[Dict[str, Any]]) -> int:
    """
    Distinguishes true dependency errors (violating known preconditions)
    from first-time discoveries of unknown environmental constraints.
    """
    dep_errors = 0
    # Track what has been discovered or established
    for step in step_history:
        res = step.get("result", {})
        status = res.get("status", "")
        tool = step.get("tool", "")
        params = step.get("params", {})

        # Dependency error 1: trying to deliver when not holding package
        if status == "NOT_HOLDING_PACKAGE":
            dep_errors += 1
        # Dependency error 2: trying to deliver to wrong room
        elif status == "WRONG_LOCATION" and tool == "deliver":
            dep_errors += 1
        # Dependency error 3: trying to pickup when inventory is full
        elif status == "INVENTORY_FULL":
            dep_errors += 1
        # Dependency error 4: trying to recharge when not at charger
        elif status == "NOT_AT_CHARGER":
            dep_errors += 1

    return dep_errors


def run_96_matrix():
    print("=" * 78)
    print("STARTING 96-UNIT CONTROLLED DIAGNOSIS (8 SCENARIOS x 4 GROUPS x 3 RUNS)")
    print("Model: /models/Qwen2.5-Coder-7B-Instruct (GPU CUDA, deterministic)")
    print("=" * 78)

    llm = LLMBackend(model_path="/models/Qwen2.5-Coder-7B-Instruct", device="cuda")

    scenarios = get_8_diagnostic_scenarios()
    conditions = [
        {"id": "S1_M0", "group": "A", "injection_mode": "none", "name": "Skeleton + No Memory (A)"},
        {"id": "S1_M1", "group": "B", "injection_mode": "global", "name": "Skeleton + Global Memory (B)"},
        {"id": "S1_H",  "group": "C", "injection_mode": "phase_heuristic", "name": "Skeleton + Phase Heuristic (C)"},
        {"id": "S1_G",  "group": "D", "injection_mode": "explicit_subgoal", "name": "Skeleton + Explicit Subgoal (D)"},
    ]
    num_runs = 3

    unit_results = []
    unit_index = 0
    t_start_total = time.time()

    for scen in scenarios:
        scen_id = scen["scenario_id"]
        scen_name = scen["name"]
        scen_dim = scen["dimension"]
        seed_type = scen["seed_type"]

        print(f"\n>>> Scenario: [{scen_id}] {scen_name} ({scen_dim})")

        # 1. Generate authentic seed history once per scenario
        pre_metrics, seed_steps, seed_events, shared_known = generate_authentic_seed_history(seed_type)

        for cond in conditions:
            cond_id = cond["id"]
            cond_group = cond["group"]
            inj_mode = cond["injection_mode"]

            for run_idx in range(1, num_runs + 1):
                unit_index += 1
                unit_id = f"{scen_id}_{cond_id}_r{run_idx}"
                t_unit_start = time.time()

                # Setup memory adapter with authentic seed events
                adapter = SubgoalMemoryAdapter(
                    injection_mode=inj_mode,
                    store_mode="F",
                    adjacency_map=MAP_ADJACENCY,
                )
                adapter.on_task_start("seed_t1", 0)

                for evt in seed_events:
                    if "action_name" in evt:
                        adapter.record_action_failure(
                            event_id=evt["event_id"],
                            task_id=evt["task_id"],
                            action_name=evt["action_name"],
                            target=evt["target"],
                            error_code=evt["error_code"],
                            raw_message=evt["raw_message"],
                            observation=evt.get("observation", {}),
                            sim_time=evt.get("sim_time", 0.0),
                        )
                    elif "observation" in evt:
                        adapter.record_observation(
                            event_id=evt["event_id"],
                            observation=evt["observation"],
                            sim_time=evt.get("sim_time", 0.0),
                        )

                # Initialize runner with PublicTaskSkeleton (S1)
                runner = AgentRunner(
                    llm_backend=llm,
                    memory_adapter=adapter,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=f"u{unit_index:03d}_{cond_id}",
                    use_task_skeleton=True,
                )

                # Run continuation Task 2
                task_spec = {
                    "task_id": f"{scen_id}_eval",
                    "instruction": scen["task_instruction"],
                    "env_config": copy.deepcopy(scen["env_config"]),
                }

                task_result = runner.run_task(
                    task_spec=task_spec,
                    task_index=1,
                    seq_id=scen_id,
                    initial_known_state=copy.deepcopy(shared_known),
                )

                t_unit_wall = time.time() - t_unit_start

                # Evaluate metrics
                success = bool(task_result.get("success", False))
                step_history = task_result.get("step_history", [])
                continuation_steps = len(step_history)
                continuation_battery = task_result.get("battery_consumed", 0)
                continuation_sim_time = task_result.get("sim_time_s", 0.0)

                dep_errors = evaluate_dependency_errors(step_history, seed_steps)

                # Score unwarranted detours and repeated failures
                scored = PilotScorer.score_sequence_results([task_result])
                rep_failures = scored.get("repeated_failures", 0)
                detours = scored.get("unwarranted_detour_count", 0)

                step1_dec = step_history[0].get("tool") if step_history else "none"
                step1_ok = step_history[0].get("result", {}).get("success", False) if step_history else False

                unit_record = {
                    "unit_index": unit_index,
                    "unit_id": unit_id,
                    "scenario_id": scen_id,
                    "scenario_name": scen_name,
                    "dimension": scen_dim,
                    "condition": cond_id,
                    "group": cond_group,
                    "run_index": run_idx,
                    "success": success,
                    "continuation_steps": continuation_steps,
                    "continuation_battery": continuation_battery,
                    "continuation_sim_time_s": continuation_sim_time,
                    "pre_run_battery": pre_metrics["pre_battery_consumed"],
                    "pre_run_sim_time_s": pre_metrics["pre_sim_time_s"],
                    "total_battery": continuation_battery + pre_metrics["pre_battery_consumed"],
                    "total_sim_time_s": continuation_sim_time + pre_metrics["pre_sim_time_s"],
                    "dependency_errors": dep_errors,
                    "repeated_failures": rep_failures,
                    "unwarranted_detours": detours,
                    "step1_action": step1_dec,
                    "step1_success": step1_ok,
                    "total_llm_calls": task_result.get("llm_calls", 0),
                    "wall_time_s": round(t_unit_wall, 2),
                    "retrieval_audits": adapter.retrieval_audit_log,
                    "step_history": step_history,
                    "constraint_violations": task_result.get("constraint_violations", []),
                }
                unit_results.append(unit_record)

                print(f"  [{unit_index:2d}/96] {cond_id:5s} r{run_idx}: Success={str(success):5s} | Steps={continuation_steps:2d} | Batt={continuation_battery:2d}% | DepErr={dep_errors} | RepFail={rep_failures} | Detour={detours} | Time={t_unit_wall:4.1f}s")

                # Checkpoint save
                checkpoint_payload = {
                    "benchmark_type": "96_unit_matrix_diagnosis",
                    "total_units_evaluated": len(unit_results),
                    "total_wall_time_s": round(time.time() - t_start_total, 2),
                    "unit_results": unit_results,
                }
                with open(OUTPUT_FILE, "w") as f:
                    json.dump(checkpoint_payload, f, indent=2)

    total_wall = time.time() - t_start_total
    print("\n" + "=" * 78)
    print(f"COMPLETED ALL 96 UNITS in {total_wall/60:.1f} minutes ({total_wall:.1f}s)")
    print("=" * 78)

    # Compute condition-level aggregates
    cond_summaries = {}
    for c in conditions:
        cid = c["id"]
        c_units = [u for u in unit_results if u["condition"] == cid]
        n = len(c_units)
        succ = sum(1 for u in c_units if u["success"])
        cond_summaries[cid] = {
            "group": c["group"],
            "name": c["name"],
            "total_units": n,
            "success_count": succ,
            "success_rate": round(succ / n, 4) if n > 0 else 0.0,
            "total_dependency_errors": sum(u["dependency_errors"] for u in c_units),
            "total_repeated_failures": sum(u["repeated_failures"] for u in c_units),
            "total_unwarranted_detours": sum(u["unwarranted_detours"] for u in c_units),
            "avg_steps": round(sum(u["continuation_steps"] for u in c_units) / n, 2) if n > 0 else 0.0,
            "avg_battery": round(sum(u["continuation_battery"] for u in c_units) / n, 2) if n > 0 else 0.0,
            "total_llm_calls": sum(u["total_llm_calls"] for u in c_units),
        }

    # Paired comparisons strictly on mutual successes
    def compute_paired_comparison(cond1_id: str, cond2_id: str) -> Dict[str, Any]:
        """Compares cond1 (e.g. S1_G) vs cond2 (e.g. S1_M0 or S1_H) strictly on mutually successful units."""
        pairs = []
        for scen in scenarios:
            sid = scen["scenario_id"]
            for r in range(1, num_runs + 1):
                u1 = next((u for u in unit_results if u["scenario_id"] == sid and u["condition"] == cond1_id and u["run_index"] == r), None)
                u2 = next((u for u in unit_results if u["scenario_id"] == sid and u["condition"] == cond2_id and u["run_index"] == r), None)
                if u1 and u2:
                    both_succeeded = u1["success"] and u2["success"]
                    pairs.append({
                        "scenario_id": sid,
                        "run_index": r,
                        "both_succeeded": both_succeeded,
                        "u1_success": u1["success"],
                        "u2_success": u2["success"],
                        "u1_battery": u1["continuation_battery"],
                        "u2_battery": u2["continuation_battery"],
                        "battery_diff_u1_minus_u2": u1["continuation_battery"] - u2["continuation_battery"] if both_succeeded else None,
                        "u1_steps": u1["continuation_steps"],
                        "u2_steps": u2["continuation_steps"],
                        "step_diff_u1_minus_u2": u1["continuation_steps"] - u2["continuation_steps"] if both_succeeded else None,
                    })
        mutual_pairs = [p for p in pairs if p["both_succeeded"]]
        n_mutual = len(mutual_pairs)
        avg_batt_diff = round(sum(p["battery_diff_u1_minus_u2"] for p in mutual_pairs) / n_mutual, 2) if n_mutual > 0 else 0.0
        avg_step_diff = round(sum(p["step_diff_u1_minus_u2"] for p in mutual_pairs) / n_mutual, 2) if n_mutual > 0 else 0.0
        return {
            "comparison": f"{cond1_id} vs {cond2_id}",
            "total_paired_runs": len(pairs),
            "mutual_success_runs": n_mutual,
            "avg_battery_diff_on_mutual_success (cond1 - cond2)": avg_batt_diff,
            "avg_step_diff_on_mutual_success (cond1 - cond2)": avg_step_diff,
            "mutual_pairs": mutual_pairs,
        }

    paired_g_vs_m0 = compute_paired_comparison("S1_G", "S1_M0")
    paired_g_vs_h = compute_paired_comparison("S1_G", "S1_H")
    paired_g_vs_m1 = compute_paired_comparison("S1_G", "S1_M1")

    final_payload = {
        "benchmark_type": "96_unit_matrix_diagnosis",
        "total_units_evaluated": len(unit_results),
        "total_wall_time_s": round(total_wall, 2),
        "condition_summaries": cond_summaries,
        "paired_comparisons": {
            "G_vs_M0": paired_g_vs_m0,
            "G_vs_H": paired_g_vs_h,
            "G_vs_M1": paired_g_vs_m1,
        },
        "unit_results": unit_results,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(final_payload, f, indent=2)

    print(f"\nFinal results saved to {OUTPUT_FILE}")
    print("\nCondition Summaries:")
    for cid, s in cond_summaries.items():
        print(f"  {cid:6s} | Success: {s['success_count']:2d}/{s['total_units']} ({s['success_rate']*100:5.1f}%) | DepErr: {s['total_dependency_errors']:2d} | RepFail: {s['total_repeated_failures']:2d} | Detour: {s['total_unwarranted_detours']:2d} | AvgBatt: {s['avg_battery']:4.1f}%")

    print("\nPaired Comparisons on Mutual Successes:")
    print(f"  G vs M0: Mutual Successes = {paired_g_vs_m0['mutual_success_runs']}/{paired_g_vs_m0['total_paired_runs']}, Avg Batt Diff = {paired_g_vs_m0['avg_battery_diff_on_mutual_success (cond1 - cond2)']}%")
    print(f"  G vs H : Mutual Successes = {paired_g_vs_h['mutual_success_runs']}/{paired_g_vs_h['total_paired_runs']}, Avg Batt Diff = {paired_g_vs_h['avg_battery_diff_on_mutual_success (cond1 - cond2)']}%")
    print(f"  G vs M1: Mutual Successes = {paired_g_vs_m1['mutual_success_runs']}/{paired_g_vs_m1['total_paired_runs']}, Avg Batt Diff = {paired_g_vs_m1['avg_battery_diff_on_mutual_success (cond1 - cond2)']}%")


if __name__ == "__main__":
    run_96_matrix()
