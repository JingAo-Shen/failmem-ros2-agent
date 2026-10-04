"""
FailMem Stage 2: Authentic Credential Repair Benchmark & Fair Comparison Runner.
Evaluates 3 Groups (Group B, Group C, Group D) across 4 Target Tasks using
an authentic verified repair memory and homologous facts extracted from a real agent trajectory.

Base Model: Qwen3-14B-AWQ Direct (single GPU, temp=0.0)
Strict Fair Protocol:
  1. Phase A: Run Group B on 3 development tasks to verify search closed-loop.
  2. Autonomous Source Generation: Run Group B on a source task, extract real trajectory,
     promote to VERIFIED via strict verify_and_promote, and extract homologous facts.
  3. Phase B: Evaluate Groups B, C, D across 4 Target Tasks (12 runs total).
  4. Track full memory lifecycle and output complete auditable JSON report.
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


def extract_and_promote_source_memory(source_result: Dict[str, Any]) -> Tuple[RepairMemoryStore, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Extracts failure and repair sequence from an authentic Group B execution trajectory,
    registers it in RepairMemoryStore, promotes it to VERIFIED via verify_and_promote,
    and extracts homologous historical facts for Group C.
    """
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

    # Repair proposal is the exact sequence of executed steps from failure to acquire_credential
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

    # Locate where badge was found from the trajectory
    badge_room = "Office_A"
    for step in step_history[fail_idx + 1 : acq_idx + 1]:
        if step.get("tool") == "observe" and "security_badge" in step.get("result", {}).get("observation", {}).get("items", []):
            badge_room = step["params"].get("target", "Office_A")
            break

    store = RepairMemoryStore()
    mem_id = f"mem_repair_badge_{badge_room.lower()}"

    store.propose_repair(
        memory_id=mem_id,
        source_task_id=task_id,
        failure_event=fail_evt,
        repair_proposal=repair_proposal,
        applicability={"target": "Lab_Secure"},
        required_facts={"security_badge_required": True},
        invalidation_conditions={
            f"credential_not_found_in_{badge_room}": True,
            f"room_checked_empty_{badge_room}": True,
        },
        expected_effects=["has_credential(security_badge)"],
    )

    # Verify and promote using authentic trajectory
    ok, msg = store.verify_and_promote(
        memory_id=mem_id,
        source_trajectory=step_history,
        expected_effects=["has_credential(security_badge)"],
    )
    if not ok:
        raise RuntimeError(f"Authentic trajectory failed verification: {msg}")

    # Homologous historical facts for Group C (extracted from the exact same trajectory)
    homologous_facts = {
        f"room_items_{badge_room}": ["security_badge"],
        "badge_location": badge_room,
        "security_badge_required": True,
    }
    homologous_failures = [fail_evt]

    return store, homologous_facts, homologous_failures


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
        "phase_a_dev_results": [],
        "source_memory_generation": {},
        "phase_b_target_results": [],
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
    # AUTONOMOUS SOURCE GENERATION & VERIFICATION
    # =========================================================================
    print("\n" + "#" * 80)
    print("### AUTONOMOUS REPAIR MEMORY EXTRACTION & PROMOTION")
    print("#" * 80)

    source_run = phase_a_runs["cred_task_1_office_a"]
    if not source_run["success"]:
        raise RuntimeError("Source task cred_task_1_office_a failed; cannot extract authentic memory.")

    verified_store, homologous_facts, homologous_failures = extract_and_promote_source_memory(source_run)
    mem_item = verified_store.get_all_memories()[0]

    benchmark_records["source_memory_generation"] = {
        "source_task_id": "cred_task_1_office_a",
        "memory_id": mem_item.memory_id,
        "verification_status": mem_item.verification_status.value,
        "lifecycle_state": mem_item.lifecycle_state.value,
        "verification_evidence": mem_item.verification_evidence,
        "repair_proposal": mem_item.repair_proposal,
        "expected_effects": mem_item.expected_effects,
        "homologous_facts": homologous_facts,
        "homologous_failures": homologous_failures,
    }
    print(f"Memory '{mem_item.memory_id}' status: {mem_item.verification_status.value}")
    print(f"Proposal: {mem_item.repair_proposal}")
    print(f"Homologous Facts for Group C: {homologous_facts}")

    # =========================================================================
    # PHASE B: Comparative Benchmark across 4 Target Tasks x 3 Groups (12 Runs)
    # =========================================================================
    print("\n" + "#" * 80)
    print("### PHASE B: Fair Comparative Benchmark (4 Target Tasks x 3 Groups = 12 Runs)")
    print("#" * 80)

    groups = [
        {"id": "Group_B_Agent_B", "name": "Group B (Stateful Agent, Online Search, No Memory)"},
        {"id": "Group_C_Agent_C", "name": "Group C (Stateful Agent, Homologous Facts)"},
        {"id": "Group_D_Agent_D", "name": "Group D (Stateful Agent, Verified Repair Memory)"},
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

            if gid == "Group_B_Agent_B":
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    include_historical_facts=False,
                    repair_memory_store=None,
                )
                res = runner.run_task(task_spec, task_index=t_idx, seq_id="phase_b")

            elif gid == "Group_C_Agent_C":
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
                    task_index=t_idx,
                    seq_id="phase_b",
                    initial_known_state=copy.deepcopy(homologous_facts),
                    historical_failure_events=copy.deepcopy(homologous_failures),
                )

            elif gid == "Group_D_Agent_D":
                # Create a fresh store containing the verified source memory
                grp_d_store = copy.deepcopy(verified_store)
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    include_historical_facts=False,
                    repair_memory_store=grp_d_store,
                )
                res = runner.run_task(
                    task_spec,
                    task_index=t_idx,
                    seq_id="phase_b",
                )

            res["group_id"] = gid
            res["group_name"] = gname
            res["target_task_id"] = tid
            res["relevance"] = relevance
            phase_b_results.append(res)
            benchmark_records["phase_b_target_results"].append(res)

            # Compute prompt/generated token totals
            tot_p_tokens = sum(tr.get("prompt_tokens", 0) for tr in res["llm_traces"])
            tot_g_tokens = sum(tr.get("generated_tokens", 0) for tr in res["llm_traces"])
            res["total_prompt_tokens"] = tot_p_tokens
            res["total_generated_tokens"] = tot_g_tokens

            print(f"[{gid}] Task: {tid} -> Success={res['success']} | Steps={res['step_count']} | LLM Calls={res['llm_calls']} | P-Tokens={tot_p_tokens} | G-Tokens={tot_g_tokens} | Time={res['wall_time_s']}s")
            if res.get("memory_audit_log"):
                print(f"    Memory Audit Log: {res['memory_audit_log']}")

    # =========================================================================
    # SUMMARY & FAIRNESS COMPARATIVE ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("BENCHMARK EXECUTION COMPLETED. COMPUTING METRICS & COMPARATIVE ANALYSIS...")
    print("=" * 80)

    # Structure summary table
    summary_by_group = {
        "Group_B_Agent_B": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": []},
        "Group_C_Agent_C": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": []},
        "Group_D_Agent_D": {"successes": 0, "total": 0, "steps": [], "llm_calls": [], "prompt_tokens": [], "gen_tokens": [], "time_s": []},
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

            row[f"{gid}_success"] = succ
            row[f"{gid}_steps"] = steps
            row[f"{gid}_llm_calls"] = llm_calls
            row[f"{gid}_p_tokens"] = p_tok
            row[f"{gid}_g_tokens"] = g_tok
            row[f"{gid}_time_s"] = wall_t

            summary_by_group[gid]["total"] += 1
            if succ:
                summary_by_group[gid]["successes"] += 1
                summary_by_group[gid]["steps"].append(steps)
                summary_by_group[gid]["llm_calls"].append(llm_calls)
                summary_by_group[gid]["prompt_tokens"].append(p_tok)
                summary_by_group[gid]["gen_tokens"].append(g_tok)
                summary_by_group[gid]["time_s"].append(wall_t)

        per_task_table.append(row)

    benchmark_records["comparative_summary"] = {
        "per_task_comparison": per_task_table,
        "group_aggregates": {
            gid: {
                "success_rate": f"{stats['successes']}/{stats['total']} ({stats['successes']/stats['total']*100:.1f}%)" if stats['total'] > 0 else "0%",
                "avg_steps_successful": round(sum(stats["steps"])/len(stats["steps"]), 2) if stats["steps"] else 0,
                "avg_llm_calls_successful": round(sum(stats["llm_calls"])/len(stats["llm_calls"]), 2) if stats["llm_calls"] else 0,
                "avg_prompt_tokens_successful": round(sum(stats["prompt_tokens"])/len(stats["prompt_tokens"]), 1) if stats["prompt_tokens"] else 0,
                "avg_gen_tokens_successful": round(sum(stats["gen_tokens"])/len(stats["gen_tokens"]), 1) if stats["gen_tokens"] else 0,
                "avg_time_s_successful": round(sum(stats["time_s"])/len(stats["time_s"]), 2) if stats["time_s"] else 0,
            }
            for gid, stats in summary_by_group.items()
        },
    }

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(benchmark_records, f, indent=2, ensure_ascii=False)

    print(f"\n[Artifact Saved] Benchmark results written to {OUTPUT_FILE}")
    print("\n--- Summary Table ---")
    print(f"{'Task ID':<22} | {'Grp B Succ (Stp/LLM)':<20} | {'Grp C Succ (Stp/LLM)':<20} | {'Grp D Succ (Stp/LLM)':<20}")
    print("-" * 88)
    for r in per_task_table:
        b_str = f"{r['Group_B_Agent_B_success']} ({r['Group_B_Agent_B_steps']}/{r['Group_B_Agent_B_llm_calls']})"
        c_str = f"{r['Group_C_Agent_C_success']} ({r['Group_C_Agent_C_steps']}/{r['Group_C_Agent_C_llm_calls']})"
        d_str = f"{r['Group_D_Agent_D_success']} ({r['Group_D_Agent_D_steps']}/{r['Group_D_Agent_D_llm_calls']})"
        print(f"{r['task_id']:<22} | {b_str:<20} | {c_str:<20} | {d_str:<20}")
    print("-" * 88)


if __name__ == "__main__":
    run_benchmark()
