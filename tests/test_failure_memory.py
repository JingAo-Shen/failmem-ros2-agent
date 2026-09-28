"""Unit tests for deterministic failure memory module (P2a)."""
import pytest
from src.failure_memory import (
    FailureMemoryStore,
    FailureMemoryEntry,
    MemoryState,
    M0NoMemoryPolicy,
    M1PersistentMemoryPolicy,
    M2ConditionalMemoryPolicy,
)


def test_failure_memory_store_lifecycle():
    store = FailureMemoryStore(region_matching_tolerance_m=0.50)
    goal = [1.8, 0.0, 0.0]
    region = "room2_corridor_chokepoint"

    # 1. Initial State: No blocks
    blocked, entry, reason = store.is_dispatch_blocked(goal, region)
    assert not blocked
    assert entry is None
    assert reason == "DISPATCH_ALLOWED"

    # 2. Record Failure -> Becomes ACTIVE
    e1 = store.record_failure(
        target_goal=goal,
        target_region=region,
        failure_reason="TEMPORARY_BLOCKAGE_NAV_ABORTED",
        sim_time=15.4,
    )
    assert e1.state == MemoryState.ACTIVE
    assert e1.created_sim_time == 15.4
    assert e1.target_goal == goal

    # 3. Check Dispatch -> BLOCKED
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

    # 4. Perception Evaluation: OCCUPIED -> Remains ACTIVE
    inv_occupied = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "OCCUPIED", "hits_inside_count": 8},
        sim_time=20.0,
    )
    assert len(inv_occupied) == 0
    assert e1.state == MemoryState.ACTIVE

    # 5. Perception Evaluation: FREE -> Transitions to INVALIDATED
    inv_free = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "pass_through_count": 12, "costmap_cleared": True},
        sim_time=26.2,
    )
    assert len(inv_free) == 1
    assert inv_free[0].memory_id == e1.memory_id
    assert e1.state == MemoryState.INVALIDATED
    assert e1.invalidation_sim_time == 26.2
    assert e1.invalidation_evidence["doorway_state"] == "FREE"

    # 6. Check Dispatch -> ALLOWED (since entry is INVALIDATED)
    blocked_after_inv, _, reason_inv = store.is_dispatch_blocked(goal, region)
    assert not blocked_after_inv
    assert reason_inv == "DISPATCH_ALLOWED"

    # 7. Recovery Verification: Arrival confirmed -> RECOVERY_VERIFIED
    verified = store.verify_recovery(
        target_goal=goal,
        physical_evaluation={"strict_physical_arrival_and_stable": True, "final_geometric_errors": {"gt_position_error_m": 0.12}},
        sim_time=48.5,
    )
    assert verified is True
    assert e1.state == MemoryState.RECOVERY_VERIFIED
    assert e1.verification_sim_time == 48.5

    summary = store.get_summary()
    assert summary["total_entries"] == 1
    assert summary["recovery_verified_count"] == 1
    assert summary["active_count"] == 0


def test_m0_no_memory_policy():
    policy = M0NoMemoryPolicy()
    goal = [1.8, 0.0, 0.0]
    region = "room2"

    allowed, reason = policy.check_dispatch_allowed(goal, region, sim_time=1.0)
    assert allowed is True

    # Record failure
    policy.on_navigation_failure(goal, region, "BLOCKED", sim_time=10.0)

    # Still allowed immediately
    allowed_again, _ = policy.check_dispatch_allowed(goal, region, sim_time=12.0)
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
    allowed, _ = policy.check_dispatch_allowed(goal, region, sim_time=1.0)
    assert allowed is True

    # Record failure
    policy.on_navigation_failure(goal, region, "BLOCKED", sim_time=15.0)

    # Subsequent dispatch to same region or goal permanently blocked
    allowed_subsequent, reason = policy.check_dispatch_allowed(goal, region, sim_time=20.0)
    assert allowed_subsequent is False
    assert "M1_PERSISTENT_BLOCK" in reason

    # Even if environment clears, M1 has no invalidation mechanism
    policy.on_observation_update({"doorway_state": "FREE"}, sim_time=30.0)
    allowed_after_clear, _ = policy.check_dispatch_allowed(goal, region, sim_time=32.0)
    assert allowed_after_clear is False


def test_m2_conditional_memory_policy():
    policy = M2ConditionalMemoryPolicy(tolerance_m=0.50)
    goal = [1.8, 0.0, 0.0]
    region = "room2_chokepoint"

    # 1. Initial attempt allowed
    allowed, _ = policy.check_dispatch_allowed(goal, region, sim_time=1.0)
    assert allowed is True

    # 2. Failure occurs -> active block
    policy.on_navigation_failure(goal, region, "CORRIDOR_BLOCKED", sim_time=16.0)

    # 3. Repeat attempt blocked while obstacle present
    policy.on_observation_update({"doorway_state": "OCCUPIED"}, sim_time=18.0)
    allowed_repeat, reason = policy.check_dispatch_allowed(goal, region, sim_time=18.5)
    assert allowed_repeat is False
    assert "BLOCKED_BY_ACTIVE_MEMORY" in reason

    # 4. Perception observes doorway FREE -> Invalidates memory
    policy.on_observation_update({"doorway_state": "FREE", "costmap_cleared": True}, sim_time=26.0)

    # 5. Retry dispatch now permitted!
    allowed_retry, reason_retry = policy.check_dispatch_allowed(goal, region, sim_time=27.0)
    assert allowed_retry is True

    # 6. Confirm recovery arrival
    policy.on_navigation_success(
        goal, region,
        physical_eval={"strict_physical_arrival_and_stable": True},
        sim_time=45.0,
    )

    state = policy.export_state()
    assert state["policy_name"] == "M2_CONDITIONAL_MEMORY"
    assert state["recovery_verified_count"] == 1
    assert state["active_count"] == 0
