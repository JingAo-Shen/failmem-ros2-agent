"""FailMem Offline Objective Scoring Evaluator.

Extracts all evaluation rules and thresholds from configs/scoring_rules.yaml.
Strictly evaluates:
1. Sensor freshness and integrity (GT, odom, cmd_vel; rejects NaN/Inf/expired/missing/duplicate samples).
2. Physical halt and stability window coverage (>= 2.0s sim time, odom velocity < 0.05, GT displacement <= 0.03m).
3. Contract arrival tolerance (strictly 0.30m position, 0.35rad yaw, no silent relaxation).
4. Cancellation safety test (pre-cancel active motion, acceptance, CANCELED status, no safety intervention, 2.0s halt).
5. Time-aligned AMCL vs GT localization audit (delta t <= 0.1s).
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
    """Evaluate stability window coverage, freshness, sample uniqueness, and integrity."""
    min_duration = float(thresholds.get("stability_window_duration_sim_sec", 2.0))
    max_staleness = float(thresholds.get("max_sensor_staleness_sim_sec", 0.5))

    if not stability_samples:
        return {
            "window_valid": False,
            "failure_reasons": ["NO_SAMPLES_RECORDED"],
            "sim_duration_covered": 0.0,
            "unique_samples_count": 0,
            "max_sampling_interval_sec": None,
            "data_fresh": False,
            "watchdog_triggered": watchdog_triggered,
        }

    if watchdog_triggered:
        return {
            "window_valid": False,
            "failure_reasons": ["WATCHDOG_TRIGGERED_EARLY_EXIT"],
            "sim_duration_covered": 0.0,
            "unique_samples_count": len(stability_samples),
            "max_sampling_interval_sec": None,
            "data_fresh": False,
            "watchdog_triggered": True,
        }

    failure_reasons = []

    # 1. Filter duplicate cache reads:
    # A distinct sample must have a distinct (odom_msg_stamp, gt_receipt_time) or distinct seq
    unique_samples = []
    seen_keys = set()
    for s in stability_samples:
        seq = s.get("seq")
        gt = s.get("gt") or {}
        odom = s.get("odom") or {}
        key = (
            seq if seq is not None else None,
            odom.get("msg_stamp_sec"),
            gt.get("recv_sim_time_sec"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_samples.append(s)

    if len(unique_samples) < 5:
        failure_reasons.append("INSUFFICIENT_UNIQUE_SAMPLES")

    # 2. Check window duration coverage
    sim_times = [s["sim_time"] for s in unique_samples if is_finite_number(s.get("sim_time"))]
    if len(sim_times) < 2:
        return {
            "window_valid": False,
            "failure_reasons": failure_reasons if failure_reasons else ["NON_FINITE_SIM_TIMES"],
            "sim_duration_covered": 0.0,
            "unique_samples_count": len(unique_samples),
            "max_sampling_interval_sec": None,
            "data_fresh": False,
            "watchdog_triggered": watchdog_triggered,
        }

    sim_start = sim_times[0]
    sim_end = sim_times[-1]
    duration_covered = round(sim_end - sim_start, 4)

    if duration_covered < (min_duration - 0.05):  # allow 50ms tolerance for discretization
        failure_reasons.append(f"INSUFFICIENT_WINDOW_DURATION ({duration_covered:.3f}s < {min_duration}s)")

    # 3. Check sampling intervals
    max_interval = 0.0
    for i in range(len(sim_times) - 1):
        dt = sim_times[i + 1] - sim_times[i]
        if dt > max_interval:
            max_interval = dt
        if dt > max_staleness:
            failure_reasons.append(f"SAMPLING_GAP_EXCEEDS_STALENESS ({dt:.3f}s > {max_staleness}s)")
            break

    # 4. Check data integrity and finite values for required GT and odom
    for idx, s in enumerate(unique_samples):
        gt = s.get("gt")
        odom = s.get("odom")
        if not gt or not odom:
            failure_reasons.append(f"MISSING_REQUIRED_SENSORS_AT_SAMPLE_{idx}")
            break

        # Finite position & yaw
        for field in ["x", "y", "yaw"]:
            if not is_finite_number(gt.get(field)):
                failure_reasons.append(f"NON_FINITE_GT_{field.upper()}_AT_SAMPLE_{idx}")
                break
            if not is_finite_number(odom.get(field)):
                failure_reasons.append(f"NON_FINITE_ODOM_{field.upper()}_AT_SAMPLE_{idx}")
                break

        # Finite velocities
        if not is_finite_number(odom.get("linear_v")) or not is_finite_number(odom.get("angular_v")):
            failure_reasons.append(f"NON_FINITE_ODOM_VELOCITY_AT_SAMPLE_{idx}")
            break

        # Timestamp staleness relative to sample time
        if odom.get("msg_stamp_sec") is not None:
            odom_staleness = s["sim_time"] - odom["msg_stamp_sec"]
            if odom_staleness > max_staleness:
                failure_reasons.append(f"EXPIRED_ODOM_STAMP_AT_SAMPLE_{idx} ({odom_staleness:.3f}s)")
                break

    window_valid = (len(failure_reasons) == 0)

    return {
        "window_valid": window_valid,
        "failure_reasons": failure_reasons,
        "sim_duration_covered": duration_covered,
        "unique_samples_count": len(unique_samples),
        "total_raw_samples_count": len(stability_samples),
        "max_sampling_interval_sec": round(max_interval, 4),
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

    for s in stability_samples:
        odom = s.get("odom")
        if odom:
            lv = abs(odom.get("linear_v", 999.0))
            av = abs(odom.get("angular_v", 999.0))
            max_lv = max(max_lv, lv)
            max_av = max(max_av, av)
            if lv > v_tol or av > w_tol:
                velocities_stopped = False

        gt = s.get("gt")
        if gt and is_finite_number(gt.get("x")) and is_finite_number(gt.get("y")):
            gt_positions.append((gt["x"], gt["y"]))

        cmd = s.get("cmd_vel")
        if cmd:
            cmd_vel_received_count += 1
            cx = abs(cmd.get("linear_x", 0.0))
            cz = abs(cmd.get("angular_z", 0.0))
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

    displacement_ok = (max_gt_disp is not None and max_gt_disp <= 0.03)
    halt_verified = velocities_stopped and displacement_ok and not safety_intervention

    failure_reason = None
    if not velocities_stopped:
        failure_reason = f"EXCESS_VELOCITY (max lv={max_lv:.4f} > {v_tol} or max av={max_av:.4f} > {w_tol})"
    elif not displacement_ok:
        failure_reason = f"EXCESS_GT_DISPLACEMENT ({max_gt_disp:.4f}m > 0.03m)"

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
) -> Dict[str, Any]:
    """Score a navigation episode against strict contract rules."""
    pos_tol = float(thresholds.get("position_tolerance_m", 0.30))
    yaw_tol = float(thresholds.get("yaw_tolerance_rad", 0.35))

    target_x, target_y, target_yaw = float(target_goal[0]), float(target_goal[1]), float(target_goal[2])

    # 1. Action status
    nav2_succeeded = (nav2_status == "SUCCEEDED")

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
        "nav2_action_succeeded": nav2_succeeded,
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
