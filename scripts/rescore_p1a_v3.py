#!/usr/bin/env python3
"""Offline Rescorer for P1a-v3 Evidence using Updated Strict Evaluator.

Reads existing evidence from reports/evidence/p1a_v3/p1a_v3_20260928_012052_b272f5/
and applies the updated scoring evaluator without modifying the original summary.json.
Outputs differences to rescore_strict_comparison.json.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scoring_evaluator import (
    evaluate_navigation_episode,
    evaluate_cancellation_episode,
    load_scoring_rules,
)


def rescore_run(run_dir: Path, scoring_rules_path: str = "configs/scoring_rules.yaml") -> Dict[str, Any]:
    summary_file = run_dir / "summary.json"
    if not summary_file.exists():
        raise FileNotFoundError(f"summary.json not found in {run_dir}")

    with open(summary_file, "r", encoding="utf-8") as f:
        old_summary = json.load(f)

    rules = load_scoring_rules(scoring_rules_path)
    thresholds = rules["thresholds"]

    episodes_rescore = []

    for ep in old_summary.get("episodes", []):
        ep_idx = ep["episode_index"]
        ep_dir = run_dir / f"episode_{ep_idx}"
        is_cancel = ep.get("is_cancel_test", False)
        target_goal = ep.get("goal")
        nav2_status = ep.get("nav2_action_status")

        stability_file = ep_dir / "stability_window.json"
        if not stability_file.exists():
            episodes_rescore.append({
                "episode_index": ep_idx,
                "rescore_status": "CANNOT_RESCORE_MISSING_STABILITY_FILE",
            })
            continue

        with open(stability_file, "r", encoding="utf-8") as f:
            stability_samples = json.load(f)

        old_eval = ep.get("evaluation", {})

        if not is_cancel:
            new_eval = evaluate_navigation_episode(
                target_goal=target_goal,
                nav2_status=nav2_status,
                final_gt=ep.get("final_states", {}).get("gt"),
                final_amcl=ep.get("final_states", {}).get("amcl"),
                stability_samples=stability_samples,
                thresholds=thresholds,
                safety_intervention=old_eval.get("halt_evaluation", {}).get("safety_intervention", False),
            )
            strict_match = (new_eval["strict_physical_arrival_and_stable"] == old_eval.get("strict_physical_arrival_and_stable"))
        else:
            new_eval = evaluate_cancellation_episode(
                nav2_status=nav2_status,
                movement_confirmed_before_cancel=old_eval.get("movement_confirmed_before_cancel", True),
                cancel_request_accepted=old_eval.get("cancel_request_accepted", True),
                stability_samples=stability_samples,
                thresholds=thresholds,
                safety_intervention=old_eval.get("halt_evaluation", {}).get("safety_intervention", False),
            )
            strict_match = (new_eval["cancel_stop_verified"] == old_eval.get("cancel_stop_verified"))

        diffs = {}
        if not is_cancel:
            if new_eval["strict_physical_arrival_and_stable"] != old_eval.get("strict_physical_arrival_and_stable"):
                diffs["strict_physical_arrival_and_stable"] = {
                    "old": old_eval.get("strict_physical_arrival_and_stable"),
                    "new": new_eval["strict_physical_arrival_and_stable"],
                }
        else:
            if new_eval["cancel_stop_verified"] != old_eval.get("cancel_stop_verified"):
                diffs["cancel_stop_verified"] = {
                    "old": old_eval.get("cancel_stop_verified"),
                    "new": new_eval["cancel_stop_verified"],
                }

        diffs["window_valid"] = {
            "old": old_eval.get("window_evaluation", {}).get("window_valid"),
            "new": new_eval.get("window_evaluation", {}).get("window_valid"),
        }
        diffs["halt_verified"] = {
            "old": old_eval.get("halt_evaluation", {}).get("halt_verified"),
            "new": new_eval.get("halt_evaluation", {}).get("halt_verified"),
        }

        episodes_rescore.append({
            "episode_index": ep_idx,
            "action_id": ep.get("action_id"),
            "is_cancel_test": is_cancel,
            "old_evaluation_summary": {
                "window_valid": old_eval.get("window_evaluation", {}).get("window_valid"),
                "halt_verified": old_eval.get("halt_evaluation", {}).get("halt_verified"),
                "strict_passed": old_eval.get("strict_physical_arrival_and_stable") if not is_cancel else old_eval.get("cancel_stop_verified"),
            },
            "new_strict_evaluation_summary": {
                "window_valid": new_eval.get("window_evaluation", {}).get("window_valid"),
                "halt_verified": new_eval.get("halt_evaluation", {}).get("halt_verified"),
                "strict_passed": new_eval.get("strict_physical_arrival_and_stable") if not is_cancel else new_eval.get("cancel_stop_verified"),
                "odom_duration_covered": new_eval.get("window_evaluation", {}).get("odom_duration_covered"),
                "gt_duration_covered": new_eval.get("window_evaluation", {}).get("gt_duration_covered"),
                "unique_odom_count": new_eval.get("window_evaluation", {}).get("unique_odom_count"),
                "unique_gt_count": new_eval.get("window_evaluation", {}).get("unique_gt_count"),
                "failure_reasons": new_eval.get("window_evaluation", {}).get("failure_reasons"),
            },
            "differences": diffs,
            "full_new_evaluation": new_eval,
        })

    result = {
        "run_id": old_summary.get("run_id"),
        "scoring_rules_applied": rules,
        "episodes_rescore": episodes_rescore,
    }

    out_file = run_dir / "rescore_strict_comparison.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Rescore complete. Saved to {out_file}")
    return result


if __name__ == "__main__":
    p = Path("reports/evidence/p1a_v3/p1a_v3_20260928_012052_b272f5")
    rescore_run(p)
