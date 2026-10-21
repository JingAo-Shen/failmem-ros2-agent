"""
Native Action Pass-Through Diagnostic Experiment (R11, R12, R13, R14)
Evaluates 4 episodes under adapter_mode="native" with 30-step horizon:
- R11: test-conductivity var 460 (paper clip), Input A (extra_context = "")
- R12: test-conductivity var 460 (paper clip), Input B (historical T1-B extra_context)
- R13: test-conductivity var 160 (book), Input A (extra_context = "")
- R14: test-conductivity var 160 (book), Input B (historical T4-B extra_context)

Rules for native mode:
- Strip leading/trailing whitespace, directly pass to env.step
- No candidate list filtering / permissions
- No synonym conversion, no alias conversion, no fuzzy matching, no look around fallback
- Raw env rejection feedback passed directly to history
- Early termination on score >= 100.0 or done == True
- Model calls counted via LLMClient.total_calls delta
"""

import os
import sys
import json
import csv
import time
from typing import Dict, Any, List, Tuple, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from agents.base_agent import BaseAgent


def get_historical_context(task_id: str) -> str:
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
        if r["task_id"] == task_id and r["condition"] == "B":
            return r["extra_context"]
    raise ValueError(f"Could not find {task_id} Condition B extra_context in attribution_results.json")


def run_native_episode(
    run_id: str,
    task_name: str,
    variation: int,
    task_id: str,
    memory_condition: str,
    extra_context: str,
    env: ScienceWorldWrapper,
    llm: LLMClient,
    step_limit: int = 30
) -> Dict[str, Any]:
    calls_before = llm.total_calls
    agent = BaseAgent(llm, adapter_mode="native")

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
    anomaly_notes = []

    score_at_10: Optional[float] = None
    score_at_20: Optional[float] = None
    score_at_30: Optional[float] = None

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
            anomaly_notes.append(f"Step {step_num}: empty or non-string action, terminating episode.")
            termination_reason = "parse_exception_empty_or_non_string"
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
                "proposed_action_in_candidate_list": telem.get("proposed_action_in_candidate_list", False),
                "executed_action_equals_trimmed_proposed": False,
                "observation": obs,
                "next_observation": None,
                "reward": 0.0,
                "score": final_score,
                "done": True,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "model_call_index": llm.total_calls
            }
            steps_log.append(step_record)
            break

        # Step environment directly with action (native pass-through)
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
            "proposed_action_in_candidate_list": telem.get("proposed_action_in_candidate_list", False),
            "executed_action_equals_trimmed_proposed": telem.get("executed_action_equals_trimmed_proposed", False),
            "observation": obs,
            "next_observation": next_obs,
            "reward": reward,
            "score": current_score,
            "done": done,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
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
            break
        elif done:
            termination_reason = "env_done"
            break

    calls_after = llm.total_calls
    model_calls = calls_after - calls_before
    duration = round(time.time() - t0, 2)
    success = (final_score >= 100.0)

    return {
        "run_id": run_id,
        "adapter_mode": "native",
        "memory_condition": memory_condition,
        "task_name": task_name,
        "variation": variation,
        "task_id": task_id,
        "extra_context": extra_context,
        "model_name": "Qwen2.5-Coder-7B-Instruct",
        "model_path": "/models/Qwen2.5-Coder-7B-Instruct",
        "decoding_config": {
            "do_sample": False,
            "temperature": 0.0,
            "max_new_tokens": 128
        },
        "code_version": "54b4742",
        "step_limit": step_limit,
        "initial_task_desc": task_desc,
        "initial_observation": steps_log[0]["observation"] if steps_log else obs,
        "initial_score": initial_score,
        "initial_candidate_actions": initial_candidates,
        "final_score": final_score,
        "success": success,
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

    t1_b_context = get_historical_context("T1_conductivity_paper_clip_workshop")
    t4_b_context = get_historical_context("T4_conductivity_book_workshop")

    print("=" * 70)
    print("STARTING NATIVE ACTION PASS-THROUGH DIAGNOSTIC EXPERIMENT (R11 - R14)")
    print("Model: Qwen2.5-Coder-7B-Instruct (greedy, do_sample=False, temperature=0.0)")
    print("Horizon: 30 steps (envStepLimit=30, loop=30)")
    print("Adapter mode: native (pass-through raw action)")
    print("=" * 70)

    env = ScienceWorldWrapper(step_limit=30)
    llm = LLMClient.get_instance()

    runs_config = [
        ("R11", "test-conductivity", 460, "T1_conductivity_paper_clip_workshop", "A", ""),
        ("R12", "test-conductivity", 460, "T1_conductivity_paper_clip_workshop", "B", t1_b_context),
        ("R13", "test-conductivity", 160, "T4_conductivity_book_workshop", "A", ""),
        ("R14", "test-conductivity", 160, "T4_conductivity_book_workshop", "B", t4_b_context),
    ]

    all_runs_data: Dict[str, Dict[str, Any]] = {}
    summary_rows = []

    for run_id, task_name, var, task_id, mem_cond, extra_ctx in runs_config:
        print(f"\n>>> Running {run_id}: task={task_name} var={var} (id={task_id}), memory={mem_cond}...")
        ep_data = run_native_episode(
            run_id=run_id,
            task_name=task_name,
            variation=var,
            task_id=task_id,
            memory_condition=mem_cond,
            extra_context=extra_ctx,
            env=env,
            llm=llm,
            step_limit=30
        )
        all_runs_data[run_id] = ep_data

        # Save individual JSON
        indiv_json_path = os.path.join(out_dir, f"{run_id}_native_{mem_cond}_var{var}.json")
        with open(indiv_json_path, "w", encoding="utf-8") as f:
            json.dump(ep_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved individual JSON: {indiv_json_path}")

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
            "termination_reason": ep_data["termination_reason"],
            "first_success_step": ep_data["first_success_step"] if ep_data["first_success_step"] is not None else "",
            "score_at_step_10": ep_data["score_at_step_10"] if ep_data["score_at_step_10"] is not None else "",
            "score_at_step_20": ep_data["score_at_step_20"] if ep_data["score_at_step_20"] is not None else "",
            "score_at_step_30": ep_data["score_at_step_30"] if ep_data["score_at_step_30"] is not None else ""
        })

        print(f"    Finished {run_id}: score={ep_data['final_score']}, success={ep_data['success']}, steps={ep_data['steps_taken']}, first_succ={ep_data['first_success_step']}, termination={ep_data['termination_reason']}")

    env.close()

    # Save summary.csv
    csv_path = os.path.join(out_dir, "summary.csv")
    fieldnames = [
        "run_id", "adapter_mode", "memory_condition", "score", "success",
        "steps", "adapter_modified_count", "model_calls", "input_tokens",
        "output_tokens", "termination_reason", "first_success_step",
        "score_at_step_10", "score_at_step_20", "score_at_step_30"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)

    # Check initial state consistency for paper clip (R11 vs R12)
    r11_init = all_runs_data["R11"]
    r12_init = all_runs_data["R12"]
    paperclip_initial_consistent = (
        r11_init["initial_task_desc"] == r12_init["initial_task_desc"] and
        r11_init["initial_observation"] == r12_init["initial_observation"] and
        r11_init["initial_candidate_actions"] == r12_init["initial_candidate_actions"] and
        r11_init["initial_score"] == r12_init["initial_score"]
    )
    print(f"\nPaper clip task (R11 vs R12) initial state consistent: {paperclip_initial_consistent}")

    # Check initial state consistency for book (R13 vs R14)
    r13_init = all_runs_data["R13"]
    r14_init = all_runs_data["R14"]
    book_initial_consistent = (
        r13_init["initial_task_desc"] == r14_init["initial_task_desc"] and
        r13_init["initial_observation"] == r14_init["initial_observation"] and
        r13_init["initial_candidate_actions"] == r14_init["initial_candidate_actions"] and
        r13_init["initial_score"] == r14_init["initial_score"]
    )
    print(f"Book task (R13 vs R14) initial state consistent: {book_initial_consistent}")

    print("\n" + "=" * 70)
    print("NATIVE ACTION PASS-THROUGH DIAGNOSIS COMPLETED")
    print(f"Summary CSV: {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
