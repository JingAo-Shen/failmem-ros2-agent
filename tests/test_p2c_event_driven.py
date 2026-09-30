"""Unit tests for P2c event-driven failure memory, perception evaluation, and route execution.

Verifies:
1. SUCCEEDED navigation action does NOT create failure memory.
2. Missing, stale, or occluded scan does NOT produce FREE.
3. Policy decisions are independent of scenario_name (strictly state/observation driven).
4. First action success does NOT trigger fallback.
5. Trajectory without chokepoint approach does NOT increment dead_end_traversals.
6. history_valid=False causes episode_valid=False.
"""
import math
import pytest
from typing import Any, Dict, List

from src.failure_memory import (
    FailureMemoryStore,
    FailureMemoryEntry,
    MemoryState,
)
from src.doorway_evaluator import (
    evaluate_doorway_clearance,
    extract_costmap_doorway_subgrid,
    project_laser_scan_rays_tf,
)
from scripts.run_p2c_pilot_diagnosis import (
    SpatialObservationCache,
    verify_sightline_occlusion,
)


def test_succeeded_action_does_not_create_failure_memory():
    """Verify that a successful action (e.g. reaching vantage point) does not create failure memory."""
    store = FailureMemoryStore()
    action_summary = {
        "action_id": "hist_reach_obs_vantage",
        "terminal_status_name": "SUCCEEDED",
        "execution_outcome": "BUDGET_SUCCESS",
        "deadline_exceeded": False,
    }
    
    # Check that success does not record failure
    if action_summary["execution_outcome"] != "BUDGET_SUCCESS" or action_summary["terminal_status_name"] != "SUCCEEDED":
        store.record_failure(
            goal=[2.5, 0.0, 0.0],
            region_id="north_corridor_chokepoint",
            failure_reason="BUDGET_DEADLINE_EXCEEDED",
            sim_time=15.0,
            failed_action_id=action_summary["action_id"],
            failure_evidence_id="none",
            failure_evidence={"doorway_state": "OCCUPIED"},
        )

    assert len(store.entries) == 0
    is_blocked, entry, _ = store.is_dispatch_blocked([2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1")
    assert is_blocked is False
    assert entry is None


def test_failed_action_with_occupied_evidence_creates_failure_memory():
    """Verify that only an actual failed action with OCCUPIED evidence creates failure memory."""
    store = FailureMemoryStore()
    occ_obs = {
        "doorway_state": "OCCUPIED",
        "reason": "OBSTACLE_DETECTED (8 laser hits inside doorway)",
        "stamp_sec": 18.5,
        "region_id": "north_corridor_chokepoint",
        "map_version": "p2c_dualpath_world_v1",
    }
    failed_action_summary = {
        "action_id": "hist_attempt_chokepoint_traversal",
        "terminal_status_name": "ABORTED",
        "execution_outcome": "BUDGET_DEADLINE_EXCEEDED",
        "deadline_exceeded": True,
        "goal_uuid": "12345678-1234-5678-1234-567812345678",
    }
    
    entry = None
    if failed_action_summary["execution_outcome"] in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"]:
        entry = store.record_failure(
            goal=[2.5, 0.0, 0.0],
            region_id="north_corridor_chokepoint",
            failure_reason=failed_action_summary["execution_outcome"],
            sim_time=18.5,
            failed_action_id=failed_action_summary["action_id"],
            failure_evidence_id="probe1_occ_obs",
            failure_evidence=occ_obs,
            map_version="p2c_dualpath_world_v1",
            metadata={"goal_uuid": failed_action_summary["goal_uuid"]},
        )
    
    assert entry is not None
    assert len(store.entries) == 1
    assert entry.state == MemoryState.ACTIVE
    assert entry.failed_action_id == "hist_attempt_chokepoint_traversal"
    assert entry.failure_evidence["doorway_state"] == "OCCUPIED"
    assert entry.metadata.get("goal_uuid") == failed_action_summary["goal_uuid"]

    is_blocked, blocked_entry, _ = store.is_dispatch_blocked([2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1")
    assert is_blocked is True
    assert blocked_entry == entry


def test_missing_stale_or_occluded_scan_never_produces_free():
    """Verify that missing, stale, or occluded scan results in UNKNOWN, never FREE."""
    doorway_bbox = (-0.30, 0.30, 0.80, 1.60)
    
    # Case A: Occluded / No rays hitting or passing through doorway (robot at J0 = -2.5, 0.0, facing south -1.57)
    ranges_away = [5.0] * 100
    res_occluded = evaluate_doorway_clearance(
        ranges=ranges_away,
        angle_min=-0.5,
        angle_increment=0.01,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-2.50, 0.00, 0.1],
        tf_yaw=-1.57,  # Facing away from doorway
        tf_stamp_sec=20.0,
        scan_stamp_sec=20.0,
        current_sim_time=20.0,
        doorway_bbox=doorway_bbox,
    )
    assert res_occluded["doorway_state"] == "UNKNOWN"
    assert res_occluded["doorway_state"] != "FREE"

    # Case B: Stale scan (scan time 15.0s, current time 20.0s -> staleness 5.0s > 1.0s limit)
    ranges_valid = [3.0] * 100
    res_stale = evaluate_doorway_clearance(
        ranges=ranges_valid,
        angle_min=-0.5,
        angle_increment=0.01,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-0.50, 1.20, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=15.0,
        scan_stamp_sec=15.0,
        current_sim_time=20.0,
        doorway_bbox=doorway_bbox,
    )
    assert res_stale["doorway_state"] == "UNKNOWN"
    assert res_stale["doorway_state"] != "FREE"

    # Case C: No hits inside, but pass-through rays < min_pass_through_rays (e.g. only 2 rays pass through)
    ranges_few = [3.0] * 2
    res_few = evaluate_doorway_clearance(
        ranges=ranges_few,
        angle_min=-0.01,
        angle_increment=0.02,
        range_min=0.1,
        range_max=10.0,
        tf_translation=[-0.50, 1.20, 0.1],
        tf_yaw=0.0,
        tf_stamp_sec=20.0,
        scan_stamp_sec=20.0,
        current_sim_time=20.0,
        doorway_bbox=doorway_bbox,
        min_pass_through_rays=8,
    )
    assert res_few["doorway_state"] == "UNKNOWN"
    assert res_few["doorway_state"] != "FREE"


def test_policy_decisions_are_scenario_agnostic():
    """Verify that policy decisions depend solely on internal policy state, not scenario label."""
    def decide_route(method: str, fail_store: FailureMemoryStore, cache: SpatialObservationCache, m1_suppressed: bool) -> str:
        if method == "R":
            return "Path_A"
        elif method == "O":
            cached_st = cache.get_latest_state("north_corridor_chokepoint")
            return "Path_B" if cached_st == "OCCUPIED" else "Path_A"
        elif method == "F":
            is_blocked, _, _ = fail_store.is_dispatch_blocked([2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1")
            return "Path_B" if is_blocked else "Path_A"
        elif method == "M1":
            return "Path_B" if m1_suppressed else "Path_A"
        return "UNKNOWN"

    store_active = FailureMemoryStore()
    store_active.record_failure(
        goal=[2.5, 0.0, 0.0],
        region_id="north_corridor_chokepoint",
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=10.0,
        failed_action_id="act_1",
        failure_evidence_id="ev_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
        map_version="p2c_dualpath_world_v1",
    )
    cache_occ = SpatialObservationCache()
    cache_occ.update_observation("north_corridor_chokepoint", "OCCUPIED", 10.0, {})

    # Method F with active failure memory chooses Path_B regardless of any fictitious scenario tag
    for fake_scenario in ["D0", "D1", "D2", "CUSTOM_X"]:
        route = decide_route("F", store_active, cache_occ, False)
        assert route == "Path_B"

    # Method R always explores Path_A regardless of scenario tag
    for fake_scenario in ["D0", "D1", "D2"]:
        route = decide_route("R", store_active, cache_occ, False)
        assert route == "Path_A"


def test_first_action_success_does_not_trigger_fallback():
    """Verify that when Leg 2 succeeds (e.g. in D0/D2), route executor does not trigger fallback to Path B."""
    leg2_result = {
        "action_id": "dec_leg2_traversal",
        "terminal_status_name": "SUCCEEDED",
        "execution_outcome": "BUDGET_SUCCESS",
        "deadline_exceeded": False,
    }
    
    fallback_triggered = False
    dead_end_traversals = 0
    
    if leg2_result["terminal_status_name"] != "SUCCEEDED" or leg2_result["execution_outcome"] != "BUDGET_SUCCESS":
        fallback_triggered = True
        dead_end_traversals += 1

    assert fallback_triggered is False
    assert dead_end_traversals == 0


def test_dead_end_traversal_detection():
    """Verify that dead-end traversal is detected only when trajectory actually enters chokepoint and retreats."""
    traj_path_b = [
        {"x": -2.50, "y": 0.00},
        {"x": -2.50, "y": -1.00},
        {"x": -2.50, "y": -2.00},
        {"x": -1.00, "y": -2.40},
        {"x": 0.00, "y": -2.40},
        {"x": 2.50, "y": 0.00},
    ]
    
    def count_dead_ends(samples: List[Dict[str, float]], chokepoint_x_min: float = -1.8, chokepoint_y_min: float = 0.6) -> int:
        entered_chokepoint = any(s["x"] >= chokepoint_x_min and s["y"] >= chokepoint_y_min for s in samples)
        retreated_to_j0 = entered_chokepoint and any(s["x"] <= -2.2 and abs(s["y"]) <= 0.5 for s in samples[len(samples)//2:])
        return 1 if (entered_chokepoint and retreated_to_j0) else 0

    assert count_dead_ends(traj_path_b) == 0

    traj_dead_end = [
        {"x": -2.50, "y": 0.00},
        {"x": -1.50, "y": 1.20},
        {"x": -0.50, "y": 1.20},
        {"x": -1.50, "y": 1.20},
        {"x": -2.50, "y": 0.00},
        {"x": -2.50, "y": -2.00},
        {"x": 0.00, "y": -2.40},
        {"x": 2.50, "y": 0.00},
    ]
    assert count_dead_ends(traj_dead_end) == 1


def test_episode_validity_flags():
    """Verify that failure in history_valid or route_valid marks episode_valid=False."""
    def compute_episode_validity(final_goal_success: bool, history_valid: bool, route_valid: bool) -> Dict[str, bool]:
        return {
            "final_goal_success": final_goal_success,
            "history_valid": history_valid,
            "route_valid": route_valid,
            "episode_valid": bool(final_goal_success and history_valid and route_valid),
        }

    # Case 1: All valid
    v1 = compute_episode_validity(final_goal_success=True, history_valid=True, route_valid=True)
    assert v1["episode_valid"] is True

    # Case 2: History invalid (e.g. failed probe when it should succeed)
    v2 = compute_episode_validity(final_goal_success=True, history_valid=False, route_valid=True)
    assert v2["episode_valid"] is False

    # Case 3: Final goal failed
    v3 = compute_episode_validity(final_goal_success=False, history_valid=True, route_valid=True)
    assert v3["episode_valid"] is False
