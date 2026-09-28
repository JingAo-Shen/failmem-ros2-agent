"""Unit tests for P1b ObserveInterface and strict whitelist schema."""
import unittest
from src.observe_interface import (
    ObserveInterface,
    apply_strict_observation_whitelist,
)


class TestObserveInterface(unittest.TestCase):
    def setUp(self):
        self.obs_iface = ObserveInterface(
            max_sensor_staleness_sec=0.5,
            max_stationary_amcl_staleness_sec=4.0,
        )
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
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
        )
        self.assertEqual(res["status"], "SUCCESS")
        self.assertIsNone(res["error_type"])
        obs = res["observation"]
        self.assertEqual(obs["localization"]["pose"], [-1.5, -0.5, 0.1])
        self.assertEqual(obs["localization"]["status"], "UP_TO_DATE")
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

    def test_stale_amcl_moving_returns_error(self):
        fresh_moving_odom = dict(self.valid_odom, linear_v=0.15, msg_stamp_sec=10.75, recv_sim_time_sec=10.75)
        res = self.obs_iface.extract_observation(
            current_sim_time=10.8,  # 0.8s later > 0.5s max staleness for AMCL (at 10.0)
            latest_amcl=self.valid_amcl,
            latest_odom=fresh_moving_odom,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "AMCL_STALE")

    def test_stale_odom_returns_error(self):
        fresh_amcl = dict(self.valid_amcl, msg_stamp_sec=10.75, recv_sim_time_sec=10.75)
        res = self.obs_iface.extract_observation(
            current_sim_time=10.8,
            latest_amcl=fresh_amcl,
            latest_odom=self.valid_odom,  # at 10.05 -> 0.75s > 0.5s staleness
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "ODOMETRY_STALE")

    def test_stationary_amcl_cache_status(self):
        """When robot is stationary, AMCL within stationary staleness returns VALID_STATIONARY_CACHE."""
        res = self.obs_iface.extract_observation(
            current_sim_time=12.0,  # 2.0s later, within 4.0s stationary staleness
            latest_amcl=self.valid_amcl,
            latest_odom=dict(self.valid_odom, msg_stamp_sec=11.9, recv_sim_time_sec=11.9),
            latest_scan=dict(self.valid_scan, msg_stamp_sec=11.9, recv_sim_time_sec=11.9),
        )
        self.assertEqual(res["status"], "SUCCESS")
        obs = res["observation"]
        self.assertEqual(obs["localization"]["status"], "VALID_STATIONARY_CACHE")
        self.assertEqual(obs["localization"]["staleness_sec"], 2.0)

    def test_missing_covariance_fails_without_fabrication(self):
        no_cov_amcl = dict(self.valid_amcl, covariance_diagonal=None)
        res = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=no_cov_amcl,
            latest_odom=self.valid_odom,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "AMCL_MISSING_COVARIANCE")

    def test_zero_timestamp_rejected(self):
        zero_stamp_odom = dict(self.valid_odom, msg_stamp_sec=0.0)
        res = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=self.valid_amcl,
            latest_odom=zero_stamp_odom,
            latest_scan=self.valid_scan,
        )
        self.assertEqual(res["status"], "ERROR")
        self.assertEqual(res["error_type"], "ODOMETRY_INVALID_TIMESTAMP")

    def test_degraded_scan_contract(self):
        """Missing or stale scan returns DEGRADED status with explicit reason."""
        res_missing = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=self.valid_amcl,
            latest_odom=self.valid_odom,
            latest_scan=None,
        )
        self.assertEqual(res_missing["status"], "DEGRADED")
        self.assertEqual(res_missing["error_type"], "SCAN_DEGRADED")
        self.assertFalse(res_missing["observation"]["laser_scan"]["available"])

        stale_scan = dict(self.valid_scan, msg_stamp_sec=8.0)
        res_stale = self.obs_iface.extract_observation(
            current_sim_time=10.1,
            latest_amcl=self.valid_amcl,
            latest_odom=self.valid_odom,
            latest_scan=stale_scan,
        )
        self.assertEqual(res_stale["status"], "DEGRADED")
        self.assertFalse(res_stale["observation"]["laser_scan"]["fresh"])

    def test_whitelist_strict_schema_filter(self):
        """Ensure arbitrary named or nested fields cannot leak into policy output."""
        leaky_data = {
            "timestamp": {"sim_time_sec": 10.0, "amcl_stamp_sec": 10.0, "extra_leak": 999},
            "localization": {
                "pose": [1.0, 2.0, 0.0],
                "covariance_diagonal": [0.01, 0.01, 0.01],
                "frame_id": "map",
                "ground_truth_pose": [1.05, 2.02, 0.01],
                "hidden_oracle_code": "SECRET_KEY_123",
            },
            "odometry": {
                "linear_velocity_mps": 0.0,
                "angular_velocity_radps": 0.0,
                "gt_accel": 0.5,
            },
            "laser_scan": {
                "available": True,
                "fresh": True,
                "min_distance_m": 0.35,
                "valid_ranges_count": 360,
                "total_ranges_count": 360,
                "simulated_noise_params": [0.1, 0.2],
            },
            "arbitrary_top_level": {"injected_fault": True, "answer": [0.0, 0.0]},
        }
        cleaned = apply_strict_observation_whitelist(leaky_data)
        self.assertNotIn("arbitrary_top_level", cleaned)
        self.assertNotIn("extra_leak", cleaned["timestamp"])
        self.assertNotIn("ground_truth_pose", cleaned["localization"])
        self.assertNotIn("hidden_oracle_code", cleaned["localization"])
        self.assertNotIn("gt_accel", cleaned["odometry"])
        self.assertNotIn("simulated_noise_params", cleaned["laser_scan"])
        # Check standard fields are preserved
        self.assertEqual(cleaned["localization"]["pose"], [1.0, 2.0, 0.0])


if __name__ == "__main__":
    unittest.main()
