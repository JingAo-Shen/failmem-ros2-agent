"""
FailMem Stage 2: Authentic Credential Repair Benchmark & Fair Comparison Runner.
Evaluates 4 Groups (Group B, Group C_updated, Group C_guard, Group D) across 4 Target Tasks using
an authentic dual-verified repair memory and homologous facts extracted from a real agent trajectory.

Base Model: Qwen3-14B-AWQ Direct (single GPU, temp=0.0)
Strict Fair Protocol:
  1. Smoke Tests (2 runs): Verify execution pipeline on valid history and changed location.
  2. Phase A: Run Group B on 3 development tasks to verify search closed-loop and extract authentic source trajectory.
  3. Autonomous Source Generation: Extract real trajectory, promote via dual-layer verification (source episode + compiled template).
  4. Phase B: Evaluate Groups B, C_updated, C_guard, D across 4 Target Tasks (16 formal runs, budget=20/25).
  5. Budget-Sensitivity Analysis: Evaluate all 4 Groups on Target 3 with expanded budget (30 LLM / 35 tool calls).
  6. Track full memory lifecycle, plan deviations, token costs, latency, and output auditable JSON report.
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
from ..memory.repair_memory import RepairMemoryStore, VerificationStatus, MemoryLifecycleState
from ..env.task_env import DeliveryTaskEnv
from ..env.tools import StatusCode


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "credential_fair_comparison_results.json"


def get_phase_a_dev_tasks() -> List[Dict[str, Any]]:
    """Phase A: 3 Development Tasks for Group B Search Verification."""
    return [
        {
            "task_id": "cred_task_1_office_a",
            "name": "Dev Task 1 (Badge in Office_A)",
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
            "name": "Dev Task 2 (Badge in Office_B, Office_A Empty)",
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
            "name": "Dev Task 3 (Badge in Lobby)",
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


def get_phase_b_target_tasks() -> List[Dict[str, Any]]:
    """
    Phase B: 4 Pre-determined Target Tasks for Comparative Evaluation.
      - Target 1: Historical badge location preserved (Office_A).
      - Target 2: Start/goal changed, historical badge location preserved (Office_A).
      - Target 3: Badge location changed to Office_B (invalidated memory & historical fact).
      - Target 4: Irrelevant past history (Delivery to Office_B, no badge required).
    """
    return [
        {
            "task_id": "target_1_same_loc",
            "name": "Target 1 (Historical Location Preserved: Office_A)",
            "description": "Deliver pkg_t1 from Lobby to Bob in Lab_Secure. Badge is in Office_A.",
            "instruction": "Deliver package pkg_t1 from Lobby to Bob in Lab_Secure.",
            "badge_location": "Office_A",
            "relevance": "valid_applicable",
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
                    "pkg_t1": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                "room_items": {"Office_A": ["security_badge"], "Office_B": []},
            },
        },
        {
            "task_id": "target_2_diff_route",
            "name": "Target 2 (Different Route / Start Location, Badge in Office_A)",
            "description": "Deliver pkg_t2 from Office_B to Bob in Lab_Secure. Badge is in Office_A.",
            "instruction": "Deliver package pkg_t2 from Office_B to Bob in Lab_Secure.",
            "badge_location": "Office_A",
            "relevance": "valid_applicable",
            "env_config": {
                "robot_start_location": "Office_B",
                "robot_start_battery": 100,
                "doors": {
                    "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                    "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                    "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                    "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                    "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                },
                "packages": {
                    "pkg_t2": {"location": "Office_B", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                "room_items": {"Office_A": ["security_badge"], "Office_B": []},
            },
        },
        {
            "task_id": "target_3_loc_changed",
            "name": "Target 3 (Location Changed: Badge Moved to Office_B, Office_A Empty)",
            "description": "Deliver pkg_t3 from Lobby to Bob in Lab_Secure. Badge moved to Office_B (Office_A is empty).",
            "instruction": "Deliver package pkg_t3 from Lobby to Bob in Lab_Secure.",
            "badge_location": "Office_B",
            "relevance": "stale_invalidated",
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
                    "pkg_t3": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                },
                "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                "room_items": {"Office_A": [], "Office_B": ["security_badge"]},
            },
        },
        {
            "task_id": "target_4_irrelevant_hist",
            "name": "Target 4 (Irrelevant History: Delivery to Office_B, No Badge Required)",
            "description": "Deliver pkg_t4 from Lobby to Alice in Office_B (No badge required).",
            "instruction": "Deliver package pkg_t4 from Lobby to Alice in Office_B.",
            "badge_location": "Lobby",
            "relevance": "irrelevant",
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
                    "pkg_t4": {"location": "Lobby", "target_room": "Office_B", "recipient": "Alice", "delivered": False},
                },
                "recipients": {"Alice": {"room": "Office_B", "status": "available"}},
                "room_items": {"Office_A": [], "Office_B": []},
            },
        },
    ]


def extract_and_promote_source_memory(source_result: Dict[str, Any]) -> Tuple[RepairMemoryStore, Dict[str, Any], List[Dict[str, Any]], str]:
    """
    Extracts failure and repair sequence from an authentic Group B execution trajectory,
    registers it in RepairMemoryStore as a two-layer memory item, promotes it to VERIFIED
    via dual-layer verify_and_promote, extracts homologous historical facts, and computes parity hash.
    """
    import hashlib
    step_history = source_result.get("step_history", [])
    task_id = source_result.get("task_id", "source_task")

    # Find the failure step
    fail_idx = -1
    fail_step = None
    for idx, step in enumerate(step_history):
        res = step.get("result", {})
        err = res.get("error_code") or res.get("status")
        if err in ("SECURITY_BADGE_REQUIRED", "ACCESS_DENIED_NO_BADGE"):
            fail_idx = idx
            fail_step = step
            break

    if fail_idx == -1 or not fail_step:
        raise RuntimeError("No security badge failure event found in source trajectory.")

    # Find the acquire_credential step
    acq_idx = -1
    for idx in range(fail_idx + 1, len(step_history)):
        step = step_history[idx]
        if step.get("tool") == "acquire_credential" and step.get("result", {}).get("success"):
            acq_idx = idx
            break

    if acq_idx == -1:
        raise RuntimeError("No successful acquire_credential step found after failure in source trajectory.")

    # Locate where badge was found from the trajectory
    badge_room = "Office_A"
    for step in step_history[fail_idx + 1 : acq_idx + 1]:
        if step.get("tool") == "observe" and "security_badge" in step.get("result", {}).get("observation", {}).get("items", []):
            badge_room = step["params"].get("target", "Office_A")
            break

    # Repair proposal matching the executed trajectory steps from failure to acquire
    repair_proposal = []
    for step in step_history[fail_idx + 1 : acq_idx + 1]:
        repair_proposal.append({
            "action": step["tool"],
            "params": copy.deepcopy(step["params"]),
        })

    fail_evt = {
        "action_name": fail_step["tool"],
        "target": fail_step["params"].get("target_zone") or "Lab_Secure",
        "error_code": "SECURITY_BADGE_REQUIRED",
        "event_id": fail_step["event_id"],
    }

    store = RepairMemoryStore()
    mem_id = f"mem_repair_badge_{badge_room.lower()}"

    item = store.propose_repair(
        memory_id=mem_id,
        source_task_id=task_id,
        failure_event=fail_evt,
        repair_proposal=repair_proposal,
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={
            f"credential_not_found_in_{badge_room}": True,
            f"room_checked_empty_{badge_room}": True,
        },
        expected_effects=["has_credential(security_badge)"],
    )

    # Attach two-layer structured representations
    item.raw_experience = {
        "source_task_id": task_id,
        "failure_step": fail_step,
        "executed_repair_steps": copy.deepcopy(repair_proposal),
    }
    item.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": badge_room,
        "target_door": "door_lab",
        "required_facts": {"requires_credential(door_lab,security_badge)": True},
        "invalidation_conditions": {
            f"credential_not_found_in_{badge_room}": True,
            f"room_checked_empty_{badge_room}": True,
        },
        "expected_effects": ["has_credential(security_badge)"],
    }

    # Verify and promote using dual-validation (source trajectory + compiled template)
    ok, msg = store.verify_and_promote(
        memory_id=mem_id,
        source_trajectory=step_history,
        expected_effects=["has_credential(security_badge)"],
    )
    if not ok:
        raise RuntimeError(f"Authentic trajectory failed verification: {msg}")

    # Homologous historical facts for Groups C_updated, C_guard, and D
    homologous_facts = {
        f"room_items_{badge_room}": ["security_badge"],
        "badge_location": badge_room,
        f"credential_available_in({badge_room},security_badge)": True,
        "requires_credential(door_lab,security_badge)": True,
    }
    homologous_failures = [fail_evt]

    fact_hash = hashlib.sha256(json.dumps(homologous_facts, sort_keys=True).encode("utf-8")).hexdigest()

    return store, homologous_facts, homologous_failures, fact_hash


def run_benchmark():
    print("=" * 80)
    print("STARTING AUTHENTIC CREDENTIAL REPAIR BENCHMARK & FAIR COMPARISON")
    print("Model: /models/Qwen3-14B-AWQ (AWQ, Deterministic, temp=0.0)")
    print("=" * 80)

    # 1. Initialize Model Backend
    llm = LLMBackend(
        model_path="/models/Qwen3-14B-AWQ",
        device="cuda",
        enable_thinking=False,
        quantization_format="awq",
        max_new_tokens=256,
        temperature=0.0,
    )

    dev_tasks = get_phase_a_dev_tasks()
    target_tasks = get_phase_b_target_tasks()

    benchmark_records = {
        "metadata": {
            "model_path": "/models/Qwen3-14B-AWQ",
            "quantization": "awq",
            "enable_thinking": False,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "smoke_test_results": [],
        "phase_a_dev_results": [],
        "source_memory_generation": {},
        "phase_b_target_results": [],
        "budget_sensitivity_results": [],
        "comparative_summary": {},
    }

    # =========================================================================
    # PHASE A: Group B Development Runs on 3 Credential Search Tasks
    # =========================================================================
    print("\n" + "#" * 80)
    print("### PHASE A: Group B Search Closed-Loop Verification (3 Tasks)")
    print("#" * 80)

    phase_a_runs = {}
    for idx, t in enumerate(dev_tasks, start=1):
        tid = t["task_id"]
        tname = t["name"]
        print(f"\n--- [Phase A Task {idx}/3] {tid}: {tname} ---")
        runner = StatefulAgentRunner(
            llm_backend=llm,
            max_tool_calls=25,
            max_llm_calls=20,
            run_id=f"phase_a_grp_b_{tid}",
            include_historical_facts=False,
            repair_memory_store=None,
        )
        task_spec = {
            "task_id": tid,
            "instruction": t["instruction"],
            "env_config": copy.deepcopy(t["env_config"]),
        }
        res = runner.run_task(task_spec, task_index=idx, seq_id="phase_a")
        phase_a_runs[tid] = res
        benchmark_records["phase_a_dev_results"].append(res)
        print(f"Outcome: Success={res['success']}, Steps={res['step_count']}, LLM Calls={res['llm_calls']}, Time={res['wall_time_s']}s")
        if not res["success"]:
            print(f"WARNING: Phase A task {tid} did not succeed! Reason: {res['completion_reason']}")

    # =========================================================================
    # AUTONOMOUS SOURCE GENERATION & DUAL-VALIDATION PROMOTION
    # =========================================================================
    print("\n" + "#" * 80)
    print("### AUTONOMOUS REPAIR MEMORY EXTRACTION & PROMOTION")
    print("#" * 80)

    source_run = phase_a_runs["cred_task_1_office_a"]
    if not source_run["success"]:
        raise RuntimeError("Source task cred_task_1_office_a failed; cannot extract authentic memory.")

    verified_store, homologous_facts, homologous_failures, fact_hash = extract_and_promote_source_memory(source_run)
    mem_item = verified_store.get_all_memories()[0]

    benchmark_records["source_memory_generation"] = {
        "source_task_id": "cred_task_1_office_a",
        "memory_id": mem_item.memory_id,
        "verification_status": mem_item.verification_status.value,
        "lifecycle_state": mem_item.lifecycle_state.value,
        "source_episode_verified": mem_item.source_episode_verified,
        "compiled_template_validated": mem_item.compiled_template_validated,
        "verification_evidence": mem_item.verification_evidence,
        "repair_proposal": mem_item.repair_proposal,
        "raw_experience": mem_item.raw_experience,
        "reusable_repair_plan": mem_item.reusable_repair_plan,
        "expected_effects": mem_item.expected_effects,
        "homologous_facts": homologous_facts,
        "homologous_failures": homologous_failures,
        "homologous_facts_sha256": fact_hash,
    }
    print(f"Memory '{mem_item.memory_id}' status: {mem_item.verification_status.value}")
    print(f"Dual-layer verified: source_episode={mem_item.source_episode_verified}, template_validated={mem_item.compiled_template_validated}")
    print(f"Reusable Plan Template: {mem_item.reusable_repair_plan}")
    print(f"Homologous Facts (SHA256: {fact_hash[:12]}...): {homologous_facts}")

    # =========================================================================
    # SMOKE TESTS (3 Strict Execution Gates)
    # =========================================================================
    print("\n" + "#" * 80)
    print("### SMOKE TESTS: 3 Strict Execution Gates")
    print("#" * 80)

    try:
        # Gate 1: Valid History (Pre-execution interception & verified reuse)
        print("\n--- [Smoke Gate 1/3] Valid History Pre-interception (Target 1) ---")
        smoke_store_1 = copy.deepcopy(verified_store)
        smoke_runner_1 = StatefulAgentRunner(
            llm_backend=llm,
            max_tool_calls=25,
            max_llm_calls=20,
            run_id="smoke_1_valid_hist",
            include_historical_facts=True,
            repair_memory_store=smoke_store_1,
            is_static=False,
            enable_observation_guard=True,
        )
        s_res_1 = smoke_runner_1.run_task(
            {
                "task_id": target_tasks[0]["task_id"],
                "instruction": target_tasks[0]["instruction"],
                "env_config": copy.deepcopy(target_tasks[0]["env_config"]),
            },
            task_index=99,
            seq_id="smoke_gate_1",
            initial_known_state=copy.deepcopy(homologous_facts),
            historical_failure_events=copy.deepcopy(homologous_failures),
        )
        benchmark_records["smoke_test_results"].append(s_res_1)
        print(f"Smoke 1 Outcome: Success={s_res_1['success']}, Steps={s_res_1['step_count']}, Reused={s_res_1['memory_reused_and_verified']}, Intercepts={s_res_1['intercepted_actions_count']}, TermReason={s_res_1['termination_reason']}")
        assert s_res_1["success"] is True, f"Smoke Gate 1 FAILED: Success was False ({s_res_1['completion_reason']})"
        assert s_res_1["memory_reused_and_verified"] is True, "Smoke Gate 1 FAILED: memory_reused_and_verified was False"
        assert s_res_1["intercepted_actions_count"] >= 1 or s_res_1["total_revisions_count"] >= 1, "Smoke Gate 1 FAILED: no pre-execution intercept or plan repair triggered"
        print(">>> [PASS] Smoke Gate 1 passed.")

        # Gate 2: No History / Unknown Fact (Post-execution tool failure & online search)
        print("\n--- [Smoke Gate 2/3] No History Tool Failure Recovery (Target 1) ---")
        smoke_runner_2 = StatefulAgentRunner(
            llm_backend=llm,
            max_tool_calls=25,
            max_llm_calls=20,
            run_id="smoke_2_no_hist",
            include_historical_facts=False,
            repair_memory_store=None,
            is_static=False,
            enable_observation_guard=True,
        )
        s_res_2 = smoke_runner_2.run_task(
            {
                "task_id": target_tasks[0]["task_id"],
                "instruction": target_tasks[0]["instruction"],
                "env_config": copy.deepcopy(target_tasks[0]["env_config"]),
            },
            task_index=99,
            seq_id="smoke_gate_2",
            initial_known_state=None,
            historical_failure_events=None,
        )
        benchmark_records["smoke_test_results"].append(s_res_2)
        print(f"Smoke 2 Outcome: Success={s_res_2['success']}, Steps={s_res_2['step_count']}, ConstraintEvts={len(s_res_2.get('constraint_events', []))}, TermReason={s_res_2['termination_reason']}")
        assert s_res_2["success"] is True, f"Smoke Gate 2 FAILED: Success was False ({s_res_2['completion_reason']})"
        assert any(evt.get("origin") == "tool_result" for evt in s_res_2.get("constraint_events", [])), "Smoke Gate 2 FAILED: no tool_result failure recorded"
        print(">>> [PASS] Smoke Gate 2 passed.")

        # Gate 3: Changed Location (Invalidation & Online Recovery)
        print("\n--- [Smoke Gate 3/3] Changed Location Invalidation & Online Recovery (Target 3) ---")
        smoke_store_3 = copy.deepcopy(verified_store)
        smoke_runner_3 = StatefulAgentRunner(
            llm_backend=llm,
            max_tool_calls=25,
            max_llm_calls=20,
            run_id="smoke_3_changed_loc",
            include_historical_facts=True,
            repair_memory_store=smoke_store_3,
            is_static=False,
            enable_observation_guard=True,
        )
        s_res_3 = smoke_runner_3.run_task(
            {
                "task_id": target_tasks[2]["task_id"],
                "instruction": target_tasks[2]["instruction"],
                "env_config": copy.deepcopy(target_tasks[2]["env_config"]),
            },
            task_index=99,
            seq_id="smoke_gate_3",
            initial_known_state=copy.deepcopy(homologous_facts),
            historical_failure_events=copy.deepcopy(homologous_failures),
        )
        benchmark_records["smoke_test_results"].append(s_res_3)
        print(f"Smoke 3 Outcome: Success={s_res_3['success']}, Steps={s_res_3['step_count']}, Recovered={s_res_3['memory_invalidated_online_recovered']}, TermReason={s_res_3['termination_reason']}")
        assert s_res_3["success"] is True, f"Smoke Gate 3 FAILED: Success was False ({s_res_3['completion_reason']})"
        assert s_res_3["memory_invalidated_online_recovered"] is True, "Smoke Gate 3 FAILED: memory_invalidated_online_recovered was False"
        print(">>> [PASS] Smoke Gate 3 passed.")

        print("\n" + "=" * 80)
        print(">>> ALL 3 SMOKE TEST GATES PASSED STRICT VALIDATION! PROCEEDING TO FORMAL RUNS.")
        print("=" * 80)

    except Exception as e:
        print(f"\n[CRITICAL FAILURE] Strict Smoke Gate Failed: {e}")
        import traceback
        traceback.print_exc()
        raise RuntimeError(f"Strict Smoke Gate Failed! Aborting formal evaluation: {e}")

    # =========================================================================
    # PHASE B: Comparative Benchmark across 4 Target Tasks x 4 Groups (16 Runs)
    # =========================================================================
    print("\n" + "#" * 80)
    print("### PHASE B: Strict Fair Comparative Benchmark (4 Target Tasks x 4 Groups = 16 Runs)")
    print("### Parity Guarantee: C_updated, C_guard, and D receive identical initial facts (SHA256 verified)")
    print("#" * 80)

    groups = [
        {"id": "Group_B_Agent_B", "name": "Group B (Online Search Baseline, No Memory/Facts)", "enable_guard": False, "use_facts": False, "use_mem": False},
        {"id": "Group_C_updated", "name": "Group C_updated (Homologous Facts + Dynamic Updating, No Guard)", "enable_guard": False, "use_facts": True, "use_mem": False},
        {"id": "Group_C_guard", "name": "Group C_guard (Homologous Facts + Dynamic Updating + Generic Obs Guard)", "enable_guard": True, "use_facts": True, "use_mem": False},
        {"id": "Group_D_Agent_D", "name": "Group D (Homologous Facts + Dynamic Updating + Dual-Verified Repair Memory)", "enable_guard": True, "use_facts": True, "use_mem": True},
    ]

    phase_b_results = []

    for t_idx, task in enumerate(target_tasks, start=1):
        tid = task["task_id"]
        tname = task["name"]
        relevance = task["relevance"]
        badge_loc = task["badge_location"]

        print(f"\n===========================================================================")
        print(f">>> Target Task [{t_idx}/4]: {tid} ({tname})")
        print(f"    Relevance: {relevance} | Badge Loc: {badge_loc}")
        print("===========================================================================")

        for grp in groups:
            gid = grp["id"]
            gname = grp["name"]
            run_id = f"phase_b_{gid}_{tid}"

            task_spec = {
                "task_id": tid,
                "instruction": task["instruction"],
                "env_config": copy.deepcopy(task["env_config"]),
            }

            mem_store = copy.deepcopy(verified_store) if grp["use_mem"] else None
            runner = StatefulAgentRunner(
                llm_backend=llm,
                max_tool_calls=25,
                max_llm_calls=20,
                run_id=run_id,
                include_historical_facts=grp["use_facts"],
                repair_memory_store=mem_store,
                is_static=False,
                enable_observation_guard=grp["enable_guard"],
            )

            res = runner.run_task(
                task_spec,
                task_index=t_idx,
                seq_id="phase_b",
                initial_known_state=copy.deepcopy(homologous_facts) if grp["use_facts"] else None,
                historical_failure_events=copy.deepcopy(homologous_failures) if grp["use_facts"] else None,
            )

            res["group_id"] = gid
            res["group_name"] = gname
            res["target_task_id"] = tid
            res["relevance"] = relevance
            res["input_facts_sha256"] = fact_hash if grp["use_facts"] else "N/A"

            # Compute prompt/generated token totals and tool errors
            tot_p_tokens = sum(tr.get("prompt_tokens", 0) for tr in res["llm_traces"])
            tot_g_tokens = sum(tr.get("generated_tokens", 0) for tr in res["llm_traces"])
            tool_errors = sum(1 for step in res["step_history"] if not step.get("result", {}).get("success", True))
            plan_deviations = sum(1 for step in res["step_history"] if step.get("plan_deviated", False))

            res["total_prompt_tokens"] = tot_p_tokens
            res["total_generated_tokens"] = tot_g_tokens
            res["tool_errors_count"] = tool_errors
            res["plan_deviations_count"] = plan_deviations

            phase_b_results.append(res)
            benchmark_records["phase_b_target_results"].append(res)

            print(f"[{gid}] Task: {tid} -> Success={res['success']} | TermReason={res.get('termination_reason')} | Steps={res['step_count']} | LLM Calls={res['llm_calls']} | Intercepts={res.get('intercepted_actions_count')} | Tool Errs={tool_errors} | P-Tok={tot_p_tokens} | G-Tok={tot_g_tokens} | Time={res['wall_time_s']}s")
            if res.get("target_audit_log"):
                print(f"    Target Audit Log: {res['target_audit_log']}")

    # =========================================================================
    # BUDGET SENSITIVITY EXTENSION: Target 3 with Expanded Budget (30 LLM / 35 Tools)
    # =========================================================================
    print("\n" + "#" * 80)
    print("### BUDGET SENSITIVITY TEST: Target 3 (Badge Moved) with Expanded Budget (30 LLM / 35 Tool Calls)")
    print("#" * 80)

    sens_task = target_tasks[2] # target_3_loc_changed
    sens_results = []

    for grp in groups:
        gid = grp["id"]
        run_id = f"sens_{gid}_{sens_task['task_id']}"

        task_spec = {
            "task_id": sens_task["task_id"],
            "instruction": sens_task["instruction"],
            "env_config": copy.deepcopy(sens_task["env_config"]),
        }

        mem_store = copy.deepcopy(verified_store) if grp["use_mem"] else None
        runner = StatefulAgentRunner(
            llm_backend=llm,
            max_tool_calls=35,
            max_llm_calls=30,
            run_id=run_id,
            include_historical_facts=grp["use_facts"],
            repair_memory_store=mem_store,
            is_static=False,
            enable_observation_guard=grp["enable_guard"],
        )

        s_res = runner.run_task(
            task_spec,
            task_index=3,
            seq_id="sensitivity",
            initial_known_state=copy.deepcopy(homologous_facts) if grp["use_facts"] else None,
            historical_failure_events=copy.deepcopy(homologous_failures) if grp["use_facts"] else None,
        )

        s_res["group_id"] = gid
        s_res["group_name"] = grp["name"]
        s_res["target_task_id"] = sens_task["task_id"]
        s_res["budget_llm"] = 30
        s_res["budget_tools"] = 35

        tot_p_tokens = sum(tr.get("prompt_tokens", 0) for tr in s_res["llm_traces"])
        tot_g_tokens = sum(tr.get("generated_tokens", 0) for tr in s_res["llm_traces"])
        s_res["total_prompt_tokens"] = tot_p_tokens
        s_res["total_generated_tokens"] = tot_g_tokens
        s_res["tool_errors_count"] = sum(1 for step in s_res["step_history"] if not step.get("result", {}).get("success", True))
        s_res["plan_deviations_count"] = sum(1 for step in s_res["step_history"] if step.get("plan_deviated", False))

        sens_results.append(s_res)
        benchmark_records["budget_sensitivity_results"].append(s_res)

        print(f"[Sensitivity 30-Call] [{gid}] -> Success={s_res['success']} | Steps={s_res['step_count']} | LLM Calls={s_res['llm_calls']} | Tool Errs={s_res['tool_errors_count']} | P-Tok={tot_p_tokens} | G-Tok={tot_g_tokens} | Time={s_res['wall_time_s']}s")

    # =========================================================================
    # SUMMARY & PAIRED DISCRIMINATIVE ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("BENCHMARK EXECUTION COMPLETED. COMPUTING METRICS & PAIRED COMPARATIVE ANALYSIS...")
    print("=" * 80)

    summary_by_group = {
        "Group_B_Agent_B": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": [], "tool_errors": [], "deviations": [], "mem_reused": 0, "mem_recovered": 0},
        "Group_C_updated": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": [], "tool_errors": [], "deviations": [], "mem_reused": 0, "mem_recovered": 0},
        "Group_C_guard": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": [], "tool_errors": [], "deviations": [], "mem_reused": 0, "mem_recovered": 0},
        "Group_D_Agent_D": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": [], "tool_errors": [], "deviations": [], "mem_reused": 0, "mem_recovered": 0},
    }

    per_task_table = []
    for t in target_tasks:
        tid = t["task_id"]
        row = {"task_id": tid, "name": t["name"], "relevance": t["relevance"]}
        for gid in summary_by_group.keys():
            matching = [r for r in phase_b_results if r["target_task_id"] == tid and r["group_id"] == gid][0]
            succ = matching["success"]
            steps = matching["step_count"]
            llm_calls = matching["llm_calls"]
            p_tok = matching["total_prompt_tokens"]
            g_tok = matching["total_generated_tokens"]
            wall_t = matching["wall_time_s"]
            errs = matching["tool_errors_count"]
            devs = matching["plan_deviations_count"]

            row[f"{gid}_success"] = succ
            row[f"{gid}_steps"] = steps
            row[f"{gid}_llm_calls"] = llm_calls
            row[f"{gid}_p_tokens"] = p_tok
            row[f"{gid}_g_tokens"] = g_tok
            row[f"{gid}_time_s"] = wall_t
            row[f"{gid}_tool_errors"] = errs
            row[f"{gid}_deviations"] = devs

            summary_by_group[gid]["total"] += 1
            summary_by_group[gid]["tool_errors"].append(errs)
            summary_by_group[gid]["deviations"].append(devs)
            if matching.get("memory_reused_and_verified"):
                summary_by_group[gid]["mem_reused"] += 1
            if matching.get("memory_invalidated_online_recovered"):
                summary_by_group[gid]["mem_recovered"] += 1

            if succ:
                summary_by_group[gid]["successes"] += 1
                summary_by_group[gid]["steps"].append(steps)
                summary_by_group[gid]["llm_calls"].append(llm_calls)
                summary_by_group[gid]["prompt_tokens"].append(p_tok)
                summary_by_group[gid]["gen_tokens"].append(g_tok)
                summary_by_group[gid]["time_s"].append(wall_t)

        per_task_table.append(row)

    # Paired comparisons: D vs C_guard, D vs C_updated, D vs B
    paired_analysis = []
    for t in target_tasks:
        tid = t["task_id"]
        res_d = [r for r in phase_b_results if r["target_task_id"] == tid and r["group_id"] == "Group_D_Agent_D"][0]
        res_cg = [r for r in phase_b_results if r["target_task_id"] == tid and r["group_id"] == "Group_C_guard"][0]
        res_cu = [r for r in phase_b_results if r["target_task_id"] == tid and r["group_id"] == "Group_C_updated"][0]
        res_b = [r for r in phase_b_results if r["target_task_id"] == tid and r["group_id"] == "Group_B_Agent_B"][0]

        paired_analysis.append({
            "task_id": tid,
            "d_vs_c_guard": {
                "step_diff_d_minus_cg": res_d["step_count"] - res_cg["step_count"],
                "llm_diff_d_minus_cg": res_d["llm_calls"] - res_cg["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_cg["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_cg["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_cg["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_cg["success"],
            },
            "d_vs_c_updated": {
                "step_diff_d_minus_cu": res_d["step_count"] - res_cu["step_count"],
                "llm_diff_d_minus_cu": res_d["llm_calls"] - res_cu["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_cu["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_cu["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_cu["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_cu["success"],
            },
            "d_vs_b": {
                "step_diff_d_minus_b": res_d["step_count"] - res_b["step_count"],
                "llm_diff_d_minus_b": res_d["llm_calls"] - res_b["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b["success"],
            },
        })

    benchmark_records["comparative_summary"] = {
        "per_task_comparison": per_task_table,
        "paired_analysis": paired_analysis,
        "group_aggregates": {
            gid: {
                "success_rate": f"{stats['successes']}/{stats['total']} ({stats['successes']/stats['total']*100:.1f}%)" if stats['total'] > 0 else "0%",
                "avg_steps_successful": round(sum(stats["steps"])/len(stats["steps"]), 2) if stats["steps"] else 0,
                "avg_llm_calls_successful": round(sum(stats["llm_calls"])/len(stats["llm_calls"]), 2) if stats["llm_calls"] else 0,
                "avg_prompt_tokens_successful": round(sum(stats["prompt_tokens"])/len(stats["prompt_tokens"]), 1) if stats["prompt_tokens"] else 0,
                "avg_gen_tokens_successful": round(sum(stats["gen_tokens"])/len(stats["gen_tokens"]), 1) if stats["gen_tokens"] else 0,
                "avg_time_s_successful": round(sum(stats["time_s"])/len(stats["time_s"]), 2) if stats["time_s"] else 0,
                "total_tool_errors": sum(stats["tool_errors"]),
                "total_plan_deviations": sum(stats["deviations"]),
                "memory_reused_and_verified_count": stats["mem_reused"],
                "memory_invalidated_online_recovered_count": stats["mem_recovered"],
            }
            for gid, stats in summary_by_group.items()
        },
    }

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(benchmark_records, f, indent=2, ensure_ascii=False)

    print(f"\n[Artifact Saved] Benchmark results written to {OUTPUT_FILE}")
    print("\n--- Summary Table (16 Formal Runs, Budget: 20 LLM / 25 Tools) ---")
    print(f"{'Task ID':<22} | {'Grp B (Stp/LLM)':<16} | {'Grp C_upd (Stp/LLM)':<19} | {'Grp C_guard (Stp/LLM)':<21} | {'Grp D (Stp/LLM)':<16}")
    print("-" * 105)
    for r in per_task_table:
        b_str = f"{r['Group_B_Agent_B_success']} ({r['Group_B_Agent_B_steps']}/{r['Group_B_Agent_B_llm_calls']})"
        cu_str = f"{r['Group_C_updated_success']} ({r['Group_C_updated_steps']}/{r['Group_C_updated_llm_calls']})"
        cg_str = f"{r['Group_C_guard_success']} ({r['Group_C_guard_steps']}/{r['Group_C_guard_llm_calls']})"
        d_str = f"{r['Group_D_Agent_D_success']} ({r['Group_D_Agent_D_steps']}/{r['Group_D_Agent_D_llm_calls']})"
        print(f"{r['task_id']:<22} | {b_str:<16} | {cu_str:<19} | {cg_str:<21} | {d_str:<16}")
    print("-" * 105)

    print("\n--- Budget Sensitivity Table on Target 3 (Expanded Budget: 30 LLM / 35 Tools) ---")
    print(f"{'Group ID':<22} | {'Success':<8} | {'Steps':<6} | {'LLM Calls':<10} | {'P-Tokens':<10} | {'G-Tokens':<10} | {'Time (s)':<8}")
    print("-" * 85)
    for sr in sens_results:
        print(f"{sr['group_id']:<22} | {str(sr['success']):<8} | {sr['step_count']:<6} | {sr['llm_calls']:<10} | {sr['total_prompt_tokens']:<10} | {sr['total_generated_tokens']:<10} | {sr['wall_time_s']:<8}")
    print("-" * 85)


if __name__ == "__main__":
    run_benchmark()
