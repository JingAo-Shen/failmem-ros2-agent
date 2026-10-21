"""
Small Replication Experiment: T1 Paper Clip Conductivity Task under Current vs Strict Adapters
Evaluates exactly 4 episodes:
- R1: current adapter + A input (extra_context = "")
- R2: current adapter + B input (extra_context from attribution_results.json)
- R3: strict adapter + A input (extra_context = "")
- R4: strict adapter + B input (extra_context from attribution_results.json)

Task: test-conductivity, variation: 460 (T1_conductivity_paper_clip_workshop)
Step limit: 10 steps per episode.
Budget limit: <= 4 episodes, <= 60 model calls.
Outputs:
- replication_t1_runs.json
- replication_t1_runs.jsonl
- summary.csv
"""

import os
import sys
import json
import csv
import time
from typing import Dict, Any, List, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from agents.base_agent import BaseAgent


def get_t1_condition_b_context() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_path = os.path.join(
        base_dir,
        "runs",
        "run_20261020_232315_P1_attribution_experiment",
        "attribution_results.json"
    )
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for r in data["results"]:
        if r["task_id"] == "T1_conductivity_paper_clip_workshop" and r["condition"] == "B":
            return r["extra_context"]
    raise ValueError("Could not find T1 Condition B extra_context in attribution_results.json")


def run_episode(
    run_id: str,
    adapter_mode: str,
    memory_condition: str,
    extra_context: str,
    env: ScienceWorldWrapper,
    llm: LLMClient,
    step_limit: int = 10
) -> Dict[str, Any]:
    agent = BaseAgent(llm, adapter_mode=adapter_mode)
    obs, task_desc, valid_actions, info = env.load_and_reset("test-conductivity", 460)
    initial_score = env.get_score()
    initial_candidates = agent._filter_candidate_actions(valid_actions, task_desc, obs)

    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []

    total_prompt_tokens = 0
    total_completion_tokens = 0
    adapter_modified_count = 0
    t0 = time.time()
    final_score = initial_score
    termination_reason = "step_limit_10"
    anomaly_notes = []

    for step_num in range(1, step_limit + 1):
        action, thought, stats, telem = agent.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions,
            extra_context=extra_context
        )

        in_tok = stats.get("input_tokens", 0)
        out_tok = stats.get("output_tokens", 0)
        total_prompt_tokens += in_tok
        total_completion_tokens += out_tok

        if telem.get("adapter_modified", False):
            adapter_modified_count += 1

        if telem.get("terminate_immediately", False) or action is None:
            anomaly_notes.append(f"Step {step_num}: Look around unavailable in strict mode, terminating episode.")
            termination_reason = "adapter_error_look_around_unavailable"
            step_record = {
                "step": step_num,
                "system_prompt": telem.get("system_prompt", ""),
                "user_prompt": telem.get("user_prompt", ""),
                "raw_response": telem.get("raw_response", ""),
                "parsed_response": telem.get("parsed_response", {}),
                "thought": thought,
                "proposed_action": telem.get("proposed_action", ""),
                "executed_action": None,
                "adapter_modified": True,
                "adapter_reason": telem.get("adapter_reason", ""),
                "candidate_actions": telem.get("candidate_actions", []),
                "observation": obs,
                "next_observation": None,
                "reward": 0.0,
                "score": final_score,
                "done": True,
                "input_tokens": in_tok,
                "output_tokens": out_tok
            }
            steps_log.append(step_record)
            break

        # Step environment
        next_obs, reward, done, info, next_valid_actions = env.step(action)
        current_score = env.get_score()

        step_record = {
            "step": step_num,
            "system_prompt": telem.get("system_prompt", ""),
            "user_prompt": telem.get("user_prompt", ""),
            "raw_response": telem.get("raw_response", ""),
            "parsed_response": telem.get("parsed_response", {}),
            "thought": thought,
            "proposed_action": telem.get("proposed_action", ""),
            "executed_action": action,
            "adapter_modified": telem.get("adapter_modified", False),
            "adapter_reason": telem.get("adapter_reason", ""),
            "candidate_actions": telem.get("candidate_actions", []),
            "observation": obs,
            "next_observation": next_obs,
            "reward": reward,
            "score": current_score,
            "done": done,
            "input_tokens": in_tok,
            "output_tokens": out_tok
        }
        steps_log.append(step_record)
        history.append((action, next_obs))
        obs = next_obs
        valid_actions = next_valid_actions
        final_score = current_score

        if final_score >= 100.0:
            termination_reason = "success_100"
            break
        elif done:
            termination_reason = "env_done"
            break

    duration = round(time.time() - t0, 2)
    success = (final_score >= 100.0)

    return {
        "run_id": run_id,
        "adapter_mode": adapter_mode,
        "memory_condition": memory_condition,
        "task_name": "test-conductivity",
        "variation": 460,
        "task_id": "T1_conductivity_paper_clip_workshop",
        "initial_task_desc": task_desc,
        "initial_observation": obs if not steps_log else steps_log[0]["observation"],
        "initial_score": initial_score,
        "initial_candidate_actions": initial_candidates,
        "final_score": final_score,
        "success": success,
        "steps_taken": len(steps_log),
        "adapter_modified_count": adapter_modified_count,
        "model_calls": len(steps_log),
        "total_input_tokens": total_prompt_tokens,
        "total_output_tokens": total_completion_tokens,
        "termination_reason": termination_reason,
        "duration_seconds": duration,
        "anomalies": anomaly_notes,
        "steps": steps_log
    }


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)

    extra_context_b = get_t1_condition_b_context()

    print("=" * 70)
    print("STARTING T1 REPLICATION EXPERIMENT (4 EPISODES)")
    print("Task: test-conductivity var 460")
    print("Model: Qwen2.5-Coder-7B-Instruct (greedy, do_sample=False)")
    print("Code version: b67a8b1")
    print("=" * 70)

    env = ScienceWorldWrapper(step_limit=10)
    llm = LLMClient.get_instance()

    configs = [
        ("R1", "current", "A", ""),
        ("R2", "current", "B", extra_context_b),
        ("R3", "strict", "A", ""),
        ("R4", "strict", "B", extra_context_b),
    ]

    all_runs = []
    summary_rows = []

    # Verification of initial state consistency across the 4 runs
    initial_states = []

    for run_id, adapter_mode, memory_condition, extra_context in configs:
        print(f"\n>>> Running {run_id}: adapter={adapter_mode}, memory={memory_condition}...")
        ep_data = run_episode(
            run_id=run_id,
            adapter_mode=adapter_mode,
            memory_condition=memory_condition,
            extra_context=extra_context,
            env=env,
            llm=llm,
            step_limit=10
        )
        all_runs.append(ep_data)

        initial_states.append({
            "run_id": run_id,
            "task_desc": ep_data["initial_task_desc"],
            "obs": ep_data["initial_observation"],
            "score": ep_data["initial_score"],
            "candidates": ep_data["initial_candidate_actions"]
        })

        summary_rows.append({
            "run_id": ep_data["run_id"],
            "adapter_mode": ep_data["adapter_mode"],
            "memory_condition": ep_data["memory_condition"],
            "score": ep_data["final_score"],
            "success": ep_data["success"],
            "steps": ep_data["steps_taken"],
            "adapter_modified_count": ep_data["adapter_modified_count"],
            "model_calls": ep_data["model_calls"],
            "input_tokens": ep_data["total_input_tokens"],
            "output_tokens": ep_data["total_output_tokens"],
            "termination_reason": ep_data["termination_reason"]
        })

        print(f"    Finished {run_id}: score={ep_data['final_score']}, success={ep_data['success']}, steps={ep_data['steps_taken']}, adapter_mods={ep_data['adapter_modified_count']}, termination={ep_data['termination_reason']}")

    env.close()

    # Check initial state consistency
    base_state = initial_states[0]
    initial_consistent = True
    for s in initial_states[1:]:
        if s["task_desc"] != base_state["task_desc"] or s["obs"] != base_state["obs"] or s["candidates"] != base_state["candidates"]:
            initial_consistent = False
            print(f"[WARNING] Initial state mismatch in {s['run_id']}")

    print(f"\nInitial state consistency across R1-R4: {initial_consistent}")

    # Save JSON
    json_path = os.path.join(out_dir, "replication_t1_runs.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "experiment": "replication_t1_conductivity_paper_clip",
            "model_name": "Qwen2.5-Coder-7B-Instruct",
            "model_path": "/models/Qwen2.5-Coder-7B-Instruct",
            "decoding_config": {
                "do_sample": False,
                "temperature": 0.0,
                "max_new_tokens": 128
            },
            "code_version": "b67a8b1",
            "initial_state_consistent": initial_consistent,
            "runs": all_runs
        }, f, indent=2, ensure_ascii=False)

    # Save JSONL
    jsonl_path = os.path.join(out_dir, "replication_t1_runs.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in all_runs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Save CSV
    csv_path = os.path.join(out_dir, "summary.csv")
    fieldnames = [
        "run_id", "adapter_mode", "memory_condition", "score", "success",
        "steps", "adapter_modified_count", "model_calls", "input_tokens",
        "output_tokens", "termination_reason"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    print("\n" + "=" * 70)
    print("REPLICATION EXPERIMENT COMPLETED")
    print(f"JSON saved to: {json_path}")
    print(f"JSONL saved to: {jsonl_path}")
    print(f"CSV saved to: {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
