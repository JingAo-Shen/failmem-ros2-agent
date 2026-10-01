"""Unit tests for paper table generation chain (paper/scripts/generate_paper_tables.py)."""

import json
from pathlib import Path
import pandas as pd
import pytest

from paper.scripts.generate_paper_tables import (
    generate_table1,
    generate_table2,
    generate_table3,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_generate_table1_missing_files(tmp_path):
    empty_dir = tmp_path / "empty_analysis"
    empty_dir.mkdir()
    out_dir = tmp_path / "tables"
    with pytest.raises(FileNotFoundError, match="Missing required condition summary CSV"):
        generate_table1(empty_dir, out_dir)


def test_generate_table1_dynamic_routes_and_audit(tmp_path):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    out_dir = tmp_path / "tables"

    # Synthetic summary
    df_sum = pd.DataFrame([{
        "scenario": "D1",
        "method": "F",
        "condition_id": "D1_F",
        "n": 2,
        "dead_end_traversals_mean": 0.0,
        "dead_end_traversals_std_ddof1": 0.0,
        "decision_distance_m_mean": 7.5,
        "decision_distance_m_std_ddof1": 0.1,
        "decision_sim_time_sec_mean": 48.0,
        "decision_sim_time_sec_std_ddof1": 1.0,
        "total_distance_m_mean": 14.0,
        "total_distance_m_std_ddof1": 0.2,
        "total_sim_time_sec_mean": 109.0,
        "total_sim_time_sec_std_ddof1": 2.0,
    }])
    df_sum.to_csv(analysis_dir / "condition_summary.csv", index=False)

    # Synthetic episodes with route and audit
    df_ep = pd.DataFrame([
        {"condition_id": "D1_F", "actual_route": "Path_B", "audit_pass": True},
        {"condition_id": "D1_F", "actual_route": "Path_B", "audit_pass": False},
    ])
    df_ep.to_csv(analysis_dir / "episodes.csv", index=False)

    md_content, tex_content = generate_table1(analysis_dir, out_dir)
    assert "`Path_B`" in md_content
    assert "1/2 (50\\%)" in md_content
    assert (out_dir / "table1_condition_summary.md").exists()
    assert (out_dir / "table1_condition_summary.tex").exists()


def test_generate_table2_calculates_o_minus_r_and_all_rows(tmp_path):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    out_dir = tmp_path / "tables"

    # Create dummy summary with all required conditions: D1 (F, R, O), D2 (F, M1, O)
    summary_records = [
        {"scenario": "D1", "method": "F", "total_distance_m_mean": 14.027, "total_sim_time_sec_mean": 109.5},
        {"scenario": "D1", "method": "R", "total_distance_m_mean": 17.220, "total_sim_time_sec_mean": 141.0},
        {"scenario": "D1", "method": "O", "total_distance_m_mean": 13.947, "total_sim_time_sec_mean": 108.7},
        {"scenario": "D2", "method": "F", "total_distance_m_mean": 16.247, "total_sim_time_sec_mean": 151.1},
        {"scenario": "D2", "method": "M1", "total_distance_m_mean": 18.248, "total_sim_time_sec_mean": 148.833},
        {"scenario": "D2", "method": "O", "total_distance_m_mean": 16.396, "total_sim_time_sec_mean": 149.767},
    ]
    pd.DataFrame(summary_records).to_csv(analysis_dir / "condition_summary.csv", index=False)

    # Partial contrasts (missing O vs R to test dynamic calculation)
    contrasts_records = [
        {"scenario": "D1", "method_a": "F", "method_b": "R", "metric_field": "total_distance_m", "mean_a": 14.027, "mean_b": 17.220, "abs_diff_a_minus_b": -3.193, "rel_diff_pct": -18.5},
        {"scenario": "D1", "method_a": "F", "method_b": "R", "metric_field": "total_sim_time_sec", "mean_a": 109.5, "mean_b": 141.0, "abs_diff_a_minus_b": -31.5, "rel_diff_pct": -22.3},
        {"scenario": "D1", "method_a": "F", "method_b": "O", "metric_field": "total_distance_m", "mean_a": 14.027, "mean_b": 13.947, "abs_diff_a_minus_b": 0.080, "rel_diff_pct": 0.6},
        {"scenario": "D1", "method_a": "F", "method_b": "O", "metric_field": "total_sim_time_sec", "mean_a": 109.5, "mean_b": 108.7, "abs_diff_a_minus_b": 0.8, "rel_diff_pct": 0.7},
        {"scenario": "D2", "method_a": "F", "method_b": "M1", "metric_field": "total_distance_m", "mean_a": 16.247, "mean_b": 18.248, "abs_diff_a_minus_b": -2.000, "rel_diff_pct": -11.0},
        {"scenario": "D2", "method_a": "F", "method_b": "M1", "metric_field": "total_sim_time_sec", "mean_a": 151.1, "mean_b": 148.833, "abs_diff_a_minus_b": 2.267, "rel_diff_pct": 1.5},
        {"scenario": "D2", "method_a": "F", "method_b": "O", "metric_field": "total_distance_m", "mean_a": 16.247, "mean_b": 16.396, "abs_diff_a_minus_b": -0.149, "rel_diff_pct": -0.9},
        {"scenario": "D2", "method_a": "F", "method_b": "O", "metric_field": "total_sim_time_sec", "mean_a": 151.1, "mean_b": 149.767, "abs_diff_a_minus_b": 1.333, "rel_diff_pct": 0.9},
    ]
    pd.DataFrame(contrasts_records).to_csv(analysis_dir / "contrasts.csv", index=False)

    md_content, tex_content = generate_table2(analysis_dir, out_dir)
    assert "$O$ vs. $R$" in md_content
    assert "-3.273" in md_content  # 13.947 - 17.220 = -3.273
    assert "**-19.0\\%**" in md_content
    # Count rows in markdown table (1 header + 1 separator + 10 data rows)
    lines = [l for l in md_content.strip().split("\n") if l.startswith("|")]
    assert len(lines) == 12


def test_generate_table3_dynamic_halt_reason(tmp_path):
    h1_file = tmp_path / "h1_feasibility_parsed.json"
    out_dir = tmp_path / "tables"

    h1_data = {
        "runs": [
            {
                "run_name": "H1_aligned_run1",
                "profile_id": "act_aligned",
                "target_goal": [1.5, 1.2, 0.0],
                "doorway_state_before_action": "FREE",
                "pass_through_count": 23,
                "terminal_status_name": "SUCCEEDED",
                "terminal_status_code": 4,
                "physical_arrival_verified": False,
                "halt_failure_reason": "excess av: 0.1068 > 0.08",
                "timing_breakdown": {
                    "total_step_sim_time_sec": 18.8,
                    "estimated_nav2_navigation_duration_sec": 13.4,
                    "estimated_passive_settling_sim_time_sec": 3.0,
                    "stability_window_sim_time_sec": 2.4,
                },
            }
        ]
    }
    with open(h1_file, "w", encoding="utf-8") as f:
        json.dump(h1_data, f)

    md_content, tex_content = generate_table3(h1_file, out_dir)
    assert "excess av: 0.1068 > 0.08" in md_content
    assert "**False** (excess av: 0.1068 > 0.08)" in md_content


def test_generate_all_tables_on_baseline(tmp_path):
    baseline_analysis = REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35" / "analysis"
    h1_file = REPO_ROOT / "reports" / "evidence" / "p2d_h1_feasibility" / "derived" / "h1_feasibility_parsed.json"
    out_dir = tmp_path / "tables"

    if baseline_analysis.exists() and h1_file.exists():
        m1, t1 = generate_table1(baseline_analysis, out_dir)
        m2, t2 = generate_table2(baseline_analysis, out_dir)
        m3, t3 = generate_table3(h1_file, out_dir)

        assert len(m1) > 100
        assert len(m2) > 100
        assert len(m3) > 100
