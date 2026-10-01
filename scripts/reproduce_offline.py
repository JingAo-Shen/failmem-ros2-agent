#!/usr/bin/env python3
"""FailMem Milestone P2c Automated Offline Reproduction Suite.

Performs deterministic offline reproduction and verification:
1. Environment & System Metadata Capture (OS, Python, Git commit, package versions).
2. SHA256 Anti-Tamper Checksum Verification against baseline checksums.sha256.
3. Automated Dataset Staging to a dedicated reproduction directory.
4. Independent Replay & Scoring across all 30 episodes (`replay_and_score_p2c`).
5. Statistical Aggregation & Integrity Reporting (`analyze_p2c_results`).
6. Baseline CSV Verification (Exact/Tolerance diffing against reference CSVs).
7. H1 Feasibility Re-Verification (`verify_h1_feasibility`).
8. Structured Reproduction Manifest (`reproduction_report.json`) and Log.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.replay_and_score_p2c import replay_p2c_run
from scripts.analyze_p2c_results import analyze_p2c_run
from scripts.verify_h1_feasibility import (
    parse_and_derive_h1_evidence,
    evaluate_h1_go_nogo,
)


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_environment_metadata() -> Dict[str, Any]:
    """Capture runtime and platform environment metadata."""
    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    
    # Git status
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        ).strip()
        meta["git_commit"] = commit
        meta["git_branch"] = branch
        meta["git_dirty"] = bool(status)
    except Exception as e:
        meta["git_info_error"] = str(e)

    # Package versions
    packages = {}
    for pkg_name in ["pandas", "numpy", "scipy", "pytest", "yaml", "matplotlib", "weasyprint"]:
        try:
            mod = __import__(pkg_name)
            packages[pkg_name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            packages[pkg_name] = "not_installed"
    meta["packages"] = packages
    return meta


def verify_checksums(source_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    """Verify all files listed in checksums.sha256 in the source directory."""
    chk_file = source_dir / "checksums.sha256"
    if not chk_file.exists():
        return False, {"error": "checksums.sha256 not found in source directory"}

    results = {
        "total_files": 0,
        "matched_files": 0,
        "mismatched_files": [],
        "missing_files": [],
    }

    with open(chk_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            expected_hash, rel_path_str = parts[0], parts[1]
            if rel_path_str.startswith("./"):
                rel_path_str = rel_path_str[2:]
            
            target_path = source_dir / rel_path_str
            results["total_files"] += 1

            if not target_path.exists():
                results["missing_files"].append(rel_path_str)
                continue

            actual_hash = compute_file_sha256(target_path)
            if actual_hash == expected_hash:
                results["matched_files"] += 1
            else:
                results["mismatched_files"].append({
                    "path": rel_path_str,
                    "expected": expected_hash,
                    "actual": actual_hash,
                })

    passed = (
        len(results["missing_files"]) == 0
        and len(results["mismatched_files"]) == 0
        and results["matched_files"] == results["total_files"]
    )
    return passed, results


def stage_dataset(source_dir: Path, output_dir: Path, force: bool = False) -> None:
    """Copy episode directories and runtime protocols from source to output."""
    if output_dir.exists():
        if not force:
            raise FileExistsError(
                f"Output directory '{output_dir}' already exists. Pass --force to overwrite."
            )
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy all episode directories and checksum file
    for item in source_dir.iterdir():
        if item.name == "analysis" or item.name == "p2c_replay_summary.json":
            # Skip old derived/replay summaries so reproduction is 100% fresh
            continue
        dest = output_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        elif item.is_file():
            shutil.copy2(item, dest)


def compare_dataframes(
    df_repro: pd.DataFrame,
    df_base: pd.DataFrame,
    table_name: str,
    tolerance: float = 1e-4,
) -> Dict[str, Any]:
    """Compare two pandas DataFrames for exact and numeric equality."""
    report = {
        "table_name": table_name,
        "rows_reproduced": len(df_repro),
        "rows_baseline": len(df_base),
        "shape_match": df_repro.shape == df_base.shape,
        "columns_match": list(df_repro.columns) == list(df_base.columns),
        "all_match": True,
        "differences": [],
    }

    if not report["shape_match"] or not report["columns_match"]:
        report["all_match"] = False
        report["differences"].append("Shape or column mismatch")
        return report

    for col in df_repro.columns:
        s_rep = df_repro[col]
        s_bas = df_base[col]

        if pd.api.types.is_bool_dtype(s_rep) or pd.api.types.is_bool_dtype(s_bas):
            # Boolean comparison
            s_rep_b = s_rep.astype(bool)
            s_bas_b = s_bas.astype(bool)
            if not s_rep_b.equals(s_bas_b):
                diff_count = (s_rep_b != s_bas_b).sum()
                report["all_match"] = False
                report["differences"].append(
                    f"Column '{col}' boolean mismatch in {diff_count} rows"
                )
        elif pd.api.types.is_numeric_dtype(s_rep) and pd.api.types.is_numeric_dtype(s_bas):
            # Numeric comparison
            nan_rep = s_rep.isna()
            nan_bas = s_bas.isna()
            if not nan_rep.equals(nan_bas):
                report["all_match"] = False
                report["differences"].append(f"Column '{col}' NaN pattern mismatch")
                continue
            
            # Numeric diff on non-NaNs
            valid_idx = ~nan_rep
            if valid_idx.any():
                v_rep = s_rep[valid_idx].astype(float)
                v_bas = s_bas[valid_idx].astype(float)
                diff = (v_rep - v_bas).abs()
                max_diff = diff.max()
                if max_diff > tolerance:
                    report["all_match"] = False
                    report["differences"].append(
                        f"Column '{col}' max diff {max_diff:.6f} exceeds tolerance {tolerance}"
                    )
        else:
            # String / object comparison
            s_rep_str = s_rep.fillna("NA").astype(str)
            s_bas_str = s_bas.fillna("NA").astype(str)
            if not s_rep_str.equals(s_bas_str):
                diff_idx = s_rep_str != s_bas_str
                diff_count = diff_idx.sum()
                report["all_match"] = False
                report["differences"].append(
                    f"Column '{col}' string mismatch in {diff_count} rows"
                )

    return report


def run_reproduction_pipeline(
    source_dir: Path,
    output_dir: Path,
    baseline_dir: Optional[Path] = None,
    h1_dir: Optional[Path] = None,
    force: bool = False,
    tolerance: float = 1e-4,
) -> Dict[str, Any]:
    """Execute complete end-to-end reproduction workflow."""
    start_time = time.time()
    env_meta = get_environment_metadata()
    log_lines = []

    def log(msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] {msg}"
        log_lines.append(line)
        print(line)

    log("=======================================================================")
    log("Starting FailMem P2c Offline Reproduction Pipeline")
    log("=======================================================================")
    log(f"Source Directory:   {source_dir}")
    log(f"Output Directory:   {output_dir}")
    log(f"Baseline Directory: {baseline_dir}")
    log(f"H1 Directory:       {h1_dir}")
    log(f"Platform:           {env_meta['platform']}")
    log(f"Python:             {sys.version.split()[0]} ({sys.executable})")
    log(f"Git Commit:         {env_meta.get('git_commit', 'unknown')} (branch: {env_meta.get('git_branch', 'unknown')})")

    # Step 1: Checksum verification
    log("\n--- Step 1: SHA256 Checksum Verification ---")
    chk_pass, chk_details = verify_checksums(source_dir)
    log(f"Checksums Verified: {chk_details['matched_files']}/{chk_details['total_files']} files")
    if not chk_pass:
        log(f"CHECKSUM FAILURE: Missing: {chk_details['missing_files']}, Mismatched: {chk_details['mismatched_files']}")
        raise RuntimeError("SHA256 checksum verification failed.")
    log("Checksum verification PASSED.")

    # Step 2: Staging dataset
    log("\n--- Step 2: Staging Dataset to Reproduction Directory ---")
    stage_dataset(source_dir, output_dir, force=force)
    log(f"Dataset successfully staged at '{output_dir}'.")

    # Step 3: Replay & Re-scoring
    log("\n--- Step 3: Independent Replay & Objective Scoring ---")
    replay_summary = replay_p2c_run(output_dir)
    log(f"Replayed Episodes:  {replay_summary['total_episodes_replayed']}")
    log(f"All Valid:          {replay_summary['all_episodes_valid']}")
    log(f"All Audit Passed:   {replay_summary['all_audit_pass']}")
    if not replay_summary["all_audit_pass"]:
        raise RuntimeError("Replay audit verification failed for one or more episodes.")
    log("Replay scoring PASSED.")

    # Step 4: Statistical Analysis
    log("\n--- Step 4: Statistical Analysis & Aggregation ---")
    analysis_res = analyze_p2c_run(output_dir, output_dir / "analysis")
    df_episodes_rep = analysis_res["episodes_df"]
    df_summary_rep = analysis_res["summary_df"]
    df_contrasts_rep = analysis_res["contrasts_df"]
    
    # Also mirror CSVs and integrity report to output_dir root for convenience
    for fpath in (output_dir / "analysis").iterdir():
        if fpath.is_file():
            shutil.copy2(fpath, output_dir / fpath.name)
    
    log("Statistical analysis completed and CSVs generated.")

    # Step 5: Baseline Comparisons
    log("\n--- Step 5: Baseline CSV Comparison ---")
    comparisons = {}
    all_comparisons_pass = True

    if baseline_dir and baseline_dir.exists():
        base_episodes_csv = baseline_dir / "episodes.csv"
        base_summary_csv = baseline_dir / "condition_summary.csv"
        base_contrasts_csv = baseline_dir / "contrasts.csv"

        if base_episodes_csv.exists():
            df_episodes_base = pd.read_csv(base_episodes_csv)
            rep_ep = compare_dataframes(df_episodes_rep, df_episodes_base, "episodes.csv", tolerance)
            comparisons["episodes"] = rep_ep
            log(f"episodes.csv Match: {rep_ep['all_match']} (Diffs: {rep_ep['differences']})")
            if not rep_ep["all_match"]:
                all_comparisons_pass = False

        if base_summary_csv.exists():
            df_summary_base = pd.read_csv(base_summary_csv)
            rep_sum = compare_dataframes(df_summary_rep, df_summary_base, "condition_summary.csv", tolerance)
            comparisons["condition_summary"] = rep_sum
            log(f"condition_summary.csv Match: {rep_sum['all_match']} (Diffs: {rep_sum['differences']})")
            if not rep_sum["all_match"]:
                all_comparisons_pass = False

        if base_contrasts_csv.exists():
            df_contrasts_base = pd.read_csv(base_contrasts_csv)
            rep_con = compare_dataframes(df_contrasts_rep, df_contrasts_base, "contrasts.csv", tolerance)
            comparisons["contrasts"] = rep_con
            log(f"contrasts.csv Match: {rep_con['all_match']} (Diffs: {rep_con['differences']})")
            if not rep_con["all_match"]:
                all_comparisons_pass = False
    else:
        log("No baseline analysis directory provided for comparison; skipping diff.")

    # Step 6: H1 Feasibility Re-verification
    h1_report = {}
    if h1_dir and h1_dir.exists():
        log("\n--- Step 6: H1 Feasibility Re-Verification ---")
        h1_derived_dir = output_dir / "h1_derived"
        h1_derived_dir.mkdir(parents=True, exist_ok=True)
        h1_data = parse_and_derive_h1_evidence(h1_dir, h1_derived_dir)
        h1_runs = h1_data.get("runs", [])
        h1_eval = evaluate_h1_go_nogo(h1_runs)
        h1_report = {
            "runs_evaluated": len(h1_runs),
            "nav2_succeeded_count": sum(1 for r in h1_runs if r.get("terminal_status_code") == 4),
            "physical_arrival_verified_count": sum(1 for r in h1_runs if r.get("physical_arrival_verified")),
            "go_decision": h1_eval.get("go_condition_met"),
            "verdict": h1_eval.get("verdict"),
            "rationale": h1_eval.get("rationale"),
            "unified_conclusion": h1_eval.get("unified_conclusion"),
        }
        log(f"H1 Evaluated: {h1_report['runs_evaluated']} runs")
        log(f"H1 Nav2 Succeeded: {h1_report['nav2_succeeded_count']}/4")
        log(f"H1 Arrival Verified: {h1_report['physical_arrival_verified_count']}/4")
        log(f"H1 Go/No-Go Decision: GO={h1_report['go_decision']} ({h1_report['verdict']})")

    elapsed_sec = time.time() - start_time
    log(f"\nReproduction Pipeline Completed in {elapsed_sec:.2f} seconds.")

    overall_success = (
        chk_pass
        and replay_summary["all_audit_pass"]
        and all_comparisons_pass
    )

    full_report = {
        "status": "SUCCESS" if overall_success else "FAILURE",
        "overall_success": overall_success,
        "elapsed_seconds": round(elapsed_sec, 3),
        "environment_metadata": env_meta,
        "checksum_verification": chk_details,
        "replay_summary": {
            "total_episodes_replayed": replay_summary["total_episodes_replayed"],
            "all_episodes_valid": replay_summary["all_episodes_valid"],
            "all_audit_pass": replay_summary["all_audit_pass"],
        },
        "integrity_report": analysis_res["integrity_report"],
        "baseline_comparisons": comparisons,
        "h1_feasibility": h1_report,
    }

    # Save reproduction report and log
    with open(output_dir / "reproduction_report.json", "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2)

    with open(output_dir / "reproduction_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")

    return full_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FailMem Milestone P2c Automated Offline Reproduction Suite"
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35",
        help="Path to source raw pilot dataset directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "evidence" / "p2c_pilot_reproduced",
        help="Path to dedicated reproduction evidence directory",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35" / "analysis",
        help="Path to reference baseline analysis directory containing CSVs",
    )
    parser.add_argument(
        "--h1-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "evidence" / "p2d_h1_feasibility",
        help="Path to H1 feasibility evidence directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output directory if it already exists",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-4,
        help="Numeric comparison tolerance for float metrics (default: 1e-4)",
    )

    args = parser.parse_args()

    try:
        report = run_reproduction_pipeline(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            baseline_dir=args.baseline_dir,
            h1_dir=args.h1_dir,
            force=args.force,
            tolerance=args.tolerance,
        )
        if not report["overall_success"]:
            sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Reproduction failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
