"""
Analysis script for Natural Experience Transfer Screening (Phase P1b):
Processes natural_experience_screen_summary.csv to produce:
1. Overall condition summaries (A, B, C)
2. Variation-level breakdown (Var 0, 1, 2, 3)
3. Paired comparisons: B vs A, C vs A
4. Outputs paired_comparison_report.json
"""
import os
import sys
import csv
import json
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SUMMARY_CSV = os.path.join(SCRIPT_DIR, "natural_experience_screen_summary.csv")
REPORT_JSON = os.path.join(SCRIPT_DIR, "paired_comparison_report.json")


def analyze():
    if not os.path.exists(SUMMARY_CSV):
        print(f"Summary CSV not found at {SUMMARY_CSV}")
        return

    rows = []
    with open(SUMMARY_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    print(f"Loaded {len(rows)} episodes from {SUMMARY_CSV}")

    # Index by (variation, block, condition)
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
            "term_reason": r.get("termination_reason", "")
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
            "block": b, "success": succ, "score": score, "steps": steps, "moves": moves
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
        for v in [0, 1, 2, 3]:
            for b in [1, 2]:
                base = grid.get((v, b, base_cond))
                test = grid.get((v, b, test_cond))
                if base and test:
                    pairs.append({
                        "variation": v,
                        "block": b,
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
        
        # Count outcomes
        test_wins = sum(1 for p in pairs if p[f"score_{test_cond}"] > p[f"score_{base_cond}"])
        base_wins = sum(1 for p in pairs if p[f"score_{test_cond}"] < p[f"score_{base_cond}"])
        ties = sum(1 for p in pairs if p[f"score_{test_cond}"] == p[f"score_{base_cond}"])

        return {
            "comparison": f"Condition {test_cond} vs Condition {base_cond}",
            "total_pairs": len(pairs),
            "score_wins": {test_cond: test_wins, base_cond: base_wins, "ties": ties},
            "both_succeeded_count": len(both_succ_pairs),
            "mean_delta_steps_when_both_succeeded": mean_delta_steps,
            "paired_runs": pairs
        }

    b_vs_a = compute_paired("B", "A")
    c_vs_a = compute_paired("C", "A")

    report = {
        "phase": "P1b_NATURAL_EXPERIENCE_SCREEN",
        "total_analyzed_episodes": len(rows),
        "overall_summary": overall_summary,
        "variation_breakdown": {
            f"variation_{v}": {
                c: var_stats[v][c] for c in ["A", "B", "C"]
            } for v in [0, 1, 2, 3]
        },
        "paired_comparison_B_vs_A": b_vs_a,
        "paired_comparison_C_vs_A": c_vs_a
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Analysis saved successfully to {REPORT_JSON}")

    print("\n================== OVERALL SUMMARY ==================")
    for c in ["A", "B", "C"]:
        info = overall_summary[f"Condition_{c}"]
        print(f"Condition {c}: Success={info['success_rate']}, MeanScore={info['mean_final_score']}, MeanSteps={info['mean_decision_steps_all']}, MeanSteps(Succ)={info['mean_decision_steps_successful']}, Cost=${info['total_cost_usd']}")

    print("\n================== PAIRED B vs A ==================")
    print(f"Wins: B={b_vs_a['score_wins']['B']}, A={b_vs_a['score_wins']['A']}, Ties={b_vs_a['score_wins']['ties']}")
    print(f"Both succeeded: {b_vs_a['both_succeeded_count']}/8 pairs, Mean delta steps (B - A): {b_vs_a['mean_delta_steps_when_both_succeeded']}")

    print("\n================== PAIRED C vs A ==================")
    print(f"Wins: C={c_vs_a['score_wins']['C']}, A={c_vs_a['score_wins']['A']}, Ties={c_vs_a['score_wins']['ties']}")
    print(f"Both succeeded: {c_vs_a['both_succeeded_count']}/8 pairs, Mean delta steps (C - A): {c_vs_a['mean_delta_steps_when_both_succeeded']}")

if __name__ == "__main__":
    analyze()
