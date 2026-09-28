"""Unit tests for P1b ObserveInterface."""
import unittest
from src.observe_interface import ObserveInterface, filter_observation_whitelist


class TestObserveInterface(unittest.TestCase):
    def setUp(self):
        self.obs_iface = ObserveInterface(max_sensor_staleness_sec=1.0)
        self.valid_amcl = {
            "msg_stamp_sec": 10.0,
            "recv_sim_time_sec": 10.05,
            "x": -1.5,
            "y": -0.5,
            "yaw": 0.1,
            "covariance_diagonal": [0.02, 0.02, 0.05],
            "frame_id": "map",
        }
        self.valid_odom = {
            "msg_stamp_sec": 10.05,
            "recv_sim_time_sec": 10.05,
            "linear_v": 0.0,
            "angular_v": 0.0,
            "frame_id": "odom",
        }
        self.valid_scan = {
            "msg_stamp_sec": 10.0,
            "recv_sim_time_sec": 10.05,
            "min_range": 0.35,
            "valid_count": 360,
            "total_count": 360,
        }

    def test_normal_observation_success(self):
        res = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=self.valid_amcl,
            latest_odom=self.valid_odom,
            latest_scan=self.valid_scan,
            nav2_lifecycle_state="active",
            current_goal_status="IDLE",
        )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertIsNone(res["error_type"])
        obs = res["observation"]
        self.assertEqual(obs["localization"]["pose"], [-1.5, -0.5, 0.1])
        self.assertEqual(obs["odometry"]["linear_velocity_mps"], 0.0)
        self.assertTrue(obs["laser_scan"]["available"])
        self.assertTrue(obs["laser_scan"]["fresh"])
        self.assertEqual(obs["laser_scan"]["min_distance_m"], 0.35)

    def test_missing_amcl_returns_error(self):
        res = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=None,
            latest_odom=self.valid_odom,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "AMCL_UNAVAILABLE")
        self.assertIsNone(res["observation"])

    def test_stale_amcl_returns_error(self):
        res = self.obs_iface.extract_observation(
            current_sim_time=12.5,  # 2.5s later > 1.0s max staleness
            latest_amcl=self.valid_amcl,
            latest_odom=self.valid_odom,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "AMCL_STALE")

    def test_missing_odom_returns_error(self):
        res = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=self.valid_amcl,
            latest_odom=None,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "ODOMETRY_UNAVAILABLE")

    def test_stale_odom_returns_error(self):
        fresh_amcl = dict(self.valid_amcl, msg_stamp_sec=14.8, recv_sim_time_sec=14.8)
        res = self.obs_iface.extract_observation(
            current_sim_time=15.0,
            latest_amcl=fresh_amcl,
            latest_odom=self.valid_odom,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "ODOMETRY_STALE")

    def test_whitelist_security_filter(self):
        """Ensure no ground truth or hidden labels leak even if injected upstream."""
        leaky_data = {
            "pose": [1.0, 2.0, 0.0],
            "ground_truth_pose": [1.05, 2.02, 0.01],
            "gt_label": "stuck_on_obstacle",
            "hidden_fault_injection": {"active": True, "type": "costmap_freeze"},
            "nested": {
                "safe_field": 123,
                "oracle_answer": [-0.5, -0.5],
            },
        }
        cleaned = filter_observation_whitelist(leaky_data)
        self.assertIn("pose", cleaned)
        self.assertNotIn("ground_truth_pose", cleaned)
        self.assertNotIn("gt_label", cleaned)
        self.assertNotIn("hidden_fault_injection", cleaned)
        self.assertIn("safe_field", cleaned["nested"])
        self.assertNotIn("oracle_answer", cleaned["nested"])


if __name__ == "__main__":
    unittest.main()
