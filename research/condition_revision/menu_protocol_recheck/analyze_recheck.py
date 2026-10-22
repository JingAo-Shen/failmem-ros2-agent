"""
Analysis script for Phase P1c Menu Protocol Recheck:
Processes summary.csv and evidence_trajectories/ to produce recheck_analysis_report.json.
"""
import os
import sys
import csv
import json
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_CSV = os.path.join(SCRIPT_DIR, "summary.csv")
STEP_CSV = os.path.join(SCRIPT_DIR, "step_summary.csv")
REPORT_JSON = os.path.join(SCRIPT_DIR, "recheck_analysis_report.json")


def analyze():
    if not os.path.exists(SUMMARY_CSV):
        print("Summary CSV not found.")
        return

    rows = []
    with open(SUMMARY_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    print(f"Loaded {len(rows)} episodes from {SUMMARY_CSV}")

    # Check blank cancellation events in step_summary.csv
    blank_cancels = []
    if os.path.exists(STEP_CSV):
        with open(STEP_CSV, "r", encoding="utf-8") as f:
            for s in csv.DictReader(f):
                if s.get("adapter_reason") == "menu_blank_cancellation":
                    blank_cancels.append(s)

    grid = {}
    cond_stats = defaultdict(lambda: {
        "total": 0, "success": 0, "scores": [], "steps": [], "moves": [],
        "success_steps": [], "success_moves": [], "costs": [], "durations": []
    })
    var_stats = defaultdict(lambda: defaultdict(list))

    for r in rows:
        v = int(r["variation"])
        b = int(r["block"])
        c = r["condition"]
        succ = (r["success"].strip().lower() == "true")
        score = float(r["final_score"])
        steps = int(r["decision_steps"])
        moves = int(r["env_moves"]) if r.get("env_moves") else 0
        cost = float(r["estimated_cost_usd"])
        dur = float(r["duration_seconds"])

        grid[(v, b, c)] = {
            "episode_id": r["episode_id"],
            "success": succ,
            "score": score,
            "steps": steps,
            "moves": moves,
            "cost": cost,
            "duration": dur,
            "term_reason": r.get("termination_reason", ""),
            "is_source_instance_replay": (v == 2)
        }

        s = cond_stats[c]
        s["total"] += 1
        if succ:
            s["success"] += 1
            s["success_steps"].append(steps)
            s["success_moves"].append(moves)
        s["scores"].append(score)
        s["steps"].append(steps)
        s["moves"].append(moves)
        s["costs"].append(cost)
        s["durations"].append(dur)

        var_stats[v][c].append({
            "block": b, "episode_id": r["episode_id"], "success": succ, "score": score, "steps": steps, "moves": moves
        })

    def mean(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    overall_summary = {}
    for c in ["A", "B", "C"]:
        s = cond_stats[c]
        tot = s["total"]
        succ = s["success"]
        overall_summary[f"Condition_{c}"] = {
            "total_episodes": tot,
            "success_count": succ,
            "success_rate": f"{succ}/{tot} ({succ/tot*100:.1f}%)" if tot > 0 else "0/0",
            "mean_final_score": mean(s["scores"]),
            "mean_decision_steps_all": mean(s["steps"]),
            "mean_decision_steps_successful": mean(s["success_steps"]),
            "mean_env_moves_all": mean(s["moves"]),
            "mean_env_moves_successful": mean(s["success_moves"]),
            "mean_duration_seconds": mean(s["durations"]),
            "total_cost_usd": round(sum(s["costs"]), 4)
        }

    # Paired comparisons across matching (variation, block)
    def compute_paired(test_cond, base_cond):
        pairs = []
        for v in [0, 2]:
            for b in [3, 4]:
                base = grid.get((v, b, base_cond))
                test = grid.get((v, b, test_cond))
                if base and test:
                    pairs.append({
                        "variation": v,
                        "is_source_instance_replay": (v == 2),
                        "block": b,
                        "episode_base": base["episode_id"],
                        "episode_test": test["episode_id"],
                        f"score_{base_cond}": base["score"],
                        f"score_{test_cond}": test["score"],
                        f"success_{base_cond}": base["success"],
                        f"success_{test_cond}": test["success"],
                        f"steps_{base_cond}": base["steps"],
                        f"steps_{test_cond}": test["steps"],
                        "delta_score": round(test["score"] - base["score"], 2),
                        "both_succeeded": base["success"] and test["success"],
                        "delta_steps": (test["steps"] - base["steps"]) if (base["success"] and test["success"]) else None
                    })

        both_succ_pairs = [p for p in pairs if p["both_succeeded"]]
        mean_delta_steps = mean([p["delta_steps"] for p in both_succ_pairs]) if both_succ_pairs else None
        
        test_wins = sum(1 for p in pairs if p[f"score_{test_cond}"] > p[f"score_{base_cond}"])
        base_wins = sum(1 for p in pairs if p[f"score_{test_cond}"] < p[f"score_{base_cond}"])
        ties = sum(1 for p in pairs if p[f"score_{test_cond}"] == p[f"score_{base_cond}"])

        succ_wins = sum(1 for p in pairs if p[f"success_{test_cond}"] and not p[f"success_{base_cond}"])
        succ_losses = sum(1 for p in pairs if not p[f"success_{test_cond}"] and p[f"success_{base_cond}"])
        succ_ties = sum(1 for p in pairs if p[f"success_{test_cond}"] == p[f"success_{base_cond}"])

        return {
            "comparison": f"Condition {test_cond} vs Condition {base_cond}",
            "total_pairs": len(pairs),
            "score_comparison": {f"{test_cond}_higher": test_wins, f"{base_cond}_higher": base_wins, "equal_scores": ties},
            "success_comparison": {f"{test_cond}_success_only": succ_wins, f"{base_cond}_success_only": succ_losses, "both_same_success": succ_ties},
            "both_succeeded_count": len(both_succ_pairs),
            "mean_delta_steps_when_both_succeeded": mean_delta_steps,
            "paired_runs": pairs
        }

    b_vs_a = compute_paired("B", "A")
    c_vs_a = compute_paired("C", "A")

    report = {
        "phase": "P1c_MENU_PROTOCOL_RECHECK",
        "total_episodes": len(rows),
        "overall_summary": overall_summary,
        "menu_blank_cancellations_count": len(blank_cancels),
        "menu_blank_cancellations_details": [
            {
                "episode_id": s["episode_id"],
                "step": s["decision_step"],
                "executed_action": s["executed_action"],
                "obs_before": s["env_obs"]
            } for s in blank_cancels
        ],
        "variation_breakdown": {
            f"variation_{v}": {
                "is_source_instance_replay": (v == 2),
                "conditions": {
                    c: var_stats[v][c] for c in ["A", "B", "C"]
                }
            } for v in [0, 2]
        },
        "paired_comparison_B_vs_A": b_vs_a,
        "paired_comparison_C_vs_A": c_vs_a
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Recheck report written to {REPORT_JSON}")

    print("\n================== P1c RECHECK SUMMARY ==================")
    for c in ["A", "B", "C"]:
        info = overall_summary[f"Condition_{c}"]
        print(f"Condition {c}: Success={info['success_rate']}, MeanScore={info['mean_final_score']}, MeanSteps={info['mean_decision_steps_all']}, MeanSteps(Succ)={info['mean_decision_steps_successful']}, Cost=${info['total_cost_usd']}")

    print("\n================== PAIRED B vs A ==================")
    print("Success comparison:", b_vs_a["success_comparison"])
    print(f"Both succeeded: {b_vs_a['both_succeeded_count']}/4 pairs, Mean delta steps (B - A): {b_vs_a['mean_delta_steps_when_both_succeeded']}")

    print("\n================== PAIRED C vs A ==================")
    print("Success comparison:", c_vs_a["success_comparison"])
    print(f"Both succeeded: {c_vs_a['both_succeeded_count']}/4 pairs, Mean delta steps (C - A): {c_vs_a['mean_delta_steps_when_both_succeeded']}")

if __name__ == "__main__":
    analyze()
