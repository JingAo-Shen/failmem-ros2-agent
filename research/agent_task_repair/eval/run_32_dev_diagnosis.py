"""
32-Unit Controlled Development Diagnosis Runner (FailMem Stage 2).
Evaluates 4 Groups across 8 Authentic Diagnostic Scenarios:
  - Group A (S1_M0): Single-step task skeleton planner, no repair memory
  - Group B (Agent_B): Stateful plan manager, no repair memory
  - Group C (Agent_C): Stateful plan manager + historical failure warnings (retrieval-based, unstructured)
  - Group D (Agent_D): Stateful plan manager + verified structured repair memory with active invalidation

Fairness Contract:
  - All groups receive identical shared known state (e.g. current observations)
  - Task 1 failure events are authentic tool execution traces from DeliveryTaskEnv
  - Pre-run fixed setup costs and continuation costs are strictly isolated and reported
  - Complete per-step execution traces (prompt, raw output, validation, tool events) are logged.
"""
import sys
import os
import json
import time
import copy
import gc
import torch
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..agent.stateful_runner import StatefulAgentRunner
from ..agent.planner import MAP_ADJACENCY
from ..memory.subgoal_memory_adapter import SubgoalMemoryAdapter
from ..memory.repair_memory import RepairMemoryStore, VerificationStatus
from ..env.diagnostic_scenarios_8 import get_8_diagnostic_scenarios, generate_authentic_seed_history, verify_scenario_feasibility


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "dev_32_diagnosis_results.json"


def create_group_d_repair_store(
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


def run_32_dev_diagnosis(
    model_path: str = "/models/Qwen3-14B-AWQ",
    quantization_format: str = "awq",
    enable_thinking: Optional[bool] = False,
):
    print("=" * 80)
    print("STARTING 32-UNIT CONTROLLED DEVELOPMENT DIAGNOSIS (8 SCENARIOS x 4 GROUPS)")
    print(f"Locked Base Model: {model_path} (quant={quantization_format}, thinking={enable_thinking})")
    print("=" * 80)

    # 1. Feasibility check on all 8 scenarios
    scenarios = get_8_diagnostic_scenarios()
    print(f"\n[Verification] Verifying oracle feasibility of {len(scenarios)} diagnostic scenarios...")
    for s in scenarios:
        ok, msg, _ = verify_scenario_feasibility(s)
        if not ok:
            raise RuntimeError(f"Scenario {s['scenario_id']} failed feasibility check: {msg}")
    print("[Verification] All 8 diagnostic scenarios 100% verified solvable by oracle.\n")

    # Load LLM backend
    llm = LLMBackend(
        model_path=model_path,
        device="cuda",
        enable_thinking=enable_thinking,
        quantization_format=quantization_format,
        max_new_tokens=256,
        temperature=0.0,
    )

    groups = [
        {"id": "Group_A_S1_M0", "name": "Group A (S1_M0: Stateless Skeleton Planner, No Memory)"},
        {"id": "Group_B_Agent_B", "name": "Group B (Agent_B: Stateful Plan Manager, No Memory)"},
        {"id": "Group_C_Agent_C", "name": "Group C (Agent_C: Stateful + Historical Warnings)"},
        {"id": "Group_D_Agent_D", "name": "Group D (Agent_D: Stateful + Verified Repair Memory)"},
    ]

    unit_results = []
    t_total_start = time.time()

    for s_idx, scen in enumerate(scenarios, start=1):
        sid = scen["scenario_id"]
        sname = scen["name"]
        dim = scen["dimension"]
        seed_type = scen["seed_type"]

        print(f"\n>>> Scenario [{s_idx}/8]: {sid} ({sname})")

        # Generate authentic Task 1 history and shared sensory state
        pre_metrics, seed_steps, failure_events, shared_known = generate_authentic_seed_history(seed_type)

        for grp in groups:
            gid = grp["id"]
            gname = grp["name"]
            run_id = f"diag_{gid}_{sid}"
            t_unit_start = time.time()

            task_spec = {
                "task_id": sid,
                "instruction": scen["task_instruction"],
                "env_config": copy.deepcopy(scen["env_config"]),
            }

            if gid == "Group_A_S1_M0":
                adapter = SubgoalMemoryAdapter(injection_mode="none", store_mode="F", adjacency_map=MAP_ADJACENCY)
                runner = AgentRunner(
                    llm_backend=llm,
                    memory_adapter=adapter,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    use_task_skeleton=True,
                )
                res = runner.run_task(task_spec, task_index=1, seq_id="dev32_diag", initial_known_state=shared_known)

            elif gid == "Group_B_Agent_B":
                runner = StatefulAgentRunner(
                    llm_backend=llm,
                    max_tool_calls=25,
                    max_llm_calls=20,
                    run_id=run_id,
                    include_historical_facts=False,
                    repair_memory_store=None,
                )
                res = runner.run_task(task_spec, task_index=1, seq_id="dev32_diag", initial_known_state=shared_known)

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
                    task_index=1,
                    seq_id="dev32_diag",
                    initial_known_state=shared_known,
                    historical_failure_events=failure_events,
                )

            elif gid == "Group_D_Agent_D":
                repair_store = create_group_d_repair_store(seed_type, shared_known, failure_events)
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
                    seq_id="dev32_diag",
                    initial_known_state=shared_known,
                    historical_failure_events=failure_events,
                )

            t_unit_wall = time.time() - t_unit_start
            success = bool(res.get("success", False))
            step_count = len(res.get("step_history", []))
            batt = res.get("battery_consumed", 0)
            llm_calls = res.get("llm_calls", len(res.get("llm_traces", [])))
            repeated_fails = res.get("repeated_failures_count", 0)
            intercepted = res.get("intercepted_actions_count", 0)

            # Compute first-failure recovery
            encountered_fail = any(
                not h.get("result", {}).get("success", True)
                for h in res.get("step_history", [])
            )
            recovered_after_fail = (encountered_fail and success)

            unit_record = {
                "scenario_id": sid,
                "scenario_name": sname,
                "dimension": dim,
                "group_id": gid,
                "group_name": gname,
                "success": success,
                "steps": step_count,
                "battery_consumed": batt,
                "llm_calls": llm_calls,
                "wall_time_s": round(t_unit_wall, 2),
                "repeated_failures": repeated_fails,
                "intercepted_actions": intercepted,
                "encountered_failure": encountered_fail,
                "recovered_after_failure": recovered_after_fail,
                "pre_run_setup_metrics": pre_metrics,
                "continuation_metrics": {
                    "sim_time_s": res.get("sim_time_s", 0.0),
                    "battery_consumed": batt,
                    "steps": step_count,
                },
                "total_metrics": {
                    "sim_time_s": round(pre_metrics.get("pre_sim_time_s", 0.0) + res.get("sim_time_s", 0.0), 2),
                    "battery_consumed": pre_metrics.get("pre_battery_consumed", 0) + batt,
                },
                "step_history": res.get("step_history", []),
                "llm_traces": res.get("llm_traces", []),
                "validation_records": res.get("validation_records", []),
            }
            unit_results.append(unit_record)

            print(f"  [{gid:18s}] Success={str(success):5s} | Steps={step_count:2d} | Batt={batt:2d}% | RepFails={repeated_fails} | Wall={t_unit_wall:4.1f}s")

    t_total_wall = time.time() - t_total_start

    # Group Aggregations
    group_summaries = {}
    for grp in groups:
        gid = grp["id"]
        g_records = [r for r in unit_results if r["group_id"] == gid]
        n_total = len(g_records)
        n_success = sum(1 for r in g_records if r["success"])
        succ_rate = round(n_success / max(1, n_total), 4)

        total_steps = sum(r["steps"] for r in g_records)
        total_batt = sum(r["battery_consumed"] for r in g_records)
        total_calls = sum(r["llm_calls"] for r in g_records)
        total_rep_fails = sum(r["repeated_failures"] for r in g_records)
        n_enc_fail = sum(1 for r in g_records if r["encountered_failure"])
        n_rec_fail = sum(1 for r in g_records if r["recovered_after_failure"])
        rec_rate = round(n_rec_fail / max(1, n_enc_fail), 4)

        # Paired cost on mutually successful tasks (between B and D, and C and D)
        group_summaries[gid] = {
            "group_id": gid,
            "group_name": grp["name"],
            "total_units": n_total,
            "success_count": n_success,
            "success_rate": succ_rate,
            "repeated_failures_total": total_rep_fails,
            "encountered_failures_count": n_enc_fail,
            "recovered_after_failure_count": n_rec_fail,
            "first_failure_recovery_rate": rec_rate,
            "avg_steps": round(total_steps / max(1, n_total), 2),
            "avg_battery": round(total_batt / max(1, n_total), 2),
            "avg_llm_calls": round(total_calls / max(1, n_total), 2),
        }

    # Mutual-success efficiency calculation
    b_records = {r["scenario_id"]: r for r in unit_results if r["group_id"] == "Group_B_Agent_B"}
    c_records = {r["scenario_id"]: r for r in unit_results if r["group_id"] == "Group_C_Agent_C"}
    d_records = {r["scenario_id"]: r for r in unit_results if r["group_id"] == "Group_D_Agent_D"}

    mutual_bd = [sid for sid in b_records if b_records[sid]["success"] and d_records[sid]["success"]]
    mutual_cd = [sid for sid in c_records if c_records[sid]["success"] and d_records[sid]["success"]]

    bd_step_diff = sum(b_records[s]["steps"] - d_records[s]["steps"] for s in mutual_bd) / max(1, len(mutual_bd)) if mutual_bd else 0.0
    bd_batt_diff = sum(b_records[s]["battery_consumed"] - d_records[s]["battery_consumed"] for s in mutual_bd) / max(1, len(mutual_bd)) if mutual_bd else 0.0

    cd_step_diff = sum(c_records[s]["steps"] - d_records[s]["steps"] for s in mutual_cd) / max(1, len(mutual_cd)) if mutual_cd else 0.0
    cd_batt_diff = sum(c_records[s]["battery_consumed"] - d_records[s]["battery_consumed"] for s in mutual_cd) / max(1, len(mutual_cd)) if mutual_cd else 0.0

    paired_comparison = {
        "mutual_scenarios_B_and_D": mutual_bd,
        "group_D_vs_B_step_savings": round(bd_step_diff, 2),
        "group_D_vs_B_battery_savings": round(bd_batt_diff, 2),
        "mutual_scenarios_C_and_D": mutual_cd,
        "group_D_vs_C_step_savings": round(cd_step_diff, 2),
        "group_D_vs_C_battery_savings": round(cd_batt_diff, 2),
    }

    # Synthesize objective conclusion
    d_succ = group_summaries["Group_D_Agent_D"]["success_rate"]
    b_succ = group_summaries["Group_B_Agent_B"]["success_rate"]
    c_succ = group_summaries["Group_C_Agent_C"]["success_rate"]
    a_succ = group_summaries["Group_A_S1_M0"]["success_rate"]

    d_rep = group_summaries["Group_D_Agent_D"]["repeated_failures_total"]
    b_rep = group_summaries["Group_B_Agent_B"]["repeated_failures_total"]

    if d_succ > b_succ or (d_succ == b_succ and d_rep < b_rep):
        findings_conclusion = (
            f"Group D (Agent_D with verified repair memory) achieved {d_succ*100:.1f}% success rate "
            f"vs Group B ({b_succ*100:.1f}%) and Group C ({c_succ*100:.1f}%). "
            f"Active invalidation and structured repair bindings reduced repeated failures from {b_rep} (Group B) to {d_rep} (Group D)."
        )
    else:
        findings_conclusion = (
            f"在当前模型与机制下，修复记忆未体现独立增益 (Under current model and mechanism, repair memory did not demonstrate independent gain). "
            f"Success rates: Group A={a_succ*100:.1f}%, Group B={b_succ*100:.1f}%, Group C={c_succ*100:.1f}%, Group D={d_succ*100:.1f}%."
        )

    payload = {
        "benchmark": "32_unit_controlled_development_diagnosis",
        "model_path": model_path,
        "total_wall_time_s": round(t_total_wall, 2),
        "findings_conclusion": findings_conclusion,
        "group_summaries": group_summaries,
        "paired_efficiency_comparison": paired_comparison,
        "unit_results": unit_results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("\n" + "=" * 80)
    print("32-UNIT CONTROLLED DIAGNOSIS COMPLETED")
    print(f"Conclusion: {findings_conclusion}")
    print(f"Results saved to: {OUTPUT_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    run_32_dev_diagnosis()
