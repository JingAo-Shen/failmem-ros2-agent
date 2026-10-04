"""
96-Run Held-Out Controlled Factorial Diagnosis Runner (FailMem Stage 2).
Evaluates 4 Groups across 24 Held-Out Tasks (4 Categories x 3 Relevance x 2 Instances = 24 Tasks):
  - Group A (S1_M0): Baseline Single-Step Skeleton Planner, No Memory
  - Group B (Agent_B): Stateful Agent, No Memory
  - Group C (Agent_C): Stateful Agent + Shared Historical Facts
  - Group D (Agent_D): Stateful Agent + Verified Repair Memory

Outputs structured empirical results to:
  research/agent_task_repair/results/heldout_96_diagnosis_results.json
"""
import sys
import os
import json
import time
import copy
import torch
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..agent.stateful_runner import StatefulAgentRunner
from ..agent.planner import MAP_ADJACENCY
from ..memory.subgoal_memory_adapter import SubgoalMemoryAdapter
from ..memory.repair_memory import RepairMemoryStore, VerificationStatus
from ..env.heldout_tasks_24 import get_24_heldout_tasks, verify_heldout_task_feasibility
from ..env.diagnostic_scenarios_8 import generate_authentic_seed_history


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "heldout_96_diagnosis_results.json"


def create_repair_memory_store(
    seed_type: str,
    shared_known_state: Dict[str, Any],
    historical_failure_events: List[Dict[str, Any]],
) -> RepairMemoryStore:
    """Instantiates verified RepairMemoryStore with authentic template for Group D."""
    store = RepairMemoryStore()

    if seed_type in ("door_north_blocked", "door_north_cleared_observed"):
        store.record_repair_experience(
            memory_id="mem_repair_door_north",
            failure_signature={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
            applicability={"origin": "Lobby", "blocked_entity": "door_north"},
            required_facts=["door_north_state == OCCUPIED"],
            repair_steps=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
            expected_effects=["at_location(Corridor_South)"],
            evidence_refs=["evt_seed_t1_s01"],
            verification_evidence={"verified": True, "evidence_refs": ["evt_seed_t1_s01"]},
            invalidation_conditions={"door_north_state": "FREE"},
            verification_status=VerificationStatus.VERIFIED,
            source_task_id="seed_t1",
        )
        if seed_type == "door_north_cleared_observed":
            store.update_with_observation(shared_known_state)

    elif seed_type == "lab_badge_required":
        store.record_repair_experience(
            memory_id="mem_repair_lab_badge",
            failure_signature={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED"},
            applicability={"target": "Lab_Secure"},
            required_facts=["security_badge_required == True"],
            repair_steps=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
            expected_effects=["has_credential(security_badge)"],
            evidence_refs=["evt_seed_t1_s01"],
            verification_evidence={"verified": True, "evidence_refs": ["evt_seed_t1_s01"]},
            invalidation_conditions={"has_credential": "security_badge"},
            verification_status=VerificationStatus.VERIFIED,
            source_task_id="seed_t1",
        )

    elif seed_type == "unrelated_door_office_b_blocked":
        store.record_repair_experience(
            memory_id="mem_repair_door_office_b",
            failure_signature={"action_name": "navigate", "target": "Office_B", "error_code": "DOORWAY_BLOCKED"},
            applicability={"origin": "Corridor_North", "target": "Office_B"},
            required_facts=["door_office_b_state == OCCUPIED"],
            repair_steps=[{"action": "observe", "params": {"target": "door_office_b"}}],
            expected_effects=["door_office_b_checked"],
            evidence_refs=["evt_seed_t1_s01"],
            verification_evidence={"verified": True, "evidence_refs": ["evt_seed_t1_s01"]},
            invalidation_conditions={"door_office_b_state": "FREE"},
            verification_status=VerificationStatus.VERIFIED,
            source_task_id="seed_t1",
        )

    return store


def run_heldout_96_diagnosis():
    print("=" * 78)
    print("STARTING 96-RUN HELDOUT CONTROLLED FACTORIAL DIAGNOSIS (4 GROUPS x 24 TASKS)")
    print("Model: /models/Qwen2.5-Coder-7B-Instruct (GPU CUDA, Deterministic)")
    print("=" * 78)

    # 1. First verify feasibility of all 24 heldout tasks
    tasks = get_24_heldout_tasks()
    print(f"\n[Verification] Verifying oracle feasibility of {len(tasks)} held-out tasks...")
    for t in tasks:
        ok, msg, _ = verify_heldout_task_feasibility(t)
        if not ok:
            raise RuntimeError(f"Held-out task {t['task_id']} failed feasibility check: {msg}")
    print("[Verification] All 24 heldout tasks 100% verified solvable by oracle.\n")

    groups = [
        {"id": "Group_A_S1_M0", "name": "Group A: S1_M0 Baseline Skeleton (No Memory)"},
        {"id": "Group_B_Agent_B", "name": "Group B: Stateful Agent (No Memory)"},
        {"id": "Group_C_Agent_C", "name": "Group C: Stateful Agent + Shared Facts"},
        {"id": "Group_D_Agent_D", "name": "Group D: Stateful Agent + Repair Memory"},
    ]

    llm = LLMBackend(model_path="/models/Qwen2.5-Coder-7B-Instruct", device="cuda")
    all_group_results = {}
    t_start_total = time.time()

    for grp in groups:
        grp_id = grp["id"]
        grp_name = grp["name"]
        print(f"\n>>> Running Evaluation on: {grp_name}")
        t_grp_start = time.time()
        task_runs = []

        for t_idx, task in enumerate(tasks, start=1):
            tid = task["task_id"]
            cat = task["category"]
            relevance = task["relevance"]
            seed_type = task["seed_type"]
            t_task_start = time.time()

            # Authentic seed history generation
            pre_metrics, seed_hist, seed_evts, shared_known = generate_authentic_seed_history(seed_type)

            task_spec = {
                "task_id": tid,
                "instruction": task["instruction"],
                "env_config": copy.deepcopy(task["env_config"]),
            }

            if grp_id == "Group_A_S1_M0":
                # Single-step skeleton baseline
                adapter = SubgoalMemoryAdapter(injection_mode="none", store_mode="F", adjacency_map=MAP_ADJACENCY)
                adapter.on_task_start(tid, 0)
                runner = AgentRunner(
                    llm_backend=llm,
                    memory_adapter=adapter,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=f"run_grpA_{tid}",
                    use_task_skeleton=True,
                )
                res = runner.run_task(task_spec, task_index=0, seq_id="heldout_bench")

            elif grp_id == "Group_B_Agent_B":
                # Stateful agent without memory
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    adjacency_map=MAP_ADJACENCY,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=f"run_grpB_{tid}",
                    include_historical_facts=False,
                    repair_memory_store=None,
                )
                res = runner.run_task(
                    task_spec=task_spec,
                    task_index=0,
                    seq_id="heldout_bench",
                    initial_known_state={},
                    historical_failure_events=[],
                )

            elif grp_id == "Group_C_Agent_C":
                # Stateful agent + shared historical facts
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    adjacency_map=MAP_ADJACENCY,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=f"run_grpC_{tid}",
                    include_historical_facts=True,
                    repair_memory_store=None,
                )
                res = runner.run_task(
                    task_spec=task_spec,
                    task_index=0,
                    seq_id="heldout_bench",
                    initial_known_state=shared_known,
                    historical_failure_events=seed_evts,
                )

            elif grp_id == "Group_D_Agent_D":
                # Stateful agent + verified repair memory
                rmem_store = create_repair_memory_store(seed_type, shared_known, seed_evts)
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    adjacency_map=MAP_ADJACENCY,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=f"run_grpD_{tid}",
                    include_historical_facts=True,
                    repair_memory_store=rmem_store,
                )
                res = runner.run_task(
                    task_spec=task_spec,
                    task_index=0,
                    seq_id="heldout_bench",
                    initial_known_state=shared_known,
                    historical_failure_events=seed_evts,
                )

            t_task_wall = time.time() - t_task_start
            success = bool(res.get("success", False))
            steps = len(res.get("step_history", []))
            cont_sim_time = res.get("sim_time_s", 0.0)
            cont_batt = res.get("battery_consumed", 0)
            pre_sim_time = pre_metrics.get("pre_sim_time_s", 0.0)
            pre_batt = pre_metrics.get("pre_battery_consumed", 0)

            # Determine termination reason
            term_reason = "SUCCESS" if success else "MAX_STEPS_OR_VIOLATION"
            if not success:
                if any("DEAD_LOOP" in str(v) for v in res.get("constraint_violations", [])):
                    term_reason = "DEADLOCK_LOOP"
                elif res.get("battery_consumed", 0) >= 100 or res.get("final_battery", 100) <= 0:
                    term_reason = "OUT_OF_BATTERY"
                elif res.get("llm_calls", 0) >= 20:
                    term_reason = "MAX_LLM_CALLS"

            task_runs.append({
                "task_id": tid,
                "category": cat,
                "relevance": relevance,
                "seed_type": seed_type,
                "success": success,
                "termination_reason": term_reason,
                "continuation_steps": steps,
                "continuation_sim_time_s": cont_sim_time,
                "continuation_battery_consumed": cont_batt,
                "pre_sim_time_s": pre_sim_time,
                "pre_battery_consumed": pre_batt,
                "total_sim_time_s": round(pre_sim_time + cont_sim_time, 2),
                "total_battery_consumed": pre_batt + cont_batt,
                "llm_calls": res.get("llm_calls", 0),
                "wall_time_s": round(t_task_wall, 2),
                "plan_revisions": res.get("plan_revisions", 0),
                "constraint_violations": res.get("constraint_violations", []),
            })

            print(f"  [{t_idx:2d}/24] {tid:36s} | Succ={str(success):5s} | Steps={steps:2d} | Batt={cont_batt:2d}% | Wall={t_task_wall:4.1f}s | Term={term_reason}")

        t_grp_wall = time.time() - t_grp_start
        n_tasks = len(task_runs)
        n_succ = sum(1 for r in task_runs if r["success"])
        succ_rate = round(n_succ / n_tasks, 4)

        # Aggregate breakdowns
        cat_breakdown = {}
        for c in sorted(list(set(r["category"] for r in task_runs))):
            c_runs = [r for r in task_runs if r["category"] == c]
            c_succ = sum(1 for r in c_runs if r["success"])
            cat_breakdown[c] = {
                "total": len(c_runs),
                "success": c_succ,
                "success_rate": round(c_succ / len(c_runs), 4),
            }

        rel_breakdown = {}
        for rel in sorted(list(set(r["relevance"] for r in task_runs))):
            r_runs = [r for r in task_runs if r["relevance"] == rel]
            r_succ = sum(1 for r in r_runs if r["success"])
            rel_breakdown[rel] = {
                "total": len(r_runs),
                "success": r_succ,
                "success_rate": round(r_succ / len(r_runs), 4),
            }

        grp_summary = {
            "group_id": grp_id,
            "group_name": grp_name,
            "total_tasks": n_tasks,
            "success_count": n_succ,
            "success_rate": succ_rate,
            "mean_continuation_steps": round(sum(r["continuation_steps"] for r in task_runs) / n_tasks, 2),
            "mean_continuation_sim_time_s": round(sum(r["continuation_sim_time_s"] for r in task_runs) / n_tasks, 2),
            "mean_continuation_battery": round(sum(r["continuation_battery_consumed"] for r in task_runs) / n_tasks, 2),
            "mean_llm_calls": round(sum(r["llm_calls"] for r in task_runs) / n_tasks, 2),
            "total_wall_time_s": round(t_grp_wall, 2),
            "category_breakdown": cat_breakdown,
            "relevance_breakdown": rel_breakdown,
            "task_runs": task_runs,
        }
        all_group_results[grp_id] = grp_summary
        print(f"--> Summary {grp_id}: Success {n_succ}/{n_tasks} ({succ_rate*100:.1f}%), Mean Steps={grp_summary['mean_continuation_steps']}, Mean Batt={grp_summary['mean_continuation_battery']}%")

    # 4. Factorial & Paired Mutual-Success Cost Analysis
    paired_comparisons = {}
    pairings = [
        ("Group_B_Agent_B", "Group_A_S1_M0", "Factor: Stateful Architecture vs Single-Step Skeleton (B - A)"),
        ("Group_C_Agent_C", "Group_B_Agent_B", "Factor: Shared Facts vs Stateful Agent (C - B)"),
        ("Group_D_Agent_D", "Group_C_Agent_C", "Factor: Verified Repair Memory vs Facts (D - C)"),
        ("Group_D_Agent_D", "Group_B_Agent_B", "Factor: Total Net Memory System Gain (D - B)"),
        ("Group_D_Agent_D", "Group_A_S1_M0", "Factor: Full Stateful Agent + Memory vs Skeleton (D - A)"),
    ]

    for gid_x, gid_y, factor_name in pairings:
        runs_x = {r["task_id"]: r for r in all_group_results[gid_x]["task_runs"]}
        runs_y = {r["task_id"]: r for r in all_group_results[gid_y]["task_runs"]}

        mutual_tasks = [tid for tid in runs_x if runs_x[tid]["success"] and runs_y[tid]["success"]]
        
        delta_steps = []
        delta_battery = []
        delta_sim_time = []
        delta_llm_calls = []

        for tid in mutual_tasks:
            rx = runs_x[tid]
            ry = runs_y[tid]
            delta_steps.append(rx["continuation_steps"] - ry["continuation_steps"])
            delta_battery.append(rx["continuation_battery_consumed"] - ry["continuation_battery_consumed"])
            delta_sim_time.append(rx["continuation_sim_time_s"] - ry["continuation_sim_time_s"])
            delta_llm_calls.append(rx["llm_calls"] - ry["llm_calls"])

        n_mut = len(mutual_tasks)
        paired_comparisons[f"{gid_x}_vs_{gid_y}"] = {
            "factor_name": factor_name,
            "group_x": gid_x,
            "group_y": gid_y,
            "success_rate_x": all_group_results[gid_x]["success_rate"],
            "success_rate_y": all_group_results[gid_y]["success_rate"],
            "success_rate_diff": round(all_group_results[gid_x]["success_rate"] - all_group_results[gid_y]["success_rate"], 4),
            "mutual_success_task_count": n_mut,
            "mutual_success_task_ids": mutual_tasks,
            "mean_delta_continuation_steps": round(sum(delta_steps) / max(1, n_mut), 2) if n_mut > 0 else 0.0,
            "mean_delta_continuation_battery": round(sum(delta_battery) / max(1, n_mut), 2) if n_mut > 0 else 0.0,
            "mean_delta_continuation_sim_time_s": round(sum(delta_sim_time) / max(1, n_mut), 2) if n_mut > 0 else 0.0,
            "mean_delta_llm_calls": round(sum(delta_llm_calls) / max(1, n_mut), 2) if n_mut > 0 else 0.0,
        }

    payload = {
        "benchmark": "heldout_96_controlled_factorial_diagnosis",
        "total_runs": 96,
        "total_wall_time_s": round(time.time() - t_start_total, 2),
        "group_summaries": all_group_results,
        "paired_comparisons": paired_comparisons,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("\n" + "=" * 78)
    print("96-RUN HELDOUT DIAGNOSIS COMPLETED.")
    print(f"Results saved to {OUTPUT_FILE}")
    print("=" * 78)


if __name__ == "__main__":
    run_heldout_96_diagnosis()
