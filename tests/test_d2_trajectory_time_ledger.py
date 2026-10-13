"""Unit and fault-injection tests for D2 Trajectory Time Ledger analysis and validation."""

import math
import pytest
from pathlib import Path
from typing import Dict, Any, List

from scripts.analyze_d2_trajectory_time_ledger import (
    validate_action_intervals,
    validate_trajectory_timestamps,
    classify_velocity,
    decompose_phase,
    analyze_episode,
    DEFAULT_V_LIN_THRESH,
    DEFAULT_V_ANG_THRESH,
)


def test_normal_clean_data_passes_validation():
    """Clean actions and samples must pass validation."""
    actions = [
        {"dispatch": {"action_id": "act_1"}, "timestamp_sim_start": 10.0, "timestamp_sim": 20.0},
        {"dispatch": {"action_id": "act_2"}, "timestamp_sim_start": 20.5, "timestamp_sim": 30.0},
    ]
    samples = [
        {"recv_sim_time_sec": 10.0, "linear_v": 0.1, "angular_v": 0.0},
        {"recv_sim_time_sec": 15.0, "linear_v": 0.1, "angular_v": 0.0},
        {"recv_sim_time_sec": 20.0, "linear_v": 0.0, "angular_v": 0.0},
    ]

    act_val = validate_action_intervals(actions)
    assert act_val["valid"] is True
    assert act_val["overlap_count"] == 0
    assert len(act_val["issues"]) == 0

    traj_val = validate_trajectory_timestamps(samples)
    assert traj_val["valid"] is True
    assert len(traj_val["issues"]) == 0


def test_fault_injection_overlapping_actions_fails_validation():
    """Overlapping actions must cause validation to FAIL (valid == False)."""
    actions = [
        {"dispatch": {"action_id": "act_1"}, "timestamp_sim_start": 10.0, "timestamp_sim": 20.0},
        {"dispatch": {"action_id": "act_2"}, "timestamp_sim_start": 19.5, "timestamp_sim": 30.0},  # Overlaps by 0.5s
    ]
    act_val = validate_action_intervals(actions)
    assert act_val["valid"] is False
    assert act_val["overlap_count"] == 1
    assert act_val["total_overlap_sec"] == pytest.approx(0.5, abs=1e-4)


def test_fault_injection_non_finite_timestamps_fails_validation():
    """Non-finite timestamps in trajectory or actions must cause validation to FAIL."""
    actions_bad = [
        {"dispatch": {"action_id": "act_1"}, "timestamp_sim_start": 10.0, "timestamp_sim": float("nan")},
    ]
    act_val = validate_action_intervals(actions_bad)
    assert act_val["valid"] is False
    assert any("NON_FINITE" in issue for issue in act_val["issues"])

    samples_bad = [
        {"recv_sim_time_sec": 10.0, "linear_v": 0.1, "angular_v": 0.0},
        {"recv_sim_time_sec": float("inf"), "linear_v": 0.1, "angular_v": 0.0},
    ]
    traj_val = validate_trajectory_timestamps(samples_bad)
    assert traj_val["valid"] is False
    assert any("NON_FINITE" in issue for issue in traj_val["issues"])


def test_fault_injection_missing_velocity_fields_accounted_as_unknown():
    """Missing or NaN velocity fields must be classified as UNKNOWN and absorbed in unobserved active time."""
    assert classify_velocity(None, 0.0, DEFAULT_V_LIN_THRESH, DEFAULT_V_ANG_THRESH) == "UNKNOWN"
    assert classify_velocity(0.1, None, DEFAULT_V_LIN_THRESH, DEFAULT_V_ANG_THRESH) == "UNKNOWN"
    assert classify_velocity(float("nan"), 0.0, DEFAULT_V_LIN_THRESH, DEFAULT_V_ANG_THRESH) == "UNKNOWN"

    actions = [
        {"dispatch": {"action_id": "act_1"}, "timestamp_sim_start": 10.0, "timestamp_sim": 20.0},
    ]
    samples_with_missing = [
        {"recv_sim_time_sec": 10.0, "linear_v": None, "angular_v": None},
        {"recv_sim_time_sec": 10.1, "linear_v": None, "angular_v": None},
        {"recv_sim_time_sec": 10.2, "linear_v": 0.0, "angular_v": 0.0},
    ]
    dec = decompose_phase(actions, samples_with_missing, total_phase_time=10.0)
    assert dec["algebraic_closure_valid"] is True
    assert dec["unobserved_details"]["missing_velocity_fields_time"] > 0.0


def test_fault_injection_cross_phase_actions_detected(tmp_path: Path):
    """Actions crossing phase boundaries must trigger cross_phase_overlap detection."""
    ep_dir = tmp_path / "corrupted_ep"
    ep_dir.mkdir(parents=True)

    action_result = {
        "episode_id": "corrupted_ep",
        "condition_id": "D2_F",
        "scenario": "D2",
        "method": "F",
        "total_sim_time_sec": 100.0,
        "history_sim_time_sec": 50.0,
        "decision_sim_time_sec": 50.0,
        "actions": [
            {"dispatch": {"action_id": "hist_1"}, "timestamp_sim_start": 0.0, "timestamp_sim": 60.0},  # Crosses into decision (50.0)
            {"dispatch": {"action_id": "dec_1"}, "timestamp_sim_start": 55.0, "timestamp_sim": 100.0}, # Overlaps hist_1
        ],
    }
    trajectory = {
        "gt_trajectory": [
            {"recv_sim_time_sec": 0.0, "linear_v": 0.0, "angular_v": 0.0},
            {"recv_sim_time_sec": 100.0, "linear_v": 0.0, "angular_v": 0.0},
        ],
        "odom_trajectory": [
            {"recv_sim_time_sec": 0.0, "linear_v": 0.0, "angular_v": 0.0},
            {"recv_sim_time_sec": 100.0, "linear_v": 0.0, "angular_v": 0.0},
        ],
    }
    stability = {"sample_count": 0, "window_records": []}

    import json
    with open(ep_dir / "action_result.json", "w") as f:
        json.dump(action_result, f)
    with open(ep_dir / "trajectory.json", "w") as f:
        json.dump(trajectory, f)
    with open(ep_dir / "stability_window.json", "w") as f:
        json.dump(stability, f)

    res = analyze_episode(ep_dir)
    assert res["validation"]["is_valid"] is False
    assert res["validation"]["cross_phase_overlap"] is True
