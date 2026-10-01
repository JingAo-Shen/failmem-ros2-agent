"""Unit tests for P2c production pipeline, event-driven memory, and replay audit.

Directly imports and validates production modules from `src.p2c_pipeline`:
- P2cProtocolConfig
- P2cTrajectoryClassifier
- P2cPolicyDecider
- P2cEpisodeEvaluator
"""

import json
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
    verify_sightline_occlusion,
)
from src.p2c_pipeline import (
    P2cProtocolConfig,
    P2cTrajectoryClassifier,
    P2cPolicyDecider,
    P2cEpisodeEvaluator,
    SpatialObservationCache,
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


def test_negative_probe_without_real_terminal_evidence():
    """Verify that a probe claiming failure without genuine obstacle evidence cannot justify memory."""
    store = FailureMemoryStore()
    fake_probe_action = {
        "action_id": "hist_attempt_chokepoint_traversal",
        "terminal_status_name": "ABORTED",
        "execution_outcome": "BUDGET_ABORTED",
    }
    # Trajectory stopped far before doorway
    traj_stopped_early = [{"x": -2.0, "y": 0.5, "recv_sim_time_sec": 10.0}]
    obs_none = None

    cause = P2cTrajectoryClassifier.diagnose_failure_cause(
        fake_probe_action, traj_stopped_early, obs_none, max_staleness_sec=2.0
    )
    assert cause != "BLOCKED_AT_DOORWAY"
    assert cause == "NAVIGATION_ABORTED_OR_FAILED"

    # Memory must NOT be created without confirmed BLOCKED_AT_DOORWAY / OCCUPIED evidence
    if cause == "BLOCKED_AT_DOORWAY":
        store.record_failure(
            goal=[2.5, 0.0, 0.0],
            region_id="north_corridor_chokepoint",
            failure_reason=cause,
            sim_time=10.0,
            failed_action_id="hist_attempt_chokepoint_traversal",
            failure_evidence_id="none",
            failure_evidence={},
        )
    assert len(store.entries) == 0


def test_negative_invalid_history_runner_hard_stop_zero_dispatches():
    """Verify that an invalid history marks history_aborted=True, 0 dispatches, and fails task_success."""
    actions = [
        {"action_id": "hist_reach_obs_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS"},
        {"action_id": "hist_attempt_chokepoint_traversal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS"},  # Traversal unexpectedly succeeded in D1!
    ]
    odom_samples = [{"x": -2.5 + i * 0.1, "y": 0.0} for i in range(20)]

    res_aborted = P2cEpisodeEvaluator.evaluate_episode(
        scenario="D1",
        method="F",
        actions=actions,
        total_sim_time_sec=40.0,
        total_budget_sec=180.0,
        physical_eval_dict={"strict_physical_arrival_and_stable": False},
        odom_samples=odom_samples,
        costmap_snapshots=[],
        checksums_verified=True,
        protocol_hash_match=True,
        evidence_complete=True,
        history_aborted=True,
    )
    assert res_aborted["history_valid"] is False
    assert res_aborted["task_success"] is False
    assert res_aborted["final_goal_success"] is False
    assert res_aborted["episode_valid"] is False
    assert "HISTORY_ABORTED_DUE_TO_INCOMPLETE_OR_INVALID_EVIDENCE" in res_aborted["history_reasons"]


def test_negative_spatial_cache_unified_observation_update():
    """Verify that SpatialObservationCache updates on OCCUPIED and FREE, but ignores UNKNOWN without dropping state."""
    cache = SpatialObservationCache()
    fail_store = FailureMemoryStore()

    # Initial state is UNKNOWN
    assert cache.get_latest_state("north_corridor_chokepoint") == "UNKNOWN"

    # Step 1: Observes OCCUPIED
    cache.update_observation("north_corridor_chokepoint", "OCCUPIED", 10.0, {"hits": 5})
    assert cache.get_latest_state("north_corridor_chokepoint") == "OCCUPIED"

    # Step 2: Observes UNKNOWN (e.g. at J0) -> must NOT overwrite OCCUPIED
    cache.update_observation("north_corridor_chokepoint", "UNKNOWN", 15.0, {"reason": "OCCLUDED"})
    assert cache.get_latest_state("north_corridor_chokepoint") == "OCCUPIED"

    # Step 3: Observes FREE (after clearance in D2) -> updates to FREE
    cache.update_observation("north_corridor_chokepoint", "FREE", 20.0, {"hits": 0})
    assert cache.get_latest_state("north_corridor_chokepoint") == "FREE"

    # Step 4: Observes UNKNOWN again at J0 -> must NOT overwrite FREE
    cache.update_observation("north_corridor_chokepoint", "UNKNOWN", 25.0, {"reason": "OCCLUDED"})
    assert cache.get_latest_state("north_corridor_chokepoint") == "FREE"

    # Policy Method O must select Path A when cache is FREE
    live_obs_j0 = {"doorway_state": "UNKNOWN", "reason": "OCCLUDED"}
    chosen_route, rationale, meta = P2cPolicyDecider.decide_route(
        method="O",
        live_obs=live_obs_j0,
        cache=cache,
        fail_store=fail_store,
        m1_suppressed=False,
        target_goal=[2.5, 0.0, 0.0],
        region_id="north_corridor_chokepoint",
        map_version="p2c_dualpath_world_v1",
    )
    assert chosen_route == "Path_A"
    assert meta.get("cache_state") == "FREE"


import hashlib
from pathlib import Path


def _recompute_episode_checksums(ep_dir: Path) -> Dict[str, str]:
    ep_id = ep_dir.name
    chk_dict = {}
    for p in ep_dir.iterdir():
        if p.is_file() and p.name != "checksums.sha256":
            h = hashlib.sha256()
            with open(p, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            chk_dict[f"{ep_id}/{p.name}"] = h.hexdigest()
    return chk_dict


def _create_valid_test_episode_bundle(
    ep_dir: Path,
    scenario: str = "D1",
    method: str = "F",
) -> Dict[str, str]:
    """Helper to create a complete, 100% production-valid test episode directory in tmp_path."""
    from src.doorway_evaluator import create_observation_bundle, evaluate_observation_bundle
    ep_dir.mkdir(parents=True, exist_ok=True)

    doorway_bbox = (-0.25, 0.25, 0.90, 1.50)
    opening_bbox = (-0.15, 0.15, 0.95, 1.45)
    target_goal = [2.50, 0.00, 0.0]
    chokepoint_region = "north_corridor_chokepoint"
    map_version = "p2c_dualpath_world_v1"

    goal_uuid_tr1 = "11111111-2222-3333-4444-555555555555"

    subgrid_blocked = [[100 if (4 <= u <= 6 and 4 <= v <= 6) else 0 for u in range(10)] for v in range(10)]
    subgrid_free = [[0 for _ in range(10)] for _ in range(10)]

    cm_probe1 = {
        "stage": "COSTMAP_PROBE_BLOCKED_AT_CHOKEPOINT",
        "sim_time_sec": 10.0,
        "costmap_available": True,
        "resolution_m": 0.05,
        "origin_xy": [-0.25, 0.90],
        "grid_bounds_u": [0, 9],
        "grid_bounds_v": [0, 9],
        "doorway_bbox": list(doorway_bbox),
        "opening_bbox": list(opening_bbox),
        "cell_counts": {"unknown": 0, "free": 91, "inflated": 0, "lethal": 9, "opening_lethal": 9},
        "has_blockage": True,
        "subgrid_matrix": subgrid_blocked,
    }

    cm_probe2 = {
        "stage": "COSTMAP_PROBE_CLEARED_AT_CHOKEPOINT",
        "sim_time_sec": 40.0,
        "costmap_available": True,
        "resolution_m": 0.05,
        "origin_xy": [-0.25, 0.90],
        "grid_bounds_u": [0, 9],
        "grid_bounds_v": [0, 9],
        "doorway_bbox": list(doorway_bbox),
        "opening_bbox": list(opening_bbox),
        "cell_counts": {"unknown": 0, "free": 100, "inflated": 0, "lethal": 0, "opening_lethal": 0},
        "has_blockage": False,
        "subgrid_matrix": subgrid_free,
    }

    # Bundles created via production functions
    b_v1 = create_observation_bundle(
        stage="STEP1_VANTAGE1",
        raw_scan_msg={"ranges": [1.0] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 10.0},
        tf_transform_dict={"translation": [-1.00, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 10.0},
        raw_costmap_msg=None,
        capture_sim_time=10.0,
        capture_wall_time=100.0,
        doorway_bbox=doorway_bbox,
        opening_bbox=opening_bbox,
        observation_id="obs_v1_valid_001",
    )
    b_v1 = evaluate_observation_bundle(b_v1, current_sim_time=10.0, current_wall_time=100.0)

    b_tr1 = create_observation_bundle(
        stage="STEP2_POST_TRAVERSAL",
        raw_scan_msg={"ranges": [0.4] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 20.0},
        tf_transform_dict={"translation": [-0.40, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 20.0},
        raw_costmap_msg=None,
        capture_sim_time=20.0,
        capture_wall_time=110.0,
        doorway_bbox=doorway_bbox,
        opening_bbox=opening_bbox,
        observation_id="obs_tr1_valid_002",
    )
    b_tr1 = evaluate_observation_bundle(b_tr1, current_sim_time=20.0, current_wall_time=110.0)

    b_ret1 = create_observation_bundle(
        stage="STEP3_RETREAT_J0",
        raw_scan_msg={"ranges": [2.5] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 28.0},
        tf_transform_dict={"translation": [-2.50, 0.00, 0.0], "yaw": 0.0, "stamp_sec": 28.0},
        raw_costmap_msg=None,
        capture_sim_time=28.0,
        capture_wall_time=118.0,
        doorway_bbox=doorway_bbox,
        opening_bbox=opening_bbox,
        observation_id="obs_ret1_valid_003",
    )
    b_ret1 = evaluate_observation_bundle(b_ret1, current_sim_time=28.0, current_wall_time=118.0)

    b_dec = create_observation_bundle(
        stage="DECISION_J0",
        raw_scan_msg={"ranges": [2.5] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 30.0},
        tf_transform_dict={"translation": [-2.50, 0.00, 0.0], "yaw": 0.0, "stamp_sec": 30.0},
        raw_costmap_msg=None,
        capture_sim_time=30.0,
        capture_wall_time=120.0,
        doorway_bbox=doorway_bbox,
        opening_bbox=opening_bbox,
        observation_id="obs_dec_valid_004",
    )
    b_dec = evaluate_observation_bundle(b_dec, current_sim_time=30.0, current_wall_time=120.0)

    if scenario == "D1" and method == "F":
        actions = [
            {"action_id": "hist_reach_obs_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 0.0, "timestamp_sim": 10.0, "evaluation": {"timestamp_sim": 10.0}},
            {"action_id": "hist_attempt_chokepoint_traversal", "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_DEADLINE_EXCEEDED", "timestamp_sim_start": 10.1, "timestamp_sim": 20.0, "dispatch": {"goal_uuid": goal_uuid_tr1}, "evaluation": {"timestamp_sim": 20.0}},
            {"action_id": "hist_retreat_to_j0", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 20.1, "timestamp_sim": 28.0, "evaluation": {"timestamp_sim": 28.0}},
            {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 30.0, "timestamp_sim": 80.0, "evaluation": {"timestamp_sim": 80.0}},
        ]
        requested_route = "Path_B"
        costmap_snaps = [cm_probe1]
        scan_snaps = [b_v1, b_tr1, b_ret1, b_dec]
        mem_events = [
            {
                "event_seq": 1,
                "event_type": "RECORD_FAILURE",
                "sim_time": 20.0,
                "memory_id": "mem_entry_0001",
                "failed_action_id": "hist_attempt_chokepoint_traversal",
                "goal_uuid": goal_uuid_tr1,
                "observation_id": "obs_tr1_valid_002",
                "region_id": chokepoint_region,
                "map_version": map_version,
                "target_goal": target_goal,
                "failure_reason": "BUDGET_DEADLINE_EXCEEDED",
                "initial_state": "ACTIVE",
                "evidence_state": "OCCUPIED",
            }
        ]

    elif scenario == "D2" and method == "F":
        b_clr = create_observation_bundle(
            stage="STEP4_CLEARANCE_VANTAGE",
            raw_scan_msg={"ranges": [3.0] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 40.0},
            tf_transform_dict={"translation": [-1.00, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 40.0},
            raw_costmap_msg=None,
            capture_sim_time=40.0,
            capture_wall_time=130.0,
            doorway_bbox=doorway_bbox,
            opening_bbox=opening_bbox,
            observation_id="obs_clr_valid_005",
        )
        b_clr = evaluate_observation_bundle(b_clr, current_sim_time=40.0, current_wall_time=130.0)

        b_ret2 = create_observation_bundle(
            stage="STEP5_RETREAT_J0_CLEAR",
            raw_scan_msg={"ranges": [2.5] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 48.0},
            tf_transform_dict={"translation": [-2.50, 0.00, 0.0], "yaw": 0.0, "stamp_sec": 48.0},
            raw_costmap_msg=None,
            capture_sim_time=48.0,
            capture_wall_time=138.0,
            doorway_bbox=doorway_bbox,
            opening_bbox=opening_bbox,
            observation_id="obs_ret2_valid_006",
        )
        b_ret2 = evaluate_observation_bundle(b_ret2, current_sim_time=48.0, current_wall_time=138.0)

        b_dec_d2 = create_observation_bundle(
            stage="DECISION_J0",
            raw_scan_msg={"ranges": [2.5] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 50.0},
            tf_transform_dict={"translation": [-2.50, 0.00, 0.0], "yaw": 0.0, "stamp_sec": 50.0},
            raw_costmap_msg=None,
            capture_sim_time=50.0,
            capture_wall_time=140.0,
            doorway_bbox=doorway_bbox,
            opening_bbox=opening_bbox,
            observation_id="obs_dec_d2_valid_007",
        )
        b_dec_d2 = evaluate_observation_bundle(b_dec_d2, current_sim_time=50.0, current_wall_time=140.0)

        actions = [
            {"action_id": "hist_reach_obs_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 0.0, "timestamp_sim": 10.0, "evaluation": {"timestamp_sim": 10.0}},
            {"action_id": "hist_attempt_chokepoint_traversal", "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_DEADLINE_EXCEEDED", "timestamp_sim_start": 10.1, "timestamp_sim": 20.0, "dispatch": {"goal_uuid": goal_uuid_tr1}, "evaluation": {"timestamp_sim": 20.0}},
            {"action_id": "hist_retreat_to_j0", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 20.1, "timestamp_sim": 28.0, "evaluation": {"timestamp_sim": 28.0}},
            {"action_id": "hist_probe_clearance_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 30.0, "timestamp_sim": 40.0, "evaluation": {"timestamp_sim": 40.0}},
            {"action_id": "hist_retreat_to_j0_clear", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 40.1, "timestamp_sim": 48.0, "evaluation": {"timestamp_sim": 48.0}},
            {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 50.0, "timestamp_sim": 90.0, "evaluation": {"timestamp_sim": 90.0}},
        ]
        requested_route = "Path_A"
        costmap_snaps = [cm_probe1, cm_probe2]
        scan_snaps = [b_v1, b_tr1, b_ret1, b_clr, b_ret2, b_dec_d2]
        mem_events = [
            {
                "event_seq": 1,
                "event_type": "RECORD_FAILURE",
                "sim_time": 20.0,
                "memory_id": "mem_entry_0001",
                "failed_action_id": "hist_attempt_chokepoint_traversal",
                "goal_uuid": goal_uuid_tr1,
                "observation_id": "obs_tr1_valid_002",
                "region_id": chokepoint_region,
                "map_version": map_version,
                "target_goal": target_goal,
                "failure_reason": "BUDGET_DEADLINE_EXCEEDED",
                "initial_state": "ACTIVE",
                "evidence_state": "OCCUPIED",
            },
            {
                "event_seq": 2,
                "event_type": "INVALIDATE_MEMORY",
                "sim_time": 40.0,
                "memory_id": "mem_entry_0001",
                "invalidated_by_observation_id": "obs_clr_valid_005",
                "region_id": chokepoint_region,
                "map_version": map_version,
                "target_goal": target_goal,
                "previous_state": "ACTIVE",
                "resulting_state": "INVALIDATED",
                "evidence_state": "FREE",
            }
        ]
    else:  # D0_R
        actions = [
            {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "timestamp_sim_start": 0.0, "timestamp_sim": 50.0, "evaluation": {"timestamp_sim": 50.0}},
        ]
        requested_route = "Path_A"
        costmap_snaps = []
        scan_snaps = [b_dec]
        mem_events = []

    action_res = {
        "episode_id": ep_dir.name,
        "condition_id": f"{scenario}_{method}",
        "scenario": scenario,
        "method": method,
        "requested_route": requested_route,
        "chosen_route": requested_route,
        "total_distance_m": 12.0,
        "total_sim_time_sec": 80.0 if scenario == "D1" else (90.0 if scenario == "D2" else 50.0),
        "total_budget_sec": 180.0,
        "actions": actions,
    }
    with open(ep_dir / "action_result.json", "w") as f:
        json.dump(action_res, f, indent=2)

    with open(ep_dir / "trajectory.json", "w") as f:
        json.dump({
            "odom_trajectory": [{"x": -2.5 + i * 0.1, "y": 0.0, "recv_sim_time_sec": float(i)} for i in range(50)],
            "gt_trajectory": [{"x": -2.5 + i * 0.1, "y": 0.0, "sim_time": float(i)} for i in range(50)],
        }, f, indent=2)

    with open(ep_dir / "costmap_snapshots.json", "w") as f:
        json.dump(costmap_snaps, f, indent=2)

    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(scan_snaps, f, indent=2)

    t_base = 77.0 if scenario == "D1" else (87.0 if scenario == "D2" else 47.0)
    with open(ep_dir / "stability_window.json", "w") as f:
        json.dump({
            "sample_count": 7,
            "window_records": [
                {
                    "sample_index": i + 1,
                    "sim_time": t_base + i * 0.4,
                    "timestamp_sim": t_base + i * 0.4,
                    "odom": {
                        "linear_v": 0.001,
                        "angular_v": 0.001,
                        "msg_stamp_sec": t_base + i * 0.4,
                        "recv_sim_time_sec": t_base + i * 0.4,
                        "x": 2.50,
                        "y": 0.00,
                        "yaw": 0.00,
                    },
                    "gt": {
                        "linear_v": 0.0001,
                        "angular_v": 0.0001,
                        "msg_stamp_sec": t_base + i * 0.4,
                        "recv_sim_time_sec": t_base + i * 0.4,
                        "sim_time": t_base + i * 0.4,
                        "x": 2.50,
                        "y": 0.00,
                        "yaw": 0.00,
                    },
                    "amcl": {
                        "x": 2.50,
                        "y": 0.00,
                        "yaw": 0.00,
                        "covariance_xx": 0.01,
                        "covariance_yy": 0.01,
                        "covariance_yaw": 0.01,
                        "msg_stamp_sec": t_base + i * 0.4,
                    },
                    "cmd_vel": {
                        "linear_x": 0.0,
                        "linear_y": 0.0,
                        "angular_z": 0.0,
                        "recv_sim_time_sec": t_base + i * 0.4,
                    },
                }
                for i in range(7)
            ],
        }, f, indent=2)

    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(mem_events, f, indent=2)

    with open(ep_dir / "runtime_protocol.json", "w") as f:
        json.dump({
            "protocol_version": "4.1",
            "protocol_config": {
                "navigation_task": {"episode_total_sim_budget_sec": 180.0, "goal_pose": {"x": 2.5, "y": 0.0, "yaw": 0.0}, "target_region": "north_corridor_chokepoint"},
                "decision_junction": {"pose": {"x": -2.5, "y": 0.0, "yaw": 0.0}},
                "obstacle_channel": {"doorway_bbox": {"x_min": -0.25, "x_max": 0.25, "y_min": 0.90, "y_max": 1.50}},
                "environment": {"map_version": "p2c_dualpath_world_v1"},
            },
        }, f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    with open(ep_dir / "checksums.sha256", "w") as f:
        for k, v in sorted(chks.items()):
            f.write(f"{v}  {k}\n")

    return chks


# =============================================================================
# POSITIVE-NEGATIVE PAIRED ACCEPTANCE TESTS FOR P2c PRODUCTION REPLAY & AUDIT
# =============================================================================

def test_negative_pair_1_tampered_memory_id_binding(tmp_path):
    """Negative Test 1: Mutating memory_id binding -> REPLAY FAIL (MISMATCHED_MEMORY_ID_BINDING)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    # Step 1: Base fixture must pass audit
    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True, f"Base fixture failed: {base_res['failure_reasons']}"

    # Step 2: Mutate memory_id binding in memory_events.json
    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["memory_id"] = "tampered_fake_mem_9999"
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    # Step 3: Recompute checksums to isolate semantic failure
    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISMATCHED_MEMORY_ID_BINDING" in r for r in res["failure_reasons"])


def test_negative_pair_2_tampered_goal_uuid_binding(tmp_path):
    """Negative Test 2: Mutating goal_uuid binding -> REPLAY FAIL (MISMATCHED_GOAL_UUID_BINDING)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["goal_uuid"] = "99999999-9999-9999-9999-999999999999"
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISMATCHED_GOAL_UUID_BINDING" in r for r in res["failure_reasons"])


def test_negative_pair_3_tampered_observation_id_binding(tmp_path):
    """Negative Test 3: Mutating observation_id binding -> REPLAY FAIL (MISMATCHED_OBSERVATION_ID_BINDING)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["observation_id"] = "obs_fake_nonexistent_999"
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISMATCHED_OBSERVATION_ID_BINDING" in r for r in res["failure_reasons"])


def test_negative_pair_4_duplicate_record_failure(tmp_path):
    """Negative Test 4: Duplicate RECORD_FAILURE event -> REPLAY FAIL (DUPLICATE_RECORD_FAILURE_EVENT)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    dup_event = dict(events[0])
    dup_event["event_seq"] = 2
    events.append(dup_event)
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("DUPLICATE_RECORD_FAILURE_EVENT" in r for r in res["failure_reasons"])


def test_negative_pair_5_invalidation_before_failure(tmp_path):
    """Negative Test 5: Invalidation timestamp before failure -> REPLAY FAIL (INVALIDATION_BEFORE_FAILURE_EVENT)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D2_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D2", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Mutate INVALIDATE_MEMORY sim_time to 15.0s (failure is at 20.0s)
    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    for e in events:
        if e.get("event_type") == "INVALIDATE_MEMORY":
            e["sim_time"] = 15.0
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("INVALIDATION_BEFORE_FAILURE_EVENT" in r for r in res["failure_reasons"])


def test_negative_pair_6_future_free_does_not_alter_past_decision(tmp_path):
    """Negative Test 6: Future FREE observation after decision timestamp does not alter past decision."""
    from scripts.replay_and_score_p2c import replay_p2c_episode
    from src.doorway_evaluator import create_observation_bundle, evaluate_observation_bundle

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True
    assert base_res["requested_route"] == "Path_B"

    # Insert a future FREE observation at t=100.0s (after t_dec=30.0s)
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    b_future = create_observation_bundle(
        stage="STEP_FUTURE_CLEAR",
        raw_scan_msg={"ranges": [3.0] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 100.0},
        tf_transform_dict={"translation": [-1.00, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 100.0},
        raw_costmap_msg=None,
        capture_sim_time=100.0,
        capture_wall_time=200.0,
        observation_id="obs_future_free",
    )
    b_future = evaluate_observation_bundle(b_future, current_sim_time=100.0, current_wall_time=200.0)
    snaps.append(b_future)
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    # 1. With action_result remaining Path_B, decision at t_dec=30.0s is unchanged and replayer matches Path_B
    chks_new = _recompute_episode_checksums(ep_dir)
    res_b = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res_b["policy_matched"] is True

    # 2. If runner falsely claimed Path_A at decision time, replay must REJECT due to POLICY_DECISION_MISMATCH
    with open(ep_dir / "action_result.json", "r") as f:
        data = json.load(f)
    data["requested_route"] = "Path_A"
    data["chosen_route"] = "Path_A"
    with open(ep_dir / "action_result.json", "w") as f:
        json.dump(data, f, indent=2)

    chks_new2 = _recompute_episode_checksums(ep_dir)
    res_a = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new2, checksum_file_present=True)
    assert res_a["audit_pass"] is False
    assert any("POLICY_DECISION_MISMATCH" in r for r in res_a["failure_reasons"])


def test_negative_pair_7_orphan_invalidation_without_free_evidence(tmp_path):
    """Negative Test 7: Invalidation event recorded without verified FREE perception -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D2_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D2", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Alter STEP4_CLEARANCE_VANTAGE to hit obstacle (ranges=0.4m), making recomputed perception OCCUPIED
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    for s in snaps:
        if s.get("stage") == "STEP4_CLEARANCE_VANTAGE":
            s["scan_data"]["ranges"] = [0.4] * 360
            s["perception_result"]["doorway_state"] = "FREE"  # Falsely claimed FREE
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("PERCEPTION_RECOMPUTE_MISMATCH" in r or "INVALIDATION_WITHOUT_VERIFIED_FREE_PERCEPTION" in r for r in res["failure_reasons"])


def test_negative_pair_8_tampered_bundle_costmap_summary_without_raw_roi(tmp_path):
    """Negative Test 8: Tampered costmap summary in perception_result without modifying raw ROI -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Tamper STEP2_POST_TRAVERSAL: attach a costmap_roi with lethal cells, but claim costmap_cleared=True in perception_result
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    for s in snaps:
        if s.get("stage") == "STEP2_POST_TRAVERSAL":
            s["costmap_roi"] = {
                "costmap_available": True,
                "costmap_stamp_sec": 20.0,
                "resolution_m": 0.05,
                "origin_xy": [-0.25, 0.90],
                "grid_bounds_u": [0, 9],
                "grid_bounds_v": [0, 9],
                "doorway_bbox": [-0.25, 0.25, 0.90, 1.50],
                "opening_bbox": [-0.15, 0.15, 0.95, 1.45],
                "cell_counts": {"unknown": 0, "free": 91, "inflated": 0, "lethal": 9, "opening_lethal": 9},
                "subgrid_matrix": [[100 if (4 <= u <= 6 and 4 <= v <= 6) else 0 for u in range(10)] for v in range(10)],
            }
            s["perception_result"]["costmap_summary"] = {"costmap_cleared": True, "occupied_cells": 0}
            s["perception_result"]["doorway_state"] = "FREE"  # Falsely claims FREE!
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("PERCEPTION_RECOMPUTE_MISMATCH" in r for r in res["failure_reasons"])


def test_negative_pair_9_stale_scan_timestamp_exceeds_threshold(tmp_path):
    """Negative Test 9: Scan timestamp difference from evaluation time exceeds protocol threshold (1.5s) -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Alter STEP2_POST_TRAVERSAL scan stamp to 10.0s (eval time is 20.0s, diff=10s > 1.5s)
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    for s in snaps:
        if s.get("stage") == "STEP2_POST_TRAVERSAL":
            s["scan_data"]["stamp_sec"] = 10.0
            s["tf_transform"]["stamp_sec"] = 10.0
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("STALE_SCAN_TIMESTAMP_IN_BUNDLE" in r for r in res["failure_reasons"])


def test_negative_pair_10_hash_tampered_file_without_checksum_update(tmp_path):
    """Negative Test 10: File modified without updating checksum tree -> REPLAY FAIL (HASH_MISMATCH)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    original_chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=original_chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Tamper file WITHOUT updating checksums dict
    with open(ep_dir / "action_result.json", "r") as f:
        data = json.load(f)
    data["total_distance_m"] = 999.0
    with open(ep_dir / "action_result.json", "w") as f:
        json.dump(data, f, indent=2)

    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=original_chks, checksum_file_present=True)
    assert res["checksums_verified"] is False
    assert res["audit_pass"] is False
    assert any("HASH_MISMATCH" in r for r in res["failure_reasons"])


def test_negative_pair_11_missing_decision_j0_snapshot(tmp_path):
    """Negative Test 11: Missing DECISION_J0 observation snapshot -> REPLAY FAIL (MISSING_DECISION_J0_PERCEPTION_SNAPSHOT)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Delete DECISION_J0 snapshot
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    snaps = [s for s in snaps if s.get("stage") != "DECISION_J0"]
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISSING_DECISION_J0_PERCEPTION_SNAPSHOT" in r for r in res["failure_reasons"])


def test_negative_pair_12_empty_goal_uuid_binding(tmp_path):
    """Negative Test 12: Empty goal_uuid in failure event -> REPLAY FAIL (MISSING_OR_EMPTY_EVENT_FIELD)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["goal_uuid"] = ""
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISSING_OR_EMPTY_EVENT_FIELD" in r and "goal_uuid" in r for r in res["failure_reasons"])


def test_negative_pair_13_empty_observation_id_binding(tmp_path):
    """Negative Test 13: Empty observation_id in failure event -> REPLAY FAIL (MISSING_OR_EMPTY_EVENT_FIELD)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["observation_id"] = ""
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISSING_OR_EMPTY_EVENT_FIELD" in r and "observation_id" in r for r in res["failure_reasons"])


def test_negative_pair_14_empty_memory_id_binding(tmp_path):
    """Negative Test 14: Empty memory_id in failure event -> REPLAY FAIL (MISSING_OR_EMPTY_EVENT_FIELD)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["memory_id"] = ""
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISSING_OR_EMPTY_EVENT_FIELD" in r and "memory_id" in r for r in res["failure_reasons"])


def test_negative_pair_15_empty_region_binding(tmp_path):
    """Negative Test 15: Empty region_id in failure event -> REPLAY FAIL (MISSING_OR_EMPTY_EVENT_FIELD)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["region_id"] = ""
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISSING_OR_EMPTY_EVENT_FIELD" in r and "region_id" in r for r in res["failure_reasons"])


def test_negative_pair_16_empty_map_version_binding(tmp_path):
    """Negative Test 16: Empty map_version in failure event -> REPLAY FAIL (MISSING_OR_EMPTY_EVENT_FIELD)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["map_version"] = ""
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("MISSING_OR_EMPTY_EVENT_FIELD" in r and "map_version" in r for r in res["failure_reasons"])


def test_negative_pair_17_placeholder_unknown_memory_id(tmp_path):
    """Negative Test 17: Placeholder memory_id='unknown' in failure event -> REPLAY FAIL (INVALID_PLACEHOLDER_MEMORY_ID)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["memory_id"] = "unknown"
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("INVALID_PLACEHOLDER_MEMORY_ID" in r for r in res["failure_reasons"])


def test_negative_pair_18_d2_failure_before_action_end(tmp_path):
    """Negative Test 18: D2 failure event timestamp before traversal action ends -> REPLAY FAIL (FAILURE_EVENT_BEFORE_ACTION_END)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D2_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D2", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Mutate RECORD_FAILURE sim_time to 15.0s (action ends at 20.0s)
    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[0]["sim_time"] = 15.0
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("FAILURE_EVENT_BEFORE_ACTION_END" in r for r in res["failure_reasons"])


def test_negative_pair_19_invalidation_before_free_observation(tmp_path):
    """Negative Test 19: Invalidation timestamp before clearance observation -> REPLAY FAIL (INVALIDATION_BEFORE_FREE_OBSERVATION)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D2_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D2", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Mutate INVALIDATE_MEMORY sim_time to 35.0s (clearance observation is at 40.0s, failure at 20.0s)
    with open(ep_dir / "memory_events.json", "r") as f:
        events = json.load(f)
    events[1]["sim_time"] = 35.0
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump(events, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("INVALIDATION_BEFORE_FREE_OBSERVATION" in r for r in res["failure_reasons"])


def test_negative_pair_20_duplicate_observation_id(tmp_path):
    """Negative Test 20: Duplicate observation_id across scan snapshots -> REPLAY FAIL (DUPLICATE_OBSERVATION_ID)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Set duplicate observation_id on STEP3_RETREAT_J0 to match STEP1_VANTAGE1
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    snaps[2]["observation_id"] = snaps[0]["observation_id"]
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("DUPLICATE_OBSERVATION_ID" in r for r in res["failure_reasons"])


def test_negative_pair_21_duplicate_stage_snapshot(tmp_path):
    """Negative Test 21: Duplicate stage name across scan snapshots -> REPLAY FAIL (DUPLICATE_STAGE_SNAPSHOT)."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    base_res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert base_res["audit_pass"] is True

    # Duplicate STEP1_VANTAGE1 stage name on STEP2_POST_TRAVERSAL
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    snaps[1]["stage"] = "STEP1_VANTAGE1"
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks_new = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks_new, checksum_file_present=True)
    assert res["audit_pass"] is False
    assert any("DUPLICATE_STAGE_SNAPSHOT" in r for r in res["failure_reasons"])




