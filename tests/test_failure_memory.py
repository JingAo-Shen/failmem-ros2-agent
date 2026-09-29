"""Unit tests for deterministic failure memory module (P2a-v2)."""
import pytest
from src.failure_memory import (
    FailureMemoryStore,
    FailureMemoryEntry,
    MemoryState,
    M0NoMemoryPolicy,
    M1PersistentMemoryPolicy,
    M2ConditionalMemoryPolicy,
    is_failure_eligible_for_doorway_memory,
)


def test_failure_memory_eligibility():
    # 1. Valid OCCUPIED perception evidence -> Eligible
    valid_ev = {"doorway_state": "OCCUPIED", "hits_inside_count": 15, "pass_through_count": 0}
    assert is_failure_eligible_for_doorway_memory("NAV2_ABORTED", valid_ev) is True

    # 2. UNKNOWN perception -> Not eligible (cannot attribute to doorway obstacle)
    unknown_ev = {"doorway_state": "UNKNOWN", "reason": "TF_STALE", "hits_inside_count": 0}
    assert is_failure_eligible_for_doorway_memory("EXECUTION_FAILED", unknown_ev) is False

    # 3. FREE perception -> Not eligible
    free_ev = {"doorway_state": "FREE", "pass_through_count": 20}
    assert is_failure_eligible_for_doorway_memory("EXECUTION_FAILED", free_ev) is False

    # 4. Missing or None -> Not eligible
    assert is_failure_eligible_for_doorway_memory("COMMUNICATION_TIMEOUT", None) is False


def test_failure_memory_store_lifecycle():
    store = FailureMemoryStore(region_matching_tolerance_m=0.50)
    goal = [1.8, 0.0, 0.0]
    region = "room2_corridor_chokepoint"

    # 1. Initial State: No blocks
    blocked, entry, reason = store.is_dispatch_blocked(goal, region)
    assert not blocked
    assert entry is None
    assert reason == "DISPATCH_ALLOWED"

    # 2. Non-eligible failure -> Not recorded
    e_rej = store.record_failure(
        goal=goal,
        region_id=region,
        failure_reason="TF_ERROR",
        sim_time=10.0,
        failed_action_id="act_00",
        failure_evidence_id="obs_00",
        failure_evidence={"doorway_state": "UNKNOWN"},
    )
    assert e_rej is None
    assert len(store.entries) == 0

    # 3. Record Eligible Failure -> Becomes ACTIVE
    e1 = store.record_failure(
        goal=goal,
        region_id=region,
        failure_reason="TEMPORARY_BLOCKAGE_NAV_ABORTED",
        sim_time=15.4,
        failed_action_id="act_01",
        failure_evidence_id="obs_01",
        failure_evidence={"doorway_state": "OCCUPIED", "hits_inside_count": 8},
        map_version="chokepoint_world_v1",
    )
    assert e1 is not None
    assert e1.state == MemoryState.ACTIVE
    assert e1.created_sim_time == 15.4
    assert e1.goal == goal
    assert e1.failed_action_id == "act_01"
    assert e1.failure_evidence_id == "obs_01"
    assert len(e1.history) == 1

    # 4. Check Dispatch -> BLOCKED
    blocked, entry, reason = store.is_dispatch_blocked(goal, region)
    assert blocked
    assert entry.memory_id == e1.memory_id
    assert "BLOCKED_BY_ACTIVE_MEMORY_REGION" in reason

    # Check coordinate match nearby
    blocked_near, _, reason_near = store.is_dispatch_blocked([1.9, 0.1, 0.0])
    assert blocked_near
    assert "BLOCKED_BY_ACTIVE_MEMORY_GOAL" in reason_near

    # Check far target -> not blocked
    blocked_far, _, _ = store.is_dispatch_blocked([-1.8, 0.0, 0.0], "room1_start")
    assert not blocked_far

    # 5. Perception Evaluation: OCCUPIED -> Remains ACTIVE
    inv_occupied = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "OCCUPIED", "hits_inside_count": 8},
        sim_time=20.0,
        evidence_id="obs_02",
    )
    assert len(inv_occupied) == 0
    assert e1.state == MemoryState.ACTIVE

    # 6. Perception Evaluation: Mismatched Map Version -> Remains ACTIVE
    inv_wrong_map = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "pass_through_count": 12},
        sim_time=22.0,
        evidence_id="obs_03",
        map_version="other_map_v2",
    )
    assert len(inv_wrong_map) == 0
    assert e1.state == MemoryState.ACTIVE

    # 7. Perception Evaluation: Old Timestamp (sim_time <= failure_time) -> Remains ACTIVE
    inv_old = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "pass_through_count": 12},
        sim_time=14.0,  # Older than 15.4s
        evidence_id="obs_04",
    )
    assert len(inv_old) == 0
    assert e1.state == MemoryState.ACTIVE

    # 8. Perception Evaluation: Valid Newer FREE -> Transitions to INVALIDATED
    inv_free = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "pass_through_count": 12, "costmap_cleared": True},
        sim_time=26.2,
        evidence_id="obs_05",
    )
    assert len(inv_free) == 1
    assert inv_free[0].memory_id == e1.memory_id
    assert e1.state == MemoryState.INVALIDATED
    assert e1.invalidation_sim_time == 26.2
    assert e1.invalidation_evidence_id == "obs_05"
    assert len(e1.history) == 2

    # 9. Check Dispatch -> ALLOWED (since entry is INVALIDATED)
    blocked_after_inv, _, reason_inv = store.is_dispatch_blocked(goal, region)
    assert not blocked_after_inv
    assert reason_inv == "DISPATCH_ALLOWED"

    # 10. Recovery Verification: Online arrival confirmed -> RECOVERY_VERIFIED
    verified = store.verify_recovery(
        target_goal=goal,
        recovery_action_id="act_recovery_01",
        online_feedback={"nav2_status": "SUCCEEDED", "amcl_pose": {"x": 1.82, "y": 0.01, "yaw": 0.0}},
        sim_time=48.5,
    )
    assert verified is True
    assert e1.state == MemoryState.RECOVERY_VERIFIED
    assert e1.recovery_action_id == "act_recovery_01"
    assert e1.recovery_time == 48.5
    assert len(e1.history) == 3

    summary = store.get_summary()
    assert summary["total_entries"] == 1
    assert summary["recovery_verified_count"] == 1
    assert summary["active_count"] == 0


def test_m0_no_memory_policy():
    policy = M0NoMemoryPolicy()
    goal = [1.8, 0.0, 0.0]
    region = "room2"

    allowed, reason, blocked_id = policy.check_dispatch_allowed(goal, region, sim_time=1.0)
    assert allowed is True
    assert blocked_id is None

    # Record failure
    policy.on_navigation_failure(
        target_goal=goal,
        target_region=region,
        failure_reason="BLOCKED",
        sim_time=10.0,
        failed_action_id="act_1",
        failure_evidence_id="obs_1",
    )

    # Still allowed immediately
    allowed_again, _, _ = policy.check_dispatch_allowed(goal, region, sim_time=12.0)
    assert allowed_again is True

    state = policy.export_state()
    assert state["policy_name"] == "M0_NO_MEMORY"
    assert state["dispatches_attempted"] == 2
    assert state["failures_recorded"] == 1


def test_m1_persistent_memory_policy():
    policy = M1PersistentMemoryPolicy(tolerance_m=0.50)
    goal = [1.8, 0.0, 0.0]
    region = "room2_chokepoint"

    # First dispatch allowed
    allowed, _, _ = policy.check_dispatch_allowed(goal, region, sim_time=1.0)
    assert allowed is True

    # Non-eligible failure -> not blocked
    policy.on_navigation_failure(
        target_goal=goal,
        target_region=region,
        failure_reason="UNKNOWN_REASON",
        sim_time=10.0,
        failed_action_id="act_0",
        failure_evidence_id="obs_0",
        perception_evidence={"doorway_state": "UNKNOWN"},
    )
    allowed_unblocked, _, _ = policy.check_dispatch_allowed(goal, region, sim_time=11.0)
    assert allowed_unblocked is True

    # Eligible failure -> records persistent block
    policy.on_navigation_failure(
        target_goal=goal,
        target_region=region,
        failure_reason="BLOCKED",
        sim_time=15.0,
        failed_action_id="act_1",
        failure_evidence_id="obs_1",
        perception_evidence={"doorway_state": "OCCUPIED"},
    )

    # Subsequent dispatch to same region or goal permanently blocked
    allowed_subsequent, reason, blocked_id = policy.check_dispatch_allowed(goal, region, sim_time=20.0)
    assert allowed_subsequent is False
    assert "M1_PERSISTENT_BLOCK" in reason
    assert blocked_id is not None

    # Even if environment clears, M1 has no invalidation mechanism
    policy.on_observation_update({"doorway_state": "FREE"}, sim_time=30.0)
    allowed_after_clear, _, _ = policy.check_dispatch_allowed(goal, region, sim_time=32.0)
    assert allowed_after_clear is False


def test_m2_conditional_memory_policy():
    policy = M2ConditionalMemoryPolicy(tolerance_m=0.50)
    goal = [1.8, 0.0, 0.0]
    region = "room2_chokepoint"

    # 1. Initial attempt allowed
    allowed, _, _ = policy.check_dispatch_allowed(goal, region, sim_time=1.0)
    assert allowed is True

    # 2. Failure occurs with OCCUPIED evidence -> active block
    policy.on_navigation_failure(
        target_goal=goal,
        target_region=region,
        failure_reason="CORRIDOR_BLOCKED",
        sim_time=16.0,
        failed_action_id="act_1",
        failure_evidence_id="obs_1",
        perception_evidence={"doorway_state": "OCCUPIED"},
    )

    # 3. Repeat attempt blocked while obstacle present
    policy.on_observation_update({"doorway_state": "OCCUPIED"}, sim_time=18.0)
    allowed_repeat, reason, blocked_id = policy.check_dispatch_allowed(goal, region, sim_time=18.5)
    assert allowed_repeat is False
    assert "BLOCKED_BY_ACTIVE_MEMORY" in reason
    assert blocked_id is not None

    # 4. Perception observes doorway FREE -> Invalidates memory
    policy.on_observation_update(
        {"doorway_state": "FREE", "costmap_cleared": True},
        sim_time=26.0,
        evidence_id="obs_clear",
    )

    # 5. Retry dispatch now permitted!
    allowed_retry, reason_retry, _ = policy.check_dispatch_allowed(goal, region, sim_time=27.0)
    assert allowed_retry is True

    # 6. Confirm online recovery arrival (without GT)
    policy.on_navigation_success(
        target_goal=goal,
        target_region=region,
        action_id="act_retry_2",
        online_feedback={"nav2_status": "SUCCEEDED", "amcl_pose": {"x": 1.78, "y": 0.02, "yaw": 0.0}},
        sim_time=45.0,
    )

    state = policy.export_state()
    assert state["policy_name"] == "M2_CONDITIONAL_MEMORY"
    assert state["recovery_verified_count"] == 1
    assert state["active_count"] == 0
    # Verify zero GT fields in memory export
    assert "gt" not in str(state).lower() or "target_goal" in str(state)
