#!/usr/bin/env python3
"""FailMem Milestone P2c Automated Offline Reproduction Suite.

Performs deterministic offline reproduction and verification:
1. Path safety and collision validation (prevents dangerous overwrite/nesting).
2. Environment & System Metadata Capture (OS, Python, Git commit, package versions).
3. SHA256 Anti-Tamper Checksum Verification against baseline checksums.sha256.
4. Automated Dataset Staging to a dedicated reproduction directory.
5. Independent Replay & Scoring across all 30 episodes (`replay_and_score_p2c`).
6. Statistical Aggregation & Integrity Reporting (`analyze_p2c_results`).
7. Mandatory Baseline CSV Verification (Exact/Tolerance diffing against reference CSVs).
8. H1 Raw and Derived Evidence Verification (`verify_h1_feasibility`).
9. Single-Location Clean Artifact Retention & Structured Reproduction Manifest.
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
import traceback
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
    EXPECTED_H1_RUNS,
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


def validate_reproduction_paths(
    source_dir: Path,
    output_dir: Path,
    baseline_dir: Optional[Path],
    h1_dir: Optional[Path],
) -> None:
    """Validate directory paths to prevent corruption, collisions, and dangerous deletions."""
    src_res = source_dir.resolve()
    out_res = output_dir.resolve()
    repo_res = REPO_ROOT.resolve()

    if not src_res.exists() or not src_res.is_dir():
        raise FileNotFoundError(f"Source raw directory does not exist: {src_res}")

    # Dangerous root paths
    dangerous_paths = [
        Path("/"),
        Path("/root"),
        Path("/home"),
        Path("/etc"),
        Path("/var"),
        Path("/usr"),
        Path("/code"),
    ]
    if out_res in dangerous_paths or out_res == repo_res:
        raise ValueError(f"Output directory '{out_res}' cannot be system root or repository root.")

    # Equal path checks
    if out_res == src_res:
        raise ValueError(f"Output directory '{out_res}' cannot be identical to source directory.")

    if baseline_dir is not None:
        base_res = baseline_dir.resolve()
        if out_res == base_res:
            raise ValueError(f"Output directory '{out_res}' cannot be identical to baseline directory.")

    if h1_dir is not None:
        h1_res = h1_dir.resolve()
        if out_res == h1_res:
            raise ValueError(f"Output directory '{out_res}' cannot be identical to H1 directory.")

    # Ancestor checks: output_dir cannot be parent/ancestor of repo root or source dir
    try:
        if repo_res.is_relative_to(out_res):
            raise ValueError(f"Output directory '{out_res}' cannot be an ancestor of repository root.")
        if src_res.is_relative_to(out_res):
            raise ValueError(f"Output directory '{out_res}' cannot be an ancestor of source directory.")
        if baseline_dir is not None and baseline_dir.resolve().is_relative_to(out_res):
            raise ValueError(f"Output directory '{out_res}' cannot be an ancestor of baseline directory.")
        if h1_dir is not None and h1_dir.resolve().is_relative_to(out_res):
            raise ValueError(f"Output directory '{out_res}' cannot be an ancestor of H1 directory.")
    except AttributeError:
        # Python < 3.9 fallback
        if str(repo_res).startswith(str(out_res) + "/"):
            raise ValueError(f"Output directory '{out_res}' cannot be an ancestor of repository root.")

    # Nesting inside source check
    try:
        if out_res.is_relative_to(src_res):
            raise ValueError(f"Output directory '{out_res}' cannot be nested inside source directory.")
    except AttributeError:
        if str(out_res).startswith(str(src_res) + "/"):
            raise ValueError(f"Output directory '{out_res}' cannot be nested inside source directory.")

    # Existing non-empty output directory check (no blind recursive rmtree)
    if out_res.exists() and any(out_res.iterdir()):
        raise FileExistsError(
            f"Output directory '{out_res}' already exists and is not empty. "
            f"Please specify a new or empty directory path."
        )


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
        and results["total_files"] > 0
    )
    return passed, results


def stage_dataset(source_dir: Path, output_dir: Path) -> None:
    """Copy episode directories and runtime protocols from source to output."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy all episode directories and checksum file, omitting prior analysis
    copied_count = 0
    for item in sorted(source_dir.iterdir()):
        if item.name in ["analysis", "p2c_replay_summary.json", "h1_derived", "derived"]:
            # Skip old derived/replay summaries so reproduction is 100% fresh
            continue
        dest = output_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
            copied_count += 1
        elif item.is_file():
            shutil.copy2(item, dest)
            copied_count += 1

    if copied_count == 0:
        raise ValueError(f"No episode files or directories were found to stage from {source_dir}")


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
        report["differences"].append(
            f"Shape or column mismatch: Repro {df_repro.shape} vs Base {df_base.shape}"
        )
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


def verify_h1_raw_evidence(h1_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    """Verify existence and format integrity of raw H1 evidence files."""
    report = {
        "h1_dir": str(h1_dir),
        "checksum_verified": False,
        "runs_checked": 0,
        "missing_runs": [],
        "corrupted_runs": [],
        "all_valid": True,
    }

    if not h1_dir.exists() or not h1_dir.is_dir():
        report["all_valid"] = False
        report["error"] = f"H1 directory '{h1_dir}' does not exist"
        return False, report

    # Optional checksums.sha256 in h1_dir
    h1_chk = h1_dir / "checksums.sha256"
    if h1_chk.exists():
        chk_pass, chk_res = verify_checksums(h1_dir)
        report["checksum_verified"] = chk_pass
        report["checksum_details"] = chk_res
        if not chk_pass:
            report["all_valid"] = False
            report["corrupted_runs"].append("H1 checksum verification failed")

    for rname in EXPECTED_H1_RUNS:
        run_p = h1_dir / rname
        report["runs_checked"] += 1
        if not run_p.exists() or not run_p.is_dir():
            report["missing_runs"].append(rname)
            report["all_valid"] = False
            continue

        res_f = run_p / "feasibility_result.json"
        scan_f = run_p / "scan_snapshots.json"

        if not res_f.exists() or not scan_f.exists():
            report["corrupted_runs"].append(f"{rname}: missing json files")
            report["all_valid"] = False
            continue

        try:
            with open(res_f, "r", encoding="utf-8") as f:
                res_data = json.load(f)
            if not res_data.get("run_name") or not res_data.get("actions"):
                report["corrupted_runs"].append(f"{rname}: empty/invalid feasibility_result.json")
                report["all_valid"] = False

            with open(scan_f, "r", encoding="utf-8") as f:
                scan_data = json.load(f)
            if not isinstance(scan_data, list) or len(scan_data) == 0:
                report["corrupted_runs"].append(f"{rname}: empty scan_snapshots.json")
                report["all_valid"] = False
        except Exception as e:
            report["corrupted_runs"].append(f"{rname}: json parse error {str(e)}")
            report["all_valid"] = False

    return report["all_valid"], report


def run_reproduction_pipeline(
    source_dir: Path,
    output_dir: Path,
    baseline_dir: Optional[Path] = None,
    h1_dir: Optional[Path] = None,
    tolerance: float = 1e-4,
) -> Dict[str, Any]:
    """Execute complete end-to-end reproduction workflow."""
    start_time = time.time()
    env_meta = get_environment_metadata()
    log_lines = []
    current_stage = "INITIALIZATION"

    def log(msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] {msg}"
        log_lines.append(line)
        print(line)

    try:
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

        # Step 0: Path Validation
        current_stage = "PATH_VALIDATION"
        log("\n--- Step 0: Path & Safety Validation ---")
        validate_reproduction_paths(source_dir, output_dir, baseline_dir, h1_dir)
        log("Path safety check PASSED.")

        # Step 1: Checksum verification
        current_stage = "CHECKSUM_VERIFICATION"
        log("\n--- Step 1: SHA256 Checksum Verification ---")
        chk_pass, chk_details = verify_checksums(source_dir)
        log(f"Checksums Verified: {chk_details['matched_files']}/{chk_details['total_files']} files")
        if not chk_pass:
            log(f"CHECKSUM FAILURE: Missing: {chk_details.get('missing_files')}, Mismatched: {chk_details.get('mismatched_files')}")
            raise RuntimeError("SHA256 checksum verification failed.")
        log("Checksum verification PASSED.")

        # Step 2: Staging dataset
        current_stage = "DATASET_STAGING"
        log("\n--- Step 2: Staging Dataset to Dedicated Reproduction Directory ---")
        stage_dataset(source_dir, output_dir)
        log(f"Dataset successfully staged at '{output_dir}'.")

        # Step 3: Replay & Re-scoring
        current_stage = "REPLAY_AND_SCORING"
        log("\n--- Step 3: Independent Replay & Objective Scoring ---")
        replay_summary = replay_p2c_run(output_dir)
        log(f"Replayed Episodes:  {replay_summary['total_episodes_replayed']}")
        log(f"All Valid:          {replay_summary['all_episodes_valid']}")
        log(f"All Audit Passed:   {replay_summary['all_audit_pass']}")
        if not replay_summary["all_audit_pass"]:
            raise RuntimeError("Replay audit verification failed for one or more episodes.")
        log("Replay scoring PASSED.")

        # Step 4: Statistical Analysis & Integrity
        current_stage = "STATISTICAL_ANALYSIS"
        log("\n--- Step 4: Statistical Analysis & Aggregation ---")
        analysis_dir = output_dir / "analysis"
        analysis_res = analyze_p2c_run(output_dir, analysis_dir)
        df_episodes_rep = analysis_res["episodes_df"]
        df_summary_rep = analysis_res["summary_df"]
        df_contrasts_rep = analysis_res["contrasts_df"]
        integrity_rep = analysis_res.get("integrity_report", {})
        integrity_passed = bool(integrity_rep.get("integrity_check_passed", False))

        log(f"Integrity Passed:   {integrity_passed} (Audited: {integrity_rep.get('episodes_audited_valid', 0)}/30)")
        if not integrity_passed:
            raise RuntimeError(f"Integrity check failed: {integrity_rep.get('integrity_violations', [])}")
        log("Statistical analysis completed and CSVs generated in output_dir/analysis/.")

        # Step 5: Baseline Comparisons
        current_stage = "BASELINE_COMPARISON"
        log("\n--- Step 5: Baseline CSV Comparison ---")
        comparisons: Dict[str, Any] = {}
        all_comparisons_pass = True

        if baseline_dir is None:
            log("ERROR: Baseline directory is mandatory but was not specified.")
            all_comparisons_pass = False
            comparisons["error"] = "Baseline directory not specified"
        elif not baseline_dir.exists():
            log(f"ERROR: Baseline directory does not exist: {baseline_dir}")
            all_comparisons_pass = False
            comparisons["error"] = f"Baseline directory does not exist: {baseline_dir}"
        else:
            required_baseline_files = [
                ("episodes", baseline_dir / "episodes.csv", df_episodes_rep),
                ("condition_summary", baseline_dir / "condition_summary.csv", df_summary_rep),
                ("contrasts", baseline_dir / "contrasts.csv", df_contrasts_rep),
            ]

            for name, base_path, df_rep in required_baseline_files:
                if not base_path.exists():
                    log(f"ERROR: Required baseline CSV missing: {base_path}")
                    all_comparisons_pass = False
                    comparisons[name] = {"all_match": False, "error": f"Missing file {base_path}"}
                    continue

                df_base = pd.read_csv(base_path)
                rep_cmp = compare_dataframes(df_rep, df_base, base_path.name, tolerance)
                comparisons[name] = rep_cmp
                log(f"{base_path.name} Match: {rep_cmp['all_match']} (Diffs: {rep_cmp['differences']})")
                if not rep_cmp["all_match"]:
                    all_comparisons_pass = False

        if not all_comparisons_pass:
            log("Baseline comparison checks FAILED.")
        else:
            log("Baseline comparison checks PASSED.")

        # Step 6: H1 Feasibility Re-verification
        current_stage = "H1_FEASIBILITY"
        h1_report: Dict[str, Any] = {}
        h1_verified = False

        if h1_dir is None:
            log("ERROR: H1 evidence directory is mandatory but was not specified.")
            h1_report["error"] = "H1 directory not specified"
        elif not h1_dir.exists():
            log(f"ERROR: H1 directory does not exist: {h1_dir}")
            h1_report["error"] = f"H1 directory does not exist: {h1_dir}"
        else:
            log("\n--- Step 6: H1 Feasibility Re-Verification ---")
            raw_h1_pass, raw_h1_details = verify_h1_raw_evidence(h1_dir)
            if not raw_h1_pass:
                log(f"H1 Raw Evidence Verification FAILED: {raw_h1_details}")
            else:
                log("H1 Raw Evidence Verification PASSED.")

            h1_derived_dir = output_dir / "h1_derived"
            h1_derived_dir.mkdir(parents=True, exist_ok=True)
            h1_data = parse_and_derive_h1_evidence(h1_dir, h1_derived_dir)
            h1_runs = h1_data.get("runs", [])
            h1_eval = evaluate_h1_go_nogo(h1_runs)

            h1_verified = (
                raw_h1_pass
                and len(h1_runs) == len(EXPECTED_H1_RUNS)
                and all(r.get("doorway_state_before_action") is not None for r in h1_runs)
            )

            h1_report = {
                "raw_verification": raw_h1_details,
                "runs_evaluated": len(h1_runs),
                "nav2_succeeded_count": sum(1 for r in h1_runs if r.get("terminal_status_code") == 4),
                "physical_arrival_verified_count": sum(1 for r in h1_runs if r.get("physical_arrival_verified")),
                "go_decision": h1_eval.get("go_condition_met"),
                "verdict": h1_eval.get("verdict"),
                "rationale": h1_eval.get("rationale"),
                "unified_conclusion": h1_eval.get("unified_conclusion"),
                "h1_verified": h1_verified,
            }
            log(f"H1 Evaluated: {h1_report['runs_evaluated']} runs")
            log(f"H1 Nav2 Succeeded: {h1_report['nav2_succeeded_count']}/4")
            log(f"H1 Arrival Verified: {h1_report['physical_arrival_verified_count']}/4")
            log(f"H1 Go/No-Go Decision: GO={h1_report['go_decision']} ({h1_report['verdict']})")

        elapsed_sec = time.time() - start_time
        overall_success = (
            chk_pass
            and replay_summary.get("all_audit_pass", False)
            and integrity_passed
            and all_comparisons_pass
            and h1_verified
        )

        log(f"\nReproduction Pipeline Completed in {elapsed_sec:.2f} seconds. Overall Success: {overall_success}")

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
            "integrity_report": integrity_rep,
            "baseline_comparisons": comparisons,
            "h1_feasibility": h1_report,
        }

        # Save reproduction report and log
        with open(output_dir / "reproduction_report.json", "w", encoding="utf-8") as f:
            json.dump(full_report, f, indent=2)

        with open(output_dir / "reproduction_log.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")

        return full_report

    except Exception as e:
        elapsed_sec = time.time() - start_time
        err_tb = traceback.format_exc()
        log(f"\n[EXCEPTION IN STAGE '{current_stage}']: {e}\n{err_tb}")

        err_report = {
            "status": "ERROR",
            "overall_success": False,
            "failed_stage": current_stage,
            "error_message": str(e),
            "traceback": err_tb,
            "elapsed_seconds": round(elapsed_sec, 3),
            "environment_metadata": env_meta,
        }

        if output_dir.exists():
            try:
                with open(output_dir / "reproduction_report.json", "w", encoding="utf-8") as f:
                    json.dump(err_report, f, indent=2)
                with open(output_dir / "reproduction_log.txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(log_lines) + "\n")
            except Exception:
                pass

        raise


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
            tolerance=args.tolerance,
        )
        if not report["overall_success"]:
            print(f"\n[REPRODUCTION FAILED] Overall success was False. See {args.output_dir}/reproduction_report.json", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"\n[REPRODUCTION SUCCESS] All audits and baseline comparisons matched. Output at {args.output_dir}")
    except Exception as e:
        print(f"\n[ERROR] Reproduction pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
