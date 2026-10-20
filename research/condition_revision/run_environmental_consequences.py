"""
Environmental Consequences Comparison Experiment:
Rolls out complete trajectory branches from shared deterministic prefixes
across pre-registered frozen development chains:
- Chain 1: Conductivity Foil (Source: Aluminum Foil, Boundary: Apricot, Retention: Fork)
- Chain 2: Conductivity Fork (Source: Fork, Boundary: Glass Jar, Retention: Pot)
- Chain 3: Classification Living (Source: Living Thing, Boundary: Non-Living Thing, Retention: Living Thing v2)

Evaluates 4 Conditions:
- Cond A: No Memory (Control)
- Cond B: Raw Trajectory Demonstration
- Cond C: Condition-Gated Rule Memory (with grounded ConditionEvaluator)
- Cond D: Unconditioned Blind Rule Memory (Diagnostic Stress Test)

Tracks:
- Full step-by-step rollout to environment termination
- Memory exposure text and condition gating status ('not_exposed_to_rule' if rejected)
- Model proposed vs executed action
- Environmental outcome: score, success, termination reason, step count, and resource costs.
"""

import sys
import os
import json
import time
from typing import Dict, Any, List, Tuple, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from env_wrapper import ScienceWorldWrapper
from llm_client import LLMClient
from run_manager import RunManager
from condition_evaluator import ConditionEvaluator, ConditionResult, extract_target_entity
from experience_extractor import NaturalExperienceExtractor
from task_manifest import FROZEN_DEV_EXPERIENCE_CHAINS
from agents.base_agent import BaseAgent
from agents.trajectory_retrieval_agent import TrajectoryRetrievalAgent
from agents.literature_memory_agent import LiteratureMemoryAgent


class EnvironmentalRolloutRunner:
    def __init__(self, run_mgr: RunManager, llm: LLMClient):
        self.run_mgr = run_mgr
        self.llm = llm
        self.extractor = NaturalExperienceExtractor(llm)

    def run_source_collection(self, chain: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        src = chain["source_task"]
        task_name = src["task_name"]
        var = src["variation"]
        target = src["target"]
        ep_id = f"col_{chain['chain_id']}_{src['id']}"

        print(f"\n============================================================")
        print(f"  [Collection] Running Source Task: {task_name} var {var} ({target})")
        print(f"============================================================")

        env = ScienceWorldWrapper(step_limit=8)
        obs, task_desc, valid_actions, info = env.load_and_reset(task_name, var)
        agent = BaseAgent(self.llm)

        history = []
        steps_log = []
        done = False
        final_score = 0.0
        term_reason = "timeout"

        for s_idx in range(8):
            action, thought, stats, telemetry = agent.select_action(
                task_desc=task_desc,
                current_obs=obs,
                history=history,
                valid_actions=valid_actions
            )
            next_obs, reward, done, info, next_valid_actions = env.step(action)
            history.append((action, next_obs))

            step_record = {
                "step": s_idx + 1,
                "thought": thought,
                "proposed_action": telemetry["proposed_action"],
                "executed_action": action,
                "adapter_modified": telemetry["adapter_modified"],
                "adapter_reason": telemetry["adapter_reason"],
                "observation": next_obs,
                "reward": reward,
                "done": done
            }
            steps_log.append(step_record)
            self.run_mgr.log_step(
                episode_id=ep_id,
                step=s_idx + 1,
                thought=thought,
                model_action=telemetry["proposed_action"],
                executed_action=action,
                adapter_modified=telemetry["adapter_modified"],
                adapter_reason=telemetry["adapter_reason"],
                observation=next_obs,
                reward=reward,
                done=done,
                termination_reason=term_reason if done else None
            )

            if done:
                final_score = env.get_score()
                if final_score >= 100.0:
                    term_reason = "success"
                elif reward < 0:
                    term_reason = "fatal_penalty"
                else:
                    term_reason = "environment_done"
                break

            obs = next_obs
            valid_actions = next_valid_actions
            final_score = env.get_score()

        success = (final_score >= 100.0)
        traj_data = {
            "episode_id": ep_id,
            "task_name": task_name,
            "variation": var,
            "task_desc": task_desc,
            "task_description": task_desc,
            "target": target,
            "agent": "A_NoMemory",
            "success": success,
            "score": final_score,
            "num_steps": len(steps_log),
            "termination_reason": term_reason,
            "steps": steps_log
        }
        self.run_mgr.log_episode(
            episode_id=ep_id,
            stage="P1_COLLECTION",
            round_num=1,
            agent_name="A_NoMemory",
            task_name=task_name,
            variation=var,
            task_desc=task_desc,
            target_entity=target,
            success=success,
            score=final_score,
            num_steps=len(steps_log),
            termination_reason=term_reason,
            memory_injected=False
        )

        extracted_rule = None
        if success:
            print(f"  Source task succeeded! Extracting natural rule...")
            extracted_rule = self.extractor.extract_from_trajectory(traj_data)
            extracted_rule["rule_type"] = "success_summary"
            print(f"  Extracted Rule ID: {extracted_rule.get('rule_id')}")
            print(f"  Conditions: {extracted_rule.get('applicability_conditions')}")
            print(f"  Procedure: {extracted_rule.get('recovery_procedure')}")
        else:
            print(f"  Source task did not achieve full success (score: {final_score}). Skipping rule extraction.")

        return traj_data, extracted_rule

    def execute_prefix(self, env: ScienceWorldWrapper, task_name: str, var: int, target: str) -> Tuple[str, str, List[str], List[Tuple[str, str]], List[Dict[str, Any]]]:
        """Executes a shared deterministic prefix up to the critical choice state."""
        obs, task_desc, valid_actions, info = env.load_and_reset(task_name, var)
        history = []
        prefix_steps = []

        # 1. Navigation step
        target_loc = "workshop" if "workshop" in task_desc.lower() else ("kitchen" if "kitchen" in task_desc.lower() else ("greenhouse" if "greenhouse" in task_desc.lower() else None))
        if target_loc:
            nav_act = f"teleport to {target_loc}"
            if nav_act in valid_actions:
                next_obs, rew, done, info, valid_actions = env.step(nav_act)
                history.append((nav_act, next_obs))
                prefix_steps.append({"step": 1, "action": nav_act, "observation": next_obs, "reward": rew, "done": done})
                obs = next_obs

        # 2. Focus step
        focus_act = f"focus on {target.lower()}"
        if focus_act in valid_actions:
            next_obs, rew, done, info, valid_actions = env.step(focus_act)
            history.append((focus_act, next_obs))
            prefix_steps.append({"step": 2, "action": focus_act, "observation": next_obs, "reward": rew, "done": done})
            obs = next_obs

        return obs, task_desc, valid_actions, history, prefix_steps

    def rollout_branch(
        self,
        task_role: str,
        chain_id: str,
        cond_name: str,
        agent: Any,
        task_name: str,
        var: int,
        target: str,
        forced_context: str = "",
        max_remaining_steps: int = 6
    ) -> Dict[str, Any]:
        """Rolls out a full branch from the shared prefix to environment completion."""
        ep_id = f"rollout_{chain_id}_{task_role}_{cond_name}"
        env = ScienceWorldWrapper(step_limit=10)

        # 1. Establish deterministic prefix
        obs, task_desc, valid_actions, history, prefix_steps = self.execute_prefix(env, task_name, var, target)

        if hasattr(agent, "reset_episode_state"):
            agent.reset_episode_state()

        steps_log = list(prefix_steps)
        done = False
        final_score = env.get_score()
        term_reason = "timeout"
        memory_ever_injected = False
        exposure_details = None

        # 2. Complete the rollout
        for s_idx in range(len(prefix_steps), len(prefix_steps) + max_remaining_steps):
            # Select action
            res = agent.select_action(
                task_desc=task_desc,
                current_obs=obs,
                history=history,
                valid_actions=valid_actions,
                extra_context=forced_context
            )
            action, thought, stats, telemetry = res

            # Check memory injection
            injected_rule = None
            eval_records = []
            if hasattr(agent, "active_rule") and agent.active_rule:
                injected_rule = agent.active_rule
                memory_ever_injected = True
                exposure_details = {
                    "type": "condition_gated_rule",
                    "rule_id": injected_rule.get("rule_id"),
                    "conditions": injected_rule.get("applicability_conditions"),
                    "procedure": injected_rule.get("recovery_procedure")
                }
            elif hasattr(agent, "active_memory") and agent.active_memory:
                memory_ever_injected = True
                exposure_details = agent.active_memory
            elif forced_context:
                memory_ever_injected = True
                exposure_details = {
                    "type": "forced_unconditioned_diagnostic",
                    "context_snippet": forced_context[:150]
                }
            else:
                exposure_details = {"status": "not_exposed_to_rule"}

            if hasattr(agent, "last_eval_records"):
                eval_records = agent.last_eval_records

            next_obs, reward, done, info, next_valid_actions = env.step(action)
            history.append((action, next_obs))

            step_entry = {
                "step": s_idx + 1,
                "thought": thought,
                "proposed_action": telemetry["proposed_action"],
                "executed_action": action,
                "adapter_modified": telemetry["adapter_modified"],
                "adapter_reason": telemetry["adapter_reason"],
                "observation": next_obs,
                "reward": reward,
                "done": done,
                "memory_exposure": exposure_details,
                "eval_records": eval_records
            }
            steps_log.append(step_entry)

            self.run_mgr.log_step(
                episode_id=ep_id,
                step=s_idx + 1,
                thought=thought,
                model_action=telemetry["proposed_action"],
                executed_action=action,
                adapter_modified=telemetry["adapter_modified"],
                adapter_reason=telemetry["adapter_reason"],
                observation=next_obs,
                reward=reward,
                done=done,
                injected_rule=injected_rule,
                condition_eval_results=eval_records,
                memory_exposure=exposure_details,
                termination_reason=term_reason if done else None
            )

            if done:
                final_score = env.get_score()
                if final_score >= 100.0:
                    term_reason = "success"
                elif reward < 0:
                    term_reason = "fatal_penalty"
                else:
                    term_reason = "environment_done"
                break

            obs = next_obs
            valid_actions = next_valid_actions
            final_score = env.get_score()

        success = (final_score >= 100.0)
        self.run_mgr.log_episode(
            episode_id=ep_id,
            stage=f"P1_ROLLOUT_{task_role.upper()}",
            round_num=1,
            agent_name=cond_name,
            task_name=task_name,
            variation=var,
            task_desc=task_desc,
            target_entity=target,
            success=success,
            score=final_score,
            num_steps=len(steps_log),
            termination_reason=term_reason,
            memory_injected=memory_ever_injected,
            memory_exposure=exposure_details
        )

        return {
            "episode_id": ep_id,
            "chain_id": chain_id,
            "task_role": task_role,
            "cond_name": cond_name,
            "task_name": task_name,
            "variation": var,
            "target": target,
            "success": success,
            "score": final_score,
            "steps_taken": len(steps_log),
            "termination_reason": term_reason,
            "memory_injected": memory_ever_injected,
            "exposure_details": exposure_details,
            "condition_eval_records": eval_records,
            "actions": [s.get("executed_action") for s in steps_log]
        }

    def run_all_chains(self) -> Dict[str, Any]:
        rollout_results = []

        for chain in FROZEN_DEV_EXPERIENCE_CHAINS:
            chain_id = chain["chain_id"]
            print(f"\n############################################################")
            print(f"      STARTING CHAIN: {chain_id}")
            print(f"############################################################")

            # 1. Source Task Collection & Natural Rule Extraction
            source_traj, extracted_rule = self.run_source_collection(chain)
            rules_pool = [extracted_rule] if extracted_rule else []

            # 2. Evaluate on Boundary Task (Task B - Potential Counterexample)
            bnd = chain["boundary_task"]
            print(f"\n--- [Boundary Task B] {bnd['task_name']} var {bnd['variation']} ({bnd['target']}) ---")

            # Branch A: No Memory
            ag_a = BaseAgent(self.llm)
            res_a = self.rollout_branch("boundary_b", chain_id, "Cond_A_NoMemory", ag_a, bnd["task_name"], bnd["variation"], bnd["target"])
            rollout_results.append(res_a)
            print(f"  Cond A (No Memory): Score={res_a['score']}, Success={res_a['success']}, Steps={res_a['steps_taken']}, Term={res_a['termination_reason']}")

            # Branch B: Raw Trajectory
            ag_b = TrajectoryRetrievalAgent(self.llm, trajectory_store=[source_traj])
            res_b = self.rollout_branch("boundary_b", chain_id, "Cond_B_RawTrajectory", ag_b, bnd["task_name"], bnd["variation"], bnd["target"])
            rollout_results.append(res_b)
            print(f"  Cond B (Raw Trajectory): Score={res_b['score']}, Success={res_b['success']}, Steps={res_b['steps_taken']}, Term={res_b['termination_reason']}, Injected={res_b['memory_injected']}")

            # Branch C: Condition-Gated Rule
            ag_c = LiteratureMemoryAgent(self.llm, rule_library=rules_pool)
            res_c = self.rollout_branch("boundary_b", chain_id, "Cond_C_GroundedRule", ag_c, bnd["task_name"], bnd["variation"], bnd["target"])
            rollout_results.append(res_c)
            print(f"  Cond C (Grounded Rule): Score={res_c['score']}, Success={res_c['success']}, Steps={res_c['steps_taken']}, Term={res_c['termination_reason']}, Injected={res_c['memory_injected']}")

            # Branch D: Unconditioned Blind Rule (Diagnostic Stress Test)
            forced_rule_str = ""
            if extracted_rule:
                forced_rule_str = f"### Past Experience Rule:\nGoal: {extracted_rule.get('goal')}\nProcedure: {extracted_rule.get('recovery_procedure')}"
            ag_d = BaseAgent(self.llm)
            res_d = self.rollout_branch("boundary_b", chain_id, "Cond_D_UnconditionedBlindRule", ag_d, bnd["task_name"], bnd["variation"], bnd["target"], forced_context=forced_rule_str)
            rollout_results.append(res_d)
            print(f"  Cond D (Blind Rule Stress): Score={res_d['score']}, Success={res_d['success']}, Steps={res_d['steps_taken']}, Term={res_d['termination_reason']}")

            # 3. Evaluate on Retention Task (Unseen Valid Instance)
            ret = chain["retention_task"]
            print(f"\n--- [Retention Task] {ret['task_name']} var {ret['variation']} ({ret['target']}) ---")

            # Retention under Cond A (No Memory)
            res_ret_a = self.rollout_branch("retention", chain_id, "Cond_A_NoMemory", ag_a, ret["task_name"], ret["variation"], ret["target"])
            rollout_results.append(res_ret_a)
            print(f"  Retention Cond A: Score={res_ret_a['score']}, Success={res_ret_a['success']}, Steps={res_ret_a['steps_taken']}, Term={res_ret_a['termination_reason']}")

            # Retention under Cond C (Grounded Rule)
            res_ret_c = self.rollout_branch("retention", chain_id, "Cond_C_GroundedRule", ag_c, ret["task_name"], ret["variation"], ret["target"])
            rollout_results.append(res_ret_c)
            print(f"  Retention Cond C: Score={res_ret_c['score']}, Success={res_ret_c['success']}, Steps={res_ret_c['steps_taken']}, Term={res_ret_c['termination_reason']}, Injected={res_ret_c['memory_injected']}")

        # Save all rollout results
        out_summary_path = os.path.join(self.run_mgr.run_dir, "environmental_rollout_results.json")
        with open(out_summary_path, "w", encoding="utf-8") as f:
            json.dump(rollout_results, f, indent=2)

        print("\n============================================================")
        print(f"Environmental consequences rollout complete.")
        print(f"Summary written to: {out_summary_path}")
        print("============================================================")
        return {"rollout_results": rollout_results, "run_dir": self.run_mgr.run_dir}


def main():
    llm = LLMClient.get_instance()
    run_mgr = RunManager(phase="P1", tag="environmental_rollout")
    runner = EnvironmentalRolloutRunner(run_mgr, llm)
    runner.run_all_chains()


if __name__ == "__main__":
    main()
