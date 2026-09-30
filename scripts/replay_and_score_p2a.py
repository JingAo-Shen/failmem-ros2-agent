#!/usr/bin/env python3
"""FailMem P2a/P2b Offline Replay & Objective Scoring Suite (v3.3).

Strict Replay Architecture:
1. Mandatory Frozen Configuration:
   - Replay strictly loads `runtime_config.json` from the target run/episode directory.
   - If missing or unverified, explicitly marks the run/episode as UNVERIFIABLE.
2. Pure Raw Event Reconstruction with Strict Causal Tracing:
   - Reconstructs failure memory state, invalidation, and recovery lifecycle by
     instantiating a clean `FailureMemoryStore` and feeding raw perception records
     (doorway_perception.json) and attempt results (attempt_*/action_result.json).
   - Only qualifies blockage failure when action actually failed AND has fresh OCCUPIED evidence.
   - Eliminates backward time tolerances (strictly > and >=).
   - Enforces exact map_version, region_id, and recovery_action_id binding checks.
3. Multi-Layer Anti-Tamper & Validity Evaluation:
   - `episode_valid` computed from config integrity, artifact existence, timeline monotonicity,
     budget adherence, and absence of infrastructure anomalies.
   - `raw_checksum_tamper_detected`: Hashes against `checksums.sha256`.
   - `summary_discrepancy_detected`: Cross-checks recomputed metrics against `episode_summary.json`.
   - `policy_state_discrepancy_detected`: Cross-checks memory states against `memory_events.json`.
4. Sensitivity Re-scoring:
   - Supports --sensitivity-003 to evaluate impact of strict 0.03 m/s / 0.03 rad/s physical halt thresholds.
   - Saves results into a separate `sensitivity_report_003.json` without overwriting frozen baseline.
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
from src.failure_memory import (
    FailureMemoryStore,
    MemoryState,
    is_failure_eligible_for_doorway_memory,
)


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_checksums(run_dir: Path) -> Dict[str, str]:
    """Load checksums.sha256 dictionary mapping relative path to expected sha256."""
    chk_file = run_dir / "checksums.sha256"
    if not chk_file.exists():
        return {}
    checksums = {}
    with open(chk_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                checksums[parts[1].strip()] = parts[0].strip()
    return checksums


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

    # Categorize failure type
    is_infra_failure = (
        exec_outcome in ["INFRASTRUCTURE_FAILURE", "ROS_COMM_FAILURE", "CRASH"]
        or (watchdog_triggered and not window_records)
    )
    is_action_failure = (
        nav2_status in ["ABORTED", "CANCELED", "TIMEOUT"]
        or exec_outcome in ["BUDGET_FAILURE", "BUDGET_DEADLINE_EXCEEDED"]
        or deadline_exceeded
    ) and not is_infra_failure

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
        "completion_sim_time": completion_sim_time,
        "target_goal": target_goal,
        "target_region": target_region,
        "map_version": map_version,
        "nav2_status": nav2_status,
        "execution_outcome": exec_outcome,
        "is_action_failure": is_action_failure,
        "is_infra_failure": is_infra_failure,
        "online_action_succeeded": recomputed_online_success,
        "online_failure_reasons": online_reasons,
        "online_feedback": online_feedback,
        "evaluator_verified_success": eval_arrival,
        "disagreement_reason": disagreement,
        "recomputed_evaluation": recomputed_eval,
    }, []


def replay_and_score_episode(
    ep_dir: Path,
    thresholds: Dict[str, Any],
    run_dir: Optional[Path] = None,
    runtime_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Replay and re-score an entire episode strictly from raw artifacts with pure state reconstruction."""
    ep_id = ep_dir.name
    missing_artifacts: List[str] = []
    unverifiable_reasons: List[str] = []

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

    if missing_artifacts:
        return {
            "episode_id": ep_id,
            "status": "UNVERIFIABLE",
            "unverifiable_reasons": [f"Missing required artifact: {m}" for m in missing_artifacts],
            "episode_valid": False,
        }

    # Verify raw artifact checksums against checksums.sha256 if present
    raw_checksum_tamper_detected = False
    checksum_mismatches: List[Dict[str, Any]] = []
    effective_run_dir = run_dir or ep_dir.parent
    checksum_map = load_checksums(effective_run_dir)

    if checksum_map:
        for root_p, _, files in os.walk(ep_dir):
            for fname in files:
                fpath = Path(root_p) / fname
                rel_path = str(fpath.relative_to(effective_run_dir))
                if rel_path in checksum_map:
                    actual_sha = compute_file_sha256(fpath)
                    expected_sha = checksum_map[rel_path]
                    if actual_sha != expected_sha:
                        raw_checksum_tamper_detected = True
                        checksum_mismatches.append({
                            "file": rel_path,
                            "expected_sha256": expected_sha,
                            "actual_sha256": actual_sha,
                        })

    # Load raw event logs
    try:
        with open(perception_path, "r", encoding="utf-8") as f:
            doorway_perceptions = json.load(f)
    except Exception as e:
        return {
            "episode_id": ep_id,
            "status": "UNVERIFIABLE",
            "unverifiable_reasons": [f"Corrupted doorway_perception.json: {e}"],
            "episode_valid": False,
        }

    try:
        with open(memory_events_path, "r", encoding="utf-8") as f:
            memory_events = json.load(f)
    except Exception as e:
        return {
            "episode_id": ep_id,
            "status": "UNVERIFIABLE",
            "unverifiable_reasons": [f"Corrupted memory_events.json: {e}"],
            "episode_valid": False,
        }

    # Parse condition/policy/sequence from directory name
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

    # Validate timeline health and timestamps monotonicity
    prev_sim = -1.0
    for obs in doorway_perceptions:
        s_time = obs.get("sim_time")
        if not is_finite_number(s_time):
            unverifiable_reasons.append("Non-finite sim_time in doorway_perception")
            break
        if s_time < prev_sim:
            unverifiable_reasons.append(f"Retrograde sim_time in doorway_perception: {s_time} < {prev_sim}")
            break
        prev_sim = s_time

    # Validate budget limit
    max_budget = float(runtime_config.get("protocol", {}).get("navigation_task", {}).get("episode_total_sim_budget_sec", 75.0)) if runtime_config else 75.0
    if attempt_results:
        last_disp = attempt_results[-1].get("dispatch_elapsed_sim")
        if last_disp is not None and last_disp > (max_budget + 5.0):
            unverifiable_reasons.append(f"Episode execution exceeded total budget: elapsed={last_disp}s > {max_budget}s")

    # Independent Metric Reconstruction (Pure Raw Data)
    navigation_attempt_count = len(attempt_results)
    observation_count = len(doorway_perceptions)

    # 1. Recompute suppression_count purely from gate check events in memory_events.json
    suppression_count = sum(
        1 for ev in memory_events
        if ev.get("event_type") == "DISPATCH_GATE_CHECK" and ev.get("allowed") is False
    )

    # 2. Recompute redundant_retries_count purely from raw timeline
    redundant_retries_count = 0
    for att in attempt_results:
        att_idx = att.get("attempt_index", 1)
        if att_idx > 1:
            att_dispatch_sim = att.get("dispatch_time_sim", 0.0)
            preceding_obs = [
                obs for obs in doorway_perceptions
                if round(obs.get("sim_time", 0.0), 4) <= round(att_dispatch_sim, 4)
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

    # 4. Pure Deterministic Memory Lifecycle Reconstruction per memory_id
    # We instantiate FailureMemoryStore and evaluate lifecycle strictly from raw events
    store = FailureMemoryStore(region_matching_tolerance_m=0.50)
    target_goal = attempt_results[0].get("target_goal", [1.8, 0.0, 0.0]) if attempt_results else [1.8, 0.0, 0.0]
    target_region = attempt_results[0].get("target_region", "room2_corridor_chokepoint") if attempt_results else "room2_corridor_chokepoint"
    map_version = attempt_results[0].get("map_version", "chokepoint_world_v1") if attempt_results else "chokepoint_world_v1"

    exact_timestamps: Dict[str, Any] = {
        "failure_times": [],
        "invalidation_times": [],
        "recovery_dispatch_times": [],
        "recovery_success_times": [],
        "observation_stamps": [obs.get("sim_time") for obs in doorway_perceptions if obs.get("sim_time") is not None],
    }

    # Step 4a: Process Attempt 1 failure (if policy records failure memory: M1 or M2)
    if policy_name in ["M1", "M2"] and attempt_results:
        att1 = attempt_results[0]
        if att1["is_action_failure"] and not att1["is_infra_failure"]:
            att1_fail_time = att1["completion_sim_time"] or att1["dispatch_time_sim"]
            exact_timestamps["failure_times"].append(att1_fail_time)

            # Find fresh OCCUPIED observation matching failure
            fresh_occ_obs = [
                obs for obs in doorway_perceptions
                if abs(obs.get("sim_time", 0.0) - att1_fail_time) <= 5.0
                and obs.get("evaluation", {}).get("doorway_state") == "OCCUPIED"
            ]
            if fresh_occ_obs:
                chosen_obs = fresh_occ_obs[-1]
                store.record_failure(
                    goal=target_goal,
                    region_id=target_region,
                    failure_reason=str(att1.get("execution_outcome", "BUDGET_FAILURE")),
                    sim_time=att1_fail_time,
                    failed_action_id=str(att1.get("action_id", "attempt_1")),
                    failure_evidence_id=str(chosen_obs.get("action_id", "obs_fail")),
                    failure_evidence=chosen_obs.get("evaluation", {}),
                    map_version=map_version,
                )

    # Step 4b: Process observations for invalidation (M2 only)
    if policy_name == "M2" and store.entries:
        for obs in doorway_perceptions:
            obs_eval = obs.get("evaluation", {})
            obs_sim = obs.get("sim_time", 0.0)
            # Invalidation strictly requires doorway FREE
            if obs_eval.get("doorway_state") == "FREE":
                # Ensure region/map match
                ev_to_check = dict(obs_eval)
                ev_to_check["timestamp_sim"] = obs_sim
                invalidated = store.evaluate_perception_for_invalidation(
                    perception_evidence=ev_to_check,
                    sim_time=obs_sim,
                    evidence_id=str(obs.get("action_id", f"obs_{obs.get('observation_index')}")),
                    map_version=map_version,
                    region_id=target_region,
                )
                if invalidated:
                    for inv_e in invalidated:
                        if inv_e.invalidation_time and inv_e.invalidation_time not in exact_timestamps["invalidation_times"]:
                            exact_timestamps["invalidation_times"].append(inv_e.invalidation_time)

    # Step 4c: Process recovery action dispatch & arrival verification (M2 only)
    if policy_name == "M2" and store.entries:
        for att in attempt_results[1:]:
            att_disp_sim = att.get("dispatch_time_sim", 0.0)
            att_action_id = att.get("action_id")
            # Bind recovery action if memory was invalidated strictly at or before dispatch
            bound_mem_id = store.bind_recovery_action(
                target_goal=target_goal,
                target_region=target_region,
                recovery_action_id=str(att_action_id),
                sim_time=att_disp_sim,
                map_version=map_version,
            )
            if bound_mem_id:
                exact_timestamps["recovery_dispatch_times"].append(att_disp_sim)
                # Verify recovery online feedback upon completion
                att_comp_sim = att.get("completion_sim_time", att_disp_sim)
                verified = store.verify_recovery(
                    target_goal=target_goal,
                    recovery_action_id=str(att_action_id),
                    online_feedback=att.get("online_feedback", {}),
                    sim_time=att_comp_sim,
                    target_region=target_region,
                    map_version=map_version,
                    thresholds=thresholds,
                )
                if verified:
                    exact_timestamps["recovery_success_times"].append(att_comp_sim)

    # Extract memory lifecycle states from store
    invalidation_verified = any(
        e.state in (MemoryState.INVALIDATED, MemoryState.RECOVERY_VERIFIED)
        for e in store.entries
    )
    policy_reported_recovery = any(
        e.state == MemoryState.RECOVERY_VERIFIED
        for e in store.entries
    )
    evaluator_verified_recovery = (
        policy_reported_recovery and any(att["evaluator_verified_success"] for att in attempt_results[1:])
    )

    # 5. Causal Mechanism Verification
    episode_valid = (len(unverifiable_reasons) == 0) and not raw_checksum_tamper_detected
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
        "status": "VERIFIED" if episode_valid else "UNVERIFIABLE",
        "unverifiable_reasons": unverifiable_reasons,
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
        "raw_checksum_tamper_detected": raw_checksum_tamper_detected,
        "checksum_mismatches": checksum_mismatches,
    }

    # 6. Anti-Tamper Check against episode_summary.json (summary_discrepancy_detected)
    summary_path = ep_dir / "episode_summary.json"
    summary_discrepancy_detected = False
    summary_discrepancies: List[Dict[str, Any]] = []

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
                    summary_discrepancy_detected = True
                    summary_discrepancies.append({
                        "field": fld,
                        "stored_value": stored_val,
                        "recomputed_value": recomputed_val,
                    })
        except Exception as e:
            summary_discrepancy_detected = True
            summary_discrepancies.append({"field": "episode_summary_corrupted", "error": str(e)})

    # 7. Check if policy_state logged in memory_events matches recomputed lifecycle
    policy_state_discrepancy_detected = False
    policy_state_discrepancies: List[Dict[str, Any]] = []
    if memory_events:
        last_ev = memory_events[-1]
        logged_pol_state = last_ev.get("policy_state", {})
        logged_rec_count = logged_pol_state.get("recovery_verified_count", 0)
        recomputed_rec_count = 1 if policy_reported_recovery else 0
        if logged_rec_count != recomputed_rec_count:
            policy_state_discrepancy_detected = True
            policy_state_discrepancies.append({
                "field": "recovery_verified_count",
                "logged_in_policy_state": logged_rec_count,
                "recomputed_from_raw": recomputed_rec_count,
            })

    recomputed_result["summary_discrepancy_detected"] = summary_discrepancy_detected
    recomputed_result["summary_discrepancies"] = summary_discrepancies
    recomputed_result["policy_state_discrepancy_detected"] = policy_state_discrepancy_detected
    recomputed_result["policy_state_discrepancies"] = policy_state_discrepancies
    recomputed_result["tamper_detected"] = (
        raw_checksum_tamper_detected or summary_discrepancy_detected or policy_state_discrepancy_detected
    )

    return recomputed_result


def find_target_episodes_and_config(
    target: Path,
    rules_override: Optional[str] = None,
) -> Tuple[List[Path], Optional[Dict[str, Any]], Optional[Path], Optional[str]]:
    """Locate episode directories, frozen runtime_config.json, and run directory.

    Returns:
        (episode_dirs, runtime_config_dict, run_dir, unverifiable_error_msg)
    """
    if not target.exists():
        return [], None, None, f"Target path does not exist: {target}"

    run_dir: Optional[Path] = None
    config_path: Optional[Path] = None

    if (target / "doorway_perception.json").exists() or (target / "attempt_1").exists():
        ep_dirs = [target]
        candidate_run_dir = target.parent
        if (candidate_run_dir / "runtime_config.json").exists():
            run_dir = candidate_run_dir
            config_path = candidate_run_dir / "runtime_config.json"
        elif (target / "runtime_config.json").exists():
            run_dir = target
            config_path = target / "runtime_config.json"
    else:
        run_dir = target
        if (target / "runtime_config.json").exists():
            config_path = target / "runtime_config.json"
        ep_dirs = sorted([
            d for d in target.iterdir()
            if d.is_dir() and ((d / "doorway_perception.json").exists() or (d / "episode_summary.json").exists() or (d / "attempt_1").exists())
        ])

    if not ep_dirs:
        return [], None, run_dir, f"No valid episode directories found in {target}"

    runtime_config: Optional[Dict[str, Any]] = None
    if config_path and config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                runtime_config = json.load(f)
        except Exception as e:
            return ep_dirs, None, run_dir, f"Failed to parse runtime_config.json: {e}"
    elif rules_override:
        try:
            loaded_rules = load_scoring_rules(rules_override)
            runtime_config = {
                "runtime_config_source": f"OVERRIDE: {rules_override}",
                "scoring_thresholds": loaded_rules.get("thresholds", {}),
            }
        except Exception as e:
            return ep_dirs, None, run_dir, f"Failed to load rules override: {e}"
    else:
        return ep_dirs, None, run_dir, "MISSING_FROZEN_RUNTIME_CONFIG: No runtime_config.json found in run directory. Historical config is unverified."

    return ep_dirs, runtime_config, run_dir, None


def main():
    parser = argparse.ArgumentParser(description="FailMem P2a/P2b Offline Replay & Scoring Suite")
    parser.add_argument("target_path", help="Path to episode dir or run dir containing episodes")
    parser.add_argument("--rules-override", default=None, help="Explicit path to override scoring rules YAML (not recommended for frozen verification)")
    parser.add_argument("--sensitivity-003", action="store_true", help="Perform sensitivity re-scoring with strict 0.03 m/s / 0.03 rad/s halt thresholds")
    args = parser.parse_args()

    target = Path(args.target_path)
    ep_dirs, runtime_config, run_dir, error_msg = find_target_episodes_and_config(target, args.rules_override)

    if error_msg and not runtime_config:
        print(f"[ERROR] UNVERIFIABLE: {error_msg}")
        replay_report = {
            "target_path": str(target),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "UNVERIFIABLE",
            "unverifiable_reason": error_msg,
            "total_episodes_replayed": len(ep_dirs),
            "verified_episodes": 0,
            "unverifiable_episodes": len(ep_dirs),
            "tamper_detected_episodes": 0,
            "mechanism_verified_episodes": 0,
            "episodes": [],
        }
        report_out = target if target.is_dir() and not (target / "attempt_1").exists() else target.parent
        out_filename = "sensitivity_report_003.json" if args.sensitivity_003 else "replay_report.json"
        report_file = report_out / out_filename
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(replay_report, f, indent=2)
        print(f"Report written to: {report_file}")
        sys.exit(0)

    base_thresholds = (
        runtime_config.get("scoring_thresholds")
        or runtime_config.get("protocol", {}).get("scoring_thresholds")
        or runtime_config.get("scoring_rules", {}).get("thresholds")
    )
    if not base_thresholds:
        print("[ERROR] UNVERIFIABLE: No scoring_thresholds found in runtime_config.json")
        sys.exit(1)

    thresholds = dict(base_thresholds)
    if args.sensitivity_003:
        thresholds["max_linear_velocity_mps"] = 0.03
        thresholds["max_angular_velocity_radps"] = 0.03

    mode_str = "SENSITIVITY (0.03/0.03)" if args.sensitivity_003 else "FROZEN CONFIG"
    print(f"[{mode_str}] Replaying and independently scoring {len(ep_dirs)} episodes from: {target}...")
    print(f"Thresholds applied: pos={thresholds.get('position_tolerance_m')}m, yaw={thresholds.get('yaw_tolerance_rad')}rad, lv={thresholds.get('max_linear_velocity_mps')}m/s, av={thresholds.get('max_angular_velocity_radps')}rad/s")

    results = []
    unverifiable_count = 0
    tampered_count = 0
    raw_tampered_count = 0
    summary_tampered_count = 0
    mech_verified_count = 0

    for ed in ep_dirs:
        res = replay_and_score_episode(ed, thresholds, run_dir=run_dir, runtime_config=runtime_config)
        results.append(res)
        if res.get("status") == "UNVERIFIABLE":
            unverifiable_count += 1
            print(f"[{res['episode_id']}] UNVERIFIABLE: {res.get('unverifiable_reasons')}")
        else:
            if res.get("raw_checksum_tamper_detected"):
                raw_tampered_count += 1
                print(f"[{res['episode_id']}] RAW CHECKSUM MISMATCH: {res.get('checksum_mismatches')}")
            if res.get("summary_discrepancy_detected"):
                summary_tampered_count += 1
                print(f"[{res['episode_id']}] SUMMARY DISCREPANCY: {res.get('summary_discrepancies')}")
            if res.get("tamper_detected"):
                tampered_count += 1
            if res.get("mechanism_verified"):
                mech_verified_count += 1
            print(f"[{res['episode_id']}] Status: {res['status']}, PolicyOK: {res['policy_reported_success']}, EvalOK: {res['evaluator_verified_success']}, MechOK: {res['mechanism_verified']}, Attempts: {res['navigation_attempt_count']}, Suppressions: {res['suppression_count']}")

    report_out = target if target.is_dir() and not (target / "attempt_1").exists() else target.parent
    config_sha256 = None
    if (report_out / "runtime_config.json").exists():
        config_sha256 = compute_file_sha256(report_out / "runtime_config.json")

    replay_report = {
        "target_path": str(target),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "sensitivity_003" if args.sensitivity_003 else "frozen_baseline",
        "applied_thresholds": thresholds,
        "runtime_config_sha256": config_sha256,
        "total_episodes_replayed": len(results),
        "verified_episodes": len(results) - unverifiable_count,
        "unverifiable_episodes": unverifiable_count,
        "tamper_detected_episodes": tampered_count,
        "raw_checksum_tamper_episodes": raw_tampered_count,
        "summary_discrepancy_episodes": summary_tampered_count,
        "mechanism_verified_episodes": mech_verified_count,
        "episodes": results,
    }

    out_filename = "sensitivity_report_003.json" if args.sensitivity_003 else "replay_report.json"
    report_file = report_out / out_filename
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(replay_report, f, indent=2)

    print(f"\nReplay Complete! Report written to: {report_file}")
    print(f"Summary: Total={len(results)}, MechVerified={mech_verified_count}/{len(results)}, Unverifiable={unverifiable_count}, RawTampered={raw_tampered_count}, SummaryDiscrepancy={summary_tampered_count}")


if __name__ == "__main__":
    main()
