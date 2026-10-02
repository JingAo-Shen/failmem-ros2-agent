"""
Reproducible Pilot Evaluation Runner for FailMem Stage 2.
Executes 75 paired evaluation units (15 task sequences x 5 methods),
logs all raw traces, and outputs structured JSON/CSV metrics.
"""
import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..env.scenarios import get_pilot_scenarios, get_development_scenarios
from ..memory.baselines import (
    B0_NoMemory,
    B1_UnstructuredNLMemory,
    B2_StaticConditionalMemory,
    B3_DecayMemory,
    F_ConditionAwareMemory,
)
from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from .scorer import PilotScorer


def create_memory_adapter(method_name: str):
    if method_name == "B0":
        return B0_NoMemory()
    elif method_name == "B1":
        return B1_UnstructuredNLMemory()
    elif method_name == "B2":
        return B2_StaticConditionalMemory()
    elif method_name == "B3":
        return B3_DecayMemory(ttl_tasks=1)
    elif method_name == "F":
        return F_ConditionAwareMemory()
    else:
        raise ValueError(f"Unknown method name: {method_name}")


def run_pilot_benchmark(
    model_path: Optional[str] = None,
    output_dir: str = "research/agent_task_repair/results",
    device: str = "cuda",
    scenarios: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if scenarios is None:
        scenarios = get_pilot_scenarios()

    methods = ["B0", "B1", "B2", "B3", "F"]
    print(f"================================================================================")
    print(f"STARTING FAILMEM STAGE 2 PILOT EVALUATION BENCHMARK")
    print(f"Total Sequences: {len(scenarios)} | Methods: {methods} | Total Units: {len(scenarios) * len(methods)}")
    print(f"Model Path: {model_path or 'Deterministic Fallback Engine'}")
    print(f"================================================================================")

    # Initialize shared LLM Backend
    llm = LLMBackend(model_path=model_path, device=device)

    all_sequence_results = []
    category_summary: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        "Cat1_Valid": {m: [] for m in methods},
        "Cat2_Stale": {m: [] for m in methods},
        "Cat3_Inapplicable": {m: [] for m in methods},
    }

    t0_global = time.time()
    unit_idx = 0

    for seq in scenarios:
        seq_id = seq["sequence_id"]
        category = seq.get("category", "Unspecified")
        tasks = seq["tasks"]

        print(f"\n--- Sequence: {seq_id} ({category}) ---")

        for method in methods:
            unit_idx += 1
            print(f"[{unit_idx:02d}/{len(scenarios)*len(methods)}] Running Method: {method} on {seq_id}...")

            # Fresh memory adapter for each independent sequence
            memory = create_memory_adapter(method)
            runner = AgentRunner(llm_backend=llm, memory_adapter=memory)

            task_runs = []
            for t_idx, task_spec in enumerate(tasks):
                task_run = runner.run_task(task_spec, task_index=t_idx)
                task_runs.append(task_run)

            seq_score = PilotScorer.score_sequence_results(task_runs)
            eval_record = {
                "sequence_id": seq_id,
                "category": category,
                "method": method,
                "metrics": seq_score,
                "task_runs": task_runs,
            }
            all_sequence_results.append(eval_record)
            if category in category_summary:
                category_summary[category][method].append(seq_score)

    t1_global = time.time()

    # Aggregate by method across entire pilot
    method_aggregates = {}
    for m in methods:
        m_runs = [r["metrics"] for r in all_sequence_results if r["method"] == m]
        n_seq = len(m_runs)
        if n_seq > 0:
            method_aggregates[m] = {
                "avg_success_rate": round(sum(r["success_rate"] for r in m_runs) / n_seq, 4),
                "avg_violation_rate": round(sum(r["constraint_violation_rate"] for r in m_runs) / n_seq, 4),
                "total_repeated_failures": sum(r["repeated_failures"] for r in m_runs),
                "total_unwarranted_avoidance": sum(r["unwarranted_avoidance_count"] for r in m_runs),
                "avg_sim_time_s": round(sum(r["total_sim_time_s"] for r in m_runs) / n_seq, 2),
                "avg_battery_consumed": round(sum(r["total_battery_consumed"] for r in m_runs) / n_seq, 2),
                "total_tokens": sum(r["total_tokens"] for r in m_runs),
                "total_wall_time_s": round(sum(r["total_wall_time_s"] for r in m_runs), 2),
            }

    # Aggregate by category and method
    category_aggregates = {}
    for cat, m_dict in category_summary.items():
        category_aggregates[cat] = {}
        for m, scores in m_dict.items():
            if scores:
                category_aggregates[cat][m] = {
                    "success_rate": round(sum(s["success_rate"] for s in scores) / len(scores), 4),
                    "violation_rate": round(sum(s["constraint_violation_rate"] for s in scores) / len(scores), 4),
                    "repeated_failures": sum(s["repeated_failures"] for s in scores),
                    "unwarranted_avoidances": sum(s["unwarranted_avoidance_count"] for s in scores),
                    "avg_sim_time_s": round(sum(s["total_sim_time_s"] for s in scores) / len(scores), 2),
                    "avg_battery": round(sum(s["total_battery_consumed"] for s in scores) / len(scores), 2),
                }

    final_payload = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_wall_time_s": round(t1_global - t0_global, 2),
        "total_units_evaluated": len(all_sequence_results),
        "llm_stats": llm.get_aggregate_stats(),
        "method_aggregates": method_aggregates,
        "category_aggregates": category_aggregates,
        "raw_results": all_sequence_results,
    }

    # Save to disk
    raw_json_file = out_path / "pilot_raw_results.json"
    with open(raw_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)

    print(f"\n[SUCCESS] Pilot evaluation finished in {t1_global - t0_global:.2f}s.")
    print(f"[SUCCESS] Raw results saved to {raw_json_file}.")
    return final_payload


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None, help="Path to local HuggingFace model")
    parser.add_argument("--output", type=str, default="research/agent_task_repair/results", help="Output directory")
    args = parser.parse_args()

    run_pilot_benchmark(model_path=args.model, output_dir=args.output)
