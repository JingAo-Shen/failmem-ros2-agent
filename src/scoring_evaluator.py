"""FailMem Offline Objective Scoring Evaluator.

Extracts all evaluation rules and thresholds from configs/scoring_rules.yaml.
Strictly evaluates:
1. Sensor freshness and integrity (GT, odom, cmd_vel; rejects NaN/Inf/expired/future/retrograde/missing/duplicate samples).
2. Independent source sequence and timestamp tracking for Odom and GT.
3. Physical halt and stability window coverage (strictly >= 2.0s sim time, odom velocity < 0.05, GT displacement <= max_gt_displacement_m).
4. Contract arrival tolerance (strictly 0.30m position, 0.35rad yaw, no silent relaxation).
5. Cancellation safety test (pre-cancel active motion, acceptance, CANCELED status, no safety intervention, 2.0s halt).
6. Time-aligned AMCL vs GT localization audit (delta t <= 0.1s).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
import yaml


def normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi]."""
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def load_scoring_rules(config_path: str = "configs/scoring_rules.yaml") -> Dict[str, Any]:
    """Load scoring rules configuration file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_finite_number(val: Any) -> bool:
    """Check if value is a finite number (not None, not NaN, not Inf, not bool)."""
    if val is None or isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    return math.isfinite(val)


def evaluate_sensor_freshness_and_window(
    stability_samples: List[Dict[str, Any]],
    thresholds: Dict[str, Any],
    watchdog_triggered: bool = False,
) -> Dict[str, Any]:
    """Evaluate stability window coverage, freshness, independent sensor source updates, and integrity."""
    min_duration = float(thresholds.get("stability_window_duration_sim_sec", 2.0))
    max_staleness = float(thresholds.get("max_sensor_staleness_sim_sec", 0.5))

    if not stability_samples:
        return {
            "window_valid": False,
            "failure_reasons": ["NO_SAMPLES_RECORDED"],
            "sim_duration_covered": 0.0,
            "odom_duration_covered": 0.0,
            "gt_duration_covered": 0.0,
            "unique_samples_count": 0,
            "unique_odom_count": 0,
            "unique_gt_count": 0,
            "max_sampling_interval_sec": None,
            "data_fresh": False,
            "watchdog_triggered": watchdog_triggered,
        }

    if watchdog_triggered:
        return {
            "window_valid": False,
            "failure_reasons": ["WATCHDOG_TRIGGERED_EARLY_EXIT"],
            "sim_duration_covered": 0.0,
            "odom_duration_covered": 0.0,
            "gt_duration_covered": 0.0,
            "unique_samples_count": len(stability_samples),
            "unique_odom_count": 0,
            "unique_gt_count": 0,
            "max_sampling_interval_sec": None,
            "data_fresh": False,
            "watchdog_triggered": True,
        }

    failure_reasons = []

    # 1. Per-sample integrity, finite timestamps, monotonicity, and staleness
    prev_sim_time = None
    prev_odom_stamp = None
    prev_gt_stamp = None

    seen_odom_keys = set()
    seen_gt_keys = set()
    unique_odom_stamps = []
    unique_gt_stamps = []
    unique_samples = []
    seen_combined_keys = set()

    for idx, s in enumerate(stability_samples):
        sim_time = s.get("sim_time")
        if not is_finite_number(sim_time):
            failure_reasons.append(f"NON_FINITE_SIM_TIME_AT_SAMPLE_{idx}")
            continue

        if prev_sim_time is not None and sim_time < prev_sim_time:
            failure_reasons.append(f"RETROGRADE_SIM_TIME_AT_SAMPLE_{idx} ({sim_time} < {prev_sim_time})")
        prev_sim_time = sim_time

        gt = s.get("gt")
        odom = s.get("odom")

        if gt is None:
            failure_reasons.append(f"MISSING_GT_AT_SAMPLE_{idx}")
        if odom is None:
            failure_reasons.append(f"MISSING_ODOM_AT_SAMPLE_{idx}")

        # Check Odom specifics
        odom_key = None
        if odom is not None:
            odom_stamp = odom.get("msg_stamp_sec")
            if not is_finite_number(odom_stamp):
                failure_reasons.append(f"NON_FINITE_OR_MISSING_ODOM_STAMP_AT_SAMPLE_{idx}")
            else:
                # Monotonicity check
                if prev_odom_stamp is not None and odom_stamp < prev_odom_stamp:
                    failure_reasons.append(f"RETROGRADE_ODOM_STAMP_AT_SAMPLE_{idx} ({odom_stamp} < {prev_odom_stamp})")
                prev_odom_stamp = odom_stamp

                # Future timestamp check (relative to sampling sim time, allowing 0.15s clock discretization jitter)
                if odom_stamp > (sim_time + 0.15):
                    failure_reasons.append(f"FUTURE_ODOM_STAMP_AT_SAMPLE_{idx} ({odom_stamp} > {sim_time})")

                # Staleness check
                odom_staleness = sim_time - odom_stamp
                if odom_staleness > max_staleness:
                    failure_reasons.append(f"EXPIRED_ODOM_STAMP_AT_SAMPLE_{idx} ({odom_staleness:.3f}s > {max_staleness}s)")

                # Finite coordinates and velocities
                for fld in ["x", "y", "yaw"]:
                    if not is_finite_number(odom.get(fld)):
                        failure_reasons.append(f"NON_FINITE_ODOM_{fld.upper()}_AT_SAMPLE_{idx}")
                for vfld in ["linear_v", "angular_v"]:
                    if not is_finite_number(odom.get(vfld)):
                        failure_reasons.append(f"NON_FINITE_ODOM_{vfld.upper()}_AT_SAMPLE_{idx}")

                odom_seq = odom.get("seq")
                odom_key = (odom_seq, round(odom_stamp, 4))
                if odom_key not in seen_odom_keys:
                    seen_odom_keys.add(odom_key)
                    unique_odom_stamps.append(round(odom_stamp, 4))

        # Check GT specifics
        gt_key = None
        if gt is not None:
            gt_stamp = gt.get("recv_sim_time_sec")
            if not is_finite_number(gt_stamp):
                failure_reasons.append(f"NON_FINITE_OR_MISSING_GT_STAMP_AT_SAMPLE_{idx}")
            else:
                # Monotonicity check
                if prev_gt_stamp is not None and gt_stamp < prev_gt_stamp:
                    failure_reasons.append(f"RETROGRADE_GT_STAMP_AT_SAMPLE_{idx} ({gt_stamp} < {prev_gt_stamp})")
                prev_gt_stamp = gt_stamp

                # Future timestamp check
                if gt_stamp > (sim_time + 0.15):
                    failure_reasons.append(f"FUTURE_GT_STAMP_AT_SAMPLE_{idx} ({gt_stamp} > {sim_time})")

                # Staleness check
                gt_staleness = abs(sim_time - gt_stamp)
                if gt_staleness > max_staleness:
                    failure_reasons.append(f"EXPIRED_GT_STAMP_AT_SAMPLE_{idx} ({gt_staleness:.3f}s > {max_staleness}s)")

                # Finite coordinates
                for fld in ["x", "y", "yaw"]:
                    if not is_finite_number(gt.get(fld)):
                        failure_reasons.append(f"NON_FINITE_GT_{fld.upper()}_AT_SAMPLE_{idx}")

                gt_seq = gt.get("seq")
                gt_key = (gt_seq, round(gt_stamp, 4))
                if gt_key not in seen_gt_keys:
                    seen_gt_keys.add(gt_key)
                    unique_gt_stamps.append(round(gt_stamp, 4))

        # Combined sample deduplication based on source keys (NOT external sample seq)
        combined_key = (odom_key, gt_key)
        if combined_key not in seen_combined_keys:
            seen_combined_keys.add(combined_key)
            unique_samples.append(s)

    # 2. Sensor independent coverage and update count
    if len(seen_odom_keys) < 5:
        failure_reasons.append(f"INSUFFICIENT_UNIQUE_ODOM_UPDATES ({len(seen_odom_keys)} < 5)")
    if len(seen_gt_keys) < 5:
        failure_reasons.append(f"INSUFFICIENT_UNIQUE_GT_UPDATES ({len(seen_gt_keys)} < 5)")

    odom_duration_covered = (
        round(unique_odom_stamps[-1] - unique_odom_stamps[0], 4)
        if len(unique_odom_stamps) >= 2 else 0.0
    )
    gt_duration_covered = (
        round(unique_gt_stamps[-1] - unique_gt_stamps[0], 4)
        if len(unique_gt_stamps) >= 2 else 0.0
    )

    # Strict min_duration check (no -0.05 relaxation)
    if odom_duration_covered < min_duration:
        failure_reasons.append(f"INSUFFICIENT_ODOM_DURATION ({odom_duration_covered:.3f}s < {min_duration}s)")
    if gt_duration_covered < min_duration:
        failure_reasons.append(f"INSUFFICIENT_GT_DURATION ({gt_duration_covered:.3f}s < {min_duration}s)")

    # 3. Overall window duration based on unique combined sample sim_times
    unique_sim_times = [s["sim_time"] for s in unique_samples if is_finite_number(s.get("sim_time"))]
    if len(unique_sim_times) < 2:
        sim_duration_covered = 0.0
        failure_reasons.append("INSUFFICIENT_UNIQUE_SAMPLES_IN_WINDOW")
    else:
        sim_duration_covered = round(unique_sim_times[-1] - unique_sim_times[0], 4)
        if sim_duration_covered < min_duration:
            failure_reasons.append(f"INSUFFICIENT_WINDOW_DURATION ({sim_duration_covered:.3f}s < {min_duration}s)")

    # 4. Check sampling intervals
    max_interval = 0.0
    for i in range(len(unique_sim_times) - 1):
        dt = round(unique_sim_times[i + 1] - unique_sim_times[i], 4)
        if dt > max_interval:
            max_interval = dt
        if dt > max_staleness:
            failure_reasons.append(f"SAMPLING_GAP_EXCEEDS_STALENESS ({dt:.3f}s > {max_staleness}s)")
            break

    # Also check odom and GT max gap
    for stamps, name in [(unique_odom_stamps, "ODOM"), (unique_gt_stamps, "GT")]:
        for i in range(len(stamps) - 1):
            dt = round(stamps[i + 1] - stamps[i], 4)
            if dt > max_staleness:
                failure_reasons.append(f"{name}_GAP_EXCEEDS_STALENESS ({dt:.3f}s > {max_staleness}s)")
                break

    window_valid = (len(failure_reasons) == 0)

    return {
        "window_valid": window_valid,
        "failure_reasons": failure_reasons,
        "sim_duration_covered": sim_duration_covered,
        "odom_duration_covered": odom_duration_covered,
        "gt_duration_covered": gt_duration_covered,
        "unique_samples_count": len(unique_samples),
        "unique_odom_count": len(seen_odom_keys),
        "unique_gt_count": len(seen_gt_keys),
        "total_raw_samples_count": len(stability_samples),
        "max_sampling_interval_sec": round(max_interval, 4) if unique_sim_times else None,
        "data_fresh": window_valid,
        "watchdog_triggered": watchdog_triggered,
    }


def evaluate_physical_halt(
    stability_samples: List[Dict[str, Any]],
    thresholds: Dict[str, Any],
    safety_intervention: bool = False,
) -> Dict[str, Any]:
    """Evaluate physical halt: vehicle stopped via odom twist and negligible GT displacement.
    
    If safety_intervention is True (forced external cmd_vel publication), autonomous stop FAILS.
    """
    v_tol = float(thresholds.get("max_linear_velocity_mps", 0.05))
    w_tol = float(thresholds.get("max_angular_velocity_radps", 0.05))
    max_gt_disp_thresh = float(thresholds.get("max_gt_displacement_m", 0.03))

    if safety_intervention:
        return {
            "all_samples_stopped": False,
            "max_linear_v_seen": None,
            "max_angular_v_seen": None,
            "max_gt_displacement_m": None,
            "cmd_vel_status": "SAFETY_INTERVENTION_OVERRIDE",
            "safety_intervention": True,
            "halt_verified": False,
            "halt_failure_reason": "SAFETY_INTERVENTION_OVERRIDE_TRIGGERED",
        }

    if not stability_samples:
        return {
            "all_samples_stopped": False,
            "max_linear_v_seen": None,
            "max_angular_v_seen": None,
            "max_gt_displacement_m": None,
            "cmd_vel_status": "NO_SAMPLES",
            "safety_intervention": False,
            "halt_verified": False,
            "halt_failure_reason": "NO_SAMPLES",
        }

    max_lv = 0.0
    max_av = 0.0
    velocities_stopped = True
    gt_positions = []
    cmd_vel_non_zero = False
    cmd_vel_received_count = 0

    for idx, s in enumerate(stability_samples):
        odom = s.get("odom")
        if odom is None:
            return {
                "all_samples_stopped": False,
                "max_linear_v_seen": None,
                "max_angular_v_seen": None,
                "max_gt_displacement_m": None,
                "cmd_vel_status": "ERROR_MISSING_ODOM",
                "safety_intervention": False,
                "halt_verified": False,
                "halt_failure_reason": f"MISSING_ODOM_AT_SAMPLE_{idx}",
            }

        lv_raw = odom.get("linear_v")
        av_raw = odom.get("angular_v")
        if not is_finite_number(lv_raw) or not is_finite_number(av_raw):
            return {
                "all_samples_stopped": False,
                "max_linear_v_seen": None,
                "max_angular_v_seen": None,
                "max_gt_displacement_m": None,
                "cmd_vel_status": "ERROR_NON_FINITE_VELOCITY",
                "safety_intervention": False,
                "halt_verified": False,
                "halt_failure_reason": f"NON_FINITE_ODOM_VELOCITY_AT_SAMPLE_{idx}",
            }

        lv = abs(float(lv_raw))
        av = abs(float(av_raw))
        max_lv = max(max_lv, lv)
        max_av = max(max_av, av)
        if lv > v_tol or av > w_tol:
            velocities_stopped = False

        gt = s.get("gt")
        if gt is None or not is_finite_number(gt.get("x")) or not is_finite_number(gt.get("y")):
            return {
                "all_samples_stopped": False,
                "max_linear_v_seen": round(max_lv, 4),
                "max_angular_v_seen": round(max_av, 4),
                "max_gt_displacement_m": None,
                "cmd_vel_status": "ERROR_MISSING_OR_NON_FINITE_GT",
                "safety_intervention": False,
                "halt_verified": False,
                "halt_failure_reason": f"MISSING_OR_NON_FINITE_GT_AT_SAMPLE_{idx}",
            }

        gt_positions.append((float(gt["x"]), float(gt["y"])))

        cmd = s.get("cmd_vel")
        if cmd:
            cmd_vel_received_count += 1
            cx = abs(cmd.get("linear_x", 0.0))
            cz = abs(cmd.get("angular_z", 0.0))
            if is_finite_number(cx) and is_finite_number(cz):
                if cx > v_tol or cz > w_tol:
                    cmd_vel_non_zero = True

    if cmd_vel_received_count == 0:
        cmd_vel_status = "NO_COMMANDS_RECEIVED"
    elif cmd_vel_non_zero:
        cmd_vel_status = "NON_ZERO_COMMANDS_RECEIVED"
    else:
        cmd_vel_status = "ZERO_COMMANDS_RECEIVED"

    # GT displacement in window
    if gt_positions:
        disp_x = max(p[0] for p in gt_positions) - min(p[0] for p in gt_positions)
        disp_y = max(p[1] for p in gt_positions) - min(p[1] for p in gt_positions)
        max_gt_disp = math.hypot(disp_x, disp_y)
    else:
        max_gt_disp = None

    displacement_ok = (max_gt_disp is not None and max_gt_disp <= max_gt_disp_thresh)
    halt_verified = velocities_stopped and displacement_ok and not safety_intervention

    failure_reason = None
    if not velocities_stopped:
        failure_reason = f"EXCESS_VELOCITY (max lv={max_lv:.4f} > {v_tol} or max av={max_av:.4f} > {w_tol})"
    elif not displacement_ok:
        failure_reason = (
            f"EXCESS_GT_DISPLACEMENT ({max_gt_disp:.4f}m > {max_gt_disp_thresh:.4f}m)"
            if max_gt_disp is not None else "MISSING_GT_DISPLACEMENT"
        )

    return {
        "all_samples_stopped": velocities_stopped,
        "max_linear_v_seen": round(max_lv, 4),
        "max_angular_v_seen": round(max_av, 4),
        "max_gt_displacement_m": round(max_gt_disp, 4) if max_gt_disp is not None else None,
        "cmd_vel_status": cmd_vel_status,
        "safety_intervention": safety_intervention,
        "halt_verified": halt_verified,
        "halt_failure_reason": failure_reason,
    }


def evaluate_navigation_episode(
    target_goal: List[float],
    nav2_status: str,
    final_gt: Optional[Dict[str, Any]],
    final_amcl: Optional[Dict[str, Any]],
    stability_samples: List[Dict[str, Any]],
    thresholds: Dict[str, Any],
    watchdog_triggered: bool = False,
    safety_intervention: bool = False,
    execution_outcome: Optional[str] = None,
    deadline_exceeded: bool = False,
    failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a navigation episode against strict contract rules."""
    pos_tol = float(thresholds.get("position_tolerance_m", 0.30))
    yaw_tol = float(thresholds.get("yaw_tolerance_rad", 0.35))

    target_x, target_y, target_yaw = float(target_goal[0]), float(target_goal[1]), float(target_goal[2])

    # 1. Action status & budget constraint
    effective_outcome = execution_outcome or ("BUDGET_SUCCESS" if (nav2_status == "SUCCEEDED" and not deadline_exceeded) else ("BUDGET_DEADLINE_EXCEEDED" if deadline_exceeded else "EXECUTION_FAILED"))
    nav2_succeeded = (
        nav2_status == "SUCCEEDED"
        and not deadline_exceeded
        and effective_outcome == "BUDGET_SUCCESS"
    )

    # 2. Final geometric errors
    if final_gt and is_finite_number(final_gt.get("x")) and is_finite_number(final_gt.get("y")) and is_finite_number(final_gt.get("yaw")):
        gt_pos_err = math.hypot(final_gt["x"] - target_x, final_gt["y"] - target_y)
        gt_yaw_err = abs(normalize_angle(final_gt["yaw"] - target_yaw))
    else:
        gt_pos_err = None
        gt_yaw_err = None

    if final_amcl and is_finite_number(final_amcl.get("x")) and is_finite_number(final_amcl.get("y")) and is_finite_number(final_amcl.get("yaw")):
        amcl_pos_err = math.hypot(final_amcl["x"] - target_x, final_amcl["y"] - target_y)
        amcl_yaw_err = abs(normalize_angle(final_amcl["yaw"] - target_yaw))
    else:
        amcl_pos_err = None
        amcl_yaw_err = None

    final_pose_arrived = (
        gt_pos_err is not None
        and gt_yaw_err is not None
        and gt_pos_err <= pos_tol
        and gt_yaw_err <= yaw_tol
    )

    # 3. Stability window evaluation
    window_eval = evaluate_sensor_freshness_and_window(
        stability_samples, thresholds, watchdog_triggered=watchdog_triggered
    )
    halt_eval = evaluate_physical_halt(
        stability_samples, thresholds, safety_intervention=safety_intervention
    )

    # 4. Check all window samples maintain arrival pose
    all_window_pos_ok = True
    all_window_yaw_ok = True
    for s in stability_samples:
        gt = s.get("gt")
        if gt and is_finite_number(gt.get("x")) and is_finite_number(gt.get("y")) and is_finite_number(gt.get("yaw")):
            d = math.hypot(gt["x"] - target_x, gt["y"] - target_y)
            dyaw = abs(normalize_angle(gt["yaw"] - target_yaw))
            if d > pos_tol:
                all_window_pos_ok = False
            if dyaw > yaw_tol:
                all_window_yaw_ok = False
        else:
            all_window_pos_ok = False
            all_window_yaw_ok = False

    # 5. Overall strict physical arrival & stable
    strict_physical_arrival_and_stable = (
        nav2_succeeded
        and final_pose_arrived
        and all_window_pos_ok
        and all_window_yaw_ok
        and window_eval["window_valid"]
        and halt_eval["halt_verified"]
    )

    return {
        "nav2_action_status": nav2_status,
        "execution_outcome": effective_outcome,
        "deadline_exceeded": deadline_exceeded,
        "nav2_action_succeeded": nav2_succeeded,
        "failure_reason": failure_reason,
        "final_geometric_errors": {
            "gt_position_error_m": round(gt_pos_err, 4) if gt_pos_err is not None else None,
            "gt_yaw_error_rad": round(gt_yaw_err, 4) if gt_yaw_err is not None else None,
            "amcl_position_error_m": round(amcl_pos_err, 4) if amcl_pos_err is not None else None,
            "amcl_yaw_error_rad": round(amcl_yaw_err, 4) if amcl_yaw_err is not None else None,
            "thresholds_applied": {
                "position_tolerance_m": pos_tol,
                "yaw_tolerance_rad": yaw_tol,
            },
        },
        "window_evaluation": window_eval,
        "halt_evaluation": halt_eval,
        "all_window_pos_ok": all_window_pos_ok,
        "all_window_yaw_ok": all_window_yaw_ok,
        "final_pose_arrived": final_pose_arrived,
        "strict_physical_arrival_and_stable": strict_physical_arrival_and_stable,
    }


def evaluate_cancellation_episode(
    nav2_status: str,
    movement_confirmed_before_cancel: bool,
    cancel_request_accepted: bool,
    stability_samples: List[Dict[str, Any]],
    thresholds: Dict[str, Any],
    watchdog_triggered: bool = False,
    safety_intervention: bool = False,
) -> Dict[str, Any]:
    """Score a cancellation safety test."""
    window_eval = evaluate_sensor_freshness_and_window(
        stability_samples, thresholds, watchdog_triggered=watchdog_triggered
    )
    halt_eval = evaluate_physical_halt(
        stability_samples, thresholds, safety_intervention=safety_intervention
    )

    cancel_passed = (
        movement_confirmed_before_cancel
        and cancel_request_accepted
        and nav2_status == "CANCELED"
        and not safety_intervention
        and window_eval["window_valid"]
        and halt_eval["halt_verified"]
    )

    failure_reasons = []
    if not movement_confirmed_before_cancel:
        failure_reasons.append("MOVEMENT_NOT_CONFIRMED_BEFORE_CANCEL")
    if not cancel_request_accepted:
        failure_reasons.append("CANCEL_REQUEST_NOT_ACCEPTED")
    if nav2_status != "CANCELED":
        failure_reasons.append(f"TERMINAL_STATUS_NOT_CANCELED ({nav2_status})")
    if safety_intervention:
        failure_reasons.append("EXTERNAL_SAFETY_INTERVENTION_USED")
    if not window_eval["window_valid"]:
        failure_reasons.extend(window_eval["failure_reasons"])
    if not halt_eval["halt_verified"]:
        if halt_eval["halt_failure_reason"]:
            failure_reasons.append(halt_eval["halt_failure_reason"])

    return {
        "nav2_action_status": nav2_status,
        "movement_confirmed_before_cancel": movement_confirmed_before_cancel,
        "cancel_request_accepted": cancel_request_accepted,
        "safety_intervention": safety_intervention,
        "window_evaluation": window_eval,
        "halt_evaluation": halt_eval,
        "cancel_stop_verified": cancel_passed,
        "failure_reasons": failure_reasons,
    }


def audit_localization_discrepancy(
    amcl_samples: List[Dict[str, Any]],
    gt_samples: List[Dict[str, Any]],
    thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """Time-aligned AMCL vs Ground Truth comparison with delta t <= threshold."""
    max_delta = float(thresholds.get("max_time_alignment_delta_sim_sec", 0.1))

    aligned = []
    unmatched_amcl_count = 0

    # Deduplicate AMCL by message stamp or sim receipt
    unique_amcl = {}
    for s in amcl_samples:
        t = s.get("msg_stamp_sec") or s.get("recv_sim_time_sec")
        if t is not None and is_finite_number(t):
            unique_amcl[t] = s

    for t_amcl, amcl_s in sorted(unique_amcl.items()):
        if not gt_samples:
            unmatched_amcl_count += 1
            continue

        # GT timestamp is recv_sim_time_sec (ModelStates has no header)
        valid_gt = [g for g in gt_samples if is_finite_number(g.get("recv_sim_time_sec"))]
        if not valid_gt:
            unmatched_amcl_count += 1
            continue

        closest_gt = min(valid_gt, key=lambda g: abs(g["recv_sim_time_sec"] - t_amcl))
        t_diff = abs(closest_gt["recv_sim_time_sec"] - t_amcl)

        if t_diff <= max_delta:
            discrepancy = math.hypot(amcl_s["x"] - closest_gt["x"], amcl_s["y"] - closest_gt["y"])
            aligned.append({
                "amcl_stamp_sec": round(t_amcl, 4),
                "gt_receipt_sim_sec": round(closest_gt["recv_sim_time_sec"], 4),
                "time_delta_sec": round(t_diff, 4),
                "amcl_xy": [round(amcl_s["x"], 4), round(amcl_s["y"], 4)],
                "gt_xy": [round(closest_gt["x"], 4), round(closest_gt["y"], 4)],
                "localization_discrepancy_m": round(discrepancy, 4),
            })
        else:
            unmatched_amcl_count += 1

    mean_disc = (
        round(sum(c["localization_discrepancy_m"] for c in aligned) / len(aligned), 4)
        if aligned else None
    )

    return {
        "time_aligned_samples_count": len(aligned),
        "unmatched_amcl_samples_count": unmatched_amcl_count,
        "mean_localization_discrepancy_m": mean_disc,
        "alignment_max_delta_sec": max_delta,
        "synchronization_disclaimer": "ModelStates has no header; timestamp is ROS sim time at callback receipt (RECEIPT_ROS_SIM_TIME_APPROX). AMCL uses header.stamp.",
        "aligned_samples": aligned,
    }
