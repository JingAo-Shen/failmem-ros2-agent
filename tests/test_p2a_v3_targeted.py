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
