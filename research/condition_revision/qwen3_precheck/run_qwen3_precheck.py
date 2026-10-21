"""
Qwen3-14B-AWQ Candidate Planner Pre-check Runner
Tasks:
- C1: test-conductivity var 0
- C2: test-conductivity var 460
- C3: test-conductivity var 160
- C4: test-conductivity var 230
- C5: melt var 4
- C6: boil var 2

Settings:
- adapter_mode="native"
- history_mode="all_steps"
- extra_context=""
- max_new_tokens=256
- seed=3407 fixed before each task
- step limit=30
- hard cap: max 6 episodes, 400 model calls
"""

import os
import sys
import json
import csv
import time
from typing import Dict, Any, List, Tuple, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_wrapper import ScienceWorldWrapper
from qwen3_llm_client import Qwen3AWQClient, set_deterministic_seed
from agents.base_agent import BaseAgent


def run_episode(
    run_id: str,
    task_name: str,
    variation: int,
    env: ScienceWorldWrapper,
    llm: Qwen3AWQClient,
    live_meta: Dict[str, Any],
    step_limit: int = 30,
    max_calls_remaining: int = 400
) -> Dict[str, Any]:
    # Fix seed before each task
    set_deterministic_seed(3407)

    calls_before = llm.total_calls
    agent = BaseAgent(
        llm,
        adapter_mode="native",
        history_mode="all_steps",
        max_new_tokens=256
    )

    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    initial_score = env.get_score()
    initial_candidates = agent._filter_candidate_actions(valid_actions, task_desc, obs)

    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []

    total_prompt_tokens = 0
    total_completion_tokens = 0
    adapter_modified_count = 0
    t0 = time.time()
    final_score = initial_score
    first_success_step: Optional[int] = None
    termination_reason = f"step_limit_{step_limit}"
    failure_type = "none"
    anomaly_notes = []

    score_at_10: Optional[float] = None
    score_at_20: Optional[float] = None
    score_at_30: Optional[float] = None

    for step_num in range(1, step_limit + 1):
        if (llm.total_calls - calls_before) >= max_calls_remaining:
            termination_reason = "batch_call_limit_reached"
            failure_type = "budget_exhausted"
            anomaly_notes.append(f"Step {step_num}: reached maximum call limit.")
            break

        action, thought, stats, telem = agent.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions,
            extra_context=""
        )

        in_tok = stats.get("input_tokens", 0)
        out_tok = stats.get("output_tokens", 0)
        total_prompt_tokens += in_tok
        total_completion_tokens += out_tok

        if telem.get("adapter_modified", False):
            adapter_modified_count += 1

        if telem.get("terminate_immediately", False) or action is None:
            anomaly_notes.append(f"Step {step_num}: empty or non-string action, terminating episode.")
            termination_reason = "parse_exception_empty_or_non_string"
            failure_type = "parsing_failure"
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
                "history_mode": "all_steps",
                "proposed_action_in_candidate_list": telem.get("proposed_action_in_candidate_list", False),
                "executed_action_equals_trimmed_proposed": False,
                "observation": obs,
                "next_observation": None,
                "reward": 0.0,
                "score": final_score,
                "done": True,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "latency_s": stats.get("latency_s", 0.0),
                "actual_generation_params": stats.get("actual_generation_params", {}),
                "peak_vram_gib": stats.get("peak_vram_gib", 0.0),
                "model_call_index": llm.total_calls
            }
            steps_log.append(step_record)
            break

        # Step environment directly with action (native pass-through)
        try:
            next_obs, reward, done, info, next_valid_actions = env.step(action)
            current_score = env.get_score()
        except Exception as e:
            termination_reason = f"env_exception_{type(e).__name__}"
            failure_type = "environment_exception"
            anomaly_notes.append(f"Step {step_num}: environment exception {str(e)}")
            break

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
            "history_mode": "all_steps",
            "proposed_action_in_candidate_list": telem.get("proposed_action_in_candidate_list", False),
            "executed_action_equals_trimmed_proposed": telem.get("executed_action_equals_trimmed_proposed", False),
            "observation": obs,
            "next_observation": next_obs,
            "reward": reward,
            "score": current_score,
            "done": done,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "latency_s": stats.get("latency_s", 0.0),
            "actual_generation_params": stats.get("actual_generation_params", {}),
            "peak_vram_gib": stats.get("peak_vram_gib", 0.0),
            "model_call_index": llm.total_calls
        }
        steps_log.append(step_record)
        history.append((action, next_obs))
        obs = next_obs
        valid_actions = next_valid_actions
        final_score = current_score

        if step_num == 10:
            score_at_10 = current_score
        elif step_num == 20:
            score_at_20 = current_score
        elif step_num == 30:
            score_at_30 = current_score

        if current_score >= 100.0:
            if first_success_step is None:
                first_success_step = step_num
            termination_reason = "success_100"
            failure_type = "none"
            break
        elif done:
            termination_reason = "env_done"
            failure_type = "task_failure"
            break

    calls_after = llm.total_calls
    model_calls = calls_after - calls_before
    duration = round(time.time() - t0, 2)
    success = (final_score >= 100.0)
    if not success and failure_type == "none":
        failure_type = "task_failure"

    return {
        "run_id": run_id,
        "adapter_mode": "native",
        "history_mode": "all_steps",
        "memory_condition": "A_NoMemory",
        "task_name": task_name,
        "variation": variation,
        "seed": 3407,
        "extra_context": "",
        "live_model_metadata": live_meta,
        "step_limit": step_limit,
        "initial_task_desc": task_desc,
        "initial_observation": steps_log[0]["observation"] if steps_log else obs,
        "initial_score": initial_score,
        "initial_candidate_actions": initial_candidates,
        "final_score": final_score,
        "success": success,
        "failure_type": failure_type,
        "steps_taken": len(steps_log),
        "first_success_step": first_success_step,
        "score_at_step_10": score_at_10,
        "score_at_step_20": score_at_20,
        "score_at_step_30": score_at_30,
        "adapter_modified_count": adapter_modified_count,
        "model_calls": model_calls,
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

    print("=" * 70)
    print("STARTING QWEN3-14B-AWQ CANDIDATE PLANNER PRE-CHECK")
    print("=" * 70)

    # 1. Initialize fresh Qwen3AWQClient
    print("[1/3] Loading Qwen3-14B-AWQ model in a fresh process...")
    t0_load = time.time()
    try:
        llm = Qwen3AWQClient(model_path="/models/Qwen3-14B-AWQ")
        live_meta = llm.get_model_metadata()
    except Exception as e:
        print(f"CRITICAL: Model loading failed with exception: {e}")
        fail_record = {
            "status": "FAILED_LOADING",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(out_dir, "load_and_json_check.json"), "w", encoding="utf-8") as f:
            json.dump(fail_record, f, indent=2)
        sys.exit(1)

    load_duration = round(time.time() - t0_load, 2)
    print(f"Model loaded in {load_duration}s.")
    print("Live Model Metadata:")
    for k, v in live_meta.items():
        print(f"  {k}: {v}")

    # Save live model metadata
    meta_path = os.path.join(out_dir, "live_qwen3_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(live_meta, f, indent=2)
    print(f"Saved metadata to {meta_path}")

    # 2. Non-environment JSON Output Check
    print("\n[2/3] Performing non-environment JSON output check...")
    json_check_prompt = "Return ONLY a JSON object: {\"ok\": true}"
    set_deterministic_seed(3407)
    calls_start = llm.total_calls
    parsed_check, check_stats = llm.generate_json(
        json_check_prompt,
        system_prompt="You are a helpful assistant. Output ONLY valid JSON."
    )
    json_check_calls = llm.total_calls - calls_start

    check_passed = (parsed_check.get("ok") is True)
    check_record = {
        "status": "PASSED" if check_passed else "FAILED",
        "prompt": json_check_prompt,
        "attempts": check_stats.get("attempts", 1),
        "raw_response": check_stats.get("raw_text", ""),
        "raw_response_first_attempt": check_stats.get("raw_text_first_attempt", None),
        "parsed_response": parsed_check,
        "calls_used": json_check_calls,
        "input_tokens": check_stats.get("input_tokens", 0),
        "output_tokens": check_stats.get("output_tokens", 0),
        "latency_s": check_stats.get("latency_s", 0.0),
        "actual_generation_params": check_stats.get("actual_generation_params", {}),
        "live_metadata": live_meta
    }
    check_file = os.path.join(out_dir, "load_and_json_check.json")
    with open(check_file, "w", encoding="utf-8") as f:
        json.dump(check_record, f, indent=2)
    print(f"JSON check record saved to {check_file}. Status: {check_record['status']}")

    if not check_passed:
        print("CRITICAL: JSON output check failed! Halting before environment tasks.")
        sys.exit(1)

    # 3. Six Environment Tasks
    print("\n[3/3] Running 6 qualification tasks (C1 - C6)...")
    tasks_config = [
        ("C1", "test-conductivity", 0, "C1_conductivity_var0.json"),
        ("C2", "test-conductivity", 460, "C2_conductivity_var460.json"),
        ("C3", "test-conductivity", 160, "C3_conductivity_var160.json"),
        ("C4", "test-conductivity", 230, "C4_conductivity_var230.json"),
        ("C5", "melt", 4, "C5_melt_var4.json"),
        ("C6", "boil", 2, "C6_boil_var2.json"),
    ]

    env = ScienceWorldWrapper(step_limit=30)
    summary_rows = []
    total_batch_calls_limit = 400

    for run_id, task_name, var, json_name in tasks_config:
        remaining_calls = total_batch_calls_limit - llm.total_calls
        if remaining_calls <= 0:
            print(f"Reached batch call limit of {total_batch_calls_limit}. Stopping before {run_id}.")
            break

        print(f"\n>>> Running {run_id}: task={task_name} var={var}...")
        ep_data = run_episode(
            run_id=run_id,
            task_name=task_name,
            variation=var,
            env=env,
            llm=llm,
            live_meta=live_meta,
            step_limit=30,
            max_calls_remaining=remaining_calls
        )

        indiv_path = os.path.join(out_dir, json_name)
        with open(indiv_path, "w", encoding="utf-8") as f:
            json.dump(ep_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved individual JSON: {indiv_path}")

        summary_rows.append({
            "run_id": ep_data["run_id"],
            "task_name": ep_data["task_name"],
            "variation": ep_data["variation"],
            "score": ep_data["final_score"],
            "success": ep_data["success"],
            "failure_type": ep_data["failure_type"],
            "steps": ep_data["steps_taken"],
            "adapter_modified_count": ep_data["adapter_modified_count"],
            "model_calls": ep_data["model_calls"],
            "input_tokens": ep_data["total_input_tokens"],
            "output_tokens": ep_data["total_output_tokens"],
            "termination_reason": ep_data["termination_reason"],
            "first_success_step": ep_data["first_success_step"] if ep_data["first_success_step"] is not None else "",
            "score_at_step_10": ep_data["score_at_step_10"] if ep_data["score_at_step_10"] is not None else "",
            "score_at_step_20": ep_data["score_at_step_20"] if ep_data["score_at_step_20"] is not None else "",
            "score_at_step_30": ep_data["score_at_step_30"] if ep_data["score_at_step_30"] is not None else ""
        })

        print(f"    Finished {run_id}: score={ep_data['final_score']}, success={ep_data['success']}, steps={ep_data['steps_taken']}, failure_type={ep_data['failure_type']}, termination={ep_data['termination_reason']}, calls={ep_data['model_calls']}")

    env.close()

    # Save summary.csv
    csv_path = os.path.join(out_dir, "summary.csv")
    fieldnames = [
        "run_id", "task_name", "variation", "score", "success", "failure_type",
        "steps", "adapter_modified_count", "model_calls", "input_tokens",
        "output_tokens", "termination_reason", "first_success_step",
        "score_at_step_10", "score_at_step_20", "score_at_step_30"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)
    print(f"\nSaved summary CSV: {csv_path}")

    print("\n" + "=" * 70)
    print("QWEN3-14B-AWQ CANDIDATE PLANNER PRE-CHECK COMPLETED")
    print(f"Total model calls used: {llm.total_calls} (limit: {total_batch_calls_limit})")
    print("=" * 70)


if __name__ == "__main__":
    main()
