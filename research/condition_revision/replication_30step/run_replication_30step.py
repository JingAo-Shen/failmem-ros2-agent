"""
Strict Adapter 30-Step Horizon Experiment on Known Cases (T1 & T4)
Runs exactly 4 episodes:
- R5: test-conductivity var 460, strict adapter, Input A (extra_context = "")
- R6: test-conductivity var 460, strict adapter, Input B (extra_context from attribution_results.json T1-B)
- R7: test-conductivity var 160, strict adapter, Input A (extra_context = "")
- R8: test-conductivity var 160, strict adapter, Input B (extra_context from attribution_results.json T4-B)

Parameters:
- step_limit = 30 (envStepLimit=30, loop limit=30)
- Model: Qwen2.5-Coder-7B-Instruct (greedy decoding, do_sample=False, temperature=0.0, max_new_tokens=128)
- Model calls counted via LLMClient.total_calls difference
- Early termination on score >= 100.0 or done == True
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


def run_single_episode_30step(
    run_id: str,
    task_name: str,
    variation: int,
    task_id: str,
    adapter_mode: str,
    memory_condition: str,
    extra_context: str,
    env: ScienceWorldWrapper,
    llm: LLMClient,
    step_limit: int = 30
) -> Dict[str, Any]:
    calls_before = llm.total_calls
    agent = BaseAgent(llm, adapter_mode=adapter_mode)

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
            anomaly_notes.append(f"Step {step_num}: look around unavailable in strict mode, terminating episode.")
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
                "output_tokens": out_tok,
                "model_call_index": llm.total_calls
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
        "adapter_mode": adapter_mode,
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
        "code_version": "d7138de",
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


def compare_with_historical_r3_r4(r5_data: Dict[str, Any], r6_data: Dict[str, Any], base_dir: str) -> Dict[str, Any]:
    hist_path = os.path.join(base_dir, "replication_t1", "replication_t1_runs.json")
    if not os.path.exists(hist_path):
        return {"error": "replication_t1_runs.json not found"}

    with open(hist_path, "r", encoding="utf-8") as f:
        hist_data = json.load(f)

    r3_steps = next(r["steps"] for r in hist_data["runs"] if r["run_id"] == "R3")
    r4_steps = next(r["steps"] for r in hist_data["runs"] if r["run_id"] == "R4")

    # Compare R5 vs R3 for steps 1-10
    r5_vs_r3 = []
    min_len_r5 = min(len(r5_data["steps"]), len(r3_steps), 10)
    r5_r3_all_match = (len(r5_data["steps"]) >= min_len_r5)
    for i in range(min_len_r5):
        s5 = r5_data["steps"][i]
        s3 = r3_steps[i]
        prop_match = (s5["proposed_action"] == s3["proposed_action"])
        exec_match = (s5["executed_action"] == s3["executed_action"])
        score_match = (s5["score"] == s3["score"])
        all_m = prop_match and exec_match and score_match
        if not all_m:
            r5_r3_all_match = False
        r5_vs_r3.append({
            "step": i + 1,
            "r5_proposed": s5["proposed_action"],
            "r3_proposed": s3["proposed_action"],
            "r5_executed": s5["executed_action"],
            "r3_executed": s3["executed_action"],
            "r5_score": s5["score"],
            "r3_score": s3["score"],
            "all_match": all_m
        })

    # Compare R6 vs R4 for steps 1-10
    r6_vs_r4 = []
    min_len_r6 = min(len(r6_data["steps"]), len(r4_steps), 10)
    r6_r4_all_match = (len(r6_data["steps"]) >= min_len_r6)
    for i in range(min_len_r6):
        s6 = r6_data["steps"][i]
        s4 = r4_steps[i]
        prop_match = (s6["proposed_action"] == s4["proposed_action"])
        exec_match = (s6["executed_action"] == s4["executed_action"])
        score_match = (s6["score"] == s4["score"])
        all_m = prop_match and exec_match and score_match
        if not all_m:
            r6_r4_all_match = False
        r6_vs_r4.append({
            "step": i + 1,
            "r6_proposed": s6["proposed_action"],
            "r4_proposed": s4["proposed_action"],
            "r6_executed": s6["executed_action"],
            "r4_executed": s4["executed_action"],
            "r6_score": s6["score"],
            "r4_score": s4["score"],
            "all_match": all_m
        })

    return {
        "r5_vs_r3_first_10_steps_identical": r5_r3_all_match,
        "r6_vs_r4_first_10_steps_identical": r6_r4_all_match,
        "r5_vs_r3_details": r5_vs_r3,
        "r6_vs_r4_details": r6_vs_r4
    }


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    t1_b_context = get_historical_context("T1_conductivity_paper_clip_workshop")
    t4_b_context = get_historical_context("T4_conductivity_book_workshop")

    print("=" * 70)
    print("STARTING 30-STEP STRICT ADAPTER EXPERIMENT ON T1 & T4 (R5 - R8)")
    print("Model: Qwen2.5-Coder-7B-Instruct (greedy, do_sample=False, temperature=0.0)")
    print("Horizon limit: 30 steps (envStepLimit=30, loop=30)")
    print("Adapter mode: strict")
    print("=" * 70)

    # Initialize environment with step_limit=30
    env = ScienceWorldWrapper(step_limit=30)
    llm = LLMClient.get_instance()

    runs_config = [
        ("R5", "test-conductivity", 460, "T1_conductivity_paper_clip_workshop", "strict", "A", ""),
        ("R6", "test-conductivity", 460, "T1_conductivity_paper_clip_workshop", "strict", "B", t1_b_context),
        ("R7", "test-conductivity", 160, "T4_conductivity_book_workshop", "strict", "A", ""),
        ("R8", "test-conductivity", 160, "T4_conductivity_book_workshop", "strict", "B", t4_b_context),
    ]

    all_runs_data: Dict[str, Dict[str, Any]] = {}
    summary_rows = []

    for run_id, task_name, var, task_id, adapter_mode, mem_cond, extra_ctx in runs_config:
        print(f"\n>>> Running {run_id}: task={task_name} var={var} (id={task_id}), adapter={adapter_mode}, memory={mem_cond}...")
        ep_data = run_single_episode_30step(
            run_id=run_id,
            task_name=task_name,
            variation=var,
            task_id=task_id,
            adapter_mode=adapter_mode,
            memory_condition=mem_cond,
            extra_context=extra_ctx,
            env=env,
            llm=llm,
            step_limit=30
        )
        all_runs_data[run_id] = ep_data

        # Save individual JSON
        indiv_json_path = os.path.join(out_dir, f"{run_id}_{adapter_mode}_{mem_cond}_var{var}.json")
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

    # Initial state checks
    # Book task initial state consistency (R7 vs R8)
    r7_init = all_runs_data["R7"]
    r8_init = all_runs_data["R8"]
    book_initial_consistent = (
        r7_init["initial_task_desc"] == r8_init["initial_task_desc"] and
        r7_init["initial_observation"] == r8_init["initial_observation"] and
        r7_init["initial_candidate_actions"] == r8_init["initial_candidate_actions"] and
        r7_init["initial_score"] == r8_init["initial_score"]
    )
    print(f"\nBook task (R7 vs R8) initial state consistent: {book_initial_consistent}")

    # Paper clip task initial state consistency (R5 vs R6)
    r5_init = all_runs_data["R5"]
    r6_init = all_runs_data["R6"]
    paperclip_initial_consistent = (
        r5_init["initial_task_desc"] == r6_init["initial_task_desc"] and
        r5_init["initial_observation"] == r6_init["initial_observation"] and
        r5_init["initial_candidate_actions"] == r6_init["initial_candidate_actions"] and
        r5_init["initial_score"] == r6_init["initial_score"]
    )
    print(f"Paper clip task (R5 vs R6) initial state consistent: {paperclip_initial_consistent}")

    # Comparison with historical R3 and R4
    comp = compare_with_historical_r3_r4(r5_init, r6_init, base_dir)
    print(f"R5 vs R3 first 10 steps identical: {comp.get('r5_vs_r3_first_10_steps_identical')}")
    print(f"R6 vs R4 first 10 steps identical: {comp.get('r6_vs_r4_first_10_steps_identical')}")

    comp_path = os.path.join(out_dir, "consistency_check.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump({
            "book_initial_state_consistent_r7_r8": book_initial_consistent,
            "paperclip_initial_state_consistent_r5_r6": paperclip_initial_consistent,
            "r5_vs_r3_comparison": comp
        }, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("ALL 4 EPISODES COMPLETED")
    print(f"Summary CSV: {csv_path}")
    print(f"Consistency check: {comp_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
