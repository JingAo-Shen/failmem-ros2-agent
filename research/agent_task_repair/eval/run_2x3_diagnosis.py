"""
Controlled 2x3 Matrix Diagnosis Runner for FailMem Stage 2.
Evaluates:
  Factor 1 (Planning Architecture): S0 (Flat Single-Step) vs S1 (Public Task Skeleton)
  Factor 2 (Memory Injection Scope): M0 (No Memory) vs M1 (Global Memory) vs M2 (Subgoal-Aware Memory)

Total units: 6 Scenarios x 6 Conditions = 36 Continuation Units.
All historical events are strictly generated via real tool execution on DeliveryTaskEnv.
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
from ..env.task_env import DeliveryTaskEnv
from ..eval.scorer import PilotScorer
from ..memory.subgoal_memory_adapter import SubgoalMemoryAdapter
from ..memory.baselines import B0_NoMemory


def generate_authentic_seed_history(
    scenario_type: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """
    Executes actual tool calls on DeliveryTaskEnv to produce authentic, verifiable Task 1 history.
    Returns: (pre_run_metrics, seed_step_history, seed_observation_events, shared_known_state)
    """
    if scenario_type == "door_north_blocked":
        # Task 1: Robot tries to navigate Corridor_North, gets blocked by door_north
        env_cfg = {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
            },
        }
        env = DeliveryTaskEnv(env_cfg)
        res = env.step("navigate", {"target_zone": "Corridor_North"})
        step_hist = [{
            "step": 1,
            "event_id": "evt_seed_t1_s01",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": res.to_dict(),
            "sim_time_s": env.sim_time_s,
            "battery": env.battery,
        }]
        pre_metrics = {"pre_sim_time_s": env.sim_time_s, "pre_battery_consumed": env.cumulative_battery_consumed}
        failure_event = {
            "event_id": "evt_seed_t1_s01",
            "task_id": "seed_t1",
            "action_name": "navigate",
            "target": "Corridor_North",
            "error_code": res.error_code or "DOORWAY_BLOCKED",
            "raw_message": res.message,
            "observation": res.observation,
            "sim_time": env.sim_time_s,
        }
        return pre_metrics, step_hist, [failure_event], {}

    elif scenario_type == "door_north_cleared_observed":
        # Task 1: Blocked navigation, followed by a shared observation event confirming FREE
        env_cfg = {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
            },
        }
        env = DeliveryTaskEnv(env_cfg)
        res1 = env.step("navigate", {"target_zone": "Corridor_North"})
        failure_event = {
            "event_id": "evt_seed_t1_s01",
            "task_id": "seed_t1",
            "action_name": "navigate",
            "target": "Corridor_North",
            "error_code": res1.error_code or "DOORWAY_BLOCKED",
            "raw_message": res1.message,
            "observation": res1.observation,
            "sim_time": env.sim_time_s,
        }
        # In Task 2 environment, door is unblocked; robot performs an authentic observe tool call
        env.doors["door_north"]["blocked"] = False
        res2 = env.step("observe", {"target": "door_north"})
        obs_event = {
            "event_id": "evt_seed_obs_shared",
            "observation": res2.observation,
            "sim_time": env.sim_time_s,
        }
        step_hist = [
            {"step": 1, "tool": "navigate", "params": {"target_zone": "Corridor_North"}, "result": res1.to_dict()},
            {"step": 2, "tool": "observe", "params": {"target": "door_north"}, "result": res2.to_dict()},
        ]
        pre_metrics = {"pre_sim_time_s": env.sim_time_s, "pre_battery_consumed": env.cumulative_battery_consumed}
        shared_known = {"door_north_state": "FREE"}
        return pre_metrics, step_hist, [failure_event, obs_event], shared_known

    elif scenario_type == "lab_badge_required":
        # Task 1: Robot navigates to Corridor_South, then tries to enter Lab_Secure without badge
        env_cfg = {
            "robot_start_location": "Corridor_South",
            "robot_start_battery": 100,
            "doors": {
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
        }
        env = DeliveryTaskEnv(env_cfg)
        res = env.step("navigate", {"target_zone": "Lab_Secure"})
        failure_event = {
            "event_id": "evt_seed_t1_s01",
            "task_id": "seed_t1",
            "action_name": "navigate",
            "target": "Lab_Secure",
            "error_code": res.error_code or "ACCESS_DENIED_NO_BADGE",
            "raw_message": res.message,
            "observation": res.observation,
            "sim_time": env.sim_time_s,
        }
        pre_metrics = {"pre_sim_time_s": env.sim_time_s, "pre_battery_consumed": env.cumulative_battery_consumed}
        step_hist = [{"step": 1, "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": res.to_dict()}]
        return pre_metrics, step_hist, [failure_event], {}

    elif scenario_type == "door_office_b_blocked":
        # Task 1: Robot in Corridor_North tries to navigate to Office_B, hits blocked doorway
        env_cfg = {
            "robot_start_location": "Corridor_North",
            "robot_start_battery": 100,
            "doors": {
                "door_office_b": {"blocked": True, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
        }
        env = DeliveryTaskEnv(env_cfg)
        res = env.step("navigate", {"target_zone": "Office_B"})
        failure_event = {
            "event_id": "evt_seed_t1_s01",
            "task_id": "seed_t1",
            "action_name": "navigate",
            "target": "Office_B",
            "error_code": res.error_code or "DOORWAY_BLOCKED",
            "raw_message": res.message,
            "observation": res.observation,
            "sim_time": env.sim_time_s,
        }
        pre_metrics = {"pre_sim_time_s": env.sim_time_s, "pre_battery_consumed": env.cumulative_battery_consumed}
        step_hist = [{"step": 1, "tool": "navigate", "params": {"target_zone": "Office_B"}, "result": res.to_dict()}]
        return pre_metrics, step_hist, [failure_event], {}

    else:
        # Default empty seed
        return {"pre_sim_time_s": 0.0, "pre_battery_consumed": 0}, [], [], {}


def build_adapter_from_seed_events(
    condition_code: str,  # e.g. 'S0_M0', 'S1_M2', etc.
    seed_events: List[Dict[str, Any]],
) -> Tuple[Any, bool]:
    """
    Constructs the memory adapter and task skeleton flag corresponding to the condition code.
    Condition Codes:
      S0_M0: Flat Plan, No Memory
      S0_M1: Flat Plan, Global Memory
      S0_M2: Flat Plan, Subgoal Memory
      S1_M0: Skeleton Plan, No Memory
      S1_M1: Skeleton Plan, Global Memory
      S1_M2: Skeleton Plan, Subgoal Memory
    """
    parts = condition_code.split("_")
    s_mode = parts[0]  # S0 or S1
    m_mode = parts[1]  # M0, M1, M2

    use_skeleton = (s_mode == "S1")

    if m_mode == "M0":
        adapter = SubgoalMemoryAdapter(injection_mode="none", store_mode="F")
    elif m_mode == "M1":
        adapter = SubgoalMemoryAdapter(injection_mode="global", store_mode="F")
    elif m_mode == "M2":
        adapter = SubgoalMemoryAdapter(injection_mode="subgoal", store_mode="F")
    else:
        raise ValueError(f"Unknown memory mode: {m_mode}")

    adapter.on_task_start("seed_t1", 0)
    for evt in seed_events:
        if "action_name" in evt:
            adapter.record_action_failure(
                event_id=evt["event_id"],
                task_id=evt.get("task_id", "seed_t1"),
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

    adapter.on_task_start("eval_t2", 1)
    return adapter, use_skeleton


def get_2x3_scenarios() -> List[Dict[str, Any]]:
    return [
        # 1. Cat 1: Persisting Door North Obstacle -> Deliver to Office_B
        {
            "scenario_id": "scen_1_persist_door_north",
            "name": "Scenario 1: Persisting Door North Obstacle -> Deliver to Office_B",
            "category": "Cat1_Persisting",
            "seed_type": "door_north_blocked",
            "task_spec": {
                "task_id": "eval_scen_1",
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
        # 2. Cat 2: Cleared Door North (Unobserved at Start) -> Deliver to Office_A
        {
            "scenario_id": "scen_2_cleared_door_north_unobs",
            "name": "Scenario 2: Cleared Door North (Unobserved) -> Deliver to Office_A",
            "category": "Cat2_Cleared_Unobs",
            "seed_type": "door_north_blocked",
            "task_spec": {
                "task_id": "eval_scen_2",
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
        # 3. Cat 2: Cleared Door North (Observed FREE via Tool Call) -> Deliver to Office_B
        {
            "scenario_id": "scen_3_cleared_door_north_obs",
            "name": "Scenario 3: Cleared Door North (Observed FREE) -> Deliver to Office_B",
            "category": "Cat2_Cleared_Obs",
            "seed_type": "door_north_cleared_observed",
            "task_spec": {
                "task_id": "eval_scen_3",
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
        # 4. Cat 3: Inapplicable Lab Badge History -> Deliver to Office_A
        {
            "scenario_id": "scen_4_inapp_lab_badge",
            "name": "Scenario 4: Inapplicable Lab Badge History -> Deliver to Office_A",
            "category": "Cat3_Inapplicable",
            "seed_type": "lab_badge_required",
            "task_spec": {
                "task_id": "eval_scen_4",
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
        # 5. Multi-Package Capacity Constraint (Capacity 2 with 3 Packages)
        {
            "scenario_id": "scen_5_capacity_constraint",
            "name": "Scenario 5: 3 Packages with Max Capacity 2 (Cannot pickup all at once)",
            "category": "Capacity_Constraint",
            "seed_type": "door_office_b_blocked",
            "task_spec": {
                "task_id": "eval_scen_5",
                "instruction": "Deliver pkg_1 to Alice in Office_A, pkg_2 to Charlie in Office_B, and pkg_3 to Alice in Office_A.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 100,
                    "max_inventory_capacity": 2,
                    "doors": {
                        "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                        "pkg_3": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                    },
                    "recipients": {
                        "Alice": {"room": "Office_A", "status": "available"},
                        "Charlie": {"room": "Office_B", "status": "available"},
                    },
                },
            },
        },
        # 6. Battery Budget & Charging Constraint (Forced Recharge Subgoal)
        {
            "scenario_id": "scen_6_battery_recharge",
            "name": "Scenario 6: Low Initial Battery (35%) Requiring Safe Delivery & Charging",
            "category": "Battery_Constraint",
            "seed_type": "door_north_blocked",
            "task_spec": {
                "task_id": "eval_scen_6",
                "instruction": "Deliver package pkg_heavy from Lobby to Charlie in Office_B.",
                "env_config": {
                    "robot_start_location": "Lobby",
                    "robot_start_battery": 35,
                    "doors": {
                        "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                        "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    },
                    "packages": {
                        "pkg_heavy": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                    },
                    "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                },
            },
        },
    ]


def check_dependency_errors(step_history: List[Dict[str, Any]]) -> int:
    """
    Counts task dependency violations:
      - deliver called when package is not in inventory
      - pickup called when inventory capacity is exceeded
      - deliver called in wrong room
    """
    dep_errors = 0
    for step in step_history:
        res = step.get("result", {})
        err = res.get("error_code") or res.get("status")
        if err in ("NOT_HOLDING_PACKAGE", "INVENTORY_FULL", "WRONG_LOCATION", "ACCESS_DENIED_NO_BADGE"):
            dep_errors += 1
    return dep_errors


def run_2x3_matrix_diagnosis(
    model_path: str = "/models/Qwen2.5-Coder-7B-Instruct",
    output_file: str = "research/agent_task_repair/results/matrix_2x3_diagnosis_results.json",
    device: str = "cuda",
    allow_fallback: bool = False,
):
    scenarios = get_2x3_scenarios()
    condition_codes = ["S0_M0", "S0_M1", "S0_M2", "S1_M0", "S1_M1", "S1_M2"]

    print("=" * 80)
    print("CONTROLLED 2x3 MATRIX DIAGNOSIS (36 CONTINUATION UNITS)")
    print(f"Model: {model_path} | Device: {device}")
    print(f"Scenarios: {len(scenarios)} | Conditions: {len(condition_codes)} | Total Units: {len(scenarios) * len(condition_codes)}")
    print("=" * 80)

    llm = LLMBackend(model_path=model_path, device=device, allow_fallback=allow_fallback)

    all_unit_results = []
    scenario_histories = {}
    t_global_start = time.time()

    # 1. Generate Authentic Tool-Executed Seed History for each scenario
    print("\n--- PHASE 1: GENERATING AUTHENTIC TOOL SEED HISTORIES ---")
    for scen in scenarios:
        scen_id = scen["scenario_id"]
        seed_type = scen["seed_type"]
        pre_metrics, seed_hist, seed_evts, shared_known = generate_authentic_seed_history(seed_type)
        scenario_histories[scen_id] = {
            "pre_metrics": pre_metrics,
            "seed_hist": seed_hist,
            "seed_events": seed_evts,
            "shared_known_state": shared_known,
        }
        print(f"  [{scen_id}] Seed Events Generated: {len(seed_evts)} | Pre-run Sim Time: {pre_metrics['pre_sim_time_s']}s | Pre-run Battery: {pre_metrics['pre_battery_consumed']}% | Shared Known: {shared_known}")

    # 2. Execute 36 Continuation Units
    print("\n--- PHASE 2: RUNNING 36 CONTINUATION UNITS ---")
    unit_idx = 0
    for scen in scenarios:
        scen_id = scen["scenario_id"]
        scen_name = scen["name"]
        cat = scen["category"]
        task_spec = scen["task_spec"]
        hist_data = scenario_histories[scen_id]

        print(f"\n>>> Scenario [{scen_id}]: {scen_name}")

        for cond in condition_codes:
            unit_idx += 1
            run_id = f"matrix_{cond}_{scen_id}"

            memory_adapter, use_skeleton = build_adapter_from_seed_events(
                condition_code=cond,
                seed_events=hist_data["seed_events"],
            )

            runner = AgentRunner(
                llm_backend=llm,
                memory_adapter=memory_adapter,
                max_tool_calls=15,
                max_llm_calls=15,
                max_sim_time_s=300.0,
                run_id=run_id,
                use_task_skeleton=use_skeleton,
            )

            t0 = time.time()
            task_res = runner.run_task(
                task_spec=copy.deepcopy(task_spec),
                task_index=1,
                seq_id=scen_id,
                initial_known_state=hist_data["shared_known_state"],
            )
            t1 = time.time()

            step_hist = task_res.get("step_history", [])
            step1_tool = step_hist[0]["tool"] if len(step_hist) > 0 else "NONE"
            step1_params = step_hist[0]["params"] if len(step_hist) > 0 else {}
            step1_decision = f"{step1_tool}({step1_params})"

            step1_success = step_hist[0]["result"]["success"] if len(step_hist) > 0 else False
            dep_errors = check_dependency_errors(step_hist)
            scorer_res = PilotScorer.score_sequence_results([task_res])

            # Extract retrieval audit summary
            retrieval_audits = []
            if hasattr(memory_adapter, "retrieval_audit_log"):
                retrieval_audits = list(memory_adapter.retrieval_audit_log)

            unit_summary = {
                "unit_index": unit_idx,
                "scenario_id": scen_id,
                "category": cat,
                "condition": cond,
                "planning_architecture": "S1_Skeleton" if use_skeleton else "S0_Flat",
                "memory_injection_scope": cond.split("_")[1],
                "success": task_res["success"],
                "dependency_errors": dep_errors,
                "repeated_failures": scorer_res["repeated_failures"],
                "unwarranted_detours": scorer_res["unwarranted_detour_count"],
                "step_count": task_res["step_count"],
                "battery_consumed": task_res["battery_consumed"],
                "continuation_sim_time_s": task_res["sim_time_s"],
                "pre_run_sim_time_s": hist_data["pre_metrics"]["pre_sim_time_s"],
                "pre_run_battery_consumed": hist_data["pre_metrics"]["pre_battery_consumed"],
                "wall_time_s": round(t1 - t0, 2),
                "step1_decision": step1_decision,
                "step1_success": step1_success,
                "total_llm_calls": task_res["llm_calls"],
                "retrieval_audits": retrieval_audits,
                "task_result": task_res,
            }
            all_unit_results.append(unit_summary)

            print(
                f"  [{unit_idx:02d}/36] {cond:<5s} -> Succ: {task_res['success']} | "
                f"DepErr: {dep_errors} | Step1: {step1_decision:35s} | "
                f"Steps: {task_res['step_count']:02d} | Bat: {task_res['battery_consumed']:02d}% | "
                f"Detours: {scorer_res['unwarranted_detour_count']} | RepFail: {scorer_res['repeated_failures']} | "
                f"Time: {t1-t0:.1f}s"
            )

    t_global_end = time.time()
    total_wall_s = round(t_global_end - t_global_start, 2)

    # 3. Aggregate 2x3 Matrix Summaries
    condition_summaries = {}
    for cond in condition_codes:
        c_runs = [u for u in all_unit_results if u["condition"] == cond]
        n = len(c_runs)
        n_succ = sum(1 for u in c_runs if u["success"])
        condition_summaries[cond] = {
            "total_units": n,
            "success_count": n_succ,
            "success_rate": round(n_succ / n, 4) if n > 0 else 0.0,
            "total_dependency_errors": sum(u["dependency_errors"] for u in c_runs),
            "total_repeated_failures": sum(u["repeated_failures"] for u in c_runs),
            "total_unwarranted_detours": sum(u["unwarranted_detours"] for u in c_runs),
            "avg_steps": round(sum(u["step_count"] for u in c_runs) / n, 2) if n > 0 else 0.0,
            "avg_battery": round(sum(u["battery_consumed"] for u in c_runs) / n, 2) if n > 0 else 0.0,
            "total_llm_calls": sum(u["total_llm_calls"] for u in c_runs),
        }

    # Factor-level aggregations
    factor_planning = {}
    for s_mode in ("S0", "S1"):
        s_runs = [u for u in all_unit_results if u["condition"].startswith(s_mode)]
        n = len(s_runs)
        n_succ = sum(1 for u in s_runs if u["success"])
        factor_planning[s_mode] = {
            "total_units": n,
            "success_rate": round(n_succ / n, 4) if n > 0 else 0.0,
            "total_dependency_errors": sum(u["dependency_errors"] for u in s_runs),
            "total_repeated_failures": sum(u["repeated_failures"] for u in s_runs),
        }

    factor_memory = {}
    for m_mode in ("M0", "M1", "M2"):
        m_runs = [u for u in all_unit_results if u["condition"].endswith(m_mode)]
        n = len(m_runs)
        n_succ = sum(1 for u in m_runs if u["success"])
        factor_memory[m_mode] = {
            "total_units": n,
            "success_rate": round(n_succ / n, 4) if n > 0 else 0.0,
            "total_dependency_errors": sum(u["dependency_errors"] for u in m_runs),
            "total_repeated_failures": sum(u["repeated_failures"] for u in m_runs),
        }

    output_payload = {
        "benchmark_type": "controlled_2x3_matrix_diagnosis",
        "total_units_evaluated": len(all_unit_results),
        "total_wall_time_s": total_wall_s,
        "condition_summaries": condition_summaries,
        "factor_planning": factor_planning,
        "factor_memory": factor_memory,
        "unit_results": all_unit_results,
    }

    out_p = Path(output_file)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"2x3 MATRIX DIAGNOSIS COMPLETED IN {total_wall_s}s ({total_wall_s/60:.1f} min)")
    print(f"Results saved to: {out_p.resolve()}")
    print("=" * 80)
    print(f"{'Condition':<8} | {'SR':<8} | {'DepErrors':<10} | {'RepFail':<8} | {'Detour':<8} | {'AvgSteps':<9} | {'AvgBat':<8} | {'LLMCalls':<8}")
    print("-" * 85)
    for cond in condition_codes:
        s = condition_summaries[cond]
        print(
            f"{cond:<8} | {s['success_count']}/{s['total_units']} ({s['success_rate']*100:.1f}%) | "
            f"{s['total_dependency_errors']:<10} | {s['total_repeated_failures']:<8} | {s['total_unwarranted_detours']:<8} | "
            f"{s['avg_steps']:<9.1f} | {s['avg_battery']:<8.1f}% | {s['total_llm_calls']:<8}"
        )
    print("=" * 80)

    return output_payload


if __name__ == "__main__":
    run_2x3_matrix_diagnosis()
