"""
Diagnostic 6-Run Benchmark for Workstation Multi-Fault Diagnostic & Recovery Agent.

Targeted Investigation on the 2 previously failed tasks:
  1. target_B2_power_and_sensor (Class B combination)
  2. target_C2_sensor_power_order (Class C condition changed)

Groups evaluated:
  - Group_B2_plan: Structured facts + multi-step planning (Unified Execution Engine)
  - Group_Replay: Raw trajectory replay (Unified Execution Engine)
  - Group_D_Procedural_Memory: Structured facts + verified procedural memory (Unified Execution Engine)

Configuration:
  - Base Model: Qwen/Qwen3-14B-AWQ Direct (RTX 2080 Ti, T=0.0)
  - Budget: 32 LLM calls, 40 Tool calls
  - Time limit: 600.0s (sufficient margin to prevent early timeout truncation)
  - Unified CommonLocalPlanExecutor with active ConstraintEvent prompt feedback and real postcondition verification.
"""
import os
import sys
import json
import time
import copy
import gc
from pathlib import Path
from typing import Dict, Any, List, Optional

import torch

from .workstation_env import WorkstationEnv, StatusCode
from .workstation_tasks import get_target_tasks
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
)
from .workstation_agent import WorkstationAgentRunner
from ..agent.llm_backend import LLMBackend


RESULTS_DIR = Path("/code/failmem-ros2-agent/research/agent_task_repair/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
DIAGNOSTIC_OUTPUT_FILE = RESULTS_DIR / "diagnostic_6runs_results.json"
SOURCE_DATA_FILE = RESULTS_DIR / "workstation_benchmark_results.json"
MODEL_PATH = "/models/Qwen3-14B-AWQ"


def run_diagnostics():
    print("================================================================================")
    print(" FailMem Stage 3: Targeted 6-Run Diagnostic Benchmark")
    print(f" Model: {MODEL_PATH} (Qwen3-14B-AWQ Direct, GPU T=0.0)")
    print(" Tasks: target_B2_power_and_sensor, target_C2_sensor_power_order")
    print(" Groups: B2_plan, Group_Replay, Group_D_Procedural_Memory (6 Total Runs)")
    print("================================================================================")

    # 1. Load existing Phase A source experience
    if not SOURCE_DATA_FILE.exists():
        raise FileNotFoundError(f"Source benchmark file not found: {SOURCE_DATA_FILE}")

    with open(SOURCE_DATA_FILE, "r", encoding="utf-8") as f:
        src_data = json.load(f)

    raw_source_episodes = src_data.get("phase_a_source_episodes", [])
    facts_dict = src_data.get("discovered_structured_facts", {})
    mems_dict = src_data.get("compiled_procedural_memories", {})

    fact_store = StructuredFactStore()
    fact_store.verified_transitions = facts_dict.get("verified_transitions", [])
    fact_store.action_preconditions = facts_dict.get("action_preconditions", {})
    fact_store.invalidation_rules = facts_dict.get("invalidation_rules", [])
    fact_store.causal_order_constraints = facts_dict.get("causal_order_constraints", [])
    fact_store.commutative_subsystems = facts_dict.get("commutative_subsystems", [])

    procedural_memories = ProceduralMemoryStore()
    for mid, mdict in mems_dict.items():
        procedural_memories.add_memory(ProceduralMemoryItem.from_dict(mdict))

    print(f"[Init] Loaded {len(raw_source_episodes)} Phase A Source Episodes.")
    print(f"[Init] Loaded {len(fact_store.verified_transitions)} Verified Transitions, {len(fact_store.action_preconditions)} Preconditions.")
    print(f"[Init] Loaded {len(procedural_memories.memories)} Validated Procedural Memories.")

    # 2. Initialize LLM Backend
    llm_backend = LLMBackend(
        model_path=MODEL_PATH,
        device="cuda" if torch.cuda.is_available() else "cpu",
        torch_dtype="float16",
        max_new_tokens=512,
        temperature=0.0,
        enable_thinking=False,
        quantization_format="awq",
        allow_fallback=False,
    )

    # 3. Filter the 2 target tasks
    all_target_tasks = get_target_tasks()
    diagnostic_tasks = [
        t for t in all_target_tasks if t["task_id"] in ["target_B2_power_and_sensor", "target_C2_sensor_power_order"]
    ]

    groups = [
        ("Group_B2_plan", "B2-plan: Structured Facts Multi-Step Plan"),
        ("Group_Replay", "Replay: Naive Trajectory Segment Replay"),
        ("Group_D_Procedural_Memory", "D: Facts + Conditional Procedural Memory"),
    ]

    diagnostic_results = []
    total_runs = len(diagnostic_tasks) * len(groups)
    current_run = 0

    for t_idx, task_cfg in enumerate(diagnostic_tasks):
        tid = task_cfg["task_id"]
        tclass = task_cfg.get("transfer_class")
        print(f"\n=======================================================")
        print(f"[{t_idx+1}/2] Diagnostic Task: {tid} | Transfer Class: {tclass}")
        print(f"Goal: {task_cfg.get('goal')}")
        print(f"=======================================================")

        for gid, gname in groups:
            current_run += 1
            print(f"\n  [{current_run}/{total_runs}] Running {gname} on {tid}...")
            runner = WorkstationAgentRunner(
                group_id=gid,
                llm_backend=llm_backend,
                max_llm_calls=32,
                max_tool_calls=40,
                time_limit_s=600.0,
            )

            src_ep = raw_source_episodes if gid == "Group_Replay" else None
            facts = fact_store if gid in ["Group_B2_plan", "Group_D_Procedural_Memory"] else None
            mems = procedural_memories if gid == "Group_D_Procedural_Memory" else None

            res = runner.run_task(
                task_config=task_cfg,
                raw_source_episodes=src_ep,
                structured_facts=facts,
                procedural_memory_store=mems,
            )

            diagnostic_results.append(res)
            print(f"      Result: Success={res['success']} ({res['termination_reason']}), "
                  f"Steps={res['step_count']}, LLM_Calls={res['llm_calls']}, "
                  f"P_Tok={res['total_prompt_tokens']}, G_Tok={res['total_generated_tokens']}, "
                  f"Errors={res['tool_errors_count']}, Time={res['wall_time_s']}s")
            print(f"      MemSelected={res['memory_selected_count']}, MemExecuted={res['memory_action_executed_count']}, "
                  f"MemVerified={res['memory_postcondition_verified_count']}, MemInvalidated={res['memory_invalidated_count']}, "
                  f"RecoverySucc={res['online_recovery_succeeded']}")

            # Clean memory
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    # Save output
    output_data = {
        "metadata": {
            "model_path": MODEL_PATH,
            "device": llm_backend.device,
            "quantization": llm_backend.model_metadata.get("quantization"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "diagnostic_runs_count": len(diagnostic_results),
            "groups_evaluated": ["Group_B2_plan", "Group_Replay", "Group_D_Procedural_Memory"],
            "tasks_evaluated": ["target_B2_power_and_sensor", "target_C2_sensor_power_order"],
        },
        "diagnostic_results": diagnostic_results,
    }

    with open(DIAGNOSTIC_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n[Artifact Saved] Diagnostic results written to: {DIAGNOSTIC_OUTPUT_FILE}")

    # Summary table
    print("\n" + "=" * 105)
    print(" DIAGNOSTIC 6-RUN MASTER SUMMARY")
    print("=" * 105)
    print(f"{'Task ID':<30} | {'Group':<28} | {'Success':<8} | {'Steps':<6} | {'LLM Calls':<10} | {'Errors':<7} | {'Time (s)':<9} | {'Termination'}")
    print("-" * 105)
    for r in diagnostic_results:
        succ_str = "✓ PASS" if r["success"] else "✗ FAIL"
        print(f"{r['task_id']:<30} | {r['group_id']:<28} | {succ_str:<8} | {r['step_count']:<6} | {r['llm_calls']:<10} | {r['tool_errors_count']:<7} | {r['wall_time_s']:<9.2f} | {r['termination_reason']}")
    print("-" * 105)


if __name__ == "__main__":
    run_diagnostics()
