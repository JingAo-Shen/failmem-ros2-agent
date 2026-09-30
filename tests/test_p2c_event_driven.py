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
    """Helper to create a complete, valid test episode directory in tmp_path."""
    ep_dir.mkdir(parents=True, exist_ok=True)
    if scenario == "D1" and method == "F":
        actions = [
            {"action_id": "hist_reach_obs_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 10.0}},
            {"action_id": "hist_attempt_chokepoint_traversal", "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_DEADLINE_EXCEEDED", "evaluation": {"timestamp_sim": 20.0}},
            {"action_id": "hist_retreat_to_j0", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 30.0}},
            {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 80.0}},
        ]
        requested_route = "Path_B"
    elif scenario == "D2" and method == "F":
        actions = [
            {"action_id": "hist_reach_obs_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 10.0}},
            {"action_id": "hist_attempt_chokepoint_traversal", "terminal_status_name": "ABORTED", "execution_outcome": "BUDGET_DEADLINE_EXCEEDED", "evaluation": {"timestamp_sim": 20.0}},
            {"action_id": "hist_retreat_to_j0", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 30.0}},
            {"action_id": "hist_probe_clearance_vantage", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 40.0}},
            {"action_id": "hist_retreat_to_j0_clear", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 50.0}},
            {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 90.0}},
        ]
        requested_route = "Path_A"
    else:
        actions = [
            {"action_id": "dec_goal", "terminal_status_name": "SUCCEEDED", "execution_outcome": "BUDGET_SUCCESS", "evaluation": {"timestamp_sim": 50.0}},
        ]
        requested_route = "Path_A"

    action_res = {
        "episode_id": ep_dir.name,
        "scenario": scenario,
        "method": method,
        "requested_route": requested_route,
        "chosen_route": requested_route,
        "total_distance_m": 12.0,
        "total_sim_time_sec": 80.0,
        "actions": actions,
    }
    with open(ep_dir / "action_result.json", "w") as f:
        json.dump(action_res, f, indent=2)

    with open(ep_dir / "trajectory.json", "w") as f:
        json.dump({
            "odom_trajectory": [{"x": -2.5 + i * 0.1, "y": 0.0, "recv_sim_time_sec": float(i)} for i in range(50)],
            "gt_trajectory": [{"x": -2.5 + i * 0.1, "y": 0.0, "sim_time": float(i)} for i in range(50)],
        }, f, indent=2)

    subgrid_blocked = [[100 if (4 <= u <= 6 and 4 <= v <= 6) else 0 for u in range(10)] for v in range(10)]
    subgrid_free = [[0 for _ in range(10)] for _ in range(10)]

    cm_snaps = [
        {
            "stage": "COSTMAP_PROBE_BLOCKED",
            "sim_time_sec": 10.0,
            "resolution_m": 0.05,
            "origin_xy": [-0.25, 0.90],
            "grid_bounds_u": [0, 9],
            "grid_bounds_v": [0, 9],
            "doorway_bbox": [-0.25, 0.25, 0.90, 1.50],
            "opening_bbox": [-0.15, 0.15, 0.95, 1.45],
            "cell_counts": {"unknown": 0, "free": 91, "inflated": 0, "lethal": 9, "opening_lethal": 9},
            "subgrid_matrix": subgrid_blocked,
        }
    ]
    if scenario == "D2":
        cm_snaps.append({
            "stage": "COSTMAP_PROBE_CLEARED",
            "sim_time_sec": 40.0,
            "resolution_m": 0.05,
            "origin_xy": [-0.25, 0.90],
            "grid_bounds_u": [0, 9],
            "grid_bounds_v": [0, 9],
            "doorway_bbox": [-0.25, 0.25, 0.90, 1.50],
            "opening_bbox": [-0.15, 0.15, 0.95, 1.45],
            "cell_counts": {"unknown": 0, "free": 100, "inflated": 0, "lethal": 0, "opening_lethal": 0},
            "subgrid_matrix": subgrid_free,
        })
    with open(ep_dir / "costmap_snapshots.json", "w") as f:
        json.dump(cm_snaps, f, indent=2)

    # Note: TF translation at vantage point [-1.00, 1.20, 0.0] facing doorway [0.00, 1.20] (yaw 0.0)
    # Range 1.0 reaches doorway bbox [-0.25, 0.25, 0.90, 1.50]
    scan_snaps = [
        {
            "stage": "STEP1_VANTAGE1",
            "sim_time_sec": 10.0,
            "has_raw_scan": True,
            "has_tf": True,
            "scan_data": {"ranges": [1.0] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 10.0},
            "tf_transform": {"translation": [-1.00, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 10.0},
            "perception_result": {"doorway_state": "OCCUPIED"},
        },
        {
            "stage": "STEP2_POST_TRAVERSAL",
            "sim_time_sec": 20.0,
            "has_raw_scan": True,
            "has_tf": True,
            "scan_data": {"ranges": [0.4] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 20.0},
            "tf_transform": {"translation": [-0.40, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 20.0},
            "perception_result": {"doorway_state": "OCCUPIED"},
        },
        {
            "stage": "DECISION_J0",
            "sim_time_sec": 30.0,
            "has_raw_scan": True,
            "has_tf": True,
            "scan_data": {"ranges": [2.5] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 30.0},
            "tf_transform": {"translation": [-2.50, 0.00, 0.0], "yaw": 0.0, "stamp_sec": 30.0},
            "perception_result": {"doorway_state": "UNKNOWN"},
        },
    ]
    if scenario == "D2":
        scan_snaps.insert(2, {
            "stage": "STEP4_CLEARANCE_VANTAGE",
            "sim_time_sec": 40.0,
            "has_raw_scan": True,
            "has_tf": True,
            "scan_data": {"ranges": [3.0] * 360, "angle_min": -3.14159, "angle_max": 3.14159, "angle_increment": 0.01745, "range_min": 0.12, "range_max": 3.5, "stamp_sec": 40.0},
            "tf_transform": {"translation": [-1.00, 1.20, 0.0], "yaw": 0.0, "stamp_sec": 40.0},
            "perception_result": {"doorway_state": "FREE"},
        })
        for s in scan_snaps:
            if s["stage"] == "DECISION_J0":
                s["sim_time_sec"] = 50.0
                s["scan_data"]["stamp_sec"] = 50.0
                s["tf_transform"]["stamp_sec"] = 50.0

    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(scan_snaps, f, indent=2)

    with open(ep_dir / "stability_window.json", "w") as f:
        json.dump({
            "sample_count": 5,
            "window_records": [
                {
                    "odom": {"linear_v": 0.01, "angular_v": 0.01},
                    "gt": {"x": 2.50, "y": 0.00, "yaw": 0.00},
                    "amcl": {"x": 2.50, "y": 0.00, "yaw": 0.00, "covariance_xx": 0.01, "covariance_yy": 0.01, "covariance_yaw": 0.01},
                }
            ],
        }, f, indent=2)

    mem_events = []
    if scenario in ["D1", "D2"]:
        mem_events.append({
            "event_type": "RECORD_FAILURE",
            "sim_time": 20.0,
            "memory_id": "mem_entry_0001",
            "region_id": "north_corridor_chokepoint",
        })
    if scenario == "D2":
        mem_events.append({
            "event_type": "INVALIDATE_MEMORY",
            "sim_time": 40.0,
            "memory_id": "mem_entry_0001",
            "region_id": "north_corridor_chokepoint",
        })
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

    return _recompute_episode_checksums(ep_dir)


# =============================================================================
# 7 NEGATIVE ACCEPTANCE TESTS FOR P2c PRODUCTION REPLAY & AUDIT
# =============================================================================

def test_negative_1_policy_route_altered_replay_fail(tmp_path):
    """Negative Test 1: Runner claimed Path B chosen, but recomputed decision selects Path A -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D0_R_ep1"
    _create_valid_test_episode_bundle(ep_dir, scenario="D0", method="R")

    # In D0_R with UNKNOWN perception at J0, Method R selects Path A.
    # Alter action_result to falsely claim Path_B was chosen.
    with open(ep_dir / "action_result.json", "r") as f:
        data = json.load(f)
    data["requested_route"] = "Path_B"
    data["chosen_route"] = "Path_B"
    with open(ep_dir / "action_result.json", "w") as f:
        json.dump(data, f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert res["policy_matched"] is False
    assert res["audit_pass"] is False
    assert any("POLICY_DECISION_MISMATCH" in r for r in res["failure_reasons"])


def test_negative_2_missing_decision_j0_snapshot_replay_fail(tmp_path):
    """Negative Test 2: Missing DECISION_J0 observation snapshot -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    # Delete DECISION_J0 snapshot
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    snaps = [s for s in snaps if s.get("stage") != "DECISION_J0"]
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert res["policy_matched"] is False or res["raw_evidence_verified"] is False
    assert res["audit_pass"] is False
    assert any("MISSING_DECISION_J0_PERCEPTION_SNAPSHOT" in r for r in res["failure_reasons"])


def test_negative_3_memory_event_without_causal_action_replay_fail(tmp_path):
    """Negative Test 3: Memory event recorded without matching causal action failure -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D0_F_ep1"
    _create_valid_test_episode_bundle(ep_dir, scenario="D0", method="F")

    # In D0, all actions succeeded. Add an orphan RECORD_FAILURE event!
    with open(ep_dir / "memory_events.json", "w") as f:
        json.dump([{"event_type": "RECORD_FAILURE", "sim_time": 10.0, "memory_id": "orphan_mem"}], f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert res["memory_lifecycle_verified"] is False
    assert res["audit_pass"] is False
    assert any("UNEXPECTED_MEMORY_EVENTS_IN_D0" in r or "ORPHAN_MEMORY_EVENT" in r for r in res["failure_reasons"])


def test_negative_4_stale_observation_timestamp_replay_fail(tmp_path):
    """Negative Test 4: Stale observation timestamp (> 2.0s difference) cannot justify failure -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    # Change STEP2_POST_TRAVERSAL timestamp to 5.0s (action failed at 20.0s -> 15s staleness)
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    for s in snaps:
        if s.get("stage") == "STEP2_POST_TRAVERSAL":
            s["sim_time_sec"] = 5.0
            s["scan_data"]["stamp_sec"] = 5.0
            s["tf_transform"]["stamp_sec"] = 5.0
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert res["memory_lifecycle_verified"] is False or res["history_valid"] is False
    assert res["audit_pass"] is False
    assert any("STALE_FAILURE_PERCEPTION_TIMESTAMP" in r for r in res["failure_reasons"])


def test_negative_5_costmap_roi_subgrid_discrepancy_replay_fail(tmp_path):
    """Negative Test 5: Subgrid cell count discrepancy (tampered lethal count vs raw subgrid) -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

    # Tamper with recorded cell_counts to say opening_lethal=0 while subgrid_matrix has 100s
    with open(ep_dir / "costmap_snapshots.json", "r") as f:
        cms = json.load(f)
    cms[0]["cell_counts"]["opening_lethal"] = 0
    cms[0]["cell_counts"]["lethal"] = 0
    with open(ep_dir / "costmap_snapshots.json", "w") as f:
        json.dump(cms, f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert res["costmap_valid"] is False
    assert res["raw_evidence_verified"] is False
    assert res["audit_pass"] is False
    assert any("COSTMAP_SUBGRID_DISCREPANCY" in r for r in res["failure_reasons"])


def test_negative_6_d2_false_clearance_replay_fail(tmp_path):
    """Negative Test 6: Obstacle still lethal in scan/costmap but runner recorded FREE -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D2_F_ep1"
    _create_valid_test_episode_bundle(ep_dir, scenario="D2", method="F")

    # Alter STEP4_CLEARANCE_VANTAGE laser scan to hit obstacle (0.4m) while recorded perception says FREE
    with open(ep_dir / "scan_snapshots.json", "r") as f:
        snaps = json.load(f)
    for s in snaps:
        if s.get("stage") == "STEP4_CLEARANCE_VANTAGE":
            s["scan_data"]["ranges"] = [0.4] * 360  # obstacle present!
            s["perception_result"]["doorway_state"] = "FREE"  # runner falsely claims FREE
    with open(ep_dir / "scan_snapshots.json", "w") as f:
        json.dump(snaps, f, indent=2)

    chks = _recompute_episode_checksums(ep_dir)
    res = replay_p2c_episode(ep_dir, fallback_thresholds={}, checksums=chks, checksum_file_present=True)
    assert res["raw_evidence_verified"] is False or res["memory_lifecycle_verified"] is False
    assert res["audit_pass"] is False
    assert any("PERCEPTION_RECOMPUTE_MISMATCH" in r or "INVALIDATION_EVENT_WITHOUT_VERIFIED_FREE_PERCEPTION" in r for r in res["failure_reasons"])


def test_negative_7_checksum_tampered_file_replay_fail(tmp_path):
    """Negative Test 7: Tampered file without matching checksums.sha256 -> REPLAY FAIL."""
    from scripts.replay_and_score_p2c import replay_p2c_episode

    ep_dir = tmp_path / "D1_F_ep1"
    original_chks = _create_valid_test_episode_bundle(ep_dir, scenario="D1", method="F")

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


