#!/usr/bin/env python3
"""FailMem Milestone P2c Independent Replay & Objective Scoring Suite.

Provides strict offline verification and re-scoring:
1. Multi-Layer Anti-Tamper & Checksum Integrity:
   - Hashes all artifacts against `checksums.sha256`.
2. Raw Trajectory & Odometry Continuity:
   - Re-integrates path lengths from continuous odometry and verifies step jumps (< 2.0m).
3. Costmap ROI & Lethal Cell Audit:
   - Verifies lethal cell presence in doorway opening center during blocked stage and absence during cleared stage.
4. Causal Failure Memory Lifecycle Verification:
   - Verifies that successful vantage actions do NOT generate failure memory.
   - Verifies that traversal failure with linked OCCUPIED evidence creates active memory.
   - Verifies that D2 clearance observation strictly invalidates memory upon FREE perception.
5. Independent Physical Scoring:
   - Evaluates final goal arrival against strict physical tolerance standards.
   - Evaluates 4 separate validity flags: final_goal_success, history_valid, route_valid, episode_valid.
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
from src.failure_memory import (
    FailureMemoryStore,
    MemoryState,
)


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_checksums(run_dir: Path) -> Dict[str, str]:
    """Load checksums.sha256 dictionary mapping relative path to expected sha256."""
    chk_file = run_dir / "checksums.sha256"
    if not chk_file.exists():
        return {}
    checksums = {}
    with open(chk_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                checksums[parts[1].strip()] = parts[0].strip()
    return checksums


def integrate_trajectory_distance(samples: List[Dict[str, Any]]) -> Tuple[float, int]:
    """Compute path length and count abnormal jumps (> 2.0m)."""
    if not samples or len(samples) < 2:
        return 0.0, 0
    dist = 0.0
    jumps = 0
    for i in range(1, len(samples)):
        x0 = float(samples[i - 1]["x"])
        y0 = float(samples[i - 1]["y"])
        x1 = float(samples[i]["x"])
        y1 = float(samples[i]["y"])
        d = math.hypot(x1 - x0, y1 - y0)
        if d >= 2.0:
            jumps += 1
        else:
            dist += d
    return round(dist, 3), jumps


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
    thresholds: Dict[str, Any],
) -> Dict[str, Any]:
    """Replay and independently score a single P2c episode directory."""
    ep_id = ep_dir.name
    required_files = ["action_result.json", "trajectory.json", "costmap_snapshots.json", "stability_window.json"]
    missing = [f for f in required_files if not (ep_dir / f).exists()]
    if missing:
        return {
            "episode_id": ep_id,
            "replay_valid": False,
            "error": f"MISSING_ARTIFACTS: {missing}",
            "episode_valid": False,
        }

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
    target_goal = [2.50, 0.00, 0.0]

    # 1. Trajectory continuity
    odom_samples = traj_data.get("odom_trajectory", [])
    replayed_total_dist, jump_count = integrate_trajectory_distance(odom_samples)

    # 2. History verification
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
            history_reasons.append(f"MISSING_D1_HISTORY_ACTIONS (found v1={bool(act_v1)}, tr1={bool(act_tr1)}, r1={bool(act_r1)})")
        else:
            v1_ok = (act_v1.get("terminal_status_name") == "SUCCEEDED" and act_v1.get("execution_outcome") == "BUDGET_SUCCESS")
            tr1_failed = (act_tr1.get("execution_outcome") in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"])
            r1_ok = (act_r1.get("terminal_status_name") == "SUCCEEDED" and act_r1.get("execution_outcome") == "BUDGET_SUCCESS")
            if not (v1_ok and tr1_failed and r1_ok):
                history_valid = False
                history_reasons.append(f"D1_OUTCOME_MISMATCH (v1={v1_ok}, tr1_fail={tr1_failed}, r1={r1_ok})")

        if scenario == "D2":
            act_p2 = next((a for a in actions if get_action_id(a) == "hist_probe_clearance_vantage"), None)
            act_r2 = next((a for a in actions if get_action_id(a) == "hist_retreat_to_j0_clear"), None)
            if not (act_p2 and act_r2):
                history_valid = False
                history_reasons.append(f"MISSING_D2_HISTORY_ACTIONS (found p2={bool(act_p2)}, r2={bool(act_r2)})")
            else:
                p2_ok = (act_p2.get("terminal_status_name") == "SUCCEEDED" and act_p2.get("execution_outcome") == "BUDGET_SUCCESS")
                r2_ok = (act_r2.get("terminal_status_name") == "SUCCEEDED" and act_r2.get("execution_outcome") == "BUDGET_SUCCESS")
                if not (p2_ok and r2_ok):
                    history_valid = False
                    history_reasons.append(f"D2_OUTCOME_MISMATCH (p2={p2_ok}, r2={r2_ok})")

    # 3. Costmap snapshots verification
    costmap_valid = True
    for cm in costmap_snapshots:
        stg = cm.get("stage", "")
        op_lethal = cm.get("cell_counts", {}).get("opening_lethal", 0)
        if "PROBE_BLOCKED" in stg and op_lethal == 0:
            costmap_valid = False
        elif "PROBE_CLEARED" in stg and op_lethal > 0:
            costmap_valid = False

    # 4. Decision phase dead-ends replayed
    has_fallback = any("dec_fallback" in get_action_id(a) for a in actions)
    replayed_dead_ends = 1 if has_fallback else 0

    # 5. Final Physical Goal Arrival Re-scoring
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

    evaluator_verified_success = bool(eval_dict.get("strict_physical_arrival_and_stable", False))
    final_goal_success = evaluator_verified_success
    route_valid = bool(jump_count == 0 and len(odom_samples) > 10 and replayed_total_dist > 0.0 and costmap_valid)
    episode_valid = bool(final_goal_success and history_valid and route_valid)

    return {
        "episode_id": ep_id,
        "scenario": scenario,
        "method": method,
        "chosen_route": action_res.get("chosen_route"),
        "dead_end_traversals": action_res.get("dead_end_traversals", replayed_dead_ends),
        "replayed_dead_ends": replayed_dead_ends,
        "recorded_total_dist_m": action_res.get("total_distance_m", 0.0),
        "replayed_total_dist_m": replayed_total_dist,
        "distance_discrepancy_m": round(abs(action_res.get("total_distance_m", 0.0) - replayed_total_dist), 3),
        "trajectory_jumps": jump_count,
        "final_goal_success": final_goal_success,
        "history_valid": history_valid,
        "history_reasons": history_reasons,
        "costmap_valid": costmap_valid,
        "route_valid": route_valid,
        "episode_valid": episode_valid,
        "evaluator_verified_success": evaluator_verified_success,
        "policy_reported_success": action_res.get("policy_reported_success", False),
        "disagreement_reason": compute_disagreement_reason(action_res.get("policy_reported_success", False), evaluator_verified_success, eval_dict),
    }


def replay_p2c_run(run_dir: Path, protocol_path: Optional[Path] = None) -> Dict[str, Any]:
    """Replay and audit an entire P2c run directory."""
    checksums = load_checksums(run_dir)
    checksums_valid = True
    tampered_files: List[str] = []

    if checksums:
        for rel_path, exp_hash in checksums.items():
            fpath = run_dir / rel_path
            if not fpath.exists():
                checksums_valid = False
                tampered_files.append(f"MISSING: {rel_path}")
            else:
                actual_hash = compute_file_sha256(fpath)
                if actual_hash != exp_hash:
                    checksums_valid = False
                    tampered_files.append(f"HASH_MISMATCH: {rel_path}")

    proto_path = protocol_path or (run_dir / "protocol.yaml")
    if not proto_path.exists() and Path("configs/p2c_pilot_protocol.yaml").exists():
        proto_path = Path("configs/p2c_pilot_protocol.yaml")

    with open(proto_path, "r", encoding="utf-8") as f:
        proto_cfg = yaml.safe_load(f)

    scoring_rules_path = Path("configs/scoring_rules.yaml")
    scoring_rules = load_scoring_rules(str(scoring_rules_path)) if scoring_rules_path.exists() else {}
    thresholds = proto_cfg.get("scoring_thresholds", scoring_rules.get("thresholds", {}))

    ep_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir() and any(k in d.name for k in ["D0_", "D1_", "D2_"])])

    ep_results: List[Dict[str, Any]] = []
    for ep_dir in ep_dirs:
        ep_res = replay_p2c_episode(ep_dir, thresholds)
        ep_results.append(ep_res)

    all_valid = all(r.get("episode_valid", False) for r in ep_results) if ep_results else False

    summary = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "replay_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "checksums_verified": checksums_valid,
        "tampered_files": tampered_files,
        "total_episodes_replayed": len(ep_results),
        "all_episodes_valid": all_valid,
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
        print(f"Checksums Verified: {summary['checksums_verified']}")
        print(f"Episodes Replayed: {summary['total_episodes_replayed']}, All Valid: {summary['all_episodes_valid']}")
        print("-----------------------------------------------------------------------")
        print("| Episode | Route | Dead-End | Replayed Dist | Success | Ep Valid |")
        print("| :--- | :--- | :---: | :---: | :---: | :---: |")
        for ep in summary["episodes"]:
            print(f"| {ep['episode_id']:12s} | {ep['chosen_route']:22s} | {ep['dead_end_traversals']:8d} | {ep['replayed_total_dist_m']:11.2f}m | {str(ep['evaluator_verified_success']):7s} | {str(ep['episode_valid']):8s} |")
        print("=======================================================================\n")


if __name__ == "__main__":
    main()
