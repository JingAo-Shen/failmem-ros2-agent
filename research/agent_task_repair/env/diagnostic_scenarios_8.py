"""
8 Diagnostic Scenarios & Feasibility Verifier for FailMem Stage 2.
Evaluates Explicit Subgoal-Scoped Memory (G) vs Phase Heuristic Filtering (H)
across 8 distinct challenge dimensions:
  1. scen_1_persist_door_north: Persisting obstacle requiring detour
  2. scen_2_cleared_door_north_unobs: Stale obstacle cleared but unobserved
  3. scen_3_cleared_door_north_obs: Stale obstacle cleared and observed FREE (invalidation)
  4. scen_4_lab_badge_required: Access credential precondition
  5. scen_5_capacity_constraint: Multi-package delivery requiring multi-trip (cap=2, 3 pkgs)
  6. scen_6_multi_target_interleave: Interleaving delivery when holding item while item on floor
  7. scen_7_mandatory_battery_charging: True mandatory recharge (start batt 10% < path cost 17%)
  8. scen_8_irrelevant_memory_distraction: Memory of past failure in unrelated wing

Includes authentic tool seed generator and programmatic feasibility verifier.
"""
from typing import Dict, Any, List, Tuple
import copy
from .task_env import DeliveryTaskEnv
from .tools import StatusCode


def get_8_diagnostic_scenarios() -> List[Dict[str, Any]]:
    """Returns the complete specifications for the 8 diagnostic scenarios."""
    return [
        # =====================================================================
        # 1. Persisting Doorway Obstacle (Detour Required)
        # =====================================================================
        {
            "scenario_id": "scen_1_persist_door_north",
            "name": "Persisting Obstacle at Door North",
            "dimension": "Detour & Persistence",
            "seed_type": "door_north_blocked",
            "task_instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 100,
                "doors": {
                    "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
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

        # =====================================================================
        # 2. Recovered Obstacle (Unobserved at Start)
        # =====================================================================
        {
            "scenario_id": "scen_2_cleared_door_north_unobs",
            "name": "Recovered Door North (Unobserved, Stale Memory)",
            "dimension": "Stale Memory & Blind Detour",
            "seed_type": "door_north_blocked",
            "task_instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
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

        # =====================================================================
        # 3. Recovered Obstacle (Observed FREE Prior to Run)
        # =====================================================================
        {
            "scenario_id": "scen_3_cleared_door_north_obs",
            "name": "Recovered Door North (Observed FREE in Shared State)",
            "dimension": "Active Invalidation",
            "seed_type": "door_north_cleared_observed",
            "task_instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
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

        # =====================================================================
        # 4. Access Credential Precondition (Badge Required)
        # =====================================================================
        {
            "scenario_id": "scen_4_lab_badge_required",
            "name": "Access Credential Required for Lab Secure",
            "dimension": "Credential Precondition Scoping",
            "seed_type": "lab_badge_required",
            "task_instruction": "Deliver package pkg_hardware from Lobby to Bob in Lab_Secure.",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 90,
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                    "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                },
                "packages": {
                    "pkg_hardware": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "room_items": {
                    "Lobby": ["security_badge"],
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
            },
        },

        # =====================================================================
        # 5. Capacity-Constrained Multi-Package Delivery (3 Pkgs, Cap=2)
        # =====================================================================
        {
            "scenario_id": "scen_5_capacity_constraint",
            "name": "Capacity-Constrained Multi-Package Delivery (3 Pkgs, Cap=2)",
            "dimension": "Capacity Precondition & Multi-Trip",
            "seed_type": "clean_history",
            "task_instruction": "Deliver pkg_1 to Alice in Office_A, pkg_2 to Charlie in Office_B, and pkg_3 to Alice in Office_A.",
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

        # =====================================================================
        # 6. Multi-Target Interleaving Counterexample
        # =====================================================================
        {
            "scenario_id": "scen_6_multi_target_interleave",
            "name": "Multi-Target Interleaving (Holding Pkg 1, Pkg 2 on Floor)",
            "dimension": "Subgoal Disambiguation vs Phase Heuristic",
            "seed_type": "clean_history",
            "task_instruction": "Deliver pkg_1 to Alice in Office_A, and pkg_2 to Charlie in Office_B.",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 90,
                "robot_start_inventory": ["pkg_1"],
                "max_inventory_capacity": 2,
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                    "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                },
                "packages": {
                    "pkg_1": {"location": "robot_inventory", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                    "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                },
                "recipients": {
                    "Alice": {"room": "Office_A", "status": "available"},
                    "Charlie": {"room": "Office_B", "status": "available"},
                },
            },
        },

        # =====================================================================
        # 7. Truly Mandatory Battery Charging (Start Battery 10% < Path Cost 17%)
        # =====================================================================
        {
            "scenario_id": "scen_7_mandatory_battery_charging",
            "name": "Mandatory Battery Recharging (Start Battery 10% < Path Cost 17%)",
            "dimension": "Physical Resource Feasibility",
            "seed_type": "clean_history",
            "task_instruction": "Deliver package pkg_urgent from Lobby to Charlie in Office_B.",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 10,  # 10% battery strictly cannot reach Office_B without recharge
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                    "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                    "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                },
                "packages": {
                    "pkg_urgent": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                },
                "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
            },
        },

        # =====================================================================
        # 8. Irrelevant Memory Distraction (Failure in Unrelated Wing)
        # =====================================================================
        {
            "scenario_id": "scen_8_irrelevant_memory_distraction",
            "name": "Irrelevant Past Failure in Unrelated Wing (Office_B Blocked)",
            "dimension": "Distraction Immunity",
            "seed_type": "unrelated_door_office_b_blocked",
            "task_instruction": "Deliver package pkg_mail from Lobby to Alice in Office_A.",
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
                    "pkg_mail": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                },
                "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
            },
        },
    ]


def generate_authentic_seed_history(
    scenario_type: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Executes actual tool calls on DeliveryTaskEnv to produce authentic, verifiable Task 1 history.
    Returns: (pre_run_metrics, seed_step_history, seed_observation_events, shared_known_state)
    """
    if scenario_type == "door_north_blocked":
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
            "error_code": res.error_code or "SECURITY_BADGE_REQUIRED",
            "raw_message": res.message,
            "observation": res.observation,
            "sim_time": env.sim_time_s,
        }
        pre_metrics = {"pre_sim_time_s": env.sim_time_s, "pre_battery_consumed": env.cumulative_battery_consumed}
        step_hist = [{"step": 1, "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": res.to_dict()}]
        return pre_metrics, step_hist, [failure_event], {}

    elif scenario_type == "unrelated_door_office_b_blocked":
        # Failure in unrelated room (Office_B blocked) while current task is Lobby -> Office_A
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
        # clean_history
        return {"pre_sim_time_s": 0.0, "pre_battery_consumed": 0}, [], [], {}


def verify_scenario_feasibility(scen: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Executes an optimal oracle trajectory to mathematically prove that the scenario
    is solvable within step, time, and battery limits.
    """
    env = DeliveryTaskEnv(scen["env_config"])
    scen_id = scen["scenario_id"]
    actions_taken = []

    if scen_id == "scen_1_persist_door_north":
        actions_taken.append(env.step("pickup", {"package_id": "pkg_docs", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"}))

    elif scen_id in ("scen_2_cleared_door_north_unobs", "scen_3_cleared_door_north_obs"):
        actions_taken.append(env.step("pickup", {"package_id": "pkg_parts", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_parts", "recipient": "Charlie"}))

    elif scen_id == "scen_4_lab_badge_required":
        actions_taken.append(env.step("pickup", {"package_id": "pkg_hardware", "from_location": "Lobby"}))
        actions_taken.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_hardware", "recipient": "Bob"}))

    elif scen_id == "scen_5_capacity_constraint":
        actions_taken.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions_taken.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Lobby"}))
        actions_taken.append(env.step("pickup", {"package_id": "pkg_3", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_3", "recipient": "Alice"}))

    elif scen_id == "scen_6_multi_target_interleave":
        actions_taken.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))

    elif scen_id == "scen_7_mandatory_battery_charging":
        actions_taken.append(env.step("recharge", {}))
        actions_taken.append(env.step("pickup", {"package_id": "pkg_urgent", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_urgent", "recipient": "Charlie"}))

    elif scen_id == "scen_8_irrelevant_memory_distraction":
        actions_taken.append(env.step("pickup", {"package_id": "pkg_mail", "from_location": "Lobby"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions_taken.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions_taken.append(env.step("deliver", {"package_id": "pkg_mail", "recipient": "Alice"}))

    summary = env.get_summary()
    all_success = all(a.success for a in actions_taken) and summary["success"]
    msg = f"Executed {len(actions_taken)} oracle actions. Final battery: {summary['final_battery']}%. Violations: {summary['constraint_violations']}."
    return all_success, msg, summary
