#!/usr/bin/env python3
"""
R0 Minimal Reproduction Script (Revised per Research Lead Review):
Executes 8 authenticity audit checks, logs actual behaviors,
and saves outputs to the designated directory (default: reports/evidence/r0/run_artifacts/).
Supports custom output directory via --output-dir argument.
"""

import os
import sys
import json
import hashlib
import argparse
import subprocess
from datetime import datetime, timezone

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

def get_git_info():
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        is_dirty = len(status) > 0
        return {"commit": commit, "branch": branch, "is_dirty": is_dirty}
    except Exception as e:
        return {"commit": "unknown", "branch": "unknown", "error": str(e)}

def run_all_checks(output_dir: str = "reports/evidence/r0/run_artifacts"):
    os.makedirs(output_dir, exist_ok=True)
    git_info = get_git_info()
    findings = []

    # -------------------------------------------------------------
    # Check 1: verifier interface and event feedback check
    # -------------------------------------------------------------
    c1_dir_on = os.path.join(output_dir, "check1_ver_on")
    c1_dir_off = os.path.join(output_dir, "check1_ver_off")
    task_c1 = {
        "id": "c1_task",
        "goal_coord": [5.0, 0.0],
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

    has_verification_events = any(e.get("event_type") == "verification" or "verifier_feedback" in e for e in ev_on)
    ev_on_stripped = [{k: v for k, v in e.items() if k != "use_verifier"} for e in ev_on]
    ev_off_stripped = [{k: v for k, v in e.items() if k != "use_verifier"} for e in ev_off]
    identical_behavior = (ev_on_stripped == ev_off_stripped)

    findings.append({
        "check_id": 1,
        "name": "verifier_interface_and_feedback",
        "question": "相同输入下 verifier 开/关是否实际产生验证事件与可见反馈",
        "file": "src/evaluate.py:8-13,78,96",
        "defect_confirmed": (not has_verification_events and identical_behavior),
        "actual_behavior": (
            "use_verifier is only printed into logs and never used in logic. "
            "No verification events or agent feedback are emitted (has_verification_events=False). "
            f"Execution events (excluding echoed field) are identical: {identical_behavior}."
        ),
        "impact": "CRITICAL - Verifier toggle is not wired to any operational call path or feedback mechanism."
    })

    # -------------------------------------------------------------
    # Check 2: costmap-conditioned memory expiry on map update 1->2
    # -------------------------------------------------------------
    store = FailureMemoryStore()
    store.record_failure({
        "id": "mem_costmap_v1",
        "symptom": "ERROR: Path blocked by dynamic obstacle.",
        "recovery_action": "clear_costmap",
        "map_version": 1
    })
    retrieved_v1 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=1)
    retrieved_v2 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=2)
    store.close()

    findings.append({
        "check_id": 2,
        "name": "costmap_conditioned_memory_expiry",
        "question": "地图版本 1→2 后，依赖已改变条件的旧记忆是否仍被检索",
        "file": "src/failmem.py:44",
        "defect_confirmed": (retrieved_v2 is not None),
        "actual_behavior": (
            f"At map_ver=1, retrieved='{retrieved_v1}'. "
            f"When environment updates to map_ver=2, retrieved='{retrieved_v2}'. "
            "Line 44 uses 'map_ver <= current_map_version' (1 <= 2 is True), so old obstacle memories remain active."
        ),
        "impact": "CRITICAL - Invalidation rule fails to expire records conditioned on obsolete map versions."
    })

    # -------------------------------------------------------------
    # Check 3: unverified records defaulted to RECOVERED and retrieved
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

    store.record_failure({
        "id": "failed_record",
        "symptom": "symptom_y",
        "recovery_action": "clear_costmap",
        "verified_outcome": "FAILED"
    })
    retrieved_failed = store.retrieve_recovery("symptom_y", current_map_version=1)
    store.close()

    findings.append({
        "check_id": 3,
        "name": "unverified_default_and_filter",
        "question": "未提供验证证据的记录是否被默认视为恢复成功，检索时是否检查验证结果",
        "file": "src/failmem.py:29,38",
        "defect_confirmed": (stored_outcome == "RECOVERED" and retrieved_failed == "clear_costmap"),
        "actual_behavior": (
            f"Omitted verified_outcome defaulted to: '{stored_outcome}'. "
            f"Record with verified_outcome='FAILED' was retrieved as: '{retrieved_failed}'. "
            "SQL query lacks 'WHERE verified_outcome = RECOVERED' constraint."
        ),
        "impact": "CRITICAL - Memory store fails to isolate verified successes from unverified or failed recovery attempts."
    })

    # -------------------------------------------------------------
    # Check 4: fault exposure accounting for start==goal
    # -------------------------------------------------------------
    c4_dir = os.path.join(output_dir, "check4_exposure")
    task_c4 = {
        "id": "fixture_robot_01",
        "goal_coord": [0.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "fault_type": "path_blocked",
        "injected_fault_step": 2
    }
    m_c4 = run_evaluation([task_c4], use_memory=True, use_verifier=True, output_dir=c4_dir)
    with open(os.path.join(c4_dir, "events.jsonl")) as f:
        ev_c4 = json.loads(f.readline())

    findings.append({
        "check_id": 4,
        "name": "fault_exposure_accounting_start_equals_goal",
        "question": "起点等于终点时，任务是否在故障触发前结束，评测是否区分未暴露子集",
        "file": "data/task-specs.jsonl:1; src/evaluate.py:47-83",
        "defect_confirmed": (ev_c4["steps"] < 2 and ev_c4["passed"] and "fault_exposed" not in ev_c4),
        "actual_behavior": (
            f"Task succeeded at step {ev_c4['steps']} before reaching fault step 2. "
            f"Reported recovery_success_rate={m_c4['recovery_success_rate']}. "
            "Runner does not track fault exposure status; unexposed episodes are credited as recovery success."
        ),
        "impact": "HIGH - Benchmark conflates allocated episodes with exposed episodes; artificially elevates recovery rate."
    })

    # -------------------------------------------------------------
    # Check 5: fault persistence on active task
    # -------------------------------------------------------------
    task_c5 = {
        "id": "c5_active_task",
        "goal_coord": [5.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "fault_type": "path_blocked",
        "injected_fault_step": 2
    }
    env_c5 = RobotSimEnvironment(task_c5)
    s1, _, _ = env_c5.step("navigate")  # step 1: pos at [2,0], not success
    assert not env_c5.is_success(), "Task completed unexpectedly at step 1"
    s2, m2, _ = env_c5.step("navigate")  # step 2: fault triggers
    assert not env_c5.is_success()
    s3, m3, _ = env_c5.step("navigate")  # step 3: blind navigate without recovery

    findings.append({
        "check_id": 5,
        "name": "fault_persistence_on_active_task",
        "question": "故障后不采取有效恢复，仅继续导航是否也能通过（在仍未完成的任务上）",
        "file": "src/sim_env.py:29-37",
        "defect_confirmed": (not s2 and s3),
        "actual_behavior": (
            f"Active task (dist=5m): Step 2 fault: success={s2}, msg='{m2}'. "
            f"Step 3 blind navigate without recovery: success={s3}, msg='{m3}', pos={env_c5.pos.tolist()}. "
            "Fault is guarded strictly by 'step_count == injected_fault_step', vanishing immediately at step 3."
        ),
        "impact": "CRITICAL - Obstacles do not persist in environment; memory-less blind retry naturally passes."
    })

    # -------------------------------------------------------------
    # Check 6: target_moved parameter and state leakage
    # -------------------------------------------------------------
    task_c6 = {
        "id": "c6_active_task",
        "goal_coord": [5.0, 0.0],
        "initial_robot_pos": [0.0, 0.0],
        "fault_type": "target_moved",
        "injected_fault_step": 2
    }
    env_c6 = RobotSimEnvironment(task_c6)
    env_c6.step("navigate")  # step 1: moves to [2,0]
    s2, m2, _ = env_c6.step("navigate")  # step 2: self.goal updated to [6,1]
    pos_before = env_c6.pos.copy()
    s3, m3, _ = env_c6.step("navigate")  # step 3: agent passes params=None
    step_delta = env_c6.pos - pos_before
    leaked_y_delta = float(step_delta[1])

    findings.append({
        "check_id": 6,
        "name": "target_moved_parameter_and_state_leakage",
        "question": "目标移动后是否未经观察就使用新目标位置（参数与内部目标泄漏）",
        "file": "src/sim_env.py:26,33",
        "defect_confirmed": (leaked_y_delta > 0.0),
        "actual_behavior": (
            f"At step 2, target moved to {env_c6.goal.tolist()}. "
            "At step 3, agent called navigate() with no goal parameters. "
            f"Env defaulted target to internal self.goal: robot steered with dy={leaked_y_delta:.3f} "
            f"towards {env_c6.pos.tolist()} without receiving goal coordinates from agent."
        ),
        "impact": "CRITICAL - Environment leaks relocated target coordinates to agent without observation requirement."
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
    env_c7.step("navigate")  # reaches [1.0, 0.0]
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
        "impact": "HIGH - Implementation deviates from specification claiming distance < 0.3m AND stable 2s."
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
        "audit_version": "R0_revised_2026-09-26",
        "git": git_info,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
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
    parser = argparse.ArgumentParser(description="FailMem R0 Audit Reproduction Script")
    parser.add_argument("--output-dir", default="reports/evidence/r0/run_artifacts", help="Output directory for audit artifacts")
    args = parser.parse_args()
    run_all_checks(args.output_dir)
