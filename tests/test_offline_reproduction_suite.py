"""Unit tests for the automated offline reproduction suite (scripts/reproduce_offline.py)."""

import json
from pathlib import Path
import pandas as pd
import pytest

from scripts.reproduce_offline import (
    compute_file_sha256,
    verify_checksums,
    compare_dataframes,
    get_environment_metadata,
    validate_reproduction_paths,
    verify_h1_raw_evidence,
    run_reproduction_pipeline,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_compute_file_sha256(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello failmem", encoding="utf-8")
    h = compute_file_sha256(f)
    assert isinstance(h, str)
    assert len(h) == 64


def test_get_environment_metadata():
    meta = get_environment_metadata()
    assert "timestamp_utc" in meta
    assert "python_version" in meta
    assert "platform" in meta
    assert "packages" in meta
    assert "pandas" in meta["packages"]


def test_compare_dataframes_identical():
    df1 = pd.DataFrame({
        "scenario": ["D0", "D1"],
        "dist": [6.12, 14.03],
        "valid": [True, True],
    })
    df2 = df1.copy()
    res = compare_dataframes(df1, df2, "test_table", tolerance=1e-4)
    assert res["all_match"] is True
    assert len(res["differences"]) == 0


def test_compare_dataframes_numeric_mismatch():
    df1 = pd.DataFrame({"dist": [6.12, 14.03]})
    df2 = pd.DataFrame({"dist": [6.12, 15.00]})
    res = compare_dataframes(df1, df2, "test_table", tolerance=1e-4)
    assert res["all_match"] is False
    assert any("max diff" in d for d in res["differences"])


def test_compare_dataframes_boolean_mismatch():
    df1 = pd.DataFrame({"valid": [True, True]})
    df2 = pd.DataFrame({"valid": [True, False]})
    res = compare_dataframes(df1, df2, "test_table", tolerance=1e-4)
    assert res["all_match"] is False
    assert any("boolean mismatch" in d for d in res["differences"])


def test_verify_checksums_on_baseline():
    baseline_dir = REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35"
    if baseline_dir.exists():
        passed, details = verify_checksums(baseline_dir)
        assert passed is True
        assert details["total_files"] == 271
        assert details["matched_files"] == 271
        assert len(details["mismatched_files"]) == 0
        assert len(details["missing_files"]) == 0


def test_validate_reproduction_paths_safety(tmp_path):
    source_dir = REPO_ROOT / "reports" / "evidence" / "p2c_pilot" / "p2c_pilot_20261001_022711_0d3c35"
    out_valid = tmp_path / "valid_output_dir"

    # Valid path should pass
    validate_reproduction_paths(source_dir, out_valid, None, None)

    # Output == repo root should fail
    with pytest.raises(ValueError, match="cannot be system root or repository root"):
        validate_reproduction_paths(source_dir, REPO_ROOT, None, None)

    # Output == source should fail
    with pytest.raises(ValueError, match="cannot be identical to source directory"):
        validate_reproduction_paths(source_dir, source_dir, None, None)

    # Non-empty existing output dir should fail
    non_empty_dir = tmp_path / "non_empty"
    non_empty_dir.mkdir()
    (non_empty_dir / "file.txt").write_text("dummy")
    with pytest.raises(FileExistsError, match="already exists and is not empty"):
        validate_reproduction_paths(source_dir, non_empty_dir, None, None)


def test_verify_h1_raw_evidence_baseline():
    h1_dir = REPO_ROOT / "reports" / "evidence" / "p2d_h1_feasibility"
    if h1_dir.exists():
        passed, details = verify_h1_raw_evidence(h1_dir)
        assert passed is True
        assert details["runs_checked"] == 4
        assert len(details["missing_runs"]) == 0
        assert len(details["corrupted_runs"]) == 0


def test_verify_h1_raw_evidence_corrupted(tmp_path):
    fake_h1 = tmp_path / "fake_h1"
    fake_h1.mkdir()
    # Missing runs
    passed, details = verify_h1_raw_evidence(fake_h1)
    assert passed is False
    assert len(details["missing_runs"]) == 4

    # Empty run dir
    (fake_h1 / "H1_aligned_run1").mkdir()
    passed2, details2 = verify_h1_raw_evidence(fake_h1)
    assert passed2 is False
    assert any("missing json files" in s for s in details2["corrupted_runs"])

