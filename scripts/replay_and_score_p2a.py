#!/usr/bin/env python3
"""FailMem P2a-v3 Offline Replay & Objective Scoring Script.

Reads stored per-attempt evidence artifacts (action_result.json, trajectory.json,
stability_window.json, online_feedback.json) from episode directories,
recomputes physical evaluation and mechanism verification strictly offline
without requiring Gazebo or ROS 2 daemon execution.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scoring_evaluator import (
    evaluate_navigation_episode,
    compute_disagreement_reason,
    load_scoring_rules,
    normalize_angle,
    is_finite_number,
)


def replay_and_score_attempt(
    attempt_dir: Path,
    thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """Replay and re-score a single navigation attempt from offline artifacts."""
    with open(attempt_dir / "action_result.json", "r", encoding="utf-8") as f:
        action_result = json.load(f)

    with open(attempt_dir / "stability_window.json", "r", encoding="utf-8") as f:
        window_data = json.load(f)

    with open(attempt_dir / "trajectory.json", "r", encoding="utf-8") as f:
        traj_data = json.load(f)

    with open(attempt_dir / "online_feedback.json", "r", encoding="utf-8") as f:
        online_feedback = json.load(f)

    target_goal = action_result.get("target_goal", [1.8, 0.0, 0.0])
    nav2_status = action_result.get("terminal_status_name", "UNKNOWN")
    exec_outcome = action_result.get("execution_outcome", "UNKNOWN")
    deadline_exceeded = action_result.get("deadline_exceeded", False)
    safety_intervention = action_result.get("safety_intervention", False)
    failure_reason = action_result.get("failure_reason")

    window_records = window_data.get("window_records", [])
    watchdog_triggered = window_data.get("watchdog_triggered", False)

    # Extract final GT & AMCL from window or trajectory
    final_gt = window_records[-1].get("gt") if window_records else (
        traj_data.get("gt_trajectory", [{}])[-1] if traj_data.get("gt_trajectory") else None
    )
    final_amcl = online_feedback.get("amcl_pose")

    # Recompute physical evaluation
    recomputed_eval = evaluate_navigation_episode(
        target_goal=target_goal,
        nav2_status=nav2_status,
        final_gt=final_gt,
        final_amcl=final_amcl,
        stability_samples=window_records,
        thresholds=thresholds,
        watchdog_triggered=watchdog_triggered,
        safety_intervention=safety_intervention,
        execution_outcome=exec_outcome,
        deadline_exceeded=deadline_exceeded,
        failure_reason=failure_reason,
    )

    # Recompute online public acceptance
    amcl_ok = False
    if final_amcl and is_finite_number(final_amcl.get("x")) and is_finite_number(final_amcl.get("y")) and is_finite_number(final_amcl.get("yaw")):
        d_pos = math.hypot(final_amcl["x"] - target_goal[0], final_amcl["y"] - target_goal[1])
        d_yaw = abs(normalize_angle(final_amcl["yaw"] - target_goal[2]))
        if d_pos <= (float(thresholds.get("position_tolerance_m", 0.30)) + 0.15) and d_yaw <= (float(thresholds.get("yaw_tolerance_rad", 0.35)) + 0.20):
            amcl_ok = True

    halt_vel = online_feedback.get("halt_velocity", {})
    vel_ok = False
    if halt_vel and is_finite_number(halt_vel.get("linear_v")) and is_finite_number(halt_vel.get("angular_v")):
        if abs(float(halt_vel["linear_v"])) <= 0.03 and abs(float(halt_vel["angular_v"])) <= 0.03:
            vel_ok = True

    recomputed_online_success = (
        exec_outcome == "BUDGET_SUCCESS"
        and nav2_status == "SUCCEEDED"
        and not deadline_exceeded
        and amcl_ok
        and vel_ok
    )

    eval_arrival = recomputed_eval.get("strict_physical_arrival_and_stable", False)
    disagreement = compute_disagreement_reason(recomputed_online_success, eval_arrival, recomputed_eval)

    return {
        "attempt_dir": str(attempt_dir),
        "target_goal": target_goal,
        "nav2_status": nav2_status,
        "execution_outcome": exec_outcome,
        "online_action_succeeded": recomputed_online_success,
        "evaluator_verified_success": eval_arrival,
        "disagreement_reason": disagreement,
        "recomputed_evaluation": recomputed_eval,
    }


def replay_and_score_episode(
    ep_dir: Path,
    thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """Replay and re-score an entire episode from its summary and attempt folders."""
    with open(ep_dir / "episode_summary.json", "r", encoding="utf-8") as f:
        stored_summary = json.load(f)

    condition_id = stored_summary["condition_id"]
    policy_name = stored_summary["policy_name"]
    sequence_name = stored_summary["sequence_name"]
    ep_id = stored_summary["episode_id"]

    # Locate all attempt_* folders
    attempt_dirs = sorted(
        [d for d in ep_dir.iterdir() if d.is_dir() and d.name.startswith("attempt_")],
        key=lambda d: int(d.name.split("_")[-1]) if d.name.split("_")[-1].isdigit() else 999,
    )

    attempt_results = []
    for ad in attempt_dirs:
        att_res = replay_and_score_attempt(ad, thresholds)
        attempt_results.append(att_res)

    # Determine final outcome
    if attempt_results:
        final_attempt = attempt_results[-1]
        policy_reported_success = final_attempt["online_action_succeeded"]
        evaluator_verified_success = final_attempt["evaluator_verified_success"]
        disagreement_reason = final_attempt["disagreement_reason"]
    else:
        policy_reported_success = False
        evaluator_verified_success = False
        disagreement_reason = None

    task_success = evaluator_verified_success
    navigation_attempt_count = len(attempt_results)
    redundant_retries_count = stored_summary.get("redundant_retries_count", 0)
    suppression_count = stored_summary.get("suppression_count", 0)
    invalidation_verified = stored_summary.get("invalidation_verified", False)
    policy_reported_recovery = stored_summary.get("policy_reported_recovery", False)
    evaluator_verified_recovery = (evaluator_verified_success is True and navigation_attempt_count >= 2)

    # Determine causal mechanism verification
    mechanism_verified = False
    episode_valid = stored_summary.get("episode_valid", True)

    if episode_valid:
        if sequence_name == "S1":
            if policy_name == "M0":
                mechanism_verified = (task_success is False and navigation_attempt_count > 1 and redundant_retries_count >= 1)
            elif policy_name in ("M1", "M2"):
                mechanism_verified = (task_success is False and navigation_attempt_count == 1 and redundant_retries_count == 0 and suppression_count >= 1)
        elif sequence_name == "S2":
            if policy_name == "M0":
                mechanism_verified = (task_success is True and navigation_attempt_count >= 2)
            elif policy_name == "M1":
                mechanism_verified = (task_success is False and navigation_attempt_count == 1 and suppression_count >= 1)
            elif policy_name == "M2":
                mechanism_verified = (task_success is True and invalidation_verified is True and policy_reported_recovery is True and evaluator_verified_recovery is True)

    # Verify match with stored summary
    assert task_success == stored_summary.get("task_success"), f"Task success mismatch in {ep_id}: {task_success} != {stored_summary.get('task_success')}"
    assert mechanism_verified == stored_summary.get("mechanism_verified"), f"Mechanism verified mismatch in {ep_id}: {mechanism_verified} != {stored_summary.get('mechanism_verified')}"

    return {
        "episode_id": ep_id,
        "condition_id": condition_id,
        "policy_name": policy_name,
        "sequence_name": sequence_name,
        "episode_valid": episode_valid,
        "policy_reported_success": policy_reported_success,
        "evaluator_verified_success": evaluator_verified_success,
        "disagreement_reason": disagreement_reason,
        "task_success": task_success,
        "mechanism_verified": mechanism_verified,
        "navigation_attempt_count": navigation_attempt_count,
        "suppression_count": suppression_count,
        "attempts": attempt_results,
    }


def main():
    parser = argparse.ArgumentParser(description="FailMem P2a-v3 Offline Replay & Scoring")
    parser.add_argument("target_path", help="Path to episode dir or run dir containing episodes")
    parser.add_argument("--rules", default="configs/scoring_rules.yaml", help="Path to scoring rules YAML")
    args = parser.parse_args()

    scoring_rules = load_scoring_rules(args.rules)
    thresholds = scoring_rules.get("thresholds", {})

    target = Path(args.target_path)
    if (target / "episode_summary.json").exists():
        ep_dirs = [target]
    else:
        ep_dirs = sorted([d for d in target.iterdir() if d.is_dir() and (d / "episode_summary.json").exists()])

    if not ep_dirs:
        print(f"[ERROR] No episode directories found in {target}")
        sys.exit(1)

    print(f"Replaying and scoring {len(ep_dirs)} episodes from: {target}...")
    results = []
    for ed in ep_dirs:
        res = replay_and_score_episode(ed, thresholds)
        results.append(res)
        print(f"[{res['episode_id']}] PolicyOK: {res['policy_reported_success']}, EvalOK: {res['evaluator_verified_success']}, MechOK: {res['mechanism_verified']}, Attempts: {res['navigation_attempt_count']}")

    print("\nOffline Replay & Scoring Verification PASSED for all episodes!")


if __name__ == "__main__":
    main()
