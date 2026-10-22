"""
Natural Experience Transfer Screening Runner (Phase P1b):
Executes 24 episodes (4 variations x 3 conditions x 2 blocks) for task 'boil'.
- Native action pass-through
- Dynamic action_templates from env.get_action_templates()
- all_steps history formatting
- 150-char observation truncation
- Immediate per-episode disk persistence (runs, CSVs, budget ledger)
- Dual step metrics: env_moves and model decision_step
- Real-time budget limit enforcement (<= $10.00 USD cumulative)
"""
import os
import sys
import json
import time
import csv
import random
import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from env_wrapper import ScienceWorldWrapper
from agents.base_agent import BaseAgent
from remote_llm_client import (
    RemoteLLMClient,
    RemotePlannerError,
    BudgetExceededError,
    PayloadSizeLimitExceededError
)
from condition_evaluator import extract_target_entity

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(SCRIPT_DIR, "runs")
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "manifest.json")
FROZEN_PATH = os.path.join(SCRIPT_DIR, "frozen_experiences.json")
BUDGET_LEDGER_PATH = os.path.join(SCRIPT_DIR, "budget_ledger.json")
SUMMARY_CSV_PATH = os.path.join(SCRIPT_DIR, "natural_experience_screen_summary.csv")
STEP_SUMMARY_CSV_PATH = os.path.join(SCRIPT_DIR, "step_summary.csv")


def set_local_seed(seed: int = 3407):
    """Sets local pseudo-random seed without claiming control over remote LLM."""
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass


def load_or_init_budget_ledger(frozen_data: Dict[str, Any]) -> Dict[str, Any]:
    if os.path.exists(BUDGET_LEDGER_PATH):
        with open(BUDGET_LEDGER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return frozen_data.get("client_budget_ledger", {})


def save_budget_ledger(client: RemoteLLMClient):
    ledger = client.get_budget_ledger()
    with open(BUDGET_LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)


def get_completed_episode_ids() -> set:
    completed = set()
    if os.path.exists(SUMMARY_CSV_PATH):
        with open(SUMMARY_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("episode_id"):
                    completed.add(row["episode_id"])
    return completed


def append_summary_row(row_dict: Dict[str, Any]):
    file_exists = os.path.exists(SUMMARY_CSV_PATH)
    fieldnames = [
        "episode_id", "block", "run_index_in_block", "condition", "task_name", "variation",
        "success", "final_score", "decision_steps", "env_moves", "first_success_step",
        "termination_reason", "task_model_calls", "task_input_tokens", "task_output_tokens",
        "duration_seconds", "estimated_cost_usd", "client_cumulative_calls", "client_total_cost_usd"
    ]
    with open(SUMMARY_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row_dict)


def append_step_rows(rows: List[Dict[str, Any]]):
    file_exists = os.path.exists(STEP_SUMMARY_CSV_PATH)
    fieldnames = [
        "episode_id", "block", "condition", "task_name", "variation",
        "decision_step", "env_moves", "proposed_action", "executed_action",
        "adapter_modified", "adapter_reason", "env_obs", "reward", "score", "done",
        "finish_reason", "empty_content", "hit_output_token_limit", "retry_attempted", "parse_error",
        "model_calls_this_step", "latency_s", "input_tokens", "output_tokens",
        "client_cumulative_calls", "client_known_cost_usd"
    ]
    with open(STEP_SUMMARY_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)


def run_episode(
    spec: Dict[str, Any],
    client: RemoteLLMClient,
    env: ScienceWorldWrapper,
    exp_b_text: str,
    exp_c_text: str
) -> Dict[str, Any]:
    ep_id = spec["episode_id"]
    block = spec["block"]
    run_idx = spec["run_index_in_block"]
    task_name = spec["task_name"]
    variation = spec["variation"]
    cond = spec["condition"]
    step_limit = spec.get("step_limit", 30)

    print(f"\n========================================================")
    print(f"Starting {ep_id} (Block {block}, Run {run_idx}/12): {task_name} var={variation}, cond={cond}")
    print(f"========================================================")

    set_local_seed(3407)

    # Set condition prompt
    if cond == "A":
        extra_context = ""
    elif cond == "B":
        extra_context = f"Experience from a previous ScienceWorld interaction:\n{exp_b_text}"
    elif cond == "C":
        extra_context = f"Experience from a previous ScienceWorld interaction:\n{exp_c_text}"
    else:
        raise ValueError(f"Unknown condition: {cond}")

    # Load environment
    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    raw_templates = env.get_action_templates()
    if not raw_templates:
        raise RuntimeError("Environment get_action_templates() returned empty list!")

    target = extract_target_entity(task_desc)
    initial_score = float(env.get_score())
    initial_obs = str(obs)
    initial_moves = info.get("moves", 0)

    agent = BaseAgent(
        llm_client=client,
        adapter_mode="native",
        history_mode="all_steps",
        prompt_mode="action_templates",
        action_templates=raw_templates,
        max_new_tokens=None
    )

    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []
    episode_step_rows: List[Dict[str, Any]] = []
    done = False
    final_score = initial_score
    termination_reason = "step_limit_30"
    first_success_step = None
    ep_start_time = time.time()

    ep_model_calls = 0
    ep_input_tokens = 0
    ep_output_tokens = 0
    ep_known_cost_start = client.known_cost_usd

    current_env_moves = initial_moves

    for step_num in range(1, step_limit + 1):
        step_t0 = time.time()
        print(f"--- [{ep_id}|{cond}|Var{variation}] Step {step_num}/{step_limit} ---")

        max_step_retries = 3
        action, thought, step_stats, telemetry = None, None, None, None
        for attempt_idx in range(max_step_retries):
            try:
                action, thought, step_stats, telemetry = agent.select_action(
                    task_desc=task_desc,
                    current_obs=obs,
                    history=history,
                    valid_actions=valid_actions,
                    extra_context=extra_context,
                    action_templates=raw_templates
                )
                break
            except RemotePlannerError as rpe:
                if attempt_idx < max_step_retries - 1:
                    print(f"  [Transient Error in Step {step_num}]: {rpe}. Retrying in 5s (attempt {attempt_idx+1}/{max_step_retries})...")
                    time.sleep(5.0)
                else:
                    raise

        step_calls = step_stats.get("calls", 1)
        ep_model_calls += step_calls

        in_tok = step_stats.get("input_tokens", 0)
        out_tok = step_stats.get("output_tokens", 0)
        if isinstance(in_tok, int) and isinstance(out_tok, int):
            ep_input_tokens += in_tok
            ep_output_tokens += out_tok

        proposed_act = telemetry.get("proposed_action", "")
        executed_act = action if action is not None else "None"
        adapter_modified = telemetry.get("adapter_modified", False)
        adapter_reason = telemetry.get("adapter_reason", "")
        retry_attempted = step_stats.get("retry_attempted", False)
        parse_error = telemetry.get("parsed_response", {}).get("parse_error", False)
        finish_reason = step_stats.get("finish_reason", "unknown")
        empty_content = step_stats.get("empty_content", False)
        hit_output_token_limit = step_stats.get("hit_output_token_limit", False)

        reward = 0.0
        next_obs = ""

        if action is None:
            termination_reason = "empty_or_non_string_terminate"
            done = True
            next_obs = "TERMINATED: Empty or non-string action proposed by model."
        else:
            next_obs, reward, done, info, next_valid_actions = env.step(action)
            valid_actions = next_valid_actions
            history.append((action, next_obs))
            current_env_moves = info.get("moves", current_env_moves)

        final_score = float(env.get_score())
        step_dt = time.time() - step_t0

        if final_score >= 100.0 and first_success_step is None:
            first_success_step = step_num
            termination_reason = "success_100"
            done = True

        step_data = {
            "decision_step": step_num,
            "env_moves": current_env_moves,
            "thought": thought,
            "proposed_action": proposed_act,
            "executed_action": executed_act,
            "adapter_modified": adapter_modified,
            "adapter_reason": adapter_reason,
            "observation": next_obs,
            "reward": reward,
            "score": final_score,
            "done": done,
            "telemetry": telemetry,
            "step_stats": step_stats,
            "latency_s": round(step_dt, 3)
        }
        steps_log.append(step_data)

        csv_row = {
            "episode_id": ep_id,
            "block": block,
            "condition": cond,
            "task_name": task_name,
            "variation": variation,
            "decision_step": step_num,
            "env_moves": current_env_moves,
            "proposed_action": proposed_act,
            "executed_action": executed_act,
            "adapter_modified": adapter_modified,
            "adapter_reason": adapter_reason,
            "env_obs": next_obs.replace("\n", " ")[:150],
            "reward": reward,
            "score": final_score,
            "done": done,
            "finish_reason": finish_reason,
            "empty_content": empty_content,
            "hit_output_token_limit": hit_output_token_limit,
            "retry_attempted": retry_attempted,
            "parse_error": parse_error,
            "model_calls_this_step": step_calls,
            "latency_s": round(step_dt, 3),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "client_cumulative_calls": client.total_calls,
            "client_known_cost_usd": round(client.known_cost_usd, 6)
        }
        episode_step_rows.append(csv_row)

        print(f"  Action: '{executed_act}', Reward: {reward}, Score: {final_score}, Done: {done}")
        print(f"  Obs snippet: {next_obs.strip()[:90]}")

        if done:
            if final_score >= 100.0:
                termination_reason = "success_100"
            elif reward < 0:
                termination_reason = "fatal_penalty"
            elif termination_reason == "step_limit_30":
                termination_reason = "env_done"
            break

        obs = next_obs

    ep_duration = time.time() - ep_start_time
    is_success = (final_score >= 100.0)
    ep_cost = round(client.known_cost_usd - ep_known_cost_start, 6)

    episode_result = {
        "episode_id": ep_id,
        "block": block,
        "run_index_in_block": run_idx,
        "task_name": task_name,
        "variation": variation,
        "condition": cond,
        "condition_description": spec.get("condition_description", ""),
        "experience_sha256": spec.get("experience_sha256"),
        "target_entity": target,
        "step_limit": step_limit,
        "seed": 3407,
        "initial_task_desc": task_desc,
        "initial_observation": initial_obs,
        "initial_score": initial_score,
        "initial_action_templates": raw_templates,
        "final_score": final_score,
        "success": is_success,
        "decision_steps": len(steps_log),
        "env_moves": current_env_moves,
        "termination_reason": termination_reason,
        "first_success_step": first_success_step,
        "task_model_calls": ep_model_calls,
        "task_input_tokens": ep_input_tokens,
        "task_output_tokens": ep_output_tokens,
        "duration_seconds": round(ep_duration, 2),
        "estimated_cost_usd": ep_cost,
        "steps": steps_log
    }

    # Immediate per-episode disk persistence
    ep_filename = f"{ep_id}_{cond}_var{variation}_block{block}.json"
    ep_filepath = os.path.join(RUNS_DIR, ep_filename)
    with open(ep_filepath, "w", encoding="utf-8") as f:
        json.dump(episode_result, f, indent=2, ensure_ascii=False)

    append_step_rows(episode_step_rows)

    summary_row = {
        "episode_id": ep_id,
        "block": block,
        "run_index_in_block": run_idx,
        "condition": cond,
        "task_name": task_name,
        "variation": variation,
        "success": is_success,
        "final_score": final_score,
        "decision_steps": len(steps_log),
        "env_moves": current_env_moves,
        "first_success_step": first_success_step,
        "termination_reason": termination_reason,
        "task_model_calls": ep_model_calls,
        "task_input_tokens": ep_input_tokens,
        "task_output_tokens": ep_output_tokens,
        "duration_seconds": round(ep_duration, 2),
        "estimated_cost_usd": ep_cost,
        "client_cumulative_calls": client.total_calls,
        "client_total_cost_usd": round(client.known_cost_usd + client.unknown_reserved_cost_usd, 6)
    }
    append_summary_row(summary_row)
    save_budget_ledger(client)

    print(f"\n[Persisted {ep_id}] Outcome: Success={is_success}, Score={final_score}, Steps={len(steps_log)}, Cost=${ep_cost:.4f}, TotalCost=${client.known_cost_usd:.4f}")
    return episode_result


def main():
    os.makedirs(RUNS_DIR, exist_ok=True)

    with open(FROZEN_PATH, "r", encoding="utf-8") as f:
        frozen_data = json.load(f)

    exp_b_text = frozen_data["experience_b"]["experience_text"]
    exp_c_text = frozen_data["experience_c"]["experience_text"]

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    runs = manifest["runs"]
    completed_ids = get_completed_episode_ids()
    print(f"Total manifest runs: {len(runs)}, already completed: {len(completed_ids)}")

    # Initialize client with continuation ledger
    init_ledger = load_or_init_budget_ledger(frozen_data)
    prior_cost = float(init_ledger.get("known_cost_usd", init_ledger.get("estimated_cost_usd_from_usage", 0.129441)))
    prior_reserved = float(init_ledger.get("unknown_reserved_cost_usd", init_ledger.get("conservative_reserved_cost_usd", 0.0)))
    prior_calls = int(init_ledger.get("total_request_attempts", 59))
    prior_in_tok = int(init_ledger.get("total_input_tokens", 1433) if isinstance(init_ledger.get("total_input_tokens"), int) else 0)
    prior_out_tok = int(init_ledger.get("total_output_tokens", 940) if isinstance(init_ledger.get("total_output_tokens"), int) else 0)

    client = RemoteLLMClient(
        allow_live_network=True,
        initial_cost_usd=prior_cost,
        initial_reserved_usd=prior_reserved,
        initial_calls=prior_calls,
        initial_input_tokens=prior_in_tok,
        initial_output_tokens=prior_out_tok,
        max_budget_usd=10.00,
        max_attempts=1557
    )

    env = ScienceWorldWrapper(step_limit=30)

    try:
        for spec in runs:
            ep_id = spec["episode_id"]
            if ep_id in completed_ids:
                print(f"Skipping already completed episode: {ep_id}")
                continue

            run_episode(spec, client, env, exp_b_text, exp_c_text)

    except Exception as e:
        print(f"\n[FATAL EXCEPTION DURING RUN]: {type(e).__name__}: {e}")
        save_budget_ledger(client)
        raise
    finally:
        env.close()
        save_budget_ledger(client)
        print("\nAll execution finished or safely interrupted. Final ledger saved.")


if __name__ == "__main__":
    main()
