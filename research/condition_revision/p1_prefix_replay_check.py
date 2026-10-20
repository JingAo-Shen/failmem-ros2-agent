"""
P1 Prefix Replay and Causal Attribution Verification:
Executes targeted single-step prefix replay at critical decision points to cleanly isolate
whether memory causes harmful misdirection, or whether failures stem from base model prior bias.

Evaluates 4 Conditions:
- Cond A: No Memory (Base Model Control)
- Cond B: Raw Trajectory Retrieval (Demonstration Injected)
- Cond C: Grounded Rule Memory (Evaluated via ConditionEvaluator)
- Cond D: Unconditioned Rule Memory (Rule injected blindly without condition verification)

Tracks exact telemetry, candidate actions, model decisions, and causal deltas.
"""

import sys
import os
import json
import time
from typing import Dict, Any, List, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from run_manager import RunManager
from condition_evaluator import ConditionEvaluator, ConditionResult, extract_target_entity
from experience_extractor import NaturalExperienceExtractor
from agents.base_agent import BaseAgent
from agents.trajectory_retrieval_agent import TrajectoryRetrievalAgent
from agents.literature_memory_agent import LiteratureMemoryAgent
from task_manifest import COLLECTION_TASKS, P1_DEV_DIAGNOSTIC_PAIRS


def main():
    print("============================================================")
    print("   P1 TARGETED CAUSAL PREFIX REPLAY & PHENOMENON CHECK")
    print("============================================================")

    llm = LLMClient.get_instance()
    run_mgr = RunManager(phase="P1", tag="prefix_replay")
    extractor = NaturalExperienceExtractor(llm)

    # 1. Natural Experience Collection from successful canonical run
    print("\n--- Step 1: Natural Experience Collection & Extraction ---")
    base_collector = BaseAgent(llm)
    env = ScienceWorldWrapper(step_limit=10)

    # Collect on col_01 (aluminum foil)
    col_task = COLLECTION_TASKS[0]  # test-conductivity var 0
    obs, task_desc, valid_actions, info = env.load_and_reset(col_task["task_name"], col_task["variation"])
    target = extract_target_entity(task_desc)

    history = []
    steps_log = []
    success = False

    for s_idx in range(10):
        action, thought, stats, act_telemetry = base_collector.select_action(
            task_desc=task_desc,
            current_obs=obs,
            history=history,
            valid_actions=valid_actions
        )
        next_obs, reward, done, info, next_valid_actions = env.step(action)
        history.append((action, next_obs))
        steps_log.append({
            "step": s_idx + 1,
            "thought": thought,
            "action": action,
            "executed_action": action,
            "model_action": act_telemetry["proposed_action"],
            "observation": next_obs,
            "reward": reward,
            "done": done
        })
        if done:
            success = (env.get_score() >= 100.0)
            break
        obs = next_obs
        valid_actions = next_valid_actions

    col_traj = {
        "episode_id": "col_01_aluminum_foil",
        "task_name": col_task["task_name"],
        "variation": col_task["variation"],
        "task_desc": task_desc,
        "task_description": task_desc,
        "target": target,
        "agent": "A_NoMemory",
        "success": success,
        "score": env.get_score(),
        "num_steps": len(steps_log),
        "steps": steps_log
    }

    print(f"  Collection run result: Success={success}, Score={col_traj['score']}, Steps={col_traj['num_steps']}")

    # Extract rule via LLM with unified interface
    extracted_rule = extractor.extract_from_trajectory(col_traj)
    print(f"  Extracted Rule ID: {extracted_rule.get('rule_id')}")
    print(f"  Rule Goal: {extracted_rule.get('goal')}")
    print(f"  Applicability Conditions: {extracted_rule.get('applicability_conditions')}")
    print(f"  Recovery / Procedure: {extracted_rule.get('recovery_procedure')}")

    # Save extraction inspection sample
    extraction_sample_path = os.path.join(run_mgr.run_dir, "extraction_debug_sample.json")
    with open(extraction_sample_path, "w", encoding="utf-8") as f:
        json.dump(extractor.last_extraction_debug, f, indent=2)
    print(f"  Extraction debug log saved to: {extraction_sample_path}")

    # 2. Targeted Prefix Replay across Diagnostic Pairs
    print("\n--- Step 2: Targeted Causal Prefix Replay ---")

    replay_results = []

    for pair in P1_DEV_DIAGNOSTIC_PAIRS:
        pair_id = pair["pair_id"]
        task_b = pair["task_b"]
        print(f"\n[Evaluating Counterexample Task B: {pair_id}]")
        print(f"  Target: '{task_b['target']}', Task: {task_b['task_name']} var {task_b['variation']}")

        # We set up environment and run deterministic prefix:
        # Step 1: teleport to workshop/kitchen
        # Step 2: focus on target object
        env_b = ScienceWorldWrapper(step_limit=10)
        obs_b, task_desc_b, valid_actions_b, info_b = env_b.load_and_reset(task_b["task_name"], task_b["variation"])
        target_b = extract_target_entity(task_desc_b)

        history_prefix = []
        # Run prefix steps
        # Step 1: navigate to location
        target_loc = "workshop" if "workshop" in task_desc_b else ("kitchen" if "kitchen" in task_desc_b else "workshop")
        nav_act = f"teleport to {target_loc}"
        if nav_act in valid_actions_b:
            obs_b, rew, done, info, valid_actions_b = env_b.step(nav_act)
            history_prefix.append((nav_act, obs_b))

        # Step 2: focus on target
        focus_act = f"focus on {target_b}"
        if focus_act in valid_actions_b:
            obs_b, rew, done, info, valid_actions_b = env_b.step(focus_act)
            history_prefix.append((focus_act, obs_b))

        print(f"  Prefix executed up to critical decision point (obs: '{obs_b.strip()[:80]}').")

        # Now fork at Step 3:
        # Cond A: No Memory
        agent_a = BaseAgent(llm)
        act_a, thought_a, _, tel_a = agent_a.select_action(
            task_desc=task_desc_b,
            current_obs=obs_b,
            history=history_prefix,
            valid_actions=valid_actions_b
        )

        # Cond B: Raw Trajectory
        agent_b = TrajectoryRetrievalAgent(llm, trajectory_store=[col_traj])
        act_b, thought_b, _, tel_b = agent_b.select_action(
            task_desc=task_desc_b,
            current_obs=obs_b,
            history=history_prefix,
            valid_actions=valid_actions_b
        )

        # Cond C: Grounded Rule Memory (BASM with ConditionEvaluator)
        agent_c = LiteratureMemoryAgent(llm, rule_library=[extracted_rule])
        act_c, thought_c, _, tel_c = agent_c.select_action(
            task_desc=task_desc_b,
            current_obs=obs_b,
            history=history_prefix,
            valid_actions=valid_actions_b
        )

        # Cond D: Unconditioned Blind Rule Memory (Forcing rule injection to see counterfactual impact)
        # Formats rule context directly into extra_context
        forced_rule_context = f"""### Past Rule Memory (Unconditioned):
Goal: {extracted_rule.get('goal')}
Procedure: {extracted_rule.get('recovery_procedure')}
"""
        agent_d = BaseAgent(llm)
        act_d, thought_d, _, tel_d = agent_d.select_action(
            task_desc=task_desc_b,
            current_obs=obs_b,
            history=history_prefix,
            valid_actions=valid_actions_b,
            extra_context=forced_rule_context
        )

        pair_summary = {
            "pair_id": pair_id,
            "task_b_target": target_b,
            "condition_eval_records": agent_c.last_eval_records,
            "rule_injected_in_C": (agent_c.active_rule is not None),
            "actions": {
                "Cond_A_NoMemory": act_a,
                "Cond_B_RawTrajectory": act_b,
                "Cond_C_GroundedRule": act_c,
                "Cond_D_UnconditionedBlindRule": act_d
            },
            "thoughts": {
                "Cond_A": thought_a,
                "Cond_B": thought_b,
                "Cond_C": thought_c,
                "Cond_D": thought_d
            },
            "causal_difference_A_vs_B": (act_a != act_b),
            "causal_difference_A_vs_C": (act_a != act_c),
            "causal_difference_A_vs_D": (act_a != act_d)
        }

        print(f"    Cond A (No Memory):           Action='{act_a}'")
        print(f"    Cond B (Raw Trajectory):       Action='{act_b}' (Diff vs A: {act_a != act_b})")
        print(f"    Cond C (Grounded Rule):        Action='{act_c}' (Injected: {agent_c.active_rule is not None}, Diff vs A: {act_a != act_c})")
        print(f"    Cond D (Unconditioned Rule):   Action='{act_d}' (Diff vs A: {act_a != act_d})")

        replay_results.append(pair_summary)

    # Save detailed replay results
    replay_out_path = os.path.join(run_mgr.run_dir, "prefix_replay_results.json")
    with open(replay_out_path, "w", encoding="utf-8") as f:
        json.dump(replay_results, f, indent=2)

    print("\n============================================================")
    print(f"Replay complete. Results saved to: {replay_out_path}")
    print("============================================================")


if __name__ == "__main__":
    main()
