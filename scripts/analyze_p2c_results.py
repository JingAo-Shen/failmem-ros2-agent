#!/usr/bin/env python3
"""Unified Statistical Analysis and Visualization for Milestone P2c Experiments.

Loads raw evidence from a P2c run directory and produces:
1. episodes.csv: Complete per-episode record of metrics, stages, and audit verdicts.
2. condition_summary.csv: Condition-level aggregated statistics (n, mean, sample std ddof=1, min, max).
3. contrasts.csv: Pairwise contrasts (F vs R, F vs O, F vs M1) in absolute and relative terms.
4. Publication-ready visualization figures with raw data points and group distributions.

Strict Integrity Rules:
- Missing action_result.json or mandatory artifacts causes integrity check failure and reports missing list.
- Missing replay/audit fields are NOT defaulted to True/0.0; preserved as None / NaN.
- Runner claims and Replay verdicts are tracked separately, and conflicts are explicitly reported.
- When n=1, sample standard deviation is output as 'NA'.
- When baseline mean is 0, relative difference is output as 'NA' while absolute difference is preserved.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


EXPECTED_30_EPISODES = [
    f"{cond}_ep{i}"
    for cond in ["D0_R", "D0_O", "D0_F", "D1_R", "D1_O", "D1_F", "D2_R", "D2_O", "D2_F", "D2_M1"]
    for i in range(1, 4)
]

REQUIRED_ACTION_FIELDS: Dict[str, Tuple[type, ...]] = {
    "scenario": (str,),
    "method": (str,),
    "condition_id": (str,),
    "total_distance_m": (int, float),
    "total_sim_time_sec": (int, float),
    "decision_distance_m": (int, float),
    "decision_sim_time_sec": (int, float),
    "dead_end_traversals": (int, float),
    "final_goal_success": (bool,),
    "success_within_budget": (bool,),
    "history_valid": (bool,),
    "route_valid": (bool,),
    "episode_valid": (bool,),
}


def validate_action_dict(act: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate that action_result contains all required fields with correct types and finite values."""
    issues: List[str] = []
    for field, expected_types in REQUIRED_ACTION_FIELDS.items():
        if field not in act:
            issues.append(f"MISSING_FIELD_{field}")
            continue
        val = act[field]
        if val is None:
            issues.append(f"NULL_VALUE_{field}")
            continue
        if bool in expected_types:
            if not isinstance(val, bool):
                issues.append(f"TYPE_MISMATCH_{field}_EXPECTED_BOOL_GOT_{type(val).__name__}")
        elif (int in expected_types) or (float in expected_types):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                issues.append(f"TYPE_MISMATCH_{field}_EXPECTED_NUMERIC_GOT_{type(val).__name__}")
            elif not math.isfinite(float(val)):
                issues.append(f"NON_FINITE_VALUE_{field}")
        elif str in expected_types:
            if not isinstance(val, str) or len(val.strip()) == 0:
                issues.append(f"INVALID_STRING_{field}")
    return (len(issues) == 0), issues


def load_and_verify_run_episodes(
    run_dir: Path,
    expected_episodes: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load per-episode data by joining action_result.json and replay audit results.
    
    Strict Verification:
    - Validates required fields, non-null values, correct types, and finite numeric values.
    - Tracks duplicate replay episode IDs in p2c_replay_summary.json without silent overwrite.
    - Checks consistency between directory name, internal episode_id, scenario, method, and condition_id.
    - Identifies missing expected episodes and unexpected extra episodes.
    
    Returns:
        (episodes_list, integrity_report_dict)
    """
    if expected_episodes is None:
        expected_episodes = EXPECTED_30_EPISODES

    replay_summary_file = run_dir / "p2c_replay_summary.json"
    audit_by_ep: Dict[str, Dict[str, Any]] = {}
    duplicate_replay_ids: List[str] = []
    replay_summary_present = replay_summary_file.exists()

    if replay_summary_present:
        try:
            with open(replay_summary_file, "r", encoding="utf-8") as f:
                rep_data = json.load(f)
                for ep in rep_data.get("episodes", []):
                    eid = ep.get("episode_id")
                    if not eid:
                        continue
                    if eid in audit_by_ep:
                        duplicate_replay_ids.append(eid)
                    audit_by_ep[eid] = ep
        except Exception as e:
            pass

    found_ep_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir() and any(k in d.name for k in ["D0_", "D1_", "D2_"])])
    found_ep_ids = [d.name for d in found_ep_dirs]

    missing_expected: List[str] = [eid for eid in expected_episodes if eid not in found_ep_ids]
    extra_episodes: List[str] = [eid for eid in found_ep_ids if eid not in expected_episodes]
    missing_action_results: List[str] = []
    invalid_action_results: List[Dict[str, Any]] = []
    identity_mismatches: List[Dict[str, Any]] = []
    missing_replay_entries: List[str] = []
    conflicts: List[Dict[str, Any]] = []

    episodes: List[Dict[str, Any]] = []

    # Process all discovered directories
    for ep_dir in found_ep_dirs:
        ep_id = ep_dir.name
        act_file = ep_dir / "action_result.json"

        # Check directory identity structure
        parts = ep_id.split("_")
        expected_scen = parts[0] if len(parts) > 0 else "UNKNOWN"
        expected_meth = parts[1] if len(parts) > 1 else "UNKNOWN"
        expected_cond = f"{expected_scen}_{expected_meth}"

        if not act_file.exists():
            missing_action_results.append(ep_id)
            # Create incomplete record with None values to preserve accounting
            episodes.append({
                "episode_id": ep_id,
                "scenario": expected_scen,
                "method": expected_meth,
                "condition_id": expected_cond,
                "ep_num": int(ep_id.split("_ep")[-1]) if "_ep" in ep_id and ep_id.split("_ep")[-1].isdigit() else None,
                "data_complete": False,
                "missing_artifacts": ["action_result.json"],
                "requested_route": None,
                "actual_route": None,
                "dead_end_traversals": None,
                "decision_dispatches": None,
                "history_distance_m": None,
                "history_sim_time_sec": None,
                "decision_distance_m": None,
                "decision_sim_time_sec": None,
                "total_distance_m": None,
                "replayed_total_dist_m": None,
                "distance_discrepancy_m": None,
                "total_sim_time_sec": None,
                "total_budget_sec": None,
                "runner_goal_success": None,
                "runner_budget_success": None,
                "runner_history_valid": None,
                "runner_route_valid": None,
                "runner_episode_valid": None,
                "replay_task_success": None,
                "replay_budget_success": None,
                "replay_history_valid": None,
                "replay_route_valid": None,
                "replay_costmap_valid": None,
                "replay_raw_evidence_verified": None,
                "replay_memory_lifecycle_verified": None,
                "replay_policy_matched": None,
                "replay_episode_valid": None,
                "replay_audit_pass": None,
                "verdict_conflict": False,
                "conflict_details": "MISSING_ACTION_RESULT",
            })
            continue

        try:
            with open(act_file, "r", encoding="utf-8") as f:
                act = json.load(f)
        except Exception as e:
            missing_action_results.append(f"{ep_id} (corrupted: {e})")
            continue

        # Validate action fields and data types
        act_valid, field_issues = validate_action_dict(act)
        if not act_valid:
            invalid_action_results.append({
                "episode_id": ep_id,
                "issues": field_issues,
            })

        # Validate consistency between directory name and file metadata
        act_scen = act.get("scenario")
        act_meth = act.get("method")
        act_cond = act.get("condition_id")
        act_epid = act.get("episode_id")

        mismatch_reasons: List[str] = []
        if act_scen != expected_scen:
            mismatch_reasons.append(f"scenario mismatch (dir={expected_scen} vs file={act_scen})")
        if act_meth != expected_meth:
            mismatch_reasons.append(f"method mismatch (dir={expected_meth} vs file={act_meth})")
        if act_cond != expected_cond:
            mismatch_reasons.append(f"condition_id mismatch (dir={expected_cond} vs file={act_cond})")
        if act_epid != ep_id:
            mismatch_reasons.append(f"episode_id mismatch (dir={ep_id} vs file={act_epid})")

        if mismatch_reasons:
            identity_mismatches.append({
                "episode_id": ep_id,
                "reasons": mismatch_reasons,
            })

        audit_info = audit_by_ep.get(ep_id)
        if audit_info is None:
            missing_replay_entries.append(ep_id)

        ep_num = None
        if "_ep" in ep_id:
            try:
                ep_num = int(ep_id.split("_ep")[-1])
            except ValueError:
                pass

        # Helper to safely extract floats without defaulting missing to 0.0
        def get_float(d: Optional[Dict[str, Any]], k: str) -> Optional[float]:
            if d is None or k not in d:
                return None
            v = d[k]
            if v is None or isinstance(v, bool):
                return None
            try:
                fv = float(v)
                return fv if math.isfinite(fv) else None
            except (ValueError, TypeError):
                return None

        # Helper to safely extract bools without defaulting missing to True/False
        def get_bool(d: Optional[Dict[str, Any]], k: str) -> Optional[bool]:
            if d is None or k not in d:
                return None
            v = d[k]
            return bool(v) if isinstance(v, bool) else None

        runner_goal_success = get_bool(act, "final_goal_success")
        runner_budget_success = get_bool(act, "success_within_budget")
        runner_history_valid = get_bool(act, "history_valid")
        runner_route_valid = get_bool(act, "route_valid")
        runner_ep_valid = get_bool(act, "episode_valid")

        replay_task_success = get_bool(audit_info, "task_success") if audit_info else None
        replay_budget_success = get_bool(audit_info, "success_within_budget") if audit_info else None
        replay_history_valid = get_bool(audit_info, "history_valid") if audit_info else None
        replay_route_valid = get_bool(audit_info, "route_valid") if audit_info else None
        replay_costmap_valid = get_bool(audit_info, "costmap_valid") if audit_info else None
        replay_raw_evidence_verified = get_bool(audit_info, "raw_evidence_verified") if audit_info else None
        replay_memory_lifecycle_verified = get_bool(audit_info, "memory_lifecycle_verified") if audit_info else None
        replay_policy_matched = get_bool(audit_info, "policy_matched") if audit_info else None
        replay_ep_valid = get_bool(audit_info, "episode_valid") if audit_info else None
        replay_audit_pass = get_bool(audit_info, "audit_pass") if audit_info else None

        # Detect conflicts between runner self-reporting and offline replay audit
        verdict_conflict = False
        conflict_reasons: List[str] = []

        if audit_info is not None:
            if runner_ep_valid is not None and replay_ep_valid is not None and runner_ep_valid != replay_ep_valid:
                verdict_conflict = True
                conflict_reasons.append(f"episode_valid (runner={runner_ep_valid} vs replay={replay_ep_valid})")
            if runner_goal_success is not None and replay_task_success is not None and runner_goal_success != replay_task_success:
                verdict_conflict = True
                conflict_reasons.append(f"goal_success (runner={runner_goal_success} vs replay={replay_task_success})")
            if runner_history_valid is not None and replay_history_valid is not None and runner_history_valid != replay_history_valid:
                verdict_conflict = True
                conflict_reasons.append(f"history_valid (runner={runner_history_valid} vs replay={replay_history_valid})")
        else:
            verdict_conflict = True
            conflict_reasons.append("MISSING_REPLAY_AUDIT_RECORD")

        if verdict_conflict:
            conflicts.append({
                "episode_id": ep_id,
                "reasons": conflict_reasons,
            })

        is_data_complete = bool(act_valid and not mismatch_reasons)

        record = {
            "episode_id": ep_id,
            "scenario": expected_scen if expected_scen != "UNKNOWN" else act.get("scenario"),
            "method": expected_meth if expected_meth != "UNKNOWN" else act.get("method"),
            "condition_id": expected_cond if expected_cond != "UNKNOWN_UNKNOWN" else act.get("condition_id"),
            "ep_num": ep_num,
            "data_complete": is_data_complete,
            "missing_artifacts": field_issues if not act_valid else [],
            "requested_route": act.get("requested_route", act.get("chosen_route")),
            "actual_route": audit_info.get("actual_route", act.get("actual_route")) if audit_info else act.get("actual_route"),
            "dead_end_traversals": int(act["dead_end_traversals"]) if "dead_end_traversals" in act and isinstance(act["dead_end_traversals"], (int, float)) and not isinstance(act["dead_end_traversals"], bool) else None,
            "decision_dispatches": int(act["decision_dispatches"]) if "decision_dispatches" in act and isinstance(act["decision_dispatches"], (int, float)) and not isinstance(act["decision_dispatches"], bool) else None,
            "history_distance_m": get_float(act, "history_distance_m"),
            "history_sim_time_sec": get_float(act, "history_sim_time_sec"),
            "decision_distance_m": get_float(act, "decision_distance_m"),
            "decision_sim_time_sec": get_float(act, "decision_sim_time_sec"),
            "total_distance_m": get_float(act, "total_distance_m"),
            "replayed_total_dist_m": get_float(audit_info, "replayed_total_dist_m"),
            "distance_discrepancy_m": get_float(audit_info, "distance_discrepancy_m"),
            "total_sim_time_sec": get_float(act, "total_sim_time_sec"),
            "total_budget_sec": get_float(act, "total_budget_sec"),
            "runner_goal_success": runner_goal_success,
            "runner_budget_success": runner_budget_success,
            "runner_history_valid": runner_history_valid,
            "runner_route_valid": runner_route_valid,
            "runner_episode_valid": runner_ep_valid,
            "replay_task_success": replay_task_success,
            "replay_budget_success": replay_budget_success,
            "replay_history_valid": replay_history_valid,
            "replay_route_valid": replay_route_valid,
            "replay_costmap_valid": replay_costmap_valid,
            "replay_raw_evidence_verified": replay_raw_evidence_verified,
            "replay_memory_lifecycle_verified": replay_memory_lifecycle_verified,
            "replay_policy_matched": replay_policy_matched,
            "replay_episode_valid": replay_ep_valid,
            "replay_audit_pass": replay_audit_pass,
            "verdict_conflict": verdict_conflict,
            "conflict_details": "; ".join(conflict_reasons) if conflict_reasons else None,
        }
        episodes.append(record)

    # Check for duplicate episode directory IDs
    seen_ids: Set[str] = set()
    duplicate_ep_dirs: List[str] = []
    for r in episodes:
        eid = r["episode_id"]
        if eid in seen_ids:
            duplicate_ep_dirs.append(eid)
        seen_ids.add(eid)

    expected_count = len(expected_episodes)
    actual_found_count = len(found_ep_ids)
    data_complete_count = sum(1 for r in episodes if r.get("data_complete"))
    runner_valid_count = sum(1 for r in episodes if r.get("runner_episode_valid") is True)
    replay_audit_pass_count = sum(1 for r in episodes if r.get("replay_audit_pass") is True)

    all_intact = (
        len(missing_expected) == 0
        and len(extra_episodes) == 0
        and len(missing_action_results) == 0
        and len(invalid_action_results) == 0
        and len(identity_mismatches) == 0
        and len(missing_replay_entries) == 0
        and len(duplicate_ep_dirs) == 0
        and len(duplicate_replay_ids) == 0
        and len(conflicts) == 0
        and replay_summary_present
        and (data_complete_count == expected_count)
    )

    integrity_report = {
        "integrity_check_passed": all_intact,
        "expected_episodes_count": expected_count,
        "actual_found_count": actual_found_count,
        "data_complete_count": data_complete_count,
        "runner_valid_count": runner_valid_count,
        "replay_audit_pass_count": replay_audit_pass_count,
        "missing_expected_episodes": missing_expected,
        "extra_episodes": extra_episodes,
        "missing_action_results": missing_action_results,
        "invalid_action_results": invalid_action_results,
        "identity_mismatches": identity_mismatches,
        "missing_replay_entries": missing_replay_entries,
        "duplicate_episodes": duplicate_ep_dirs,
        "duplicate_replay_ids": duplicate_replay_ids,
        "conflicts_count": len(conflicts),
        "conflicts": conflicts,
    }

    return episodes, integrity_report


def compute_condition_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Compute condition summary statistics with sample standard deviation (ddof=1) and valid counts.
    
    Handles n=1 gracefully by returning 'NA' for sample standard deviation.
    Reports n_valid explicitly for each metric column.
    """
    metric_cols = [
        "dead_end_traversals",
        "history_distance_m",
        "history_sim_time_sec",
        "decision_distance_m",
        "decision_sim_time_sec",
        "total_distance_m",
        "total_sim_time_sec",
    ]

    rate_cols = [
        ("runner_goal_success", "runner_goal_success_rate_pct"),
        ("runner_budget_success", "runner_budget_success_rate_pct"),
        ("runner_episode_valid", "runner_valid_rate_pct"),
        ("replay_task_success", "replay_goal_success_rate_pct"),
        ("replay_budget_success", "replay_budget_success_rate_pct"),
        ("replay_episode_valid", "replay_valid_rate_pct"),
        ("replay_audit_pass", "replay_audit_pass_rate_pct"),
    ]

    records = []
    condition_order = ["D0_R", "D0_O", "D0_F", "D1_R", "D1_O", "D1_F", "D2_R", "D2_O", "D2_F", "D2_M1"]

    for cond_id in condition_order:
        sub = df[df["condition_id"] == cond_id]
        if sub.empty:
            continue

        scen = sub["scenario"].iloc[0]
        meth = sub["method"].iloc[0]
        n = len(sub)
        routes = sorted([r for r in sub["requested_route"].unique() if r is not None])
        route_str = ", ".join(routes) if routes else "UNKNOWN"

        row: Dict[str, Any] = {
            "scenario": scen,
            "method": meth,
            "condition_id": cond_id,
            "n": n,
            "requested_routes": route_str,
        }

        for m in metric_cols:
            valid_vals = sub[m].dropna().to_numpy(dtype=float)
            n_valid = len(valid_vals)
            row[f"{m}_n_valid"] = n_valid

            if n_valid == 0:
                row[f"{m}_mean"] = "NA"
                row[f"{m}_std_ddof1"] = "NA"
                row[f"{m}_min"] = "NA"
                row[f"{m}_max"] = "NA"
            else:
                row[f"{m}_mean"] = round(float(np.mean(valid_vals)), 3)
                row[f"{m}_std_ddof1"] = round(float(np.std(valid_vals, ddof=1)), 3) if n_valid > 1 else "NA"
                row[f"{m}_min"] = round(float(np.min(valid_vals)), 3)
                row[f"{m}_max"] = round(float(np.max(valid_vals)), 3)

        for col_name, out_name in rate_cols:
            valid_bools = sub[col_name].dropna().to_numpy(dtype=bool)
            n_valid_bool = len(valid_bools)
            row[f"{out_name}_n_valid"] = n_valid_bool
            if n_valid_bool == 0:
                row[out_name] = "NA"
            else:
                row[out_name] = round(float(np.mean(valid_bools) * 100.0), 1)

        records.append(row)

    return pd.DataFrame(records)


def compute_contrasts(df: pd.DataFrame) -> pd.DataFrame:
    """Compute pairwise contrasts: F - R, F - O, F - M1 across scenarios.
    
    Handles zero denominator gracefully by setting relative difference to 'NA'.
    """
    contrasts = [
        {"scenario": "D1", "method_a": "F", "method_b": "R", "comparison": "FailMem vs Reactive"},
        {"scenario": "D1", "method_a": "F", "method_b": "O", "comparison": "FailMem vs Spatial Cache"},
        {"scenario": "D2", "method_a": "F", "method_b": "M1", "comparison": "FailMem vs Persistent Memory"},
        {"scenario": "D2", "method_a": "F", "method_b": "O", "comparison": "FailMem vs Spatial Cache"},
        {"scenario": "D2", "method_a": "F", "method_b": "R", "comparison": "FailMem vs Reactive"},
        {"scenario": "D0", "method_a": "F", "method_b": "R", "comparison": "FailMem vs Reactive (Fresh)"},
        {"scenario": "D0", "method_a": "F", "method_b": "O", "comparison": "FailMem vs Spatial Cache (Fresh)"},
    ]

    metrics = [
        ("dead_end_traversals", "Dead Ends"),
        ("decision_distance_m", "Decision Dist (m)"),
        ("decision_sim_time_sec", "Decision Time (s)"),
        ("total_distance_m", "Total Dist (m)"),
        ("total_sim_time_sec", "Total Time (s)"),
    ]

    records = []
    for c in contrasts:
        scen = c["scenario"]
        ma = c["method_a"]
        mb = c["method_b"]

        sub_a = df[(df["scenario"] == scen) & (df["method"] == ma)]
        sub_b = df[(df["scenario"] == scen) & (df["method"] == mb)]

        if sub_a.empty or sub_b.empty:
            continue

        for m_col, m_label in metrics:
            vals_a = sub_a[m_col].dropna().to_numpy(dtype=float)
            vals_b = sub_b[m_col].dropna().to_numpy(dtype=float)

            n_a = len(vals_a)
            n_b = len(vals_b)

            if n_a == 0 or n_b == 0:
                continue

            mean_a = float(np.mean(vals_a))
            std_a = round(float(np.std(vals_a, ddof=1)), 3) if n_a > 1 else "NA"
            mean_b = float(np.mean(vals_b))
            std_b = round(float(np.std(vals_b, ddof=1)), 3) if n_b > 1 else "NA"

            abs_diff = mean_a - mean_b
            if abs(mean_b) > 1e-6:
                rel_diff_pct: Any = round((abs_diff / mean_b * 100.0), 2)
            else:
                rel_diff_pct = "NA"

            records.append({
                "scenario": scen,
                "comparison": c["comparison"],
                "method_a": ma,
                "method_b": mb,
                "n_a": n_a,
                "n_b": n_b,
                "metric": m_label,
                "metric_field": m_col,
                "mean_a": round(mean_a, 3),
                "std_a_ddof1": std_a,
                "mean_b": round(mean_b, 3),
                "std_b_ddof1": std_b,
                "abs_diff_a_minus_b": round(abs_diff, 3),
                "rel_diff_pct": rel_diff_pct,
            })

    return pd.DataFrame(records)


def generate_plots(df: pd.DataFrame, output_dir: Path):
    """Generate figures showing raw points for each run alongside condition means."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")

    condition_order = ["D0_R", "D0_O", "D0_F", "D1_R", "D1_O", "D1_F", "D2_R", "D2_O", "D2_F", "D2_M1"]
    colors = {
        "R": "#1f77b4",  # Blue
        "O": "#ff7f0e",  # Orange
        "F": "#2ca02c",  # Green
        "M1": "#d62728", # Red
    }

    # Filter only conditions present in data
    valid_conditions = [c for c in condition_order if not df[df["condition_id"] == c].empty]
    if not valid_conditions:
        return

    x_indices = np.arange(len(valid_conditions))

    # -------------------------------------------------------------
    # Figure 1: Distance Metrics (Decision vs Total)
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), sharey=False)

    for i, cond in enumerate(valid_conditions):
        sub = df[df["condition_id"] == cond]
        meth = sub["method"].iloc[0]
        vals = sub["decision_distance_m"].dropna().to_numpy()
        if len(vals) > 0:
            mean = np.mean(vals)
            std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            ax1.bar(i, mean, yerr=std, capsize=4, color=colors.get(meth, "#333333"), alpha=0.35, edgecolor=colors.get(meth, "#333333"), linewidth=1.5, width=0.6)
            jitter = np.linspace(-0.12, 0.12, len(vals))
            ax1.scatter(i + jitter, vals, color=colors.get(meth, "#333333"), s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax1.set_title("Decision Phase Distance (m) by Condition", fontsize=12, fontweight="bold")
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(valid_conditions, rotation=35, ha="right", fontsize=10)
    ax1.set_ylabel("Distance (m)", fontsize=11)
    ax1.set_ylim(0, 13.0)
    ax1.grid(True, linestyle="--", alpha=0.5)

    for i, cond in enumerate(valid_conditions):
        sub = df[df["condition_id"] == cond]
        meth = sub["method"].iloc[0]
        vals = sub["total_distance_m"].dropna().to_numpy()
        if len(vals) > 0:
            mean = np.mean(vals)
            std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            ax2.bar(i, mean, yerr=std, capsize=4, color=colors.get(meth, "#333333"), alpha=0.35, edgecolor=colors.get(meth, "#333333"), linewidth=1.5, width=0.6)
            jitter = np.linspace(-0.12, 0.12, len(vals))
            ax2.scatter(i + jitter, vals, color=colors.get(meth, "#333333"), s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax2.set_title("Total End-to-End Distance (m) by Condition (incl. History)", fontsize=12, fontweight="bold")
    ax2.set_xticks(x_indices)
    ax2.set_xticklabels(valid_conditions, rotation=35, ha="right", fontsize=10)
    ax2.set_ylabel("Distance (m)", fontsize=11)
    ax2.set_ylim(0, 21.0)
    ax2.grid(True, linestyle="--", alpha=0.5)

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color=colors["R"], marker="o", lw=0, label="R (Reactive)"),
        Line2D([0], [0], color=colors["O"], marker="o", lw=0, label="O (Observation Cache)"),
        Line2D([0], [0], color=colors["F"], marker="o", lw=0, label="F (FailMem Memory)"),
        Line2D([0], [0], color=colors["M1"], marker="o", lw=0, label="M1 (Persistent Memory)"),
    ]
    fig.legend(handles=legend_elements, loc="upper center", bbox_to_anchor=(0.5, 1.02), ncol=4, frameon=True, fontsize=10)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(output_dir / "p2c_distances_by_condition.png", dpi=300)
    plt.close(fig)

    # -------------------------------------------------------------
    # Figure 2: Simulation Duration Metrics (Decision vs Total)
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), sharey=False)

    for i, cond in enumerate(valid_conditions):
        sub = df[df["condition_id"] == cond]
        meth = sub["method"].iloc[0]
        vals = sub["decision_sim_time_sec"].dropna().to_numpy()
        if len(vals) > 0:
            mean = np.mean(vals)
            std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            ax1.bar(i, mean, yerr=std, capsize=4, color=colors.get(meth, "#333333"), alpha=0.35, edgecolor=colors.get(meth, "#333333"), linewidth=1.5, width=0.6)
            jitter = np.linspace(-0.12, 0.12, len(vals))
            ax1.scatter(i + jitter, vals, color=colors.get(meth, "#333333"), s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax1.set_title("Decision Phase Sim Time (s) by Condition", fontsize=12, fontweight="bold")
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(valid_conditions, rotation=35, ha="right", fontsize=10)
    ax1.set_ylabel("Simulation Time (s)", fontsize=11)
    ax1.set_ylim(0, 100.0)
    ax1.grid(True, linestyle="--", alpha=0.5)

    for i, cond in enumerate(valid_conditions):
        sub = df[df["condition_id"] == cond]
        meth = sub["method"].iloc[0]
        vals = sub["total_sim_time_sec"].dropna().to_numpy()
        if len(vals) > 0:
            mean = np.mean(vals)
            std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            ax2.bar(i, mean, yerr=std, capsize=4, color=colors.get(meth, "#333333"), alpha=0.35, edgecolor=colors.get(meth, "#333333"), linewidth=1.5, width=0.6)
            jitter = np.linspace(-0.12, 0.12, len(vals))
            ax2.scatter(i + jitter, vals, color=colors.get(meth, "#333333"), s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax2.set_title("Total End-to-End Sim Time (s) by Condition (incl. History)", fontsize=12, fontweight="bold")
    ax2.set_xticks(x_indices)
    ax2.set_xticklabels(valid_conditions, rotation=35, ha="right", fontsize=10)
    ax2.set_ylabel("Simulation Time (s)", fontsize=11)
    ax2.set_ylim(0, 180.0)
    ax2.grid(True, linestyle="--", alpha=0.5)

    fig.legend(handles=legend_elements, loc="upper center", bbox_to_anchor=(0.5, 1.02), ncol=4, frameon=True, fontsize=10)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(output_dir / "p2c_durations_by_condition.png", dpi=300)
    plt.close(fig)

    # -------------------------------------------------------------
    # Figure 3: Dead-End Traversals & Key Method Contrasts
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    for i, cond in enumerate(valid_conditions):
        sub = df[df["condition_id"] == cond]
        meth = sub["method"].iloc[0]
        vals = sub["dead_end_traversals"].dropna().to_numpy()
        if len(vals) > 0:
            mean = np.mean(vals)
            ax1.bar(i, mean, color=colors.get(meth, "#333333"), alpha=0.45, edgecolor=colors.get(meth, "#333333"), linewidth=1.5, width=0.6)
            jitter = np.linspace(-0.10, 0.10, len(vals))
            ax1.scatter(i + jitter, vals, color=colors.get(meth, "#333333"), s=50, zorder=5, edgecolors="black", linewidth=0.8)

    ax1.set_title("Dead-End Traversals (Corridor Re-entry) by Condition", fontsize=12, fontweight="bold")
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(valid_conditions, rotation=35, ha="right", fontsize=10)
    ax1.set_ylabel("Count per Episode", fontsize=11)
    ax1.set_ylim(-0.1, 1.3)
    ax1.set_yticks([0, 1])
    ax1.grid(True, linestyle="--", alpha=0.5)

    contrast_labels = ["D1: F - R", "D1: F - O", "D2: F - M1", "D2: F - O"]
    comp_keys = [
        ("D1", "F", "R"),
        ("D1", "F", "O"),
        ("D2", "F", "M1"),
        ("D2", "F", "O"),
    ]
    dist_diffs = []
    time_diffs = []
    valid_contrast_labels = []

    for idx, (scen, ma, mb) in enumerate(comp_keys):
        sub_a = df[(df["scenario"] == scen) & (df["method"] == ma)]
        sub_b = df[(df["scenario"] == scen) & (df["method"] == mb)]
        vals_da = sub_a["total_distance_m"].dropna()
        vals_db = sub_b["total_distance_m"].dropna()
        vals_ta = sub_a["total_sim_time_sec"].dropna()
        vals_tb = sub_b["total_sim_time_sec"].dropna()

        if len(vals_da) > 0 and len(vals_db) > 0:
            dist_diff = np.mean(vals_da) - np.mean(vals_db)
            time_diff = np.mean(vals_ta) - np.mean(vals_tb)
            dist_diffs.append(dist_diff)
            time_diffs.append(time_diff)
            valid_contrast_labels.append(contrast_labels[idx])

    if valid_contrast_labels:
        c_x = np.arange(len(valid_contrast_labels))
        w = 0.35
        ax2.bar(c_x - w/2, dist_diffs, width=w, label="Total Dist Diff (m)", color="#2ca02c", alpha=0.6, edgecolor="#2ca02c")
        ax2.bar(c_x + w/2, [t / 10.0 for t in time_diffs], width=w, label="Total Time Diff (scaled /10s)", color="#9467bd", alpha=0.6, edgecolor="#9467bd")

        ax2.axhline(0, color="black", linestyle="--", linewidth=0.8)
        ax2.set_title("Method Contrasts: Absolute Differences", fontsize=12, fontweight="bold")
        ax2.set_xticks(c_x)
        ax2.set_xticklabels(valid_contrast_labels, fontsize=10)
        ax2.set_ylabel("Difference (Negative = F saves cost)", fontsize=11)
        ax2.legend(loc="lower right", frameon=True, fontsize=10)
        ax2.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig.savefig(output_dir / "p2c_dead_ends_and_contrasts.png", dpi=300)
    plt.close(fig)


def analyze_p2c_run(
    run_dir: Path,
    output_dir: Optional[Path] = None,
    expected_episodes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute complete analysis pipeline on a P2c run evidence directory."""
    out_dir = output_dir if output_dir else (run_dir / "analysis")
    out_dir.mkdir(parents=True, exist_ok=True)

    episodes, integrity_report = load_and_verify_run_episodes(run_dir, expected_episodes)
    
    # Save integrity report to disk
    with open(out_dir / "integrity_report.json", "w", encoding="utf-8") as f:
        json.dump(integrity_report, f, indent=2)

    df_episodes = pd.DataFrame(episodes)
    episodes_csv = out_dir / "episodes.csv"
    df_episodes.to_csv(episodes_csv, index=False)

    df_summary = compute_condition_summary(df_episodes)
    summary_csv = out_dir / "condition_summary.csv"
    df_summary.to_csv(summary_csv, index=False)

    df_contrasts = compute_contrasts(df_episodes)
    contrasts_csv = out_dir / "contrasts.csv"
    df_contrasts.to_csv(contrasts_csv, index=False)

    generate_plots(df_episodes, out_dir)

    return {
        "integrity_report": integrity_report,
        "episodes_df": df_episodes,
        "summary_df": df_summary,
        "contrasts_df": df_contrasts,
        "output_dir": out_dir,
    }


def main():
    parser = argparse.ArgumentParser(description="P2c Statistical Analysis and Reporting Utility")
    parser.add_argument("run_dir", help="Path to P2c run evidence directory")
    parser.add_argument("--output-dir", default=None, help="Directory to save CSVs and plots (default: run_dir/analysis)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"Error: Run directory '{run_dir}' does not exist.")
        sys.exit(1)

    res = analyze_p2c_run(run_dir, Path(args.output_dir) if args.output_dir else None)
    integ = res["integrity_report"]

    print("=========================================================================================================")
    print("P2c Evidence Integrity & Accounting Check:")
    print("---------------------------------------------------------------------------------------------------------")
    print(f"Integrity Check Passed:        {integ['integrity_check_passed']}")
    print(f"Expected Episodes:             {integ['expected_episodes_count']}")
    print(f"Actual Discovered Directories: {integ['actual_found_count']}")
    print(f"Data-Complete Episodes:        {integ['data_complete_count']}")
    print(f"Runner-Valid Episodes:         {integ['runner_valid_count']}")
    print(f"Replay Audit-Passed Episodes:  {integ['replay_audit_pass_count']}")
    print(f"Conflicts Count:               {integ['conflicts_count']}")

    if integ.get("extra_episodes"):
        print(f"\n[WARNING] Unexpected Extra Episodes ({len(integ['extra_episodes'])}):")
        for m in integ["extra_episodes"]:
            print(f"  - {m}")

    if integ.get("identity_mismatches"):
        print(f"\n[ERROR] Identity / Metadata Mismatches ({len(integ['identity_mismatches'])}):")
        for m in integ["identity_mismatches"]:
            print(f"  - Episode {m['episode_id']}: {', '.join(m['reasons'])}")

    if integ.get("invalid_action_results"):
        print(f"\n[ERROR] Invalid / Incomplete action_result.json fields ({len(integ['invalid_action_results'])}):")
        for m in integ["invalid_action_results"]:
            print(f"  - Episode {m['episode_id']}: {', '.join(m['issues'])}")

    if integ.get("duplicate_replay_ids"):
        print(f"\n[ERROR] Duplicate Replay IDs in replay summary ({len(integ['duplicate_replay_ids'])}):")
        for m in integ["duplicate_replay_ids"]:
            print(f"  - {m}")

    if integ["missing_expected_episodes"]:
        print(f"\n[WARNING] Missing Expected Episodes ({len(integ['missing_expected_episodes'])}):")
        for m in integ["missing_expected_episodes"]:
            print(f"  - {m}")

    if integ["missing_action_results"]:
        print(f"\n[ERROR] Missing action_result.json in directories ({len(integ['missing_action_results'])}):")
        for m in integ["missing_action_results"]:
            print(f"  - {m}")

    if integ["conflicts"]:
        print(f"\n[WARNING] Verdict Conflicts ({len(integ['conflicts'])}):")
        for c in integ["conflicts"]:
            print(f"  - Episode {c['episode_id']}: {', '.join(c['reasons'])}")

    print("\n=========================================================================================================")
    print("P2c Condition Summary Table (Sample Std Dev ddof=1, Independent Unpaired):")
    print("---------------------------------------------------------------------------------------------------------")
    print("| Scenario | Method | n | Route | Dead-Ends | Decision Dist (m) | Decision Time (s) | Total Dist (m) | Total Time (s) | Runner Valid | Replay Audit |")
    print("| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for _, r in res["summary_df"].iterrows():
        dec_d_std = f"± {r['decision_distance_m_std_ddof1']:.2f}" if r['decision_distance_m_std_ddof1'] != "NA" else "NA"
        dec_d_str = f"{r['decision_distance_m_mean']} {dec_d_std}" if r['decision_distance_m_mean'] != "NA" else "NA"

        dec_t_std = f"± {r['decision_sim_time_sec_std_ddof1']:.1f}" if r['decision_sim_time_sec_std_ddof1'] != "NA" else "NA"
        dec_t_str = f"{r['decision_sim_time_sec_mean']} {dec_t_std}" if r['decision_sim_time_sec_mean'] != "NA" else "NA"

        tot_d_std = f"± {r['total_distance_m_std_ddof1']:.2f}" if r['total_distance_m_std_ddof1'] != "NA" else "NA"
        tot_d_str = f"{r['total_distance_m_mean']} {tot_d_std}" if r['total_distance_m_mean'] != "NA" else "NA"

        tot_t_std = f"± {r['total_sim_time_sec_std_ddof1']:.1f}" if r['total_sim_time_sec_std_ddof1'] != "NA" else "NA"
        tot_t_str = f"{r['total_sim_time_sec_mean']} {tot_t_std}" if r['total_sim_time_sec_mean'] != "NA" else "NA"

        rv_rate = f"{r['runner_valid_rate_pct']:.0f}%" if r['runner_valid_rate_pct'] != "NA" else "NA"
        ra_rate = f"{r['replay_audit_pass_rate_pct']:.0f}%" if r['replay_audit_pass_rate_pct'] != "NA" else "NA"

        print(f"| {r['scenario']:8s} | {r['method']:6s} | {r['n']:1d} | {r['requested_routes']:18s} | {r['dead_end_traversals_mean']} | {dec_d_str:17s} | {dec_t_str:17s} | {tot_d_str:14s} | {tot_t_str:14s} | {rv_rate:12s} | {ra_rate:12s} |")

    print("\n=========================================================================================================")
    print("Key Pairwise Contrasts (ddof=1, Unpaired Samples):")
    print("---------------------------------------------------------------------------------------------------------")
    print("| Scenario | Comparison | Metric | Method A Mean ± Std | Method B Mean ± Std | Abs Diff (A - B) | Rel Diff (%) |")
    print("| :--- | :--- | :--- | :--- | :--- | :---: | :---: |")
    for _, c in res["contrasts_df"].iterrows():
        a_std = f"± {c['std_a_ddof1']:.2f}" if c['std_a_ddof1'] != "NA" else "NA"
        b_std = f"± {c['std_b_ddof1']:.2f}" if c['std_b_ddof1'] != "NA" else "NA"
        a_str = f"{c['mean_a']} {a_std}"
        b_str = f"{c['mean_b']} {b_std}"
        rel_str = f"{c['rel_diff_pct']:+.1f}%" if c['rel_diff_pct'] != "NA" else "NA"
        print(f"| {c['scenario']:8s} | {c['comparison']:28s} | {c['metric']:20s} | {a_str:19s} | {b_str:19s} | {c['abs_diff_a_minus_b']:+10.2f} | {rel_str:12s} |")
    print("=========================================================================================================\n")

    if not integ["integrity_check_passed"]:
        print("[CRITICAL ERROR] Integrity check failed. Exiting with non-zero status code.")
        sys.exit(1)


if __name__ == "__main__":
    main()
