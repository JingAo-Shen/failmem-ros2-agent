#!/usr/bin/env python3
"""FailMem Historical Model Probe Output Rescorer.

Rescores historical model outputs from reports/evidence/p0/model_probe_v2.json
using the strict static schema validator (src/schema_validator.py).
DOES NOT regenerate outputs or alter original evidence file.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.schema_validator import parse_and_validate_action


def rescore_probe_results(input_path: Path, output_path: Path) -> dict:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file {input_path} not found")

    with open(input_path, "r", encoding="utf-8") as f:
        original_data = json.load(f)

    rescored_trials = []
    for trial in original_data.get("trials", []):
        raw_output = trial["raw_output"]
        val_result = parse_and_validate_action(raw_output)

        rescored_trial = dict(trial)
        rescored_trial.update({
            "json_parseable": bool(val_result["json_parseable"]),
            "schema_valid": bool(val_result["schema_valid"]),
            "runtime_precondition_status": val_result["runtime_precondition_status"],
            "action_executable_deprecated": False,
            "action_executable_note": "Deprecated static check; static validator only verifies syntax. Preconditions checked at runtime.",
            "parsed_action": val_result["action_name"],
            "error_stage": val_result["error_stage"],
            "error_type": val_result["error_type"],
            "error_message": val_result["error_message"],
        })
        rescored_trials.append(rescored_trial)

    num_trials = len(rescored_trials)
    parseable_count = sum(1 for t in rescored_trials if t["json_parseable"])
    schema_valid_count = sum(1 for t in rescored_trials if t["schema_valid"])

    rescored_data = {
        "status": "COMPLETED",
        "rescore_notice": "旧输出重评分 (Historical probe outputs rescored using strict schema validator from Commit A without regenerating model outputs)",
        "original_source_file": str(input_path.relative_to(REPO_ROOT)),
        "original_timestamp": original_data.get("timestamp"),
        "rescore_timestamp": datetime.now(timezone.utc).isoformat(),
        "purpose": "Model interface feasibility probe under Problem Lock v0.2 rescored with strict static schema validator.",
        "environment": original_data.get("environment", {}),
        "model_metadata": original_data.get("model_metadata", {}),
        "performance": original_data.get("performance", {}),
        "validation_metrics": {
            "total_trials": num_trials,
            "json_parseable_count": parseable_count,
            "json_parseable_rate": round(parseable_count / num_trials, 4) if num_trials > 0 else 0,
            "schema_valid_count": schema_valid_count,
            "schema_valid_rate": round(schema_valid_count / num_trials, 4) if num_trials > 0 else 0,
            "runtime_preconditions_checked": False,
            "action_executable_status": "DEPRECATED_STATIC_CHECK",
            "action_executable_note": "Static validator does not judge execution readiness. Runtime preconditions must be checked in EpisodeExecutionContext.",
        },
        "trials": rescored_trials,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rescored_data, f, indent=2, ensure_ascii=False)

    return rescored_data


def main():
    parser = argparse.ArgumentParser(description="Rescore historical probe outputs")
    parser.add_argument(
        "--input",
        type=str,
        default=str(REPO_ROOT / "reports/evidence/p0/model_probe_v2.json"),
        help="Input historical probe JSON file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(REPO_ROOT / "reports/evidence/p0/rescore_model_probe_v2.json"),
        help="Output rescored probe JSON file",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    print(f"Rescoring historical probe: {input_path} -> {output_path}")
    res = rescore_probe_results(input_path, output_path)
    metrics = res["validation_metrics"]
    print(f"Rescore complete. Parseable: {metrics['json_parseable_count']}/{metrics['total_trials']} | Schema Valid: {metrics['schema_valid_count']}/{metrics['total_trials']}")


if __name__ == "__main__":
    main()
