"""
Failure Trajectory Transfer Benefit Attribution Experiment
Evaluates 8 frozen target tasks across 6 conditions (A, B, C, D, E, F):
- Condition A: No Memory (Zero-shot baseline)
- Condition B: Raw Failed Trajectory (Task-family matched)
- Condition C: Generic Syntax Interface & Examples (Grammar & action format)
- Condition D: Unrelated Failed Trajectory (Thermodynamics melt task)
- Condition E: Source Task Description Only (Goal hint without actions)
- Condition F: Grounded Visible Feedback Sub-sequences (Physically verified snippets)

Strict budget and execution controls:
- Step limit: 10 steps per episode
- 8 target tasks x 6 conditions = 48 episodes
- Full step-level telemetry, token tracking, and adapter monitoring
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from agents.base_agent import BaseAgent


def build_extra_context(condition: str, manifest: Dict[str, Any], target_task: Dict[str, Any]) -> str:
    """Builds the exact extra_context string for the specified condition."""
    src_group_name = target_task.get("source_group", "src_group_1_conductivity")
    src_group = manifest["source_experiences"].get(src_group_name, {})
    unrelated_group = manifest["source_experiences"]["src_group_unrelated_thermo"]

    if condition == "A":
        return ""
    elif condition == "B":
        acts = "\n".join(f"- {act}" for act in src_group["action_sequence"])
        return f"""### Reference Execution History from a Previous Attempt:
Task Goal: {src_group['task_desc']}
Attempt Outcome: {src_group['outcome']}
Actions attempted in order:
{acts}
Note: This attempt failed and did not achieve 100% completion. You may use this execution history for reference."""
    elif condition == "C":
        return manifest["generic_interface_spec_c"]
    elif condition == "D":
        acts = "\n".join(f"- {act}" for act in unrelated_group["action_sequence"])
        return f"""### Reference Execution History from a Previous Attempt:
Task Goal: {unrelated_group['task_desc']}
Attempt Outcome: {unrelated_group['outcome']}
Actions attempted in order:
{acts}
Note: This attempt failed and did not achieve 100% completion. You may use this execution history for reference."""
    elif condition == "E":
        return f"""### Reference Task Description from a Previous Problem:
Task Goal: {src_group['task_desc']}
Note: No execution history is available for this previous problem."""
    elif condition == "F":
        snips = "\n".join(f"- {snip}" for snip in src_group.get("grounded_feedback_snippets", []))
        return f"""### Verified Environment Interaction Patterns (Grounded Feedback):
The following actions were confirmed to produce valid physical effects in previous environment interactions:
{snips}
Use these grounded interaction patterns when relevant to your current goal."""
    else:
        raise ValueError(f"Unknown condition: {condition}")


def run_single_episode(
    env: ScienceWorldWrapper,
    agent: BaseAgent,
    task_name: str,
    variation: int,
    extra_context: str,
    step_limit: int = 10
) -> Dict[str, Any]:
    obs, task_desc, valid_actions, info = env.load_and_reset(task_name, variation)
    history: List[Tuple[str, str]] = []
    steps_log: List[Dict[str, Any]] = []

    total_prompt_tokens = 0
    total_completion_tokens = 0
    ep_start_time = time.time()
    done = False
    final_score = 0.0
    termination_reason = "step_limit"

    for step_num in range(1, step_limit + 1):
        action, thought, stats, telem = agent.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions,
            extra_context=extra_context
        )

        total_prompt_tokens += stats.get("input_tokens", 0)
        total_completion_tokens += stats.get("output_tokens", 0)

        # Execute in environment
        next_obs, reward, done, info, next_valid_actions = env.step(action)
        current_score = env.get_score()

        step_record = {
            "step": step_num,
            "thought": thought,
            "proposed_action": telem.get("proposed_action", ""),
            "executed_action": action,
            "adapter_modified": telem.get("adapter_modified", False),
            "adapter_reason": telem.get("adapter_reason", ""),
            "observation": obs,
            "action": action,
            "next_observation": next_obs,
            "reward": reward,
            "score": current_score,
            "done": done,
            "prompt_tokens": stats.get("input_tokens", 0),
            "completion_tokens": stats.get("output_tokens", 0)
        }
        steps_log.append(step_record)
        history.append((action, next_obs))
        obs = next_obs
        valid_actions = next_valid_actions
        final_score = current_score

        if final_score >= 100.0:
            termination_reason = "success_100"
            done = True
            break
        elif done:
            termination_reason = "env_done"
            break

    ep_duration = time.time() - ep_start_time
    success = (final_score >= 100.0)

    return {
        "final_score": final_score,
        "success": success,
        "steps_taken": len(steps_log),
        "termination_reason": termination_reason,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "duration_seconds": round(ep_duration, 2),
        "steps": steps_log
    }


def analyze_attribution_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes comparative metrics and evaluates the 5 diagnostic questions."""
    conditions = ["A", "B", "C", "D", "E", "F"]
    cond_stats: Dict[str, Dict[str, Any]] = {c: {
        "scores": [],
        "successes": [],
        "steps": [],
        "prompt_tokens": [],
        "completion_tokens": [],
        "adapter_mod_counts": []
    } for c in conditions}

    # Aggregate by condition
    for r in results:
        c = r["condition"]
        cond_stats[c]["scores"].append(r["final_score"])
        cond_stats[c]["successes"].append(1.0 if r["success"] else 0.0)
        cond_stats[c]["steps"].append(r["steps_taken"])
        cond_stats[c]["prompt_tokens"].append(r["total_prompt_tokens"])
        cond_stats[c]["completion_tokens"].append(r["total_completion_tokens"])
        adapter_mods = sum(1 for s in r["steps"] if s.get("adapter_modified", False))
        cond_stats[c]["adapter_mod_counts"].append(adapter_mods)

    summary: Dict[str, Any] = {}
    for c in conditions:
        n = len(cond_stats[c]["scores"])
        if n == 0:
            continue
        summary[c] = {
            "n": n,
            "mean_score": round(sum(cond_stats[c]["scores"]) / n, 2),
            "success_rate": round(sum(cond_stats[c]["successes"]) / n, 4),
            "mean_steps": round(sum(cond_stats[c]["steps"]) / n, 2),
            "mean_prompt_tokens": round(sum(cond_stats[c]["prompt_tokens"]) / n, 1),
            "mean_completion_tokens": round(sum(cond_stats[c]["completion_tokens"]) / n, 1),
            "mean_adapter_mods": round(sum(cond_stats[c]["adapter_mod_counts"]) / n, 2)
        }

    # Answer 5 diagnostic questions
    q1_b_vs_a_score = round(summary["B"]["mean_score"] - summary["A"]["mean_score"], 2)
    q1_b_vs_a_succ = round(summary["B"]["success_rate"] - summary["A"]["success_rate"], 4)

    q2_c_vs_a_score = round(summary["C"]["mean_score"] - summary["A"]["mean_score"], 2)
    q2_c_vs_b_score = round(summary["C"]["mean_score"] - summary["B"]["mean_score"], 2)

    q3_e_vs_a_score = round(summary["E"]["mean_score"] - summary["A"]["mean_score"], 2)
    q3_e_vs_b_score = round(summary["E"]["mean_score"] - summary["B"]["mean_score"], 2)

    q4_d_vs_a_score = round(summary["D"]["mean_score"] - summary["A"]["mean_score"], 2)
    q4_d_vs_b_score = round(summary["D"]["mean_score"] - summary["B"]["mean_score"], 2)

    q5_f_vs_a_score = round(summary["F"]["mean_score"] - summary["A"]["mean_score"], 2)
    q5_f_vs_b_score = round(summary["F"]["mean_score"] - summary["B"]["mean_score"], 2)

    diagnostic_answers = {
        "Q1_reproducibility_B_vs_A": {
            "delta_mean_score": q1_b_vs_a_score,
            "delta_success_rate": q1_b_vs_a_succ,
            "verdict": "reproduced_gain" if q1_b_vs_a_score > 5.0 else ("reproduced_neutral" if q1_b_vs_a_score >= -5.0 else "negative_transfer")
        },
        "Q2_syntax_interface_C_explains_B": {
            "delta_score_C_vs_A": q2_c_vs_a_score,
            "delta_score_C_vs_B": q2_c_vs_b_score,
            "c_explains_b": bool(summary["C"]["mean_score"] >= summary["B"]["mean_score"] - 5.0 and q2_c_vs_a_score > 0)
        },
        "Q3_task_desc_hint_E_explains_B": {
            "delta_score_E_vs_A": q3_e_vs_a_score,
            "delta_score_E_vs_B": q3_e_vs_b_score,
            "e_explains_b": bool(summary["E"]["mean_score"] >= summary["B"]["mean_score"] - 5.0 and q3_e_vs_a_score > 0)
        },
        "Q4_unrelated_demo_D_similar_benefit": {
            "delta_score_D_vs_A": q4_d_vs_a_score,
            "delta_score_D_vs_B": q4_d_vs_b_score,
            "d_produces_similar_gain": bool(summary["D"]["mean_score"] >= summary["B"]["mean_score"] - 10.0 and q4_d_vs_a_score > 5.0)
        },
        "Q5_grounded_feedback_F_retains_benefits": {
            "delta_score_F_vs_A": q5_f_vs_a_score,
            "delta_score_F_vs_B": q5_f_vs_b_score,
            "f_token_saving_vs_b": round((summary["B"]["mean_prompt_tokens"] - summary["F"]["mean_prompt_tokens"]) / max(1, summary["B"]["mean_prompt_tokens"]), 4),
            "f_retains_or_exceeds_b": bool(summary["F"]["mean_score"] >= summary["B"]["mean_score"])
        }
    }

    # Automated scientific decision
    c_explains = diagnostic_answers["Q2_syntax_interface_C_explains_B"]["c_explains_b"]
    d_explains = diagnostic_answers["Q4_unrelated_demo_D_similar_benefit"]["d_produces_similar_gain"]
    e_explains = diagnostic_answers["Q3_task_desc_hint_E_explains_B"]["e_explains_b"]
    b_has_gain = q1_b_vs_a_score > 5.0
    f_has_gain = q5_f_vs_a_score > 5.0

    if (not b_has_gain and not f_has_gain) or c_explains or d_explains or e_explains:
        decision = "DECISION_1_TERMINATE_OR_PIVOT"
        rationale = (
            "Gains observed in failure trajectory transfer are predominantly attributable to "
            "action syntax / tool interface priming (H1), general demonstration length effects (H3), "
            "or source description hints (H2), rather than deep domain interaction knowledge reuse."
        )
    else:
        decision = "DECISION_2_CONVERGE_MINIMAL_DISTILLATION"
        rationale = (
            "Task performance is uniquely elevated by grounded interaction feedback sub-sequences (F) "
            "or domain-relevant trajectories (B), ruling out syntax interface and length confounds. "
            "Research problem converges to minimal distillation of causal interaction snippets."
        )

    return {
        "condition_summary": summary,
        "diagnostic_answers": diagnostic_answers,
        "decision": decision,
        "rationale": rationale
    }


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    manifest_path = os.path.join(base_dir, "frozen_attribution_manifest.json")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print("=" * 70)
    print("STARTING FAILURE TRAJECTORY TRANSFER BENEFIT ATTRIBUTION EXPERIMENT")
    print(f"Manifest: {manifest['manifest_name']}")
    print(f"Target Tasks: {len(manifest['target_tasks'])}")
    print(f"Conditions: A, B, C, D, E, F (6 conditions)")
    print(f"Total Episodes Planned: {len(manifest['target_tasks']) * 6}")
    print("=" * 70)

    # Initialize environment and model client
    env = ScienceWorldWrapper(step_limit=10)
    llm = LLMClient.get_instance()
    agent = BaseAgent(llm)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(base_dir, "runs", f"run_{timestamp}_P1_attribution_experiment")
    os.makedirs(run_dir, exist_ok=True)

    results: List[Dict[str, Any]] = []
    total_episodes = len(manifest["target_tasks"]) * 6
    ep_count = 0
    t0_all = time.time()

    conditions = ["A", "B", "C", "D", "E", "F"]

    for task_info in manifest["target_tasks"]:
        task_id = task_info["task_id"]
        task_name = task_info["task_name"]
        variation = task_info["variation"]
        target = task_info["target"]

        print(f"\n>>> Running Target Task: {task_id} (name={task_name}, var={variation}, target={target})")

        for cond in conditions:
            ep_count += 1
            print(f"  [{ep_count}/{total_episodes}] Condition {cond}...", end="", flush=True)

            extra_context = build_extra_context(cond, manifest, task_info)

            ep_res = run_single_episode(
                env=env,
                agent=agent,
                task_name=task_name,
                variation=variation,
                extra_context=extra_context,
                step_limit=10
            )

            result_entry = {
                "episode_index": ep_count,
                "task_id": task_id,
                "task_family": task_info["task_family"],
                "task_name": task_name,
                "variation": variation,
                "target": target,
                "expected_property": task_info.get("expected_property", ""),
                "condition": cond,
                "extra_context": extra_context,
                "final_score": ep_res["final_score"],
                "success": ep_res["success"],
                "steps_taken": ep_res["steps_taken"],
                "termination_reason": ep_res["termination_reason"],
                "total_prompt_tokens": ep_res["total_prompt_tokens"],
                "total_completion_tokens": ep_res["total_completion_tokens"],
                "duration_seconds": ep_res["duration_seconds"],
                "steps": ep_res["steps"]
            }
            results.append(result_entry)

            print(f" score={ep_res['final_score']}, success={ep_res['success']}, steps={ep_res['steps_taken']}, duration={ep_res['duration_seconds']}s")

            # Intermediate save every 6 episodes
            if ep_count % 6 == 0:
                with open(os.path.join(run_dir, "attribution_results_partial.json"), "w", encoding="utf-8") as pf:
                    json.dump(results, pf, indent=2, ensure_ascii=False)

    env.close()
    total_duration = time.time() - t0_all
    print(f"\nAll {total_episodes} episodes completed in {total_duration:.1f}s!")

    # Complete analysis
    analysis = analyze_attribution_results(results)

    final_payload = {
        "manifest_name": manifest["manifest_name"],
        "timestamp": timestamp,
        "total_episodes": total_episodes,
        "total_duration_seconds": round(total_duration, 2),
        "analysis": analysis,
        "results": results
    }

    results_file = os.path.join(run_dir, "attribution_results.json")
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("ATTRIBUTION EXPERIMENT COMPLETED")
    print(f"Results saved to: {results_file}")
    print("=" * 70)
    print("\nCONDITION SUMMARY:")
    for cond, stats in analysis["condition_summary"].items():
        print(f"  Condition {cond}: Mean Score = {stats['mean_score']}, Success Rate = {stats['success_rate']*100:.1f}%, Mean Steps = {stats['mean_steps']}, Mean Prompt Tokens = {stats['mean_prompt_tokens']}")

    print("\nDIAGNOSTIC QUESTION ANSWERS:")
    print(json.dumps(analysis["diagnostic_answers"], indent=2, ensure_ascii=False))

    print("\nFINAL SCIENTIFIC DECISION:")
    print(f"Decision: {analysis['decision']}")
    print(f"Rationale: {analysis['rationale']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
