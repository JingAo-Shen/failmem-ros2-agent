"""
Calculate exact LLM call reduction and token metrics for Batch 2 repeated constraint violation terminations.
"""
import json
from pathlib import Path

RESULTS_FILE = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/batch2_ablation_results.json")

def main():
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    results = data.get("results", [])
    max_budget = 32
    
    repeated_violation_runs = []
    for r in results:
        if r.get("termination_reason") == "REPEATED_CONSTRAINT_VIOLATION":
            calls = r.get("llm_calls", 0)
            reduction_vs_budget = (max_budget - calls) / max_budget * 100.0
            repeated_violation_runs.append({
                "group_id": r.get("group_id"),
                "task_id": r.get("task_id"),
                "llm_calls": calls,
                "max_budget": max_budget,
                "calls_avoided": max_budget - calls,
                "reduction_pct": round(reduction_vs_budget, 2),
                "total_prompt_tokens": r.get("total_prompt_tokens", 0),
                "total_generated_tokens": r.get("total_generated_tokens", 0),
            })
            
    print(f"Total runs analyzed: {len(results)}")
    print(f"Total runs terminated by REPEATED_CONSTRAINT_VIOLATION: {len(repeated_violation_runs)}")
    print("-" * 80)
    for run in repeated_violation_runs:
        print(f"[{run['group_id']}] {run['task_id'][:35]}... calls={run['llm_calls']}/{run['max_budget']} (reduction: {run['reduction_pct']}%)")
        
    calls_list = [r["llm_calls"] for r in repeated_violation_runs]
    red_pct_list = [r["reduction_pct"] for r in repeated_violation_runs]
    min_calls = min(calls_list)
    max_calls = max(calls_list)
    min_red = min(red_pct_list)
    max_red = max(red_pct_list)
    
    print("-" * 80)
    print(f"Calls at interception range: {min_calls} ~ {max_calls} calls (vs {max_budget} budget ceiling)")
    print(f"Exact call avoidance percentage range: {min_red}% ~ {max_red}%")
    
    output_summary = {
        "source_file": str(RESULTS_FILE),
        "total_runs": len(results),
        "intercepted_runs_count": len(repeated_violation_runs),
        "max_call_budget": max_budget,
        "intercepted_calls_range": [min_calls, max_calls],
        "call_reduction_percentage_range": [min_red, max_red],
        "detailed_runs": repeated_violation_runs,
    }
    
    out_json = RESULTS_FILE.parent / "loop_interception_audit.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2, ensure_ascii=False)
    print(f"Saved audit to {out_json}")

if __name__ == "__main__":
    main()
