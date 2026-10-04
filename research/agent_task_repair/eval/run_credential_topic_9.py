"""
9-Unit Credential Repair In-Depth Benchmark Runner (FailMem Stage 2).
Evaluates 3 Groups (Group B, Group C, Group D) across 3 Frozen Credential Access Tasks:
  - Task 1: Security badge in Office_A (Direct discovery / navigation)
  - Task 2: Security badge in Office_B (Search with empty Office_A counter-observation)
  - Task 3: Security badge in Lobby (Immediate local acquisition)

Fairness & Auditability Protocol:
  - Base Model: Qwen3-14B-AWQ Direct (single GPU, temp=0.0)
  - Group B: Stateful agent with online BFS repair, no cross-task memory
  - Group C: Stateful agent with cross-task historical facts (unstructured entity-location facts)
  - Group D: Stateful agent with verified structured repair memory verified via two-phase lifecycle
  - Records: Initial plan, failure event, plan before/after repair, facts checked/updated, resource consumption.
"""
import os
import sys
import json
import time
import copy
import gc
import torch
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ..agent.llm_backend import LLMBackend
from ..agent.stateful_runner import StatefulAgentRunner
from ..agent.planner import MAP_ADJACENCY
from ..agent.plan_manager import PersistentPlan, PlanNodeStatus, PlanNode
from ..memory.repair_memory import RepairMemoryStore, VerificationStatus
from ..env.task_env import DeliveryTaskEnv
from ..env.tools import StatusCode


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "credential_topic_9_results.json"


def get_credential_tasks_3() -> List[Dict[str, Any]]:
    """Returns the 3 frozen diagnostic tasks for credential access."""
    return [
        {
            "task_id": "cred_task_1_office_a",
            "name": "Credential Access (Badge in Office_A)",
            "description": "Delivery to Lab_Secure requiring security_badge located in Office_A",
            "instruction": "Deliver package pkg_sec_docs from Lobby to Bob in Lab_Secure.",
            "badge_location": "Office_A",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 100,
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                    "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                    "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                },
                "packages": {
                    "pkg_sec_docs": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                "room_items": {"Office_A": ["security_badge"], "Office_B": []},
            },
        },
        {
            "task_id": "cred_task_2_office_b",
            "name": "Credential Access (Badge in Office_B, Office_A Empty)",
            "description": "Delivery to Lab_Secure requiring security_badge located in Office_B (Office_A is empty)",
            "instruction": "Deliver package pkg_sample from Lobby to Bob in Lab_Secure.",
            "badge_location": "Office_B",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 100,
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                    "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                    "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                },
                "packages": {
                    "pkg_sample": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                "room_items": {"Office_A": [], "Office_B": ["security_badge"]},
            },
        },
        {
            "task_id": "cred_task_3_lobby",
            "name": "Credential Access (Badge in Lobby)",
            "description": "Delivery to Lab_Secure with security_badge available in starting room (Lobby)",
            "instruction": "Deliver package pkg_proto from Lobby to Bob in Lab_Secure.",
            "badge_location": "Lobby",
            "env_config": {
                "robot_start_location": "Lobby",
                "robot_start_battery": 100,
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                    "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                    "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                },
                "packages": {
                    "pkg_proto": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                "room_items": {"Lobby": ["security_badge"], "Office_A": [], "Office_B": []},
            },
        },
    ]


def generate_verified_credential_repair_store(badge_loc: str) -> RepairMemoryStore:
    """
    Executes an authentic source trajectory on DeliveryTaskEnv to produce and promote
    a verified repair memory item for the given badge location.
    """
    store = RepairMemoryStore()

    # 1. Simulate authentic seed trajectory on env
    env_cfg = {
        "robot_start_location": "Corridor_South",
        "robot_start_battery": 100,
        "doors": {
            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
        },
        "room_items": {badge_loc: ["security_badge"]},
    }
    env = DeliveryTaskEnv(env_cfg)

    # Step 1: Encounter failure
    res_fail = env.step("navigate", {"target_zone": "Lab_Secure"})
    fail_step = {
        "step": 1,
        "event_id": "evt_cred_seed_01",
        "tool": "navigate",
        "params": {"target_zone": "Lab_Secure"},
        "result": res_fail.to_dict(),
        "robot_location": "Corridor_South",
    }

    # Step 2: Navigate to badge location (if not already there)
    source_traj = [fail_step]
    repair_steps = []

    path_to_badge = []
    if badge_loc == "Office_A":
        path_to_badge = ["Office_A"]
    elif badge_loc == "Office_B":
        path_to_badge = ["Corridor_North", "Office_B"]
    elif badge_loc == "Lobby":
        path_to_badge = ["Lobby"]

    for hop in path_to_badge:
        nav = env.step("navigate", {"target_zone": hop})
        source_traj.append({
            "step": len(source_traj) + 1,
            "event_id": f"evt_cred_seed_{len(source_traj)+1:02d}",
            "tool": "navigate",
            "params": {"target_zone": hop},
            "result": nav.to_dict(),
            "robot_location": env.robot_location,
            "robot_location_after": env.robot_location,
        })
        repair_steps.append({"action": "navigate", "params": {"target_zone": hop}})

    # Step 3: Acquire credential
    res_acq = env.step("acquire_credential", {"credential_name": "security_badge"})
    source_traj.append({
        "step": len(source_traj) + 1,
        "event_id": f"evt_cred_seed_{len(source_traj)+1:02d}",
        "tool": "acquire_credential",
        "params": {"credential_name": "security_badge"},
        "result": res_acq.to_dict(),
        "robot_location": env.robot_location,
        "robot_location_after": env.robot_location,
    })
    repair_steps.append({"action": "acquire_credential", "params": {"credential_name": "security_badge"}})

    # Propose repair item
    mem_id = f"mem_repair_badge_{badge_loc.lower()}"
    store.propose_repair(
        memory_id=mem_id,
        source_task_id="seed_task_cred",
        failure_event={
            "action_name": "navigate",
            "target": "Lab_Secure",
            "error_code": "SECURITY_BADGE_REQUIRED",
            "event_id": "evt_cred_seed_01",
        },
        repair_proposal=repair_steps,
        applicability={"target": "Lab_Secure"},
        required_facts={"security_badge_required": True},
        invalidation_conditions={"has_credential": "security_badge"},
        expected_effects=["has_credential(security_badge)"],
    )

    # Verify and promote using authentic trajectory
    ok, msg = store.verify_and_promote(mem_id, source_traj, expected_effects=["has_credential(security_badge)"])
    if not ok:
        raise RuntimeError(f"Failed to promote authentic repair memory: {msg}")

    return store


def run_credential_topic_9(
    model_path: str = "/models/Qwen3-14B-AWQ",
    quantization_format: str = "awq",
    enable_thinking: Optional[bool] = False,
):
    print("=" * 80)
    print("STARTING 9-UNIT DEEP DIVE BENCHMARK: CREDENTIAL REPAIR (3 TASKS x 3 GROUPS)")
    print(f"Base Model: {model_path} (quant={quantization_format}, thinking={enable_thinking})")
    print("=" * 80)

    tasks = get_credential_tasks_3()

    # Initialize LLM backend
    llm = LLMBackend(
        model_path=model_path,
        device="cuda",
        enable_thinking=enable_thinking,
        quantization_format=quantization_format,
        max_new_tokens=256,
        temperature=0.0,
    )

    groups = [
        {"id": "Group_B_Agent_B", "name": "Group B (Stateful Agent, Online Search, No Cross-Task Memory)"},
        {"id": "Group_C_Agent_C", "name": "Group C (Stateful Agent, Historical Facts)"},
        {"id": "Group_D_Agent_D", "name": "Group D (Stateful Agent, Verified Repair Memory)"},
    ]

    all_unit_results = []
    t_bench_start = time.time()

    for t_idx, task in enumerate(tasks, start=1):
        tid = task["task_id"]
        tname = task["name"]
        badge_loc = task["badge_location"]

        print(f"\n" + "=" * 76)
        print(f">>> Task [{t_idx}/3]: {tid} ({tname})")
        print(f"    Badge Location: {badge_loc} | Recipient: Bob in Lab_Secure")
        print("=" * 76)

        for grp in groups:
            gid = grp["id"]
            gname = grp["name"]
            run_id = f"cred9_{gid}_{tid}"
            t_unit_start = time.time()

            task_spec = {
                "task_id": tid,
                "instruction": task["instruction"],
                "env_config": copy.deepcopy(task["env_config"]),
            }

            # Group setups
            initial_facts = {}
            repair_store = None

            if gid == "Group_B_Agent_B":
                # No cross-task memory
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    include_historical_facts=False,
                    repair_memory_store=None,
                )
                res = runner.run_task(task_spec, task_index=1, seq_id="cred9_bench")

            elif gid == "Group_C_Agent_C":
                # Cross-task historical fact about badge location
                initial_facts = {
                    f"room_items_{badge_loc}": ["security_badge"],
                    "badge_location": badge_loc,
                    "security_badge_required": True,
                }
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    include_historical_facts=True,
                    repair_memory_store=None,
                )
                res = runner.run_task(
                    task_spec,
                    task_index=1,
                    seq_id="cred9_bench",
                    initial_known_state=initial_facts,
                    historical_failure_events=[{
                        "event_id": "evt_cred_hist_01",
                        "action_name": "navigate",
                        "target": "Lab_Secure",
                        "error_code": "SECURITY_BADGE_REQUIRED",
                        "observation": {"required_credential": "security_badge"},
                    }],
                )

            elif gid == "Group_D_Agent_D":
                # Authentic verified repair memory
                repair_store = generate_verified_credential_repair_store(badge_loc)
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    include_historical_facts=True,
                    repair_memory_store=repair_store,
                )
                res = runner.run_task(
                    task_spec,
                    task_index=1,
                    seq_id="cred9_bench",
                    initial_known_state={"security_badge_required": True},
                    historical_failure_events=[{
                        "event_id": "evt_cred_hist_01",
                        "action_name": "navigate",
                        "target": "Lab_Secure",
                        "error_code": "SECURITY_BADGE_REQUIRED",
                    }],
                )

            t_unit_wall = time.time() - t_unit_start
            success = bool(res.get("success", False))
            step_count = len(res.get("step_history", []))
            batt = res.get("battery_consumed", 0)
            llm_calls = res.get("llm_calls", len(res.get("llm_traces", [])))
            rep_fails = res.get("repeated_failures_count", 0)

            # Extract trajectory details: plan mutations, tool calls, error handling
            step_summary = [
                f"{h['step']}:{h['tool']}({h['params']})->{h['result']['status']}"
                for h in res.get("step_history", [])
            ]

            unit_record = {
                "task_id": tid,
                "task_name": tname,
                "badge_location": badge_loc,
                "group_id": gid,
                "group_name": gname,
                "success": success,
                "steps": step_count,
                "battery_consumed": batt,
                "sim_time_s": res.get("sim_time_s", 0.0),
                "llm_calls": llm_calls,
                "wall_time_s": round(t_unit_wall, 2),
                "repeated_failures": rep_fails,
                "intercepted_actions": res.get("intercepted_actions_count", 0),
                "plan_repair_applied": bool(repair_store and any(m.lifecycle_state.value == "VERIFIED_EFFECT" or m.lifecycle_state.value == "RETRIEVED" for m in repair_store.get_all_memories())) if repair_store else False,
                "step_summary": step_summary,
                "step_history": res.get("step_history", []),
                "validation_records": res.get("validation_records", []),
            }
            all_unit_results.append(unit_record)

            print(f"  [{gid:18s}] Success={str(success):5s} | Steps={step_count:2d} | Batt={batt:2d}% | Wall={t_unit_wall:4.1f}s | Flow={', '.join(step_summary[:4])}...")

    t_bench_wall = time.time() - t_bench_start

    # Aggregated Summary
    group_aggregates = {}
    for grp in groups:
        gid = grp["id"]
        g_records = [r for r in all_unit_results if r["group_id"] == gid]
        n_succ = sum(1 for r in g_records if r["success"])
        total_steps = sum(r["steps"] for r in g_records)
        total_batt = sum(r["battery_consumed"] for r in g_records)
        total_wall = sum(r["wall_time_s"] for r in g_records)

        group_aggregates[gid] = {
            "group_id": gid,
            "group_name": grp["name"],
            "total_tasks": len(g_records),
            "success_count": n_succ,
            "success_rate": round(n_succ / max(1, len(g_records)), 4),
            "avg_steps": round(total_steps / max(1, len(g_records)), 2),
            "avg_battery": round(total_batt / max(1, len(g_records)), 2),
            "avg_wall_time_s": round(total_wall / max(1, len(g_records)), 2),
        }

    # Mutual-success efficiency comparison
    b_records = {r["task_id"]: r for r in all_unit_results if r["group_id"] == "Group_B_Agent_B"}
    c_records = {r["task_id"]: r for r in all_unit_results if r["group_id"] == "Group_C_Agent_C"}
    d_records = {r["task_id"]: r for r in all_unit_results if r["group_id"] == "Group_D_Agent_D"}

    mutual_tasks_bd = [tid for tid in b_records if b_records[tid]["success"] and d_records[tid]["success"]]
    mutual_tasks_cd = [tid for tid in c_records if c_records[tid]["success"] and d_records[tid]["success"]]

    bd_step_diff = sum(b_records[t]["steps"] - d_records[t]["steps"] for t in mutual_tasks_bd) / max(1, len(mutual_tasks_bd))
    bd_batt_diff = sum(b_records[t]["battery_consumed"] - d_records[t]["battery_consumed"] for t in mutual_tasks_bd) / max(1, len(mutual_tasks_bd))

    cd_step_diff = sum(c_records[t]["steps"] - d_records[t]["steps"] for t in mutual_tasks_cd) / max(1, len(mutual_tasks_cd))
    cd_batt_diff = sum(c_records[t]["battery_consumed"] - d_records[t]["battery_consumed"] for t in mutual_tasks_cd) / max(1, len(mutual_tasks_cd))

    paired_comparison = {
        "mutual_tasks_B_and_D": mutual_tasks_bd,
        "group_D_vs_B_step_savings": round(bd_step_diff, 2),
        "group_D_vs_B_battery_savings": round(bd_batt_diff, 2),
        "mutual_tasks_C_and_D": mutual_tasks_cd,
        "group_D_vs_C_step_savings": round(cd_step_diff, 2),
        "group_D_vs_C_battery_savings": round(cd_batt_diff, 2),
    }

    payload = {
        "benchmark": "9_unit_credential_topic",
        "base_model": model_path,
        "quantization": quantization_format,
        "enable_thinking": enable_thinking,
        "total_wall_time_s": round(t_bench_wall, 2),
        "group_aggregates": group_aggregates,
        "paired_efficiency_comparison": paired_comparison,
        "unit_results": all_unit_results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("\n" + "=" * 80)
    print("9-UNIT CREDENTIAL TOPIC BENCHMARK COMPLETED")
    print(f"Results saved to: {OUTPUT_FILE}")
    for gid, agg in group_aggregates.items():
        print(f"  {gid:18s}: Success={agg['success_count']}/{agg['total_tasks']} | AvgSteps={agg['avg_steps']} | AvgBatt={agg['avg_battery']}")
    print(f"Paired Step Savings (Group D vs Group B): {paired_comparison['group_D_vs_B_step_savings']} steps")
    print(f"Paired Step Savings (Group D vs Group C): {paired_comparison['group_D_vs_C_step_savings']} steps")
    print("=" * 80)


if __name__ == "__main__":
    run_credential_topic_9()
