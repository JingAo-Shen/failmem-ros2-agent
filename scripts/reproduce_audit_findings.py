#!/usr/bin/env python3
"""
R0 Minimal Reproduction Script
Executes all 8 authenticity audit checks, logs actual behaviors,
and saves outputs to runs/audit_r0/.
"""

import os
import sys
import json
import hashlib

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from src.sim_env import RobotSimEnvironment
from src.failmem import FailureMemoryStore
from src.evaluate import run_evaluation

def sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def run_all_checks(output_dir: str = "runs/audit_r0"):
    os.makedirs(output_dir, exist_ok=True)
    findings = []

    # -------------------------------------------------------------
    # Check 1: verifier toggle impact
    # -------------------------------------------------------------
    c1_dir_on = os.path.join(output_dir, "check1_ver_on")
    c1_dir_off = os.path.join(output_dir, "check1_ver_off")
    task_c1 = {
        "id": "c1_task",
        "goal_coord": [2.0, 2.0],
        "initial_robot_pos": [0.0, 0.0],
        "fault_type": "path_blocked",
        "injected_fault_step": 2
    }
    m_on = run_evaluation([task_c1], use_memory=True, use_verifier=True, output_dir=c1_dir_on)
    m_off = run_evaluation([task_c1], use_memory=True, use_verifier=False, output_dir=c1_dir_off)

    with open(os.path.join(c1_dir_on, "events.jsonl")) as f:
        ev_on = [json.loads(line) for line in f]
    with open(os.path.join(c1_dir_off, "events.jsonl")) as f:
        ev_off = [json.loads(line) for line in f]

    # Verify if actions/events differ (ignoring the echoed 'use_verifier' key itself)
    ev_on_stripped = [{k: v for k, v in e.items() if k != "use_verifier"} for e in ev_on]
    ev_off_stripped = [{k: v for k, v in e.items() if k != "use_verifier"} for e in ev_off]
    identical_behavior = (ev_on_stripped == ev_off_stripped)

    findings.append({
        "check_id": 1,
        "name": "verifier_toggle_impact",
        "question": "相同输入下 verifier 开/关是否实际改变验证事件与可见反馈",
        "file": "src/evaluate.py",
        "defect_confirmed": identical_behavior,
        "actual_behavior": (
            "use_verifier is only printed into logs and never used in logic. "
            f"Execution events (excluding echoed field) are identical: {identical_behavior}. "
            f"Metrics VerON={m_on['recovery_success_rate']} vs VerOFF={m_off['recovery_success_rate']}."
        ),
        "impact": "CRITICAL - Verifier toggle is completely cosmetic; claims of verifier ablation have 0 empirical validity."
    })

    # -------------------------------------------------------------
    # Check 2: map_version 1 -> 2 expiry failure
    # -------------------------------------------------------------
    store = FailureMemoryStore()
    store.record_failure({
        "id": "m1",
        "symptom": "ERROR: Path blocked by dynamic obstacle.",
        "recovery_action": "clear_costmap",
        "map_version": 1
    })
    retrieved_v1 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=1)
    retrieved_v2 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=2)
    store.close()

    findings.append({
        "check_id": 2,
        "name": "map_version_update_retrieval",
        "question": "地图版本 1→2 后旧记忆是否仍被检索",
        "file": "src/failmem.py:44",
        "defect_confirmed": (retrieved_v2 is not None),
        "actual_behavior": (
            f"At map_ver=1, retrieved={retrieved_v1}. "
            f"When map changes to map_ver=2, retrieved={retrieved_v2}. "
            "Line 44 uses 'map_ver <= current_map_version' (1 <= 2 is True), so old memories are never expired."
        ),
        "impact": "CRITICAL - Expiration logic is backwards; stale memories from old maps remain permanently valid."
    })

    # -------------------------------------------------------------
    # Check 3: unverified records defaulted to RECOVERED
    # -------------------------------------------------------------
    store = FailureMemoryStore()
    store.record_failure({
        "id": "unverified_record",
        "symptom": "symptom_x",
        "recovery_action": "clear_costmap"
    })
    c = store.conn.cursor()
    c.execute("SELECT verified_outcome FROM failure_records WHERE id = 'unverified_record'")
    stored_outcome = c.fetchone()[0]

    # Also test if failed outcome is retrieved
    store.record_failure({
        "id": "failed_record",
        "symptom": "symptom_y",
        "recovery_action": "do_nothing",
        "verified_outcome": "FAILED"
    })
    retrieved_failed = store.retrieve_recovery("symptom_y", current_map_version=1)
    store.close()

    findings.append({
        "check_id": 3,
        "name": "unverified_default_and_filter",
        "question": "未提供验证证据的记录是否被默认视为恢复成功，检索时是否检查验证结果",
        "file": "src/failmem.py:29,38",
        "defect_confirmed": (stored_outcome == "RECOVERED" and retrieved_failed == "do_nothing"),
        "actual_behavior": (
            f"Omitted verified_outcome defaulted to: '{stored_outcome}'. "
            f"Record with verified_outcome='FAILED' was retrieved as: '{retrieved_failed}'. "
            "SQL query has no 'WHERE verified_outcome = RECOVERED' condition."
        ),
        "impact": "CRITICAL - Memory store cannot distinguish between verified and failed recovery actions."
    })

    # -------------------------------------------------------------
    # Check 4: start == goal bypasses fault injection
    # -------------------------------------------------------------
    task_c4 = {
        "id": "fixture_robot_01",
        "goal_coord": [0.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "injected_fault_step": 2
    }
    env_c4 = RobotSimEnvironment(task_c4)
    step0_succ = env_c4.is_success()
    s1, m1, _ = env_c4.step("navigate")
    step1_succ = env_c4.is_success()

    findings.append({
        "check_id": 4,
        "name": "start_equals_goal_early_pass",
        "question": "起点等于终点时，任务是否在故障触发前结束",
        "file": "data/task-specs.jsonl:1,11; src/sim_env.py:44,58",
        "defect_confirmed": (step0_succ and step1_succ and env_c4.step_count < 2),
        "actual_behavior": (
            f"At step 0 before movement, is_success={step0_succ}. "
            f"At step 1, step('navigate') returns '{m1}', is_success={step1_succ}. "
            f"Task completes at step {env_c4.step_count} before reaching fault step 2."
        ),
        "impact": "HIGH - In fixtures and test episodes (8.3% of tasks), robot succeeds without encountering injected fault."
    })

    # -------------------------------------------------------------
    # Check 5: fault vanishes after 1 step, enabling blind navigate
    # -------------------------------------------------------------
    task_c5 = {
        "id": "c5_task",
        "goal_coord": [2.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "fault_type": "path_blocked",
        "injected_fault_step": 2
    }
    env_c5 = RobotSimEnvironment(task_c5)
    env_c5.step("navigate") # step 1
    s2, m2, _ = env_c5.step("navigate") # step 2: fault triggers
    s3, m3, _ = env_c5.step("navigate") # step 3: blind navigate without recovery

    findings.append({
        "check_id": 5,
        "name": "fault_transient_blind_pass",
        "question": "故障后不采取有效恢复，仅继续导航是否也能通过",
        "file": "src/sim_env.py:29-37",
        "defect_confirmed": (not s2 and s3),
        "actual_behavior": (
            f"Step 2 fault: success={s2}, msg='{m2}'. "
            f"Step 3 blind navigate: success={s3}, msg='{m3}', is_success={env_c5.is_success()}. "
            "Fault condition is guarded by 'if step_count == injected_fault_step', vanishing at step+1."
        ),
        "impact": "CRITICAL - Obstacles do not persist. Baselines with no memory/recovery naturally pass by simply waiting/retrying."
    })

    # -------------------------------------------------------------
    # Check 6: target_moved ground truth leakage
    # -------------------------------------------------------------
    task_c6 = {
        "id": "c6_task",
        "goal_coord": [2.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "fault_type": "target_moved",
        "injected_fault_step": 2
    }
    env_c6 = RobotSimEnvironment(task_c6)
    env_c6.step("navigate") # step 1
    s2, m2, _ = env_c6.step("navigate") # step 2: target relocates to [3.0, 1.0]
    s3, m3, _ = env_c6.step("navigate") # step 3: agent navigates without params

    findings.append({
        "check_id": 6,
        "name": "target_moved_ground_truth_leakage",
        "question": "目标移动后是否未经观察就使用新目标位置",
        "file": "src/sim_env.py:26,33",
        "defect_confirmed": (env_c6.is_success() and np.allclose(env_c6.pos, [3.0, 1.0])),
        "actual_behavior": (
            f"At step 2, target moved to {env_c6.goal.tolist()}. "
            f"At step 3, agent called navigate() with no parameters. "
            f"Env defaulted target to internal self.goal: robot reached {env_c6.pos.tolist()}, is_success={env_c6.is_success()}."
        ),
        "impact": "CRITICAL - Omniscient goal leakage completely removes the need for target observation or active search."
    })

    # -------------------------------------------------------------
    # Check 7: missing stabilization time and observe check
    # -------------------------------------------------------------
    task_c7 = {
        "id": "c7_task",
        "goal_coord": [1.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "injected_fault_step": 99
    }
    env_c7 = RobotSimEnvironment(task_c7)
    env_c7.step("navigate") # reaches [1.0, 0.0]
    is_succ_c7 = env_c7.is_success()

    findings.append({
        "check_id": 7,
        "name": "success_condition_missing_checks",
        "question": "未执行 observe 或未满足稳定时间是否仍被判成功",
        "file": "src/sim_env.py:58-59",
        "defect_confirmed": is_succ_c7,
        "actual_behavior": (
            f"is_success() returns {is_succ_c7} immediately upon distance < 0.3m. "
            "No check for observe() call, and no 2-second stabilization verification."
        ),
        "impact": "HIGH - Contradicts claims in feasibility.md (到达距离 < 0.3m 且稳定 2s)."
    })

    # -------------------------------------------------------------
    # Check 8: empty task set returns 0.0 instead of null
    # -------------------------------------------------------------
    c8_dir = os.path.join(output_dir, "check8_empty")
    m_c8 = run_evaluation([], output_dir=c8_dir)

    findings.append({
        "check_id": 8,
        "name": "empty_task_metrics_zero_division",
        "question": "空任务集的指标是否错误输出 0，而不是无定义状态",
        "file": "src/evaluate.py:87-94",
        "defect_confirmed": (m_c8["recovery_success_rate"] == 0.0 and m_c8["repeat_failure_rate"] == 0.0),
        "actual_behavior": (
            f"When task list is empty, recovery_success_rate={m_c8['recovery_success_rate']}, "
            f"repeat_failure_rate={m_c8['repeat_failure_rate']}. "
            "Formula uses max(total, 1), converting undefined ratio 0/0 into 0.0."
        ),
        "impact": "MEDIUM - Violates EXECUTION-CONTRACT.md line 43 ('分母为 0 时输出 null，不能当成 0%')."
    })

    # Save detailed JSON evidence
    evidence_path = os.path.join(output_dir, "reproduction_evidence.json")
    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, ensure_ascii=False)

    summary_path = os.path.join(output_dir, "audit_summary.json")
    summary = {
        "total_checks": len(findings),
        "defects_confirmed": sum(1 for f in findings if f["defect_confirmed"]),
        "findings": findings
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Audit completed: {summary['defects_confirmed']}/{summary['total_checks']} defects confirmed.")
    print(f"Evidence saved to: {evidence_path} (SHA256: {sha256_file(evidence_path)})")
    print(f"Summary saved to: {summary_path} (SHA256: {sha256_file(summary_path)})")

if __name__ == "__main__":
    run_all_checks()
