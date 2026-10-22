"""
Qwen3-14B-AWQ No-Candidates Diagnostic Experiment (N1 - N6)
Evaluates 6 tasks under prompt_mode="no_candidates":
- N1: test-conductivity var 0
- N2: test-conductivity var 460
- N3: test-conductivity var 160
- N4: test-conductivity var 230
- N5: melt var 4
- N6: boil var 2

Settings:
- prompt_mode="no_candidates"
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


def clean_info_dict(info: Any) -> Dict[str, Any]:
    if not isinstance(info, dict):
        return {"raw_info": str(info)}
    clean = {}
    for k, v in info.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            clean[k] = v
        elif isinstance(v, (list, tuple)):
            clean[k] = [str(x) if not isinstance(x, (str, int, float, bool)) else x for x in v]
        elif isinstance(v, dict):
            clean[k] = {str(dk): (str(dv) if not isinstance(dv, (str, int, float, bool)) else dv) for dk, dv in v.items()}
        else:
            clean[k] = str(v)
    return clean


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
        max_new_tokens=256,
        prompt_mode="no_candidates"
    )

    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    initial_score = env.get_score()
    initial_candidates = agent._filter_candidate_actions(valid_actions, task_desc, obs)

    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []

    total_prompt_tokens = 0
    total_completion_tokens = 0
    adapter_modified_count = 0
    parse_failures_count = 0
    env_exceptions_count = 0
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
            parse_failures_count += 1
            anomaly_notes.append(f"Step {step_num}: empty or non-string action, terminating episode.")
            termination_reason = "parse_exception_empty_or_non_string"
            failure_type = "parsing_failure"
            step_record = {
                "step": step_num,
                "system_prompt": telem.get("system_prompt", ""),
                "user_prompt": telem.get("user_prompt", ""),
                "prompt_mode": "no_candidates",
                "raw_response": stats.get("raw_text", ""),
                "raw_response_first_attempt": stats.get("raw_text_first_attempt", None),
                "parsed_response": telem.get("parsed_response", {}),
                "thought": thought,
                "proposed_action": telem.get("proposed_action", ""),
                "executed_action": None,
                "adapter_modified": True,
                "adapter_reason": telem.get("adapter_reason", ""),
                "candidate_actions": telem.get("candidate_actions", []),
                "history_mode": "all_steps",
                "observation": obs,
                "next_observation": None,
                "reward": 0.0,
                "score": final_score,
                "done": True,
                "info": clean_info_dict(info),
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "latency_s": stats.get("latency_s", 0.0),
                "model_calls_in_step": stats.get("calls_used", 1),
                "parse_retry_occurred": stats.get("attempts", 1) > 1,
                "actual_generation_params": stats.get("actual_generation_params", {}),
                "peak_vram_gib": stats.get("peak_vram_gib", 0.0),
                "model_call_index": llm.total_calls
            }
            steps_log.append(step_record)
            break

        # Step environment directly with action (native pass-through)
        try:
            next_obs, reward, done, step_info, next_valid_actions = env.step(action)
            current_score = env.get_score()
            clean_info = clean_info_dict(step_info)
        except Exception as e:
            env_exceptions_count += 1
            termination_reason = f"env_exception_{type(e).__name__}"
            failure_type = "environment_exception"
            anomaly_notes.append(f"Step {step_num}: environment exception {str(e)}")
            break

        step_record = {
            "step": step_num,
            "system_prompt": telem.get("system_prompt", ""),
            "user_prompt": telem.get("user_prompt", ""),
            "prompt_mode": "no_candidates",
            "raw_response": stats.get("raw_text", ""),
            "raw_response_first_attempt": stats.get("raw_text_first_attempt", None),
            "parsed_response": telem.get("parsed_response", {}),
            "thought": thought,
            "proposed_action": telem.get("proposed_action", ""),
            "executed_action": action,
            "adapter_modified": telem.get("adapter_modified", False),
            "adapter_reason": telem.get("adapter_reason", ""),
            "candidate_actions": telem.get("candidate_actions", []),
            "history_mode": "all_steps",
            "observation": obs,
            "next_observation": next_obs,
            "reward": reward,
            "score": current_score,
            "done": done,
            "info": clean_info,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "latency_s": stats.get("latency_s", 0.0),
            "model_calls_in_step": stats.get("calls_used", 1),
            "parse_retry_occurred": stats.get("attempts", 1) > 1,
            "actual_generation_params": stats.get("actual_generation_params", {}),
            "peak_vram_gib": stats.get("peak_vram_gib", 0.0),
            "model_call_index": llm.total_calls
        }
        steps_log.append(step_record)
        history.append((action, next_obs))
        obs = next_obs
        valid_actions = next_valid_actions
        info = step_info
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
        "prompt_mode": "no_candidates",
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
        "parse_failures_count": parse_failures_count,
        "env_exceptions_count": env_exceptions_count,
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
    c_dir = os.path.join(os.path.dirname(out_dir), "qwen3_precheck")

    print("=" * 70)
    print("STARTING QWEN3-14B-AWQ NO-CANDIDATES DIAGNOSTIC (N1 - N6)")
    print("=" * 70)

    # 1. Initialize fresh Qwen3AWQClient
    print("[1/3] Loading Qwen3-14B-AWQ model in a fresh process...")
    t0_load = time.time()
    try:
        llm = Qwen3AWQClient(model_path="/models/Qwen3-14B-AWQ")
        live_meta = llm.get_model_metadata()
    except Exception as e:
        print(f"CRITICAL: Model loading failed with exception: {e}")
        sys.exit(1)

    load_duration = round(time.time() - t0_load, 2)
    print(f"Model loaded in {load_duration}s.")

    # Save live model metadata
    meta_path = os.path.join(out_dir, "live_model_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(live_meta, f, indent=2)
    print(f"Saved metadata to {meta_path}")

    # 2. Six Environment Tasks
    print("\n[2/3] Running 6 no-candidates diagnosis tasks (N1 - N6)...")
    tasks_config = [
        ("N1", "test-conductivity", 0, "N1_conductivity_var0.json", "C1_conductivity_var0.json"),
        ("N2", "test-conductivity", 460, "N2_conductivity_var460.json", "C2_conductivity_var460.json"),
        ("N3", "test-conductivity", 160, "N3_conductivity_var160.json", "C3_conductivity_var160.json"),
        ("N4", "test-conductivity", 230, "N4_conductivity_var230.json", "C4_conductivity_var230.json"),
        ("N5", "melt", 4, "N5_melt_var4.json", "C5_melt_var4.json"),
        ("N6", "boil", 2, "N6_boil_var2.json", "C6_boil_var2.json"),
    ]

    env = ScienceWorldWrapper(step_limit=30)
    summary_rows = []
    initial_checks = []
    all_runs_data: Dict[str, Dict[str, Any]] = {}
    total_batch_calls_limit = 400

    for run_id, task_name, var, json_name, c_json_name in tasks_config:
        remaining_calls = total_batch_calls_limit - llm.total_calls
        if remaining_calls <= 0:
            print(f"Reached batch call limit of {total_batch_calls_limit}. Stopping before {run_id}.")
            break

        print(f"\n>>> Running {run_id}: task={task_name} var={var} (no_candidates)...")
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
        all_runs_data[run_id] = ep_data

        indiv_path = os.path.join(out_dir, json_name)
        with open(indiv_path, "w", encoding="utf-8") as f:
            json.dump(ep_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved individual JSON: {indiv_path}")

        # Check initial state against corresponding C run
        c_path = os.path.join(c_dir, c_json_name)
        c_data = {}
        if os.path.exists(c_path):
            with open(c_path, "r", encoding="utf-8") as fp:
                c_data = json.load(fp)

        init_desc_match = (ep_data["initial_task_desc"] == c_data.get("initial_task_desc"))
        init_obs_match = (ep_data["initial_observation"] == c_data.get("initial_observation"))
        init_score_match = (ep_data["initial_score"] == c_data.get("initial_score"))

        initial_checks.append({
            "N_run_id": run_id,
            "C_run_id": c_data.get("run_id", "C?"),
            "task_name": task_name,
            "variation": var,
            "initial_task_desc_match": init_desc_match,
            "initial_obs_match": init_obs_match,
            "initial_score_match": init_score_match,
            "all_initial_matched": (init_desc_match and init_obs_match and init_score_match)
        })

        summary_rows.append({
            "task_id": run_id.replace("N", "Task_"),
            "task_name": ep_data["task_name"],
            "variation": ep_data["variation"],
            "C_run_id": c_data.get("run_id", ""),
            "C_score": c_data.get("final_score", ""),
            "C_success": c_data.get("success", ""),
            "C_steps": c_data.get("steps_taken", ""),
            "C_model_calls": c_data.get("model_calls", ""),
            "N_run_id": ep_data["run_id"],
            "N_prompt_mode": ep_data["prompt_mode"],
            "N_score": ep_data["final_score"],
            "N_success": ep_data["success"],
            "N_steps": ep_data["steps_taken"],
            "N_model_calls": ep_data["model_calls"],
            "N_input_tokens": ep_data["total_input_tokens"],
            "N_output_tokens": ep_data["total_output_tokens"],
            "N_parse_failures": ep_data["parse_failures_count"],
            "N_env_exceptions": ep_data["env_exceptions_count"],
            "N_failure_type": ep_data["failure_type"],
            "N_termination_reason": ep_data["termination_reason"],
            "N_first_success_step": ep_data["first_success_step"] if ep_data["first_success_step"] is not None else "",
            "N_score_at_step_10": ep_data["score_at_step_10"] if ep_data["score_at_step_10"] is not None else "",
            "N_score_at_step_20": ep_data["score_at_step_20"] if ep_data["score_at_step_20"] is not None else "",
            "N_score_at_step_30": ep_data["score_at_step_30"] if ep_data["score_at_step_30"] is not None else ""
        })

        print(f"    Finished {run_id}: score={ep_data['final_score']}, success={ep_data['success']}, steps={ep_data['steps_taken']}, failure_type={ep_data['failure_type']}, termination={ep_data['termination_reason']}, calls={ep_data['model_calls']}")

    env.close()

    # Save summary.csv
    csv_path = os.path.join(out_dir, "summary.csv")
    fieldnames = list(summary_rows[0].keys()) if summary_rows else []
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)
    print(f"\nSaved summary CSV: {csv_path}")

    # Save initial_state_check.json
    init_check_path = os.path.join(out_dir, "initial_state_check.json")
    with open(init_check_path, "w", encoding="utf-8") as f:
        json.dump(initial_checks, f, indent=2)
    print(f"Saved initial state check to {init_check_path}")

    # 3. Evaluate Qualification Threshold
    print("\n[3/3] Evaluating qualification threshold...")
    num_success = sum(1 for r in summary_rows if r["N_success"] is True)
    melt_or_boil_success = any(r["N_success"] is True for r in summary_rows if r["task_name"] in ("melt", "boil"))

    print(f"Total successes: {num_success} / {len(summary_rows)}")
    print(f"Melt or boil success: {melt_or_boil_success}")

    threshold_met = (num_success >= 4 and melt_or_boil_success)
    if threshold_met:
        decision_tag = "DEVELOPMENT_SIGNAL_PENDING_VALIDATION"
    else:
        decision_tag = "LOCAL_BASELINE_QUALIFICATION_FAILED"

    print(f"\nDecision Tag: {decision_tag}")

    outcome_record = {
        "decision_tag": decision_tag,
        "threshold_rule": ">= 4/6 tasks succeed AND at least one of melt or boil succeeds",
        "num_success": num_success,
        "total_tasks": len(summary_rows),
        "melt_or_boil_success": melt_or_boil_success,
        "total_model_calls": llm.total_calls,
        "threshold_met": threshold_met
    }
    with open(os.path.join(out_dir, "qualification_outcome.json"), "w", encoding="utf-8") as f:
        json.dump(outcome_record, f, indent=2)

    print("\n" + "=" * 70)
    print("QWEN3 NO-CANDIDATES DIAGNOSTIC COMPLETED")
    print(f"Total model calls used: {llm.total_calls} (limit: {total_batch_calls_limit})")
    print("=" * 70)


if __name__ == "__main__":
    main()
