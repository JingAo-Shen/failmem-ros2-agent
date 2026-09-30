#!/usr/bin/env python3
"""FailMem P2a/P2b Offline Replay & Objective Scoring Suite (v3.0).

Strict Replay Architecture:
1. Reconstructs and recomputes all physical evaluations and mechanism metrics
   strictly from raw timeline files:
   - doorway_perception.json
   - memory_events.json
   - attempt_*/action_result.json
   - attempt_*/stability_window.json
   - attempt_*/trajectory.json
   - attempt_*/online_feedback.json
2. Does NOT rely on episode_summary.json as truth. If episode_summary.json is present,
   it performs anti-tamper verification and flags any discrepancies.
3. If critical raw artifacts are missing, explicitly flags the episode as UNVERIFIABLE.
4. Uses shared verify_online_arrival from src.online_verifier and evaluate_navigation_episode
   from src.scoring_evaluator.
5. Emits replay_report.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
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
from src.online_verifier import verify_online_arrival


def replay_and_score_attempt(
    attempt_dir: Path,
    thresholds: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """Replay and re-score a single navigation attempt from raw offline artifacts.

    Returns:
        (valid: bool, result_dict: Optional[Dict], missing_artifacts: List[str])
    """
    missing: List[str] = []
    for req_file in ["action_result.json", "stability_window.json", "trajectory.json", "online_feedback.json"]:
        if not (attempt_dir / req_file).exists():
            missing.append(f"{attempt_dir.name}/{req_file}")

    if missing:
        return False, None, missing

    with open(attempt_dir / "action_result.json", "r", encoding="utf-8") as f:
        action_result = json.load(f)

    with open(attempt_dir / "stability_window.json", "r", encoding="utf-8") as f:
        window_data = json.load(f)

    with open(attempt_dir / "trajectory.json", "r", encoding="utf-8") as f:
        traj_data = json.load(f)

    with open(attempt_dir / "online_feedback.json", "r", encoding="utf-8") as f:
        online_feedback = json.load(f)

    target_goal = action_result.get("target_goal", [1.8, 0.0, 0.0])
    target_region = action_result.get("target_region", "room2_corridor_chokepoint")
    map_version = action_result.get("map_version", "chokepoint_world_v1")
    nav2_status = action_result.get("terminal_status_name", "UNKNOWN")
    exec_outcome = action_result.get("execution_outcome", "UNKNOWN")
    deadline_exceeded = bool(action_result.get("deadline_exceeded", False))
    safety_intervention = bool(action_result.get("safety_intervention", False))
    failure_reason = action_result.get("failure_reason")
    dispatch_time_sim = action_result.get("dispatch_time_sim")

    window_records = window_data.get("window_records", [])
    watchdog_triggered = bool(window_data.get("watchdog_triggered", False))

    # Extract final GT & AMCL from window or trajectory
    final_gt = window_records[-1].get("gt") if window_records else (
        traj_data.get("gt_trajectory", [{}])[-1] if traj_data.get("gt_trajectory") else None
    )
    final_amcl = online_feedback.get("amcl_pose")

    # Extract completion sim time
    completion_sim_time = (
        window_records[-1].get("sim_time") if window_records else (
            traj_data.get("odom_trajectory", [{}])[-1].get("msg_stamp_sec") if traj_data.get("odom_trajectory") else None
        )
    )
    if completion_sim_time is None and final_amcl:
        completion_sim_time = final_amcl.get("msg_stamp_sec", final_amcl.get("recv_sim_time_sec"))

    # 1. Recompute physical evaluation (GT only)
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
    eval_arrival = bool(recomputed_eval.get("strict_physical_arrival_and_stable", False))

    # 2. Recompute online public acceptance (Shared Non-GT online_verifier)
    recomputed_online_success, online_reasons, online_details = verify_online_arrival(
        target_goal=target_goal,
        online_feedback=online_feedback,
        thresholds=thresholds,
        sim_time=completion_sim_time,
        target_region=target_region,
        map_version=map_version,
    )

    # 3. Compute disagreement reason
    disagreement = compute_disagreement_reason(recomputed_online_success, eval_arrival, recomputed_eval)

    return True, {
        "attempt_dir": str(attempt_dir),
        "attempt_index": action_result.get("attempt_index", 1),
        "action_id": action_result.get("action_id"),
        "dispatch_time_sim": dispatch_time_sim,
        "dispatch_elapsed_sim": action_result.get("dispatch_elapsed_sim"),
        "target_goal": target_goal,
        "nav2_status": nav2_status,
        "execution_outcome": exec_outcome,
        "online_action_succeeded": recomputed_online_success,
        "online_failure_reasons": online_reasons,
        "evaluator_verified_success": eval_arrival,
        "disagreement_reason": disagreement,
        "recomputed_evaluation": recomputed_eval,
    }, []


def replay_and_score_episode(
    ep_dir: Path,
    thresholds: Dict[str, Any],
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Replay and re-score an entire episode strictly from raw artifacts with anti-tamper check."""
    ep_id = ep_dir.name
    missing_artifacts: List[str] = []

    # Check raw event logs
    perception_path = ep_dir / "doorway_perception.json"
    memory_events_path = ep_dir / "memory_events.json"

    if not perception_path.exists():
        missing_artifacts.append("doorway_perception.json")
    if not memory_events_path.exists():
        missing_artifacts.append("memory_events.json")

    # Discover attempt folders
    attempt_dirs = sorted(
        [d for d in ep_dir.iterdir() if d.is_dir() and d.name.startswith("attempt_")],
        key=lambda d: int(d.name.split("_")[-1]) if d.name.split("_")[-1].isdigit() else 999,
    )

    # If missing artifacts at root, mark UNVERIFIABLE
    if missing_artifacts:
        return {
            "episode_id": ep_id,
            "status": "UNVERIFIABLE",
            "unverifiable_reasons": [f"Missing required artifact: {m}" for m in missing_artifacts],
            "episode_valid": False,
        }

    # Load raw event logs
    with open(perception_path, "r", encoding="utf-8") as f:
        doorway_perceptions = json.load(f)

    with open(memory_events_path, "r", encoding="utf-8") as f:
        memory_events = json.load(f)

    # Parse condition/policy/sequence from directory name or memory_events
    parts = ep_id.split("_")
    policy_name = parts[0] if len(parts) >= 3 else "UNKNOWN"
    sequence_name = parts[1] if len(parts) >= 3 else "UNKNOWN"
    condition_id = f"{policy_name}_{sequence_name}"

    # Replay all attempts
    attempt_results: List[Dict[str, Any]] = []
    for ad in attempt_dirs:
        att_ok, att_res, att_missing = replay_and_score_attempt(ad, thresholds)
        if not att_ok:
            return {
                "episode_id": ep_id,
                "status": "UNVERIFIABLE",
                "unverifiable_reasons": [f"Missing attempt artifact: {m}" for m in att_missing],
                "episode_valid": False,
            }
        attempt_results.append(att_res)

    # Independent Metric Reconstruction
    navigation_attempt_count = len(attempt_results)
    observation_count = len(doorway_perceptions)

    # 1. Recompute suppression_count
    suppression_count = sum(
        1 for ev in memory_events
        if ev.get("event_type") == "DISPATCH_GATE_CHECK" and ev.get("allowed") is False
    )

    # 2. Recompute redundant_retries_count
    # A redundant retry is any navigation attempt > 1 dispatched while doorway was OCCUPIED
    redundant_retries_count = 0
    for att in attempt_results:
        att_idx = att.get("attempt_index", 1)
        if att_idx > 1:
            att_dispatch_sim = att.get("dispatch_time_sim", 0.0)
            # Find latest perception before or at dispatch
            preceding_obs = [
                obs for obs in doorway_perceptions
                if obs.get("sim_time", 0.0) <= (att_dispatch_sim + 0.1)
            ]
            if preceding_obs:
                latest_state = preceding_obs[-1].get("evaluation", {}).get("doorway_state")
                if latest_state == "OCCUPIED":
                    redundant_retries_count += 1

    # 3. Recompute success outcomes
    if attempt_results:
        final_attempt = attempt_results[-1]
        policy_reported_success = bool(final_attempt["online_action_succeeded"])
        evaluator_verified_success = any(bool(att["evaluator_verified_success"]) for att in attempt_results)
        disagreement_reason = final_attempt["disagreement_reason"]
    else:
        policy_reported_success = False
        evaluator_verified_success = False
        disagreement_reason = None

    task_success = evaluator_verified_success

    # 4. Reconstruct Memory Invalidation and Recovery Lifecycle
    invalidation_verified = False
    policy_reported_recovery = False
    evaluator_verified_recovery = (evaluator_verified_success is True and navigation_attempt_count >= 2)

    # Reconstruct timestamps
    exact_timestamps: Dict[str, Any] = {
        "failure_times": [],
        "invalidation_times": [],
        "recovery_dispatch_times": [],
        "recovery_success_times": [],
        "observation_stamps": [obs.get("sim_time") for obs in doorway_perceptions],
    }

    for ev in memory_events:
        pol_state = ev.get("policy_state", {})
        entries = pol_state.get("entries", [])
        for entry in entries:
            f_time = entry.get("failure_time")
            if f_time is not None and f_time not in exact_timestamps["failure_times"]:
                exact_timestamps["failure_times"].append(f_time)

            inv_time = entry.get("invalidation_time")
            if inv_time is not None:
                invalidation_verified = True
                if inv_time not in exact_timestamps["invalidation_times"]:
                    exact_timestamps["invalidation_times"].append(inv_time)

            rec_disp = entry.get("recovery_dispatch_time")
            if rec_disp is not None and rec_disp not in exact_timestamps["recovery_dispatch_times"]:
                exact_timestamps["recovery_dispatch_times"].append(rec_disp)

            rec_time = entry.get("recovery_time")
            if rec_time is not None and rec_time not in exact_timestamps["recovery_success_times"]:
                exact_timestamps["recovery_success_times"].append(rec_time)

        if pol_state.get("recovery_verified_count", 0) > 0:
            policy_reported_recovery = True

    # Reconstruct recovery from attempt results if invalidated
    if invalidation_verified:
        for att in attempt_results:
            if att.get("attempt_index", 1) >= 2:
                disp_sim = att.get("dispatch_time_sim")
                if disp_sim is not None and disp_sim not in exact_timestamps["recovery_dispatch_times"]:
                    exact_timestamps["recovery_dispatch_times"].append(disp_sim)
                if att.get("online_action_succeeded"):
                    policy_reported_recovery = True
                    comp_sim = att.get("recomputed_evaluation", {}).get("window_evaluation", {}).get("gt_samples_count")
                    # Use last sample time or amcl time
                    amcl_stamp = att.get("recomputed_evaluation", {}).get("final_geometric_errors", {})
                    # or dispatch_time_sim + window
                    if att.get("attempt_dir"):
                        try:
                            with open(Path(att["attempt_dir"]) / "online_feedback.json", "r") as f_onl:
                                onl_d = json.load(f_onl)
                                t_stamp = onl_d.get("amcl_pose", {}).get("msg_stamp_sec")
                                if t_stamp and t_stamp not in exact_timestamps["recovery_success_times"]:
                                    exact_timestamps["recovery_success_times"].append(t_stamp)
                        except Exception:
                            pass

    # 5. Causal Mechanism Verification
    episode_valid = True
    mechanism_verified = False

    if sequence_name == "S1":
        if policy_name == "M0":
            mechanism_verified = (task_success is False and navigation_attempt_count > 1 and redundant_retries_count >= 1)
        elif policy_name in ("M1", "M2"):
            mechanism_verified = (task_success is False and navigation_attempt_count == 1 and redundant_retries_count == 0 and suppression_count >= 1)
        elif policy_name == "M3":
            mechanism_verified = (task_success is False and navigation_attempt_count == 0 and suppression_count >= 1)
    elif sequence_name == "S2":
        if policy_name == "M0":
            mechanism_verified = (task_success is True and navigation_attempt_count >= 2)
        elif policy_name == "M1":
            mechanism_verified = (task_success is False and navigation_attempt_count == 1 and suppression_count >= 1)
        elif policy_name == "M2":
            mechanism_verified = (task_success is True and invalidation_verified is True and policy_reported_recovery is True and evaluator_verified_recovery is True)
        elif policy_name == "M3":
            mechanism_verified = (task_success is True and navigation_attempt_count == 1 and suppression_count >= 1)

    recomputed_result = {
        "episode_id": ep_id,
        "condition_id": condition_id,
        "policy_name": policy_name,
        "sequence_name": sequence_name,
        "status": "VERIFIED",
        "episode_valid": episode_valid,
        "policy_reported_success": policy_reported_success,
        "evaluator_verified_success": evaluator_verified_success,
        "disagreement_reason": disagreement_reason,
        "task_success": task_success,
        "mechanism_verified": mechanism_verified,
        "observation_count": observation_count,
        "suppression_count": suppression_count,
        "navigation_attempt_count": navigation_attempt_count,
        "redundant_retries_count": redundant_retries_count,
        "invalidation_verified": invalidation_verified,
        "policy_reported_recovery": policy_reported_recovery,
        "evaluator_verified_recovery": evaluator_verified_recovery,
        "exact_timestamps": exact_timestamps,
        "attempts": attempt_results,
    }

    # 6. Anti-Tamper Check against episode_summary.json
    summary_path = ep_dir / "episode_summary.json"
    tamper_detected = False
    discrepancies: List[Dict[str, Any]] = []

    if summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                stored_summary = json.load(f)

            check_fields = [
                "task_success",
                "mechanism_verified",
                "policy_reported_success",
                "evaluator_verified_success",
                "navigation_attempt_count",
                "suppression_count",
                "redundant_retries_count",
                "invalidation_verified",
                "policy_reported_recovery",
                "evaluator_verified_recovery",
            ]
            for fld in check_fields:
                stored_val = stored_summary.get(fld)
                recomputed_val = recomputed_result.get(fld)
                if stored_val != recomputed_val:
                    tamper_detected = True
                    discrepancies.append({
                        "field": fld,
                        "stored_value": stored_val,
                        "recomputed_value": recomputed_val,
                    })
        except Exception as e:
            tamper_detected = True
            discrepancies.append({"field": "episode_summary_corrupted", "error": str(e)})

    recomputed_result["tamper_detected"] = tamper_detected
    recomputed_result["discrepancies"] = discrepancies

    return recomputed_result


def main():
    parser = argparse.ArgumentParser(description="FailMem P2a/P2b Offline Replay & Scoring Suite")
    parser.add_argument("target_path", help="Path to episode dir or run dir containing episodes")
    parser.add_argument("--rules", default="configs/scoring_rules.yaml", help="Path to scoring rules YAML")
    args = parser.parse_args()

    scoring_rules = load_scoring_rules(args.rules)
    thresholds = scoring_rules.get("thresholds", {})

    target = Path(args.target_path)
    runtime_config: Optional[Dict[str, Any]] = None

    if (target / "runtime_config.json").exists():
        with open(target / "runtime_config.json", "r", encoding="utf-8") as f:
            runtime_config = json.load(f)

    if (target / "doorway_perception.json").exists() or (target / "attempt_1").exists():
        ep_dirs = [target]
    else:
        ep_dirs = sorted([
            d for d in target.iterdir()
            if d.is_dir() and ((d / "doorway_perception.json").exists() or (d / "episode_summary.json").exists() or (d / "attempt_1").exists())
        ])

    if not ep_dirs:
        print(f"[ERROR] No valid episode directories found in {target}")
        sys.exit(1)

    print(f"Replaying and independently scoring {len(ep_dirs)} episodes from: {target}...")
    results = []
    unverifiable_count = 0
    tampered_count = 0
    mech_verified_count = 0

    for ed in ep_dirs:
        res = replay_and_score_episode(ed, thresholds, runtime_config)
        results.append(res)
        if res.get("status") == "UNVERIFIABLE":
            unverifiable_count += 1
            print(f"[{res['episode_id']}] UNVERIFIABLE: {res.get('unverifiable_reasons')}")
        else:
            if res.get("tamper_detected"):
                tampered_count += 1
                print(f"[{res['episode_id']}] TAMPER DETECTED: {res.get('discrepancies')}")
            if res.get("mechanism_verified"):
                mech_verified_count += 1
            print(f"[{res['episode_id']}] Status: {res['status']}, PolicyOK: {res['policy_reported_success']}, EvalOK: {res['evaluator_verified_success']}, MechOK: {res['mechanism_verified']}, Attempts: {res['navigation_attempt_count']}, Suppressions: {res['suppression_count']}")

    replay_report = {
        "target_path": str(target),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_episodes_replayed": len(results),
        "verified_episodes": len(results) - unverifiable_count,
        "unverifiable_episodes": unverifiable_count,
        "tamper_detected_episodes": tampered_count,
        "mechanism_verified_episodes": mech_verified_count,
        "episodes": results,
    }

    report_out = target if target.is_dir() and not (target / "attempt_1").exists() else target.parent
    report_file = report_out / "replay_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(replay_report, f, indent=2)

    print(f"\nReplay Complete! Report written to: {report_file}")
    print(f"Summary: Total={len(results)}, MechVerified={mech_verified_count}/{len(results)}, Unverifiable={unverifiable_count}, Tampered={tampered_count}")


if __name__ == "__main__":
    main()
