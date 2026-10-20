"""
Base Planner Capability Pre-Check Script:
Tests whether Qwen2.5-Coder-7B-Instruct can:
1. Complete the experience source task (test-conductivity var 0).
2. Execute valid actions on multi-step tasks (melt var 4, boil var 2) without fatal room-focus penalties.
3. Show behavioral responsiveness to candidate actions and prompt state.
Tracks proposed action vs executed action (adapter telemetry).
"""

import sys
import os
import json
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from agents.base_agent import BaseAgent
from condition_evaluator import extract_target_entity


def test_task(env: ScienceWorldWrapper, agent: BaseAgent, task_name: str, variation: int, max_steps: int = 10):
    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    target = extract_target_entity(task_desc)
    print(f"\n--- Testing {task_name} (var {variation}, target: '{target}') ---")
    print(f"Task Description: {task_desc}")

    history = []
    steps_log = []
    done = False
    final_score = 0.0
    term_reason = "timeout"

    for step_idx in range(max_steps):
        action, thought, stats, act_telemetry = agent.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions
        )

        next_obs, reward, done, info, next_valid_actions = env.step(action)
        history.append((action, next_obs))
        steps_log.append({
            "step": step_idx + 1,
            "thought": thought,
            "proposed_action": act_telemetry["proposed_action"],
            "executed_action": action,
            "adapter_modified": act_telemetry["adapter_modified"],
            "adapter_reason": act_telemetry["adapter_reason"],
            "observation": next_obs,
            "reward": reward,
            "done": done
        })

        print(f"  Step {step_idx+1}: Proposed='{act_telemetry['proposed_action']}', Executed='{action}' (AdapterMod={act_telemetry['adapter_modified']}) -> Reward={reward}")
        print(f"    Obs: '{next_obs.strip()[:100]}'")

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

    print(f"  Outcome: Score={final_score}, Success={final_score >= 100.0}, Steps={len(steps_log)}, Reason={term_reason}")
    return {
        "task_name": task_name,
        "variation": variation,
        "target": target,
        "score": final_score,
        "success": final_score >= 100.0,
        "steps_taken": len(steps_log),
        "term_reason": term_reason,
        "steps": steps_log
    }


def main():
    llm = LLMClient.get_instance()
    agent = BaseAgent(llm)
    env = ScienceWorldWrapper(step_limit=10)

    results = []
    results.append(test_task(env, agent, "test-conductivity", 0, max_steps=8))
    results.append(test_task(env, agent, "melt", 4, max_steps=8))
    results.append(test_task(env, agent, "boil", 2, max_steps=8))

    out_path = "/code/failmem-ros2-agent/research/condition_revision/runs/planner_precheck_results.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nPre-check results saved to {out_path}")


if __name__ == "__main__":
    main()
