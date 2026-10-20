"""
Counterexample-Driven Local Revision Agent (Group D Prototype):
Maintains rules with explicit provenance (pointers to supporting positive trajectories).
Upon encountering a counterexample:
1. Differential Diagnosis: Compares counterexample state against support trajectories.
2. Candidate Condition Generation: Derives a discriminating condition literal.
3. Deterministic Regression Verification: Executes condition evaluator against ALL historical support cases and the counterexample.
4. Fallback Handling: If regression fails or exclusion fails, rejects condition or flags rule as uncertain.
"""

from typing import List, Dict, Any, Tuple, Optional
import json
from agents.base_agent import BaseAgent
from condition_evaluator import ConditionEvaluator, ConditionResult, extract_target_entity
from verifier import RegressionVerifier

STOP_WORDS = {"the", "and", "for", "are", "was", "were", "with", "from", "that", "this", "have", "has", "must", "should", "been", "there", "some", "also", "then", "into", "their", "here"}


def extract_keywords(text: str) -> List[str]:
    return [w for w in text.lower().split() if w not in STOP_WORDS and len(w) >= 3]


class LocalRevisionAgent(BaseAgent):
    def __init__(self, llm_client, rule_library: List[Dict[str, Any]] = None):
        super().__init__(llm_client)
        self.name = "D_Counterexample_Local_Revision"
        self.rule_library = rule_library or []
        self.active_rule = None
        self.last_applied_rule = None
        self.last_eval_records = []

    def reset_episode_state(self):
        self.active_rule = None
        self.last_applied_rule = None
        self.last_eval_records = []

    def retrieve_matching_rule(self, task_desc: str, current_obs: str, history: List[Tuple[str, str]] = None) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        task_lower = task_desc.lower()
        target_entity = extract_target_entity(task_desc)
        history_obs = [h[1] for h in history if isinstance(h, (tuple, list)) and len(h) >= 2] if history else []

        eval_records = []
        for rule in self.rule_library:
            if rule.get("status") in ["uncertain", "deprecated"]:
                continue

            goal = rule.get("goal", "").lower()
            goal_words = extract_keywords(goal)
            if any(w in task_lower for w in goal_words):
                conds = rule.get("applicability_conditions", [])
                match_all = True
                for c in conds:
                    res, expl = ConditionEvaluator.evaluate_condition_string(
                        condition_str=c,
                        target=target_entity,
                        task_desc=task_desc,
                        current_obs=current_obs,
                        history_obs=history_obs
                    )
                    eval_records.append({
                        "rule_id": rule.get("rule_id"),
                        "condition": c,
                        "result": res.value,
                        "explanation": expl
                    })
                    # ONLY TRUE allows rule injection!
                    if res != ConditionResult.TRUE:
                        match_all = False
                        break
                if match_all:
                    return rule, eval_records
        return None, eval_records

    def format_rule_context(self, rule: Dict[str, Any]) -> str:
        return f"""### Retrieved Validated Decision Rule (Local Condition Constrained):
Goal: {rule.get('goal')}
Applicability Conditions: {', '.join(rule.get('applicability_conditions', []))}
Verified Support Cases: {len(rule.get('support_cases', rule.get('support_trajectories', [])))}
Recommended Procedure: {rule.get('recovery_procedure')}
"""

    def select_action(
        self,
        task_desc: str,
        current_obs: str,
        history: List[Tuple[str, str]],
        valid_actions: List[str],
        extra_context: str = ""
    ) -> Tuple[str, str, Dict[str, Any], Dict[str, Any]]:
        rule, eval_records = self.retrieve_matching_rule(task_desc, current_obs, history)
        self.last_eval_records = eval_records
        self.active_rule = rule
        if rule:
            self.last_applied_rule = rule

        rule_context = self.format_rule_context(rule) if rule else ""
        combined_context = f"{rule_context}\n\n{extra_context}" if extra_context else rule_context

        return super().select_action(
            task_desc=task_desc,
            current_obs=current_obs,
            history=history,
            valid_actions=valid_actions,
            extra_context=combined_context
        )

    def revise_on_counterexample(self, failed_task_desc: str, failed_obs: str, failed_trace: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Counterexample-Driven Local Revision:
        1. Compare counterexample with supporting positive cases.
        2. Propose candidate specializing condition via LLM.
        3. Independently verify candidate condition with RegressionVerifier against historical support cases.
        4. Accept or reject deterministically.
        """
        target_rule = self.active_rule or self.last_applied_rule
        if not target_rule:
            return {"status": "SKIPPED", "reason": "No active rule was applied."}

        rule = target_rule
        support_cases = rule.get("support_cases", []) or rule.get("support_trajectories", [])
        support_summaries = [f"- Task: {c.get('task_desc', c.get('task_description'))} (target: {c.get('target', 'N/A')})" for c in support_cases]

        cnt_target = extract_target_entity(failed_task_desc)
        counterexample_case = {
            "task_id": "current_counterexample",
            "task_desc": failed_task_desc,
            "target": cnt_target,
            "key_obs": failed_obs
        }

        diagnosis_prompt = f"""You are diagnosing an applicability condition mismatch for a decision rule.
The following rule was applied because its goal matched, but the task FAILED.

Rule Goal: {rule.get('goal')}
Current Conditions: {rule.get('applicability_conditions')}
Rule Action: {rule.get('recovery_procedure')}

Supporting Historical Tasks where this rule SUCCEEDED:
{chr(10).join(support_summaries) if support_summaries else "None recorded"}

New Counterexample Task where this rule FAILED:
Task: {failed_task_desc}
Final Observation: {failed_obs}

Find the KEY DIFFERENCE between the historical successful tasks and this failed task.
Propose a single specializing condition that must be satisfied.
Output ONLY a JSON object:
{{
  "distinguishing_feature": "e.g., target is non-metallic, or substance is solid chocolate",
  "specializing_condition": "exact condition string (e.g. 'the target object must be metal' or 'the substance must be liquid')"
}}
"""
        diag_json, stats = self.llm.generate_json(diagnosis_prompt, max_new_tokens=256)
        spec_cond = diag_json.get("specializing_condition", "")

        # Independent Deterministic Regression Verification
        verifier = RegressionVerifier()
        verif_report = verifier.verify_candidate_condition(
            candidate_condition=spec_cond,
            support_cases=support_cases,
            counterexample_case=counterexample_case
        )

        rule_id = rule.get("rule_id")
        if verif_report["decision"] == "ACCEPT":
            for i, r in enumerate(self.rule_library):
                if r.get("rule_id") == rule_id:
                    if spec_cond not in self.rule_library[i]["applicability_conditions"]:
                        self.rule_library[i]["applicability_conditions"].append(spec_cond)
                    self.rule_library[i]["status"] = "specialized"
                    if "version" in self.rule_library[i]:
                        self.rule_library[i]["version"] += 1
                    return {
                        "status": "REVISED_SUCCESS",
                        "rule_id": rule_id,
                        "added_condition": spec_cond,
                        "verification_report": verif_report,
                        "stats": stats
                    }
        else:
            for i, r in enumerate(self.rule_library):
                if r.get("rule_id") == rule_id:
                    self.rule_library[i]["status"] = "uncertain"
            return {
                "status": "REVISION_REJECTED",
                "rule_id": rule_id,
                "candidate_condition": spec_cond,
                "verification_report": verif_report,
                "stats": stats
            }

        return {"status": "NO_CHANGE", "stats": stats}
