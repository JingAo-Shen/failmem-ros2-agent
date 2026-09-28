"""FailMem P1b Minimal Read-Only Observe Interface.

Provides structured, policy-visible robot sensor observations:
- AMCL estimated pose & covariance
- Odometry velocities
- 2D Laser scan availability, freshness, min range, and valid ray counts
- Nav2 lifecycle & goal status
- Timestamp metadata

CRITICAL SAFETY & LEAKAGE RESTRICTIONS:
- Strict field whitelist schema: Unknown, custom, or privileged fields (ground truth, world pose, fault labels, oracle data) are strictly dropped.
- Distinguishes valid observation, stale sensor, missing sensor, and degraded scan with structured responses.
- NEVER fakes timestamps, covariance, velocities, lifecycle state, or goal status.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Tuple, Union


def is_finite_number(val: Any) -> bool:
    """Check if value is a finite number (not None, not NaN, not Inf, not bool)."""
    if val is None or isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    return math.isfinite(val)


def apply_strict_observation_whitelist(raw_obs: Dict[str, Any]) -> Dict[str, Any]:
    """Strictly construct the observation using an explicit field whitelist and fixed output schema.
    
    Any unrecognized or unwhitelisted top-level or nested keys are discarded.
    """
    ts_raw = raw_obs.get("timestamp") or {}
    loc_raw = raw_obs.get("localization") or {}
    odom_raw = raw_obs.get("odometry") or {}
    scan_raw = raw_obs.get("laser_scan") or {}
    nav_raw = raw_obs.get("navigation_status") or {}

    # 1. Whitelisted Timestamp
    timestamp_out = {
        "sim_time_sec": float(ts_raw["sim_time_sec"]) if is_finite_number(ts_raw.get("sim_time_sec")) else None,
        "amcl_stamp_sec": float(ts_raw["amcl_stamp_sec"]) if is_finite_number(ts_raw.get("amcl_stamp_sec")) else None,
        "odom_stamp_sec": float(ts_raw["odom_stamp_sec"]) if is_finite_number(ts_raw.get("odom_stamp_sec")) else None,
        "scan_stamp_sec": float(ts_raw["scan_stamp_sec"]) if is_finite_number(ts_raw.get("scan_stamp_sec")) else None,
    }

    # 2. Whitelisted Localization
    pose_raw = loc_raw.get("pose")
    pose_out = (
        [round(float(p), 4) for p in pose_raw[:3]]
        if (isinstance(pose_raw, (list, tuple)) and len(pose_raw) >= 3 and all(is_finite_number(p) for p in pose_raw[:3]))
        else None
    )

    cov_raw = loc_raw.get("covariance_diagonal")
    cov_out = (
        [round(float(c), 6) for c in cov_raw[:3]]
        if (isinstance(cov_raw, (list, tuple)) and len(cov_raw) >= 3 and all(is_finite_number(c) for c in cov_raw[:3]))
        else None
    )

    localization_out = {
        "pose": pose_out,
        "covariance_diagonal": cov_out,
        "frame_id": str(loc_raw.get("frame_id", "map")),
        "staleness_sec": round(float(loc_raw["staleness_sec"]), 4) if is_finite_number(loc_raw.get("staleness_sec")) else None,
        "status": str(loc_raw.get("status", "UNKNOWN")),
    }

    # 3. Whitelisted Odometry
    odometry_out = {
        "linear_velocity_mps": round(float(odom_raw["linear_velocity_mps"]), 4) if is_finite_number(odom_raw.get("linear_velocity_mps")) else None,
        "angular_velocity_radps": round(float(odom_raw["angular_velocity_radps"]), 4) if is_finite_number(odom_raw.get("angular_velocity_radps")) else None,
        "staleness_sec": round(float(odom_raw["staleness_sec"]), 4) if is_finite_number(odom_raw.get("staleness_sec")) else None,
    }

    # 4. Whitelisted Laser Scan
    laser_scan_out = {
        "available": bool(scan_raw.get("available", False)),
        "fresh": bool(scan_raw.get("fresh", False)),
        "staleness_sec": round(float(scan_raw["staleness_sec"]), 4) if is_finite_number(scan_raw.get("staleness_sec")) else None,
        "min_distance_m": round(float(scan_raw["min_distance_m"]), 4) if is_finite_number(scan_raw.get("min_distance_m")) else None,
        "valid_ranges_count": int(scan_raw["valid_ranges_count"]) if isinstance(scan_raw.get("valid_ranges_count"), (int, float)) else 0,
        "total_ranges_count": int(scan_raw["total_ranges_count"]) if isinstance(scan_raw.get("total_ranges_count"), (int, float)) else 0,
    }

    # 5. Whitelisted Navigation Status
    navigation_status_out = {
        "nav2_lifecycle_state": str(nav_raw.get("nav2_lifecycle_state", "UNKNOWN")),
        "current_goal_status": str(nav_raw.get("current_goal_status", "UNKNOWN")),
    }

    return {
        "timestamp": timestamp_out,
        "localization": localization_out,
        "odometry": odometry_out,
        "laser_scan": laser_scan_out,
        "navigation_status": navigation_status_out,
    }


class ObserveInterface:
    """Provides validated, read-only observation queries from live ROS node caches."""

    def __init__(
        self,
        max_sensor_staleness_sec: float = 0.5,
        max_stationary_amcl_staleness_sec: float = 30.0,
    ):
        self.max_sensor_staleness_sec = max_sensor_staleness_sec
        self.max_stationary_amcl_staleness_sec = max_stationary_amcl_staleness_sec

    def extract_observation(
        self,
        current_sim_time: float,
        latest_amcl: Optional[Dict[str, Any]],
        latest_odom: Optional[Dict[str, Any]],
        latest_scan: Optional[Dict[str, Any]],
        nav2_lifecycle_state: Optional[str] = None,
        current_goal_status: Optional[str] = None,
        odom_history: Optional[List[Dict[str, Any]]] = None,
        wall_clock_timeout: bool = False,
        clock_frozen: bool = False,
    ) -> Dict[str, Any]:
        """Extract and strictly validate a structured read-only observation.
        
        Returns:
            Dict with 'status' ('SUCCESS' | 'DEGRADED' | 'ERROR'),
                      'error_type', 'error_message', 'observation'.
        """
        if clock_frozen:
            return {
                "status": "ERROR",
                "error_type": "SIMULATION_CLOCK_FROZEN",
                "error_message": "Simulation clock has stopped advancing while wall-clock time elapsed.",
                "observation": None,
            }

        if not is_finite_number(current_sim_time) or current_sim_time < 0.0:
            return {
                "status": "ERROR",
                "error_type": "INVALID_SIMULATION_TIME",
                "error_message": f"Simulation time {current_sim_time} is non-finite or negative.",
                "observation": None,
            }

        # 1. Odometry Validation (Required)
        if latest_odom is None:
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_UNAVAILABLE",
                "error_message": "Odometry stream is not available.",
                "observation": None,
            }

        odom_stamp = latest_odom.get("msg_stamp_sec")
        if not is_finite_number(odom_stamp) or odom_stamp <= 0.0:
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_INVALID_TIMESTAMP",
                "error_message": f"Odometry message timestamp {odom_stamp} is non-finite or zero.",
                "observation": None,
            }

        odom_staleness = current_sim_time - odom_stamp
        if odom_staleness < -0.50:
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_FUTURE_TIMESTAMP",
                "error_message": f"Odometry stamp {odom_stamp} is in the future relative to sim time {current_sim_time}.",
                "observation": None,
            }
        if odom_staleness > self.max_sensor_staleness_sec:
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_STALE",
                "error_message": f"Odometry is stale ({odom_staleness:.3f}s > {self.max_sensor_staleness_sec}s).",
                "observation": None,
            }

        lv = latest_odom.get("linear_v")
        av = latest_odom.get("angular_v")
        if not is_finite_number(lv) or not is_finite_number(av):
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_INVALID_DATA",
                "error_message": "Odometry linear or angular velocity is non-finite.",
                "observation": None,
            }

        is_robot_stationary = (abs(float(lv)) < 0.05 and abs(float(av)) < 0.05)

        # 2. AMCL Validation (Required)
        if latest_amcl is None:
            return {
                "status": "ERROR",
                "error_type": "AMCL_UNAVAILABLE",
                "error_message": "AMCL pose estimation is not available.",
                "observation": None,
            }

        amcl_x = latest_amcl.get("x")
        amcl_y = latest_amcl.get("y")
        amcl_yaw = latest_amcl.get("yaw")
        if not is_finite_number(amcl_x) or not is_finite_number(amcl_y) or not is_finite_number(amcl_yaw):
            return {
                "status": "ERROR",
                "error_type": "AMCL_INVALID_DATA",
                "error_message": "AMCL pose coordinates or yaw are non-finite.",
                "observation": None,
            }

        cov_diag = latest_amcl.get("covariance_diagonal")
        if (
            not isinstance(cov_diag, (list, tuple))
            or len(cov_diag) < 3
            or not all(is_finite_number(c) for c in cov_diag[:3])
        ):
            return {
                "status": "ERROR",
                "error_type": "AMCL_MISSING_COVARIANCE",
                "error_message": "AMCL covariance diagonal is missing or non-finite (no defaults fabricated).",
                "observation": None,
            }

        amcl_stamp = latest_amcl.get("msg_stamp_sec")
        if not is_finite_number(amcl_stamp) or amcl_stamp <= 0.0:
            return {
                "status": "ERROR",
                "error_type": "AMCL_INVALID_TIMESTAMP",
                "error_message": f"AMCL message timestamp {amcl_stamp} is non-finite or zero.",
                "observation": None,
            }

        amcl_staleness = current_sim_time - amcl_stamp
        if amcl_staleness < -0.50:
            return {
                "status": "ERROR",
                "error_type": "AMCL_FUTURE_TIMESTAMP",
                "error_message": f"AMCL stamp {amcl_stamp} is in the future relative to sim time {current_sim_time}.",
                "observation": None,
            }

        # AMCL low-frequency handling when stationary
        if amcl_staleness <= self.max_sensor_staleness_sec:
            amcl_status = "UP_TO_DATE"
        elif amcl_staleness <= self.max_stationary_amcl_staleness_sec:
            if not is_robot_stationary:
                return {
                    "status": "ERROR",
                    "error_type": "AMCL_STALE",
                    "error_message": f"AMCL pose is stale ({amcl_staleness:.3f}s > {self.max_sensor_staleness_sec}s) while robot is moving.",
                    "observation": None,
                }

            # If robot is stationary, verify odom history strictly covers the AMCL gap without gaps or motion
            if odom_history is None or len(odom_history) == 0:
                return {
                    "status": "ERROR",
                    "error_type": "AMCL_HISTORY_UNAVAILABLE",
                    "error_message": f"AMCL pose is stale ({amcl_staleness:.3f}s > {self.max_sensor_staleness_sec}s) and no odometry history is available to verify stationary state.",
                    "observation": None,
                }

            valid_stamps = [
                float(r["msg_stamp_sec"]) for r in odom_history
                if is_finite_number(r.get("msg_stamp_sec")) and float(r["msg_stamp_sec"]) > 0.0
            ]
            if not valid_stamps:
                return {
                    "status": "ERROR",
                    "error_type": "AMCL_HISTORY_INVALID",
                    "error_message": "Odometry history contains no valid timestamps.",
                    "observation": None,
                }

            earliest_stamp = min(valid_stamps)
            latest_stamp = max(valid_stamps)

            if earliest_stamp > (amcl_stamp + 0.15):
                return {
                    "status": "ERROR",
                    "error_type": "AMCL_HISTORY_INSUFFICIENT",
                    "error_message": f"Odometry history starts too late ({earliest_stamp:.3f}s > AMCL stamp {amcl_stamp:.3f}s + 0.15s).",
                    "observation": None,
                }

            if latest_stamp < (current_sim_time - 0.25):
                return {
                    "status": "ERROR",
                    "error_type": "AMCL_HISTORY_INSUFFICIENT",
                    "error_message": f"Odometry history ends too early ({latest_stamp:.3f}s < current sim time {current_sim_time:.3f}s - 0.25s).",
                    "observation": None,
                }

            sorted_records = sorted(
                [r for r in odom_history if is_finite_number(r.get("msg_stamp_sec")) and r["msg_stamp_sec"] >= (amcl_stamp - 0.15)],
                key=lambda x: x["msg_stamp_sec"]
            )

            # 1. First check if any motion occurred during the gap
            motion_detected = False
            motion_reason = None
            initial_x = sorted_records[0].get("x")
            initial_y = sorted_records[0].get("y")
            for r in sorted_records:
                r_lv = abs(float(r.get("linear_v", 0.0)))
                r_av = abs(float(r.get("angular_v", 0.0)))
                if r_lv >= 0.05 or r_av >= 0.05:
                    motion_detected = True
                    motion_reason = f"Velocity exceeded threshold (linear_v={r_lv:.3f}, angular_v={r_av:.3f})"
                    break
                if initial_x is not None and initial_y is not None:
                    curr_x = r.get("x")
                    curr_y = r.get("y")
                    if curr_x is not None and curr_y is not None:
                        disp = math.hypot(curr_x - initial_x, curr_y - initial_y)
                        if disp > 0.03:
                            motion_detected = True
                            motion_reason = f"Displacement exceeded threshold ({disp:.3f}m > 0.03m)"
                            break

            if motion_detected:
                return {
                    "status": "ERROR",
                    "error_type": "AMCL_STALE_AFTER_MOTION",
                    "error_message": f"AMCL pose is stale ({amcl_staleness:.3f}s) and robot moved during the gap: {motion_reason}.",
                    "observation": None,
                }

            # 2. Check for excessive sampling gap in the history
            for i in range(1, len(sorted_records)):
                dt = sorted_records[i]["msg_stamp_sec"] - sorted_records[i-1]["msg_stamp_sec"]
                if dt > 0.60:
                    return {
                        "status": "ERROR",
                        "error_type": "AMCL_HISTORY_INSUFFICIENT",
                        "error_message": f"Odometry history has excessive gap ({dt:.3f}s > 0.60s) between {sorted_records[i-1]['msg_stamp_sec']:.3f}s and {sorted_records[i]['msg_stamp_sec']:.3f}s.",
                        "observation": None,
                    }

            amcl_status = "VALID_STATIONARY_CACHE"
        else:
            return {
                "status": "ERROR",
                "error_type": "AMCL_STALE",
                "error_message": f"AMCL pose is stale ({amcl_staleness:.3f}s > {self.max_sensor_staleness_sec}s).",
                "observation": None,
            }

        # 3. Laser Scan Validation (Contract: Degraded if missing/stale, never faked)
        scan_stamp = None
        scan_available = False
        scan_fresh = False
        scan_staleness = None
        scan_min_distance = None
        scan_valid_count = 0
        scan_total_count = 0
        is_scan_degraded = False
        degradation_reasons = []

        if latest_scan is None:
            is_scan_degraded = True
            degradation_reasons.append("SCAN_UNAVAILABLE")
        else:
            scan_stamp_raw = latest_scan.get("msg_stamp_sec")
            if is_finite_number(scan_stamp_raw) and scan_stamp_raw > 0.0:
                scan_stamp = float(scan_stamp_raw)
                scan_staleness = current_sim_time - scan_stamp
                scan_available = True
                scan_fresh = (scan_staleness <= self.max_sensor_staleness_sec and scan_staleness >= -0.50)
                if not scan_fresh:
                    is_scan_degraded = True
                    degradation_reasons.append(f"SCAN_STALE ({scan_staleness:.3f}s > {self.max_sensor_staleness_sec}s)")

                min_r = latest_scan.get("min_range")
                scan_min_distance = float(min_r) if is_finite_number(min_r) else None
                scan_valid_count = int(latest_scan.get("valid_count", 0))
                scan_total_count = int(latest_scan.get("total_count", 0))
            else:
                is_scan_degraded = True
                degradation_reasons.append("SCAN_INVALID_TIMESTAMP")

        # 4. Construct Raw Observation with Explicit Unfabricated Fields
        raw_observation = {
            "timestamp": {
                "sim_time_sec": current_sim_time,
                "amcl_stamp_sec": amcl_stamp,
                "odom_stamp_sec": odom_stamp,
                "scan_stamp_sec": scan_stamp,
            },
            "localization": {
                "pose": [amcl_x, amcl_y, amcl_yaw],
                "covariance_diagonal": cov_diag[:3],
                "frame_id": latest_amcl.get("frame_id", "map"),
                "staleness_sec": amcl_staleness,
                "status": amcl_status,
            },
            "odometry": {
                "linear_velocity_mps": lv,
                "angular_velocity_radps": av,
                "staleness_sec": odom_staleness,
            },
            "laser_scan": {
                "available": scan_available,
                "fresh": scan_fresh,
                "staleness_sec": scan_staleness,
                "min_distance_m": scan_min_distance,
                "valid_ranges_count": scan_valid_count,
                "total_ranges_count": scan_total_count,
            },
            "navigation_status": {
                "nav2_lifecycle_state": str(nav2_lifecycle_state or "UNKNOWN"),
                "current_goal_status": str(current_goal_status or "UNKNOWN"),
            },
        }

        # 5. Apply Strict Output Schema & Field Whitelist Filter
        safe_observation = apply_strict_observation_whitelist(raw_observation)

        if is_scan_degraded:
            return {
                "status": "DEGRADED",
                "error_type": "SCAN_DEGRADED",
                "error_message": "; ".join(degradation_reasons),
                "observation": safe_observation,
            }

        return {
            "status": "SUCCESS",
            "error_type": None,
            "error_message": None,
            "observation": safe_observation,
        }
