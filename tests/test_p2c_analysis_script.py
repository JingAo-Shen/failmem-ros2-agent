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
    """Assert missing numeric fields remain None/NaN rather than defaulting to 0.0, and marks data_complete=False."""
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

    episodes, report = load_and_verify_run_episodes(run_dir, expected_episodes=["D1_F_ep1"])
    assert episodes[0]["history_distance_m"] is None
    assert episodes[0]["total_sim_time_sec"] is None
    assert episodes[0]["total_distance_m"] == 14.0
    assert episodes[0]["data_complete"] is False
    assert report["integrity_check_passed"] is False
    assert len(report["invalid_action_results"]) == 1


def test_invalid_field_type_and_non_finite_fails_integrity(tmp_path: Path):
    """Assert non-finite float (NaN/Inf) or wrong type causes data_complete=False and integrity failure."""
    run_dir = tmp_path / "mock_invalid_types"
    ep_dir = run_dir / "D1_F_ep1"
    ep_dir.mkdir(parents=True, exist_ok=True)

    act_data = {
        "episode_id": "D1_F_ep1",
        "scenario": "D1",
        "method": "F",
        "condition_id": "D1_F",
        "total_distance_m": "fourteen_meters",  # invalid string type for numeric
        "total_sim_time_sec": 100.0,
        "decision_distance_m": 7.5,
        "decision_sim_time_sec": 40.0,
        "dead_end_traversals": 0,
        "final_goal_success": True,
        "success_within_budget": True,
        "history_valid": True,
        "route_valid": True,
        "episode_valid": True,
    }
    with open(ep_dir / "action_result.json", "w", encoding="utf-8") as f:
        json.dump(act_data, f)

    episodes, report = load_and_verify_run_episodes(run_dir, expected_episodes=["D1_F_ep1"])
    assert episodes[0]["data_complete"] is False
    assert episodes[0]["total_distance_m"] is None
    assert report["integrity_check_passed"] is False
    assert len(report["invalid_action_results"]) == 1
    assert any("TYPE_MISMATCH_total_distance_m" in issue for issue in report["invalid_action_results"][0]["issues"])


def test_duplicate_replay_id_fails_integrity(temp_run_dir: Path):
    """Assert duplicate replay IDs in p2c_replay_summary.json causes integrity failure."""
    with open(temp_run_dir / "p2c_replay_summary.json", "r", encoding="utf-8") as f:
        rep = json.load(f)
    # Duplicate the first episode record
    rep["episodes"].append(dict(rep["episodes"][0]))
    with open(temp_run_dir / "p2c_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(rep, f)

    episodes, report = load_and_verify_run_episodes(temp_run_dir, expected_episodes=["D1_F_ep1", "D1_F_ep2", "D1_R_ep1", "D1_R_ep2"])
    assert report["integrity_check_passed"] is False
    assert "D1_F_ep1" in report["duplicate_replay_ids"]


def test_identity_and_condition_mismatch_fails_integrity(temp_run_dir: Path):
    """Assert mismatch between directory name and file scenario/method metadata causes integrity failure."""
    act_file = temp_run_dir / "D1_F_ep1" / "action_result.json"
    with open(act_file, "r", encoding="utf-8") as f:
        act = json.load(f)
    # Mismatch scenario and method inside file
    act["scenario"] = "D0"
    act["method"] = "R"
    with open(act_file, "w", encoding="utf-8") as f:
        json.dump(act, f)

    episodes, report = load_and_verify_run_episodes(temp_run_dir, expected_episodes=["D1_F_ep1", "D1_F_ep2", "D1_R_ep1", "D1_R_ep2"])
    assert report["integrity_check_passed"] is False
    assert len(report["identity_mismatches"]) == 1
    assert report["identity_mismatches"][0]["episode_id"] == "D1_F_ep1"


def test_analyze_p2c_run_generates_integrity_report_and_valid_counts(temp_run_dir: Path, tmp_path: Path):
    """Assert analyze_p2c_run persists integrity_report.json and condition summary includes valid counts."""
    out_dir = tmp_path / "analysis_out"
    res = analyze_p2c_run(temp_run_dir, output_dir=out_dir, expected_episodes=["D1_F_ep1", "D1_F_ep2", "D1_R_ep1", "D1_R_ep2"])

    assert (out_dir / "integrity_report.json").exists()
    with open(out_dir / "integrity_report.json", "r", encoding="utf-8") as f:
        saved_report = json.load(f)
    assert saved_report["integrity_check_passed"] is True
    assert saved_report["data_complete_count"] == 4

    summary_df = res["summary_df"]
    assert "total_distance_m_n_valid" in summary_df.columns
    assert "decision_sim_time_sec_n_valid" in summary_df.columns
    assert summary_df["total_distance_m_n_valid"].iloc[0] == 2


def test_h1_derived_parser_and_go_nogo_decision(tmp_path: Path):
    """Assert H1 offline parser correctly parses records, decomposes timings, and enforces strict No-Go."""
    from scripts.verify_h1_feasibility import parse_and_derive_h1_evidence, evaluate_h1_go_nogo

    # Test with mock parsed runs where oblique succeeded (should be NO-GO)
    mock_runs = [
        {"profile_id": "act_aligned", "doorway_state_before_action": "FREE", "terminal_status_name": "SUCCEEDED", "terminal_status_code": 4, "physical_arrival_verified": False, "execution_outcome": "BUDGET_SUCCESS"},
        {"profile_id": "act_aligned", "doorway_state_before_action": "FREE", "terminal_status_name": "SUCCEEDED", "terminal_status_code": 4, "physical_arrival_verified": True, "execution_outcome": "BUDGET_SUCCESS"},
        {"profile_id": "act_oblique", "doorway_state_before_action": "FREE", "terminal_status_name": "SUCCEEDED", "terminal_status_code": 4, "physical_arrival_verified": True, "execution_outcome": "BUDGET_SUCCESS"},
        {"profile_id": "act_oblique", "doorway_state_before_action": "FREE", "terminal_status_name": "SUCCEEDED", "terminal_status_code": 4, "physical_arrival_verified": True, "execution_outcome": "BUDGET_SUCCESS"},
    ]
    res_nogo = evaluate_h1_go_nogo(mock_runs)
    assert res_nogo["go_condition_met"] is False
    assert "NO-GO" in res_nogo["verdict"]
    assert res_nogo["aligned_strict_successes"] == 1  # only 1 passed physical arrival
    assert res_nogo["oblique_failures"] == 0

    # Test with hypothetical successful separation (2 strict successes, 2 failures)
    mock_runs_go = [
        {"profile_id": "act_aligned", "doorway_state_before_action": "FREE", "terminal_status_name": "SUCCEEDED", "terminal_status_code": 4, "physical_arrival_verified": True, "execution_outcome": "BUDGET_SUCCESS"},
        {"profile_id": "act_aligned", "doorway_state_before_action": "FREE", "terminal_status_name": "SUCCEEDED", "terminal_status_code": 4, "physical_arrival_verified": True, "execution_outcome": "BUDGET_SUCCESS"},
        {"profile_id": "act_oblique", "doorway_state_before_action": "FREE", "terminal_status_name": "ABORTED", "terminal_status_code": 6, "physical_arrival_verified": False, "execution_outcome": "BUDGET_DEADLINE_EXCEEDED"},
        {"profile_id": "act_oblique", "doorway_state_before_action": "FREE", "terminal_status_name": "ABORTED", "terminal_status_code": 6, "physical_arrival_verified": False, "execution_outcome": "BUDGET_DEADLINE_EXCEEDED"},
    ]
    res_go = evaluate_h1_go_nogo(mock_runs_go)
    assert res_go["go_condition_met"] is True
    assert "GO" in res_go["verdict"]
    assert res_go["aligned_strict_successes"] == 2
    assert res_go["oblique_failures"] == 2


