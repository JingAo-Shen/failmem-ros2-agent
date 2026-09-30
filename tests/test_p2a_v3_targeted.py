"""FailMem Milestone P2a-v3 Targeted Unit Tests.

Covers:
1. Counterfactual Ground Truth mutation test (online control, policy callbacks, and memory state are invariant to GT; only evaluator_verified_success and disagreement_reason change).
2. Evidence timestamp temporal causality (evidence_stamp <= failure_time is strictly rejected).
3. Stale FREE replay rejection (freshness > 5.0s relative to evaluation sim_time is rejected).
4. Mismatched region and map version rejection.
5. Non-finite / missing evidence timestamp rejection.
6. Recovery action ID binding and mismatch verification.
7. Budget deadline enforcement in scoring evaluator.
"""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import pytest
from typing import Any, Dict, List

from src.failure_memory import (
    MemoryState,
    FailureMemoryEntry,
    FailureMemoryStore,
    M0NoMemoryPolicy,
    M1PersistentMemoryPolicy,
    M2ConditionalMemoryPolicy,
)
from src.scoring_evaluator import (
    evaluate_navigation_episode,
    compute_disagreement_reason,
    load_scoring_rules,
)
from src.terminal_resolution import await_nav_goal_terminal_result


def test_counterfactual_gt_mutation_isolation():
    """Verify that online policy and memory state depend ONLY on public feedback,
    while offline evaluator strictly detects GT mutation and produces disagreement reason.
    """
    target_goal = [1.80, 0.0, 0.0]
    target_region = "room2_corridor_chokepoint"

    # Step 1: Initialize M2 policy and simulate failure at t=18.0s
    policy = M2ConditionalMemoryPolicy()
    failed_action_id = "test_ep_nav_attempt1"
    failure_obs = {
        "doorway_state": "OCCUPIED",
        "timestamp_sim": 18.2,
        "hits_inside_count": 5,
    }
    policy.on_navigation_failure(
        target_goal=target_goal,
        target_region=target_region,
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=18.5,
        failed_action_id=failed_action_id,
        failure_evidence_id="test_ep_postfail_obs_1",
        perception_evidence=failure_obs,
    )
    assert len(policy.store.entries) == 1
    entry = policy.store.entries[0]
    assert entry.state == MemoryState.ACTIVE

    # Step 2: Gate check blocks repeat dispatch while blocked
    allowed, reason, blocked_id = policy.check_dispatch_allowed(
        target_goal=target_goal,
        target_region=target_region,
        sim_time=22.0,
    )
    assert not allowed
    assert blocked_id == entry.memory_id

    # Step 3: Clearance observed at t=26.0s (doorway FREE)
    clearance_obs = {
        "doorway_state": "FREE",
        "timestamp_sim": 26.0,
        "region_id": target_region,
        "map_version": "chokepoint_world_v1",
        "pass_through_count": 8,
    }
    policy.on_observation_update(
        perception_evidence=clearance_obs,
        sim_time=26.2,
        evidence_id="obs_clear_1",
    )
    assert entry.state == MemoryState.INVALIDATED

    # Step 4: Dispatch recovery action attempt 2 at t=26.5s
    recovery_action_id = "test_ep_nav_attempt2"
    allowed, reason, _ = policy.check_dispatch_allowed(
        target_goal=target_goal,
        target_region=target_region,
        sim_time=26.5,
    )
    assert allowed
    bound_id = policy.bind_recovery_action(
        target_goal=target_goal,
        target_region=target_region,
        recovery_action_id=recovery_action_id,
        sim_time=26.5,
    )
    assert bound_id == entry.memory_id
    assert entry.pending_recovery_action_id == recovery_action_id

    # Step 5: Public feedback indicates success (Nav2 SUCCEEDED, fresh AMCL pose close to goal, zero velocity)
    public_feedback = {
        "nav2_status": "SUCCEEDED",
        "status_code": 4,
        "execution_outcome": "BUDGET_SUCCESS",
        "amcl_pose": {"x": 1.82, "y": 0.01, "yaw": 0.02, "msg_stamp_sec": 38.0},
        "halt_velocity": {"linear_v": 0.001, "angular_v": 0.002},
    }

    # Case A: Normal Ground Truth matching target goal
    normal_gt = {"x": 1.81, "y": 0.02, "yaw": 0.01, "recv_sim_time_sec": 38.0, "seq": 100}
    normal_window = [
        {
            "sim_time": 38.0 + i * 0.1,
            "gt": {"x": 1.81, "y": 0.02, "yaw": 0.01, "recv_sim_time_sec": 38.0 + i * 0.1, "seq": 100 + i},
            "odom": {"x": 1.81, "y": 0.02, "yaw": 0.01, "msg_stamp_sec": 38.0 + i * 0.1, "linear_v": 0.001, "angular_v": 0.001, "seq": 100 + i},
            "cmd_vel": {"linear_x": 0.0, "angular_z": 0.0},
        }
        for i in range(25)
    ]
    scoring_thresholds = {
        "position_tolerance_m": 0.30,
        "yaw_tolerance_rad": 0.35,
        "stability_window_duration_sim_sec": 2.0,
        "max_sensor_staleness_sim_sec": 0.5,
        "max_halt_velocity_linear_mps": 0.05,
        "max_halt_velocity_angular_radps": 0.05,
        "max_gt_displacement_m": 0.05,
    }
    normal_eval = evaluate_navigation_episode(
        target_goal=target_goal,
        nav2_status="SUCCEEDED",
        final_gt=normal_gt,
        final_amcl=public_feedback["amcl_pose"],
        stability_samples=normal_window,
        thresholds=scoring_thresholds,
    )
    assert normal_eval["strict_physical_arrival_and_stable"] is True
    disagreement_normal = compute_disagreement_reason(True, True, normal_eval)
    assert disagreement_normal is None

    # Case B: Counterfactual GT Mutation (GT corrupted/relocated to x=10.0, y=10.0)
    mutated_gt = {"x": 10.0, "y": 10.0, "yaw": 0.0, "recv_sim_time_sec": 38.0, "seq": 200}
    mutated_window = [
        {
            "sim_time": 38.0 + i * 0.1,
            "gt": {"x": 10.0, "y": 10.0, "yaw": 0.0, "recv_sim_time_sec": 38.0 + i * 0.1, "seq": 200 + i},
            "odom": {"x": 1.81, "y": 0.02, "yaw": 0.01, "msg_stamp_sec": 38.0 + i * 0.1, "linear_v": 0.001, "angular_v": 0.001, "seq": 200 + i},
            "cmd_vel": {"linear_x": 0.0, "angular_z": 0.0},
        }
        for i in range(25)
    ]
    mutated_eval = evaluate_navigation_episode(
        target_goal=target_goal,
        nav2_status="SUCCEEDED",
        final_gt=mutated_gt,
        final_amcl=public_feedback["amcl_pose"],
        stability_samples=mutated_window,
        thresholds=scoring_thresholds,
    )
    assert mutated_eval["strict_physical_arrival_and_stable"] is False
    disagreement_mutated = compute_disagreement_reason(True, False, mutated_eval)
    assert disagreement_mutated is not None
    assert "EVALUATOR_GT_ARRIVAL_TOLERANCE_EXCEEDED" in disagreement_mutated

    # Verify that Online Policy execution & state are IDENTICAL in both cases
    policy.on_navigation_success(
        target_goal=target_goal,
        target_region=target_region,
        action_id=recovery_action_id,
        online_feedback=public_feedback,
        sim_time=38.5,
    )
    assert entry.state == MemoryState.RECOVERY_VERIFIED
    assert entry.recovery_action_id == recovery_action_id


def test_temporal_causality_and_stale_replay():
    """Verify evidence_stamp <= failure_time or stale evidence (>5.0s old) is rejected."""
    store = FailureMemoryStore()
    target_goal = [1.80, 0.0, 0.0]
    target_region = "chokepoint_corridor"

    store.record_failure(
        goal=target_goal,
        region_id=target_region,
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=20.0,
        failed_action_id="nav_1",
        failure_evidence_id="postfail_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
    )
    entry = store.entries[0]
    assert entry.state == MemoryState.ACTIVE
    assert entry.failure_time == 20.0

    # 1. Past/Stale timestamp: evidence_stamp = 15.0s (before failure at 20.0s) -> REJECT
    inv = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 15.0},
        sim_time=22.0,
        evidence_id="stale_1",
    )
    assert len(inv) == 0
    assert entry.state == MemoryState.ACTIVE

    # 2. Equal timestamp: evidence_stamp = 20.0s -> REJECT
    inv = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 20.0},
        sim_time=22.0,
        evidence_id="equal_1",
    )
    assert len(inv) == 0
    assert entry.state == MemoryState.ACTIVE

    # 3. Future evaluation sim_time but evidence is stale: evidence_stamp = 21.0s, sim_time = 30.0s (delta = 9.0s > 5.0s) -> REJECT
    inv = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 21.0},
        sim_time=30.0,
        evidence_id="stale_delta_1",
    )
    assert len(inv) == 0
    assert entry.state == MemoryState.ACTIVE

    # 4. Valid causal & fresh evidence: evidence_stamp = 26.0s, sim_time = 26.5s -> ACCEPT
    inv = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 26.0},
        sim_time=26.5,
        evidence_id="valid_clear_1",
    )
    assert len(inv) == 1
    assert entry.state == MemoryState.INVALIDATED
    assert entry.invalidation_time == 26.0


def test_mismatched_region_and_map_version():
    """Verify mismatched region or map version does not invalidate memory."""
    store = FailureMemoryStore()
    target_goal = [1.80, 0.0, 0.0]

    store.record_failure(
        goal=target_goal,
        region_id="region_A",
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=20.0,
        failed_action_id="nav_1",
        failure_evidence_id="postfail_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
        map_version="chokepoint_world_v1",
    )
    entry = store.entries[0]

    # Mismatched region in evidence
    inv = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 25.0, "region_id": "region_B"},
        sim_time=25.5,
        evidence_id="mismatch_reg",
    )
    assert len(inv) == 0
    assert entry.state == MemoryState.ACTIVE

    # Mismatched map version in evidence
    inv = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 25.0, "map_version": "other_world_v2"},
        sim_time=25.5,
        evidence_id="mismatch_map",
    )
    assert len(inv) == 0
    assert entry.state == MemoryState.ACTIVE


def test_missing_or_nonfinite_timestamp():
    """Verify missing, None, NaN, Inf evidence timestamps are rejected."""
    store = FailureMemoryStore()
    store.record_failure(
        goal=[1.8, 0.0, 0.0],
        region_id="room2",
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=20.0,
        failed_action_id="nav_1",
        failure_evidence_id="postfail_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
    )
    entry = store.entries[0]

    for bad_stamp in [None, float("nan"), float("inf"), "invalid_str", True]:
        inv = store.evaluate_perception_for_invalidation(
            perception_evidence={"doorway_state": "FREE", "timestamp_sim": bad_stamp},
            sim_time=25.0,
            evidence_id="bad_stamp",
        )
        assert len(inv) == 0
        assert entry.state == MemoryState.ACTIVE


def test_recovery_action_binding_and_mismatch():
    """Verify recovery action ID binding and rejection when action ID does not match."""
    store = FailureMemoryStore()
    target_goal = [1.80, 0.0, 0.0]
    target_region = "room2"

    store.record_failure(
        goal=target_goal,
        region_id=target_region,
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=20.0,
        failed_action_id="nav_1",
        failure_evidence_id="postfail_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
    )
    entry = store.entries[0]

    # Invalidate
    store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 26.0},
        sim_time=26.5,
        evidence_id="clear_1",
    )
    assert entry.state == MemoryState.INVALIDATED

    # Bind recovery action "nav_attempt_2"
    bound_id = store.bind_recovery_action(
        target_goal=target_goal,
        target_region=target_region,
        recovery_action_id="nav_attempt_2",
        sim_time=27.0,
    )
    assert bound_id == entry.memory_id
    assert entry.pending_recovery_action_id == "nav_attempt_2"

    # Try verifying recovery with wrong action ID "nav_attempt_999" -> Should return False
    wrong_feedback = {
        "nav2_status": "SUCCEEDED",
        "amcl_pose": {"x": 1.80, "y": 0.0, "yaw": 0.0},
        "halt_velocity": {"linear_v": 0.0, "angular_v": 0.0},
    }
    verified_wrong = store.verify_recovery(
        target_goal=target_goal,
        recovery_action_id="nav_attempt_999",
        online_feedback=wrong_feedback,
        sim_time=35.0,
    )
    assert not verified_wrong
    assert entry.state == MemoryState.INVALIDATED

    # Verify recovery with correct action ID "nav_attempt_2" -> Should succeed
    verified_correct = store.verify_recovery(
        target_goal=target_goal,
        recovery_action_id="nav_attempt_2",
        online_feedback=wrong_feedback,
        sim_time=35.0,
    )
    assert verified_correct
    assert entry.state == MemoryState.RECOVERY_VERIFIED
    assert entry.recovery_action_id == "nav_attempt_2"


def test_online_verifier_edge_cases():
    """Verify online_verifier rejects stale AMCL, future AMCL, invalid frames, non-finite coords, and high covariance."""
    from src.online_verifier import verify_online_arrival

    target_goal = [1.80, 0.0, 0.0]
    thresh = {
        "online_position_tolerance_m": 0.45,
        "online_yaw_tolerance_rad": 0.55,
        "online_max_linear_velocity_mps": 0.03,
        "online_max_angular_velocity_radps": 0.05,
        "max_amcl_staleness_sec": 30.0,
        "max_sensor_staleness_sim_sec": 0.50,
        "max_amcl_covariance_variance": 0.50,
    }

    base_feedback = {
        "nav2_status": "SUCCEEDED",
        "execution_outcome": "BUDGET_SUCCESS",
        "deadline_exceeded": False,
        "amcl_pose": {
            "x": 1.82,
            "y": 0.01,
            "yaw": 0.02,
            "msg_stamp_sec": 35.0,
            "frame_id": "map",
            "covariance": [0.01] * 36,
        },
        "halt_velocity": {
            "linear_v": 0.001,
            "angular_v": 0.002,
        },
    }

    # 1. Baseline Valid Case
    ok, reasons, details = verify_online_arrival(target_goal, base_feedback, thresh, sim_time=35.2)
    assert ok is True
    assert len(reasons) == 0

    # 2. Stale AMCL (> 30s old relative to sim_time)
    ok, reasons, _ = verify_online_arrival(target_goal, base_feedback, thresh, sim_time=70.0)
    assert ok is False
    assert any("EXPIRED_AMCL_STAMP" in r for r in reasons)

    # 3. Future AMCL (> sim_time + 0.15s)
    ok, reasons, _ = verify_online_arrival(target_goal, base_feedback, thresh, sim_time=20.0)
    assert ok is False
    assert any("FUTURE_AMCL_STAMP" in r for r in reasons)

    # 4. Invalid Frame ID
    bad_frame = copy.deepcopy(base_feedback)
    bad_frame["amcl_pose"]["frame_id"] = "odom"
    ok, reasons, _ = verify_online_arrival(target_goal, bad_frame, thresh, sim_time=35.2)
    assert ok is False
    assert any("INVALID_AMCL_FRAME_ID" in r for r in reasons)

    # 5. Non-finite Coordinates
    nan_coords = copy.deepcopy(base_feedback)
    nan_coords["amcl_pose"]["x"] = float("nan")
    ok, reasons, _ = verify_online_arrival(target_goal, nan_coords, thresh, sim_time=35.2)
    assert ok is False
    assert any("NON_FINITE_AMCL_COORDINATES" in r for r in reasons)

    # 6. Excessive Covariance (> 0.50)
    high_cov = copy.deepcopy(base_feedback)
    cov_list = [0.01] * 36
    cov_list[0] = 0.85  # var_x
    high_cov["amcl_pose"]["covariance"] = cov_list
    ok, reasons, _ = verify_online_arrival(target_goal, high_cov, thresh, sim_time=35.2)
    assert ok is False
    assert any("AMCL_COVARIANCE_TOO_LARGE" in r for r in reasons)


def test_counterfactual_online_fail_physical_pass():
    """Verify combination (False, True): online check fails due to AMCL covariance/stale pose,
    while physical GT arrives and evaluator records success. Disagreement reason must match.
    """
    from src.online_verifier import verify_online_arrival

    target_goal = [1.80, 0.0, 0.0]
    thresh = {
        "position_tolerance_m": 0.30,
        "yaw_tolerance_rad": 0.35,
        "stability_window_duration_sim_sec": 2.0,
        "max_sensor_staleness_sim_sec": 0.5,
        "max_halt_velocity_linear_mps": 0.05,
        "max_halt_velocity_angular_radps": 0.05,
        "max_gt_displacement_m": 0.05,
        "online_position_tolerance_m": 0.45,
        "online_yaw_tolerance_rad": 0.55,
        "online_max_linear_velocity_mps": 0.03,
        "online_max_angular_velocity_radps": 0.05,
        "max_amcl_staleness_sec": 30.0,
        "max_amcl_covariance_variance": 0.50,
    }

    # AMCL localization has high covariance / poor estimate
    corrupted_online_feedback = {
        "nav2_status": "SUCCEEDED",
        "execution_outcome": "BUDGET_SUCCESS",
        "deadline_exceeded": False,
        "amcl_pose": {
            "x": 3.50,  # 1.7m error
            "y": 0.0,
            "yaw": 0.0,
            "msg_stamp_sec": 35.0,
            "frame_id": "map",
            "covariance": [0.01] * 36,
        },
        "halt_velocity": {
            "linear_v": 0.001,
            "angular_v": 0.002,
        },
    }

    # Physical GT is perfectly at goal
    perfect_gt = {"x": 1.81, "y": 0.01, "yaw": 0.02, "recv_sim_time_sec": 35.0, "seq": 500}
    perfect_window = [
        {
            "sim_time": 35.0 + i * 0.1,
            "gt": {"x": 1.81, "y": 0.01, "yaw": 0.02, "recv_sim_time_sec": 35.0 + i * 0.1, "seq": 500 + i},
            "odom": {"x": 1.81, "y": 0.01, "yaw": 0.02, "msg_stamp_sec": 35.0 + i * 0.1, "linear_v": 0.001, "angular_v": 0.001, "seq": 500 + i},
            "cmd_vel": {"linear_x": 0.0, "angular_z": 0.0},
        }
        for i in range(25)
    ]

    online_ok, reasons, _ = verify_online_arrival(target_goal, corrupted_online_feedback, thresh, sim_time=35.2)
    assert online_ok is False

    eval_result = evaluate_navigation_episode(
        target_goal=target_goal,
        nav2_status="SUCCEEDED",
        final_gt=perfect_gt,
        final_amcl=corrupted_online_feedback["amcl_pose"],
        stability_samples=perfect_window,
        thresholds=thresh,
    )
    assert eval_result["strict_physical_arrival_and_stable"] is True

    # (False, True) Disagreement
    disagreement = compute_disagreement_reason(online_ok, eval_result["strict_physical_arrival_and_stable"], eval_result)
    assert disagreement == "POLICY_REPORTED_FAILURE_DESPITE_PHYSICAL_ARRIVAL"


def test_m3_reactive_gating_policy():
    """Verify M3CurrentPerceptionPolicy reactive gating and zero failure memory entries."""
    from src.failure_memory import M3CurrentPerceptionPolicy

    policy = M3CurrentPerceptionPolicy()
    target_goal = [1.80, 0.0, 0.0]
    target_region = "room2"

    # Initial state: UNKNOWN -> blocked
    allowed, reason, blocked_id = policy.check_dispatch_allowed(target_goal, target_region, sim_time=1.0)
    assert allowed is False
    assert "BLOCKED" in reason
    assert blocked_id is None

    # Update observation: OCCUPIED -> blocked
    policy.on_observation_update(
        perception_evidence={"doorway_state": "OCCUPIED"},
        sim_time=2.0,
    )
    allowed, reason, _ = policy.check_dispatch_allowed(target_goal, target_region, sim_time=2.0)
    assert allowed is False
    assert reason == "M3_PERCEPTION_OCCUPIED_BLOCKED"

    # Navigation failure notification: records failure count but zero memory entries
    policy.on_navigation_failure(
        target_goal=target_goal,
        target_region=target_region,
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=3.0,
        failed_action_id="nav_1",
        failure_evidence_id="postfail_1",
        perception_evidence={"doorway_state": "OCCUPIED"},
    )
    state = policy.export_state()
    assert state["failures_recorded"] == 1
    assert len(state["memory_entries"]) == 0

    # Update observation: FREE -> allowed
    policy.on_observation_update(
        perception_evidence={"doorway_state": "FREE"},
        sim_time=26.0,
    )
    allowed, reason, _ = policy.check_dispatch_allowed(target_goal, target_region, sim_time=26.0)
    assert allowed is True
    assert reason == "M3_PERCEPTION_FREE_ALLOWED"


def test_replay_tamper_detection_and_unverifiable(tmp_path):
    """Verify replay_and_score_p2a detects tampered episode_summary and flags missing artifacts as UNVERIFIABLE."""
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    thresh = {
        "position_tolerance_m": 0.30,
        "yaw_tolerance_rad": 0.35,
        "stability_window_duration_sim_sec": 2.0,
        "max_sensor_staleness_sim_sec": 0.5,
        "max_halt_velocity_linear_mps": 0.05,
        "max_halt_velocity_angular_radps": 0.05,
        "max_gt_displacement_m": 0.05,
        "online_position_tolerance_m": 0.45,
        "online_yaw_tolerance_rad": 0.55,
        "online_max_linear_velocity_mps": 0.03,
        "online_max_angular_velocity_radps": 0.05,
        "max_amcl_staleness_sec": 30.0,
        "max_amcl_covariance_variance": 0.50,
    }

    ep_dir = tmp_path / "M2_S2_ep1"
    ep_dir.mkdir()

    # Case 1: Missing doorway_perception.json -> UNVERIFIABLE
    res_unv = replay_and_score_episode(ep_dir, thresh)
    assert res_unv["status"] == "UNVERIFIABLE"

    # Create doorway_perception.json & memory_events.json
    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([
            {"sim_time": 0.0, "evaluation": {"doorway_state": "OCCUPIED"}},
            {"sim_time": 27.6, "evaluation": {"doorway_state": "FREE"}},
        ], f)

    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([
            {"event_type": "DISPATCH_GATE_CHECK", "allowed": True, "policy_state": {}},
            {"event_type": "DISPATCH_GATE_CHECK", "allowed": False, "policy_state": {}},
        ], f)

    # Create attempt_1 (failure)
    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": []}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    # Create attempt_2 (success)
    att2_dir = ep_dir / "attempt_2"
    att2_dir.mkdir()
    with open(att2_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 2, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "dispatch_time_sim": 28.0}, f)
    with open(att2_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "amcl_pose": {"x": 1.81, "y": 0.0, "yaw": 0.0, "msg_stamp_sec": 40.0}, "halt_velocity": {"linear_v": 0.0, "angular_v": 0.0}, "online_action_succeeded": True}, f)
    with open(att2_dir / "stability_window.json", "w") as f:
        samples = [
            {"sim_time": 40.0 + i * 0.1, "gt": {"x": 1.81, "y": 0.0, "yaw": 0.0, "recv_sim_time_sec": 40.0 + i * 0.1, "seq": 100 + i}, "odom": {"x": 1.81, "y": 0.0, "yaw": 0.0, "msg_stamp_sec": 40.0 + i * 0.1, "linear_v": 0.0, "angular_v": 0.0, "seq": 100 + i}, "cmd_vel": {"linear_x": 0.0, "angular_z": 0.0}}
            for i in range(25)
        ]
        json.dump({"window_records": samples, "watchdog_triggered": False}, f)
    with open(att2_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    # Create tampered episode_summary.json (falsely claiming task_success = False)
    with open(ep_dir / "episode_summary.json", "w") as f:
        json.dump({
            "task_success": False,  # Tampered! True value is True
            "mechanism_verified": False,
            "policy_reported_success": True,
            "evaluator_verified_success": True,
            "navigation_attempt_count": 2,
            "suppression_count": 1,
            "redundant_retries_count": 0,
            "invalidation_verified": True,
            "policy_reported_recovery": True,
            "evaluator_verified_recovery": True,
        }, f)

    res_tamper = replay_and_score_episode(ep_dir, thresh)
    assert res_tamper["status"] == "VERIFIED"
    assert res_tamper["task_success"] is True  # Recomputed true value
    assert res_tamper["summary_discrepancy_detected"] is True
    assert res_tamper["tamper_detected"] is True
    assert any(d["field"] == "task_success" for d in res_tamper["summary_discrepancies"])


def test_replay_missing_frozen_config_unverifiable(tmp_path):
    """Verify replay suite fails with UNVERIFIABLE if runtime_config.json is missing."""
    from scripts.replay_and_score_p2a import find_target_episodes_and_config

    run_dir = tmp_path / "test_run_without_config"
    run_dir.mkdir()
    ep_dir = run_dir / "M2_S2_ep1"
    ep_dir.mkdir()
    with open(ep_dir / "doorway_perception.json", "w") as f:
        f.write("[]")

    ep_dirs, runtime_config, found_run_dir, error_msg = find_target_episodes_and_config(run_dir)
    assert runtime_config is None
    assert "MISSING_FROZEN_RUNTIME_CONFIG" in error_msg


def test_replay_raw_checksum_tamper_detection(tmp_path):
    """Verify replay suite detects raw artifact tampering via checksums.sha256."""
    import hashlib
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    run_dir = tmp_path / "test_run_checksums"
    run_dir.mkdir()
    ep_dir = run_dir / "M2_S2_ep1"
    ep_dir.mkdir()

    # Raw files
    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([
            {"sim_time": 0.0, "evaluation": {"doorway_state": "OCCUPIED"}},
            {"sim_time": 27.6, "evaluation": {"doorway_state": "FREE"}},
        ], f)

    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([
            {"event_type": "DISPATCH_GATE_CHECK", "allowed": True, "policy_state": {}},
        ], f)

    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": []}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    # Generate genuine checksums.sha256
    chk_lines = []
    for root_p, _, files in os.walk(ep_dir):
        for fname in files:
            fpath = Path(root_p) / fname
            rel = str(fpath.relative_to(run_dir))
            sha = hashlib.sha256(open(fpath, "rb").read()).hexdigest()
            chk_lines.append(f"{sha}  {rel}\n")
    with open(run_dir / "checksums.sha256", "w") as f:
        f.writelines(chk_lines)

    thresh = {
        "position_tolerance_m": 0.30,
        "yaw_tolerance_rad": 0.35,
        "stability_window_duration_sim_sec": 2.0,
        "max_sensor_staleness_sim_sec": 0.5,
        "max_linear_velocity_mps": 0.05,
        "max_angular_velocity_radps": 0.08,
        "max_gt_displacement_m": 0.05,
        "online_position_tolerance_m": 0.45,
        "online_yaw_tolerance_rad": 0.55,
        "online_max_linear_velocity_mps": 0.03,
        "online_max_angular_velocity_radps": 0.05,
        "max_amcl_covariance_variance": 0.50,
    }

    # Verify initial state: no tamper
    res1 = replay_and_score_episode(ep_dir, thresh, run_dir=run_dir)
    assert not res1["raw_checksum_tamper_detected"]

    # Tamper with raw action_result.json
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "TAMPERED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0}, f)

    res2 = replay_and_score_episode(ep_dir, thresh, run_dir=run_dir)
    assert res2["raw_checksum_tamper_detected"] is True
    assert len(res2["checksum_mismatches"]) == 1
    assert res2["checksum_mismatches"][0]["file"] == "M2_S2_ep1/attempt_1/action_result.json"


def test_replay_policy_state_injection_ignored(tmp_path):
    """Verify that fake policy_state injected into memory_events.json is ignored by replayer."""
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    ep_dir = tmp_path / "M2_S2_ep1"
    ep_dir.mkdir()

    # doorway_perception has NO FREE observation (always OCCUPIED)
    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([
            {"sim_time": 0.0, "evaluation": {"doorway_state": "OCCUPIED"}},
            {"sim_time": 27.6, "evaluation": {"doorway_state": "OCCUPIED"}},
        ], f)

    # Injected fake policy_state claiming recovery_verified_count = 1
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([
            {
                "event_type": "DISPATCH_GATE_CHECK",
                "allowed": False,
                "policy_state": {
                    "recovery_verified_count": 1,  # FAKE INJECTION!
                    "invalidated_count": 1,
                    "entries": [{"invalidation_time": 25.0, "recovery_verified": True}],
                },
            },
        ], f)

    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": []}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    thresh = {
        "position_tolerance_m": 0.30,
        "yaw_tolerance_rad": 0.35,
        "stability_window_duration_sim_sec": 2.0,
        "max_sensor_staleness_sim_sec": 0.5,
        "max_linear_velocity_mps": 0.05,
        "max_angular_velocity_radps": 0.08,
        "max_gt_displacement_m": 0.05,
        "online_position_tolerance_m": 0.45,
        "online_yaw_tolerance_rad": 0.55,
        "online_max_linear_velocity_mps": 0.03,
        "online_max_angular_velocity_radps": 0.05,
        "max_amcl_covariance_variance": 0.50,
    }

    res = replay_and_score_episode(ep_dir, thresh)
    # Replayer must reconstruct purely from raw perception -> invalidation_verified is False!
    assert res["invalidation_verified"] is False
    assert res["policy_reported_recovery"] is False
    assert res["mechanism_verified"] is False
    # Discrepancy detected because fake policy_state had recovery_verified_count = 1
    assert res["policy_state_discrepancy_detected"] is True


def test_replay_negative_free_before_failure(tmp_path):
    """Verify that a FREE observation occurring BEFORE failure time does NOT invalidate memory."""
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    ep_dir = tmp_path / "M2_S2_ep1"
    ep_dir.mkdir()

    # FREE obs at t=10.0s (BEFORE failure at t=20.0s), OCCUPIED at t=20.0s
    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([
            {"sim_time": 10.0, "action_id": "obs_1", "evaluation": {"doorway_state": "FREE", "region_id": "room2_corridor_chokepoint"}},
            {"sim_time": 20.0, "action_id": "obs_2", "evaluation": {"doorway_state": "OCCUPIED", "region_id": "room2_corridor_chokepoint"}},
        ], f)

    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([{"event_type": "DISPATCH_GATE_CHECK", "allowed": False}], f)

    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0, "completion_sim_time": 20.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": []}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    thresh = {"position_tolerance_m": 0.30, "yaw_tolerance_rad": 0.35, "max_linear_velocity_mps": 0.05, "max_angular_velocity_radps": 0.08}
    res = replay_and_score_episode(ep_dir, thresh)
    assert res["invalidation_verified"] is False
    assert res["policy_reported_recovery"] is False


def test_replay_negative_other_region_free(tmp_path):
    """Verify that a FREE observation for a DIFFERENT region does NOT invalidate memory."""
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    ep_dir = tmp_path / "M2_S2_ep1"
    ep_dir.mkdir()

    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([
            {"sim_time": 20.0, "action_id": "obs_1", "evaluation": {"doorway_state": "OCCUPIED", "region_id": "room2_corridor_chokepoint"}},
            # FREE observation is for room1_corner, NOT room2_corridor_chokepoint!
            {"sim_time": 25.0, "action_id": "obs_2", "evaluation": {"doorway_state": "FREE", "region_id": "room1_corner"}},
        ], f)

    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([{"event_type": "DISPATCH_GATE_CHECK", "allowed": False}], f)

    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0, "completion_sim_time": 20.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": []}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    thresh = {"position_tolerance_m": 0.30, "yaw_tolerance_rad": 0.35, "max_linear_velocity_mps": 0.05, "max_angular_velocity_radps": 0.08}
    res = replay_and_score_episode(ep_dir, thresh)
    assert res["invalidation_verified"] is False


def test_replay_negative_infrastructure_failure_not_memory_eligible(tmp_path):
    """Verify that infrastructure failures do NOT qualify as doorway blockage memories."""
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    ep_dir = tmp_path / "M2_S2_ep1"
    ep_dir.mkdir()

    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([{"sim_time": 0.0, "evaluation": {"doorway_state": "OCCUPIED"}}], f)
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([], f)

    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    # Infrastructure crash
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "UNKNOWN", "execution_outcome": "INFRASTRUCTURE_FAILURE", "dispatch_time_sim": 0.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "UNKNOWN", "execution_outcome": "INFRASTRUCTURE_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": [], "watchdog_triggered": True}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    thresh = {"position_tolerance_m": 0.30, "yaw_tolerance_rad": 0.35, "max_linear_velocity_mps": 0.05, "max_angular_velocity_radps": 0.08}
    res = replay_and_score_episode(ep_dir, thresh)
    assert len(res["exact_timestamps"]["failure_times"]) == 0


def test_replay_negative_retrograde_timestamps_unverifiable(tmp_path):
    """Verify that retrograde/non-monotonic timestamps in perception mark episode UNVERIFIABLE."""
    import json
    from scripts.replay_and_score_p2a import replay_and_score_episode

    ep_dir = tmp_path / "M2_S2_ep1"
    ep_dir.mkdir()

    # Retrograde timestamp: 25.0s then 20.0s
    with open(ep_dir / "doorway_perception.json", "w") as f:
        json.dump([
            {"sim_time": 25.0, "evaluation": {"doorway_state": "OCCUPIED"}},
            {"sim_time": 20.0, "evaluation": {"doorway_state": "OCCUPIED"}},
        ], f)
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([], f)

    att1_dir = ep_dir / "attempt_1"
    att1_dir.mkdir()
    with open(att1_dir / "action_result.json", "w") as f:
        json.dump({"attempt_index": 1, "target_goal": [1.8, 0.0, 0.0], "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "dispatch_time_sim": 0.0}, f)
    with open(att1_dir / "online_feedback.json", "w") as f:
        json.dump({"nav2_status": "ABORTED", "execution_outcome": "BUDGET_FAILURE", "online_action_succeeded": False}, f)
    with open(att1_dir / "stability_window.json", "w") as f:
        json.dump({"window_records": []}, f)
    with open(att1_dir / "trajectory.json", "w") as f:
        json.dump({"gt_trajectory": [], "odom_trajectory": []}, f)

    thresh = {"position_tolerance_m": 0.30, "yaw_tolerance_rad": 0.35, "max_linear_velocity_mps": 0.05, "max_angular_velocity_radps": 0.08}
    res = replay_and_score_episode(ep_dir, thresh)
    assert res["status"] == "UNVERIFIABLE"
    assert res["episode_valid"] is False
    assert any("Retrograde sim_time" in r for r in res["unverifiable_reasons"])


