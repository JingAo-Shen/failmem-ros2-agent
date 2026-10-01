#!/usr/bin/env python3
"""Unified Statistical Analysis and Visualization for Milestone P2c Experiments.

Loads raw evidence from a P2c run directory and produces:
1. episodes.csv: Complete per-episode record of metrics, stages, and audit verdicts.
2. condition_summary.csv: Condition-level aggregated statistics (n, mean, sample std ddof=1, min, max).
3. contrasts.csv: Pairwise contrasts (F vs R, F vs O, F vs M1) in absolute and relative terms.
4. Publication-ready visualization figures with raw data points and group distributions.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_run_episodes(run_dir: Path) -> List[Dict[str, Any]]:
    """Load per-episode data by joining action_result.json and replay audit results."""
    replay_summary_file = run_dir / "p2c_replay_summary.json"
    audit_by_ep: Dict[str, Dict[str, Any]] = {}
    if replay_summary_file.exists():
        with open(replay_summary_file, "r", encoding="utf-8") as f:
            rep_data = json.load(f)
            for ep in rep_data.get("episodes", []):
                audit_by_ep[ep["episode_id"]] = ep

    episodes: List[Dict[str, Any]] = []
    ep_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir() and any(k in d.name for k in ["D0_", "D1_", "D2_"])])

    for ep_dir in ep_dirs:
        act_file = ep_dir / "action_result.json"
        if not act_file.exists():
            continue
        with open(act_file, "r", encoding="utf-8") as f:
            act = json.load(f)

        ep_id = act.get("episode_id", ep_dir.name)
        audit_info = audit_by_ep.get(ep_id, {})

        ep_num = 1
        if "_ep" in ep_id:
            try:
                ep_num = int(ep_id.split("_ep")[-1])
            except ValueError:
                pass

        record = {
            "episode_id": ep_id,
            "scenario": act.get("scenario", ep_id.split("_")[0]),
            "method": act.get("method", ep_id.split("_")[1]),
            "condition_id": act.get("condition_id", f"{act.get('scenario')}_{act.get('method')}"),
            "ep_num": ep_num,
            "requested_route": act.get("requested_route", act.get("chosen_route", "UNKNOWN")),
            "actual_route": act.get("actual_route", audit_info.get("actual_route", "UNKNOWN")),
            "dead_end_traversals": int(act.get("dead_end_traversals", audit_info.get("dead_end_traversals", 0))),
            "decision_dispatches": int(act.get("decision_dispatches", 0)),
            "history_distance_m": float(act.get("history_distance_m", 0.0)),
            "history_sim_time_sec": float(act.get("history_sim_time_sec", 0.0)),
            "decision_distance_m": float(act.get("decision_distance_m", 0.0)),
            "decision_sim_time_sec": float(act.get("decision_sim_time_sec", 0.0)),
            "total_distance_m": float(act.get("total_distance_m", 0.0)),
            "replayed_total_dist_m": float(audit_info.get("replayed_total_dist_m", act.get("total_distance_m", 0.0))),
            "distance_discrepancy_m": float(audit_info.get("distance_discrepancy_m", 0.0)),
            "total_sim_time_sec": float(act.get("total_sim_time_sec", 0.0)),
            "total_budget_sec": float(act.get("total_budget_sec", 180.0)),
            "final_goal_success": bool(act.get("final_goal_success", False)),
            "success_within_budget": bool(act.get("success_within_budget", False)),
            "history_valid": bool(act.get("history_valid", audit_info.get("history_valid", False))),
            "route_valid": bool(act.get("route_valid", audit_info.get("route_valid", False))),
            "costmap_valid": bool(audit_info.get("costmap_valid", True)),
            "raw_evidence_verified": bool(audit_info.get("raw_evidence_verified", True)),
            "memory_lifecycle_verified": bool(audit_info.get("memory_lifecycle_verified", True)),
            "policy_matched": bool(audit_info.get("policy_matched", True)),
            "episode_valid": bool(act.get("episode_valid", audit_info.get("episode_valid", False))),
            "audit_pass": bool(audit_info.get("audit_pass", False)),
        }
        episodes.append(record)

    return episodes


def compute_condition_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Compute condition summary statistics with sample standard deviation (ddof=1)."""
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
        "final_goal_success",
        "success_within_budget",
        "history_valid",
        "route_valid",
        "episode_valid",
        "audit_pass",
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
        routes = sorted(sub["requested_route"].unique().tolist())
        route_str = ", ".join(routes)

        row = {
            "scenario": scen,
            "method": meth,
            "condition_id": cond_id,
            "n": n,
            "requested_routes": route_str,
        }

        for m in metric_cols:
            vals = sub[m].to_numpy(dtype=float)
            row[f"{m}_mean"] = round(float(np.mean(vals)), 3)
            row[f"{m}_std_ddof1"] = round(float(np.std(vals, ddof=1)), 3) if n > 1 else 0.0
            row[f"{m}_min"] = round(float(np.min(vals)), 3)
            row[f"{m}_max"] = round(float(np.max(vals)), 3)

        for r in rate_cols:
            vals = sub[r].to_numpy(dtype=bool)
            row[f"{r}_rate_pct"] = round(float(np.mean(vals) * 100.0), 1)

        records.append(row)

    return pd.DataFrame(records)


def compute_contrasts(df: pd.DataFrame) -> pd.DataFrame:
    """Compute pairwise contrasts: F - R, F - O, F - M1 across scenarios."""
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

        n_a = len(sub_a)
        n_b = len(sub_b)

        for m_col, m_label in metrics:
            vals_a = sub_a[m_col].to_numpy(dtype=float)
            vals_b = sub_b[m_col].to_numpy(dtype=float)

            mean_a = float(np.mean(vals_a))
            std_a = float(np.std(vals_a, ddof=1)) if n_a > 1 else 0.0
            mean_b = float(np.mean(vals_b))
            std_b = float(np.std(vals_b, ddof=1)) if n_b > 1 else 0.0

            abs_diff = mean_a - mean_b
            rel_diff_pct = (abs_diff / mean_b * 100.0) if abs(mean_b) > 1e-6 else 0.0

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
                "std_a_ddof1": round(std_a, 3),
                "mean_b": round(mean_b, 3),
                "std_b_ddof1": round(std_b, 3),
                "abs_diff_a_minus_b": round(abs_diff, 3),
                "rel_diff_pct": round(rel_diff_pct, 2),
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

    # -------------------------------------------------------------
    # Figure 1: Distance Metrics (Decision vs Total)
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), sharey=False)

    x_indices = np.arange(len(condition_order))

    # Subplot 1: Decision Phase Distance
    for i, cond in enumerate(condition_order):
        sub = df[df["condition_id"] == cond]
        if sub.empty:
            continue
        meth = sub["method"].iloc[0]
        vals = sub["decision_distance_m"].to_numpy()
        mean = np.mean(vals)
        std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0

        # Draw mean bar / error bar
        ax1.bar(i, mean, yerr=std, capsize=4, color=colors[meth], alpha=0.35, edgecolor=colors[meth], linewidth=1.5, width=0.6)
        # Overlay raw data points (with slight jitter)
        jitter = np.linspace(-0.12, 0.12, len(vals))
        ax1.scatter(i + jitter, vals, color=colors[meth], s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax1.set_title("Decision Phase Distance (m) by Condition", fontsize=12, fontweight="bold")
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(condition_order, rotation=35, ha="right", fontsize=10)
    ax1.set_ylabel("Distance (m)", fontsize=11)
    ax1.set_ylim(0, 13.0)
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Subplot 2: Total End-to-End Distance
    for i, cond in enumerate(condition_order):
        sub = df[df["condition_id"] == cond]
        if sub.empty:
            continue
        meth = sub["method"].iloc[0]
        vals = sub["total_distance_m"].to_numpy()
        mean = np.mean(vals)
        std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0

        ax2.bar(i, mean, yerr=std, capsize=4, color=colors[meth], alpha=0.35, edgecolor=colors[meth], linewidth=1.5, width=0.6)
        jitter = np.linspace(-0.12, 0.12, len(vals))
        ax2.scatter(i + jitter, vals, color=colors[meth], s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax2.set_title("Total End-to-End Distance (m) by Condition (incl. History)", fontsize=12, fontweight="bold")
    ax2.set_xticks(x_indices)
    ax2.set_xticklabels(condition_order, rotation=35, ha="right", fontsize=10)
    ax2.set_ylabel("Distance (m)", fontsize=11)
    ax2.set_ylim(0, 21.0)
    ax2.grid(True, linestyle="--", alpha=0.5)

    # Add custom legend
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

    # Subplot 1: Decision Phase Sim Time
    for i, cond in enumerate(condition_order):
        sub = df[df["condition_id"] == cond]
        if sub.empty:
            continue
        meth = sub["method"].iloc[0]
        vals = sub["decision_sim_time_sec"].to_numpy()
        mean = np.mean(vals)
        std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0

        ax1.bar(i, mean, yerr=std, capsize=4, color=colors[meth], alpha=0.35, edgecolor=colors[meth], linewidth=1.5, width=0.6)
        jitter = np.linspace(-0.12, 0.12, len(vals))
        ax1.scatter(i + jitter, vals, color=colors[meth], s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax1.set_title("Decision Phase Sim Time (s) by Condition", fontsize=12, fontweight="bold")
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(condition_order, rotation=35, ha="right", fontsize=10)
    ax1.set_ylabel("Simulation Time (s)", fontsize=11)
    ax1.set_ylim(0, 100.0)
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Subplot 2: Total End-to-End Sim Time
    for i, cond in enumerate(condition_order):
        sub = df[df["condition_id"] == cond]
        if sub.empty:
            continue
        meth = sub["method"].iloc[0]
        vals = sub["total_sim_time_sec"].to_numpy()
        mean = np.mean(vals)
        std = np.std(vals, ddof=1) if len(vals) > 1 else 0.0

        ax2.bar(i, mean, yerr=std, capsize=4, color=colors[meth], alpha=0.35, edgecolor=colors[meth], linewidth=1.5, width=0.6)
        jitter = np.linspace(-0.12, 0.12, len(vals))
        ax2.scatter(i + jitter, vals, color=colors[meth], s=45, zorder=5, edgecolors="black", linewidth=0.8, alpha=0.9)

    ax2.set_title("Total End-to-End Sim Time (s) by Condition (incl. History)", fontsize=12, fontweight="bold")
    ax2.set_xticks(x_indices)
    ax2.set_xticklabels(condition_order, rotation=35, ha="right", fontsize=10)
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

    # Subplot 1: Dead-End Traversals (Entrance Re-entry count)
    for i, cond in enumerate(condition_order):
        sub = df[df["condition_id"] == cond]
        if sub.empty:
            continue
        meth = sub["method"].iloc[0]
        vals = sub["dead_end_traversals"].to_numpy()
        mean = np.mean(vals)
        ax1.bar(i, mean, color=colors[meth], alpha=0.45, edgecolor=colors[meth], linewidth=1.5, width=0.6)
        jitter = np.linspace(-0.10, 0.10, len(vals))
        ax1.scatter(i + jitter, vals, color=colors[meth], s=50, zorder=5, edgecolors="black", linewidth=0.8)

    ax1.set_title("Dead-End Traversals (Corridor Re-entry) by Condition", fontsize=12, fontweight="bold")
    ax1.set_xticks(x_indices)
    ax1.set_xticklabels(condition_order, rotation=35, ha="right", fontsize=10)
    ax1.set_ylabel("Count per Episode", fontsize=11)
    ax1.set_ylim(-0.1, 1.3)
    ax1.set_yticks([0, 1])
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Subplot 2: Contrasts Absolute Differences
    contrast_labels = ["D1: F - R", "D1: F - O", "D2: F - M1", "D2: F - O"]
    comp_keys = [
        ("D1", "F", "R"),
        ("D1", "F", "O"),
        ("D2", "F", "M1"),
        ("D2", "F", "O"),
    ]
    dist_diffs = []
    time_diffs = []
    for scen, ma, mb in comp_keys:
        sub_a = df[(df["scenario"] == scen) & (df["method"] == ma)]
        sub_b = df[(df["scenario"] == scen) & (df["method"] == mb)]
        dist_diff = np.mean(sub_a["total_distance_m"]) - np.mean(sub_b["total_distance_m"])
        time_diff = np.mean(sub_a["total_sim_time_sec"]) - np.mean(sub_b["total_sim_time_sec"])
        dist_diffs.append(dist_diff)
        time_diffs.append(time_diff)

    c_x = np.arange(len(contrast_labels))
    w = 0.35
    ax2.bar(c_x - w/2, dist_diffs, width=w, label="Total Dist Diff (m)", color="#2ca02c", alpha=0.6, edgecolor="#2ca02c")
    ax2.bar(c_x + w/2, [t / 10.0 for t in time_diffs], width=w, label="Total Time Diff (scaled /10s)", color="#9467bd", alpha=0.6, edgecolor="#9467bd")

    ax2.axhline(0, color="black", linestyle="--", linewidth=0.8)
    ax2.set_title("Method Contrasts: Absolute Differences", fontsize=12, fontweight="bold")
    ax2.set_xticks(c_x)
    ax2.set_xticklabels(contrast_labels, fontsize=10)
    ax2.set_ylabel("Difference (Negative = F saves cost)", fontsize=11)
    ax2.legend(loc="lower right", frameon=True, fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig.savefig(output_dir / "p2c_dead_ends_and_contrasts.png", dpi=300)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="P2c Statistical Analysis and Reporting Utility")
    parser.add_argument("run_dir", help="Path to P2c run evidence directory")
    parser.add_argument("--output-dir", default=None, help="Directory to save CSVs and plots (default: run_dir/analysis)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"Error: Run directory '{run_dir}' does not exist.")
        sys.exit(1)

    out_dir = Path(args.output_dir) if args.output_dir else (run_dir / "analysis")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading episodes from: {run_dir}")
    episodes = load_run_episodes(run_dir)
    if not episodes:
        print("No valid episodes found in run directory.")
        sys.exit(1)

    df_episodes = pd.DataFrame(episodes)
    episodes_csv = out_dir / "episodes.csv"
    df_episodes.to_csv(episodes_csv, index=False)
    print(f"Saved episodes record: {episodes_csv} ({len(df_episodes)} rows)")

    df_summary = compute_condition_summary(df_episodes)
    summary_csv = out_dir / "condition_summary.csv"
    df_summary.to_csv(summary_csv, index=False)
    print(f"Saved condition summary: {summary_csv} ({len(df_summary)} conditions)")

    df_contrasts = compute_contrasts(df_episodes)
    contrasts_csv = out_dir / "contrasts.csv"
    df_contrasts.to_csv(contrasts_csv, index=False)
    print(f"Saved pairwise contrasts: {contrasts_csv} ({len(df_contrasts)} contrast rows)")

    generate_plots(df_episodes, out_dir)
    print(f"Saved visualization plots in: {out_dir}")

    # Print markdown tables for easy verification
    print("\n=========================================================================================================")
    print("P2c Condition Summary Table (Sample Std Dev ddof=1):")
    print("---------------------------------------------------------------------------------------------------------")
    print("| Scenario | Method | n | Route | Dead-Ends | Decision Dist (m) | Decision Time (s) | Total Dist (m) | Total Time (s) | Arrival Rate | Audit Pass |")
    print("| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for _, r in df_summary.iterrows():
        dec_d_str = f"{r['decision_distance_m_mean']:.2f} ± {r['decision_distance_m_std_ddof1']:.2f}"
        dec_t_str = f"{r['decision_sim_time_sec_mean']:.1f} ± {r['decision_sim_time_sec_std_ddof1']:.1f}"
        tot_d_str = f"{r['total_distance_m_mean']:.2f} ± {r['total_distance_m_std_ddof1']:.2f}"
        tot_t_str = f"{r['total_sim_time_sec_mean']:.1f} ± {r['total_sim_time_sec_std_ddof1']:.1f}"
        print(f"| {r['scenario']:8s} | {r['method']:6s} | {r['n']:1d} | {r['requested_routes']:18s} | {r['dead_end_traversals_mean']:.1f} | {dec_d_str:17s} | {dec_t_str:17s} | {tot_d_str:14s} | {tot_t_str:14s} | {r['final_goal_success_rate_pct']:.0f}% | {r['audit_pass_rate_pct']:.0f}% |")

    print("\n=========================================================================================================")
    print("Key Pairwise Contrasts (ddof=1, Unpaired Samples):")
    print("---------------------------------------------------------------------------------------------------------")
    print("| Scenario | Comparison | Metric | Method A Mean ± Std | Method B Mean ± Std | Abs Diff (A - B) | Rel Diff (%) |")
    print("| :--- | :--- | :--- | :--- | :--- | :---: | :---: |")
    for _, c in df_contrasts.iterrows():
        a_str = f"{c['mean_a']:.2f} ± {c['std_a_ddof1']:.2f}"
        b_str = f"{c['mean_b']:.2f} ± {c['std_b_ddof1']:.2f}"
        print(f"| {c['scenario']:8s} | {c['comparison']:25s} | {c['metric']:20s} | {a_str:19s} | {b_str:19s} | {c['abs_diff_a_minus_b']:+10.2f} | {c['rel_diff_pct']:+8.1f}% |")
    print("=========================================================================================================\n")


if __name__ == "__main__":
    main()
