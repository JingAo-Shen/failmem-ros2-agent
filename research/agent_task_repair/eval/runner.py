"""
Reproducible Benchmark Runner for FailMem Stage 2.
Executes paired evaluation units (sequences x 5 methods),
logs all raw traces, and outputs structured JSON metrics.
"""
import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..env.scenarios import get_development_scenarios, get_exploratory_pilot_scenarios
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


def run_benchmark(
    model_path: Optional[str] = None,
    output_dir: str = "research/agent_task_repair/results",
    output_filename: str = "dev_benchmark_results.json",
    device: str = "cuda",
    scenarios: Optional[List[Dict[str, Any]]] = None,
    allow_fallback: bool = False,
) -> Dict[str, Any]:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if scenarios is None:
        scenarios = get_development_scenarios()

    methods = ["B0", "B1", "B2", "B3", "F"]
    total_units = len(scenarios) * len(methods)
    print("=" * 80)
    print("STARTING FAILMEM STAGE 2 BENCHMARK RUN")
    print(f"Total Sequences: {len(scenarios)} | Methods: {methods} | Total Units: {total_units}")
    print(f"Model Path: {model_path or 'Fallback Testing Engine'}")
    print("=" * 80)

    # Initialize shared LLM Backend
    llm = LLMBackend(model_path=model_path, device=device, allow_fallback=allow_fallback)

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
            print(f"[{unit_idx:02d}/{total_units}] Running Method: {method} on {seq_id}...")

            # Fresh memory adapter for each independent sequence run
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

    # Aggregate by method across all executed sequences
    method_aggregates = {}
    for m in methods:
        m_runs = [r["metrics"] for r in all_sequence_results if r["method"] == m]
        n_seq = len(m_runs)
        if n_seq > 0:
            method_aggregates[m] = {
                "avg_task_success_rate": round(sum(r["task_success_rate"] for r in m_runs) / n_seq, 4),
                "avg_eval_success_rate": round(sum(r["evaluation_task_success_rate"] for r in m_runs) / n_seq, 4),
                "sequence_full_success_rate": round(sum(r["sequence_full_success"] for r in m_runs) / n_seq, 4),
                "avg_hard_violation_rate": round(sum(r["hard_violation_rate"] for r in m_runs) / n_seq, 4),
                "total_repeated_failures": sum(r["repeated_failures"] for r in m_runs),
                "total_unwarranted_detours": sum(r["unwarranted_detour_count"] for r in m_runs),
                "total_parse_errors": sum(r.get("parse_error_tasks", 0) for r in m_runs),
                "total_dead_loops": sum(r.get("dead_loop_aborts", 0) for r in m_runs),
                "avg_sim_time_s": round(sum(r["total_sim_time_s"] for r in m_runs) / n_seq, 2),
                "avg_battery_consumed": round(sum(r["total_battery_consumed"] for r in m_runs) / n_seq, 2),
                "total_llm_calls": sum(r["total_llm_calls"] for r in m_runs),
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
                    "task_success_rate": round(sum(s["task_success_rate"] for s in scores) / len(scores), 4),
                    "eval_success_rate": round(sum(s["evaluation_task_success_rate"] for s in scores) / len(scores), 4),
                    "hard_violation_rate": round(sum(s["hard_violation_rate"] for s in scores) / len(scores), 4),
                    "repeated_failures": sum(s["repeated_failures"] for s in scores),
                    "unwarranted_detours": sum(s["unwarranted_detour_count"] for s in scores),
                    "parse_errors": sum(s.get("parse_error_tasks", 0) for s in scores),
                    "avg_sim_time_s": round(sum(s["total_sim_time_s"] for s in scores) / len(scores), 2),
                    "avg_battery": round(sum(s["total_battery_consumed"] for s in scores) / len(scores), 2),
                }

    final_payload = {
        "benchmark_type": "development_validation",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_wall_time_s": round(t1_global - t0_global, 2),
        "total_units_evaluated": len(all_sequence_results),
        "llm_stats": llm.get_aggregate_stats(),
        "method_aggregates": method_aggregates,
        "category_aggregates": category_aggregates,
        "raw_results": all_sequence_results,
    }

    # Save to disk
    raw_json_file = out_path / output_filename
    with open(raw_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)

    print(f"\n[SUCCESS] Benchmark finished in {t1_global - t0_global:.2f}s.")
    print(f"[SUCCESS] Results saved to {raw_json_file}.")
    return final_payload


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None, help="Path to local HuggingFace model")
    parser.add_argument("--output", type=str, default="research/agent_task_repair/results", help="Output directory")
    parser.add_argument("--output_file", type=str, default="dev_benchmark_results.json", help="Output JSON filename")
    parser.add_argument("--fallback", action="store_true", help="Allow fallback engine (unit test only)")
    args = parser.parse_args()

    run_benchmark(
        model_path=args.model,
        output_dir=args.output,
        output_filename=args.output_file,
        allow_fallback=args.fallback,
    )
