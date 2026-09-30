#!/usr/bin/env python3
"""FailMem Milestone P2c Analytical Model & Policy Unit Demonstration Runner.

Demonstrates algorithmic policy logic (R, O, F, M1) under simplified kinematic/analytic
abstraction across paired scenarios (D0, D1, D2):
- R (Reactive Only)
- O (Spatial Observation Cache)
- F (FailMem Failure Memory)
- M1 (Persistent Suppression Baseline)

NOTE: This script produces analytical model predictions under idealized velocity assumptions,
NOT real physical ROS 2 / Gazebo / Nav2 execution results.
"""

from __future__ import annotations

import argparse
import copy
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
from src.failure_memory import (
    FailureMemoryStore,
    MemoryState,
)


class SpatialObservationCache:
    """Non-decaying spatial observation cache storing environmental observations with coordinates/region."""

    def __init__(self):
        self.cache: Dict[str, List[Dict[str, Any]]] = {}

    def update_observation(self, region_id: str, state: str, sim_time: float, evidence: Dict[str, Any]):
        if region_id not in self.cache:
            self.cache[region_id] = []
        self.cache[region_id].append({
            "region_id": region_id,
            "doorway_state": state,
            "sim_time": round(float(sim_time), 4),
            "evidence": copy.deepcopy(evidence),
        })

    def get_latest_state(self, region_id: str) -> str:
        if region_id not in self.cache or not self.cache[region_id]:
            return "UNKNOWN"
        return self.cache[region_id][-1]["doorway_state"]


def verify_sightline_occlusion(junc_xy: Tuple[float, float], doorway_xy: Tuple[float, float]) -> Dict[str, Any]:
    """Verify that Chokepoint A is occluded by the central horizontal island from Junction J0."""
    # Central island is at x in [-1.8, 1.8], y in [-1.0, 0.4]
    x0, y0 = junc_xy
    x1, y1 = doorway_xy
    
    # Parametric ray: (x0 + t*(x1-x0), y0 + t*(y1-y0)) for t in [0, 1]
    intersects = False
    intersection_point = None
    for step in range(1001):
        t = step / 1000.0
        rx = x0 + t * (x1 - x0)
        ry = y0 + t * (y1 - y0)
        if -1.8 <= rx <= 1.8 and -1.0 <= ry <= 0.4:
            intersects = True
            intersection_point = (round(rx, 3), round(ry, 3))
            break
            
    dist_total = math.hypot(x1 - x0, y1 - y0)
    
    return {
        "junction_xy": list(junc_xy),
        "doorway_xy": list(doorway_xy),
        "ray_distance_m": round(dist_total, 3),
        "line_of_sight_occluded": intersects,
        "occluding_geometry": "central_island_box [-1.8, 1.8] x [-1.0, 0.4]" if intersects else None,
        "intersection_point": list(intersection_point) if intersection_point else None,
        "junction_local_observation": "UNKNOWN" if intersects else "VISIBLE",
    }


def simulate_diagnostic_trial(
    scenario: str,
    method: str,
    protocol: Dict[str, Any],
) -> Dict[str, Any]:
    """Simulate single analytical diagnostic trial for a given method under scenario D0, D1, or D2."""
    routes = protocol["routes"]
    path_a_len = float(routes["path_a"]["nominal_length_m"])  # 5.8m
    path_b_len = float(routes["path_b"]["nominal_length_m"])  # 8.8m
    chokepoint_region = "north_corridor_chokepoint"
    
    # Speed assumption in analytical model: ~0.25 m/s avg navigation velocity
    avg_speed = 0.25
    
    # Track state
    cache = SpatialObservationCache()
    fail_store = FailureMemoryStore()
    m1_suppressed = False
    
    history_distance = 0.0
    history_sim_time = 0.0
    history_events: List[Dict[str, Any]] = []
    
    global_costmap_retains_obstacle = False
    
    # Probe distance: J0(-2.5, 0) -> (-1.5, 1.2) -> (-0.3, 1.2) = ~2.8m
    probe_dist = 2.8
    probe_time = round(probe_dist / avg_speed + 5.0, 2)  # ~16.2s
    retreat_dist = 2.8
    retreat_time = round(retreat_dist / avg_speed + 2.0, 2)  # ~13.2s
    
    # -------------------------------------------------------------------------
    # 1. HISTORY PHASE
    # -------------------------------------------------------------------------
    if scenario == "D0":
        history_distance = 0.0
        history_sim_time = 0.0
        global_costmap_retains_obstacle = False
        
    elif scenario == "D1":
        occ_obs = {
            "doorway_state": "OCCUPIED",
            "reason": "OBSTACLE_DETECTED (laser hits inside chokepoint_bbox)",
            "doorway_bbox": [-0.3, 0.3, 0.80, 1.60],
            "stamp_sec": probe_time - 2.0,
            "region_id": chokepoint_region,
            "map_version": "p2c_dualpath_world_v1",
        }
        
        cache.update_observation(chokepoint_region, "OCCUPIED", probe_time - 2.0, occ_obs)
        fail_store.record_failure(
            goal=[2.5, 0.0, 0.0],
            region_id=chokepoint_region,
            failure_reason="BUDGET_DEADLINE_EXCEEDED",
            sim_time=probe_time - 2.0,
            failed_action_id="probe_attempt_1",
            failure_evidence_id="probe_obs_1",
            failure_evidence=occ_obs,
            map_version="p2c_dualpath_world_v1",
        )
        m1_suppressed = True
        global_costmap_retains_obstacle = True
        
        history_distance = round(probe_dist + retreat_dist, 2)  # 5.6m
        history_sim_time = round(probe_time + retreat_time, 2)  # ~29.4s
        history_events.append({
            "phase": "HISTORY_PROBE_BLOCKED",
            "probe_distance_m": probe_dist,
            "retreat_distance_m": retreat_dist,
            "obstacle_detected_at_sim": round(probe_time - 2.0, 2),
            "retreat_arrival_at_sim": round(history_sim_time, 2),
        })
        
    elif scenario == "D2":
        occ_obs = {
            "doorway_state": "OCCUPIED",
            "stamp_sec": probe_time - 2.0,
            "region_id": chokepoint_region,
            "map_version": "p2c_dualpath_world_v1",
        }
        cache.update_observation(chokepoint_region, "OCCUPIED", probe_time - 2.0, occ_obs)
        fail_store.record_failure(
            goal=[2.5, 0.0, 0.0],
            region_id=chokepoint_region,
            failure_reason="BUDGET_DEADLINE_EXCEEDED",
            sim_time=probe_time - 2.0,
            failed_action_id="probe_attempt_1",
            failure_evidence_id="probe_obs_1",
            failure_evidence=occ_obs,
            map_version="p2c_dualpath_world_v1",
        )
        m1_suppressed = True
        
        t_mid = probe_time + retreat_time
        
        probe2_dist = 2.8
        probe2_time = t_mid + (probe2_dist / avg_speed + 3.0)
        free_obs = {
            "doorway_state": "FREE",
            "reason": "DOORWAY_CLEARANCE_VERIFIED (rays traversing corridor)",
            "doorway_bbox": [-0.3, 0.3, 0.80, 1.60],
            "stamp_sec": probe2_time - 1.0,
            "region_id": chokepoint_region,
            "map_version": "p2c_dualpath_world_v1",
        }
        cache.update_observation(chokepoint_region, "FREE", probe2_time - 1.0, free_obs)
        ev_to_check = dict(free_obs)
        ev_to_check["timestamp_sim"] = probe2_time - 1.0
        fail_store.evaluate_perception_for_invalidation(
            perception_evidence=ev_to_check,
            sim_time=probe2_time - 1.0,
            evidence_id="probe2_obs_clear",
            map_version="p2c_dualpath_world_v1",
            region_id=chokepoint_region,
        )
        global_costmap_retains_obstacle = False
        
        retreat2_dist = 2.8
        t_final_hist = probe2_time + (retreat2_dist / avg_speed + 2.0)
        
        history_distance = round(probe_dist + retreat_dist + probe2_dist + retreat2_dist, 2)  # 11.2m
        history_sim_time = round(t_final_hist, 2)  # ~58.8s
        history_events.append({
            "phase": "HISTORY_PROBE_CLEARED",
            "blocked_probe_sim": round(probe_time, 2),
            "cleared_probe_sim": round(probe2_time, 2),
            "retreat_arrival_at_sim": round(history_sim_time, 2),
        })

    # -------------------------------------------------------------------------
    # 2. DECISION PHASE AT JUNCTION J0
    # -------------------------------------------------------------------------
    local_sightline = verify_sightline_occlusion((-2.5, 0.0), (0.0, 1.20))
    instant_local_obs = local_sightline["junction_local_observation"]  # "UNKNOWN"
    
    chosen_route = "UNKNOWN"
    dead_end_traversals = 0
    decision_dispatches = 0
    decision_distance = 0.0
    decision_sim_time = 0.0
    decision_rationales: List[str] = []
    
    if method == "R":
        if scenario in ["D0", "D2"]:
            chosen_route = "Path_A"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_a_len  # 5.8m
            decision_sim_time = round(path_a_len / avg_speed + 2.0, 2)  # ~25.2s
            decision_rationales.append("Local obs UNKNOWN -> explore nominal Path A -> SUCCESS")
        elif scenario == "D1":
            chosen_route = "Path_A_then_Path_B"
            decision_dispatches = 2
            dead_end_traversals = 1
            # Traverses into Path A (2.8m) + retreats (2.8m) + traverses Path B (8.8m) = 14.4m
            decision_distance = round(2.8 + 2.8 + path_b_len, 2)  # 14.4m
            decision_sim_time = round((2.8 + 2.8 + path_b_len) / avg_speed + 6.0, 2)  # ~63.6s
            decision_rationales.append("Local obs UNKNOWN -> naive Path A re-entry -> BLOCKED at chokepoint -> retreat to J0 -> fallback Path B -> SUCCESS")

    elif method == "O":
        cached_state = cache.get_latest_state(chokepoint_region)
        if cached_state == "OCCUPIED":
            chosen_route = "Path_B"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_b_len  # 8.8m
            decision_sim_time = round(path_b_len / avg_speed + 2.0, 2)  # ~37.2s
            decision_rationales.append("Chokepoint A cached OCCUPIED -> bypass via Path B immediately -> SUCCESS (0 dead-end traversals)")
        else:
            chosen_route = "Path_A"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_a_len  # 5.8m
            decision_sim_time = round(path_a_len / avg_speed + 2.0, 2)  # ~25.2s
            decision_rationales.append(f"Chokepoint A cached {cached_state} -> route via Path A -> SUCCESS")

    elif method == "F":
        is_blocked, blocked_entry, block_reason = fail_store.is_dispatch_blocked([2.5, 0.0, 0.0], chokepoint_region, "p2c_dualpath_world_v1")
        if is_blocked:
            chosen_route = "Path_B"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_b_len  # 8.8m
            decision_sim_time = round(path_b_len / avg_speed + 2.0, 2)  # ~37.2s
            decision_rationales.append(f"Path A blocked by {blocked_entry.memory_id} -> route via Path B immediately -> SUCCESS (0 dead-end traversals)")
        else:
            chosen_route = "Path_A"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_a_len  # 5.8m
            decision_sim_time = round(path_a_len / avg_speed + 2.0, 2)  # ~25.2s
            inv_str = " (recovery verified)" if scenario == "D2" else ""
            decision_rationales.append(f"Path A un-suppressed{inv_str} -> route via Path A -> SUCCESS")

    elif method == "M1":
        if m1_suppressed:
            chosen_route = "Path_B"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_b_len  # 8.8m
            decision_sim_time = round(path_b_len / avg_speed + 2.0, 2)  # ~37.2s
            decision_rationales.append("Path A permanently suppressed -> route via Path B (detour penalty incurred in D2)")
        else:
            chosen_route = "Path_A"
            decision_dispatches = 1
            dead_end_traversals = 0
            decision_distance = path_a_len
            decision_sim_time = round(path_a_len / avg_speed + 2.0, 2)
            decision_rationales.append("Nominal Path A -> SUCCESS")

    # End-to-End Totals
    total_distance = round(history_distance + decision_distance, 2)
    total_sim_time = round(history_sim_time + decision_sim_time, 2)

    return {
        "evidence_type": "analytical_model",
        "scenario": scenario,
        "method": method,
        "junction_pose": [-2.5, 0.0, 0.0],
        "local_sensor_observation_at_junction": instant_local_obs,
        "global_costmap_retains_obstacle": global_costmap_retains_obstacle,
        "history_phase": {
            "distance_m": history_distance,
            "sim_time_sec": history_sim_time,
            "events": history_events,
        },
        "decision_phase": {
            "chosen_route": chosen_route,
            "dead_end_traversals": dead_end_traversals,
            "dispatches_count": decision_dispatches,
            "distance_m": decision_distance,
            "sim_time_sec": decision_sim_time,
            "rationales": decision_rationales,
        },
        "end_to_end_total": {
            "total_distance_m": total_distance,
            "total_sim_time_sec": total_sim_time,
            "task_success": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="FailMem Milestone P2c Analytical Model & Policy Unit Demonstration")
    parser.add_argument("--protocol", default="configs/p2c_pilot_protocol.yaml", help="Path to protocol YAML")
    parser.add_argument("--out-dir", default="reports/evidence/p2c_analytical", help="Output analytical evidence directory")
    args = parser.parse_args()

    protocol_path = Path(args.protocol)
    with open(protocol_path, "r", encoding="utf-8") as f:
        protocol = yaml.safe_load(f)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=======================================================================")
    print("FailMem Milestone P2c Analytical Model & Policy Unit Demonstration")
    print(f"Protocol: {protocol_path} (Version {protocol.get('protocol_version')})")
    print(f"Evidence Type: analytical_model")
    print(f"Evidence Directory: {out_dir}")
    print("=======================================================================\n")

    # 1. Sightline Verification
    sightline_proof = verify_sightline_occlusion((-2.5, 0.0), (0.0, 1.20))
    sightline_proof["evidence_type"] = "analytical_model"
    with open(out_dir / "sightline_occlusion_proof.json", "w", encoding="utf-8") as f:
        json.dump(sightline_proof, f, indent=2)

    print("1. SIGHTLINE OCCLUSION VERIFICATION (Analytical):")
    print(f"   Junction J0: {sightline_proof['junction_xy']} -> Chokepoint A: {sightline_proof['doorway_xy']}")
    print(f"   Ray Distance: {sightline_proof['ray_distance_m']}m")
    print(f"   Line of Sight Occluded: {sightline_proof['line_of_sight_occluded']} (Occluder: {sightline_proof['occluding_geometry']})")
    print(f"   Junction Local Sensor Observation: {sightline_proof['junction_local_observation']}\n")

    # 2. Run Analytical Diagnostics (D0, D1, D2) for R, O, F, M1
    diagnostics = ["D0", "D1", "D2"]
    methods = ["R", "O", "F", "M1"]
    all_results: List[Dict[str, Any]] = []

    for diag in diagnostics:
        for m in methods:
            res = simulate_diagnostic_trial(diag, m, protocol)
            all_results.append(res)

    pilot_report = {
        "evidence_type": "analytical_model",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_version": protocol.get("protocol_version"),
        "sightline_occlusion_proof": sightline_proof,
        "diagnostic_trials": all_results,
    }

    with open(out_dir / "p2c_pilot_diagnosis_results.json", "w", encoding="utf-8") as f:
        json.dump(pilot_report, f, indent=2)

    # Print Summary Comparison Table
    print("=======================================================================")
    print("2. ANALYTICAL DIAGNOSTIC SUMMARY MATRIX (Idealized Kinematics):")
    print("-----------------------------------------------------------------------")
    print("| Scenario | Method | Route | Dead-End | Decision Dist | Decision Time | Total Dist | Total Time |")
    print("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
    for r in all_results:
        diag = r["scenario"]
        m = r["method"]
        route = r["decision_phase"]["chosen_route"]
        dead_end = r["decision_phase"]["dead_end_traversals"]
        dec_d = r["decision_phase"]["distance_m"]
        dec_t = r["decision_phase"]["sim_time_sec"]
        tot_d = r["end_to_end_total"]["total_distance_m"]
        tot_t = r["end_to_end_total"]["total_sim_time_sec"]
        print(f"| {diag:8s} | {m:6s} | {route:22s} | {dead_end:8d} | {dec_d:11.1f}m | {dec_t:11.1f}s | {tot_d:8.1f}m | {tot_t:8.1f}s |")
    print("=======================================================================")
    print(f"\nAnalytical evidence written to: {out_dir / 'p2c_pilot_diagnosis_results.json'}")


if __name__ == "__main__":
    main()
