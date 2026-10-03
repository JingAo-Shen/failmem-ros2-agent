"""
Offline Diagnosis and Detailed Trace Extraction for FailMem Stage 2 75-Unit Pilot Benchmark.
Extracts failure creation, retrieval status, 3-valued evaluations, invalidation timing,
and B2 vs F divergence points across all 75 method-sequence units.
Outputs:
  - research/agent_task_repair/results/offline_diagnosis_75.csv
  - research/agent_task_repair/results/offline_diagnosis_summary.json
"""
import json
import csv
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def run_offline_diagnosis(
    input_file: str = "research/agent_task_repair/results/pilot_75_results.json",
    csv_output_file: str = "research/agent_task_repair/results/offline_diagnosis_75.csv",
    summary_output_file: str = "research/agent_task_repair/results/offline_diagnosis_summary.json"
):
    in_path = Path(input_file)
    if not in_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_results = data.get("raw_results", [])
    print(f"[offline_diagnosis] Loaded {len(raw_results)} units from {input_file}")

    # Group units by sequence_id for easy paired comparison
    sequences_dict = {}
    for r in raw_results:
        seq_id = r["sequence_id"]
        method = r["method"]
        if seq_id not in sequences_dict:
            sequences_dict[seq_id] = {}
        sequences_dict[seq_id][method] = r

    csv_rows = []
    
    # Trackers for aggregate questions
    b2_vs_f_divergences = []
    
    # Method stats recomputation
    methods = ["B0", "B1", "B2", "B3", "F"]
    recomputed_stats = {
        m: {
            "total_tasks": 0,
            "successful_tasks": 0,
            "eval_tasks": 0,
            "eval_successful_tasks": 0,
            "seq_total": 0,
            "seq_full_success": 0,
            "hard_violation_tasks": 0,
            "repeated_failures": 0,
            "unwarranted_detours": 0,
            "parse_errors": 0,
            "total_battery": 0,
            "total_sim_time": 0.0,
            "total_llm_calls": 0,
        }
        for m in methods
    }

    # Trackers for Cat 1, 2, 3 specific checks
    cat1_checks = []
    cat2_checks = []
    cat3_checks = []

    for seq_id, m_dict in sorted(sequences_dict.items()):
        category = m_dict.get("B0", {}).get("category", "Unspecified")
        
        # Compare B2 and F on this sequence
        b2_unit = m_dict.get("B2")
        f_unit = m_dict.get("F")
        first_diff_step = "NO_DIFF"
        diff_detail = ""
        
        if b2_unit and f_unit:
            b2_tasks = b2_unit.get("task_runs", [])
            f_tasks = f_unit.get("task_runs", [])
            found_diff = False
            for t_idx in range(min(len(b2_tasks), len(f_tasks))):
                t_b2 = b2_tasks[t_idx]
                t_f = f_tasks[t_idx]
                
                # Compare step by step
                h_b2 = t_b2.get("step_history", [])
                h_f = t_f.get("step_history", [])
                traces_b2 = t_b2.get("llm_traces", [])
                traces_f = t_f.get("llm_traces", [])
                
                max_s = max(len(h_b2), len(h_f), len(traces_b2), len(traces_f))
                for s_idx in range(max_s):
                    # Check retrieved memories
                    mem_b2 = traces_b2[s_idx].get("retrieved_memories", []) if s_idx < len(traces_b2) else None
                    mem_f = traces_f[s_idx].get("retrieved_memories", []) if s_idx < len(traces_f) else None
                    
                    act_b2 = (h_b2[s_idx].get("tool"), h_b2[s_idx].get("params")) if s_idx < len(h_b2) else None
                    act_f = (h_f[s_idx].get("tool"), h_f[s_idx].get("params")) if s_idx < len(h_f) else None
                    
                    if mem_b2 != mem_f or act_b2 != act_f:
                        first_diff_step = f"T{t_idx+1}_S{s_idx+1}"
                        diff_detail = f"Mem B2={mem_b2} vs F={mem_f} | Act B2={act_b2} vs F={act_f}"
                        found_diff = True
                        break
                if found_diff:
                    break
            
            b2_vs_f_divergences.append({
                "sequence_id": seq_id,
                "category": category,
                "first_diff_step": first_diff_step,
                "detail": diff_detail,
            })

        for method in methods:
            unit = m_dict.get(method)
            if not unit:
                continue
            
            tasks = unit.get("task_runs", [])
            metrics = unit.get("metrics", {})
            
            recomputed_stats[method]["seq_total"] += 1
            if metrics.get("sequence_full_success") == 1.0:
                recomputed_stats[method]["seq_full_success"] += 1
            recomputed_stats[method]["repeated_failures"] += metrics.get("repeated_failures", 0)
            recomputed_stats[method]["unwarranted_detours"] += metrics.get("unwarranted_detour_count", 0)
            recomputed_stats[method]["parse_errors"] += metrics.get("parse_error_tasks", 0)
            recomputed_stats[method]["total_battery"] += metrics.get("total_battery_consumed", 0)
            recomputed_stats[method]["total_sim_time"] += metrics.get("total_sim_time_s", 0.0)
            recomputed_stats[method]["total_llm_calls"] += metrics.get("total_llm_calls", 0)

            for t_idx, t in enumerate(tasks):
                recomputed_stats[method]["total_tasks"] += 1
                if t.get("success", False):
                    recomputed_stats[method]["successful_tasks"] += 1
                if t_idx > 0:
                    recomputed_stats[method]["eval_tasks"] += 1
                    if t.get("success", False):
                        recomputed_stats[method]["eval_successful_tasks"] += 1
                if len(t.get("constraint_violations", [])) > 0:
                    recomputed_stats[method]["hard_violation_tasks"] += 1

                # Trace analysis for this task
                history = t.get("step_history", [])
                traces = t.get("llm_traces", [])
                
                # 1. Did failure actually occur?
                failed_steps = [h for h in history if not h.get("result", {}).get("success", True)]
                had_failure = len(failed_steps) > 0
                failure_codes = [h.get("result", {}).get("error_code") or h.get("result", {}).get("status") for h in failed_steps]

                # 2. Retrieved memories
                all_retrieved = []
                match_types = []
                for tr in traces:
                    mems = tr.get("retrieved_memories", [])
                    if mems:
                        all_retrieved.extend(mems)
                        for m_str in mems:
                            if "[MATCH]" in m_str:
                                match_types.append("MATCH")
                            elif "[MISMATCH]" in m_str:
                                match_types.append("MISMATCH")
                            elif "[UNKNOWN]" in m_str:
                                match_types.append("UNKNOWN")
                            elif "[ACTIVE]" in m_str:
                                match_types.append("ACTIVE")
                            else:
                                match_types.append("UNSTRUCTURED")

                # Check invalidation timing in Cat 2
                inval_timing = "N/A"
                if category == "Cat2_Stale" and method == "F":
                    if t_idx == 0:
                        inval_timing = "TASK_0_ACQUISITION"
                    elif t_idx >= 1:
                        door_north_transit_steps = [
                            h["step"] for h in history
                            if h.get("tool") == "navigate" and (
                                h.get("result", {}).get("observation", {}).get("door") in ("door_north", "door_south")
                                or h.get("params", {}).get("target_zone") in ("Corridor_North", "Corridor_South")
                            )
                        ]
                        if door_north_transit_steps:
                            inval_timing = f"OCCURRED_DURING_STEP_{door_north_transit_steps[0]}"
                        else:
                            inval_timing = "NO_TRANSIT_OBSERVED"

                csv_rows.append({
                    "sequence_id": seq_id,
                    "category": category,
                    "method": method,
                    "task_id": t.get("task_id"),
                    "task_index": t_idx,
                    "success": t.get("success"),
                    "step_count": t.get("step_count"),
                    "battery_consumed": t.get("battery_consumed"),
                    "sim_time_s": t.get("sim_time_s"),
                    "llm_calls": t.get("llm_calls"),
                    "had_failure": had_failure,
                    "failure_codes": ";".join(str(c) for c in failure_codes),
                    "retrieved_memories_count": len(all_retrieved),
                    "match_evaluations": ";".join(set(match_types)) if match_types else "NONE",
                    "violations": ";".join(t.get("constraint_violations", [])),
                    "b2_vs_f_first_diff": first_diff_step if method in ("B2", "F") else "N/A",
                    "invalidation_timing": inval_timing,
                })

    # Save CSV
    fieldnames = [
        "sequence_id", "category", "method", "task_id", "task_index", "success",
        "step_count", "battery_consumed", "sim_time_s", "llm_calls",
        "had_failure", "failure_codes", "retrieved_memories_count",
        "match_evaluations", "violations", "b2_vs_f_first_diff", "invalidation_timing"
    ]
    with open(csv_output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"[offline_diagnosis] Wrote {len(csv_rows)} rows to {csv_output_file}")

    # Compute high-level synthesis
    summary_report = {
        "recomputed_method_stats": recomputed_stats,
        "b2_vs_f_divergence_analysis": {
            "identical_sequences": sum(1 for d in b2_vs_f_divergences if d["first_diff_step"] == "NO_DIFF"),
            "divergent_sequences": sum(1 for d in b2_vs_f_divergences if d["first_diff_step"] != "NO_DIFF"),
            "divergences_list": b2_vs_f_divergences,
        },
    }

    with open(summary_output_file, "w", encoding="utf-8") as f:
        json.dump(summary_report, f, indent=2)
    print(f"[offline_diagnosis] Wrote summary to {summary_output_file}")

    return summary_report


if __name__ == "__main__":
    run_offline_diagnosis()
