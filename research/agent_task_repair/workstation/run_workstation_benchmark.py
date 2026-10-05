"""
Master Benchmark Runner for Workstation Multi-Fault Procedural Memory Agent.

Evaluates 4 Groups:
  - Group_B0: Online Agent without cross-task history.
  - Group_B1: Agent with retrieved raw source trajectories.
  - Group_B2: Agent with rich structured facts (transitions, preconditions, invalidation rules).
  - Group_D: Agent with identical B2 facts + compiled conditional procedural repair memories.

Protocol:
  1. Mechanism Tests verification.
  2. Phase A: Run 3 Source Tasks (max 2 attempts each, saving all trajectories).
  3. Causal Intervention Compilation: Test ordering & invalidation hypotheses, compile B2 facts & D memories.
  4. Phase B: 32 Formal Runs (8 Target Tasks × 4 Transfer Classes × 4 Groups, budget: 32 LLM / 40 Tools).
  5. Paired analysis (D vs B2), telemetry aggregation, and auditable JSON output.
"""
import os
import sys
import json
import time
import copy
import gc
import torch
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .workstation_env import WorkstationEnv, StatusCode
from .workstation_tasks import get_source_tasks, get_target_tasks
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    CausalInterventionCompiler,
)
from .workstation_agent import WorkstationAgentRunner
from ..agent.llm_backend import LLMBackend


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "workstation_benchmark_results.json"
MODEL_PATH = "/models/Qwen3-14B-AWQ"


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
        print(f"\n[Phase A] Running Source Task: {tid} ({task_cfg.get('name')})")
        
        task_success = False
        for attempt in range(1, max_attempts + 1):
            print(f"  Attempt {attempt}/{max_attempts}...")
            runner = WorkstationAgentRunner(
                group_id="Group_B0_Online",
                llm_backend=llm_backend,
                max_llm_calls=25,
                max_tool_calls=30,
            )
            ep_res = runner.run_task(task_config=task_cfg)
            ep_res["attempt"] = attempt
            source_episodes.append(ep_res)
            print(f"  Result: Success={ep_res['success']}, Steps={ep_res['step_count']}, LLM_Calls={ep_res['llm_calls']}, Time={ep_res['wall_time_s']}s")
            
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
          f"{len(structured_facts.commutative_subsystems)} Commutative Pairs.")
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
    Execute Phase B 32 formal runs (8 target tasks × 4 groups).
    """
    print("\n=======================================================")
    print(">>> PHASE B: 32 Formal Target Benchmark Runs")
    print("=======================================================")

    groups = [
        ("Group_B0_Online", "B0: Pure Online (No History)"),
        ("Group_B1_Raw_Trajectories", "B1: Raw Trajectory Context"),
        ("Group_B2_Structured_Facts", "B2: Structured Facts Autonomous"),
        ("Group_D_Procedural_Memory", "D: Facts + Procedural Memory"),
    ]

    formal_results: List[Dict[str, Any]] = []

    for t_idx, task_cfg in enumerate(target_tasks):
        tid = task_cfg["task_id"]
        tclass = task_cfg.get("transfer_class")
        print(f"\n[{t_idx+1}/8] Target Task: {tid} | Transfer Class: {tclass}")

        for gid, gname in groups:
            print(f"  --> Running {gname}...")
            runner = WorkstationAgentRunner(
                group_id=gid,
                llm_backend=llm_backend,
                max_llm_calls=32,
                max_tool_calls=40,
                time_limit_s=300.0,
            )

            # Injected history
            src_ep = raw_source_episodes if gid == "Group_B1_Raw_Trajectories" else None
            facts = structured_facts if gid in ["Group_B2_Structured_Facts", "Group_D_Procedural_Memory"] else None
            mems = procedural_memories if gid == "Group_D_Procedural_Memory" else None

            run_res = runner.run_task(
                task_config=task_cfg,
                raw_source_episodes=src_ep,
                structured_facts=facts,
                procedural_memory_store=mems,
            )

            formal_results.append(run_res)
            print(f"      Result: Success={run_res['success']} ({run_res['termination_reason']}), "
                  f"Steps={run_res['step_count']}, LLM_Calls={run_res['llm_calls']}, "
                  f"P_Tok={run_res['total_prompt_tokens']}, G_Tok={run_res['total_generated_tokens']}, "
                  f"Errors={run_res['tool_errors_count']}, Time={run_res['wall_time_s']}s")

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
    Compute per-task table, group aggregates, and paired differences (D vs B2, D vs B1, D vs B0).
    """
    groups = [
        "Group_B0_Online",
        "Group_B1_Raw_Trajectories",
        "Group_B2_Structured_Facts",
        "Group_D_Procedural_Memory",
    ]

    per_task_table = []
    summary_by_group = {
        gid: {
            "total": 0, "successes": 0, "steps": [], "llm_calls": [],
            "prompt_tokens": [], "gen_tokens": [], "time_s": [],
            "tool_errors": [], "plan_deviations": [], "mem_reused": 0, "mem_recovered": 0,
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
            if r.get("memory_reused"):
                summary_by_group[gid]["mem_reused"] += 1
            if r.get("memory_invalidated_recovered"):
                summary_by_group[gid]["mem_recovered"] += 1

            if succ:
                summary_by_group[gid]["successes"] += 1
                summary_by_group[gid]["steps"].append(steps)
                summary_by_group[gid]["llm_calls"].append(llm_c)
                summary_by_group[gid]["prompt_tokens"].append(p_tok)
                summary_by_group[gid]["gen_tokens"].append(g_tok)
                summary_by_group[gid]["time_s"].append(wall_t)

        per_task_table.append(row)

    # Paired comparisons: D vs B2, D vs B1, D vs B0
    paired_analysis = []
    for task_cfg in target_tasks:
        tid = task_cfg["task_id"]
        res_d = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_D_Procedural_Memory"][0]
        res_b2 = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_B2_Structured_Facts"][0]
        res_b1 = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_B1_Raw_Trajectories"][0]
        res_b0 = [r for r in formal_results if r["task_id"] == tid and r["group_id"] == "Group_B0_Online"][0]

        paired_analysis.append({
            "task_id": tid,
            "transfer_class": task_cfg.get("transfer_class"),
            "d_vs_b2": {
                "step_diff_d_minus_b2": res_d["step_count"] - res_b2["step_count"],
                "llm_diff_d_minus_b2": res_d["llm_calls"] - res_b2["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b2["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b2["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b2["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b2["success"],
            },
            "d_vs_b1": {
                "step_diff_d_minus_b1": res_d["step_count"] - res_b1["step_count"],
                "llm_diff_d_minus_b1": res_d["llm_calls"] - res_b1["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b1["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b1["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b1["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b1["success"],
            },
            "d_vs_b0": {
                "step_diff_d_minus_b0": res_d["step_count"] - res_b0["step_count"],
                "llm_diff_d_minus_b0": res_d["llm_calls"] - res_b0["llm_calls"],
                "p_token_diff": res_d["total_prompt_tokens"] - res_b0["total_prompt_tokens"],
                "g_token_diff": res_d["total_generated_tokens"] - res_b0["total_generated_tokens"],
                "time_diff_s": round(res_d["wall_time_s"] - res_b0["wall_time_s"], 2),
                "both_succeeded": res_d["success"] and res_b0["success"],
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
            "memory_reused_count": stats["mem_reused"],
            "memory_invalidated_recovered_count": stats["mem_recovered"],
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
    print("================================================================================")

    # Initialize LLM Backend
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

    # Phase A: Source Experience
    source_episodes, structured_facts, procedural_memories = run_phase_a_sources(
        llm_backend=llm_backend,
        source_tasks=source_tasks,
        max_attempts=2,
    )

    # Phase B: Formal Benchmark
    formal_results = run_phase_b_formal_benchmark(
        llm_backend=llm_backend,
        target_tasks=target_tasks,
        raw_source_episodes=source_episodes,
        structured_facts=structured_facts,
        procedural_memories=procedural_memories,
    )

    # Analysis
    analysis = compute_benchmark_analysis(
        target_tasks=target_tasks,
        formal_results=formal_results,
        source_episodes=source_episodes,
        structured_facts=structured_facts,
        procedural_memories=procedural_memories,
    )

    # Compile final JSON artifact
    full_output = {
        "metadata": {
            "model_path": MODEL_PATH,
            "device": llm_backend.device,
            "quantization": llm_backend.model_metadata.get("quantization"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_runs": len(source_episodes) + len(formal_results),
            "source_runs_count": len(source_episodes),
            "formal_runs_count": len(formal_results),
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

    # Print Summary Tables
    print("\n" + "=" * 115)
    print(" PHASE B MASTER COMPARISON TABLE (8 Target Tasks × 4 Transfer Classes × 4 Groups)")
    print("=" * 115)
    print(f"{'Task ID':<26} | {'Class':<12} | {'Grp B0 (Stp/LLM)':<16} | {'Grp B1 (Stp/LLM)':<16} | {'Grp B2 (Stp/LLM)':<16} | {'Grp D (Stp/LLM)':<16}")
    print("-" * 115)
    for r in analysis["per_task_comparison"]:
        b0_str = f"{r['Group_B0_Online_success']} ({r['Group_B0_Online_steps']}/{r['Group_B0_Online_llm_calls']})"
        b1_str = f"{r['Group_B1_Raw_Trajectories_success']} ({r['Group_B1_Raw_Trajectories_steps']}/{r['Group_B1_Raw_Trajectories_llm_calls']})"
        b2_str = f"{r['Group_B2_Structured_Facts_success']} ({r['Group_B2_Structured_Facts_steps']}/{r['Group_B2_Structured_Facts_llm_calls']})"
        d_str = f"{r['Group_D_Procedural_Memory_success']} ({r['Group_D_Procedural_Memory_steps']}/{r['Group_D_Procedural_Memory_llm_calls']})"
        print(f"{r['task_id']:<26} | {r['transfer_class'][:12]:<12} | {b0_str:<16} | {b1_str:<16} | {b2_str:<16} | {d_str:<16}")
    print("-" * 115)

    print("\nGROUP AGGREGATES SUMMARY:")
    for gid, agg in analysis["group_aggregates"].items():
        print(f"  [{gid}]: Success={agg['success_rate']}, AvgSteps={agg['avg_steps_successful']}, AvgLLM={agg['avg_llm_calls_successful']}, AvgPromptTok={agg['avg_prompt_tokens_successful']}, ToolErrors={agg['total_tool_errors']}")


if __name__ == "__main__":
    main()
