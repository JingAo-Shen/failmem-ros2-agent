"""
History Window Comparison Diagnostic Experiment (R15, R16, R17, R18)
Evaluates 4 episodes under adapter_mode="native" with 30-step horizon:
- R15: history_mode="last5", Input A (extra_context="")
- R16: history_mode="last5", Input B (verbatim T1-B extra_context)
- R17: history_mode="all_steps", Input A (extra_context="")
- R18: history_mode="all_steps", Input B (verbatim T1-B extra_context)

Constraints:
1. Verify live model object matches /models/Qwen2.5-Coder-7B-Instruct; halt if mismatch.
2. Record live model metadata (class, path, tokenizer, dtype, decode params).
3. Same process, same model instance across all 4 runs.
4. Native execution: model non-empty action stripped of leading/trailing whitespace only.
5. Reinitialize env each run, verify initial state consistency.
6. Compare steps 1-6 between R15/R17 and R16/R18.
7. Budget hard cap: max 4 episodes, 240 model calls.
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


def run_episode(
    run_id: str,
    task_name: str,
    variation: int,
    history_mode: str,
    memory_condition: str,
    extra_context: str,
    env: ScienceWorldWrapper,
    llm: LLMClient,
    live_model_metadata: Dict[str, Any],
    step_limit: int = 30,
    max_batch_calls_remaining: int = 240
) -> Dict[str, Any]:
    calls_before = llm.total_calls
    agent = BaseAgent(llm, adapter_mode="native", history_mode=history_mode)

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
        # Check budget limit
        calls_used_in_ep = llm.total_calls - calls_before
        if calls_used_in_ep >= max_batch_calls_remaining:
            termination_reason = "batch_call_limit_reached"
            anomaly_notes.append(f"Step {step_num}: reached maximum allocated calls for batch.")
            break

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
                "history_mode": history_mode,
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
            "history_mode": history_mode,
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
        "history_mode": history_mode,
        "memory_condition": memory_condition,
        "task_name": task_name,
        "variation": variation,
        "task_id": "T1_conductivity_paper_clip_workshop",
        "extra_context": extra_context,
        "live_model_metadata": live_model_metadata,
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


def compare_steps_1_to_6(run_x: Dict[str, Any], run_y: Dict[str, Any]) -> List[Dict[str, Any]]:
    comparison = []
    max_step = min(6, max(len(run_x["steps"]), len(run_y["steps"])))
    for s in range(1, max_step + 1):
        step_x = run_x["steps"][s - 1] if s <= len(run_x["steps"]) else None
        step_y = run_y["steps"][s - 1] if s <= len(run_y["steps"]) else None

        if step_x is None or step_y is None:
            comparison.append({
                "step": s,
                "both_steps_present": False,
                "prompt_identical": False,
                "proposed_action_identical": False,
                "executed_action_identical": False,
                "score_identical": False,
                "run_x_step_present": step_x is not None,
                "run_y_step_present": step_y is not None
            })
            continue

        prompt_match = (
            step_x["system_prompt"] == step_y["system_prompt"] and
            step_x["user_prompt"] == step_y["user_prompt"]
        )
        prop_act_match = (step_x["proposed_action"] == step_y["proposed_action"])
        exec_act_match = (step_x["executed_action"] == step_y["executed_action"])
        score_match = (step_x["score"] == step_y["score"])

        comparison.append({
            "step": s,
            "both_steps_present": True,
            "prompt_identical": prompt_match,
            "proposed_action_identical": prop_act_match,
            "executed_action_identical": exec_act_match,
            "score_identical": score_match,
            "run_x_action": step_x["executed_action"],
            "run_y_action": step_y["executed_action"],
            "run_x_score": step_x["score"],
            "run_y_score": step_y["score"]
        })
    return comparison


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 70)
    print("STARTING HISTORY WINDOW COMPARISON EXPERIMENT (R15 - R18)")
    print("=" * 70)

    # 1. Initialize LLM and verify live model metadata
    print("[1/5] Initializing LLMClient and verifying live model object...")
    llm = LLMClient.get_instance()
    live_meta = llm.get_model_metadata()

    print("Live Model Metadata:")
    for k, v in live_meta.items():
        print(f"  {k}: {v}")

    expected_model_path = "/models/Qwen2.5-Coder-7B-Instruct"
    actual_model_path = live_meta.get("model_config_name_or_path", "")
    if actual_model_path != expected_model_path:
        conflict_record = {
            "status": "STOPPED_MODEL_MISMATCH",
            "expected_model": expected_model_path,
            "actual_metadata": live_meta,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        conflict_file = os.path.join(out_dir, "model_conflict_record.json")
        with open(conflict_file, "w", encoding="utf-8") as f:
            json.dump(conflict_record, f, indent=2)
        print(f"\nCRITICAL ERROR: Model mismatch! Expected {expected_model_path}, but loaded {actual_model_path}.")
        print(f"Saved conflict record to {conflict_file}. Halting inference without running.")
        sys.exit(1)

    # Save live model metadata
    meta_path = os.path.join(out_dir, "live_model_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(live_meta, f, indent=2)
    print(f"Verified model object. Saved metadata to {meta_path}.")

    # 2. Load historical context
    t1_b_context = get_historical_context("T1_conductivity_paper_clip_workshop")

    # 3. Setup environment and runs
    env = ScienceWorldWrapper(step_limit=30)
    runs_config = [
        ("R15", "last5", "A", ""),
        ("R16", "last5", "B", t1_b_context),
        ("R17", "all_steps", "A", ""),
        ("R18", "all_steps", "B", t1_b_context),
    ]

    all_runs_data: Dict[str, Dict[str, Any]] = {}
    summary_rows = []
    total_batch_calls_limit = 240
    batch_calls_used = 0

    for run_id, hist_mode, mem_cond, extra_ctx in runs_config:
        remaining_calls = total_batch_calls_limit - batch_calls_used
        if remaining_calls <= 0:
            print(f"Reached batch call limit of {total_batch_calls_limit}. Stopping before {run_id}.")
            break

        print(f"\n>>> Running {run_id}: task=test-conductivity var=460, history_mode={hist_mode}, memory={mem_cond}...")
        ep_data = run_episode(
            run_id=run_id,
            task_name="test-conductivity",
            variation=460,
            history_mode=hist_mode,
            memory_condition=mem_cond,
            extra_context=extra_ctx,
            env=env,
            llm=llm,
            live_model_metadata=live_meta,
            step_limit=30,
            max_batch_calls_remaining=remaining_calls
        )
        all_runs_data[run_id] = ep_data
        batch_calls_used += ep_data["model_calls"]

        # Save individual JSON
        indiv_json_path = os.path.join(out_dir, f"{run_id}_{hist_mode}_{mem_cond}_var460.json")
        with open(indiv_json_path, "w", encoding="utf-8") as f:
            json.dump(ep_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved individual JSON: {indiv_json_path}")

        summary_rows.append({
            "run_id": ep_data["run_id"],
            "adapter_mode": ep_data["adapter_mode"],
            "history_mode": ep_data["history_mode"],
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

        print(f"    Finished {run_id}: score={ep_data['final_score']}, success={ep_data['success']}, steps={ep_data['steps_taken']}, termination={ep_data['termination_reason']}, calls={ep_data['model_calls']}")

    env.close()

    # 4. Save summary.csv
    csv_path = os.path.join(out_dir, "summary.csv")
    fieldnames = [
        "run_id", "adapter_mode", "history_mode", "memory_condition", "score", "success",
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

    # 5. Check initial state consistency across all four runs
    print("\n[5/5] Checking initial state consistency across R15-R18...")
    runs = list(all_runs_data.keys())
    ref = all_runs_data[runs[0]]
    initial_consistent = True
    for r in runs[1:]:
        curr = all_runs_data[r]
        desc_eq = (curr["initial_task_desc"] == ref["initial_task_desc"])
        obs_eq = (curr["initial_observation"] == ref["initial_observation"])
        cand_eq = (curr["initial_candidate_actions"] == ref["initial_candidate_actions"])
        score_eq = (curr["initial_score"] == ref["initial_score"])
        if not (desc_eq and obs_eq and cand_eq and score_eq):
            print(f"  Mismatch in initial state between {runs[0]} and {r}: desc={desc_eq}, obs={obs_eq}, cand={cand_eq}, score={score_eq}")
            initial_consistent = False
        else:
            print(f"  {runs[0]} vs {r} initial state: identical (True)")
    print(f"Overall initial state consistency across all runs: {initial_consistent}")

    # 6. Step 1-6 detailed comparison
    print("\nComparing Steps 1-6:")
    step_comp = {}
    if "R15" in all_runs_data and "R17" in all_runs_data:
        comp_15_17 = compare_steps_1_to_6(all_runs_data["R15"], all_runs_data["R17"])
        step_comp["R15_vs_R17"] = comp_15_17
        print("  R15 (last5, A) vs R17 (all_steps, A) steps 1-6:")
        for sc in comp_15_17:
            print(f"    Step {sc['step']}: prompt_match={sc.get('prompt_identical')}, act_match={sc.get('executed_action_identical')}, score_match={sc.get('score_identical')}")

    if "R16" in all_runs_data and "R18" in all_runs_data:
        comp_16_18 = compare_steps_1_to_6(all_runs_data["R16"], all_runs_data["R18"])
        step_comp["R16_vs_R18"] = comp_16_18
        print("  R16 (last5, B) vs R18 (all_steps, B) steps 1-6:")
        for sc in comp_16_18:
            print(f"    Step {sc['step']}: prompt_match={sc.get('prompt_identical')}, act_match={sc.get('executed_action_identical')}, score_match={sc.get('score_identical')}")

    comp_path = os.path.join(out_dir, "step1_6_comparison.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(step_comp, f, indent=2)
    print(f"Saved step 1-6 comparison to {comp_path}")

    print("\n" + "=" * 70)
    print("HISTORY WINDOW COMPARISON COMPLETED")
    print(f"Total batch calls used: {batch_calls_used} (limit: {total_batch_calls_limit})")
    print("=" * 70)


if __name__ == "__main__":
    main()
