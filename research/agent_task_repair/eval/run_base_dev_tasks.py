"""
Calibration runner for Phase B: Executes B0 across the 6 Base Development Tasks.
Evaluates basic planning, pickup, sequential navigation, delivery, and detour execution.
"""
import sys
import json
import time
from pathlib import Path
from ..env.scenarios import get_base_development_tasks
from ..memory.baselines import B0_NoMemory
from ..agent.llm_backend import LLMBackend
from ..agent.agent_runner import AgentRunner
from ..eval.scorer import PilotScorer


def run_base_dev_calibration(model_path: str = "/models/Qwen2.5-Coder-7B-Instruct", device: str = "cuda"):
    tasks = get_base_development_tasks()
    print("=" * 80)
    print(f"PHASE B: RUNNING B0 ON {len(tasks)} BASE DEVELOPMENT TASKS")
    print(f"Model: {model_path} on {device}")
    print("=" * 80)

    llm = LLMBackend(model_path=model_path, device=device)
    memory = B0_NoMemory()
    runner = AgentRunner(llm_backend=llm, memory_adapter=memory, run_id="phase_b_calib")

    task_results = []
    success_count = 0

    for idx, task_spec in enumerate(tasks):
        task_id = task_spec["task_id"]
        name = task_spec.get("name", task_id)
        print(f"\n[{idx+1}/{len(tasks)}] Running {name} ({task_id})...")
        t0 = time.time()
        res = runner.run_task(task_spec, task_index=idx, seq_id="base_dev")
        t1 = time.time()
        
        is_succ = res["success"]
        if is_succ:
            success_count += 1
        print(f"  -> Success: {is_succ} | Steps: {res['step_count']} | LLM Calls: {res['llm_calls']} | Time: {t1-t0:.2f}s | Violations: {res['constraint_violations']}")
        task_results.append(res)

    print("\n" + "=" * 80)
    print(f"PHASE B CALIBRATION SUMMARY: {success_count}/{len(tasks)} ({success_count/len(tasks)*100:.1f}%) Tasks Succeeded")
    print("=" * 80)

    return {
        "success_count": success_count,
        "total_tasks": len(tasks),
        "task_results": task_results,
    }


if __name__ == "__main__":
    run_base_dev_calibration()
