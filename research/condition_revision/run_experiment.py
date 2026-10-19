"""
Main Experiment Runner for Condition Revision Feasibility Study:
Orchestrates two independent rounds across Groups A, B, C, D on ScienceWorld.
Monitors budgets (<=200 episodes, <=8000 calls).
Logs step-level traces to JSONL and produces summary tables.
"""

import os
import sys
import json
import time
import argparse
from typing import Dict, List, Any, Tuple

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from task_manifest import COLLECTION_TASKS, DIAGNOSTIC_TASK_PAIRS
from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from experience_extractor import NaturalExperienceExtractor
from agents.base_agent import BaseAgent
from agents.trajectory_retrieval_agent import TrajectoryRetrievalAgent
from agents.literature_memory_agent import LiteratureMemoryAgent
from agents.local_revision_agent import LocalRevisionAgent
from decision_tree_check import ShallowDecisionTreeChecker


class ExperimentRunner:
    def __init__(self, step_limit: int = 25, log_dir: str = "/code/failmem-ros2-agent/research/condition_revision/logs"):
        self.step_limit = step_limit
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.raw_trajectories_path = os.path.join(log_dir, "raw_trajectories.jsonl")
        self.revision_events_path = os.path.join(log_dir, "revision_events.jsonl")
        self.extracted_rules_path = os.path.join(log_dir, "extracted_rules.json")
        self.env = ScienceWorldWrapper(step_limit=step_limit)
        self.llm = LLMClient.get_instance()
        self.total_episodes = 0
        self.max_episodes = 200
        self.max_calls = 8000

    def run_episode(self, agent, task_name: str, variation: int, task_id: str = "") -> Dict[str, Any]:
        if self.total_episodes >= self.max_episodes:
            print("[Runner] MAX EPISODES BUDGET REACHED! Halting.")
            return {"status": "BUDGET_EXCEEDED"}
        if self.llm.total_calls >= self.max_calls:
            print("[Runner] MAX MODEL CALLS BUDGET REACHED! Halting.")
            return {"status": "BUDGET_EXCEEDED"}

        self.total_episodes += 1
        if hasattr(agent, "reset_episode_state"):
            agent.reset_episode_state()
        obs, task_desc, valid_actions, info = self.env.load_and_reset(task_name, variation)
        history = []
        steps_log = []
        done = False
        final_score = 0.0

        for step_idx in range(self.step_limit):
            action, thought, stats = agent.select_action(
                task_desc=task_desc,
                current_obs=obs,
                history=history,
                valid_actions=valid_actions
            )
            next_obs, reward, done, info, next_valid_actions = self.env.step(action)
            history.append((action, next_obs))
            steps_log.append({
                "step": step_idx + 1,
                "thought": thought,
                "action": action,
                "observation": next_obs,
                "reward": reward,
                "done": done
            })
            obs = next_obs
            valid_actions = next_valid_actions
            final_score = self.env.get_score()
            if done:
                break

        success = (final_score >= 100.0) or (done and final_score > 0)
        trajectory = {
            "task_id": task_id,
            "task_name": task_name,
            "variation": variation,
            "task_description": task_desc,
            "agent": agent.name,
            "success": success,
            "score": final_score,
            "num_steps": len(steps_log),
            "steps": steps_log
        }
        # Immediately persist trajectory to raw_trajectories.jsonl
        try:
            with open(self.raw_trajectories_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(trajectory) + "\n")
        except Exception as e:
            print(f"[Warning] Failed to log trajectory: {e}")

        return trajectory

    def run_collection_phase(self, tasks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        print("\n" + "="*60)
        print("--- PHASE 1: NATURAL EXPERIENCE COLLECTION (Group A BaseAgent) ---")
        print("="*60)
        collector_agent = BaseAgent(self.llm)
        extractor = NaturalExperienceExtractor(self.llm)

        raw_trajectories = []
        extracted_rules = []

        for t in tasks:
            print(f"Collecting: {t['id']} | Task: {t['task_name']} var {t['variation']} ({t['description']})...")
            traj = self.run_episode(collector_agent, t["task_name"], t["variation"], task_id=t["id"])
            if traj.get("status") == "BUDGET_EXCEEDED":
                break
            raw_trajectories.append(traj)
            print(f"  -> Outcome: {'SUCCESS' if traj['success'] else 'FAILED'} (score={traj['score']}, steps={traj['num_steps']})")

            # Extract rule from successful or recovered runs
            if traj["success"] or traj["score"] > 20:
                print(f"  -> Extracting natural experience via LLM...")
                rule = extractor.extract_from_trajectory(traj)
                extracted_rules.append(rule)
                print(f"     Extracted Goal: {rule.get('goal')}")
                print(f"     Conditions: {rule.get('applicability_conditions')}")

        try:
            with open(self.extracted_rules_path, "w", encoding="utf-8") as f:
                json.dump(extracted_rules, f, indent=2)
        except Exception as e:
            print(f"[Warning] Failed to save extracted rules: {e}")

        return raw_trajectories, extracted_rules

    def run_evaluation_phase(self, diagnostic_pairs: List[Dict[str, Any]], initial_trajectories: List[Dict[str, Any]], initial_rules: List[Dict[str, Any]], round_num: int) -> Dict[str, Any]:
        print("\n" + "="*60)
        print(f"--- PHASE 2: FOUR-GROUP DIAGNOSTIC EVALUATION (Round {round_num}) ---")
        print("="*60)

        # Initialize the 4 agents
        agent_a = BaseAgent(self.llm)
        agent_b = TrajectoryRetrievalAgent(self.llm, trajectory_store=list(initial_trajectories))
        agent_c = LiteratureMemoryAgent(self.llm, rule_library=json.loads(json.dumps(initial_rules)))
        agent_d = LocalRevisionAgent(self.llm, rule_library=json.loads(json.dumps(initial_rules)))

        agents = [agent_a, agent_b, agent_c, agent_d]
        results_ledger = {ag.name: {"task_a_successes": 0, "task_b_successes": 0, "task_b_misuses": 0, "episodes": []} for ag in agents}

        for pair in diagnostic_pairs:
            pair_id = pair["pair_id"]
            cat = pair["category"]
            task_a = pair["task_a"]
            task_b = pair["task_b"]

            print(f"\n[Diagnostic Pair: {pair_id}] ({cat})")

            # 1. Run Task B first (The Counterexample) to observe if misuse occurs
            print(f"  Testing Counterexample Task B: {task_b['id']} ({task_b['task_name']} var {task_b['variation']}, target: {task_b['target']})...")
            for ag in agents:
                traj_b = self.run_episode(ag, task_b["task_name"], task_b["variation"], task_id=f"{pair_id}_{ag.name}_task_b")
                is_success = traj_b.get("success", False)
                results_ledger[ag.name]["episodes"].append(traj_b)

                if is_success:
                    results_ledger[ag.name]["task_b_successes"] += 1
                else:
                    # Check if failure was caused by misapplying the rule
                    results_ledger[ag.name]["task_b_misuses"] += 1

                # If counterexample failed, trigger agent's update mechanism
                if not is_success:
                    failed_desc = traj_b.get("task_description", task_b["target"])
                    if ag.name == "B_RawTrajectory":
                        ag.add_trajectory(traj_b)
                    elif ag.name == "C_Literature_BASM_ExpeL":
                        rev_res = ag.update_on_counterexample(failed_desc, traj_b.get("steps", []))
                        try:
                            rev_event = {"round": round_num, "pair_id": pair_id, "agent": ag.name, "failed_task": failed_desc, "result": rev_res}
                            with open(self.revision_events_path, "a", encoding="utf-8") as rf:
                                rf.write(json.dumps(rev_event) + "\n")
                        except Exception:
                            pass
                    elif ag.name == "D_Counterexample_Local_Revision":
                        last_obs = traj_b.get("steps", [{}])[-1].get("observation", "")
                        rev_res = ag.revise_on_counterexample(failed_desc, last_obs, traj_b.get("steps", []))
                        try:
                            rev_event = {"round": round_num, "pair_id": pair_id, "agent": ag.name, "failed_task": failed_desc, "result": rev_res}
                            with open(self.revision_events_path, "a", encoding="utf-8") as rf:
                                rf.write(json.dumps(rev_event) + "\n")
                        except Exception:
                            pass

                print(f"    [{ag.name}] Task B Result: {'SUCCESS' if is_success else 'FAILED'} (score={traj_b.get('score', 0)})")

            # 2. Run Task A (Original Valid Task) to check retention / regression
            print(f"  Testing Original Valid Task A: {task_a['id']} ({task_a['task_name']} var {task_a['variation']}, target: {task_a['target']})...")
            for ag in agents:
                traj_a = self.run_episode(ag, task_a["task_name"], task_a["variation"], task_id=f"{pair_id}_{ag.name}_task_a")
                is_success = traj_a.get("success", False)
                results_ledger[ag.name]["episodes"].append(traj_a)
                if is_success:
                    results_ledger[ag.name]["task_a_successes"] += 1
                print(f"    [{ag.name}] Task A Result: {'SUCCESS' if is_success else 'FAILED'} (score={traj_a.get('score', 0)})")

        return results_ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=2, help="Number of independent rounds (default 2)")
    parser.add_argument("--step_limit", type=int, default=10, help="Per episode step limit")
    parser.add_argument("--smoke_test", action="store_true", help="Run a quick smoke test on pair_03 and col_07")
    parser.add_argument("--max_pairs", type=int, default=None, help="Limit number of diagnostic pairs")
    parser.add_argument("--max_collections", type=int, default=None, help="Limit number of collection tasks")
    args = parser.parse_args()

    runner = ExperimentRunner(step_limit=args.step_limit)

    if args.smoke_test:
        collection_tasks = [COLLECTION_TASKS[6]]  # col_07 (conductivity of aluminum foil)
        diagnostic_pairs = [DIAGNOSTIC_TASK_PAIRS[2]]  # pair_03 (aluminum vs apricot)
        total_rounds = 1
    else:
        collection_tasks = COLLECTION_TASKS[:args.max_collections] if args.max_collections else COLLECTION_TASKS
        diagnostic_pairs = DIAGNOSTIC_TASK_PAIRS[:args.max_pairs] if args.max_pairs else DIAGNOSTIC_TASK_PAIRS
        total_rounds = args.rounds

    all_round_metrics = []

    for r in range(1, total_rounds + 1):
        print(f"\n############################################################")
        print(f"               STARTING EXPERIMENT ROUND {r} OF {total_rounds}")
        print(f"############################################################")

        # Select tasks for this round
        raw_trajs, rules = runner.run_collection_phase(collection_tasks)

        # Run evaluation on diagnostic pairs
        eval_ledger = runner.run_evaluation_phase(diagnostic_pairs, raw_trajs, rules, round_num=r)

        # Compute summary metrics for round r
        round_summary = {
            "round": r,
            "total_episodes_so_far": runner.total_episodes,
            "llm_stats": runner.llm.get_aggregate_stats(),
            "groups": {}
        }

        total_pairs = len(diagnostic_pairs)
        for ag_name, data in eval_ledger.items():
            round_summary["groups"][ag_name] = {
                "task_a_retention_rate": round(data["task_a_successes"] / total_pairs, 3),
                "task_b_success_rate": round(data["task_b_successes"] / total_pairs, 3),
                "task_b_misuse_rate": round(data["task_b_misuses"] / total_pairs, 3)
            }
        all_round_metrics.append(round_summary)

        # Save round data
        if not args.smoke_test:
            round_log_file = os.path.join(runner.log_dir, f"round_{r}_ledger.json")
            with open(round_log_file, "w") as f:
                clean_ledger = {}
                for k, v in eval_ledger.items():
                    clean_ledger[k] = {
                        "task_a_successes": v["task_a_successes"],
                        "task_b_success_rate": v["task_b_successes"],
                        "task_b_misuses": v["task_b_misuses"],
                        "num_episodes": len(v["episodes"])
                    }
                json.dump(clean_ledger, f, indent=2)

    # Run decision tree check
    dt_checker = ShallowDecisionTreeChecker()
    dt_res = dt_checker.run_check()

    # Final combined report
    final_output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_episodes": runner.total_episodes,
        "llm_aggregate_stats": runner.llm.get_aggregate_stats(),
        "round_summaries": all_round_metrics,
        "decision_tree_check": dt_res
    }

    report_name = "smoke_test_summary.json" if args.smoke_test else "experiment_summary.json"
    final_report_path = os.path.join(runner.log_dir, report_name)
    with open(final_report_path, "w") as f:
        json.dump(final_output, f, indent=2)

    print("\n" + "="*70)
    print("                     EXPERIMENT SUMMARY REPORT")
    print("="*70)
    print(json.dumps(final_output, indent=2))
    print(f"\nAll logs saved to {final_report_path}")

if __name__ == "__main__":
    main()
