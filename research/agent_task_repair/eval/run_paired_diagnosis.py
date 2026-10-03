"""
Paired Memory Intervention Diagnosis for FailMem Stage 2.
Evaluates 5 memory mechanisms (B0, B1, B2, B3, F) across 6 strictly controlled
intervention scenarios (30 total paired evaluation units) initialized from
identical tool-generated failure memory states.
"""
import sys
import os
import json
import time
import copy
from pathlib import Path
from typing import Dict, Any, List

from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..env.task_env import DeliveryTaskEnv
from ..eval.scorer import PilotScorer
from ..memory.baselines import (
    B0_NoMemory,
    B1_UnstructuredNLMemory,
    B2_StaticConditionalMemory,
    B3_DecayMemory,
    F_ConditionAwareMemory,
    BaseMemoryAdapter,
)
from ..memory.memory_store import EpistemicLevel, MemoryStatus


def setup_memory_checkpoint(
    method_name: str,
    scenario_type: str,
    known_obs_before: Dict[str, Any] = None,
) -> BaseMemoryAdapter:
    """
    Constructs a memory adapter pre-populated with a standardized, tool-generated Task 1 failure.
    """
    if method_name == "B0":
        adapter = B0_NoMemory()
    elif method_name == "B1":
        adapter = B1_UnstructuredNLMemory()
    elif method_name == "B2":
        adapter = B2_StaticConditionalMemory()
    elif method_name == "B3":
        adapter = B3_DecayMemory(ttl_tasks=1)
    elif method_name == "F":
        adapter = F_ConditionAwareMemory()
    else:
        raise ValueError(f"Unknown method: {method_name}")

    adapter.on_task_start(task_id="seed_task_t1", task_index=0)

    # Seed failure according to scenario type
    if scenario_type in ("door_north_blocked", "door_north_stale_cleared", "door_north_stale_observed"):
        # Simulated Task 1 failure: navigate(Corridor_North) failed because door_north is blocked
        adapter.record_action_failure(
            event_id="evt_seed_t1_s01_fail",
            task_id="seed_task_t1",
            action_name="navigate",
            target="Corridor_North",
            error_code="DOORWAY_BLOCKED",
            raw_message="Navigation to Corridor_North failed: Door door_north is blocked by obstacle.",
            observation={"door": "door_north", "passage_state": "OCCUPIED"},
            sim_time=8.0,
        )
    elif scenario_type == "lab_badge_required":
        # Simulated Task 1 failure: navigate(Lab_Secure) failed due to missing badge
        adapter.record_action_failure(
            event_id="evt_seed_t1_s01_fail",
            task_id="seed_task_t1",
            action_name="navigate",
            target="Lab_Secure",
            error_code="ACCESS_DENIED_NO_BADGE",
            raw_message="Access denied: door_lab requires security_badge.",
            observation={"door": "door_lab", "access_status": "DENIED", "required_credential": "security_badge"},
            sim_time=14.0,
        )
    elif scenario_type == "recipient_busy":
        # Simulated Task 1 failure: deliver to Alice failed because Alice was in meeting
        adapter.record_action_failure(
            event_id="evt_seed_t1_s01_fail",
            task_id="seed_task_t1",
            action_name="deliver",
            target="Alice",
            error_code="RECIPIENT_BUSY",
            raw_message="Delivery failed: Recipient Alice is currently in_meeting.",
            observation={"recipient": "Alice", "recipient_status": "in_meeting"},
            sim_time=20.0,
        )

    # If this scenario includes a subsequent observation before Task 2:
    if known_obs_before:
        adapter.record_observation(
            event_id="evt_seed_obs_update",
            observation=known_obs_before,
            sim_time=30.0,
        )

    # Transition adapter to Task 2 (task_index=1)
    adapter.on_task_start(task_id="eval_task_t2", task_index=1)
    return adapter


def get_paired_intervention_scenarios() -> List[Dict[str, Any]]:
    return [
        # -------------------------------------------------------------
        # Category 1: Persisting Constraint (Cat1_Valid)
        # -------------------------------------------------------------
        {
            "scenario_id": "interv_c1_door_north_persist_office_b",
            "category": "Cat1_Valid",
            "name": "Cat1: Persisting Door North Obstacle -> Deliver to Office_B",
            "seed_type": "door_north_blocked",
            "known_obs_before": None,
            "task_spec": {
                "task_id": "eval_c1_t2_office_b",
                "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 90,
                    "doors": {
                        "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                    },
                    "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                },
            },
        },
        {
            "scenario_id": "interv_c1_door_north_persist_office_a",
            "category": "Cat1_Valid",
            "name": "Cat1: Persisting Door North Obstacle -> Deliver to Office_A",
            "seed_type": "door_north_blocked",
            "known_obs_before": None,
            "task_spec": {
                "task_id": "eval_c1_t2_office_a",
                "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 90,
                    "doors": {
                        "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                    },
                    "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                },
            },
        },
        # -------------------------------------------------------------
        # Category 2: Stale Constraint (Cat2_Stale)
        # -------------------------------------------------------------
        {
            "scenario_id": "interv_c2_door_north_cleared_unobserved",
            "category": "Cat2_Stale",
            "name": "Cat2: Door North Cleared (Unobserved at Start) -> Deliver to Office_B",
            "seed_type": "door_north_stale_cleared",
            "known_obs_before": None,
            "task_spec": {
                "task_id": "eval_c2_t2_unobs",
                "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 90,
                    "doors": {
                        "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                    },
                    "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                },
            },
        },
        {
            "scenario_id": "interv_c2_door_north_cleared_observed",
            "category": "Cat2_Stale",
            "name": "Cat2: Door North Cleared (Observed FREE) -> Deliver to Office_A",
            "seed_type": "door_north_stale_observed",
            "known_obs_before": {"door": "door_north", "passage_state": "FREE"},
            "task_spec": {
                "task_id": "eval_c2_t2_obs",
                "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 90,
                    "doors": {
                        "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                    },
                    "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                },
            },
        },
        # -------------------------------------------------------------
        # Category 3: Inapplicable Constraint (Cat3_Inapplicable)
        # -------------------------------------------------------------
        {
            "scenario_id": "interv_c3_lab_badge_to_office_a",
            "category": "Cat3_Inapplicable",
            "name": "Cat3: Lab Badge Memory -> Deliver to Office_A (No Badge Needed)",
            "seed_type": "lab_badge_required",
            "known_obs_before": None,
            "task_spec": {
                "task_id": "eval_c3_t2_office_a",
                "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 90,
                    "doors": {
                        "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                        "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                    },
                    "packages": {
                        "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                    },
                    "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                },
            },
        },
        {
            "scenario_id": "interv_c3_alice_busy_to_charlie_office_b",
            "category": "Cat3_Inapplicable",
            "name": "Cat3: Alice Busy Memory -> Deliver to Charlie in Office_B",
            "seed_type": "recipient_busy",
            "known_obs_before": None,
            "task_spec": {
                "task_id": "eval_c3_t2_charlie_b",
                "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 90,
                    "doors": {
                        "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                    },
                    "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                },
            },
        },
    ]


def run_paired_diagnosis(
    model_path: str = "/models/Qwen2.5-Coder-7B-Instruct",
    output_file: str = "research/agent_task_repair/results/paired_diagnosis_results.json",
    device: str = "cuda",
    allow_fallback: bool = False,
):
    scenarios = get_paired_intervention_scenarios()
    methods = ["B0", "B1", "B2", "B3", "F"]

    print("=" * 80)
    print(f"PAIRED MEMORY INTERVENTION DIAGNOSIS (30 EVALUATION UNITS)")
    print(f"Model: {model_path} | Device: {device}")
    print(f"Scenarios: {len(scenarios)} | Methods: {len(methods)} | Total Units: {len(scenarios) * len(methods)}")
    print("=" * 80)

    llm = LLMBackend(model_path=model_path, device=device, allow_fallback=allow_fallback)

    all_unit_results = []
    t_global_start = time.time()

    unit_idx = 0
    for scen in scenarios:
        scen_id = scen["scenario_id"]
        scen_name = scen["name"]
        cat = scen["category"]
        seed_type = scen["seed_type"]
        known_obs_before = scen.get("known_obs_before")
        task_spec = scen["task_spec"]

        print(f"\n>>> Scenario [{scen_id}]: {scen_name}")

        for m_name in methods:
            unit_idx += 1
            run_id = f"interv_{m_name}_{scen_id}"
            
            # Setup pre-populated memory adapter
            memory_adapter = setup_memory_checkpoint(
                method_name=m_name,
                scenario_type=seed_type,
                known_obs_before=known_obs_before,
            )

            runner = AgentRunner(
                llm_backend=llm,
                memory_adapter=memory_adapter,
                max_tool_calls=15,
                max_llm_calls=15,
                max_sim_time_s=300.0,
                run_id=run_id,
            )

            t0 = time.time()
            task_res = runner.run_task(
                task_spec=copy.deepcopy(task_spec),
                task_index=1,
                seq_id=scen_id,
            )
            t1 = time.time()

            # Extract Step 1 action and first differing decision
            step_hist = task_res.get("step_history", [])
            step1_tool = step_hist[0]["tool"] if len(step_hist) > 0 else "NONE"
            step1_params = step_hist[0]["params"] if len(step_hist) > 0 else {}
            step1_decision = f"{step1_tool}({step1_params})"

            # Check if Step 1 avoided obstacle or collided
            step1_success = step_hist[0]["result"]["success"] if len(step_hist) > 0 else False
            step1_error = step_hist[0]["result"].get("error_code") if len(step_hist) > 0 else ""

            # Check retrieved memories at Step 1
            step1_retrieved = []
            if len(task_res.get("llm_traces", [])) > 0:
                step1_retrieved = task_res["llm_traces"][0].get("retrieved_memories", [])

            # Compute PilotScorer metrics on this task
            scorer_res = PilotScorer.score_sequence_results([task_res])

            unit_summary = {
                "unit_index": unit_idx,
                "scenario_id": scen_id,
                "category": cat,
                "method": m_name,
                "success": task_res["success"],
                "step_count": task_res["step_count"],
                "battery_consumed": task_res["battery_consumed"],
                "sim_time_s": task_res["sim_time_s"],
                "wall_time_s": round(t1 - t0, 2),
                "step1_decision": step1_decision,
                "step1_success": step1_success,
                "step1_error": step1_error,
                "step1_retrieved_memories": step1_retrieved,
                "repeated_failures": scorer_res["repeated_failures"],
                "unwarranted_detours": scorer_res["unwarranted_detour_count"],
                "hard_violations": scorer_res["hard_violation_events"],
                "parse_errors": scorer_res["parse_error_events"],
                "total_llm_calls": task_res["llm_calls"],
                "task_result": task_res,
            }
            all_unit_results.append(unit_summary)

            print(
                f"  [{unit_idx:02d}/30] {m_name:2s} -> Success: {task_res['success']} | "
                f"Step 1: {step1_decision:35s} | Step1 Succ: {step1_success} | "
                f"Steps: {task_res['step_count']:02d} | Bat: {task_res['battery_consumed']:02d} | "
                f"Detours: {scorer_res['unwarranted_detour_count']} | RepFail: {scorer_res['repeated_failures']} | "
                f"Time: {t1-t0:.1f}s"
            )

    t_global_end = time.time()
    total_wall_s = round(t_global_end - t_global_start, 2)

    # Aggregate summaries by Method and Category
    method_summaries = {}
    for m in methods:
        m_runs = [u for u in all_unit_results if u["method"] == m]
        n = len(m_runs)
        n_succ = sum(1 for u in m_runs if u["success"])
        method_summaries[m] = {
            "total_units": n,
            "success_count": n_succ,
            "success_rate": round(n_succ / n, 4) if n > 0 else 0.0,
            "total_repeated_failures": sum(u["repeated_failures"] for u in m_runs),
            "total_unwarranted_detours": sum(u["unwarranted_detours"] for u in m_runs),
            "total_hard_violations": sum(u["hard_violations"] for u in m_runs),
            "avg_steps": round(sum(u["step_count"] for u in m_runs) / n, 2) if n > 0 else 0.0,
            "avg_battery": round(sum(u["battery_consumed"] for u in m_runs) / n, 2) if n > 0 else 0.0,
            "total_llm_calls": sum(u["total_llm_calls"] for u in m_runs),
        }

    output_payload = {
        "benchmark_type": "paired_memory_intervention_diagnosis",
        "total_units_evaluated": len(all_unit_results),
        "total_wall_time_s": total_wall_s,
        "method_summaries": method_summaries,
        "unit_results": all_unit_results,
    }

    out_p = Path(output_file)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"PAIRED DIAGNOSIS COMPLETED IN {total_wall_s}s ({total_wall_s/60:.1f} min)")
    print(f"Results saved to: {out_p.resolve()}")
    print("=" * 80)
    print(f"{'Method':<6} | {'SR':<8} | {'RepFail':<8} | {'Detour':<8} | {'Viol':<6} | {'AvgSteps':<9} | {'AvgBat':<8} | {'LLMCalls':<8}")
    print("-" * 75)
    for m in methods:
        s = method_summaries[m]
        print(
            f"{m:<6} | {s['success_count']}/{s['total_units']} ({s['success_rate']*100:.1f}%) | "
            f"{s['total_repeated_failures']:<8} | {s['total_unwarranted_detours']:<8} | "
            f"{s['total_hard_violations']:<6} | {s['avg_steps']:<9.1f} | {s['avg_battery']:<8.1f} | {s['total_llm_calls']:<8}"
        )
    print("=" * 80)

    return output_payload


if __name__ == "__main__":
    run_paired_diagnosis()
