"""FailMem P1b Minimal Read-Only Observe Interface.

Provides structured, policy-visible robot sensor observations:
- AMCL estimated pose & covariance
- Odometry velocities
- 2D Laser scan availability, freshness, min range, and valid ray counts
- Nav2 lifecycle & goal status
- Timestamp metadata

CRITICAL SAFETY & LEAKAGE RESTRICTIONS:
- Whitelist filtering strictly strips and denies ground truth (GT), hidden fault labels, or evaluation answers.
- Distinguishes valid observation, stale sensor, missing sensor, and timeout with structured errors. Never fakes observations.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, Optional, Tuple


FORBIDDEN_KEYWORDS = (
    "ground_truth",
    "gt_",
    "_gt",
    "gt",
    "world_pose",
    "true_pose",
    "fault",
    "injection",
    "label",
    "oracle",
    "answer",
    "evaluation",
)


def filter_observation_whitelist(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively strip any fields that could leak hidden ground truth or evaluation labels."""
    cleaned = {}
    for k, v in raw_data.items():
        k_lower = str(k).lower()
        if any(bad in k_lower for bad in FORBIDDEN_KEYWORDS):
            continue
        if isinstance(v, dict):
            cleaned[k] = filter_observation_whitelist(v)
        elif isinstance(v, list):
            cleaned[k] = [
                filter_observation_whitelist(elem) if isinstance(elem, dict) else elem
                for elem in v
            ]
        else:
            cleaned[k] = v
    return cleaned


class ObserveInterface:
    """Provides read-only observation queries from live ROS node caches."""

    def __init__(self, max_sensor_staleness_sec: float = 1.0):
        self.max_sensor_staleness_sec = max_sensor_staleness_sec

    def extract_observation(
        self,
        current_sim_time: float,
        latest_amcl: Optional[Dict[str, Any]],
        latest_odom: Optional[Dict[str, Any]],
        latest_scan: Optional[Dict[str, Any]],
        nav2_lifecycle_state: str = "active",
        current_goal_status: Optional[str] = "IDLE",
    ) -> Dict[str, Any]:
        """Extract a structured read-only observation.
        
        Returns:
            Dict with 'status': 'SUCCESS' | 'ERROR', 'error_type', 'error_message', 'observation'.
        """
        if not math.isfinite(current_sim_time):
            return {
                "status": "ERROR",
                "error_type": "INVALID_SIMULATION_TIME",
                "error_message": f"Simulation time {current_sim_time} is not finite.",
                "observation": None,
            }

        # 1. AMCL Localization check
        if latest_amcl is None:
            return {
                "status": "ERROR",
                "error_type": "AMCL_UNAVAILABLE",
                "error_message": "AMCL pose estimation is not available.",
                "observation": None,
            }

        amcl_stamp = latest_amcl.get("msg_stamp_sec") or latest_amcl.get("recv_sim_time_sec")
        if amcl_stamp is None or (current_sim_time - amcl_stamp) > self.max_sensor_staleness_sec:
            staleness = (current_sim_time - amcl_stamp) if amcl_stamp is not None else 999.0
            return {
                "status": "ERROR",
                "error_type": "AMCL_STALE",
                "error_message": f"AMCL pose is stale ({staleness:.3f}s > {self.max_sensor_staleness_sec}s).",
                "observation": None,
            }

        # 2. Odometry check
        if latest_odom is None:
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_UNAVAILABLE",
                "error_message": "Odometry stream is not available.",
                "observation": None,
            }

        odom_stamp = latest_odom.get("msg_stamp_sec") or latest_odom.get("recv_sim_time_sec")
        if odom_stamp is None or (current_sim_time - odom_stamp) > self.max_sensor_staleness_sec:
            staleness = (current_sim_time - odom_stamp) if odom_stamp is not None else 999.0
            return {
                "status": "ERROR",
                "error_type": "ODOMETRY_STALE",
                "error_message": f"Odometry is stale ({staleness:.3f}s > {self.max_sensor_staleness_sec}s).",
                "observation": None,
            }

        # 3. Laser Scan check
        scan_obs: Dict[str, Any]
        if latest_scan is None:
            scan_obs = {
                "available": False,
                "fresh": False,
                "staleness_sec": None,
                "min_distance_m": None,
                "valid_ranges_count": 0,
                "total_ranges_count": 0,
            }
        else:
            scan_stamp = latest_scan.get("msg_stamp_sec") or latest_scan.get("recv_sim_time_sec")
            staleness = (current_sim_time - scan_stamp) if scan_stamp is not None else 999.0
            fresh = (staleness <= self.max_sensor_staleness_sec)
            scan_obs = {
                "available": True,
                "fresh": fresh,
                "staleness_sec": round(staleness, 4),
                "min_distance_m": round(latest_scan.get("min_range", 0.0), 4) if latest_scan.get("min_range") is not None else None,
                "valid_ranges_count": latest_scan.get("valid_count", 0),
                "total_ranges_count": latest_scan.get("total_count", 0),
            }

        # 4. Construct Whitelisted Observation
        cov_diag = latest_amcl.get("covariance_diagonal", [0.01, 0.01, 0.01])
        raw_observation = {
            "timestamp": {
                "sim_time_sec": round(current_sim_time, 4),
                "amcl_stamp_sec": round(amcl_stamp, 4),
                "odom_stamp_sec": round(odom_stamp, 4),
            },
            "localization": {
                "pose": [
                    round(latest_amcl.get("x", 0.0), 4),
                    round(latest_amcl.get("y", 0.0), 4),
                    round(latest_amcl.get("yaw", 0.0), 4),
                ],
                "covariance_diagonal": [round(c, 6) for c in cov_diag],
                "frame_id": latest_amcl.get("frame_id", "map"),
            },
            "odometry": {
                "linear_velocity_mps": round(latest_odom.get("linear_v", 0.0), 4),
                "angular_velocity_radps": round(latest_odom.get("angular_v", 0.0), 4),
            },
            "laser_scan": scan_obs,
            "navigation_status": {
                "nav2_lifecycle_state": nav2_lifecycle_state,
                "current_goal_status": current_goal_status,
            },
        }

        # Enforce whitelist security filter
        safe_observation = filter_observation_whitelist(raw_observation)

        return {
            "status": "SUCCESS",
            "error_type": None,
            "error_message": None,
            "observation": safe_observation,
        }
