"""Targeted unit tests for P1c-v3 state machine, observation contract, and clearance evaluation."""
import math
import unittest
from unittest.mock import MagicMock
from src.observe_interface import ObserveInterface


def evaluate_c2_retry_eligibility(
    obs_result: dict,
    doorway_evidence: dict | None = None,
) -> tuple[bool, dict | None, str]:
    """Pure logic function for evaluating C2 retry eligibility from observation result."""
    # 1. Doorway spatial clearance gate (if evidence provided)
    if doorway_evidence is not None:
        doorway_state = doorway_evidence.get("doorway_state")
        if doorway_state != "FREE":
            return False, None, f"DOORWAY_NOT_FREE ({doorway_state})"

    obs_status = obs_result.get("status")
    obs_data = obs_result.get("observation") or {}
    localization = obs_data.get("localization") or {}
    pose = localization.get("pose")
    frame_id = localization.get("frame_id")
    cov = localization.get("covariance_diagonal")

    # 1. SUCCESS: Valid observation with verified localization
    if obs_status == "SUCCESS":
        if pose is not None and frame_id == "map" and isinstance(pose, (list, tuple)) and len(pose) >= 3:
            return True, {"amcl_pose": pose}, "SUCCESS"
        return False, None, "INVALID_SUCCESS_STRUCTURE"

    # 2. DEGRADED: Permitted ONLY if localization fields are complete and valid in map frame
    if obs_status == "DEGRADED":
        if (
            pose is not None
            and frame_id == "map"
            and isinstance(pose, (list, tuple))
            and len(pose) >= 3
            and all(math.isfinite(x) for x in pose[:3])
            and cov is not None
            and len(cov) >= 3
            and all(math.isfinite(c) for c in cov[:3])
        ):
            return True, {"amcl_pose": pose}, "DEGRADED_LOCALIZATION_VALID"
        return False, None, "DEGRADED_LOCALIZATION_MISSING"

    # 3. ERROR / UNKNOWN
    return False, None, f"OBSERVATION_UNAVAILABLE_{obs_status}"


def evaluate_initial_attempt_early_exit(step_orig_summary: dict, orig_eval: dict) -> tuple[bool, bool, str | None]:
    """Pure logic function evaluating early exit if initial navigation attempt succeeds unexpectedly."""
    strict_arrival = orig_eval.get("strict_physical_arrival_and_stable", False)
    outcome = step_orig_summary.get("execution_outcome")

    if strict_arrival and outcome == "BUDGET_SUCCESS":
        # Task completed on initial attempt; mechanism cannot be verified (no failure to recover from)
        task_success = True
        mechanism_verified = False
        reason = "INITIAL_ATTEMPT_SUCCEEDED_OR_DETOURED"
        return task_success, mechanism_verified, reason

    # Genuine failure: proceed with recovery
    return False, False, None


def check_doorway_laser_clearance(
    ranges: list[float],
    angle_min: float,
    angle_inc: float,
    r_min: float,
    r_max: float,
    robot_pose_map: tuple[float, float, float] | list[float],
    doorway_bbox: tuple[float, float, float, float],
) -> dict:
    """Project 2D laser scan rays into map frame and count points inside doorway bounding box."""
    if not ranges or robot_pose_map is None or len(robot_pose_map) < 3:
        return {"doorway_cleared": False, "points_count": 0, "error": "MISSING_INPUTS"}

    rx, ry, ryaw = robot_pose_map[0], robot_pose_map[1], robot_pose_map[2]
    xmin, xmax, ymin, ymax = doorway_bbox
    points_in_box = []

    for i, r in enumerate(ranges):
        if not math.isfinite(r) or r < r_min or r > r_max:
            continue
        theta = angle_min + i * angle_inc
        lx = r * math.cos(theta)
        ly = r * math.sin(theta)
        mx = rx + lx * math.cos(ryaw) - ly * math.sin(ryaw)
        my = ry + lx * math.sin(ryaw) + ly * math.cos(ryaw)

        if xmin <= mx <= xmax and ymin <= my <= ymax:
            points_in_box.append((mx, my, r))

    points_count = len(points_in_box)
    doorway_cleared = (points_count == 0)
    return {
        "doorway_cleared": doorway_cleared,
        "points_count": points_count,
        "doorway_bbox": doorway_bbox,
        "error": None,
    }


class TestP1cV3StateMachine(unittest.TestCase):
    def setUp(self):
        self.obs_iface = ObserveInterface(
            max_sensor_staleness_sec=0.5,
            max_stationary_amcl_staleness_sec=4.0,
        )

    def test_observe_status_success_allows_retry(self):
        """SUCCESS observation with valid map pose must be accepted for retry."""
        obs_res = {
            "status": "SUCCESS",
            "observation": {
                "localization": {
                    "pose": [-1.8, 0.0, 0.0],
                    "frame_id": "map",
                    "covariance_diagonal": [0.01, 0.01, 0.02],
                    "status": "UP_TO_DATE",
                }
            }
        }
        eligible, visible_state, reason = evaluate_c2_retry_eligibility(obs_res)
        self.assertTrue(eligible)
        self.assertEqual(visible_state, {"amcl_pose": [-1.8, 0.0, 0.0]})
        self.assertEqual(reason, "SUCCESS")

    def test_observe_status_degraded_with_valid_pose_allows_retry(self):
        """DEGRADED observation (e.g. scan missing) with valid map localization must be accepted."""
        obs_res = {
            "status": "DEGRADED",
            "observation": {
                "localization": {
                    "pose": [-1.5, 0.2, 0.05],
                    "frame_id": "map",
                    "covariance_diagonal": [0.02, 0.02, 0.05],
                    "status": "VALID_STATIONARY_CACHE",
                }
            }
        }
        eligible, visible_state, reason = evaluate_c2_retry_eligibility(obs_res)
        self.assertTrue(eligible)
        self.assertEqual(visible_state, {"amcl_pose": [-1.5, 0.2, 0.05]})
        self.assertEqual(reason, "DEGRADED_LOCALIZATION_VALID")

    def test_observe_status_degraded_missing_pose_rejects_retry(self):
        """DEGRADED observation with missing/non-map localization must be rejected."""
        obs_res = {
            "status": "DEGRADED",
            "observation": {
                "localization": {
                    "pose": None,
                    "frame_id": "odom",
                }
            }
        }
        eligible, visible_state, reason = evaluate_c2_retry_eligibility(obs_res)
        self.assertFalse(eligible)
        self.assertIsNone(visible_state)
        self.assertEqual(reason, "DEGRADED_LOCALIZATION_MISSING")

    def test_observe_status_error_rejects_retry(self):
        """ERROR observation must be rejected without faking fallback coordinates."""
        obs_res = {
            "status": "ERROR",
            "error_type": "AMCL_STALE_AFTER_MOTION",
            "observation": None,
        }
        eligible, visible_state, reason = evaluate_c2_retry_eligibility(obs_res)
        self.assertFalse(eligible)
        self.assertIsNone(visible_state)
        self.assertEqual(reason, "OBSERVATION_UNAVAILABLE_ERROR")

    def test_doorway_evidence_not_free_rejects_retry(self):
        """Even with SUCCESS observation, if doorway is OCCUPIED or UNKNOWN, retry is rejected."""
        obs_res = {
            "status": "SUCCESS",
            "observation": {
                "localization": {
                    "pose": [-1.8, 0.0, 0.0],
                    "frame_id": "map",
                    "covariance_diagonal": [0.01, 0.01, 0.02],
                    "status": "UP_TO_DATE",
                }
            }
        }
        # Occupied doorway
        eligible, visible_state, reason = evaluate_c2_retry_eligibility(
            obs_res, doorway_evidence={"doorway_state": "OCCUPIED"}
        )
        self.assertFalse(eligible)
        self.assertIsNone(visible_state)
        self.assertIn("DOORWAY_NOT_FREE", reason)

        # Unknown doorway
        eligible_unk, _, reason_unk = evaluate_c2_retry_eligibility(
            obs_res, doorway_evidence={"doorway_state": "UNKNOWN"}
        )
        self.assertFalse(eligible_unk)
        self.assertIn("DOORWAY_NOT_FREE", reason_unk)

        # Free doorway -> accepts
        eligible_free, vis_free, reason_free = evaluate_c2_retry_eligibility(
            obs_res, doorway_evidence={"doorway_state": "FREE"}
        )
        self.assertTrue(eligible_free)
        self.assertEqual(vis_free, {"amcl_pose": [-1.8, 0.0, 0.0]})
        self.assertEqual(reason_free, "SUCCESS")

    def test_initial_attempt_success_early_exit(self):
        """If initial navigate succeeds (detour), task_success=True and mechanism_verified=False."""
        step_sum = {"execution_outcome": "BUDGET_SUCCESS"}
        eval_dict = {"strict_physical_arrival_and_stable": True}

        task_succ, mech_ver, reason = evaluate_initial_attempt_early_exit(step_sum, eval_dict)
        self.assertTrue(task_succ)
        self.assertFalse(mech_ver)
        self.assertEqual(reason, "INITIAL_ATTEMPT_SUCCEEDED_OR_DETOURED")

    def test_initial_attempt_failure_proceeds_to_recovery(self):
        """If initial navigate fails (blocked), proceed with recovery flow."""
        step_sum = {"execution_outcome": "BUDGET_DEADLINE_EXCEEDED"}
        eval_dict = {"strict_physical_arrival_and_stable": False}

        task_succ, mech_ver, reason = evaluate_initial_attempt_early_exit(step_sum, eval_dict)
        self.assertFalse(task_succ)
        self.assertFalse(mech_ver)
        self.assertIsNone(reason)

    def test_doorway_clearance_detection_blocked_vs_cleared(self):
        """Doorway bounding box correctly detects blockage vs clearance from scan rays."""
        bbox = (-0.25, 0.25, -0.40, 0.40)
        robot_pose = [-1.8, 0.0, 0.0]

        # Case 1: Obstacle at x=0.0 -> rays in forward direction hit at range 1.6m (x_map = -0.2m)
        ranges_blocked = [1.6 if abs(i - 180) < 15 else 3.0 for i in range(360)]
        res_blocked = check_doorway_laser_clearance(
            ranges_blocked, -math.pi, 2 * math.pi / 360, 0.1, 10.0, robot_pose, bbox
        )
        self.assertFalse(res_blocked["doorway_cleared"])
        self.assertGreater(res_blocked["points_count"], 5)

        # Case 2: Cleared doorway -> rays pass through to far wall at range 4.8m (x_map = 3.0m)
        ranges_cleared = [4.8 if abs(i - 180) < 15 else 3.0 for i in range(360)]
        res_cleared = check_doorway_laser_clearance(
            ranges_cleared, -math.pi, 2 * math.pi / 360, 0.1, 10.0, robot_pose, bbox
        )
        self.assertTrue(res_cleared["doorway_cleared"])
        self.assertEqual(res_cleared["points_count"], 0)

    def test_doorway_clearance_missing_pose_fails_safely(self):
        """Missing robot pose or scan fails clearance safely without false positives."""
        bbox = (-0.25, 0.25, -0.40, 0.40)
        res = check_doorway_laser_clearance([], -math.pi, 2 * math.pi / 360, 0.1, 10.0, None, bbox)
        self.assertFalse(res["doorway_cleared"])
        self.assertEqual(res["error"], "MISSING_INPUTS")


if __name__ == "__main__":
    unittest.main()
