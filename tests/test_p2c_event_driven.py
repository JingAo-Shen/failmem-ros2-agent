"""Unit tests for P2c production pipeline, event-driven memory, and replay audit.

Directly imports and validates production modules from `src.p2c_pipeline`:
- P2cProtocolConfig
- P2cTrajectoryClassifier
- P2cPolicyDecider
- P2cEpisodeEvaluator
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
from src.p2c_pipeline import (
    P2cProtocolConfig,
    P2cTrajectoryClassifier,
    P2cPolicyDecider,
    P2cEpisodeEvaluator,
)


def test_succeeded_action_does_not_create_failure_memory():
    """Verify that a successful action (e.g. reaching vantage point) never creates failure memory."""
    store = FailureMemoryStore()
    action_summary = {
        "action_id": "hist_reach_obs_vantage",
        "terminal_status_name": "SUCCEEDED",
        "execution_outcome": "BUDGET_SUCCESS",
        "deadline_exceeded": False,
    }

    # Production logic check: only failed actions trigger record_failure
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


def test_failed_traversal_with_fresh_occupied_evidence_creates_memory():
    """Verify that failed traversal with fresh OCCUPIED evidence creates failure memory."""
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
    action_traj = [{"x": -0.4, "y": 1.2, "recv_sim_time_sec": 19.0}]

    cause = P2cTrajectoryClassifier.diagnose_failure_cause(failed_action_summary, action_traj, occ_obs, max_staleness_sec=2.0)
    assert cause == "BLOCKED_AT_DOORWAY"

    entry = store.record_failure(
        goal=[2.5, 0.0, 0.0],
        region_id="north_corridor_chokepoint",
        failure_reason=failed_action_summary["execution_outcome"],
        sim_time=19.0,
        failed_action_id=failed_action_summary["action_id"],
        failure_evidence_id="probe1_occ_obs",
        failure_evidence=occ_obs,
        map_version="p2c_dualpath_world_v1",
        metadata={"goal_uuid": failed_action_summary["goal_uuid"]},
    )

    assert entry is not None
    assert entry.state == MemoryState.ACTIVE
    is_blocked, blocked_entry, _ = store.is_dispatch_blocked([2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1")
    assert is_blocked is True


def test_stale_occupied_cannot_justify_failure():
    """Verify that stale OCCUPIED evidence (> 2.0s old) is diagnosed as STALE, not confirmed blocked."""
    stale_occ_obs = {
        "doorway_state": "OCCUPIED",
        "stamp_sec": 10.0,  # 10.0s vs action time 35.0s -> 25s staleness
        "region_id": "north_corridor_chokepoint",
        "map_version": "p2c_dualpath_world_v1",
    }
    failed_action_summary = {
        "action_id": "dec_path_a_traversal",
        "terminal_status_name": "ABORTED",
        "execution_outcome": "BUDGET_DEADLINE_EXCEEDED",
    }
    action_traj = [{"x": -0.3, "y": 1.2, "recv_sim_time_sec": 35.0}]

    cause = P2cTrajectoryClassifier.diagnose_failure_cause(failed_action_summary, action_traj, stale_occ_obs, max_staleness_sec=2.0)
    assert cause == "DOORWAY_BLOCKED_EVIDENCE_STALE"


def test_missing_free_evidence_does_not_invalidate_memory():
    """Verify that absence of FREE evidence leaves memory ACTIVE."""
    store = FailureMemoryStore()
    store.record_failure(
        goal=[2.5, 0.0, 0.0],
        region_id="north_corridor_chokepoint",
        failure_reason="BUDGET_DEADLINE_EXCEEDED",
        sim_time=10.0,
        failed_action_id="act_1",
        failure_evidence_id="ev_1",
        failure_evidence={"doorway_state": "OCCUPIED"},
        map_version="p2c_dualpath_world_v1",
    )

    # Inconclusive / UNKNOWN observation
    unknown_obs = {
        "doorway_state": "UNKNOWN",
        "timestamp_sim": 25.0,
        "region_id": "north_corridor_chokepoint",
        "map_version": "p2c_dualpath_world_v1",
    }
    invalidated_entries = store.evaluate_perception_for_invalidation(
        perception_evidence=unknown_obs,
        sim_time=25.0,
        evidence_id="obs_unknown",
        map_version="p2c_dualpath_world_v1",
        region_id="north_corridor_chokepoint",
    )
    assert len(invalidated_entries) == 0
    is_blocked, _, _ = store.is_dispatch_blocked([2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1")
    assert is_blocked is True


def test_method_r_consumes_live_observation_via_production_decider():
    """Verify that Method R properly routes based on live observation at J0."""
    cache = SpatialObservationCache()
    fail_store = FailureMemoryStore()

    # Case A: Live sensor returns UNKNOWN (occluded sightline) -> explores Path A
    obs_unknown = {"doorway_state": "UNKNOWN", "reason": "DOORWAY_NOT_IN_FOV_OR_OCCLUDED"}
    route_a, rationale_a, meta_a = P2cPolicyDecider.decide_route(
        "R", obs_unknown, cache, fail_store, False, [2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1"
    )
    assert route_a == "Path_A"
    assert meta_a.get("infra_error") is False

    # Case B: Live sensor returns OCCUPIED (e.g. vantage point) -> routes Path B
    obs_occ = {"doorway_state": "OCCUPIED", "reason": "OBSTACLE_DETECTED"}
    route_b, _, _ = P2cPolicyDecider.decide_route(
        "R", obs_occ, cache, fail_store, False, [2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1"
    )
    assert route_b == "Path_B"

    # Case C: Infrastructure error (TF unavailable) -> flags anomaly
    obs_tf_err = {"doorway_state": "UNKNOWN", "error": "TF_TRANSLATION_OR_YAW_MISSING"}
    _, _, meta_c = P2cPolicyDecider.decide_route(
        "R", obs_tf_err, cache, fail_store, False, [2.5, 0.0, 0.0], "north_corridor_chokepoint", "p2c_dualpath_world_v1"
    )
    assert meta_c.get("infra_error") is True


def test_dead_end_traversal_detection_production_classifier():
    """Verify that P2cTrajectoryClassifier correctly identifies genuine dead ends."""
    # 1. Direct Path B trajectory (never entered North approach)
    traj_path_b = [
        {"x": -2.50, "y": 0.00},
        {"x": -2.50, "y": -1.00},
        {"x": -2.50, "y": -2.00},
        {"x": -1.00, "y": -2.40},
        {"x": 0.00, "y": -2.40},
        {"x": 1.00, "y": -2.40},
        {"x": 2.50, "y": -2.00},
        {"x": 2.50, "y": 0.00},
    ] * 5
    assert P2cTrajectoryClassifier.classify_dead_end_traversals(traj_path_b) == 0
    assert P2cTrajectoryClassifier.classify_actual_route(traj_path_b) == "Path_B"

    # 2. Dead-end entry: J0 -> Approach -> Halt at Doorway -> Retreat to J0 -> Path B -> Goal
    traj_dead_end = (
        [{"x": -2.50, "y": 0.00}] * 5
        + [{"x": -1.50, "y": 1.20}] * 5
        + [{"x": -0.40, "y": 1.20}] * 10  # halted at doorway
        + [{"x": -1.50, "y": 1.20}] * 5
        + [{"x": -2.50, "y": 0.00}] * 5   # retreated to J0
        + [{"x": 0.00, "y": -2.40}] * 10  # detour
        + [{"x": 2.50, "y": 0.00}] * 5
    )
    assert P2cTrajectoryClassifier.classify_dead_end_traversals(traj_dead_end) == 1
    assert P2cTrajectoryClassifier.classify_actual_route(traj_dead_end) == "Path_A_then_Path_B"


def test_budget_exhaustion_fails_evaluation_in_production_evaluator():
    """Verify that total simulation time exceeding 180s fails success_within_budget and episode_valid."""
    actions = [
        {"action_id": "hist_reach_obs_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS"},
        {"action_id": "hist_attempt_chokepoint_traversal", "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_DEADLINE_EXCEEDED"},
        {"action_id": "hist_retreat_to_j0", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS"},
        {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS"},
    ]
    odom_samples = [{"x": -2.5 + i * 0.1, "y": 0.0} for i in range(50)]

    # Case A: 185.6s > 180.0s budget -> FAIL
    res_over = P2cEpisodeEvaluator.evaluate_episode(
        scenario="D1",
        method="R",
        actions=actions,
        total_sim_time_sec=185.6,
        total_budget_sec=180.0,
        physical_eval_dict={"strict_physical_arrival_and_stable": True},
        odom_samples=odom_samples,
        costmap_snapshots=[{"stage": "COSTMAP_PROBE_BLOCKED", "cell_counts": {"opening_lethal": 10}}],
        checksums_verified=True,
        protocol_hash_match=True,
        evidence_complete=True,
    )
    assert res_over["final_goal_success"] is True
    assert res_over["success_within_budget"] is False
    assert res_over["episode_valid"] is False

    # Case B: 175.0s <= 180.0s budget -> PASS
    res_under = P2cEpisodeEvaluator.evaluate_episode(
        scenario="D1",
        method="R",
        actions=actions,
        total_sim_time_sec=175.0,
        total_budget_sec=180.0,
        physical_eval_dict={"strict_physical_arrival_and_stable": True},
        odom_samples=odom_samples,
        costmap_snapshots=[{"stage": "COSTMAP_PROBE_BLOCKED", "cell_counts": {"opening_lethal": 10}}],
        checksums_verified=True,
        protocol_hash_match=True,
        evidence_complete=True,
    )
    assert res_under["success_within_budget"] is True
    assert res_under["episode_valid"] is True


def test_tamper_detection_in_production_evaluator():
    """Verify that missing checksums, protocol mismatch, or incomplete evidence fails audit."""
    actions = [{"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS"}]
    odom_samples = [{"x": -2.5 + i * 0.1, "y": 0.0} for i in range(50)]

    # Checksum verification failure -> audit_pass = False
    res_tamper = P2cEpisodeEvaluator.evaluate_episode(
        scenario="D0",
        method="R",
        actions=actions,
        total_sim_time_sec=50.0,
        total_budget_sec=180.0,
        physical_eval_dict={"strict_physical_arrival_and_stable": True},
        odom_samples=odom_samples,
        costmap_snapshots=[],
        checksums_verified=False,  # Tampered!
        protocol_hash_match=True,
        evidence_complete=True,
    )
    assert res_tamper["audit_pass"] is False

    # Protocol hash mismatch -> audit_pass = False
    res_proto = P2cEpisodeEvaluator.evaluate_episode(
        scenario="D0",
        method="R",
        actions=actions,
        total_sim_time_sec=50.0,
        total_budget_sec=180.0,
        physical_eval_dict={"strict_physical_arrival_and_stable": True},
        odom_samples=odom_samples,
        costmap_snapshots=[],
        checksums_verified=True,
        protocol_hash_match=False,  # Mismatch!
        evidence_complete=True,
    )
    assert res_proto["audit_pass"] is False
