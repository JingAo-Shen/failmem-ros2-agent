"""
Model Capability Screening Runner (FailMem Stage 2).
Evaluates foundational model capability across 24 standalone screening tasks (no cross-task memory).
Evaluates 3 Model Configurations:
  1. Config_Ref_7B: Qwen2.5-Coder-7B-Instruct (FP16, Direct Structured JSON)
  2. Config_14B_Direct: Qwen3-14B-AWQ (AWQ 4-bit, Direct Structured JSON, enable_thinking=False)
  3. Config_14B_Thinking: Qwen3-14B-AWQ (AWQ 4-bit, Official Thinking Mode, enable_thinking=True)

Evaluates Against Engineering Admission Criteria:
  1. Basic Delivery & Tool Calling: 100% completion (4/4 on basic delivery tasks)
  2. First-Call Action Schema Validity Rate: >= 95%
  3. Total Task Success Rate: >= 80% (>= 20/24)
  4. Peak VRAM < 20GB and continuous local execution latency manageable on single RTX 2080 Ti

If no candidate meets all criteria, admission is explicitly marked as failed ("候选模型准入未通过"),
and selected_configuration is set to null in the official payload.
"""
import sys
import os
import json
import time
import copy
import gc
import torch
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..agent.planner import AgentPlanner, MAP_ADJACENCY
from ..env.task_env import DeliveryTaskEnv
from ..env.screening_tasks_24 import get_24_screening_tasks, verify_screening_task_feasibility
from ..memory.subgoal_memory_adapter import SubgoalMemoryAdapter


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "model_screening_results.json"


def get_model_commit_info(model_path: str) -> str:
    """Extracts git commit hash or config hash for reproducible logging."""
    commit_file = Path(model_path) / ".git" / "HEAD"
    if commit_file.exists():
        try:
            head_content = commit_file.read_text().strip()
            if head_content.startswith("ref:"):
                ref_path = Path(model_path) / ".git" / head_content.split(" ")[1]
                if ref_path.exists():
                    return ref_path.read_text().strip()[:10]
            return head_content[:10]
        except Exception:
            pass
    # Check config.json mtime or hash
    cfg_file = Path(model_path) / "config.json"
    if cfg_file.exists():
        return f"rev_mtime_{int(cfg_file.stat().st_mtime)}"
    return "unknown_revision"


def run_model_screening():
    print("=" * 80)
    print("STARTING 24-TASK MODEL CAPABILITY SCREENING BENCHMARK (FAILMEM STAGE 2)")
    print("Screening Candidate Models for Single-GPU Robotic Planning Admission")
    print("=" * 80)

    # 1. First verify feasibility of all 24 tasks
    tasks = get_24_screening_tasks()
    print(f"\n[Verification] Verifying oracle feasibility of {len(tasks)} screening tasks...")
    for t in tasks:
        ok, msg, _ = verify_screening_task_feasibility(t)
        if not ok:
            raise RuntimeError(f"Task {t['task_id']} failed feasibility check: {msg}")
    print("[Verification] All 24 screening tasks 100% verified solvable by oracle.\n")

    configs = [
        {
            "id": "Config_Ref_7B",
            "name": "Qwen2.5-Coder-7B-Instruct (Reference FP16, Direct)",
            "model_path": "/models/Qwen2.5-Coder-7B-Instruct",
            "quantization": "fp16",
            "thinking": None,
        },
        {
            "id": "Config_14B_Direct",
            "name": "Qwen3-14B-AWQ (AWQ 4-bit, Direct Structured)",
            "model_path": "/models/Qwen3-14B-AWQ",
            "quantization": "awq",
            "thinking": False,
        },
        {
            "id": "Config_14B_Thinking",
            "name": "Qwen3-14B-AWQ (AWQ 4-bit, Native Thinking Mode)",
            "model_path": "/models/Qwen3-14B-AWQ",
            "quantization": "awq",
            "thinking": True,
        },
    ]

    all_config_results = {}
    t_start_total = time.time()

    for cfg in configs:
        cfg_id = cfg["id"]
        cfg_name = cfg["name"]
        model_path = cfg["model_path"]
        quantization = cfg["quantization"]
        thinking_mode = cfg["thinking"]

        print("\n" + "=" * 78)
        print(f">>> EVALUATING: {cfg_name}")
        print(f"    Path: {model_path} | Quant: {quantization} | Thinking: {thinking_mode}")
        print("=" * 78)

        if not os.path.exists(model_path):
            print(f"[ERROR] Model path '{model_path}' not found on disk. Skipping {cfg_id}.")
            continue

        commit_hash = get_model_commit_info(model_path)

        # Clear GPU memory
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()

        try:
            llm = LLMBackend(
                model_path=model_path,
                device="cuda",
                enable_thinking=thinking_mode,
                quantization_format=quantization,
                max_new_tokens=512 if thinking_mode else 256,
                temperature=0.0,
            )
        except Exception as e:
            print(f"[ERROR] Failed to load model for {cfg_id}: {e}")
            all_config_results[cfg_id] = {
                "config_id": cfg_id,
                "config_name": cfg_name,
                "model_path": model_path,
                "commit_hash": commit_hash,
                "load_error": str(e),
                "meets_admission_criteria": False,
            }
            continue

        t_cfg_start = time.time()
        task_runs = []
        total_first_calls = 0
        valid_first_calls = 0
        total_retry_calls = 0
        valid_retry_calls = 0

        for t_idx, task in enumerate(tasks, start=1):
            tid = task["task_id"]
            cat = task["category"]
            t_task_start = time.time()

            adapter = SubgoalMemoryAdapter(injection_mode="none", store_mode="F", adjacency_map=MAP_ADJACENCY)
            adapter.on_task_start(tid, 0)

            runner = AgentRunner(
                llm_backend=llm,
                memory_adapter=adapter,
                max_tool_calls=25,
                max_llm_calls=20,
                run_id=f"screen_{cfg_id}_{tid}",
                use_task_skeleton=True,
            )

            task_spec = {
                "task_id": tid,
                "instruction": task["instruction"],
                "env_config": copy.deepcopy(task["env_config"]),
            }

            res = runner.run_task(task_spec, task_index=0, seq_id="screen_bench")
            t_task_wall = time.time() - t_task_start

            # Calculate first-call vs revised schema validity
            for trace in res.get("llm_traces", []):
                is_retry = trace.get("retry_used", False)
                parse_ok = trace.get("parse_ok", not trace.get("parse_error", False))
                if not is_retry:
                    total_first_calls += 1
                    if parse_ok:
                        valid_first_calls += 1
                else:
                    total_retry_calls += 1
                    if parse_ok:
                        valid_retry_calls += 1

            success = bool(res.get("success", False))
            step_count = len(res.get("step_history", []))
            batt = res.get("battery_consumed", 0)

            task_runs.append({
                "task_id": tid,
                "category": cat,
                "success": success,
                "steps": step_count,
                "battery_consumed": batt,
                "sim_time_s": res.get("sim_time_s", 0.0),
                "llm_calls": res.get("llm_calls", 0),
                "wall_time_s": round(t_task_wall, 2),
                "constraint_violations": res.get("constraint_violations", []),
                "step_history": res.get("step_history", []),
            })

            print(f"  [{t_idx:2d}/24] {tid:42s} | Success={str(success):5s} | Steps={step_count:2d} | Batt={batt:2d}% | Wall={t_task_wall:4.1f}s")

        t_cfg_wall = time.time() - t_cfg_start
        peak_vram_mb = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2) if torch.cuda.is_available() else 0.0

        # Aggregate metrics
        n_tasks = len(task_runs)
        n_success = sum(1 for r in task_runs if r["success"])
        success_rate = round(n_success / max(1, n_tasks), 4)

        # Category breakdowns
        cat_summaries = {}
        for c in sorted(set(r["category"] for r in task_runs)):
            c_runs = [r for r in task_runs if r["category"] == c]
            c_succ = sum(1 for r in c_runs if r["success"])
            cat_summaries[c] = {
                "total": len(c_runs),
                "success": c_succ,
                "success_rate": round(c_succ / len(c_runs), 4),
            }

        first_call_schema_rate = round(valid_first_calls / max(1, total_first_calls), 4)
        total_calls_all = total_first_calls + total_retry_calls
        total_valid_all = valid_first_calls + valid_retry_calls
        revised_schema_rate = round(total_valid_all / max(1, total_calls_all), 4)
        basic_delivery_rate = cat_summaries.get("1_basic_delivery", {}).get("success_rate", 0.0)

        stats = llm.get_aggregate_stats()

        meets_admission = (
            basic_delivery_rate >= 1.0 and
            first_call_schema_rate >= 0.95 and
            success_rate >= 0.80 and
            peak_vram_mb < 20000
        )

        cfg_summary = {
            "config_id": cfg_id,
            "config_name": cfg_name,
            "model_id": model_path,
            "revision_commit": commit_hash,
            "quantization_format": quantization,
            "enable_thinking": thinking_mode,
            "total_tasks": n_tasks,
            "success_count": n_success,
            "success_rate": success_rate,
            "first_call_schema_validity_rate": first_call_schema_rate,
            "revised_schema_validity_rate": revised_schema_rate,
            "basic_delivery_completion_rate": basic_delivery_rate,
            "meets_admission_criteria": meets_admission,
            "peak_vram_mb": peak_vram_mb,
            "avg_step_latency_s": stats.get("avg_latency_s", 0.0),
            "avg_tokens_per_sec": stats.get("avg_tokens_per_sec", 0.0),
            "total_prompt_tokens": stats.get("total_prompt_tokens", 0),
            "total_generated_tokens": stats.get("total_generated_tokens", 0),
            "total_wall_time_s": round(t_cfg_wall, 2),
            "category_breakdown": cat_summaries,
            "task_runs": task_runs,
        }
        all_config_results[cfg_id] = cfg_summary

        print(f"\n--- Summary for {cfg_id} ---")
        print(f"  Overall Success Rate:        {n_success}/{n_tasks} ({success_rate*100:.1f}%) [Admission Target >= 80%]")
        print(f"  Basic Delivery Rate:         {basic_delivery_rate*100:.1f}% [Admission Target = 100%]")
        print(f"  First-Call Schema Validity:  {first_call_schema_rate*100:.1f}% [Admission Target >= 95%]")
        print(f"  Revised Schema Validity:     {revised_schema_rate*100:.1f}%")
        print(f"  Peak VRAM:                   {peak_vram_mb} MB")
        print(f"  Throughput:                  {stats.get('avg_tokens_per_sec', 0.0)} tokens/s")
        print(f"  Meets Admission Criteria:    {meets_admission}")

        # Free LLM instance
        del llm
        del runner
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # Determine recommended locked configuration
    admitted_configs = [k for k, v in all_config_results.items() if v.get("meets_admission_criteria", False)]
    best_overall_id = max(
        all_config_results.keys(),
        key=lambda k: (
            all_config_results[k].get("success_rate", 0),
            all_config_results[k].get("first_call_schema_validity_rate", 0)
        )
    )

    if admitted_configs:
        selected_config_id = max(
            admitted_configs,
            key=lambda k: (
                all_config_results[k].get("success_rate", 0),
                all_config_results[k].get("first_call_schema_validity_rate", 0)
            )
        )
        admission_passed = True
        rationale = f"Configuration '{selected_config_id}' passed all 4 admission criteria with success_rate={all_config_results[selected_config_id]['success_rate']*100:.1f}%."
    else:
        selected_config_id = None
        admission_passed = False
        rationale = (
            f"候选模型准入未通过 (Candidate model admission not passed). "
            f"None of the candidate configurations met all admission thresholds (100% basic delivery, >=95% first-call schema validity, >=80% success rate). "
            f"Relative best configuration is '{best_overall_id}' (Success: {all_config_results[best_overall_id].get('success_rate', 0)*100:.1f}%), "
            f"which is used as the baseline for development diagnosis while recording non-admission status."
        )

    payload = {
        "benchmark": "24_task_model_screening",
        "total_wall_time_s": round(time.time() - t_start_total, 2),
        "admission_passed": admission_passed,
        "selected_configuration": selected_config_id,
        "best_available_configuration": best_overall_id,
        "selection_rationale": rationale,
        "admission_rules": {
            "rule_1_basic_delivery_100pct": "Must achieve 100% completion on 4 basic delivery tasks",
            "rule_2_first_call_schema_ge_95pct": "Must achieve >= 95.0% schema validity on initial generation",
            "rule_3_total_success_ge_80pct": "Must achieve >= 80.0% overall task completion on 24 tasks",
            "rule_4_vram_and_latency_continuous": "Must fit comfortably within 22GB single GPU (<20GB peak)",
        },
        "config_results": all_config_results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("\n" + "=" * 80)
    print("MODEL SCREENING COMPLETED")
    print(f"Admission Passed: {admission_passed}")
    print(f"Selected Config:  {selected_config_id}")
    print(f"Relative Best:    {best_overall_id}")
    print(f"Rationale:        {rationale}")
    print(f"Results saved to: {OUTPUT_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    run_model_screening()
