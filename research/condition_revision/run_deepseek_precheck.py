"""
DeepSeek Real Planner Admission Precheck Runner:
Executes:
1. Model metadata fetch from DeepSeek official endpoint.
2. Non-environment connectivity and format check (expecting {"ok"}).
3. Fixed 6 tasks (D1-D6) with native action pass-through, action_templates from env.get_action_templates(),
   all_steps history, and real-time conservative budget tracking (< $10.00 USD, < 400 calls).
4. Generates auditable artifacts: summary.csv, step_summary.csv, budget_ledger.json, consistency check vs C1-C6.
"""

import os
import sys
import json
import time
import csv
import random
import datetime
from typing import Dict, Any, List, Optional, Tuple
import requests

# Ensure project root in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from env_wrapper import ScienceWorldWrapper
from agents.base_agent import BaseAgent
from remote_llm_client import (
    RemoteLLMClient,
    RemotePlannerError,
    ConfigurationError,
    BudgetExceededError,
    PayloadSizeLimitExceededError
)
from condition_evaluator import extract_target_entity


OUTPUT_DIR = "/code/failmem-ros2-agent/research/condition_revision/deepseek_precheck"

TASK_SPECS = [
    {"run_id": "D1", "task_name": "test-conductivity", "variation": 0, "corresp_c": "C1"},
    {"run_id": "D2", "task_name": "test-conductivity", "variation": 460, "corresp_c": "C2"},
    {"run_id": "D3", "task_name": "test-conductivity", "variation": 160, "corresp_c": "C3"},
    {"run_id": "D4", "task_name": "test-conductivity", "variation": 230, "corresp_c": "C4"},
    {"run_id": "D5", "task_name": "melt", "variation": 4, "corresp_c": "C5"},
    {"run_id": "D6", "task_name": "boil", "variation": 2, "corresp_c": "C6"}
]


def fetch_official_model_metadata(api_key: str) -> Dict[str, Any]:
    """Fetches official model mapping and metadata from DeepSeek endpoint."""
    t_fetch = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        resp = requests.get(
            "https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0
        )
        if resp.status_code == 200:
            data = resp.json()
        else:
            data = {"error_http_status": resp.status_code, "text": resp.text}
    except Exception as e:
        data = {"error": str(e)}

    # Target version mapping
    metadata_record = {
        "fetch_timestamp_utc": t_fetch,
        "endpoint": "https://api.deepseek.com/models",
        "requested_model_id": "deepseek-flash",
        "target_version_stated": "DeepSeek-V4.1-Flash-1017",
        "official_models_response": data,
        "pricing_model_reference": "Official peak conservative: input_miss $0.55/M, input_hit $0.14/M, output $2.19/M"
    }
    return metadata_record


def run_non_environment_check(client: RemoteLLMClient) -> Dict[str, Any]:
    """
    Executes a non-environment connectivity and JSON format check.
    Expects response containing {"ok": ...}.
    """
    print("\n[DeepSeek Precheck] Running non-environment check...")
    user_prompt = "Output a JSON object with a single key 'ok' and value true: {\"ok\": true}"
    system_prompt = "You are an assistant. Output ONLY a valid JSON object."

    parsed, stats = client.generate_json(user_prompt, system_prompt=system_prompt)
    is_ok = ("ok" in parsed) and bool(parsed["ok"])
    
    check_result = {
        "check_passed": is_ok,
        "parsed_response": parsed,
        "stats": stats,
        "raw_text": stats.get("raw_text", ""),
        "attempts": stats.get("attempts", []),
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    print(f"  Non-environment check outcome: ok={is_ok}, calls={stats.get('calls')}, raw='{stats.get('raw_text')[:100]}'")
    return check_result


def set_local_seed(seed: int = 3407):
    """Sets local random seed without claiming control over remote model randomness."""
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass


def run_single_task(
    spec: Dict[str, Any],
    client: RemoteLLMClient,
    env: ScienceWorldWrapper,
    all_steps_rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    run_id = spec["run_id"]
    task_name = spec["task_name"]
    variation = spec["variation"]
    step_limit = 30

    print(f"\n==========================================")
    print(f"Starting Task {run_id}: {task_name} (variation {variation})")
    print(f"==========================================")

    set_local_seed(3407)

    # 1. Load and reset environment
    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    raw_templates = env.get_action_templates()
    if not raw_templates:
        raise RuntimeError("Environment get_action_templates() returned empty list!")

    target = extract_target_entity(task_desc)
    initial_score = float(env.get_score())
    initial_obs = str(obs)

    # 2. Instantiate BaseAgent with explicit environment action templates
    agent = BaseAgent(
        llm_client=client,
        adapter_mode="native",
        history_mode="all_steps",
        prompt_mode="action_templates",
        action_templates=raw_templates,
        max_new_tokens=None  # Client handles 8192
    )

    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []
    done = False
    final_score = initial_score
    termination_reason = "step_limit_30"
    first_success_step = None
    score_at_10 = None
    score_at_20 = None
    score_at_30 = None
    task_start_time = time.time()

    task_model_calls = 0
    task_input_tokens = 0
    task_output_tokens = 0
    has_unknown_tokens = False

    for step_num in range(1, step_limit + 1):
        step_t0 = time.time()
        print(f"--- {run_id} Step {step_num}/{step_limit} ---")

        # Select action
        action, thought, step_stats, telemetry = agent.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions,
            extra_context="",
            action_templates=raw_templates
        )

        step_calls = step_stats.get("calls", 1)
        task_model_calls += step_calls

        in_tok = step_stats.get("input_tokens", 0)
        out_tok = step_stats.get("output_tokens", 0)
        if isinstance(in_tok, int) and isinstance(out_tok, int) and not has_unknown_tokens:
            task_input_tokens += in_tok
            task_output_tokens += out_tok
        else:
            has_unknown_tokens = True

        proposed_act = telemetry.get("proposed_action", "")
        executed_act = action if action is not None else "None"
        adapter_modified = telemetry.get("adapter_modified", False)
        adapter_reason = telemetry.get("adapter_reason", "")
        retry_attempted = step_stats.get("retry_attempted", False)
        parse_error = telemetry.get("parsed_response", {}).get("parse_error", False)

        # Execute in environment if not terminated immediately
        reward = 0.0
        next_obs = ""
        truncation_error = False
        transport_error = False

        if action is None:
            # Terminate immediately on empty/invalid proposed action under native mode
            termination_reason = "empty_or_non_string_terminate"
            done = True
            next_obs = "TERMINATED: Empty or non-string action proposed by model."
        else:
            next_obs, reward, done, info, next_valid_actions = env.step(action)
            valid_actions = next_valid_actions
            history.append((action, next_obs))

        final_score = float(env.get_score())
        step_dt = time.time() - step_t0

        if step_num == 10:
            score_at_10 = final_score
        elif step_num == 20:
            score_at_20 = final_score
        elif step_num == 30:
            score_at_30 = final_score

        if final_score >= 100.0 and first_success_step is None:
            first_success_step = step_num
            termination_reason = "success_100"
            done = True

        step_data = {
            "step": step_num,
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

        # Record row for step_summary.csv
        step_row = {
            "run_id": run_id,
            "task_name": task_name,
            "variation": variation,
            "step": step_num,
            "proposed_action": proposed_act,
            "executed_action": executed_act,
            "adapter_modified": adapter_modified,
            "adapter_reason": adapter_reason,
            "env_obs": next_obs.replace("\n", " ")[:150],
            "reward": reward,
            "score": final_score,
            "done": done,
            "model_calls_this_step": step_calls,
            "retry_attempted": retry_attempted,
            "truncation_error": truncation_error,
            "parse_error": parse_error,
            "transport_error": transport_error,
            "latency_s": round(step_dt, 3),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "client_known_cost_usd": client.known_cost_usd
        }
        all_steps_rows.append(step_row)

        print(f"  Action: '{executed_act}', Reward: {reward}, Score: {final_score}, Done: {done}")
        print(f"  Obs snippet: {next_obs.strip()[:100]}")

        if done:
            if final_score >= 100.0:
                termination_reason = "success_100"
            elif reward < 0:
                termination_reason = "fatal_penalty"
            elif termination_reason == "step_limit_30":
                termination_reason = "env_done"
            break

        obs = next_obs

    task_duration = time.time() - task_start_time
    is_success = (final_score >= 100.0)

    task_result = {
        "run_id": run_id,
        "task_name": task_name,
        "variation": variation,
        "target_entity": target,
        "step_limit": step_limit,
        "seed": 3407,
        "initial_task_desc": task_desc,
        "initial_observation": initial_obs,
        "initial_score": initial_score,
        "initial_action_templates": raw_templates,
        "final_score": final_score,
        "success": is_success,
        "steps_taken": len(steps_log),
        "termination_reason": termination_reason,
        "first_success_step": first_success_step,
        "score_at_step_10": score_at_10,
        "score_at_step_20": score_at_20,
        "score_at_step_30": score_at_30,
        "task_model_calls": task_model_calls,
        "task_input_tokens": task_input_tokens if not has_unknown_tokens else "unknown",
        "task_output_tokens": task_output_tokens if not has_unknown_tokens else "unknown",
        "duration_seconds": round(task_duration, 2),
        "steps": steps_log
    }

    print(f"\nTask {run_id} finished in {len(steps_log)} steps. Final Score={final_score}, Success={is_success}, Reason={termination_reason}")
    return task_result


def check_consistency_vs_c1_c6(task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compares initial task description, observation, and score against baseline C1-C6."""
    comparison = {}
    c_dir = "/code/failmem-ros2-agent/research/condition_revision/qwen3_precheck"

    for t in task_results:
        run_id = t["run_id"]
        # Find corresponding C run
        c_id = "C" + run_id[1:]
        c_path = os.path.join(c_dir, f"{c_id}_{t['task_name'].replace('-', '_')}_var{t['variation']}.json")
        if not os.path.exists(c_path):
            # Try matching by c_id in filename
            import glob
            matches = glob.glob(os.path.join(c_dir, f"{c_id}_*.json"))
            c_path = matches[0] if matches else None

        if c_path and os.path.exists(c_path):
            with open(c_path, "r", encoding="utf-8") as f:
                c_data = json.load(f)
            
            desc_match = (t["initial_task_desc"].strip() == c_data.get("initial_task_desc", "").strip())
            obs_match = (t["initial_observation"].strip() == c_data.get("initial_observation", "").strip())
            score_match = (t["initial_score"] == c_data.get("initial_score"))

            comparison[run_id] = {
                "corresp_c_id": c_id,
                "task_name": t["task_name"],
                "variation": t["variation"],
                "desc_match": desc_match,
                "obs_match": obs_match,
                "initial_score_match": score_match,
                "all_initial_conditions_identical": (desc_match and obs_match and score_match)
            }
        else:
            comparison[run_id] = {
                "corresp_c_id": c_id,
                "error": f"C baseline file not found: {c_path}"
            }
    return comparison


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 60)
    print("DeepSeek Real Planner Admission Precheck (D1 - D6)")
    print("=" * 60)

    # 1. Initialize client with explicit live network configuration
    client = RemoteLLMClient(
        endpoint="https://api.deepseek.com/chat/completions",
        model_id="deepseek-flash",
        api_key_env_var="DEEPSEEK_API_KEY",
        timeout=180.0,
        allow_live_network=True,
        max_budget_usd=10.00,
        max_attempts=400,
        generation_params={
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
            "max_tokens": 8192,
            "stream": False
        }
    )

    api_key = client._get_api_key()
    if not api_key:
        print("[FATAL] DEEPSEEK_API_KEY not found in environment or ~/.bashrc. Aborting.")
        sys.exit(1)

    # 2. Fetch official model metadata
    model_metadata = fetch_official_model_metadata(api_key)
    meta_path = os.path.join(OUTPUT_DIR, "model_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(model_metadata, f, indent=2, ensure_ascii=False)
    print(f"[DeepSeek Precheck] Saved model metadata to {meta_path}")

    # 3. Non-environment check
    non_env_result = run_non_environment_check(client)
    non_env_path = os.path.join(OUTPUT_DIR, "non_environment_check.json")
    with open(non_env_path, "w", encoding="utf-8") as f:
        json.dump(non_env_result, f, indent=2, ensure_ascii=False)

    if not non_env_result["check_passed"]:
        print("[FATAL] Non-environment check failed! Technical blocker encountered. Aborting.")
        sys.exit(1)

    # 4. Run D1 - D6 tasks
    env = ScienceWorldWrapper(step_limit=30)
    task_results = []
    all_steps_rows: List[Dict[str, Any]] = []

    success_count = 0
    melt_boil_success = False

    try:
        for spec in TASK_SPECS:
            res = run_single_task(spec, client, env, all_steps_rows)
            task_results.append(res)
            
            # Save individual task JSON
            task_filename = f"{spec['run_id']}_{spec['task_name'].replace('-', '_')}_var{spec['variation']}.json"
            task_filepath = os.path.join(OUTPUT_DIR, task_filename)
            with open(task_filepath, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)

            if res["success"]:
                success_count += 1
                if spec["task_name"] in ("melt", "boil"):
                    melt_boil_success = True

    finally:
        env.close()

    # 5. Consistency check vs C1-C6
    consistency = check_consistency_vs_c1_c6(task_results)
    const_path = os.path.join(OUTPUT_DIR, "consistency_check_vs_c1_c6.json")
    with open(const_path, "w", encoding="utf-8") as f:
        json.dump(consistency, f, indent=2, ensure_ascii=False)
    print(f"[DeepSeek Precheck] Saved C1-C6 consistency check to {const_path}")

    # 6. Save summary.csv
    summary_path = os.path.join(OUTPUT_DIR, "summary.csv")
    fieldnames = [
        "run_id", "task_name", "variation", "score", "success", "failure_type",
        "steps", "adapter_modified_count", "model_calls", "input_tokens",
        "output_tokens", "total_tokens", "cost_usd", "termination_reason",
        "first_success_step", "score_at_step_10", "score_at_step_20", "score_at_step_30"
    ]
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in task_results:
            tot_tok = t["task_input_tokens"] + t["task_output_tokens"] if (isinstance(t["task_input_tokens"], int) and isinstance(t["task_output_tokens"], int)) else "unknown"
            writer.writerow({
                "run_id": t["run_id"],
                "task_name": t["task_name"],
                "variation": t["variation"],
                "score": t["final_score"],
                "success": t["success"],
                "failure_type": "none" if t["success"] else "task_failure",
                "steps": t["steps_taken"],
                "adapter_modified_count": sum(1 for s in t["steps"] if s["adapter_modified"]),
                "model_calls": t["task_model_calls"],
                "input_tokens": t["task_input_tokens"],
                "output_tokens": t["task_output_tokens"],
                "total_tokens": tot_tok,
                "cost_usd": "see_ledger",
                "termination_reason": t["termination_reason"],
                "first_success_step": t["first_success_step"],
                "score_at_step_10": t["score_at_step_10"],
                "score_at_step_20": t["score_at_step_20"],
                "score_at_step_30": t["score_at_step_30"]
            })
    print(f"[DeepSeek Precheck] Saved summary.csv to {summary_path}")

    # 7. Save step_summary.csv
    step_summary_path = os.path.join(OUTPUT_DIR, "step_summary.csv")
    if all_steps_rows:
        step_fieldnames = list(all_steps_rows[0].keys())
        with open(step_summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=step_fieldnames)
            writer.writeheader()
            for r in all_steps_rows:
                writer.writerow(r)
    print(f"[DeepSeek Precheck] Saved step_summary.csv to {step_summary_path}")

    # 8. Save budget ledger
    budget_ledger = client.get_budget_ledger()
    ledger_path = os.path.join(OUTPUT_DIR, "budget_ledger.json")
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(budget_ledger, f, indent=2)
    print(f"[DeepSeek Precheck] Saved budget_ledger.json to {ledger_path}")

    # 9. Evaluate admission gate
    gate_passed = (success_count >= 4) and melt_boil_success
    if len(task_results) == 6:
        verdict = "REMOTE_PLANNER_DEVELOPMENT_GATE_PASSED" if gate_passed else "REMOTE_PLANNER_ADMISSION_FAILED"
    else:
        verdict = "REMOTE_PLANNER_CHECK_INCOMPLETE"

    print("\n" + "=" * 60)
    print(f"ADMISSION VERDICT: {verdict}")
    print(f"Success Count: {success_count}/6 | Melt/Boil Success: {melt_boil_success}")
    print(f"Total Model Calls: {client.total_calls} | Total Cost: ${client.known_cost_usd:.4f} USD")
    print("=" * 60)

    # Save verdict in execution notes
    exec_notes_path = os.path.join(OUTPUT_DIR, "execution_notes.md")
    with open(exec_notes_path, "w", encoding="utf-8") as f:
        f.write(f"# DeepSeek Real Planner Admission Precheck Execution Notes\n\n")
        f.write(f"- **Verdict**: `{verdict}`\n")
        f.write(f"- **Admission Threshold**: >= 4/6 tasks succeed and at least one of melt/boil succeeds.\n")
        f.write(f"- **Success Count**: {success_count}/6 (D1-D6)\n")
        f.write(f"- **Melt/Boil Success**: {melt_boil_success}\n")
        f.write(f"- **Total Model Requests**: {client.total_calls} (limit 400)\n")
        f.write(f"- **Total Known Cost**: ${client.known_cost_usd:.4f} USD (budget $10.00 USD)\n")
        f.write(f"- **Model**: `{client.model_id}` (Target: DeepSeek-V4.1-Flash-1017)\n")
        f.write(f"- **Prompt Mode**: `action_templates` (from ScienceWorldWrapper.get_action_templates())\n")
        f.write(f"- **Adapter Mode**: `native` (raw pass-through, whitespace trimmed)\n")
        f.write(f"- **Execution Timestamp**: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n")


if __name__ == "__main__":
    main()
