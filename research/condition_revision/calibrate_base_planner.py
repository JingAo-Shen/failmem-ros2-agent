"""
Base Planner Capability Calibration Script:
Calibrates Qwen2.5-Coder-7B-Instruct on ScienceWorld benchmark tasks prior to memory injection.
Evaluates:
1. Step-limit sensitivity (10 vs 15 vs 20 steps) to check for horizon cutoff pseudo-failures.
2. Fundamental execution capability on canonical tasks (conductivity, melt, boil).
3. Attribution of Task B failures (distinguishing prior bias / lack of domain knowledge from memory misuse).
"""

import sys
import os
import json
import time
from typing import Dict, Any, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from agents.base_agent import BaseAgent
from condition_evaluator import extract_target_entity


def run_single_calibration_episode(
    env: ScienceWorldWrapper,
    agent: BaseAgent,
    task_name: str,
    variation: int,
    step_limit: int
) -> Dict[str, Any]:
    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    target_entity = extract_target_entity(task_desc)

    history = []
    steps_log = []
    done = False
    final_score = 0.0
    term_reason = "timeout"

    for step_idx in range(step_limit):
        action, thought, stats, act_telemetry = agent.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions
        )

        next_obs, reward, done, info, next_valid_actions = env.step(action)
        history.append((action, next_obs))

        step_entry = {
            "step": step_idx + 1,
            "thought": thought,
            "action": action,
            "executed_action": action,
            "model_action": act_telemetry["proposed_action"],
            "adapter_modified": act_telemetry["adapter_modified"],
            "observation": next_obs,
            "reward": reward,
            "done": done
        }
        steps_log.append(step_entry)

        if done:
            final_score = env.get_score()
            if final_score >= 100.0:
                term_reason = "success"
            elif reward < 0:
                term_reason = "fatal_penalty"
            else:
                term_reason = "environment_done"
            break

        obs = next_obs
        valid_actions = next_valid_actions
        final_score = env.get_score()

    return {
        "task_name": task_name,
        "variation": variation,
        "target": target_entity,
        "step_limit": step_limit,
        "steps_taken": len(steps_log),
        "score": final_score,
        "success": (final_score >= 100.0),
        "term_reason": term_reason,
        "steps": steps_log
    }


def main():
    print("============================================================")
    print("     BASE PLANNER CAPABILITY & STEP BUDGET CALIBRATION")
    print("============================================================")

    llm = LLMClient.get_instance()
    agent = BaseAgent(llm)

    # Test cases:
    # 1. Conductivity Aluminum Foil (var 0) - known positive
    # 2. Conductivity Apricot (var 80) - known negative
    # 3. Melt Ice (var 4) at step_limit 10 vs 15 vs 20
    test_suite = [
        {"task_name": "test-conductivity", "variation": 0, "limit": 10, "tag": "foil_limit_10"},
        {"task_name": "test-conductivity", "variation": 80, "limit": 10, "tag": "apricot_limit_10"},
        {"task_name": "melt", "variation": 4, "limit": 10, "tag": "melt_ice_limit_10"},
        {"task_name": "melt", "variation": 4, "limit": 15, "tag": "melt_ice_limit_15"},
        {"task_name": "melt", "variation": 4, "limit": 20, "tag": "melt_ice_limit_20"},
        {"task_name": "boil", "variation": 2, "limit": 15, "tag": "boil_water_limit_15"}
    ]

    results = []
    total_calls_before = llm.total_calls
    total_tokens_before = llm.total_input_tokens + llm.total_output_tokens

    for tc in test_suite:
        env = ScienceWorldWrapper(step_limit=tc["limit"])
        print(f"\n[Running {tc['tag']}] Task: {tc['task_name']} var {tc['variation']} (Limit: {tc['limit']} steps)...")
        res = run_single_calibration_episode(
            env=env,
            agent=agent,
            task_name=tc["task_name"],
            variation=tc["variation"],
            step_limit=tc["limit"]
        )
        print(f"  Result: Success={res['success']}, Score={res['score']}, Steps={res['steps_taken']}/{tc['limit']}, Reason={res['term_reason']}")
        if res["steps"]:
            final_step = res["steps"][-1]
            print(f"  Final Action: '{final_step['executed_action']}' -> Obs: '{final_step['observation'][:80]}'")
        results.append(res)

    calls_used = llm.total_calls - total_calls_before
    tokens_used = (llm.total_input_tokens + llm.total_output_tokens) - total_tokens_before

    # Save summary
    out_dir = "/code/failmem-ros2-agent/research/condition_revision/runs"
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "base_planner_calibration_results.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "results": results,
            "calls_used": calls_used,
            "tokens_used": tokens_used
        }, f, indent=2)

    print("\n============================================================")
    print(f"Calibration finished. Total calls: {calls_used}, tokens: {tokens_used}")
    print(f"Summary written to: {summary_path}")
    print("============================================================")


if __name__ == "__main__":
    main()
