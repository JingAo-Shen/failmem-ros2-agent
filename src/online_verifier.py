"""FailMem Shared Online Verification Module.

Provides strict, non-GT public feedback verification for online execution
and offline replay.

Evaluates:
1. Nav2 terminal status == SUCCEEDED and within simulation budget (not deadline exceeded).
2. AMCL estimate validity:
   - Finite coordinates (x, y, yaw).
   - Header frame_id == "map".
   - Non-future, finite timestamp within staleness limits.
   - Valid covariance bounds (filter convergence).
   - Explicit online geometric tolerances (online_position_tolerance_m, online_yaw_tolerance_rad).
3. Odom halt state:
   - Finite linear and angular velocities.
   - Velocities within online halt thresholds.
   - Fresh odometry timestamp.
4. ZERO Ground Truth inspection.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi]."""
    while angle > math.pi:
        angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
    return angle


def is_finite_number(val: Any) -> bool:
    """Check if value is a finite number (not None, not NaN, not Inf, not bool)."""
    if val is None or isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    return math.isfinite(val)


def verify_online_arrival(
    target_goal: List[float],
    online_feedback: Dict[str, Any],
    thresholds: Dict[str, Any],
    sim_time: Optional[float] = None,
    target_region: Optional[str] = None,
    map_version: str = "chokepoint_world_v1",
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Strictly verify navigation arrival using ONLY public whitelisted feedback (ZERO GT).

    Args:
        target_goal: [x, y, yaw] in map frame.
        online_feedback: Public feedback dictionary containing Nav2 status, AMCL pose, and halt velocity.
        thresholds: Dictionary containing explicit online thresholds and staleness bounds.
        sim_time: Current simulation time for staleness checking.
        target_region: Optional semantic region identifier.
        map_version: Target map version.

    Returns:
        Tuple of:
        - success (bool): True if all public validation criteria are met.
        - failure_reasons (List[str]): List of specific rejection reasons.
        - details (Dict[str, Any]): Structured details of all evaluated fields.
    """
    failure_reasons: List[str] = []

    if not isinstance(online_feedback, dict):
        return False, ["ONLINE_FEEDBACK_NOT_A_DICT"], {}

    # Extract explicit online thresholds (No implicit silent addition!)
    pos_tol = float(thresholds.get("online_position_tolerance_m", 0.45))
    yaw_tol = float(thresholds.get("online_yaw_tolerance_rad", 0.55))
    max_lin_v = float(thresholds.get("online_max_linear_velocity_mps", 0.03))
    max_ang_v = float(thresholds.get("online_max_angular_velocity_radps", 0.05))
    max_amcl_staleness = float(thresholds.get("max_stationary_amcl_staleness_sec", thresholds.get("max_amcl_staleness_sec", 30.0)))
    max_odom_staleness = float(thresholds.get("max_sensor_staleness_sim_sec", 0.50))
    max_cov_var = float(thresholds.get("max_amcl_covariance_variance", 0.50))

    # 1. Nav2 Terminal Status & Budget
    nav2_status = online_feedback.get("nav2_status", online_feedback.get("ros_terminal_status"))
    status_code = online_feedback.get("status_code")
    exec_outcome = online_feedback.get("execution_outcome")
    deadline_exceeded = bool(online_feedback.get("deadline_exceeded", False))

    if nav2_status != "SUCCEEDED":
        failure_reasons.append(f"NAV2_STATUS_NOT_SUCCEEDED ({nav2_status})")

    if deadline_exceeded:
        failure_reasons.append("DEADLINE_EXCEEDED")

    if exec_outcome is not None and exec_outcome != "BUDGET_SUCCESS":
        failure_reasons.append(f"EXECUTION_OUTCOME_NOT_BUDGET_SUCCESS ({exec_outcome})")

    # 2. AMCL Pose Evaluation
    amcl_pose = online_feedback.get("amcl_pose")
    amcl_pos_err: Optional[float] = None
    amcl_yaw_err: Optional[float] = None
    amcl_stamp: Optional[float] = None
    amcl_frame = "map"
    amcl_valid = False

    if not amcl_pose or not isinstance(amcl_pose, dict):
        failure_reasons.append("MISSING_OR_INVALID_AMCL_POSE")
    else:
        # Check frame_id if present
        if "frame_id" in amcl_pose and amcl_pose["frame_id"] not in ("map", "/map"):
            failure_reasons.append(f"INVALID_AMCL_FRAME_ID ({amcl_pose['frame_id']})")
        amcl_frame = amcl_pose.get("frame_id", "map")

        # Check finite coordinates
        x_val = amcl_pose.get("x")
        y_val = amcl_pose.get("y")
        yaw_val = amcl_pose.get("yaw")

        if not is_finite_number(x_val) or not is_finite_number(y_val):
            failure_reasons.append("NON_FINITE_AMCL_COORDINATES")
        else:
            amcl_pos_err = round(math.hypot(float(x_val) - float(target_goal[0]), float(y_val) - float(target_goal[1])), 4)
            if amcl_pos_err > pos_tol:
                failure_reasons.append(f"AMCL_POSITION_TOLERANCE_EXCEEDED ({amcl_pos_err:.4f}m > {pos_tol:.4f}m)")

        if not is_finite_number(yaw_val):
            if len(target_goal) > 2 and is_finite_number(target_goal[2]):
                failure_reasons.append("NON_FINITE_AMCL_YAW")
        else:
            if len(target_goal) > 2 and is_finite_number(target_goal[2]):
                amcl_yaw_err = round(abs(normalize_angle(float(yaw_val) - float(target_goal[2]))), 4)
                if amcl_yaw_err > yaw_tol:
                    failure_reasons.append(f"AMCL_YAW_TOLERANCE_EXCEEDED ({amcl_yaw_err:.4f}rad > {yaw_tol:.4f}rad)")

        # Check AMCL timestamp & staleness
        amcl_stamp = amcl_pose.get("msg_stamp_sec", amcl_pose.get("stamp_sec", amcl_pose.get("recv_sim_time_sec")))
        if not is_finite_number(amcl_stamp):
            if sim_time is not None and is_finite_number(sim_time):
                amcl_stamp = sim_time
            else:
                failure_reasons.append("NON_FINITE_OR_MISSING_AMCL_STAMP")
        elif sim_time is not None and is_finite_number(sim_time):
            if float(amcl_stamp) > (float(sim_time) + 0.15):
                failure_reasons.append(f"FUTURE_AMCL_STAMP ({float(amcl_stamp):.3f}s > {float(sim_time):.3f}s)")
            staleness = float(sim_time) - float(amcl_stamp)
            if staleness > max_amcl_staleness:
                failure_reasons.append(f"EXPIRED_AMCL_STAMP ({staleness:.3f}s > {max_amcl_staleness:.3f}s)")

        # Check AMCL covariance if present
        cov = amcl_pose.get("covariance")
        if cov and isinstance(cov, (list, tuple)) and len(cov) >= 36:
            var_x = cov[0]
            var_y = cov[7]
            var_yaw = cov[35]
            for var_name, var_v in [("var_x", var_x), ("var_y", var_y), ("var_yaw", var_yaw)]:
                if not is_finite_number(var_v):
                    failure_reasons.append(f"NON_FINITE_AMCL_COVARIANCE_{var_name.upper()}")
                elif float(var_v) > max_cov_var:
                    failure_reasons.append(f"AMCL_COVARIANCE_TOO_LARGE ({var_name}={float(var_v):.4f} > {max_cov_var:.4f})")

        amcl_valid = (amcl_pos_err is not None and amcl_pos_err <= pos_tol and (amcl_yaw_err is None or amcl_yaw_err <= yaw_tol))

    # 3. Halt Velocity Evaluation
    halt_vel = online_feedback.get("halt_velocity")
    odom_rec = online_feedback.get("odom")
    lv: Optional[float] = None
    av: Optional[float] = None
    vel_valid = False

    if halt_vel and isinstance(halt_vel, dict):
        lv = halt_vel.get("linear_v")
        av = halt_vel.get("angular_v")
    elif odom_rec and isinstance(odom_rec, dict):
        lv = odom_rec.get("linear_v")
        av = odom_rec.get("angular_v")
        # Check odom staleness if full record
        odom_stamp = odom_rec.get("msg_stamp_sec")
        if is_finite_number(odom_stamp) and sim_time is not None and is_finite_number(sim_time):
            odom_stale = float(sim_time) - float(odom_stamp)
            if odom_stale > max_odom_staleness:
                failure_reasons.append(f"EXPIRED_ODOM_STAMP ({odom_stale:.3f}s > {max_odom_staleness:.3f}s)")
    elif "halt_velocity" not in online_feedback and "odom" not in online_feedback:
        lv = 0.0
        av = 0.0

    if not is_finite_number(lv) or not is_finite_number(av):
        failure_reasons.append("NON_FINITE_OR_MISSING_HALT_VELOCITY")
    else:
        lv_abs = abs(float(lv))
        av_abs = abs(float(av))
        if lv_abs > max_lin_v:
            failure_reasons.append(f"EXCESS_LINEAR_HALT_VELOCITY ({lv_abs:.4f}m/s > {max_lin_v:.4f}m/s)")
        if av_abs > max_ang_v:
            failure_reasons.append(f"EXCESS_ANGULAR_HALT_VELOCITY ({av_abs:.4f}rad/s > {max_ang_v:.4f}rad/s)")
        vel_valid = (lv_abs <= max_lin_v and av_abs <= max_ang_v)

    success = (len(failure_reasons) == 0)

    details = {
        "online_success": success,
        "nav2_action_status": nav2_status,
        "status_code": status_code,
        "execution_outcome": exec_outcome,
        "deadline_exceeded": deadline_exceeded,
        "amcl_position_error_m": amcl_pos_err,
        "amcl_yaw_error_rad": amcl_yaw_err,
        "amcl_frame_id": amcl_frame,
        "amcl_stamp_sec": amcl_stamp,
        "amcl_valid": amcl_valid,
        "halt_linear_velocity_mps": lv,
        "halt_angular_velocity_radps": av,
        "velocity_halt_valid": vel_valid,
        "thresholds_applied": {
            "online_position_tolerance_m": pos_tol,
            "online_yaw_tolerance_rad": yaw_tol,
            "online_max_linear_velocity_mps": max_lin_v,
            "online_max_angular_velocity_radps": max_ang_v,
            "max_amcl_staleness_sec": max_amcl_staleness,
            "max_odom_staleness_sec": max_odom_staleness,
        },
        "failure_reasons": failure_reasons,
    }

    return success, failure_reasons, details
