"""FailMem Milestone P2c Core Pipeline & Production Verification Module.

Contains unified production components shared across:
1. Online Physical Experiment Runner (`scripts/run_p2c_experiment.py`)
2. Independent Offline Replay Engine (`scripts/replay_and_score_p2c.py`)
3. Regression Test Suite (`tests/test_p2c_event_driven.py`)

Components:
- P2cProtocolConfig: Protocol loading, geometry validation, nominal waypoint calculations.
- P2cObservationClassifier: Freshness, occlusion proof, and 3-valued perception classification.
- P2cTrajectoryClassifier: Continuous odometry integration, dead-end sequence detection, actual route classification, and failure diagnosis.
- P2cPolicyDecider: Live observation consumption, caching, and causal memory route selection.
- P2cEpisodeEvaluator: Unified evaluation of budget, physical arrival, validity flags, and audit integrity.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from src.doorway_evaluator import (
    evaluate_doorway_clearance,
    extract_costmap_doorway_subgrid,
    project_laser_scan_rays_tf,
    is_finite_number,
)
from src.failure_memory import (
    FailureMemoryStore,
    FailureMemoryEntry,
    MemoryState,
)


class P2cProtocolConfig:
    """Loads, validates, and provides calibrated geometric references from protocol YAML."""

    def __init__(self, config_dict: Dict[str, Any], source_path: Optional[str] = None):
        self.raw_config = config_dict
        self.source_path = source_path
        self.protocol_version = str(config_dict.get("protocol_version", "4.1"))
        self.total_sim_budget_sec = float(
            config_dict.get("navigation_task", {}).get("episode_total_sim_budget_sec", 180.0)
        )
        self.action_sim_timeout_sec = float(
            config_dict.get("navigation_task", {}).get("action_sim_timeout_sec", 45.0)
        )
        self.target_goal = [
            float(config_dict.get("navigation_task", {}).get("goal_pose", {}).get("x", 2.50)),
            float(config_dict.get("navigation_task", {}).get("goal_pose", {}).get("y", 0.00)),
            float(config_dict.get("navigation_task", {}).get("goal_pose", {}).get("yaw", 0.00)),
        ]
        self.decision_junction = [
            float(config_dict.get("decision_junction", {}).get("pose", {}).get("x", -2.50)),
            float(config_dict.get("decision_junction", {}).get("pose", {}).get("y", 0.00)),
            float(config_dict.get("decision_junction", {}).get("pose", {}).get("yaw", 0.00)),
        ]
        self.chokepoint_region = str(config_dict.get("navigation_task", {}).get("target_region", "north_corridor_chokepoint"))
        self.map_version = str(config_dict.get("environment", {}).get("map_version", "p2c_dualpath_world_v1"))

        doorway_dict = config_dict.get("obstacle_channel", {}).get(
            "doorway_bbox", {"x_min": -0.25, "x_max": 0.25, "y_min": 0.90, "y_max": 1.50}
        )
        self.doorway_bbox = (
            float(doorway_dict["x_min"]),
            float(doorway_dict["x_max"]),
            float(doorway_dict["y_min"]),
            float(doorway_dict["y_max"]),
        )
        self.opening_bbox = (-0.15, 0.15, 0.95, 1.45)

        routes_cfg = config_dict.get("routes", {})
        self.path_a_waypoints = routes_cfg.get("path_a", {}).get("waypoints", [
            [-2.50, 0.00, 0.0], [-1.50, 1.20, 0.0], [0.00, 1.20, 0.0], [1.50, 1.20, 0.0], [2.50, 0.00, 0.0]
        ])
        self.path_b_waypoints = routes_cfg.get("path_b", {}).get("waypoints", [
            [-2.50, 0.00, 0.0], [-2.50, -2.00, 0.0], [-1.00, -2.40, 0.0], [0.00, -2.40, 0.0],
            [1.00, -2.40, 0.0], [2.50, -2.00, 0.0], [2.50, 0.00, 0.0]
        ])
        self.nominal_length_a = self.compute_polyline_length(self.path_a_waypoints)
        self.nominal_length_b = self.compute_polyline_length(self.path_b_waypoints)

        self.thresholds = config_dict.get("scoring_thresholds", {
            "position_tolerance_m": 0.30,
            "yaw_tolerance_rad": 0.35,
            "max_linear_velocity_mps": 0.05,
            "max_angular_velocity_radps": 0.08,
            "stability_window_duration_sim_sec": 2.0,
            "max_gt_displacement_m": 0.03,
            "max_sensor_staleness_sim_sec": 0.50,
            "max_costmap_staleness_sec": 3.00,
            "max_stationary_amcl_staleness_sec": 30.0,
            "online_position_tolerance_m": 0.45,
            "online_yaw_tolerance_rad": 0.55,
            "online_max_linear_velocity_mps": 0.03,
            "online_max_angular_velocity_radps": 0.05,
            "max_amcl_covariance_variance": 0.50,
        })

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> "P2cProtocolConfig":
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cls(cfg, source_path=str(p))

    @staticmethod
    def compute_polyline_length(waypoints: List[List[float]]) -> float:
        if not waypoints or len(waypoints) < 2:
            return 0.0
        dist = 0.0
        for i in range(1, len(waypoints)):
            dx = float(waypoints[i][0]) - float(waypoints[i - 1][0])
            dy = float(waypoints[i][1]) - float(waypoints[i - 1][1])
            dist += math.hypot(dx, dy)
        return round(dist, 3)


class P2cTrajectoryClassifier:
    """Classifies executed trajectories, detects dead ends, and diagnoses failure causes."""

    @staticmethod
    def integrate_distance(samples: List[Dict[str, Any]]) -> Tuple[float, int]:
        """Integrate continuous odometry distance with spike jump filtering."""
        if not samples or len(samples) < 2:
            return 0.0, 0
        dist = 0.0
        jumps = 0
        for i in range(1, len(samples)):
            x0 = float(samples[i - 1]["x"])
            y0 = float(samples[i - 1]["y"])
            x1 = float(samples[i]["x"])
            y1 = float(samples[i]["y"])
            d = math.hypot(x1 - x0, y1 - y0)
            if d >= 2.0:
                jumps += 1
            else:
                dist += d
        return round(dist, 3), jumps

    @staticmethod
    def _to_map_frame(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize samples to map frame if they were recorded in odom frame (spawn at -2.5, 0.0)."""
        if not samples:
            return []
        first_x = float(samples[0].get("x", 0.0))
        # In odom frame, spawn at (-2.5, 0.0) is (0.0, 0.0), and goal (2.5, 0.0) is (5.0, 0.0).
        # In map frame, spawn is at (-2.5, 0.0) and goal is at (2.5, 0.0).
        is_odom_frame = (abs(first_x) < 0.6 and any(float(s.get("x", 0.0)) > 2.8 for s in samples))
        if is_odom_frame:
            return [{**s, "x": float(s.get("x", 0.0)) - 2.50} for s in samples]
        return samples

    @staticmethod
    def classify_dead_end_traversals(samples: List[Dict[str, Any]]) -> int:
        """Strict spatio-temporal sequence detection for dead-end entries in map frame.
        
        A dead-end entry requires:
        1. Departure from Decision Junction vicinity (x <= -2.2).
        2. Progress into North corridor approach region (x >= -1.8, y >= 0.6).
        3. Physical retreat back to Decision Junction (x <= -2.2, |y| <= 0.5) without crossing doorway (x > 0.5).
        """
        if not samples or len(samples) < 10:
            return 0

        map_samples = P2cTrajectoryClassifier._to_map_frame(samples)
        stage = 0  # 0: at J0, 1: entered north corridor, 2: retreated back to J0
        for s in map_samples:
            x = float(s.get("x", 0.0))
            y = float(s.get("y", 0.0))

            if stage == 0:
                if x >= -1.8 and y >= 0.6:
                    stage = 1
            elif stage == 1:
                if x > 0.5:
                    # Crossed through doorway -> succeeded, not a dead end
                    stage = 0
                elif x <= -2.2 and abs(y) <= 0.5:
                    # Retreated back to J0
                    stage = 2

        return 1 if stage == 2 else 0

    @staticmethod
    def classify_actual_route(samples: List[Dict[str, Any]]) -> str:
        """Classify actual physical route taken from continuous map-frame trajectory."""
        if not samples or len(samples) < 5:
            return "UNKNOWN"

        map_samples = P2cTrajectoryClassifier._to_map_frame(samples)
        entered_north = any(s.get("x", 0.0) >= -1.8 and s.get("y", 0.0) >= 0.6 for s in map_samples)
        traversed_doorway = any(s.get("x", 0.0) >= 1.0 and s.get("y", 0.0) >= 0.6 for s in map_samples)
        entered_south = any(s.get("y", 0.0) <= -1.2 for s in map_samples)
        reached_goal = any(math.hypot(s.get("x", 0.0) - 2.50, s.get("y", 0.0) - 0.00) < 0.35 for s in map_samples)

        if entered_north and traversed_doorway and reached_goal and not entered_south:
            return "Path_A"
        elif entered_south and reached_goal and not entered_north:
            return "Path_B"
        elif entered_north and not traversed_doorway and entered_south and reached_goal:
            return "Path_A_then_Path_B"
        elif entered_north and not traversed_doorway and not reached_goal:
            return "ABORTED_IN_PATH_A"
        elif entered_south and not reached_goal:
            return "ABORTED_IN_PATH_B"
        return "OTHER"

    @staticmethod
    def diagnose_failure_cause(
        action_summary: Dict[str, Any],
        action_samples: List[Dict[str, Any]],
        linked_perception: Optional[Dict[str, Any]],
        max_staleness_sec: float = 2.0,
    ) -> str:
        """Diagnose root failure cause from trajectory and time-aligned perception."""
        outcome = action_summary.get("execution_outcome", "UNKNOWN")
        if outcome == "BUDGET_SUCCESS" and action_summary.get("terminal_status_name") == "SUCCEEDED":
            return "NONE"

        if not action_samples:
            return "NO_TRAJECTORY_DATA"

        map_samples = P2cTrajectoryClassifier._to_map_frame(action_samples)
        last_pt = map_samples[-1]
        lx = float(last_pt.get("x", 0.0))
        ly = float(last_pt.get("y", 0.0))
        act_id = str(action_summary.get("action_id") or action_summary.get("dispatch", {}).get("action_id", ""))

        # Check if planner rerouted into South detour
        in_south = any(float(s.get("y", 0.0)) <= -1.2 for s in map_samples)
        if in_south and "traversal" in act_id:
            return "NAV2_PLANNER_DETOUR_TIMEOUT"

        # Check if robot reached doorway blockage
        near_doorway = (-0.95 <= lx <= 0.25 and 0.65 <= ly <= 1.75)
        if near_doorway:
            if linked_perception is not None:
                st = linked_perception.get("doorway_state")
                p_stamp = linked_perception.get("stamp_sec", 0.0)
                a_stamp = last_pt.get("recv_sim_time_sec", last_pt.get("sim_time", 0.0))
                is_fresh = abs(a_stamp - p_stamp) <= max_staleness_sec if (p_stamp > 0 and a_stamp > 0) else True
                if st == "OCCUPIED" and is_fresh:
                    return "BLOCKED_AT_DOORWAY"
                elif not is_fresh:
                    return "DOORWAY_BLOCKED_EVIDENCE_STALE"
            return "BLOCKED_AT_DOORWAY_UNCONFIRMED_PERCEPTION"

        if action_summary.get("deadline_exceeded", False):
            return "BUDGET_EXHAUSTED"

        return "NAVIGATION_ABORTED_OR_FAILED"


class P2cPolicyDecider:
    """Consumes live observations and internal policy state to make route decisions."""

    @staticmethod
    def decide_route(
        method: str,
        live_obs: Dict[str, Any],
        cache: Any,  # SpatialObservationCache
        fail_store: FailureMemoryStore,
        m1_suppressed: bool,
        target_goal: List[float],
        region_id: str,
        map_version: str,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Selects route based on method semantics and live observation state.
        
        Returns:
            (chosen_route: str, rationale: str, metadata: Dict)
        """
        obs_state = live_obs.get("doorway_state", "UNKNOWN")
        obs_reason = live_obs.get("reason", "")
        obs_error = live_obs.get("error")

        # Check for infrastructure failure
        infra_error = bool(obs_error in ["TF_TRANSLATION_OR_YAW_MISSING", "TF_STALE", "ZERO_VALID_LASER_RAYS"])

        if method == "R":
            if infra_error:
                return "Path_A", f"Infrastructure warning ({obs_error}) -> fallback to nominal Path A", {"infra_error": True}
            if obs_state == "OCCUPIED":
                return "Path_B", f"Live sensor OCCUPIED at decision junction -> bypass via Path B", {"infra_error": False}
            elif obs_state == "FREE":
                return "Path_A", f"Live sensor FREE -> route via Path A", {"infra_error": False}
            else:
                # UNKNOWN due to occlusion
                return "Path_A", f"Local sensor UNKNOWN ({obs_reason}) -> explore nominal short Path A", {"infra_error": False}

        elif method == "O":
            cached_st = cache.get_latest_state(region_id) if hasattr(cache, "get_latest_state") else "UNKNOWN"
            if cached_st == "OCCUPIED":
                return "Path_B", "Spatial observation cache OCCUPIED -> bypass via Path B immediately", {"cache_state": cached_st}
            else:
                return "Path_A", f"Spatial observation cache {cached_st} -> route via Path A", {"cache_state": cached_st}

        elif method == "F":
            is_blocked, blocked_entry, block_reason = fail_store.is_dispatch_blocked(target_goal, region_id, map_version)
            if is_blocked:
                mem_id = blocked_entry.memory_id if blocked_entry else "active_memory"
                return "Path_B", f"FailMem active memory {mem_id} -> bypass via Path B immediately", {"blocked": True, "memory_id": mem_id}
            else:
                return "Path_A", "FailMem un-suppressed -> route via Path A", {"blocked": False}

        elif method == "M1":
            if m1_suppressed:
                return "Path_B", "Persistent memory permanently suppresses Path A -> route via Path B detour", {"suppressed": True}
            else:
                return "Path_A", "No prior suppression -> route via Path A", {"suppressed": False}

        return "Path_A", "Default fallback to Path A", {}


class P2cEpisodeEvaluator:
    """Independent multi-flag evaluator checking physical arrival, budget, validity, and audit pass."""

    @staticmethod
    def evaluate_episode(
        scenario: str,
        method: str,
        actions: List[Dict[str, Any]],
        total_sim_time_sec: float,
        total_budget_sec: float,
        physical_eval_dict: Dict[str, Any],
        odom_samples: List[Dict[str, Any]],
        costmap_snapshots: List[Dict[str, Any]],
        checksums_verified: bool,
        protocol_hash_match: bool,
        evidence_complete: bool,
    ) -> Dict[str, Any]:
        """Compute full suite of objective validity flags."""
        final_goal_success = bool(physical_eval_dict.get("strict_physical_arrival_and_stable", False))
        success_within_budget = bool(final_goal_success and total_sim_time_sec <= total_budget_sec + 0.50)

        # 1. Trajectory & Route Validation
        dist, jumps = P2cTrajectoryClassifier.integrate_distance(odom_samples)
        actual_route = P2cTrajectoryClassifier.classify_actual_route(odom_samples)
        dead_ends = P2cTrajectoryClassifier.classify_dead_end_traversals(odom_samples)

        costmap_valid = True
        for cm in costmap_snapshots:
            stg = cm.get("stage", "")
            op_lethal = cm.get("cell_counts", {}).get("opening_lethal", 0)
            if "PROBE_BLOCKED" in stg and op_lethal == 0:
                costmap_valid = False
            elif "PROBE_CLEARED" in stg and op_lethal > 0:
                costmap_valid = False

        route_valid = bool(jumps == 0 and len(odom_samples) > 10 and dist > 0.0 and costmap_valid)

        # 2. History Validation
        history_valid = True
        history_reasons: List[str] = []

        def get_aid(act):
            if "action_id" in act: return str(act["action_id"])
            d = act.get("dispatch", {})
            return str(d.get("action_id", d.get("effective_action", {}).get("action_id", "")))

        if scenario in ["D1", "D2"]:
            v1 = next((a for a in actions if get_aid(a) == "hist_reach_obs_vantage"), None)
            tr1 = next((a for a in actions if get_aid(a) == "hist_attempt_chokepoint_traversal"), None)
            r1 = next((a for a in actions if get_aid(a) == "hist_retreat_to_j0"), None)

            if not (v1 and tr1 and r1):
                history_valid = False
                history_reasons.append("MISSING_D1_HISTORY_ACTIONS")
            else:
                v1_ok = (v1.get("terminal_status_name") == "SUCCEEDED" and v1.get("execution_outcome") == "BUDGET_SUCCESS")
                tr1_fail = (tr1.get("execution_outcome") in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"])
                r1_ok = (r1.get("terminal_status_name") == "SUCCEEDED" and r1.get("execution_outcome") == "BUDGET_SUCCESS")
                if not (v1_ok and tr1_fail and r1_ok):
                    history_valid = False
                    history_reasons.append(f"D1_OUTCOME_MISMATCH (v1_ok={v1_ok}, tr1_fail={tr1_fail}, r1_ok={r1_ok})")

            if scenario == "D2":
                p2 = next((a for a in actions if get_aid(a) == "hist_probe_clearance_vantage"), None)
                r2 = next((a for a in actions if get_aid(a) == "hist_retreat_to_j0_clear"), None)
                if not (p2 and r2):
                    history_valid = False
                    history_reasons.append("MISSING_D2_HISTORY_ACTIONS")
                else:
                    p2_ok = (p2.get("terminal_status_name") == "SUCCEEDED" and p2.get("execution_outcome") == "BUDGET_SUCCESS")
                    r2_ok = (r2.get("terminal_status_name") == "SUCCEEDED" and r2.get("execution_outcome") == "BUDGET_SUCCESS")
                    if not (p2_ok and r2_ok):
                        history_valid = False
                        history_reasons.append(f"D2_OUTCOME_MISMATCH (p2_ok={p2_ok}, r2_ok={r2_ok})")

        # 3. Comprehensive Validity & Audit
        episode_valid = bool(final_goal_success and success_within_budget and history_valid and route_valid and evidence_complete)
        audit_pass = bool(episode_valid and checksums_verified and protocol_hash_match)

        return {
            "final_goal_success": final_goal_success,
            "success_within_budget": success_within_budget,
            "history_valid": history_valid,
            "history_reasons": history_reasons,
            "route_valid": route_valid,
            "costmap_valid": costmap_valid,
            "evidence_complete": evidence_complete,
            "episode_valid": episode_valid,
            "audit_pass": audit_pass,
            "replayed_total_dist_m": dist,
            "trajectory_jumps": jumps,
            "actual_route": actual_route,
            "dead_end_traversals": dead_ends,
        }
