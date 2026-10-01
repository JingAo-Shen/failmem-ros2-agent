"""Unit tests for Hypothesis H1 limited feasibility check and evaluation logic."""

import json
from pathlib import Path
import pytest

from scripts.verify_h1_feasibility import (
    EXPECTED_H1_RUNS,
    evaluate_h1_go_nogo,
    parse_and_derive_h1_evidence,
)


@pytest.fixture
def mock_h1_runs():
    """Create a standard mock dataset matching the 4 physical runs."""
    return [
        {
            "run_name": "H1_aligned_run1",
            "profile_id": "act_aligned",
            "target_goal": [1.5, 1.2, 0.0],
            "timeout_sec": 15.0,
            "doorway_state_before_action": "FREE",
            "hits_inside_before_action": 0,
            "pass_through_count": 23,
            "terminal_status_name": "SUCCEEDED",
            "terminal_status_code": 4,
            "execution_outcome": "BUDGET_SUCCESS",
            "nav2_action_succeeded": True,
            "physical_arrival_verified": False,  # failed halt stability
            "timing_breakdown": {
                "total_step_sim_time_sec": 18.8,
                "estimated_nav2_navigation_duration_sec": 13.4,
                "estimated_passive_settling_sim_time_sec": 3.0,
                "stability_window_sim_time_sec": 2.4,
            },
        },
        {
            "run_name": "H1_aligned_run2",
            "profile_id": "act_aligned",
            "target_goal": [1.5, 1.2, 0.0],
            "timeout_sec": 15.0,
            "doorway_state_before_action": "FREE",
            "hits_inside_before_action": 0,
            "pass_through_count": 22,
            "terminal_status_name": "SUCCEEDED",
            "terminal_status_code": 4,
            "execution_outcome": "BUDGET_SUCCESS",
            "nav2_action_succeeded": True,
            "physical_arrival_verified": True,
            "timing_breakdown": {
                "total_step_sim_time_sec": 18.8,
                "estimated_nav2_navigation_duration_sec": 13.4,
                "estimated_passive_settling_sim_time_sec": 3.0,
                "stability_window_sim_time_sec": 2.4,
            },
        },
        {
            "run_name": "H1_oblique_run1",
            "profile_id": "act_oblique",
            "target_goal": [0.5, 0.88, 0.0],
            "timeout_sec": 15.0,
            "doorway_state_before_action": "FREE",
            "hits_inside_before_action": 0,
            "pass_through_count": 23,
            "terminal_status_name": "SUCCEEDED",
            "terminal_status_code": 4,
            "execution_outcome": "BUDGET_SUCCESS",
            "nav2_action_succeeded": True,
            "physical_arrival_verified": True,
            "timing_breakdown": {
                "total_step_sim_time_sec": 16.4,
                "estimated_nav2_navigation_duration_sec": 11.1,
                "estimated_passive_settling_sim_time_sec": 3.0,
                "stability_window_sim_time_sec": 2.3,
            },
        },
        {
            "run_name": "H1_oblique_run2",
            "profile_id": "act_oblique",
            "target_goal": [0.5, 0.88, 0.0],
            "timeout_sec": 15.0,
            "doorway_state_before_action": "FREE",
            "hits_inside_before_action": 0,
            "pass_through_count": 22,
            "terminal_status_name": "SUCCEEDED",
            "terminal_status_code": 4,
            "execution_outcome": "BUDGET_SUCCESS",
            "nav2_action_succeeded": True,
            "physical_arrival_verified": True,
            "timing_breakdown": {
                "total_step_sim_time_sec": 16.3,
                "estimated_nav2_navigation_duration_sec": 11.0,
                "estimated_passive_settling_sim_time_sec": 3.0,
                "stability_window_sim_time_sec": 2.3,
            },
        },
    ]


def test_evaluate_h1_actual_data_nogo(mock_h1_runs):
    """Test evaluate_h1_go_nogo on the actual 4-run result profile."""
    res = evaluate_h1_go_nogo(mock_h1_runs)
    assert res["go_condition_met"] is False
    assert "NO-GO" in res["verdict"]
    assert res["nav2_succeeded_count"] == 4
    assert res["strict_physical_arrival_count"] == 3
    assert res["aligned_strict_successes"] == 1  # run1 failed halt stability
    assert res["oblique_nav2_failures"] == 0    # both oblique succeeded in Nav2
    assert "本次候选场景未建立预期的动作可执行性差异" in res["unified_conclusion"]
    assert res["preconditions_verified"] is True


def test_evaluate_h1_invalid_run_identities(mock_h1_runs):
    """Test evaluate_h1_go_nogo rejects missing or extra runs."""
    # Missing 1 run
    res_missing = evaluate_h1_go_nogo(mock_h1_runs[:3])
    assert res_missing["go_condition_met"] is False
    assert "Invalid Run Identity" in res_missing["verdict"]

    # Wrong run name
    tampered_runs = [dict(r) for r in mock_h1_runs]
    tampered_runs[0]["run_name"] = "H1_unexpected_run"
    res_tampered = evaluate_h1_go_nogo(tampered_runs)
    assert res_tampered["go_condition_met"] is False
    assert "Invalid Run Identity" in res_tampered["verdict"]


def test_evaluate_h1_precondition_not_free(mock_h1_runs):
    """Test evaluate_h1_go_nogo fails when doorway is not verified FREE."""
    tampered = [dict(r) for r in mock_h1_runs]
    tampered[0]["hits_inside_before_action"] = 2  # laser hits detected
    res = evaluate_h1_go_nogo(tampered)
    assert res["go_condition_met"] is False
    assert res["preconditions_verified"] is False
    assert len(res["precondition_failures"]) == 1


def test_evaluate_h1_oblique_succeeded_arrival_failed_does_not_satisfy_abort(mock_h1_runs):
    """Test that an oblique run returning Nav2 SUCCEEDED with arrival stability failure is NOT counted as Nav2 abort."""
    tampered = [dict(r) for r in mock_h1_runs]
    # Set aligned runs to pass strictly
    tampered[0]["physical_arrival_verified"] = True
    # Oblique run returns Nav2 SUCCEEDED, but fails physical arrival
    tampered[2]["physical_arrival_verified"] = False
    tampered[2]["terminal_status_name"] = "SUCCEEDED"
    tampered[2]["terminal_status_code"] = 4
    tampered[2]["nav2_action_succeeded"] = True

    res = evaluate_h1_go_nogo(tampered)
    assert res["go_condition_met"] is False
    assert res["oblique_nav2_failures"] == 0  # Nav2 did not abort!


def test_evaluate_h1_ideal_go_case(mock_h1_runs):
    """Test that Go condition is met when aligned succeeds 2/2 and oblique aborts in Nav2 2/2."""
    ideal = [dict(r) for r in mock_h1_runs]
    # 2/2 aligned strict success
    ideal[0]["physical_arrival_verified"] = True
    # 2/2 oblique Nav2 abort
    ideal[2]["terminal_status_name"] = "ABORTED"
    ideal[2]["terminal_status_code"] = 6
    ideal[2]["nav2_action_succeeded"] = False
    ideal[2]["physical_arrival_verified"] = False

    ideal[3]["terminal_status_name"] = "ABORTED"
    ideal[3]["terminal_status_code"] = 6
    ideal[3]["nav2_action_succeeded"] = False
    ideal[3]["physical_arrival_verified"] = False

    res = evaluate_h1_go_nogo(ideal)
    assert res["go_condition_met"] is True
    assert "GO" in res["verdict"]
    assert res["aligned_strict_successes"] == 2
    assert res["oblique_nav2_failures"] == 2


def test_parse_and_derive_h1_evidence_from_disk(tmp_path: Path):
    """Test offline parser against existing physical evidence directory."""
    evidence_dir = Path("reports/evidence/p2d_h1_feasibility")
    if not evidence_dir.exists():
        pytest.skip("Evidence directory does not exist in workspace.")

    derived_dir = tmp_path / "derived"
    derived_data = parse_and_derive_h1_evidence(evidence_dir, derived_dir)

    assert derived_dir.joinpath("h1_feasibility_parsed.json").exists()
    assert len(derived_data["runs"]) == 4
    assert derived_data["evaluation_summary"]["go_condition_met"] is False
    for r in derived_data["runs"]:
        tb = r["timing_breakdown"]
        assert "estimated_nav2_navigation_duration_sec" in tb
        assert "estimated_passive_settling_sim_time_sec" in tb
        assert "assumptions_note" in tb
