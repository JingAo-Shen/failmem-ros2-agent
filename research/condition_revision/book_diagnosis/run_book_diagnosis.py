"""
Book Name Entity Diagnostic Experiment (P1, P2, R9, R10)
Task: test-conductivity variation 160 (T4_conductivity_book_workshop)
envStepLimit = 30, horizon = 30 steps.

1. Probes:
   - P1: Direct env probe: 'teleport to workshop' -> 'focus on book (The Foundations of the Origin of Species)'
   - P2: Direct env probe: 'teleport to workshop' -> 'focus on book'
   Both bypass BaseAgent and adapter, 0 model calls.
   Gate: Only if P2 confirms successful focus on target book, proceed to R9/R10.

2. Model evaluations:
   - R9: strict_alias adapter, Input A (extra_context = "")
   - R10: strict_alias adapter, Input B (historical T4 Condition B extra_context)
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


def get_t4_condition_b_context() -> str:
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
        if r["task_id"] == "T4_conductivity_book_workshop" and r["condition"] == "B":
            return r["extra_context"]
    raise ValueError("Could not find T4 Condition B extra_context in attribution_results.json")


def run_probe(env: ScienceWorldWrapper, probe_id: str, second_action: str) -> Dict[str, Any]:
    obs0, task_desc, valids0, info0 = env.load_and_reset("test-conductivity", 160)
    score0 = env.get_score()

    # Step 1: teleport to workshop
    act1 = "teleport to workshop"
    in_valids1 = (act1.lower() in [v.lower() for v in valids0])
    obs1, rew1, done1, info1, valids1 = env.step(act1)
    score1 = env.get_score()

    # Step 2: send specified second action directly
    act2 = second_action
    in_valids2 = (act2.lower() in [v.lower() for v in valids1])
    obs2, rew2, done2, info2, valids2 = env.step(act2)
    score2 = env.get_score()

    # Verify focus success
    focus_confirmed = bool(score2 >= 60.0 and "focus" in obs2.lower() and "book" in obs2.lower())

    return {
        "probe_id": probe_id,
        "task_name": "test-conductivity",
        "variation": 160,
        "step_limit": 30,
        "initial_task_desc": task_desc,
        "initial_observation": obs0,
        "initial_score": score0,
        "final_score": score2,
        "focus_confirmed": focus_confirmed,
        "steps": [
            {
                "step": 1,
                "action": act1,
                "in_valid_actions": in_valids1,
                "observation": obs1,
                "reward": rew1,
                "score": score1,
                "done": done1
            },
            {
                "step": 2,
                "action": act2,
                "in_valid_actions": in_valids2,
                "observation": obs2,
                "reward": rew2,
                "score": score2,
                "done": done2
            }
        ]
    }


def run_model_episode(
    run_id: str,
    adapter_mode: str,
    memory_condition: str,
    extra_context: str,
    env: ScienceWorldWrapper,
    llm: LLMClient,
    step_limit: int = 30
) -> Dict[str, Any]:
    calls_before = llm.total_calls
    agent = BaseAgent(llm, adapter_mode=adapter_mode)

    obs, task_desc, valid_actions, info = env.load_and_reset("test-conductivity", 160)
    initial_score = env.get_score()
    initial_candidates = agent._filter_candidate_actions(valid_actions, task_desc, obs)

    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []

    total_prompt_tokens = 0
    total_completion_tokens = 0
    adapter_modified_count = 0
    alias_applied_count = 0
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
        if telem.get("alias_applied", False):
            alias_applied_count += 1

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
                "alias_applied": False,
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
            "alias_applied": telem.get("alias_applied", False),
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
        "task_name": "test-conductivity",
        "variation": 160,
        "task_id": "T4_conductivity_book_workshop",
        "extra_context": extra_context,
        "model_name": "Qwen2.5-Coder-7B-Instruct",
        "model_path": "/models/Qwen2.5-Coder-7B-Instruct",
        "decoding_config": {
            "do_sample": False,
            "temperature": 0.0,
            "max_new_tokens": 128
        },
        "code_version": "09d192c",
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
        "alias_applied_count": alias_applied_count,
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
    print("STARTING BOOK NAME DIAGNOSTIC EXPERIMENT (P1, P2, R9, R10)")
    print("Task: test-conductivity var 160 (T4_conductivity_book_workshop)")
    print("envStepLimit = 30")
    print("=" * 70)

    env = ScienceWorldWrapper(step_limit=30)

    # 1. Direct environment probes
    print("\n--- Phase 1: Direct Environment Probes ---")
    p1_data = run_probe(env, "P1", "focus on book (The Foundations of the Origin of Species)")
    print(f"Probe P1 completed: act2 in_valids={p1_data['steps'][1]['in_valid_actions']}, final_score={p1_data['final_score']}, focus_confirmed={p1_data['focus_confirmed']}")

    p2_data = run_probe(env, "P2", "focus on book")
    print(f"Probe P2 completed: act2 in_valids={p2_data['steps'][1]['in_valid_actions']}, final_score={p2_data['final_score']}, focus_confirmed={p2_data['focus_confirmed']}")

    # Save probe records
    probes_path = os.path.join(out_dir, "probes_p1_p2.json")
    with open(probes_path, "w", encoding="utf-8") as f:
        json.dump({"P1": p1_data, "P2": p2_data}, f, indent=2, ensure_ascii=False)
    print(f"Saved probe records to {probes_path}")

    # Check gate
    if not p2_data["focus_confirmed"]:
        print("\n[GATE FAILED] P2 native environment feedback did not confirm successful focus on target book. Stopping round.")
        env.close()
        return

    print("\n[GATE PASSED] P2 native environment feedback confirmed successful focus on target book. Proceeding to R9 and R10.")

    # 2. Model evaluations R9 and R10
    llm = LLMClient.get_instance()
    t4_b_context = get_t4_condition_b_context()

    summary_rows = []

    # Add P1 and P2 to summary rows
    summary_rows.append({
        "run_id": "P1",
        "adapter_mode": "direct_probe",
        "memory_condition": "none",
        "score": p1_data["final_score"],
        "success": False,
        "steps": 2,
        "adapter_modified_count": 0,
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "termination_reason": "probe_completed",
        "first_success_step": "",
        "score_at_step_10": "",
        "score_at_step_20": "",
        "score_at_step_30": ""
    })
    summary_rows.append({
        "run_id": "P2",
        "adapter_mode": "direct_probe",
        "memory_condition": "none",
        "score": p2_data["final_score"],
        "success": False,
        "steps": 2,
        "adapter_modified_count": 0,
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "termination_reason": "probe_completed",
        "first_success_step": "",
        "score_at_step_10": "",
        "score_at_step_20": "",
        "score_at_step_30": ""
    })

    model_runs_config = [
        ("R9", "strict_alias", "A", ""),
        ("R10", "strict_alias", "B", t4_b_context),
    ]

    model_runs_data = {}

    for run_id, adapter_mode, mem_cond, extra_ctx in model_runs_config:
        print(f"\n>>> Running {run_id}: adapter={adapter_mode}, memory={mem_cond}...")
        ep_data = run_model_episode(
            run_id=run_id,
            adapter_mode=adapter_mode,
            memory_condition=mem_cond,
            extra_context=extra_ctx,
            env=env,
            llm=llm,
            step_limit=30
        )
        model_runs_data[run_id] = ep_data

        indiv_path = os.path.join(out_dir, f"{run_id}_{adapter_mode}_{mem_cond}_var160.json")
        with open(indiv_path, "w", encoding="utf-8") as f:
            json.dump(ep_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved individual JSON: {indiv_path}")

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

        print(f"    Finished {run_id}: score={ep_data['final_score']}, success={ep_data['success']}, steps={ep_data['steps_taken']}, alias_mods={ep_data['alias_applied_count']}, first_succ={ep_data['first_success_step']}, termination={ep_data['termination_reason']}")

    env.close()

    # Initial state consistency check (R9 vs R10)
    r9_init = model_runs_data["R9"]
    r10_init = model_runs_data["R10"]
    model_init_consistent = (
        r9_init["initial_task_desc"] == r10_init["initial_task_desc"] and
        r9_init["initial_observation"] == r10_init["initial_observation"] and
        r9_init["initial_candidate_actions"] == r10_init["initial_candidate_actions"] and
        r9_init["initial_score"] == r10_init["initial_score"]
    )
    print(f"\nR9 vs R10 initial state consistent: {model_init_consistent}")

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

    print("\n" + "=" * 70)
    print("BOOK DIAGNOSTIC EXPERIMENT COMPLETED")
    print(f"Probes JSON: {probes_path}")
    print(f"Summary CSV: {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
