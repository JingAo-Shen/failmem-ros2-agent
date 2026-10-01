#!/usr/bin/env python3
"""Generate LaTeX and Markdown tables for the FailMem paper directly from analysis CSVs.

Outputs:
- paper/tables/table1_condition_summary.tex / .md
- paper/tables/table2_pairwise_contrasts.tex / .md
- paper/tables/table3_h1_feasibility.tex / .md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ANALYSIS_DIR = REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35" / "analysis"
DEFAULT_H1_FILE = REPO_ROOT / "reports" / "evidence" / "p2d_h1_feasibility" / "derived" / "h1_feasibility_parsed.json"
DEFAULT_TABLES_DIR = REPO_ROOT / "paper" / "tables"


def generate_table1(analysis_dir: Path, output_dir: Path) -> Tuple[str, str]:
    """Generate Table 1: Condition-Level Navigation Performance."""
    summary_csv = analysis_dir / "condition_summary.csv"
    episodes_csv = analysis_dir / "episodes.csv"

    if not summary_csv.exists():
        raise FileNotFoundError(f"Missing required condition summary CSV: {summary_csv}")
    if not episodes_csv.exists():
        raise FileNotFoundError(f"Missing required episodes CSV: {episodes_csv}")

    df_summary = pd.read_csv(summary_csv)
    df_episodes = pd.read_csv(episodes_csv)

    md_lines = [
        "| Scenario | Condition | $n$ | Actual Route | Dead-End Traversals | Decision Dist (m) | Decision Time (s) | Total Dist (m) | Total Time (s) | Replay Audit Pass |",
        "| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    tex_lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Condition-Level Navigation Performance Across 30 Physical Simulation Runs ($n=3$ per condition, mean $\pm$ sample std dev, $ddof=1$).}",
        r"\label{tab:condition_summary}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{llclccccc}",
        r"\hline",
        r"Scenario & Method & $n$ & Actual Route & Dead-Ends & Decision Dist (m) & Decision Time (s) & Total Dist (m) & Total Time (s) \\",
        r"\hline",
    ]

    for _, row in df_summary.iterrows():
        scen = str(row["scenario"])
        meth = str(row["method"])
        cond_id = str(row.get("condition_id", f"{scen}_{meth}"))
        n = int(row["n"])

        # Aggregate actual route from episodes.csv
        sub_ep = df_episodes[df_episodes["condition_id"] == cond_id]
        if not sub_ep.empty and "actual_route" in sub_ep.columns:
            actual_routes = sub_ep["actual_route"].dropna().unique()
            if len(actual_routes) == 1:
                route_str = f"`{actual_routes[0]}`"
                tex_route_str = str(actual_routes[0]).replace("_", r"\_")
            else:
                route_counts = sub_ep["actual_route"].value_counts()
                route_str = ", ".join(f"`{k}` ({v})" for k, v in route_counts.items())
                tex_route_str = ", ".join(f"{str(k).replace('_', r'\_')} ({v})" for k, v in route_counts.items())
        else:
            route_str = f"`{row.get('requested_routes', 'NA')}`"
            tex_route_str = str(row.get("requested_routes", "NA")).replace("_", r"\_")

        # Compute audit pass rate from episodes.csv
        if not sub_ep.empty and "audit_pass" in sub_ep.columns:
            n_total = len(sub_ep)
            n_pass = int(sub_ep["audit_pass"].astype(bool).sum())
            pct = (n_pass / n_total * 100.0) if n_total > 0 else 0.0
            audit_str = f"{n_pass}/{n_total} ({pct:.0f}\\%)"
        else:
            audit_str = "NA"

        de = f"{row['dead_end_traversals_mean']:.1f} $\\pm$ {row['dead_end_traversals_std_ddof1']:.1f}"
        dec_d = f"{row['decision_distance_m_mean']:.3f} $\\pm$ {row['decision_distance_m_std_ddof1']:.3f}"
        dec_t = f"{row['decision_sim_time_sec_mean']:.3f} $\\pm$ {row['decision_sim_time_sec_std_ddof1']:.3f}"
        tot_d = f"{row['total_distance_m_mean']:.3f} $\\pm$ {row['total_distance_m_std_ddof1']:.3f}"
        tot_t = f"{row['total_sim_time_sec_mean']:.3f} $\\pm$ {row['total_sim_time_sec_std_ddof1']:.3f}"

        md_lines.append(
            f"| **{scen}** | ${meth}$ | {n} | {route_str} | {de} | {dec_d} | {dec_t} | {tot_d} | {tot_t} | {audit_str} |"
        )

        tex_lines.append(
            f"{scen} & {meth} & {n} & {tex_route_str} & {row['dead_end_traversals_mean']:.1f} $\\pm$ {row['dead_end_traversals_std_ddof1']:.1f} & {row['decision_distance_m_mean']:.2f} $\\pm$ {row['decision_distance_m_std_ddof1']:.2f} & {row['decision_sim_time_sec_mean']:.1f} $\\pm$ {row['decision_sim_time_sec_std_ddof1']:.1f} & {row['total_distance_m_mean']:.2f} $\\pm$ {row['total_distance_m_std_ddof1']:.2f} & {row['total_sim_time_sec_mean']:.1f} $\\pm$ {row['total_sim_time_sec_std_ddof1']:.1f} \\\\"
        )

    tex_lines.extend([
        r"\hline",
        r"\end{tabular}%",
        r"}",
        r"\end{table*}",
    ])

    output_dir.mkdir(parents=True, exist_ok=True)
    md_content = "\n".join(md_lines) + "\n"
    tex_content = "\n".join(tex_lines) + "\n"

    with open(output_dir / "table1_condition_summary.md", "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(output_dir / "table1_condition_summary.tex", "w", encoding="utf-8") as f:
        f.write(tex_content)

    return md_content, tex_content


def generate_table2(analysis_dir: Path, output_dir: Path) -> Tuple[str, str]:
    """Generate Table 2: Key Pairwise Contrasts."""
    contrasts_csv = analysis_dir / "contrasts.csv"
    summary_csv = analysis_dir / "condition_summary.csv"

    if not contrasts_csv.exists():
        raise FileNotFoundError(f"Missing required contrasts CSV: {contrasts_csv}")
    if not summary_csv.exists():
        raise FileNotFoundError(f"Missing required condition summary CSV: {summary_csv}")

    df_contrasts = pd.read_csv(contrasts_csv)
    df_summary = pd.read_csv(summary_csv)

    # 10 expected pairwise contrast entries (5 comparisons x 2 metrics)
    target_comparisons = [
        ("D1", "F", "R", "FailMem vs Reactive", "$F$ vs. $R$", "Total Dist (m)", "total_distance_m"),
        ("D1", "F", "R", "FailMem vs Reactive", "$F$ vs. $R$", "Total Time (s)", "total_sim_time_sec"),
        ("D1", "O", "R", "Spatial Cache vs Reactive", "$O$ vs. $R$", "Total Dist (m)", "total_distance_m"),
        ("D1", "O", "R", "Spatial Cache vs Reactive", "$O$ vs. $R$", "Total Time (s)", "total_sim_time_sec"),
        ("D1", "F", "O", "FailMem vs Spatial Cache", "$F$ vs. $O$", "Total Dist (m)", "total_distance_m"),
        ("D1", "F", "O", "FailMem vs Spatial Cache", "$F$ vs. $O$", "Total Time (s)", "total_sim_time_sec"),
        ("D2", "F", "M1", "FailMem vs Persistent Memory", "$F$ vs. $M1$", "Total Dist (m)", "total_distance_m"),
        ("D2", "F", "M1", "FailMem vs Persistent Memory", "$F$ vs. $M1$", "Total Time (s)", "total_sim_time_sec"),
        ("D2", "F", "O", "FailMem vs Spatial Cache", "$F$ vs. $O$", "Total Dist (m)", "total_distance_m"),
        ("D2", "F", "O", "FailMem vs Spatial Cache", "$F$ vs. $O$", "Total Time (s)", "total_sim_time_sec"),
    ]

    md_lines = [
        "| Scenario | Comparison | Metric | Method A Mean | Method B Mean | Abs Diff ($A - B$) | Rel Diff (%) |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: |",
    ]

    tex_lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Key Pairwise Contrasts Between Methods Across Scenarios D1 and D2.}",
        r"\label{tab:pairwise_contrasts}",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lllcccc}",
        r"\hline",
        r"Scenario & Comparison & Metric & $A$ Mean & $B$ Mean & Abs Diff ($A-B$) & Rel Diff (\%) \\",
        r"\hline",
    ]

    for scen, ma, mb, comp_name, disp_comp, metric_label, metric_col in target_comparisons:
        # Check if row exists in df_contrasts
        sub_c = df_contrasts[
            (df_contrasts["scenario"] == scen)
            & (df_contrasts["method_a"] == ma)
            & (df_contrasts["method_b"] == mb)
            & (df_contrasts["metric_field"] == metric_col)
        ]

        if not sub_c.empty:
            row_c = sub_c.iloc[0]
            mean_a = float(row_c["mean_a"])
            mean_b = float(row_c["mean_b"])
            abs_diff = float(row_c["abs_diff_a_minus_b"])
            rel_diff_raw = row_c["rel_diff_pct"]
            rel_diff = float(rel_diff_raw) if rel_diff_raw != "NA" and not pd.isna(rel_diff_raw) else None
        else:
            # Calculate from df_summary directly
            sub_sum_a = df_summary[(df_summary["scenario"] == scen) & (df_summary["method"] == ma)]
            sub_sum_b = df_summary[(df_summary["scenario"] == scen) & (df_summary["method"] == mb)]

            if sub_sum_a.empty or sub_sum_b.empty:
                raise ValueError(
                    f"Cannot compute contrast {disp_comp} in scenario {scen}: missing summary data for {ma} or {mb}"
                )

            mean_a = float(sub_sum_a[f"{metric_col}_mean"].iloc[0])
            mean_b = float(sub_sum_b[f"{metric_col}_mean"].iloc[0])
            abs_diff = mean_a - mean_b
            rel_diff = (abs_diff / mean_b * 100.0) if abs(mean_b) > 1e-6 else None

        # Format strings
        mean_a_str = f"{mean_a:.3f}"
        mean_b_str = f"{mean_b:.3f}"
        abs_diff_str = f"{abs_diff:+.3f}"
        if rel_diff is not None:
            rel_diff_str = f"**{rel_diff:+.1f}\\%**" if abs(rel_diff) >= 5.0 else f"{rel_diff:+.1f}\\%"
            tex_rel_str = f"{rel_diff:+.1f}\\%"
        else:
            rel_diff_str = "NA"
            tex_rel_str = "NA"

        md_lines.append(
            f"| **{scen}** | {disp_comp} | {metric_label} | {mean_a_str} | {mean_b_str} | {abs_diff_str} | {rel_diff_str} |"
        )

        tex_metric = metric_label.replace(" (m)", " [m]").replace(" (s)", " [s]")
        tex_lines.append(
            f"{scen} & {disp_comp} & {tex_metric} & {mean_a:.2f} & {mean_b:.2f} & {abs_diff:+.2f} & {tex_rel_str} \\\\"
        )

    tex_lines.extend([
        r"\hline",
        r"\end{tabular}%",
        r"}",
        r"\end{table}",
    ])

    output_dir.mkdir(parents=True, exist_ok=True)
    md_content = "\n".join(md_lines) + "\n"
    tex_content = "\n".join(tex_lines) + "\n"

    with open(output_dir / "table2_pairwise_contrasts.md", "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(output_dir / "table2_pairwise_contrasts.tex", "w", encoding="utf-8") as f:
        f.write(tex_content)

    return md_content, tex_content


def generate_table3(h1_file_or_dir: Path, output_dir: Path) -> Tuple[str, str]:
    """Generate Table 3: Hypothesis H1 Feasibility Results."""
    h1_file = h1_file_or_dir
    if h1_file.is_dir():
        candidate_1 = h1_file / "derived" / "h1_feasibility_parsed.json"
        candidate_2 = h1_file / "h1_feasibility_parsed.json"
        if candidate_1.exists():
            h1_file = candidate_1
        elif candidate_2.exists():
            h1_file = candidate_2
        else:
            raise FileNotFoundError(f"Missing h1_feasibility_parsed.json in directory: {h1_file_or_dir}")

    if not h1_file.exists():
        raise FileNotFoundError(f"Missing required H1 parsed evidence file: {h1_file}")

    with open(h1_file, "r", encoding="utf-8") as f:
        h1_data = json.load(f)

    runs = h1_data.get("runs", [])
    if not runs:
        raise ValueError(f"No run records found in H1 evidence file: {h1_file}")

    md_lines = [
        "| Run Name | Action Profile | Target Goal | Doorway Perception | Nav2 Status (Code) | Est. Nav2 Nav Time ($s$) | Assumed Settling ($s$) | Stability Window ($s$) | Total Sim Duration ($s$) | Physical Arrival Verified |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    tex_lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Exploratory Feasibility Results for Action-Conditioned Navigation Hypothesis $H_1$ ($n=4$).}",
        r"\label{tab:h1_feasibility}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{llcccccccc}",
        r"\hline",
        r"Run Name & Profile & Target Goal & Perception & Nav2 Status & Est. Nav2 ($s$) & Settling ($s$) & Stability ($s$) & Total Sim ($s$) & Strict Arrival \\",
        r"\hline",
    ]

    for r in runs:
        rname = str(r.get("run_name", "UNKNOWN"))
        prof = str(r.get("profile_id", "UNKNOWN"))
        target_goal = r.get("target_goal")
        if target_goal and len(target_goal) >= 2:
            yaw = target_goal[2] if len(target_goal) > 2 else 0.0
            goal_str = f"`[{target_goal[0]:.2f}, {target_goal[1]:.2f}, {yaw:.1f}]`"
            tex_goal_str = f"[{target_goal[0]:.2f}, {target_goal[1]:.2f}]"
        else:
            goal_str = "NA"
            tex_goal_str = "NA"

        pt_count = r.get("pass_through_count")
        door_st = r.get("doorway_state_before_action", "UNKNOWN")
        perc_str = f"`{door_st}` ({pt_count} rays)" if pt_count is not None else f"`{door_st}`"
        tex_perc_str = f"{door_st} ({pt_count})" if pt_count is not None else door_st

        status_code = r.get("terminal_status_code", -1)
        status_name = r.get("terminal_status_name", "UNKNOWN")
        status_str = f"`{status_name}` ({status_code})"
        tex_status_str = f"{status_name} ({status_code})"

        tb = r.get("timing_breakdown", {})
        est_nav = tb.get("estimated_nav2_navigation_duration_sec")
        settle = tb.get("estimated_passive_settling_sim_time_sec")
        stab = tb.get("stability_window_sim_time_sec")
        tot = tb.get("total_step_sim_time_sec")

        est_nav_str = f"${est_nav:.1f}$ (est.)" if est_nav is not None else "NA"
        settle_str = f"${settle:.1f}$ (nom.)" if settle is not None else "NA"
        stab_str = f"${stab:.1f}$" if stab is not None else "NA"
        tot_str = f"${tot:.1f}$" if tot is not None else "NA"

        tex_est_nav = f"{est_nav:.1f}" if est_nav is not None else "NA"
        tex_settle = f"{settle:.1f}" if settle is not None else "NA"
        tex_stab = f"{stab:.1f}" if stab is not None else "NA"
        tex_tot = f"{tot:.1f}" if tot is not None else "NA"

        arrival_ok = r.get("physical_arrival_verified", False)
        halt_reason = r.get("halt_failure_reason")

        if arrival_ok:
            arr_str = "**True**"
            tex_arr = r"\textbf{True}"
        else:
            # Read exact failure reason from record
            if halt_reason:
                # Extract clean brief reason
                reason_clean = halt_reason
                if "max av=" in halt_reason:
                    av_part = halt_reason.split("max av=")[-1].split(")")[0].strip()
                    reason_clean = f"excess av: {av_part}"
                elif "EXCESS_VELOCITY" in halt_reason:
                    reason_clean = "excess velocity"
                arr_str = f"**False** ({reason_clean})"
                tex_arr = f"\\textbf{{False}} ({reason_clean})"
            else:
                arr_str = "**False**"
                tex_arr = r"\textbf{False}"

        md_lines.append(
            f"| `{rname}` | `{prof}` | {goal_str} | {perc_str} | {status_str} | {est_nav_str} | {settle_str} | {stab_str} | {tot_str} | {arr_str} |"
        )

        tex_lines.append(
            f"{rname.replace('_', r'\_')} & {prof.replace('_', r'\_')} & {tex_goal_str} & {tex_perc_str} & {tex_status_str} & {tex_est_nav} & {tex_settle} & {tex_stab} & {tex_tot} & {tex_arr} \\\\"
        )

    tex_lines.extend([
        r"\hline",
        r"\end{tabular}%",
        r"}",
        r"\end{table*}",
    ])

    output_dir.mkdir(parents=True, exist_ok=True)
    md_content = "\n".join(md_lines) + "\n"
    tex_content = "\n".join(tex_lines) + "\n"

    with open(output_dir / "table3_h1_feasibility.md", "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(output_dir / "table3_h1_feasibility.tex", "w", encoding="utf-8") as f:
        f.write(tex_content)

    return md_content, tex_content


def main():
    parser = argparse.ArgumentParser(description="Generate paper tables from analysis CSVs")
    parser.add_argument(
        "--analysis-dir",
        type=Path,
        default=DEFAULT_ANALYSIS_DIR,
        help="Path to analysis directory containing condition_summary.csv and contrasts.csv",
    )
    parser.add_argument(
        "--h1-file",
        type=Path,
        default=DEFAULT_H1_FILE,
        help="Path to parsed H1 JSON file or H1 evidence directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_TABLES_DIR,
        help="Output directory for generated table files",
    )

    args = parser.parse_args()

    print(f"Generating LaTeX and Markdown tables in '{args.output_dir}'...")
    generate_table1(args.analysis_dir, args.output_dir)
    generate_table2(args.analysis_dir, args.output_dir)
    generate_table3(args.h1_file, args.output_dir)
    print("Successfully generated all paper tables.")


if __name__ == "__main__":
    main()
