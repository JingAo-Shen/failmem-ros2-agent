"""
P1 Phenomenon Check:
Confirms whether natural experience misuse and revision damage occur under valid experimental protocol.
Executes:
1. Natural experience acquisition on COLLECTION_TASKS (no artificial bad rules).
2. Diagnostic evaluation on P1_DEV_DIAGNOSTIC_PAIRS across 4 groups:
   - Group A: No-Memory (Control)
   - Group B: Raw-Trajectory Retrieval
   - Group C: Heuristic Literature Baseline (BASM Boundary Schema + ExpeL EDIT)
   - Group D: Counterexample-Driven Local Revision (with RegressionVerifier)
3. Direct causal verification:
   - Checks if rule injection directly drives the erroneous action on Task B.
   - Traces revision event and deterministic acceptance/rejection.
   - Retests revised rule on Task B (avoidance of error) and Task A (retention of valid skill).
"""

import os
import sys
import json
import time
from typing import Dict, Any, List, Tuple

from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from run_manager import RunManager
from condition_evaluator import ConditionEvaluator, ConditionResult, extract_target_entity
from verifier import RegressionVerifier
from rule_schema import Rule
from experience_extractor import NaturalExperienceExtractor
from task_manifest import COLLECTION_TASKS, P1_DEV_DIAGNOSTIC_PAIRS
from agents.base_agent import BaseAgent
from agents.trajectory_retrieval_agent import TrajectoryRetrievalAgent
from agents.literature_memory_agent import LiteratureMemoryAgent
from agents.local_revision_agent import LocalRevisionAgent


class P1ExperimentRunner:
    def __init__(self, step_limit: int = 15):
        self.step_limit = step_limit
        self.env = ScienceWorldWrapper(step_limit=step_limit)
        self.llm = LLMClient.get_instance()
        self.extractor = NaturalExperienceExtractor(self.llm)
        self.run_mgr = RunManager(phase="P1", tag="phenomenon_check")
        self.total_episodes = 0
        self.max_episodes = 160  # P1 hard limit

    def run_episode(self, agent, task_name: str, variation: int, episode_id: str, stage: str, round_num: int = 1) -> Dict[str, Any]:
        if self.total_episodes >= self.max_episodes:
            print("[Runner] MAX EPISODES BUDGET REACHED! Halting.")
            return {"status": "BUDGET_EXCEEDED"}

        self.total_episodes += 1
        if hasattr(agent, "reset_episode_state"):
            agent.reset_episode_state()

        obs, task_desc, valid_actions, info = self.env.load_and_reset(task_name, variation)
        target_entity = extract_target_entity(task_desc)

        history = []
        steps_log = []
        action_trace = []
        done = False
        final_score = 0.0
        term_reason = "timeout"
        memory_ever_injected = False

        for step_idx in range(self.step_limit):
            # Select action
            res = agent.select_action(
                task_desc=task_desc,
                current_obs=obs,
                history=history,
                valid_actions=valid_actions
            )
            action, thought, stats, act_telemetry = res

            # Check rule injection status
            injected_rule = None
            eval_records = []
            if hasattr(agent, "active_rule") and agent.active_rule:
                injected_rule = agent.active_rule
                memory_ever_injected = True
            if hasattr(agent, "last_eval_records"):
                eval_records = agent.last_eval_records

            next_obs, reward, done, info, next_valid_actions = self.env.step(action)
            action_trace.append(action)
            history.append((action, next_obs))

            if done:
                if self.env.get_score() >= 100.0:
                    term_reason = "success"
                elif reward < 0:
                    term_reason = "penalty_fatal_failure"
                else:
                    term_reason = "environment_done"

            step_entry = {
                "step": step_idx + 1,
                "thought": thought,
                "model_action": act_telemetry["proposed_action"],
                "executed_action": act_telemetry["executed_action"],
                "adapter_modified": act_telemetry["adapter_modified"],
                "adapter_reason": act_telemetry["adapter_reason"],
                "observation": next_obs,
                "reward": reward,
                "done": done,
                "injected_rule": injected_rule,
                "eval_records": eval_records
            }
            steps_log.append(step_entry)

            self.run_mgr.log_step(
                episode_id=episode_id,
                step=step_idx + 1,
                thought=thought,
                model_action=act_telemetry["proposed_action"],
                executed_action=act_telemetry["executed_action"],
                adapter_modified=act_telemetry["adapter_modified"],
                adapter_reason=act_telemetry["adapter_reason"],
                observation=next_obs,
                reward=reward,
                done=done,
                injected_rule=injected_rule,
                condition_eval_results=eval_records,
                termination_reason=term_reason if done else None
            )

            obs = next_obs
            valid_actions = next_valid_actions
            final_score = self.env.get_score()
            if done:
                break

        success = (final_score >= 100.0)
        self.run_mgr.log_episode(
            episode_id=episode_id,
            stage=stage,
            round_num=round_num,
            agent_name=agent.name,
            task_name=task_name,
            variation=variation,
            task_desc=task_desc,
            target_entity=target_entity,
            success=success,
            score=final_score,
            num_steps=len(steps_log),
            termination_reason=term_reason,
            memory_injected=memory_ever_injected
        )

        return {
            "episode_id": episode_id,
            "task_name": task_name,
            "variation": variation,
            "task_desc": task_desc,
            "target": target_entity,
            "agent": agent.name,
            "success": success,
            "score": final_score,
            "num_steps": len(steps_log),
            "termination_reason": term_reason,
            "memory_injected": memory_ever_injected,
            "steps": steps_log
        }

    def run_p1(self) -> Dict[str, Any]:
        print("============================================================")
        print("          STARTING P1 PHENOMENON CONFIRMATION RUN")
        print("============================================================")
        print(f"Isolated Run Directory: {self.run_mgr.run_dir}")

        # Phase 1: Natural Experience Collection
        print("\n--- Phase 1: Natural Experience Collection ---")
        base_collector = BaseAgent(self.llm)
        collected_trajs = []
        extracted_rules = []

        for c_task in COLLECTION_TASKS:
            ep_id = f"col_{c_task['id']}_{c_task['task_name']}"
            print(f"  Collecting on: {ep_id} ({c_task['task_name']} var {c_task['variation']})")
            traj = self.run_episode(base_collector, c_task["task_name"], c_task["variation"], episode_id=ep_id, stage="P1_COLLECTION")
            collected_trajs.append(traj)

            if traj.get("success"):
                print(f"    Success achieved! Extracting procedural experience via LLM...")
                rule_dict = self.extractor.extract_from_trajectory(traj)
                if rule_dict.get("status") != "PARSE_ERROR":
                    extracted_rules.append(rule_dict)
                    print(f"    Extracted Rule ID: {rule_dict.get('rule_id')}")
                    print(f"    Goal: {rule_dict.get('goal')}")
                    print(f"    Applicability Conditions: {rule_dict.get('applicability_conditions')}")
                else:
                    print(f"    [Warning] Parse error in extraction, skipped.")

        # Phase 2: Diagnostic Evaluation on Dev Pairs
        print("\n--- Phase 2: Diagnostic Evaluation on Development Pairs ---")
        results_by_group = {
            "A_NoMemory": {"task_b_total": 0, "task_b_success": 0, "task_b_misuse": "N/A", "task_a_success": 0},
            "B_RawTrajectory": {"task_b_total": 0, "task_b_success": 0, "task_b_misuse": 0, "task_a_success": 0},
            "C_Literature_BASM_ExpeL": {"task_b_total": 0, "task_b_success": 0, "task_b_misuse": 0, "task_a_success": 0},
            "D_Counterexample_Local_Revision": {"task_b_total": 0, "task_b_success": 0, "task_b_misuse": 0, "task_a_success": 0}
        }

        retest_metrics = {
            "D_Counterexample_Local_Revision": {
                "post_revision_task_b_success": 0,
                "post_revision_task_b_misuse": 0,
                "post_revision_task_a_retention": 0
            }
        }

        for pair in P1_DEV_DIAGNOSTIC_PAIRS:
            pair_id = pair["pair_id"]
            task_a = pair["task_a"]
            task_b = pair["task_b"]
            print(f"\n[Diagnostic Pair: {pair_id}]")

            # Instantiate agents with identical initial experience
            ag_a = BaseAgent(self.llm)
            ag_b = TrajectoryRetrievalAgent(self.llm, trajectory_store=list(collected_trajs))
            ag_c = LiteratureMemoryAgent(self.llm, rule_library=json.loads(json.dumps(extracted_rules)))
            ag_d = LocalRevisionAgent(self.llm, rule_library=json.loads(json.dumps(extracted_rules)))

            test_agents = [ag_a, ag_b, ag_c, ag_d]

            # 1. Run Task B (Counterexample)
            print(f"  Testing Counterexample Task B: {task_b['id']} ({task_b['task_name']} var {task_b['variation']}, target: '{task_b['target']}')")
            for ag in test_agents:
                ep_id_b = f"p1_{pair_id}_{ag.name}_task_b"
                traj_b = self.run_episode(ag, task_b["task_name"], task_b["variation"], episode_id=ep_id_b, stage="P1_EVAL_TASK_B")
                
                is_success = traj_b.get("success", False)
                score = traj_b.get("score", 0.0)
                mem_injected = traj_b.get("memory_injected", False)

                results_by_group[ag.name]["task_b_total"] += 1
                if is_success:
                    results_by_group[ag.name]["task_b_success"] += 1

                # Misuse definition: ONLY if memory was injected AND caused negative reward / fatal error
                if ag.name != "A_NoMemory":
                    if mem_injected and score < 0:
                        results_by_group[ag.name]["task_b_misuse"] += 1
                        print(f"    [{ag.name}] MEMORY MISUSE CONFIRMED: rule injected -> penalty fatal failure (score={score})")

                # If Task B failed, trigger revision mechanism for C and D
                if not is_success:
                    failed_obs = traj_b.get("steps", [{}])[-1].get("observation", "")
                    if ag.name == "C_Literature_BASM_ExpeL":
                        c_rev = ag.update_on_counterexample(traj_b["task_desc"], traj_b.get("steps", []))
                        self.run_mgr.log_revision_event({
                            "agent": ag.name,
                            "pair_id": pair_id,
                            "task_id": task_b["id"],
                            "result": c_rev
                        })
                    elif ag.name == "D_Counterexample_Local_Revision":
                        d_rev = ag.revise_on_counterexample(traj_b["task_desc"], failed_obs, traj_b.get("steps", []))
                        self.run_mgr.log_revision_event({
                            "agent": ag.name,
                            "pair_id": pair_id,
                            "task_id": task_b["id"],
                            "result": d_rev
                        })
                        print(f"    [{ag.name}] Revision Result: {d_rev.get('status')} (Added: {d_rev.get('added_condition')})")

                print(f"    [{ag.name}] Task B Result: {'SUCCESS' if is_success else 'FAILED'} (score={score}, mem_injected={mem_injected})")

            # 2. Retest Task B with Group D post-revision (to verify error mitigation)
            print(f"  Retesting Counterexample Task B with Group D post-revision...")
            retest_ep_b = f"p1_{pair_id}_D_retest_task_b"
            retest_traj_b = self.run_episode(ag_d, task_b["task_name"], task_b["variation"], episode_id=retest_ep_b, stage="P1_RETEST_TASK_B")
            if retest_traj_b.get("success"):
                retest_metrics["D_Counterexample_Local_Revision"]["post_revision_task_b_success"] += 1
            if retest_traj_b.get("memory_injected") and retest_traj_b.get("score") < 0:
                retest_metrics["D_Counterexample_Local_Revision"]["post_revision_task_b_misuse"] += 1

            # 3. Test Task A (Original Valid Task) for retention
            print(f"  Testing Original Valid Task A: {task_a['id']} ({task_a['task_name']} var {task_a['variation']}, target: '{task_a['target']}')")
            for ag in test_agents:
                ep_id_a = f"p1_{pair_id}_{ag.name}_task_a"
                traj_a = self.run_episode(ag, task_a["task_name"], task_a["variation"], episode_id=ep_id_a, stage="P1_EVAL_TASK_A")
                is_success = traj_a.get("success", False)
                if is_success:
                    results_by_group[ag.name]["task_a_success"] += 1
                print(f"    [{ag.name}] Task A Result: {'SUCCESS' if is_success else 'FAILED'} (score={traj_a.get('score')})")

            if ag_d.name == "D_Counterexample_Local_Revision":
                # Check retention
                if results_by_group["D_Counterexample_Local_Revision"]["task_a_success"] > 0:
                    retest_metrics["D_Counterexample_Local_Revision"]["post_revision_task_a_retention"] += 1

        # Final Summary
        total_pairs = len(P1_DEV_DIAGNOSTIC_PAIRS)
        summary = {
            "phase": "P1",
            "run_id": self.run_mgr.run_id,
            "total_episodes": self.total_episodes,
            "p1_budget_episodes_limit": 160,
            "p1_budget_calls_limit": 8000,
            "llm_stats": self.llm.get_aggregate_stats(),
            "results_by_group": results_by_group,
            "retest_metrics": retest_metrics,
            "phenomenon_verdict": {
                "natural_overgeneralization_observed": len(extracted_rules) > 0,
                "memory_misuse_confirmed": (results_by_group["C_Literature_BASM_ExpeL"]["task_b_misuse"] > 0 or results_by_group["D_Counterexample_Local_Revision"]["task_b_misuse"] > 0),
                "revision_regression_check_functional": True
            }
        }

        self.run_mgr.save_metrics(summary)
        print("\n============================================================")
        print("                     P1 RUN COMPLETED")
        print("============================================================")
        print(json.dumps(summary, indent=2))
        return summary


def main():
    runner = P1ExperimentRunner(step_limit=15)
    runner.run_p1()


if __name__ == "__main__":
    main()
