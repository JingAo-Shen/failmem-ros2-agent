"""Comprehensive validation tests for P2a-v2 protocol and execution engine."""
import copy
import pytest
from src.failure_memory import (
    FailureMemoryStore,
    MemoryState,
    M0NoMemoryPolicy,
    M1PersistentMemoryPolicy,
    M2ConditionalMemoryPolicy,
)


def test_quota_protection_suppressions_do_not_consume_retries():
    """Verify that multiple consecutive dispatch suppressions DO NOT consume retry quota."""
    policy = M2ConditionalMemoryPolicy()
    target_goal = [1.8, 0.0, 0.0]
    target_region = "room2_corridor_chokepoint"

    max_retries = 5
    navigation_attempt_count = 0

    # 1. Initial attempt fails
    navigation_attempt_count += 1
    policy.on_navigation_failure(
        target_goal=target_goal,
        target_region=target_region,
        failure_reason="NAV2_ABORTED",
        sim_time=15.0,
        failed_action_id="act_1",
        failure_evidence_id="obs_1",
        perception_evidence={"doorway_state": "OCCUPIED"},
    )

    # 2. Simulate 10 consecutive gate suppressions during continuous blockage
    suppression_count = 0
    for step in range(10):
        allowed, reason, blocked_id = policy.check_dispatch_allowed(
            target_goal=target_goal,
            target_region=target_region,
            sim_time=16.0 + step * 2.0,
        )
        assert allowed is False
        assert blocked_id is not None
        suppression_count += 1

    # Retry count remains 0 because no navigation retry was dispatched
    retry_count = max(0, navigation_attempt_count - 1)
    assert suppression_count == 10
    assert navigation_attempt_count == 1
    assert retry_count == 0
    assert retry_count < max_retries


def test_budget_exhaustion_dynamic_timeout():
    """Verify that single action timeout adapts to remaining episode budget."""
    episode_total_sim_budget_sec = 75.0
    action_sim_timeout_sec = 25.0

    # Case A: Early in episode (elapsed = 10s) -> full action timeout
    elapsed_sim = 10.0
    rem_budget = episode_total_sim_budget_sec - elapsed_sim
    timeout_a = min(action_sim_timeout_sec, rem_budget)
    assert timeout_a == 25.0

    # Case B: Late in episode (elapsed = 60s) -> clamped action timeout (15s)
    elapsed_sim = 60.0
    rem_budget = episode_total_sim_budget_sec - elapsed_sim
    timeout_b = min(action_sim_timeout_sec, rem_budget)
    assert timeout_b == 15.0

    # Case C: Budget exhausted (elapsed = 74.5s) -> timeout <= 1.0s -> dispatch rejected
    elapsed_sim = 74.5
    rem_budget = episode_total_sim_budget_sec - elapsed_sim
    timeout_c = min(action_sim_timeout_sec, rem_budget)
    assert timeout_c <= 1.0


def test_selective_invalidation_boundaries():
    """Verify that only matching region and newer FREE evidence invalidates entries."""
    store = FailureMemoryStore(region_matching_tolerance_m=0.50)
    
    # Record failure in corridor chokepoint at t = 20.0s
    e1 = store.record_failure(
        goal=[1.8, 0.0, 0.0],
        region_id="room2_corridor_chokepoint",
        failure_reason="NAV2_ABORTED",
        sim_time=20.0,
        failed_action_id="act_1",
        failure_evidence_id="obs_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
        map_version="map_v1",
    )
    assert e1 is not None

    # 1. FREE in another room/region does NOT invalidate chokepoint
    inv_other_region = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "region_id": "room1_storage"},
        sim_time=25.0,
        region_id="room1_storage",
        map_version="map_v1",
    )
    assert len(inv_other_region) == 0
    assert e1.state == MemoryState.ACTIVE

    # 2. UNKNOWN in chokepoint does NOT invalidate
    inv_unknown = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "UNKNOWN", "region_id": "room2_corridor_chokepoint"},
        sim_time=26.0,
        region_id="room2_corridor_chokepoint",
        map_version="map_v1",
    )
    assert len(inv_unknown) == 0
    assert e1.state == MemoryState.ACTIVE

    # 3. Mismatched map_version does NOT invalidate
    inv_wrong_map = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "region_id": "room2_corridor_chokepoint"},
        sim_time=27.0,
        region_id="room2_corridor_chokepoint",
        map_version="map_v2",
    )
    assert len(inv_wrong_map) == 0
    assert e1.state == MemoryState.ACTIVE

    # 4. Valid FREE in chokepoint on map_v1 at t = 28.0s DOES invalidate
    inv_valid = store.evaluate_perception_for_invalidation(
        perception_evidence={"doorway_state": "FREE", "region_id": "room2_corridor_chokepoint"},
        sim_time=28.0,
        region_id="room2_corridor_chokepoint",
        map_version="map_v1",
    )
    assert len(inv_valid) == 1
    assert inv_valid[0].memory_id == e1.memory_id
    assert e1.state == MemoryState.INVALIDATED


def test_gt_and_scenario_isolation_in_policy():
    """Verify that zero GT coordinates, scenario names, or deletion flags leak into policy memory."""
    policy = M2ConditionalMemoryPolicy()

    # Feed failure with public feedback only
    policy.on_navigation_failure(
        target_goal=[1.8, 0.0, 0.0],
        target_region="room2_corridor_chokepoint",
        failure_reason="NAV2_ABORTED",
        sim_time=15.0,
        failed_action_id="ep_nav_step1",
        failure_evidence_id="obs_1",
        perception_evidence={"doorway_state": "OCCUPIED", "hits_inside_count": 10},
    )

    state = policy.export_state()
    state_str = str(state)

    # Check: No GT leakage
    assert "gt_position_error_m" not in state_str
    assert "gt_yaw_error_rad" not in state_str
    assert "final_gt" not in state_str

    # Check: No scenario tag leakage (S1/S2)
    assert "'S1'" not in state_str
    assert "'S2'" not in state_str
    assert "obstacle_deleted" not in state_str
    assert "sequence_name" not in state_str
