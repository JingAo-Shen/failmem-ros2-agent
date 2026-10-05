"""
Master Benchmark Runner for Workstation Multi-Fault Procedural Memory Agent.

Evaluates 5 Fair Comparison Groups:
  1. Group_B2_step: Structured facts + single-step LLM planning.
  2. Group_B2_plan: Structured facts + multi-step LLM planning via CommonLocalPlanExecutor.
  3. Group_B1_plan: Full raw source trajectories + multi-step LLM planning via CommonLocalPlanExecutor.
  4. Group_Replay: Naive trajectory replay matching observed fault via CommonLocalPlanExecutor.
  5. Group_D_Procedural_Memory: Structured facts + conditional procedural memory via CommonLocalPlanExecutor.

Protocol:
  1. Pre-flight Gate Mechanism Tests (6/6 gates must pass).
  2. Phase A: Run 3 Source Tasks (max 2 attempts each, saving all trajectories).
  3. Causal Intervention Compilation: Active intervention verification of candidate dependencies.
  4. Phase B: 40 Formal Runs (8 Target Tasks × 5 Groups, budget: 32 LLM / 40 Tools / 300s timeout).
  5. Paired attribution analysis (D vs B2_plan, D vs Replay, D vs B2_step, D vs B1_plan), telemetry aggregation, and auditable JSON output.
"""
import os
import sys
import json
import time
import copy
import gc
import unittest
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import torch

from .workstation_env import WorkstationEnv, StatusCode
from .workstation_tasks import get_source_tasks, get_target_tasks
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    CausalInterventionCompiler,
)
from .workstation_agent import WorkstationAgentRunner
from .test_mechanisms import TestWorkstationMechanisms
from ..agent.llm_backend import LLMBackend


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "workstation_benchmark_results.json"
MODEL_PATH = "/models/Qwen3-14B-AWQ"


def run_preflight_gate_tests() -> bool:
    """Run all strict mechanism gate verification tests before benchmark execution."""
    print("\n=======================================================")
    print(">>> PRE-FLIGHT GATE VERIFICATION: 6 Strict Mechanism Tests")
    print("=======================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestWorkstationMechanisms)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        print(f"\n[FATAL] Pre-flight gate tests FAILED ({len(result.failures)} failures, {len(result.errors)} errors)!")
        return False
    print(f"\n[PASS] All {result.testsRun} Pre-flight Mechanism Gates PASSED.")
    return True


def run_phase_a_sources(
    llm_backend: LLMBackend,
    source_tasks: List[Dict[str, Any]],
    max_attempts: int = 2,
) -> Tuple[List[Dict[str, Any]], StructuredFactStore, ProceduralMemoryStore]:
    """
    Execute Phase A experience acquisition on 3 source tasks.
    Extract real trajectories and compile structured facts and procedural memories.
    """
    print("\n=======================================================")
    print(">>> PHASE A: Source Tasks Experience Acquisition & Causal Compilation")
    print("=======================================================")

    source_episodes: List[Dict[str, Any]] = []

    for task_cfg in source_tasks:
        tid = task_cfg["task_id"]
        print(f"\n[Phase A] Running Source Task: {tid} ({task_cfg.get("name")})")
        
        task_success = False
        for attempt in range(1, max_attempts + 1):
            print(f"  Attempt {attempt}/{max_attempts}...")
            runner = WorkstationAgentRunner(
                group_id="Group_B2_step",
                llm_backend=llm_backend,
                max_llm_calls=25,
                max_tool_calls=30,
            )
            ep_res = runner.run_task(task_config=task_cfg)
            ep_res["attempt"] = attempt
            source_episodes.append(ep_res)
            print(f"  Result: Success={ep_res["success"]}, Steps={ep_res["step_count"]}, LLM_Calls={ep_res["llm_calls"]}, Time={ep_res["wall_time_s"]}s")
            
            if ep_res["success"]:
                task_success = True
                break

    # Run Causal Intervention Compiler on successful source episodes
    print("\n[Phase A] Running Causal Intervention Compiler in source environment...")
    compiler = CausalInterventionCompiler(max_intervention_budget=30)
    structured_facts, procedural_memories = compiler.compile_from_source_episodes(
        source_episodes=source_episodes,
        source_task_configs=source_tasks,
    )

    print(f"[Phase A] Discovered {len(structured_facts.action_preconditions)} Action Preconditions, "
          f"{len(structured_facts.invalidation_rules)} Invalidation Rules, "
          f"{len(structured_facts.causal_order_constraints)} Causal Order Constraints, "
          f"{len(structured_facts.commutative_subsystems)} Commutative Pairs, "
          f"{len(structured_facts.verified_transitions)} Verified Transitions.")
    print(f"[Phase A] Compiled {len(procedural_memories.memories)} Validated Procedural Memory Templates for Group D.")

    return source_episodes, structured_facts, procedural_memories


def run_phase_b_formal_benchmark(
    llm_backend: LLMBackend,
    target_tasks: List[Dict[str, Any]],
    raw_source_episodes: List[Dict[str, Any]],
    structured_facts: StructuredFactStore,
    procedural_memories: ProceduralMemoryStore,
) -> List[Dict[str, Any]]:
    """
    Execute Phase B 40 formal runs (8 target tasks × 5 groups).
    Saves incremental results to disk after every single run.
    """
    print("\n=======================================================")
    print(">>> PHASE B: 40 Formal Target Benchmark Runs (5 Groups × 8 Tasks)")
    print("=======================================================")

    groups = [
        ("Group_B2_step", "B2-step: Structured Facts Single-Step"),
        ("Group_B2_plan", "B2-plan: Structured Facts Multi-Step Plan"),
        ("Group_B1_plan", "B1-plan: Raw Trajectory Multi-Step Plan"),
        ("Group_Replay", "Replay: Naive Trajectory Segment Replay"),
        ("Group_D_Procedural_Memory", "D: Facts + Conditional Procedural Memory"),
    ]

    formal_results: List[Dict[str, Any]] = []

    total_runs = len(target_tasks) * len(groups)
    current_run = 0

    for t_idx, task_cfg in enumerate(target_tasks):
        tid = task_cfg["task_id"]
        tclass = task_cfg.get("transfer_class")
        print(f"\n[{t_idx+1}/8] Target Task: {tid} | Transfer Class: {tclass}")

        for gid, gname in groups:
            current_run += 1
            print(f"  [{current_run}/{total_runs}] --> Running {gname}...")
            runner = WorkstationAgentRunner(
                group_id=gid,
                llm_backend=llm_backend,
                max_llm_calls=32,
                max_tool_calls=40,
                time_limit_s=300.0,
            )

            # Injected context based on group requirements
            src_ep = raw_source_episodes if gid in ["Group_B1_plan", "Group_Replay"] else None
            facts = structured_facts if gid in ["Group_B2_step", "Group_B2_plan", "Group_D_Procedural_Memory"] else None
            mems = procedural_memories if gid == "Group_D_Procedural_Memory" else None

            run_res = runner.run_task(
                task_config=task_cfg,
                raw_source_episodes=src_ep,
                structured_facts=facts,
                procedural_memory_store=mems,
            )

            formal_results.append(run_res)
            print(f"      Result: Success={run_res["success"]} ({run_res["termination_reason"]}), "
                  f"Steps={run_res["step_count"]}, LLM_Calls={run_res["llm_calls"]}, "
                  f"P_Tok={run_res["total_prompt_tokens"]}, G_Tok={run_res["total_generated_tokens"]}, "
                  f"Errors={run_res["tool_errors_count"]}, Time={run_res["wall_time_s"]}s")

            # Incremental save
            try:
                temp_output = {
                    "completed_formal_runs": len(formal_results),
                    "total_expected_runs": total_runs,
                    "phase_b_partial_results": formal_results,
                }
                with open(RESULTS_DIR / "workstation_benchmark_partial.json", "w", encoding="utf-8") as pf:
                    json.dump(temp_output, pf, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"      [Warning] Partial save failed: {e}")

            # GPU memory sanitation
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    return formal_results


def compute_benchmark_analysis(
    target_tasks: List[Dict[str, Any]],
    formal_results: List[Dict[str, Any]],
    source_episodes: List[Dict[str, Any]],
    structured_facts: StructuredFactStore,
    procedural_memories: ProceduralMemoryStore,
) -> Dict[str, Any]:
    """
    Compute per-task table, group aggregates, and paired attribution differences.
    """
    groups = [
        "Group_B2_step",
        "Group_B2_plan",
        "Group_B1_plan",
        "Group_Replay",
        "Group_D_Procedural_Memory",
    ]

    per_task_table = []
    summary_by_group = {
        gid: {
            "total": 0, "successes": 0, "steps": [], "llm_calls": [],
            "prompt_tokens": [], "gen_tokens": [], "time_s": [],
            "tool_errors": [], "plan_deviations": [],
            "memory_selected": 0, "memory_executed": 0, "memory_verified": 0,
            "memory_invalidated": 0, "recovery_attempted": 0, "recovery_succeeded": 0,
        }
        for gid in groups
    }

    for task_cfg in target_tasks:
        tid = task_cfg["task_id"]
        row = {
            "task_id": tid,
            "name": task_cfg["name"],
            "transfer_class": task_cfg.get("transfer_class"),
        }

        for gid in groups:
            res_matches = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == gid]
            if not res_matches:
                continue
            r = res_matches[0]
            succ = r["success"]
            steps = r["step_count"]
            llm_c = r["llm_calls"]
            p_tok = r["total_prompt_tokens"]
            g_tok = r["total_generated_tokens"]
            wall_t = r["wall_time_s"]
            errs = r["tool_errors_count"]

            row[f"{gid}_success"] = succ
            row[f"{gid}_steps"] = steps
            row[f"{gid}_llm_calls"] = llm_c
            row[f"{gid}_p_tokens"] = p_tok
            row[f"{gid}_g_tokens"] = g_tok
            row[f"{gid}_time_s"] = wall_t
            row[f"{gid}_tool_errors"] = errs

            summary_by_group[gid]["total"] += 1
            summary_by_group[gid]["tool_errors"].append(errs)
            summary_by_group[gid]["memory_selected"] += r.get("memory_selected_count", 0)
            summary_by_group[gid]["memory_executed"] += r.get("memory_action_executed_count", 0)
            summary_by_group[gid]["memory_verified"] += r.get("memory_postcondition_verified_count", 0)
            summary_by_group[gid]["memory_invalidated"] += r.get("memory_invalidated_count", 0)
            summary_by_group[gid]["recovery_attempted"] += r.get("online_recovery_attempted_count", 0)
            if r.get("online_recovery_succeeded"):
                summary_by_group[gid]["recovery_succeeded"] += 1

            if succ:
                summary_by_group[gid]["successes"] += 1
                summary_by_group[gid]["steps"].append(steps)
                summary_by_group[gid]["llm_calls"].append(llm_c)
                summary_by_group[gid]["prompt_tokens"].append(p_tok)
                summary_by_group[gid]["gen_tokens"].append(g_tok)
                summary_by_group[gid]["time_s"].append(wall_t)

        per_task_table.append(row)

    # Paired comparisons: D vs B2_plan, D vs Replay, D vs B2_step, D vs B1_plan
    paired_analysis = []
    for task_cfg in target_tasks:
        tid = task_cfg["task_id"]
        res_d = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_D_Procedural_Memory"][0]
        res_b2_plan = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_B2_plan"][0]
        res_replay = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_Replay"][0]
        res_b2_step = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_B2_step"][0]
        res_b1_plan = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_B1_plan"][0]

        paired_analysis.append({
            "task_id": tid,
            "transfer_class": task_cfg.get("transfer_class"),
            "d_vs_b2_plan": {
                "step_diff_d_minus_b2_plan": res_d["step_count"] - res_b2_plan["step_count"],
                "llm_diff_d_minus_b2_plan": res_d["llm_calls"] - res_b2_plan["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b2_plan["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b2_plan["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b2_plan["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b2_plan["success"],
            },
            "d_vs_replay": {
                "step_diff_d_minus_replay": res_d["step_count"] - res_replay["step_count"],
                "llm_diff_d_minus_replay": res_d["llm_calls"] - res_replay["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_replay["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_replay["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_replay["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_replay["success"],
            },
            "d_vs_b2_step": {
                "step_diff_d_minus_b2_step": res_d["step_count"] - res_b2_step["step_count"],
                "llm_diff_d_minus_b2_step": res_d["llm_calls"] - res_b2_step["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b2_step["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b2_step["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b2_step["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b2_step["success"],
            },
            "d_vs_b1_plan": {
                "step_diff_d_minus_b1_plan": res_d["step_count"] - res_b1_plan["step_count"],
                "llm_diff_d_minus_b1_plan": res_d["llm_calls"] - res_b1_plan["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b1_plan["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b1_plan["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b1_plan["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b1_plan["success"],
            },
        })

    group_aggregates = {}
    for gid, stats in summary_by_group.items():
        tot = stats["total"]
        succ_cnt = stats["successes"]
        group_aggregates[gid] = {
            "success_rate": f"{succ_cnt}/{tot} ({succ_cnt/tot*100:.1f}%)" if tot > 0 else "0%",
            "success_count": succ_cnt,
            "total_runs": tot,
            "avg_steps_successful": round(sum(stats["steps"])/len(stats["steps"]), 2) if stats["steps"] else 0,
            "avg_llm_calls_successful": round(sum(stats["llm_calls"])/len(stats["llm_calls"]), 2) if stats["llm_calls"] else 0,
            "avg_prompt_tokens_successful": round(sum(stats["prompt_tokens"])/len(stats["prompt_tokens"]), 1) if stats["prompt_tokens"] else 0,
            "avg_gen_tokens_successful": round(sum(stats["gen_tokens"])/len(stats["gen_tokens"]), 1) if stats["gen_tokens"] else 0,
            "avg_time_s_successful": round(sum(stats["time_s"])/len(stats["time_s"]), 2) if stats["time_s"] else 0,
            "total_tool_errors": sum(stats["tool_errors"]),
            "memory_selected_count": stats["memory_selected"],
            "memory_action_executed_count": stats["memory_executed"],
            "memory_postcondition_verified_count": stats["memory_verified"],
            "memory_invalidated_count": stats["memory_invalidated"],
            "online_recovery_attempted_count": stats["recovery_attempted"],
            "online_recovery_succeeded_count": stats["recovery_succeeded"],
        }

    return {
        "per_task_comparison": per_task_table,
        "paired_analysis": paired_analysis,
        "group_aggregates": group_aggregates,
    }


def main():
    print("================================================================================")
    print(" FailMem Stage 3: Workstation Multi-Fault Procedural Memory Benchmark Runner")
    print(f" Base Model: {MODEL_PATH} (Qwen3-14B-AWQ Direct, GPU T=0.0)")
    print(" 5 Groups: B2_step, B2_plan, B1_plan, Replay, D (40 Formal Runs)")
    print("================================================================================")

    # Step 1: Pre-flight Gate Verification
    gate_passed = run_preflight_gate_tests()
    if not gate_passed:
        print("[ABORT] Pre-flight gate tests did not pass. Terminating benchmark.")
        sys.exit(1)

    # Step 2: Initialize LLM Backend
    llm_backend = LLMBackend(
        model_path=MODEL_PATH,
        device="cuda" if torch.cuda.is_available() else "cpu",
        torch_dtype="float16",
        max_new_tokens=256,
        temperature=0.0,
        enable_thinking=False,
        quantization_format="awq",
        allow_fallback=False,
    )

    source_tasks = get_source_tasks()
    target_tasks = get_target_tasks()

    # Step 3: Phase A: Source Experience & Causal Compilation
    source_episodes, structured_facts, procedural_memories = run_phase_a_sources(
        llm_backend=llm_backend,
        source_tasks=source_tasks,
        max_attempts=2,
    )

    # Step 4: Phase B: Formal Benchmark (40 Runs)
    formal_results = run_phase_b_formal_benchmark(
        llm_backend=llm_backend,
        target_tasks=target_tasks,
        raw_source_episodes=source_episodes,
        structured_facts=structured_facts,
        procedural_memories=procedural_memories,
    )

    # Step 5: Paired Attribution Analysis
    analysis = compute_benchmark_analysis(
        target_tasks=target_tasks,
        formal_results=formal_results,
        source_episodes=source_episodes,
        structured_facts=structured_facts,
        procedural_memories=procedural_memories,
    )

    # Step 6: Compile Final JSON Artifact
    full_output = {
        "metadata": {
            "model_path": MODEL_PATH,
            "device": llm_backend.device,
            "quantization": llm_backend.model_metadata.get("quantization"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_runs": len(source_episodes) + len(formal_results),
            "source_runs_count": len(source_episodes),
            "formal_runs_count": len(formal_results),
            "groups_evaluated": [
                "Group_B2_step", "Group_B2_plan", "Group_B1_plan", "Group_Replay", "Group_D_Procedural_Memory"
            ],
        },
        "phase_a_source_episodes": source_episodes,
        "discovered_structured_facts": structured_facts.to_dict(),
        "compiled_procedural_memories": procedural_memories.to_dict(),
        "phase_b_formal_results": formal_results,
        "comparative_summary": analysis,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2, ensure_ascii=False)

    print(f"\n[Artifact Saved] Benchmark results written to: {OUTPUT_FILE}")

    # Step 7: Print Summary Tables
    print("\n" + "=" * 135)
    print(" PHASE B MASTER COMPARISON TABLE (8 Target Tasks × 4 Transfer Classes × 5 Evaluation Groups)")
    print("=" * 135)
    print(f"{"Task ID":<26} | {"Class":<12} | {"B2-step":<12} | {"B2-plan":<12} | {"B1-plan":<12} | {"Replay":<12} | {"Group D":<12}")
    print("-" * 135)
    for r in analysis["per_task_comparison"]:
        b2_s = f"{"✓" if r["Group_B2_step_success"] else "✗"} ({r["Group_B2_step_steps"]}s/{r["Group_B2_step_llm_calls"]}l)"
        b2_p = f"{"✓" if r["Group_B2_plan_success"] else "✗"} ({r["Group_B2_plan_steps"]}s/{r["Group_B2_plan_llm_calls"]}l)"
        b1_p = f"{"✓" if r["Group_B1_plan_success"] else "✗"} ({r["Group_B1_plan_steps"]}s/{r["Group_B1_plan_llm_calls"]}l)"
        rep = f"{"✓" if r["Group_Replay_success"] else "✗"} ({r["Group_Replay_steps"]}s/{r["Group_Replay_llm_calls"]}l)"
        grp_d = f"{"✓" if r["Group_D_Procedural_Memory_success"] else "✗"} ({r["Group_D_Procedural_Memory_steps"]}s/{r["Group_D_Procedural_Memory_llm_calls"]}l)"
        print(f"{r["task_id"]:<26} | {r["transfer_class"][:12]:<12} | {b2_s:<12} | {b2_p:<12} | {b1_p:<12} | {rep:<12} | {grp_d:<12}")
    print("-" * 135)

    print("\nGROUP AGGREGATES SUMMARY:")
    for gid, agg in analysis["group_aggregates"].items():
        print(f"  [{gid}]: Success={agg["success_rate"]}, AvgSteps={agg["avg_steps_successful"]}, "
              f"AvgLLM={agg["avg_llm_calls_successful"]}, AvgPromptTok={agg["avg_prompt_tokens_successful"]}, "
              f"ToolErrors={agg["total_tool_errors"]}, MemSelected={agg["memory_selected_count"]}, "
              f"MemInvalidated={agg["memory_invalidated_count"]}, RecoverySucc={agg["online_recovery_succeeded_count"]}")


if __name__ == "__main__":
    main()
