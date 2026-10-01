"""Unit tests for P2c automated statistical analysis and integrity checks."""

import json
import shutil
import tempfile
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

from scripts.analyze_p2c_results import (
    load_and_verify_run_episodes,
    compute_condition_summary,
    compute_contrasts,
    analyze_p2c_run,
    EXPECTED_30_EPISODES,
)


@pytest.fixture
def temp_run_dir(tmp_path: Path) -> Path:
    """Fixture to create a mock P2c run directory with 2 conditions (n=2 each)."""
    run_dir = tmp_path / "mock_p2c_run"
    run_dir.mkdir(parents=True, exist_ok=True)

    episodes = [
        {"id": "D1_F_ep1", "scen": "D1", "meth": "F", "dist": 14.0, "time": 110.0, "dead": 0, "run_valid": True, "rep_pass": True},
        {"id": "D1_F_ep2", "scen": "D1", "meth": "F", "dist": 14.2, "time": 108.0, "dead": 0, "run_valid": True, "rep_pass": True},
        {"id": "D1_R_ep1", "scen": "D1", "meth": "R", "dist": 17.5, "time": 145.0, "dead": 1, "run_valid": True, "rep_pass": True},
        {"id": "D1_R_ep2", "scen": "D1", "meth": "R", "dist": 17.1, "time": 139.0, "dead": 1, "run_valid": True, "rep_pass": True},
    ]

    replay_eps = []
    for ep in episodes:
        ep_dir = run_dir / ep["id"]
        ep_dir.mkdir(parents=True, exist_ok=True)

        act_data = {
            "episode_id": ep["id"],
            "scenario": ep["scen"],
            "method": ep["meth"],
            "condition_id": f"{ep['scen']}_{ep['meth']}",
            "requested_route": "Path_B" if ep["meth"] == "F" else "Path_A",
            "actual_route": "Path_B" if ep["meth"] == "F" else "Path_A_then_Path_B",
            "dead_end_traversals": ep["dead"],
            "decision_dispatches": 2,
            "history_distance_m": 6.5,
            "history_sim_time_sec": 60.0,
            "decision_distance_m": ep["dist"] - 6.5,
            "decision_sim_time_sec": ep["time"] - 60.0,
            "total_distance_m": ep["dist"],
            "total_sim_time_sec": ep["time"],
            "final_goal_success": True,
            "success_within_budget": True,
            "history_valid": True,
            "route_valid": True,
            "episode_valid": ep["run_valid"],
        }
        with open(ep_dir / "action_result.json", "w", encoding="utf-8") as f:
            json.dump(act_data, f)

        replay_eps.append({
            "episode_id": ep["id"],
            "scenario": ep["scen"],
            "method": ep["meth"],
            "requested_route": act_data["requested_route"],
            "actual_route": act_data["actual_route"],
            "dead_end_traversals": ep["dead"],
            "recorded_total_dist_m": ep["dist"],
            "replayed_total_dist_m": ep["dist"],
            "distance_discrepancy_m": 0.0,
            "total_sim_time_sec": ep["time"],
            "task_success": True,
            "success_within_budget": True,
            "history_valid": True,
            "route_valid": True,
            "costmap_valid": True,
            "raw_evidence_verified": True,
            "memory_lifecycle_verified": True,
            "policy_matched": True,
            "episode_valid": ep["rep_pass"],
            "audit_pass": ep["rep_pass"],
        })

    with open(run_dir / "p2c_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump({"run_id": run_dir.name, "episodes": replay_eps}, f)

    return run_dir


def test_missing_action_result_fails_integrity(temp_run_dir: Path):
    """Assert missing action_result.json causes integrity check failure and lists missing dir."""
    missing_dir = temp_run_dir / "D1_F_ep1"
    (missing_dir / "action_result.json").unlink()

    episodes, report = load_and_verify_run_episodes(temp_run_dir, expected_episodes=["D1_F_ep1", "D1_F_ep2", "D1_R_ep1", "D1_R_ep2"])
    assert report["integrity_check_passed"] is False
    assert "D1_F_ep1" in report["missing_action_results"]
    assert report["data_complete_count"] == 3


def test_missing_replay_summary_causes_conflict(temp_run_dir: Path):
    """Assert missing replay summary file causes verdict conflict tracking."""
    (temp_run_dir / "p2c_replay_summary.json").unlink()

    episodes, report = load_and_verify_run_episodes(temp_run_dir, expected_episodes=["D1_F_ep1", "D1_F_ep2", "D1_R_ep1", "D1_R_ep2"])
    assert report["integrity_check_passed"] is False
    assert report["conflicts_count"] == 4
    for ep in episodes:
        assert ep["replay_audit_pass"] is None
        assert ep["verdict_conflict"] is True


def test_conflicting_verdict_detection(temp_run_dir: Path):
    """Assert runner self-reporting True vs Replay audit False is detected and reported."""
    with open(temp_run_dir / "p2c_replay_summary.json", "r", encoding="utf-8") as f:
        rep = json.load(f)
    rep["episodes"][0]["audit_pass"] = False
    rep["episodes"][0]["episode_valid"] = False
    with open(temp_run_dir / "p2c_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(rep, f)

    episodes, report = load_and_verify_run_episodes(temp_run_dir, expected_episodes=["D1_F_ep1", "D1_F_ep2", "D1_R_ep1", "D1_R_ep2"])
    assert report["integrity_check_passed"] is False
    assert report["conflicts_count"] == 1
    assert report["conflicts"][0]["episode_id"] == "D1_F_ep1"


def test_sample_std_n_equals_1_returns_na():
    """Assert n=1 condition returns 'NA' for sample standard deviation."""
    df_single = pd.DataFrame([{
        "scenario": "D1",
        "method": "F",
        "condition_id": "D1_F",
        "requested_route": "Path_B",
        "dead_end_traversals": 0,
        "history_distance_m": 6.5,
        "history_sim_time_sec": 60.0,
        "decision_distance_m": 7.5,
        "decision_sim_time_sec": 50.0,
        "total_distance_m": 14.0,
        "total_sim_time_sec": 110.0,
        "runner_goal_success": True,
        "runner_budget_success": True,
        "runner_episode_valid": True,
        "replay_task_success": True,
        "replay_budget_success": True,
        "replay_episode_valid": True,
        "replay_audit_pass": True,
    }])

    summary = compute_condition_summary(df_single)
    assert summary["n"].iloc[0] == 1
    assert summary["total_distance_m_std_ddof1"].iloc[0] == "NA"
    assert summary["decision_sim_time_sec_std_ddof1"].iloc[0] == "NA"


def test_zero_denominator_contrast_relative_difference_na():
    """Assert zero baseline mean outputs 'NA' for relative difference while calculating absolute diff."""
    df_contrasts_test = pd.DataFrame([
        {"scenario": "D1", "method": "F", "dead_end_traversals": 0.0, "total_distance_m": 14.0, "decision_distance_m": 7.5, "decision_sim_time_sec": 50.0, "total_sim_time_sec": 110.0},
        {"scenario": "D1", "method": "F", "dead_end_traversals": 0.0, "total_distance_m": 14.2, "decision_distance_m": 7.5, "decision_sim_time_sec": 48.0, "total_sim_time_sec": 108.0},
        {"scenario": "D1", "method": "O", "dead_end_traversals": 0.0, "total_distance_m": 13.9, "decision_distance_m": 7.5, "decision_sim_time_sec": 50.0, "total_sim_time_sec": 109.0},
        {"scenario": "D1", "method": "O", "dead_end_traversals": 0.0, "total_distance_m": 14.0, "decision_distance_m": 7.5, "decision_sim_time_sec": 50.0, "total_sim_time_sec": 108.0},
    ])

    contrasts = compute_contrasts(df_contrasts_test)
    dead_end_contrast = contrasts[(contrasts["comparison"] == "FailMem vs Spatial Cache") & (contrasts["metric"] == "Dead Ends")]
    assert not dead_end_contrast.empty
    assert dead_end_contrast["abs_diff_a_minus_b"].iloc[0] == 0.0
    assert dead_end_contrast["rel_diff_pct"].iloc[0] == "NA"


def test_missing_numeric_fields_not_defaulted_to_zero(tmp_path: Path):
    """Assert missing numeric fields remain None/NaN rather than defaulting to 0.0."""
    run_dir = tmp_path / "mock_missing_fields"
    ep_dir = run_dir / "D1_F_ep1"
    ep_dir.mkdir(parents=True, exist_ok=True)

    # Omit history_distance_m and total_sim_time_sec
    act_data = {
        "episode_id": "D1_F_ep1",
        "scenario": "D1",
        "method": "F",
        "condition_id": "D1_F",
        "total_distance_m": 14.0,
    }
    with open(ep_dir / "action_result.json", "w", encoding="utf-8") as f:
        json.dump(act_data, f)

    episodes, _ = load_and_verify_run_episodes(run_dir, expected_episodes=["D1_F_ep1"])
    assert episodes[0]["history_distance_m"] is None
    assert episodes[0]["total_sim_time_sec"] is None
    assert episodes[0]["total_distance_m"] == 14.0
