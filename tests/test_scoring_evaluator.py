"""Unit tests for offline scoring evaluator with required negative cases."""
import pytest
from src.scoring_evaluator import (
    evaluate_sensor_freshness_and_window,
    evaluate_physical_halt,
    evaluate_navigation_episode,
    evaluate_cancellation_episode,
    audit_localization_discrepancy,
)

DEFAULT_THRESHOLDS = {
    "position_tolerance_m": 0.30,
    "yaw_tolerance_rad": 0.35,
    "max_linear_velocity_mps": 0.05,
    "max_angular_velocity_radps": 0.05,
    "stability_window_duration_sim_sec": 2.0,
    "max_sensor_staleness_sim_sec": 0.5,
    "max_time_alignment_delta_sim_sec": 0.1,
}


def make_valid_sample(sim_time: float, x: float = -0.5, y: float = -0.5, yaw: float = 0.0, lv: float = 0.0, av: float = 0.0, seq: int = 0):
    return {
        "seq": seq,
        "sim_time": sim_time,
        "gt": {
            "recv_sim_time_sec": sim_time,
            "monotonic_wall_sec": 1000.0 + sim_time,
            "x": x,
            "y": y,
            "yaw": yaw,
        },
        "odom": {
            "msg_stamp_sec": sim_time,
            "recv_sim_time_sec": sim_time,
            "monotonic_wall_sec": 1000.0 + sim_time,
            "x": x,
            "y": y,
            "yaw": yaw,
            "linear_v": lv,
            "angular_v": av,
        },
        "cmd_vel": {
            "recv_sim_time_sec": sim_time,
            "linear_x": 0.0,
            "angular_z": 0.0,
        },
    }


def make_valid_window(duration: float = 2.0, dt: float = 0.1, x: float = -0.5, y: float = -0.5, yaw: float = 0.0):
    samples = []
    t = 10.0
    seq = 0
    while (t - 10.0) <= duration:
        samples.append(make_valid_sample(round(t, 2), x=x, y=y, yaw=yaw, lv=0.0, av=0.0, seq=seq))
        t += dt
        seq += 1
    return samples


class TestScoringEvaluatorNegativeCases:
    """Rigorous negative tests for scoring rules."""

    def test_negative_stale_cache_repeated_sampling(self):
        """Reading identical cached sample repeatedly must NOT pass window validity."""
        single_sample = make_valid_sample(10.0, seq=1)
        # Repeat the identical sample 30 times
        stale_samples = [single_sample] * 30
        res = evaluate_sensor_freshness_and_window(stale_samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert "INSUFFICIENT_UNIQUE_SAMPLES" in res["failure_reasons"] or "INSUFFICIENT_WINDOW_DURATION" in str(res["failure_reasons"])

    def test_negative_missing_odom(self):
        """Missing odom must NOT pass."""
        samples = make_valid_window(2.0)
        for s in samples:
            s["odom"] = None
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("MISSING_REQUIRED_SENSORS" in r for r in res["failure_reasons"])

    def test_negative_nan_coordinates(self):
        """NaN in GT or Odom coordinates must NOT pass."""
        samples = make_valid_window(2.0)
        samples[5]["gt"]["x"] = float("nan")
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("NON_FINITE" in r for r in res["failure_reasons"])

    def test_negative_nan_velocity(self):
        """NaN in Odom velocity must NOT pass."""
        samples = make_valid_window(2.0)
        samples[3]["odom"]["linear_v"] = float("nan")
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("NON_FINITE" in r for r in res["failure_reasons"])

    def test_negative_insufficient_window_duration(self):
        """Window covering only 1.2s sim time (< 2.0s) must NOT pass."""
        samples = make_valid_window(duration=1.2)
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("INSUFFICIENT_WINDOW_DURATION" in r for r in res["failure_reasons"])

    def test_negative_clock_pause_freeze(self):
        """Sim clock freeze (delta t = 0 across 50 iterations) must NOT pass."""
        samples = [make_valid_sample(10.0, seq=i) for i in range(50)]
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("INSUFFICIENT_WINDOW_DURATION" in r for r in res["failure_reasons"])

    def test_negative_watchdog_triggered_early_exit(self):
        """Watchdog triggered early exit must NOT pass even if samples exist."""
        samples = make_valid_window(2.0)
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS, watchdog_triggered=True)
        assert res["window_valid"] is False
        assert "WATCHDOG_TRIGGERED_EARLY_EXIT" in res["failure_reasons"]

    def test_negative_cancel_before_movement(self):
        """Cancel test where movement was NOT confirmed (v <= 0.05) must NOT pass."""
        samples = make_valid_window(2.0)
        res = evaluate_cancellation_episode(
            nav2_status="CANCELED",
            movement_confirmed_before_cancel=False,
            cancel_request_accepted=True,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
            safety_intervention=False,
        )
        assert res["cancel_stop_verified"] is False
        assert "MOVEMENT_NOT_CONFIRMED_BEFORE_CANCEL" in res["failure_reasons"]

    def test_negative_cancel_rejection(self):
        """Cancel test where cancel request was rejected must NOT pass."""
        samples = make_valid_window(2.0)
        res = evaluate_cancellation_episode(
            nav2_status="CANCELED",
            movement_confirmed_before_cancel=True,
            cancel_request_accepted=False,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
            safety_intervention=False,
        )
        assert res["cancel_stop_verified"] is False
        assert "CANCEL_REQUEST_NOT_ACCEPTED" in res["failure_reasons"]

    def test_negative_external_safety_intervention(self):
        """Safety intervention override must NOT pass as autonomous halt."""
        samples = make_valid_window(2.0)
        res = evaluate_physical_halt(samples, DEFAULT_THRESHOLDS, safety_intervention=True)
        assert res["halt_verified"] is False
        assert res["safety_intervention"] is True
        assert res["halt_failure_reason"] == "SAFETY_INTERVENTION_OVERRIDE_TRIGGERED"

    def test_negative_navigation_position_out_of_tolerance(self):
        """GT position error of 0.35m (> 0.30m threshold) must NOT pass."""
        samples = make_valid_window(2.0, x=-0.5, y=-0.15)  # error = 0.35m from goal [-0.5, -0.5, 0.0]
        final_gt = {"x": -0.5, "y": -0.15, "yaw": 0.0}
        res = evaluate_navigation_episode(
            target_goal=[-0.5, -0.5, 0.0],
            nav2_status="SUCCEEDED",
            final_gt=final_gt,
            final_amcl=final_gt,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
        )
        assert res["final_geometric_errors"]["gt_position_error_m"] == 0.35
        assert res["final_pose_arrived"] is False
        assert res["strict_physical_arrival_and_stable"] is False


class TestScoringEvaluatorPositiveCases:
    """Positive cases verifying valid behaviors pass strictly."""

    def test_positive_navigation_success(self):
        samples = make_valid_window(2.0, x=-0.55, y=-0.52, yaw=0.05)  # error ~0.053m
        final_gt = {"x": -0.55, "y": -0.52, "yaw": 0.05}
        res = evaluate_navigation_episode(
            target_goal=[-0.5, -0.5, 0.0],
            nav2_status="SUCCEEDED",
            final_gt=final_gt,
            final_amcl=final_gt,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
        )
        assert res["nav2_action_succeeded"] is True
        assert res["final_pose_arrived"] is True
        assert res["strict_physical_arrival_and_stable"] is True

    def test_positive_cancellation_success(self):
        samples = make_valid_window(2.0, x=-1.9, y=-0.5, yaw=0.0)
        res = evaluate_cancellation_episode(
            nav2_status="CANCELED",
            movement_confirmed_before_cancel=True,
            cancel_request_accepted=True,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
            safety_intervention=False,
        )
        assert res["cancel_stop_verified"] is True
        assert len(res["failure_reasons"]) == 0
