#!/usr/bin/env python3
"""FailMem Milestone P2c Independent Replay & Objective Scoring Suite.

Provides strict offline verification and re-scoring:
1. Multi-Layer Anti-Tamper & Checksum Integrity:
   - Hashes all artifacts against `checksums.sha256`. Missing checksum file or mismatch fails audit.
2. Mandatory Frozen Configuration:
   - Replay strictly loads `runtime_protocol.json` from the target run/episode directory.
   - If missing or unverified, explicitly marks the run/episode as UNVERIFIABLE.
3. Raw Event & Memory Reconstruction:
   - Instantiates clean `FailureMemoryStore` and `SpatialObservationCache`.
   - Re-traces failure memory creation on failed traversal and invalidation on verified FREE perception.
4. Trajectory & Route Classification:
   - Integrates continuous odometry trajectory using `P2cTrajectoryClassifier`.
   - Detects genuine dead-end sequence and classifies actual route without trusting runner labels.
5. Strict Budget & Physical Scoring:
   - Re-evaluates 180s total simulation budget and physical halt stability window.
   - Reports full audit table: final_goal_success, success_within_budget, history_valid, route_valid, evidence_complete, audit_pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml
from src.scoring_evaluator import (
    evaluate_navigation_episode,
    compute_disagreement_reason,
    load_scoring_rules,
)
from src.online_verifier import verify_online_arrival
from src.doorway_evaluator import (
    evaluate_doorway_clearance,
    extract_costmap_doorway_subgrid,
    project_laser_scan_rays_tf,
    recompute_costmap_subgrid_stats,
    is_finite_number,
)
from src.failure_memory import (
    FailureMemoryStore,
    MemoryState,
)
from src.p2c_pipeline import (
    P2cProtocolConfig,
    P2cTrajectoryClassifier,
    P2cPolicyDecider,
    P2cEpisodeEvaluator,
    SpatialObservationCache,
)



def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_checksums(run_dir: Path) -> Tuple[bool, Dict[str, str]]:
    """Load checksums.sha256 dictionary mapping relative path to expected sha256."""
    chk_file = run_dir / "checksums.sha256"
    if not chk_file.exists():
        return False, {}
    checksums = {}
    with open(chk_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                checksums[parts[1].strip()] = parts[0].strip()
    return True, checksums


def get_action_id(act: Dict[str, Any]) -> str:
    """Extract action_id from summary record."""
    if "action_id" in act:
        return str(act["action_id"])
    disp = act.get("dispatch", {})
    if "action_id" in disp:
        return str(disp["action_id"])
    eff = disp.get("effective_action", {})
    if "action_id" in eff:
        return str(eff["action_id"])
    norm = disp.get("normalized_action", {})
    if "action_id" in norm:
        return str(norm["action_id"])
    return ""


def replay_p2c_episode(
    ep_dir: Path,
    fallback_thresholds: Dict[str, Any],
    checksums: Dict[str, str],
    checksum_file_present: bool,
) -> Dict[str, Any]:
    """Replay and independently score a single P2c episode directory from raw evidence."""
    ep_id = ep_dir.name
    required_files = [
        "action_result.json",
        "trajectory.json",
        "costmap_snapshots.json",
        "scan_snapshots.json",
        "stability_window.json",
        "memory_events.json",
        "runtime_protocol.json",
    ]
    missing = [f for f in required_files if not (ep_dir / f).exists()]
    if missing:
        return {
            "episode_id": ep_id,
            "scenario": "UNKNOWN",
            "method": "UNKNOWN",
            "evidence_complete": False,
            "error": f"MISSING_ARTIFACTS: {missing}",
            "requested_route": "N/A",
            "actual_route": "N/A",
            "dead_end_traversals": 0,
            "task_success": False,
            "final_goal_success": False,
            "success_within_budget": False,
            "data_valid": False,
            "history_valid": False,
            "route_valid": False,
            "episode_valid": False,
            "audit_pass": False,
            "replayed_total_dist_m": 0.0,
            "failure_reasons": [f"MISSING_ARTIFACTS: {missing}"],
        }

    evidence_complete = True

    # Checksum Verification for this episode
    chk_valid = checksum_file_present
    tamper_reasons: List[str] = []
    if not checksum_file_present:
        chk_valid = False
        tamper_reasons.append("MISSING_CHECKSUMS_FILE")
    else:
        for f in required_files:
            rel_path = f"{ep_id}/{f}"
            if rel_path in checksums:
                actual_hash = compute_file_sha256(ep_dir / f)
                if actual_hash != checksums[rel_path]:
                    chk_valid = False
                    tamper_reasons.append(f"HASH_MISMATCH: {rel_path}")
            else:
                chk_valid = False
                tamper_reasons.append(f"FILE_NOT_IN_CHECKSUMS: {rel_path}")

    # Load frozen runtime protocol
    proto_file = ep_dir / "runtime_protocol.json"
    protocol_matched = True
    if proto_file.exists():
        with open(proto_file, "r", encoding="utf-8") as f:
            proto_snap = json.load(f)
        proto_cfg = P2cProtocolConfig(proto_snap.get("protocol_config", {}))
        thresholds = proto_cfg.thresholds
        total_budget_sec = proto_cfg.total_sim_budget_sec
        doorway_bbox = proto_cfg.doorway_bbox
        target_goal = proto_cfg.target_goal
        region_id = proto_cfg.chokepoint_region
        map_version = proto_cfg.map_version
    else:
        protocol_matched = False
        tamper_reasons.append("MISSING_RUNTIME_PROTOCOL_SNAPSHOT (UNVERIFIABLE)")
        thresholds = fallback_thresholds
        total_budget_sec = 180.0
        doorway_bbox = (-0.25, 0.25, 0.90, 1.50)
        target_goal = [2.50, 0.00, 0.0]
        region_id = "north_corridor_chokepoint"
        map_version = "p2c_dualpath_world_v1"

    with open(ep_dir / "action_result.json", "r", encoding="utf-8") as f:
        action_res = json.load(f)

    with open(ep_dir / "trajectory.json", "r", encoding="utf-8") as f:
        traj_data = json.load(f)

    with open(ep_dir / "costmap_snapshots.json", "r", encoding="utf-8") as f:
        costmap_snapshots = json.load(f)

    with open(ep_dir / "scan_snapshots.json", "r", encoding="utf-8") as f:
        scan_snapshots = json.load(f)

    with open(ep_dir / "stability_window.json", "r", encoding="utf-8") as f:
        window_data = json.load(f)

    with open(ep_dir / "memory_events.json", "r", encoding="utf-8") as f:
        memory_events = json.load(f)

    scenario = action_res.get("scenario", "UNKNOWN")
    method = action_res.get("method", "UNKNOWN")
    actions = action_res.get("actions", [])
    total_sim_time_sec = float(action_res.get("total_sim_time_sec", 0.0))
    history_aborted = bool(action_res.get("history_aborted", False))

    # 1. Raw Perception Recomputation from First Principles (using Immutable Observation Bundles)
    raw_evidence_verified = True
    recomputed_perceptions: Dict[str, Dict[str, Any]] = {}
    for snap in scan_snapshots:
        stg = snap.get("stage", "")
        sdata = snap.get("scan_data")
        tfdata = snap.get("tf_transform")
        cm_roi = snap.get("costmap_roi")
        if not sdata or not tfdata or not snap.get("has_raw_scan", False) or not snap.get("has_tf", False):
            raw_evidence_verified = False
            tamper_reasons.append(f"MISSING_RAW_SCAN_OR_TF ({stg})")
            continue

        ranges = sdata.get("ranges", [])
        amin = float(sdata.get("angle_min", -3.14159))
        ainc = float(sdata.get("angle_increment", 0.0087))
        rmin = float(sdata.get("range_min", 0.12))
        rmax = float(sdata.get("range_max", 3.50))
        t_trans = tfdata.get("translation", [0.0, 0.0, 0.0])
        t_yaw = float(tfdata.get("yaw", 0.0))

        tf_stamp = float(tfdata.get("stamp_sec", 0.0)) if tfdata.get("stamp_sec") is not None else None
        scan_stamp = float(sdata.get("stamp_sec", 0.0)) if sdata.get("stamp_sec") is not None else None
        capture_sim = float(snap.get("capture_sim_time_sec", snap.get("sim_time_sec", 0.0)))
        eval_sim = float(snap.get("evaluation_sim_time_sec", snap.get("sim_time_sec", capture_sim)))

        # Check timestamp integrity
        if tf_stamp is None or scan_stamp is None or capture_sim <= 0 or eval_sim <= 0:
            raw_evidence_verified = False
            tamper_reasons.append(f"MISSING_OR_INVALID_BUNDLE_TIMESTAMPS ({stg})")
            continue

        if abs(eval_sim - scan_stamp) > 1.5:
            raw_evidence_verified = False
            tamper_reasons.append(f"STALE_SCAN_TIMESTAMP_IN_BUNDLE ({stg}: eval={eval_sim:.2f}s vs scan={scan_stamp:.2f}s, diff={abs(eval_sim-scan_stamp):.2f}s > 1.5s)")

        if abs(tf_stamp - scan_stamp) > 0.8:
            raw_evidence_verified = False
            tamper_reasons.append(f"TF_SCAN_TIME_MISMATCH ({stg}: tf={tf_stamp:.2f}s vs scan={scan_stamp:.2f}s, diff={abs(tf_stamp-scan_stamp):.2f}s > 0.8s)")

        # Recompute costmap summary directly from raw ROI subgrid matrix (ZERO trust in recorded perception_result.costmap_summary)
        recomputed_costmap_summary = None
        if cm_roi and cm_roi.get("costmap_available") and cm_roi.get("subgrid_matrix"):
            recomp_cm = recompute_costmap_subgrid_stats(
                subgrid_matrix=cm_roi.get("subgrid_matrix", []),
                grid_bounds_u=cm_roi.get("grid_bounds_u", []),
                grid_bounds_v=cm_roi.get("grid_bounds_v", []),
                resolution_m=float(cm_roi.get("resolution_m", 0.05)),
                origin_xy=cm_roi.get("origin_xy", [-5.0, -5.0]),
                opening_bbox=tuple(cm_roi.get("opening_bbox", (-0.15, 0.15, 0.95, 1.45))),
            )
            if not recomp_cm.get("valid"):
                raw_evidence_verified = False
                tamper_reasons.append(f"INVALID_BUNDLE_COSTMAP_ROI ({stg})")
            else:
                counts = recomp_cm.get("cell_counts", {})
                rec_counts = cm_roi.get("cell_counts", {})
                for k in ["unknown", "free", "inflated", "lethal", "opening_lethal"]:
                    if rec_counts.get(k) != counts.get(k):
                        raw_evidence_verified = False
                        tamper_reasons.append(f"COSTMAP_BUNDLE_ROI_DISCREPANCY ({stg}: {k} recorded={rec_counts.get(k)} vs recomputed={counts.get(k)})")

                total_cells = counts.get("unknown", 0) + counts.get("free", 0) + counts.get("inflated", 0) + counts.get("lethal", 0)
                costmap_cleared = (total_cells > 0 and counts.get("unknown", 0) == 0 and counts.get("opening_lethal", 0) == 0)
                recomputed_costmap_summary = {
                    "status": "VALID",
                    "error": None,
                    "total_cells": total_cells,
                    "unknown_cells": counts.get("unknown", 0),
                    "occupied_cells": counts.get("lethal", 0),
                    "opening_lethal_cells": counts.get("opening_lethal", 0),
                    "free_cells": counts.get("free", 0),
                    "costmap_cleared": costmap_cleared,
                    "stamp_sec": cm_roi.get("costmap_stamp_sec"),
                }

        recomp_res = evaluate_doorway_clearance(
            ranges=ranges,
            angle_min=amin,
            angle_increment=ainc,
            range_min=rmin,
            range_max=rmax,
            tf_translation=t_trans,
            tf_yaw=t_yaw,
            tf_stamp_sec=tf_stamp,
            scan_stamp_sec=scan_stamp,
            current_sim_time=eval_sim,
            doorway_bbox=doorway_bbox,
            costmap_data_summary=recomputed_costmap_summary,
            max_scan_staleness_sec=1.5,
        )

        recomputed_perceptions[stg] = recomp_res

        recorded_st = snap.get("perception_result", {}).get("doorway_state")
        recomp_st = recomp_res.get("doorway_state")
        if recorded_st != recomp_st:
            raw_evidence_verified = False
            tamper_reasons.append(f"PERCEPTION_RECOMPUTE_MISMATCH ({stg}: recorded={recorded_st}, recomputed={recomp_st})")

    # 2. Costmap Snapshots Verification from Raw Subgrid
    costmap_valid = True
    for cm in costmap_snapshots:
        stg = cm.get("stage", "")
        subgrid_mat = cm.get("subgrid_matrix")
        u_bounds = cm.get("grid_bounds_u")
        v_bounds = cm.get("grid_bounds_v")
        res_m = float(cm.get("resolution_m", 0.05))
        orig = cm.get("origin_xy", [-5.0, -5.0])
        op_bbox = tuple(cm.get("opening_bbox", [-0.15, 0.15, 0.95, 1.45]))

        if not subgrid_mat or not u_bounds or not v_bounds:
            costmap_valid = False
            raw_evidence_verified = False
            tamper_reasons.append(f"MISSING_COSTMAP_SUBGRID_MATRIX ({stg})")
            continue

        recomp_cm = recompute_costmap_subgrid_stats(
            subgrid_matrix=subgrid_mat,
            grid_bounds_u=u_bounds,
            grid_bounds_v=v_bounds,
            resolution_m=res_m,
            origin_xy=orig,
            opening_bbox=op_bbox,
        )
        if not recomp_cm.get("valid"):
            costmap_valid = False
            raw_evidence_verified = False
            tamper_reasons.append(f"INVALID_COSTMAP_SUBGRID ({stg})")
            continue

        rec_counts = cm.get("cell_counts", {})
        recomp_counts = recomp_cm.get("cell_counts", {})
        for k in ["unknown", "free", "inflated", "lethal", "opening_lethal"]:
            if rec_counts.get(k) != recomp_counts.get(k):
                costmap_valid = False
                raw_evidence_verified = False
                tamper_reasons.append(f"COSTMAP_SUBGRID_DISCREPANCY ({stg}: {k} recorded={rec_counts.get(k)} vs recomputed={recomp_counts.get(k)})")

        op_lethal = recomp_counts.get("opening_lethal", 0)
        if "PROBE_BLOCKED" in stg and op_lethal == 0:
            costmap_valid = False
            tamper_reasons.append(f"COSTMAP_BLOCKAGE_STATE_CONTRADICTION ({stg}: expected lethal obstacle in opening)")
        elif "PROBE_CLEARED" in stg and op_lethal > 0:
            costmap_valid = False
            tamper_reasons.append(f"COSTMAP_BLOCKAGE_STATE_CONTRADICTION ({stg}: expected cleared opening but opening_lethal={op_lethal})")

    # 3. Decision Time & Observation Cache Replay
    dec_snap = next((s for s in scan_snapshots if s.get("stage") == "DECISION_J0"), None)
    t_dec = None
    if not history_aborted:
        if not dec_snap or "DECISION_J0" not in recomputed_perceptions:
            raw_evidence_verified = False
            tamper_reasons.append("MISSING_DECISION_J0_PERCEPTION_SNAPSHOT")
        else:
            t_dec_val = dec_snap.get("evaluation_sim_time_sec", dec_snap.get("sim_time_sec"))
            if not is_finite_number(t_dec_val) or float(t_dec_val) <= 0:
                tamper_reasons.append("MISSING_OR_INVALID_DECISION_J0_TIMESTAMP")
            else:
                t_dec = float(t_dec_val)

    replayed_cache = SpatialObservationCache()
    if t_dec is not None:
        prior_snaps = [s for s in scan_snapshots if s.get("stage") != "DECISION_J0" and is_finite_number(s.get("evaluation_sim_time_sec", s.get("sim_time_sec"))) and float(s.get("evaluation_sim_time_sec", s.get("sim_time_sec"))) <= t_dec]
        prior_snaps.sort(key=lambda s: float(s.get("evaluation_sim_time_sec", s.get("sim_time_sec", 0.0))))
        for s in prior_snaps:
            stg = s.get("stage", "")
            recomp = recomputed_perceptions.get(stg, {})
            st = recomp.get("doorway_state")
            ts = float(s.get("evaluation_sim_time_sec", s.get("sim_time_sec", 0.0)))
            if st in ["OCCUPIED", "FREE"] and ts > 0:
                replayed_cache.update_observation(region_id, st, ts, recomp)

    # 4. Strict Chronological Memory Lifecycle & History Audit
    memory_lifecycle_verified = True
    replayed_fail_store = FailureMemoryStore()
    m1_suppressed = False
    history_valid = not history_aborted
    history_reasons: List[str] = []

    if history_aborted:
        history_reasons.append("HISTORY_ABORTED_DUE_TO_INCOMPLETE_OR_INVALID_EVIDENCE")
        if action_res.get("decision_dispatches", 0) > 0:
            history_valid = False
            tamper_reasons.append("DISPATCHED_GOALS_AFTER_INVALID_HISTORY")

    # Step 1: Check memory_events timestamps ordering
    prev_t = -1.0
    for ev in memory_events:
        t_ev = ev.get("sim_time")
        if not is_finite_number(t_ev) or float(t_ev) <= 0:
            memory_lifecycle_verified = False
            tamper_reasons.append("MISSING_OR_INVALID_MEMORY_EVENT_TIMESTAMP")
        elif float(t_ev) < prev_t:
            memory_lifecycle_verified = False
            tamper_reasons.append(f"UNSORTED_OR_PREMATURE_MEMORY_EVENT (time {t_ev} < {prev_t})")
        prev_t = float(t_ev) if is_finite_number(t_ev) else prev_t

    # Step 2: Event checks per scenario
    if scenario == "D0":
        if len(memory_events) > 0:
            memory_lifecycle_verified = False
            tamper_reasons.append("UNEXPECTED_MEMORY_EVENTS_IN_D0")

    elif scenario == "D1":
        rec_events = [e for e in memory_events if e.get("event_type") == "RECORD_FAILURE"]
        inv_events = [e for e in memory_events if e.get("event_type") == "INVALIDATE_MEMORY"]
        other_events = [e for e in memory_events if e.get("event_type") not in ["RECORD_FAILURE", "INVALIDATE_MEMORY"]]

        if len(inv_events) > 0:
            memory_lifecycle_verified = False
            tamper_reasons.append("UNEXPECTED_INVALIDATION_IN_D1")
        if len(other_events) > 0:
            memory_lifecycle_verified = False
            tamper_reasons.append(f"UNKNOWN_MEMORY_EVENT_TYPE ({[e.get('event_type') for e in other_events]})")
        if len(rec_events) > 1:
            memory_lifecycle_verified = False
            tamper_reasons.append(f"DUPLICATE_RECORD_FAILURE_EVENT (found {len(rec_events)} events in D1)")

        if not history_aborted:
            act_v1 = next((a for a in actions if get_action_id(a) == "hist_reach_obs_vantage"), None)
            act_tr1 = next((a for a in actions if get_action_id(a) == "hist_attempt_chokepoint_traversal"), None)
            act_r1 = next((a for a in actions if get_action_id(a) == "hist_retreat_to_j0"), None)

            if not (act_v1 and act_tr1 and act_r1):
                history_valid = False
                memory_lifecycle_verified = False
                history_reasons.append("MISSING_D1_HISTORY_ACTIONS")
            else:
                v1_ok = (act_v1.get("terminal_status_name") == "SUCCEEDED" and act_v1.get("execution_outcome") == "BUDGET_SUCCESS")
                tr1_failed = (act_tr1.get("execution_outcome") in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"] or act_tr1.get("terminal_status_name") in ["ABORTED", "CANCELED"])
                r1_ok = (act_r1.get("terminal_status_name") == "SUCCEEDED" and act_r1.get("execution_outcome") == "BUDGET_SUCCESS")

                t_tr1 = act_tr1.get("timestamp_sim") or act_tr1.get("evaluation", {}).get("timestamp_sim")
                t_tr1_start = act_tr1.get("timestamp_sim_start", t_tr1)
                real_goal_uuid = str(act_tr1.get("dispatch", {}).get("goal_uuid", ""))

                post_tr_snap = next((s for s in scan_snapshots if s.get("stage") == "STEP2_POST_TRAVERSAL"), None)
                v1_snap = next((s for s in scan_snapshots if s.get("stage") == "STEP1_VANTAGE1"), None)
                post_tr_recomp = recomputed_perceptions.get("STEP2_POST_TRAVERSAL", {})
                v1_recomp = recomputed_perceptions.get("STEP1_VANTAGE1", {})

                linked_snap = post_tr_snap if (post_tr_recomp.get("doorway_state") in ["OCCUPIED", "FREE"]) else v1_snap
                linked_recomp = post_tr_recomp if (post_tr_recomp.get("doorway_state") in ["OCCUPIED", "FREE"]) else v1_recomp
                probe_occ_st = linked_recomp.get("doorway_state")
                expected_obs_id = str(linked_snap.get("observation_id", "")) if linked_snap else ""

                if not (v1_ok and tr1_failed and r1_ok and probe_occ_st == "OCCUPIED"):
                    history_valid = False
                    history_reasons.append(f"D1_OUTCOME_MISMATCH (v1={v1_ok}, tr1_fail={tr1_failed}, r1={r1_ok}, probe_occ={probe_occ_st})")

                if len(rec_events) == 0:
                    memory_lifecycle_verified = False
                    tamper_reasons.append("MISSING_RECORD_FAILURE_IN_MEMORY_EVENTS")
                else:
                    rec_ev = rec_events[0]
                    ev_failed_action = str(rec_ev.get("failed_action_id", ""))
                    ev_goal_uuid = str(rec_ev.get("goal_uuid", ""))
                    ev_obs_id = str(rec_ev.get("observation_id", ""))
                    ev_mem_id = str(rec_ev.get("memory_id", ""))
                    ev_region = str(rec_ev.get("region_id", ""))
                    ev_map_ver = str(rec_ev.get("map_version", ""))
                    ev_time = float(rec_ev.get("sim_time", 0.0))

                    if ev_failed_action and ev_failed_action != "hist_attempt_chokepoint_traversal":
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_FAILED_ACTION_BINDING (expected 'hist_attempt_chokepoint_traversal', got '{ev_failed_action}')")
                    if real_goal_uuid and ev_goal_uuid and ev_goal_uuid != real_goal_uuid:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_GOAL_UUID_BINDING (expected '{real_goal_uuid}', got '{ev_goal_uuid}')")
                    if expected_obs_id and ev_obs_id and ev_obs_id != expected_obs_id:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_OBSERVATION_ID_BINDING (expected '{expected_obs_id}', got '{ev_obs_id}')")
                    if ev_region and ev_region != region_id:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_REGION_BINDING (expected '{region_id}', got '{ev_region}')")
                    if ev_map_ver and ev_map_ver != map_version:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_MAP_VERSION_BINDING (expected '{map_version}', got '{ev_map_ver}')")

                    t_start_val = float(t_tr1_start) if is_finite_number(t_tr1_start) else (float(t_tr1) if t_tr1 else 0.0)
                    t_end_val = float(t_tr1) if t_tr1 else t_start_val
                    if ev_time < (t_start_val - 2.0) or ev_time > (t_end_val + 2.0):
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"STALE_FAILURE_EVENT_TIMESTAMP (ev_time={ev_time:.2f}s outside action window [{t_start_val:.2f}s, {t_end_val:.2f}s])")

                    entry = replayed_fail_store.record_failure(
                        goal=target_goal,
                        region_id=region_id,
                        failure_reason="BLOCKED_AT_DOORWAY",
                        sim_time=ev_time,
                        failed_action_id=ev_failed_action or "hist_attempt_chokepoint_traversal",
                        failure_evidence_id=ev_obs_id or expected_obs_id,
                        failure_evidence=linked_recomp,
                        map_version=map_version,
                        metadata={"goal_uuid": ev_goal_uuid or real_goal_uuid},
                    )
                    if not entry or entry.state != MemoryState.ACTIVE:
                        memory_lifecycle_verified = False
                        tamper_reasons.append("FAILURE_MEMORY_RECORDING_FAILED")
                    elif ev_mem_id and entry.memory_id != ev_mem_id and ev_mem_id != "unknown":
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_MEMORY_ID_BINDING (reconstructed '{entry.memory_id}' vs recorded '{ev_mem_id}')")
                    m1_suppressed = True

    elif scenario == "D2":
        rec_events = [e for e in memory_events if e.get("event_type") == "RECORD_FAILURE"]
        inv_events = [e for e in memory_events if e.get("event_type") == "INVALIDATE_MEMORY"]
        other_events = [e for e in memory_events if e.get("event_type") not in ["RECORD_FAILURE", "INVALIDATE_MEMORY"]]

        if len(other_events) > 0:
            memory_lifecycle_verified = False
            tamper_reasons.append(f"UNKNOWN_MEMORY_EVENT_TYPE ({[e.get('event_type') for e in other_events]})")
        if len(rec_events) != 1:
            memory_lifecycle_verified = False
            tamper_reasons.append(f"INVALID_RECORD_FAILURE_COUNT_IN_D2 (expected 1, got {len(rec_events)})")
        if len(inv_events) != 1:
            memory_lifecycle_verified = False
            tamper_reasons.append(f"INVALID_INVALIDATE_EVENT_COUNT_IN_D2 (expected 1, got {len(inv_events)})")

        if len(rec_events) == 1 and len(inv_events) == 1:
            t_rec = float(rec_events[0].get("sim_time", 0.0))
            t_inv = float(inv_events[0].get("sim_time", 0.0))
            if t_inv <= t_rec:
                memory_lifecycle_verified = False
                tamper_reasons.append(f"INVALIDATION_BEFORE_FAILURE_EVENT (invalidation at {t_inv:.2f}s <= failure at {t_rec:.2f}s)")

        if not history_aborted:
            act_v1 = next((a for a in actions if get_action_id(a) == "hist_reach_obs_vantage"), None)
            act_tr1 = next((a for a in actions if get_action_id(a) == "hist_attempt_chokepoint_traversal"), None)
            act_r1 = next((a for a in actions if get_action_id(a) == "hist_retreat_to_j0"), None)

            act_p2 = next((a for a in actions if get_action_id(a) == "hist_probe_clearance_vantage"), None)
            act_r2 = next((a for a in actions if get_action_id(a) == "hist_retreat_to_j0_clear"), None)
            clr_snap = next((s for s in scan_snapshots if s.get("stage") == "STEP4_CLEARANCE_VANTAGE"), None)
            clear_recomp = recomputed_perceptions.get("STEP4_CLEARANCE_VANTAGE", {})
            clear_st = clear_recomp.get("doorway_state")

            if not (act_v1 and act_tr1 and act_r1 and act_p2 and act_r2 and clr_snap):
                history_valid = False
                memory_lifecycle_verified = False
                history_reasons.append("MISSING_D2_HISTORY_ACTIONS_OR_CLEARANCE_PERCEPTION")
            else:
                v1_ok = (act_v1.get("terminal_status_name") == "SUCCEEDED" and act_v1.get("execution_outcome") == "BUDGET_SUCCESS")
                tr1_failed = (act_tr1.get("execution_outcome") in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"] or act_tr1.get("terminal_status_name") in ["ABORTED", "CANCELED"])
                r1_ok = (act_r1.get("terminal_status_name") == "SUCCEEDED" and act_r1.get("execution_outcome") == "BUDGET_SUCCESS")
                p2_ok = (act_p2.get("terminal_status_name") == "SUCCEEDED" and act_p2.get("execution_outcome") == "BUDGET_SUCCESS")
                r2_ok = (act_r2.get("terminal_status_name") == "SUCCEEDED" and act_r2.get("execution_outcome") == "BUDGET_SUCCESS")

                t_tr1 = act_tr1.get("timestamp_sim") or act_tr1.get("evaluation", {}).get("timestamp_sim")
                t_tr1_start = act_tr1.get("timestamp_sim_start", t_tr1)
                real_goal_uuid = str(act_tr1.get("dispatch", {}).get("goal_uuid", ""))

                t_p2 = act_p2.get("timestamp_sim") or act_p2.get("evaluation", {}).get("timestamp_sim")
                t_p2_start = act_p2.get("timestamp_sim_start", t_p2)
                t_clr_p = float(clr_snap.get("evaluation_sim_time_sec", clr_snap.get("sim_time_sec", 0.0)))
                expected_clear_obs_id = str(clr_snap.get("observation_id", ""))

                post_tr_snap = next((s for s in scan_snapshots if s.get("stage") == "STEP2_POST_TRAVERSAL"), None)
                v1_snap = next((s for s in scan_snapshots if s.get("stage") == "STEP1_VANTAGE1"), None)
                post_tr_recomp = recomputed_perceptions.get("STEP2_POST_TRAVERSAL", {})
                v1_recomp = recomputed_perceptions.get("STEP1_VANTAGE1", {})
                linked_snap = post_tr_snap if (post_tr_recomp.get("doorway_state") in ["OCCUPIED", "FREE"]) else v1_snap
                linked_recomp = post_tr_recomp if (post_tr_recomp.get("doorway_state") in ["OCCUPIED", "FREE"]) else v1_recomp
                probe_occ_st = linked_recomp.get("doorway_state")
                expected_fail_obs_id = str(linked_snap.get("observation_id", "")) if linked_snap else ""

                if not (v1_ok and tr1_failed and r1_ok and probe_occ_st == "OCCUPIED" and p2_ok and r2_ok and clear_st == "FREE"):
                    history_valid = False
                    history_reasons.append(f"D2_OUTCOME_MISMATCH (tr1_fail={tr1_failed}, p2={p2_ok}, r2={r2_ok}, clear_st={clear_st})")

                # Replay failure first
                if len(rec_events) >= 1:
                    rec_ev = rec_events[0]
                    ev_failed_action = str(rec_ev.get("failed_action_id", ""))
                    ev_goal_uuid = str(rec_ev.get("goal_uuid", ""))
                    ev_obs_id = str(rec_ev.get("observation_id", ""))
                    ev_mem_id = str(rec_ev.get("memory_id", ""))
                    ev_time = float(rec_ev.get("sim_time", 0.0))

                    if ev_failed_action and ev_failed_action != "hist_attempt_chokepoint_traversal":
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_FAILED_ACTION_BINDING (expected 'hist_attempt_chokepoint_traversal', got '{ev_failed_action}')")
                    if real_goal_uuid and ev_goal_uuid and ev_goal_uuid != real_goal_uuid:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_GOAL_UUID_BINDING (expected '{real_goal_uuid}', got '{ev_goal_uuid}')")
                    if expected_fail_obs_id and ev_obs_id and ev_obs_id != expected_fail_obs_id:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_OBSERVATION_ID_BINDING (expected '{expected_fail_obs_id}', got '{ev_obs_id}')")

                    entry = replayed_fail_store.record_failure(
                        goal=target_goal,
                        region_id=region_id,
                        failure_reason="BLOCKED_AT_DOORWAY",
                        sim_time=ev_time,
                        failed_action_id=ev_failed_action or "hist_attempt_chokepoint_traversal",
                        failure_evidence_id=ev_obs_id or expected_fail_obs_id,
                        failure_evidence=linked_recomp,
                        map_version=map_version,
                        metadata={"goal_uuid": ev_goal_uuid or real_goal_uuid},
                    )
                    if not entry or entry.state != MemoryState.ACTIVE:
                        memory_lifecycle_verified = False
                        tamper_reasons.append("FAILURE_MEMORY_RECORDING_FAILED")
                    elif ev_mem_id and entry.memory_id != ev_mem_id and ev_mem_id != "unknown":
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_MEMORY_ID_BINDING (reconstructed '{entry.memory_id}' vs recorded '{ev_mem_id}')")

                # Replay invalidation
                if len(inv_events) >= 1:
                    inv_ev = inv_events[0]
                    inv_mem_id = str(inv_ev.get("memory_id", ""))
                    inv_obs_id = str(inv_ev.get("invalidated_by_observation_id", ""))
                    inv_time = float(inv_ev.get("sim_time", 0.0))

                    if expected_clear_obs_id and inv_obs_id and inv_obs_id != expected_clear_obs_id:
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"MISMATCHED_INVALIDATION_OBS_BINDING (expected '{expected_clear_obs_id}', got '{inv_obs_id}')")

                    if clear_st != "FREE":
                        memory_lifecycle_verified = False
                        tamper_reasons.append("INVALIDATION_WITHOUT_VERIFIED_FREE_PERCEPTION")

                    t_p2_s = float(t_p2_start) if is_finite_number(t_p2_start) else float(t_p2)
                    t_p2_e = float(t_p2)
                    if inv_time < (t_p2_s - 2.0) or inv_time > (t_p2_e + 2.0):
                        memory_lifecycle_verified = False
                        tamper_reasons.append(f"STALE_CLEARANCE_PERCEPTION_TIMESTAMP (inv_time={inv_time:.2f}s outside action window [{t_p2_s:.2f}s, {t_p2_e:.2f}s])")

                    ev_check = dict(clear_recomp)
                    ev_check["timestamp_sim"] = inv_time
                    inv_res = replayed_fail_store.evaluate_perception_for_invalidation(
                        perception_evidence=ev_check,
                        sim_time=inv_time,
                        evidence_id=inv_obs_id or expected_clear_obs_id,
                        map_version=map_version,
                        region_id=region_id,
                    )
                    if not inv_res or len(inv_res) == 0:
                        memory_lifecycle_verified = False
                        tamper_reasons.append("INVALIDATION_EXECUTION_FAILED (no memory entry invalidated)")
                    else:
                        inv_entry = inv_res[0]
                        if inv_entry.state != MemoryState.INVALIDATED:
                            memory_lifecycle_verified = False
                            tamper_reasons.append(f"INVALIDATION_STATE_TRANSITION_FAILED (entry state is {inv_entry.state})")
                        if inv_mem_id and inv_entry.memory_id != inv_mem_id and inv_mem_id != "unknown":
                            memory_lifecycle_verified = False
                            tamper_reasons.append(f"MISMATCHED_INVALIDATED_MEMORY_ID (reconstructed '{inv_entry.memory_id}' vs recorded '{inv_mem_id}')")

    if scenario == "D0" and len(memory_events) > 0:
        memory_lifecycle_verified = False
        tamper_reasons.append("UNEXPECTED_MEMORY_EVENTS_IN_D0")
    if scenario == "D1" and any(e.get("event_type") == "INVALIDATE_MEMORY" for e in memory_events):
        memory_lifecycle_verified = False
        tamper_reasons.append("UNEXPECTED_INVALIDATION_IN_D1")

    # 5. Trajectory Continuity & Classification
    odom_samples = traj_data.get("odom_trajectory", [])
    gt_samples = traj_data.get("gt_trajectory", [])
    dec_gt_samples = traj_data.get("decision_gt_trajectory", [])
    dec_odom_samples = traj_data.get("decision_odom_trajectory", [])

    samples_for_dist = odom_samples if odom_samples else gt_samples
    samples_for_route = dec_gt_samples or gt_samples or dec_odom_samples or odom_samples
    samples_for_dead_ends = dec_gt_samples or dec_odom_samples or gt_samples or odom_samples

    replayed_total_dist, jump_count = P2cTrajectoryClassifier.integrate_distance(samples_for_dist)
    actual_route = P2cTrajectoryClassifier.classify_actual_route(samples_for_route)
    replayed_dead_ends = P2cTrajectoryClassifier.classify_dead_end_traversals(samples_for_dead_ends)

    # 6. Policy Decision Replay Verification
    policy_matched = True
    if not history_aborted:
        dec_obs = recomputed_perceptions.get("DECISION_J0")
        if not dec_obs:
            policy_matched = False
            tamper_reasons.append("MISSING_DECISION_J0_PERCEPTION_SNAPSHOT")
        else:
            replayed_route, replayed_rationale, _ = P2cPolicyDecider.decide_route(
                method=method,
                live_obs=dec_obs,
                cache=replayed_cache,
                fail_store=replayed_fail_store,
                m1_suppressed=m1_suppressed,
                target_goal=target_goal,
                region_id=region_id,
                map_version=map_version,
            )
            rec_chosen = action_res.get("requested_route") or action_res.get("chosen_route")
            if not rec_chosen or not rec_chosen.startswith(replayed_route):
                policy_matched = False
                tamper_reasons.append(f"POLICY_DECISION_MISMATCH (online={rec_chosen}, replayed={replayed_route})")

    # 7. Physical Goal Arrival Re-scoring & Final Unified Audit Verdict
    last_action = actions[-1] if actions else {}
    last_summary = last_action
    window_records = window_data.get("window_records", [])
    last_gt = window_records[-1].get("gt") if window_records else (traj_data.get("gt_trajectory", [])[-1] if traj_data.get("gt_trajectory") else None)
    last_amcl = window_records[-1].get("amcl") if window_records else None

    eval_dict = evaluate_navigation_episode(
        target_goal=target_goal,
        nav2_status=last_summary.get("terminal_status_name", "UNKNOWN"),
        final_gt=last_gt,
        final_amcl=last_amcl,
        stability_samples=window_records,
        thresholds=thresholds,
        watchdog_triggered=False,
        safety_intervention=last_summary.get("safety_intervention", False),
        execution_outcome=last_summary.get("execution_outcome", "UNKNOWN"),
        deadline_exceeded=last_summary.get("deadline_exceeded", False),
        failure_reason=last_summary.get("failure_reason"),
    )

    eval_report = P2cEpisodeEvaluator.evaluate_episode(
        scenario=scenario,
        method=method,
        actions=actions,
        total_sim_time_sec=total_sim_time_sec,
        total_budget_sec=total_budget_sec,
        physical_eval_dict=eval_dict,
        odom_samples=odom_samples,
        costmap_snapshots=costmap_snapshots,
        checksums_verified=chk_valid,
        protocol_hash_match=protocol_matched,
        evidence_complete=evidence_complete,
        history_aborted=history_aborted,
        raw_evidence_verified=raw_evidence_verified,
        memory_lifecycle_verified=memory_lifecycle_verified,
        policy_matched=policy_matched,
        costmap_valid=costmap_valid,
        tamper_reasons=tamper_reasons,
    )

    task_success = eval_report["task_success"]
    success_within_budget = eval_report["success_within_budget"]
    route_valid = eval_report["route_valid"]
    episode_valid = eval_report["episode_valid"]
    audit_pass = eval_report["audit_pass"]
    data_valid = eval_report["data_valid"]

    failure_reasons = list(tamper_reasons) + list(history_reasons)
    if not success_within_budget:
        failure_reasons.append(f"TOTAL_BUDGET_EXCEEDED ({total_sim_time_sec:.1f}s > {total_budget_sec:.1f}s)")
    if not task_success:
        failure_reasons.append("PHYSICAL_ARRIVAL_FAILED")
    if not route_valid:
        failure_reasons.append(f"ROUTE_INVALID (jumps={jump_count}, costmap_valid={costmap_valid})")

    return {
        "episode_id": ep_id,
        "scenario": scenario,
        "method": method,
        "requested_route": action_res.get("requested_route", action_res.get("chosen_route")),
        "actual_route": actual_route,
        "dead_end_traversals": replayed_dead_ends,
        "recorded_total_dist_m": action_res.get("total_distance_m", 0.0),
        "replayed_total_dist_m": replayed_total_dist,
        "distance_discrepancy_m": round(abs(action_res.get("total_distance_m", 0.0) - replayed_total_dist), 3),
        "total_sim_time_sec": total_sim_time_sec,
        "total_budget_sec": total_budget_sec,
        "task_success": task_success,
        "final_goal_success": task_success,
        "success_within_budget": success_within_budget,
        "data_valid": data_valid,
        "history_valid": history_valid,
        "route_valid": route_valid,
        "costmap_valid": costmap_valid,
        "evidence_complete": evidence_complete,
        "raw_evidence_verified": raw_evidence_verified,
        "memory_lifecycle_verified": memory_lifecycle_verified,
        "policy_matched": policy_matched,
        "checksums_verified": chk_valid,
        "protocol_matched": protocol_matched,
        "episode_valid": episode_valid,
        "audit_pass": audit_pass,
        "history_aborted": history_aborted,
        "failure_reasons": failure_reasons,
    }



def replay_p2c_run(run_dir: Path, protocol_path: Optional[Path] = None) -> Dict[str, Any]:
    """Replay and audit an entire P2c run directory."""
    chk_present, checksums = load_checksums(run_dir)

    proto_path = protocol_path or (run_dir / "protocol.yaml")
    if not proto_path.exists() and Path("configs/p2c_pilot_protocol.yaml").exists():
        proto_path = Path("configs/p2c_pilot_protocol.yaml")

    with open(proto_path, "r", encoding="utf-8") as f:
        proto_cfg_dict = yaml.safe_load(f)

    scoring_rules_path = Path("configs/scoring_rules.yaml")
    scoring_rules = load_scoring_rules(str(scoring_rules_path)) if scoring_rules_path.exists() else {}
    fallback_thresholds = proto_cfg_dict.get("scoring_thresholds", scoring_rules.get("thresholds", {}))

    ep_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir() and any(k in d.name for k in ["D0_", "D1_", "D2_"])])

    ep_results: List[Dict[str, Any]] = []
    for ep_dir in ep_dirs:
        ep_res = replay_p2c_episode(ep_dir, fallback_thresholds, checksums, chk_present)
        ep_results.append(ep_res)

    all_audit_pass = all(r.get("audit_pass", False) for r in ep_results) if ep_results else False
    all_episodes_valid = all(r.get("episode_valid", False) for r in ep_results) if ep_results else False

    summary = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "replay_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "checksum_file_present": chk_present,
        "total_episodes_replayed": len(ep_results),
        "all_episodes_valid": all_episodes_valid,
        "all_audit_pass": all_audit_pass,
        "episodes": ep_results,
    }

    with open(run_dir / "p2c_replay_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    parser = argparse.ArgumentParser(description="FailMem Milestone P2c Offline Replay & Objective Scoring")
    parser.add_argument("run_dir", help="Path to P2c run directory (or evidence parent)")
    parser.add_argument("--protocol", default="configs/p2c_pilot_protocol.yaml", help="Path to protocol YAML")
    args = parser.parse_args()

    target_dir = Path(args.run_dir)
    if not target_dir.exists():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    if (target_dir / "p2c_pilot_summary.json").exists() or any(k in target_dir.name for k in ["p2c_pilot_"]):
        run_dirs = [target_dir]
    else:
        run_dirs = sorted([d for d in target_dir.iterdir() if d.is_dir() and "p2c_pilot_" in d.name])

    if not run_dirs:
        print(f"No valid P2c run directories found in '{target_dir}'.")
        sys.exit(1)

    for rdir in run_dirs:
        print("=======================================================================")
        print(f"Replaying P2c Run: {rdir.name}")
        print("=======================================================================")
        summary = replay_p2c_run(rdir, Path(args.protocol))
        print(f"Checksum File Present: {summary['checksum_file_present']}")
        print(f"Episodes: {summary['total_episodes_replayed']}, All Valid: {summary['all_episodes_valid']}, All Audit Pass: {summary['all_audit_pass']}")
        print("-------------------------------------------------------------------------------------------------------------")
        print("| Episode | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |")
        print("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for ep in summary["episodes"]:
            print(f"| {ep['episode_id']:10s} | {ep.get('requested_route', 'N/A'):18s} | {ep.get('actual_route', 'N/A'):18s} | {ep.get('dead_end_traversals', 0):8d} | {ep.get('replayed_total_dist_m', 0.0):11.2f}m | {str(ep.get('final_goal_success', False)):7s} | {str(ep.get('success_within_budget', False)):9s} | {str(ep.get('episode_valid', False)):5s} | {str(ep.get('audit_pass', False)):10s} |")
        print("=============================================================================================================\n")


if __name__ == "__main__":
    main()
