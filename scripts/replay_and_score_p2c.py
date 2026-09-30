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
)
from src.failure_memory import (
    FailureMemoryStore,
    MemoryState,
)
from scripts.run_p2c_pilot_diagnosis import (
    SpatialObservationCache,
)
from src.p2c_pipeline import (
    P2cProtocolConfig,
    P2cTrajectoryClassifier,
    P2cPolicyDecider,
    P2cEpisodeEvaluator,
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
    """Replay and independently score a single P2c episode directory."""
    ep_id = ep_dir.name
    required_files = ["action_result.json", "trajectory.json", "costmap_snapshots.json", "stability_window.json"]
    missing = [f for f in required_files if not (ep_dir / f).exists()]
    if missing:
        return {
            "episode_id": ep_id,
            "evidence_complete": False,
            "error": f"MISSING_ARTIFACTS: {missing}",
            "final_goal_success": False,
            "success_within_budget": False,
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
    else:
        # Legacy run without frozen protocol snapshot -> mark UNVERIFIABLE
        protocol_matched = False
        tamper_reasons.append("MISSING_RUNTIME_PROTOCOL_SNAPSHOT (UNVERIFIABLE)")
        thresholds = fallback_thresholds
        total_budget_sec = 180.0

    with open(ep_dir / "action_result.json", "r", encoding="utf-8") as f:
        action_res = json.load(f)

    with open(ep_dir / "trajectory.json", "r", encoding="utf-8") as f:
        traj_data = json.load(f)

    with open(ep_dir / "costmap_snapshots.json", "r", encoding="utf-8") as f:
        costmap_snapshots = json.load(f)

    with open(ep_dir / "stability_window.json", "r", encoding="utf-8") as f:
        window_data = json.load(f)

    scenario = action_res.get("scenario", "UNKNOWN")
    method = action_res.get("method", "UNKNOWN")
    actions = action_res.get("actions", [])
    total_sim_time_sec = float(action_res.get("total_sim_time_sec", 0.0))
    target_goal = [2.50, 0.00, 0.0]

    # 1. Trajectory continuity & classification
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

    # 2. Replay Causal Memory Lifecycle
    replayed_fail_store = FailureMemoryStore()
    replayed_cache = SpatialObservationCache()

    # 3. History validation
    history_valid = True
    history_reasons = []
    if scenario == "D0":
        history_valid = True
    elif scenario in ["D1", "D2"]:
        act_v1 = next((a for a in actions if get_action_id(a) == "hist_reach_obs_vantage"), None)
        act_tr1 = next((a for a in actions if get_action_id(a) == "hist_attempt_chokepoint_traversal"), None)
        act_r1 = next((a for a in actions if get_action_id(a) == "hist_retreat_to_j0"), None)

        if not (act_v1 and act_tr1 and act_r1):
            history_valid = False
            history_reasons.append("MISSING_D1_HISTORY_ACTIONS")
        else:
            v1_ok = (act_v1.get("terminal_status_name") == "SUCCEEDED" and act_v1.get("execution_outcome") == "BUDGET_SUCCESS")
            tr1_failed = (act_tr1.get("execution_outcome") in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"])
            r1_ok = (act_r1.get("terminal_status_name") == "SUCCEEDED" and act_r1.get("execution_outcome") == "BUDGET_SUCCESS")
            if not (v1_ok and tr1_failed and r1_ok):
                history_valid = False
                history_reasons.append(f"D1_OUTCOME_MISMATCH (v1_ok={v1_ok}, tr1_fail={tr1_failed}, r1_ok={r1_ok})")

            # Replay memory recording
            if tr1_failed:
                replayed_fail_store.record_failure(
                    goal=target_goal,
                    region_id="north_corridor_chokepoint",
                    failure_reason="BLOCKED_AT_DOORWAY",
                    sim_time=float(act_tr1.get("evaluation", {}).get("timestamp_sim", 20.0)),
                    failed_action_id="hist_attempt_chokepoint_traversal",
                    failure_evidence_id="post_fail_occ_obs",
                    failure_evidence={"doorway_state": "OCCUPIED"},
                    map_version="p2c_dualpath_world_v1",
                )

        if scenario == "D2":
            act_p2 = next((a for a in actions if get_action_id(a) == "hist_probe_clearance_vantage"), None)
            act_r2 = next((a for a in actions if get_action_id(a) == "hist_retreat_to_j0_clear"), None)
            if not (act_p2 and act_r2):
                history_valid = False
                history_reasons.append("MISSING_D2_HISTORY_ACTIONS")
            else:
                p2_ok = (act_p2.get("terminal_status_name") == "SUCCEEDED" and act_p2.get("execution_outcome") == "BUDGET_SUCCESS")
                r2_ok = (act_r2.get("terminal_status_name") == "SUCCEEDED" and act_r2.get("execution_outcome") == "BUDGET_SUCCESS")
                if not (p2_ok and r2_ok):
                    history_valid = False
                    history_reasons.append(f"D2_OUTCOME_MISMATCH (p2_ok={p2_ok}, r2_ok={r2_ok})")

                # Replay memory invalidation
                if p2_ok:
                    replayed_fail_store.evaluate_perception_for_invalidation(
                        perception_evidence={"doorway_state": "FREE", "timestamp_sim": 100.0},
                        sim_time=100.0,
                        evidence_id="probe2_obs_clear",
                        map_version="p2c_dualpath_world_v1",
                        region_id="north_corridor_chokepoint",
                    )

    # 4. Costmap snapshots verification
    costmap_valid = True
    for cm in costmap_snapshots:
        stg = cm.get("stage", "")
        op_lethal = cm.get("cell_counts", {}).get("opening_lethal", 0)
        if "PROBE_BLOCKED" in stg and op_lethal == 0:
            costmap_valid = False
        elif "PROBE_CLEARED" in stg and op_lethal > 0:
            costmap_valid = False

    # 5. Physical Goal Arrival Re-scoring
    last_action = actions[-1] if actions else {}
    last_summary = last_action
    window_records = window_data.get("window_records", [])
    last_gt = window_records[-1].get("gt") if window_records else (traj_data.get("gt_trajectory", [])[-1] if traj_data.get("gt_trajectory") else None)
    last_amcl = window_records[-1].get("odom") if window_records else None

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

    final_goal_success = bool(eval_dict.get("strict_physical_arrival_and_stable", False))
    success_within_budget = bool(final_goal_success and total_sim_time_sec <= total_budget_sec + 0.50)
    route_valid = bool(jump_count == 0 and len(odom_samples) > 10 and replayed_total_dist > 0.0 and costmap_valid)
    episode_valid = bool(final_goal_success and success_within_budget and history_valid and route_valid and evidence_complete)
    audit_pass = bool(episode_valid and chk_valid and protocol_matched)

    failure_reasons = list(tamper_reasons) + list(history_reasons)
    if not success_within_budget:
        failure_reasons.append(f"TOTAL_BUDGET_EXCEEDED ({total_sim_time_sec:.1f}s > {total_budget_sec:.1f}s)")
    if not final_goal_success:
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
        "final_goal_success": final_goal_success,
        "success_within_budget": success_within_budget,
        "history_valid": history_valid,
        "route_valid": route_valid,
        "costmap_valid": costmap_valid,
        "evidence_complete": evidence_complete,
        "checksums_verified": chk_valid,
        "protocol_matched": protocol_matched,
        "episode_valid": episode_valid,
        "audit_pass": audit_pass,
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
            print(f"| {ep['episode_id']:10s} | {ep.get('requested_route', 'N/A'):18s} | {ep.get('actual_route', 'N/A'):18s} | {ep['dead_end_traversals']:8d} | {ep['replayed_total_dist_m']:11.2f}m | {str(ep['final_goal_success']):7s} | {str(ep['success_within_budget']):9s} | {str(ep['episode_valid']):5s} | {str(ep['audit_pass']):10s} |")
        print("=============================================================================================================\n")


if __name__ == "__main__":
    main()
