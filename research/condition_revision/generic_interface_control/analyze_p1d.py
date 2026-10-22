"""
Analysis script for Phase P1d Generic Interface Control:
Processes summary.csv, step_summary.csv, and evidence_trajectories/ to produce p1d_analysis_report.json.
- Primary comparison: GC vs G
- Secondary comparisons: G vs A, C vs A, GC vs C
- Broken down by condition, variation, paired match-ups, error liquid actions, menu actions.
"""
import os
import sys
import csv
import json
import hashlib
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../.."))
SUMMARY_CSV = os.path.join(SCRIPT_DIR, "summary.csv")
STEP_CSV = os.path.join(SCRIPT_DIR, "step_summary.csv")
REPORT_JSON = os.path.join(SCRIPT_DIR, "p1d_analysis_report.json")
INDEX_JSON = os.path.join(SCRIPT_DIR, "trajectory_evidence_index.json")
TRAJ_DIR = os.path.join(SCRIPT_DIR, "evidence_trajectories")


def mean(lst):
    return round(sum(lst) / len(lst), 2) if lst else 0.0


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

    # Inspect error liquid actions and menu actions in step_summary.csv
    dunk_error_steps = []
    menu_disambiguation_steps = []
    menu_blank_cancel_steps = []

    if os.path.exists(STEP_CSV):
        with open(STEP_CSV, "r", encoding="utf-8") as f:
            for s in csv.DictReader(f):
                if s.get("is_dunk_error", "").lower() == "true":
                    dunk_error_steps.append(s)
                if s.get("is_menu_disambiguation", "").lower() == "true":
                    menu_disambiguation_steps.append(s)
                if s.get("is_menu_blank_cancellation", "").lower() == "true":
                    menu_blank_cancel_steps.append(s)

    grid = {}
    cond_stats = defaultdict(lambda: {
        "total": 0, "success": 0, "scores": [], "decision_steps": [], "env_moves": [],
        "success_decision_steps": [], "success_env_moves": [], "costs": [], "durations": [],
        "calls": [], "in_tokens": [], "out_tokens": [], "dunk_errors": 0, "menu_disambiguations": 0,
        "menu_blank_cancels": 0, "term_reasons": defaultdict(int)
    })
    var_cond_stats = defaultdict(lambda: defaultdict(list))

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
        calls = int(r["task_model_calls"])
        in_tok = int(r["task_input_tokens"])
        out_tok = int(r["task_output_tokens"])
        dunk_errs = int(r.get("dunk_errors_count", 0))
        menu_dis = int(r.get("menu_disambiguations_count", 0))
        menu_cancels = int(r.get("menu_blank_cancellations_count", 0))
        term_reason = r.get("termination_reason", "")

        grid[(v, b, c)] = {
            "episode_id": r["episode_id"],
            "success": succ,
            "score": score,
            "decision_steps": steps,
            "env_moves": moves,
            "cost": cost,
            "duration": dur,
            "calls": calls,
            "term_reason": term_reason,
            "dunk_errors": dunk_errs,
            "menu_disambiguations": menu_dis,
            "menu_blank_cancels": menu_cancels,
            "is_source_instance_replay": (v == 2)
        }

        s = cond_stats[c]
        s["total"] += 1
        if succ:
            s["success"] += 1
            s["success_decision_steps"].append(steps)
            s["success_env_moves"].append(moves)
        s["scores"].append(score)
        s["decision_steps"].append(steps)
        s["env_moves"].append(moves)
        s["costs"].append(cost)
        s["durations"].append(dur)
        s["calls"].append(calls)
        s["in_tokens"].append(in_tok)
        s["out_tokens"].append(out_tok)
        s["dunk_errors"] += dunk_errs
        s["menu_disambiguations"] += menu_dis
        s["menu_blank_cancels"] += menu_cancels
        s["term_reasons"][term_reason] += 1

        var_cond_stats[v][c].append({
            "block": b,
            "episode_id": r["episode_id"],
            "success": succ,
            "score": score,
            "decision_steps": steps,
            "env_moves": moves,
            "dunk_errors": dunk_errs,
            "term_reason": term_reason
        })

    overall_summary = {}
    for c in ["A", "G", "C", "GC"]:
        s = cond_stats[c]
        tot = s["total"]
        succ = s["success"]
        overall_summary[f"Condition_{c}"] = {
            "total_episodes": tot,
            "success_count": succ,
            "success_rate": f"{succ}/{tot} ({succ/tot*100:.1f}%)" if tot > 0 else "0/0",
            "mean_final_score": mean(s["scores"]),
            "mean_decision_steps_all": mean(s["decision_steps"]),
            "mean_decision_steps_successful": mean(s["success_decision_steps"]),
            "mean_env_moves_all": mean(s["env_moves"]),
            "mean_env_moves_successful": mean(s["success_env_moves"]),
            "total_model_calls": sum(s["calls"]),
            "total_input_tokens": sum(s["in_tokens"]),
            "total_output_tokens": sum(s["out_tokens"]),
            "total_cost_usd": round(sum(s["costs"]), 4),
            "mean_duration_seconds": mean(s["durations"]),
            "total_dunk_errors": s["dunk_errors"],
            "total_menu_disambiguations": s["menu_disambiguations"],
            "total_menu_blank_cancellations": s["menu_blank_cancels"],
            "termination_reasons": dict(s["term_reasons"])
        }

    # Compute paired comparisons
    def compute_paired(test_cond, base_cond):
        pairs = []
        for v in [0, 2]:
            for b in [5, 6]:
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
                        f"steps_{base_cond}": base["decision_steps"],
                        f"steps_{test_cond}": test["decision_steps"],
                        f"moves_{base_cond}": base["env_moves"],
                        f"moves_{test_cond}": test["env_moves"],
                        "delta_score": round(test["score"] - base["score"], 2),
                        "both_succeeded": base["success"] and test["success"],
                        "delta_decision_steps": (test["decision_steps"] - base["decision_steps"]) if (base["success"] and test["success"]) else None,
                        "delta_env_moves": (test["env_moves"] - base["env_moves"]) if (base["success"] and test["success"]) else None
                    })

        both_succ = [p for p in pairs if p["both_succeeded"]]
        mean_delta_steps = mean([p["delta_decision_steps"] for p in both_succ]) if both_succ else None
        mean_delta_moves = mean([p["delta_env_moves"] for p in both_succ]) if both_succ else None

        score_test_wins = sum(1 for p in pairs if p[f"score_{test_cond}"] > p[f"score_{base_cond}"])
        score_base_wins = sum(1 for p in pairs if p[f"score_{test_cond}"] < p[f"score_{base_cond}"])
        score_ties = sum(1 for p in pairs if p[f"score_{test_cond}"] == p[f"score_{base_cond}"])

        succ_test_only = sum(1 for p in pairs if p[f"success_{test_cond}"] and not p[f"success_{base_cond}"])
        succ_base_only = sum(1 for p in pairs if not p[f"success_{test_cond}"] and p[f"success_{base_cond}"])
        succ_same = sum(1 for p in pairs if p[f"success_{test_cond}"] == p[f"success_{base_cond}"])

        return {
            "comparison": f"Condition {test_cond} vs Condition {base_cond}",
            "total_pairs": len(pairs),
            "score_comparison": {f"{test_cond}_higher": score_test_wins, f"{base_cond}_higher": score_base_wins, "equal": score_ties},
            "success_comparison": {f"{test_cond}_success_only": succ_test_only, f"{base_cond}_success_only": succ_base_only, "both_same": succ_same},
            "both_succeeded_count": len(both_succ),
            "mean_delta_decision_steps_when_both_succeeded": mean_delta_steps,
            "mean_delta_env_moves_when_both_succeeded": mean_delta_moves,
            "paired_runs": pairs
        }

    primary_gc_vs_g = compute_paired("GC", "G")
    secondary_g_vs_a = compute_paired("G", "A")
    secondary_c_vs_a = compute_paired("C", "A")
    secondary_gc_vs_c = compute_paired("GC", "C")

    # Format dunk error samples
    dunk_error_summary = []
    for de in dunk_error_steps[:20]:
        dunk_error_summary.append({
            "episode_id": de.get("episode_id"),
            "condition": de.get("condition"),
            "step": de.get("decision_step"),
            "executed_action": de.get("executed_action"),
            "observation": de.get("env_obs")
        })

    report = {
        "phase": "P1d_GENERIC_INTERFACE_CONTROL",
        "total_episodes": len(rows),
        "overall_summary": overall_summary,
        "primary_comparison_GC_vs_G": primary_gc_vs_g,
        "secondary_comparison_G_vs_A": secondary_g_vs_a,
        "secondary_comparison_C_vs_A": secondary_c_vs_a,
        "secondary_comparison_GC_vs_C": secondary_gc_vs_c,
        "variation_breakdown": {
            f"variation_{v}": {
                "is_source_instance_replay": (v == 2),
                "conditions": {
                    c: var_cond_stats[v][c] for c in ["A", "G", "C", "GC"]
                }
            } for v in [0, 2]
        },
        "dunk_errors_sample": dunk_error_summary,
        "menu_interaction_stats": {
            "total_menu_disambiguations": len(menu_disambiguation_steps),
            "total_menu_blank_cancellations": len(menu_blank_cancel_steps),
            "blank_cancellations_by_condition": {
                c: sum(1 for m in menu_blank_cancel_steps if m.get("condition") == c) for c in ["A", "G", "C", "GC"]
            }
        }
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"P1d analysis report written to {REPORT_JSON}")

    # Generate trajectory evidence index
    if os.path.exists(TRAJ_DIR):
        traj_index = []
        for fname in sorted(os.listdir(TRAJ_DIR)):
            if fname.endswith(".json"):
                fpath = os.path.join(TRAJ_DIR, fname)
                with open(fpath, "rb") as f:
                    file_bytes = f.read()
                    sha = hashlib.sha256(file_bytes).hexdigest()
                ep_id = fname.split("_")[0]
                rel_path = os.path.relpath(fpath, REPO_ROOT)
                traj_index.append({
                    "episode_id": ep_id,
                    "filename": fname,
                    "relative_path": rel_path,
                    "sha256": sha
                })
        index_data = {
            "phase": "P1d_GENERIC_INTERFACE_CONTROL",
            "trajectories": traj_index
        }
        with open(INDEX_JSON, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        print(f"Trajectory evidence index written to {INDEX_JSON} ({len(traj_index)} entries)")

    print("\n================== P1d OVERALL SUMMARY ==================")
    for c in ["A", "G", "C", "GC"]:
        info = overall_summary[f"Condition_{c}"]
        print(f"Condition {c}: Success={info['success_rate']}, MeanScore={info['mean_final_score']}, DecisionSteps(Succ)={info['mean_decision_steps_successful']}, EnvMoves(Succ)={info['mean_env_moves_successful']}, DunkErrs={info['total_dunk_errors']}, Cost=${info['total_cost_usd']}")

    print("\n================== PRIMARY COMPARISON: GC vs G ==================")
    print("Success comparison:", primary_gc_vs_g["success_comparison"])
    print(f"Both succeeded: {primary_gc_vs_g['both_succeeded_count']}/4 pairs, Mean delta decision steps (GC - G): {primary_gc_vs_g['mean_delta_decision_steps_when_both_succeeded']}")

    print("\n================== SECONDARY COMPARISON: G vs A ==================")
    print("Success comparison:", secondary_g_vs_a["success_comparison"])

    print("\n================== SECONDARY COMPARISON: C vs A ==================")
    print("Success comparison:", secondary_c_vs_a["success_comparison"])

    print("\n================== SECONDARY COMPARISON: GC vs C ==================")
    print("Success comparison:", secondary_gc_vs_c["success_comparison"])


if __name__ == "__main__":
    analyze()
