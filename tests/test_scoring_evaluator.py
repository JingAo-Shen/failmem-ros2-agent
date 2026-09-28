"""Unit tests for offline scoring evaluator with comprehensive negative and positive cases."""
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
    "max_gt_displacement_m": 0.03,
    "max_sensor_staleness_sim_sec": 0.5,
    "max_time_alignment_delta_sim_sec": 0.1,
}


def make_valid_sample(
    sim_time: float,
    x: float = -0.5,
    y: float = -0.5,
    yaw: float = 0.0,
    lv: float = 0.0,
    av: float = 0.0,
    seq: int = 0,
    odom_stamp: float = None,
    gt_stamp: float = None,
    odom_seq: int = None,
    gt_seq: int = None,
):
    odom_t = odom_stamp if odom_stamp is not None else sim_time
    gt_t = gt_stamp if gt_stamp is not None else sim_time
    o_seq = odom_seq if odom_seq is not None else seq
    g_seq = gt_seq if gt_seq is not None else seq
    return {
        "seq": seq,
        "sim_time": sim_time,
        "gt": {
            "seq": g_seq,
            "recv_sim_time_sec": gt_t,
            "monotonic_wall_sec": 1000.0 + sim_time,
            "x": x,
            "y": y,
            "yaw": yaw,
        },
        "odom": {
            "seq": o_seq,
            "msg_stamp_sec": odom_t,
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


def make_valid_window(
    duration: float = 2.0,
    dt: float = 0.1,
    x: float = -0.5,
    y: float = -0.5,
    yaw: float = 0.0,
):
    samples = []
    t = 10.0
    seq = 0
    while round(t - 10.0, 4) <= duration:
        samples.append(
            make_valid_sample(
                round(t, 2),
                x=x,
                y=y,
                yaw=yaw,
                lv=0.0,
                av=0.0,
                seq=seq,
                odom_stamp=round(t, 2),
                gt_stamp=round(t, 2),
                odom_seq=seq,
                gt_seq=seq,
            )
        )
        t += dt
        seq += 1
    return samples


class TestScoringEvaluatorNegativeCases:
    """Rigorous negative tests for scoring evaluator."""

    def test_negative_outer_seq_increment_with_frozen_sensor_cache(self):
        """Outer seq increments but underlying odom/GT sensors are frozen cache. Must FAIL."""
        samples = []
        for i in range(25):
            # Outer seq and sim_time advance, but odom and GT stamps/seq are frozen at t=10.0
            samples.append(
                make_valid_sample(
                    sim_time=10.0 + i * 0.1,
                    seq=i,
                    odom_stamp=10.0,
                    gt_stamp=10.0,
                    odom_seq=1,
                    gt_seq=1,
                )
            )
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("INSUFFICIENT_UNIQUE" in r or "EXPIRED" in r for r in res["failure_reasons"])

    def test_negative_odom_updates_but_gt_frozen(self):
        """Odom updates normally over 2.0s, but GT is frozen at initial stamp. Must FAIL."""
        samples = []
        for i in range(22):
            t = 10.0 + i * 0.1
            samples.append(
                make_valid_sample(
                    sim_time=t,
                    seq=i,
                    odom_stamp=t,
                    odom_seq=i,
                    gt_stamp=10.0,  # Frozen GT
                    gt_seq=1,
                )
            )
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("GT" in r and ("INSUFFICIENT" in r or "EXPIRED" in r) for r in res["failure_reasons"])

    def test_negative_missing_or_nan_timestamps(self):
        """Missing or NaN timestamps must fail without crashing."""
        samples = make_valid_window(2.0)
        samples[4]["odom"]["msg_stamp_sec"] = float("nan")
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("NON_FINITE" in r for r in res["failure_reasons"])

        samples2 = make_valid_window(2.0)
        samples2[4]["gt"]["recv_sim_time_sec"] = None
        res2 = evaluate_sensor_freshness_and_window(samples2, DEFAULT_THRESHOLDS)
        assert res2["window_valid"] is False
        assert any("NON_FINITE" in r for r in res2["failure_reasons"])

    def test_negative_future_timestamp(self):
        """Sensor timestamp in the future relative to sampling time must FAIL."""
        samples = make_valid_window(2.0)
        samples[5]["odom"]["msg_stamp_sec"] = samples[5]["sim_time"] + 2.0
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("FUTURE" in r for r in res["failure_reasons"])

    def test_negative_retrograde_timestamp(self):
        """Timestamps that go backwards (time reversal) must FAIL."""
        samples = make_valid_window(2.0)
        samples[6]["odom"]["msg_stamp_sec"] = samples[4]["odom"]["msg_stamp_sec"] - 0.5
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("RETROGRADE" in r for r in res["failure_reasons"])

    def test_negative_1_96_second_window_strictly_fails(self):
        """Window covering 1.96s sim time strictly fails 2.0s requirement without implicit relaxation."""
        samples = make_valid_window(duration=1.96, dt=0.04)
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("INSUFFICIENT_WINDOW_DURATION" in r or "INSUFFICIENT_ODOM_DURATION" in r for r in res["failure_reasons"])

    def test_negative_missing_odom_or_gt(self):
        """Missing whole odom or GT dictionary must return structured failure."""
        samples = make_valid_window(2.0)
        samples[3]["odom"] = None
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False
        assert any("MISSING_ODOM" in r for r in res["failure_reasons"])

        samples_gt = make_valid_window(2.0)
        samples_gt[3]["gt"] = None
        res_gt = evaluate_sensor_freshness_and_window(samples_gt, DEFAULT_THRESHOLDS)
        assert res_gt["window_valid"] is False
        assert any("MISSING_GT" in r for r in res_gt["failure_reasons"])

    def test_negative_physical_halt_missing_odom_and_nan(self):
        """evaluate_physical_halt handles missing odom and NaN velocities gracefully."""
        samples = make_valid_window(2.0)
        samples[2]["odom"] = None
        halt_res = evaluate_physical_halt(samples, DEFAULT_THRESHOLDS)
        assert halt_res["halt_verified"] is False
        assert "MISSING_ODOM" in halt_res["halt_failure_reason"]

        samples2 = make_valid_window(2.0)
        samples2[2]["odom"]["linear_v"] = float("nan")
        halt_res2 = evaluate_physical_halt(samples2, DEFAULT_THRESHOLDS)
        assert halt_res2["halt_verified"] is False
        assert "NON_FINITE_ODOM_VELOCITY" in halt_res2["halt_failure_reason"]

    def test_negative_physical_halt_missing_gt_formatting(self):
        """evaluate_physical_halt with missing GT returns structured failure and does not crash formatting max_gt_disp."""
        samples = make_valid_window(2.0)
        for s in samples:
            s["gt"] = None
        halt_res = evaluate_physical_halt(samples, DEFAULT_THRESHOLDS)
        assert halt_res["halt_verified"] is False
        assert "MISSING_OR_NON_FINITE_GT" in halt_res["halt_failure_reason"]
        assert halt_res["max_gt_displacement_m"] is None

    def test_negative_clock_pause_freeze(self):
        """Sim clock freeze (delta t = 0 across 50 iterations) must NOT pass."""
        samples = [make_valid_sample(10.0, seq=i, odom_stamp=10.0, gt_stamp=10.0) for i in range(50)]
        res = evaluate_sensor_freshness_and_window(samples, DEFAULT_THRESHOLDS)
        assert res["window_valid"] is False

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
        res = evaluate_cancellation_episode(
            nav2_status="CANCELED",
            movement_confirmed_before_cancel=True,
            cancel_request_accepted=True,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
            safety_intervention=True,
        )
        assert res["cancel_stop_verified"] is False
        assert "EXTERNAL_SAFETY_INTERVENTION_USED" in res["failure_reasons"]

    def test_negative_navigation_position_out_of_tolerance(self):
        """Final position error > 0.30m must NOT pass."""
        samples = make_valid_window(2.0, x=0.0, y=0.0)
        final_gt = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        final_amcl = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        target = [-0.5, -0.5, 0.0]  # dist ~ 0.707m > 0.30m
        res = evaluate_navigation_episode(
            target_goal=target,
            nav2_status="SUCCEEDED",
            final_gt=final_gt,
            final_amcl=final_amcl,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
        )
        assert res["strict_physical_arrival_and_stable"] is False
        assert res["final_pose_arrived"] is False


class TestScoringEvaluatorPositiveCases:
    """Positive tests for scoring rules."""

    def test_positive_navigation_success(self):
        """Valid navigation episode strictly within contract."""
        samples = make_valid_window(duration=2.2, x=-0.5, y=-0.5, yaw=0.0)
        final_gt = {"x": -0.5, "y": -0.5, "yaw": 0.0}
        final_amcl = {"x": -0.51, "y": -0.49, "yaw": 0.01}
        target = [-0.5, -0.5, 0.0]
        res = evaluate_navigation_episode(
            target_goal=target,
            nav2_status="SUCCEEDED",
            final_gt=final_gt,
            final_amcl=final_amcl,
            stability_samples=samples,
            thresholds=DEFAULT_THRESHOLDS,
        )
        assert res["strict_physical_arrival_and_stable"] is True
        assert res["nav2_action_succeeded"] is True
        assert res["final_pose_arrived"] is True

    def test_positive_cancellation_success(self):
        """Valid cancellation episode with confirmed movement, accepted cancel, and 2.2s stable halt."""
        samples = make_valid_window(duration=2.2, x=-1.5, y=-0.5, yaw=0.1)
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
