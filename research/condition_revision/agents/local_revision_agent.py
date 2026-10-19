"""
Counterexample-Driven Local Revision Agent (Group D Prototype):
Maintains rules with explicit provenance (pointers to supporting positive trajectories).
Upon encountering a counterexample:
1. Differential Diagnosis: Compares counterexample state against support trajectories.
2. Local Condition Specialization: Derives a discriminating condition literal to exclude the counterexample.
3. Regression Verification: Verifies that the specialized condition preserves coverage of all prior supporting cases.
4. Fallback Handling: If evidence is ambiguous or regression check fails, flags rule as uncertain instead of corrupting/deleting it.
"""

from typing import List, Dict, Any, Tuple, Optional
import json
from agents.base_agent import BaseAgent


class LocalRevisionAgent(BaseAgent):
    def __init__(self, llm_client, rule_library: List[Dict[str, Any]] = None):
        super().__init__(llm_client)
        self.name = "D_Counterexample_Local_Revision"
        self.rule_library = rule_library or []
        self.active_rule = None

    def retrieve_matching_rule(self, task_desc: str, current_obs: str) -> Optional[Dict[str, Any]]:
        task_lower = task_desc.lower()
        obs_lower = current_obs.lower()

        for rule in self.rule_library:
            if rule.get("status") == "uncertain":
                continue

            goal = rule.get("goal", "").lower()
            if any(w in task_lower for w in goal.split() if len(w) > 3):
                conds = rule.get("applicability_conditions", [])
                match_all = True
                for c in conds:
                    c_lower = c.lower()
                    # Check negative constraints (e.g., "must not be glass", "not solid")
                    if "not" in c_lower or "no " in c_lower:
                        forbidden_words = [w for w in c_lower.replace("not", "").replace("must", "").split() if len(w) > 3]
                        if any(w in task_lower or w in obs_lower for w in forbidden_words):
                            match_all = False
                            break
                    else:
                        req_words = [w for w in c_lower.split() if len(w) > 3]
                        if not any(w in task_lower or w in obs_lower for w in req_words):
                            match_all = False
                            break
                if match_all:
                    return rule
        return None

    def format_rule_context(self, rule: Dict[str, Any]) -> str:
        return f"""### Retrieved Validated Decision Rule (Local Condition Constrained):
Goal: {rule.get('goal')}
Applicability Conditions: {', '.join(rule.get('applicability_conditions', []))}
Verified Support Cases: {len(rule.get('support_trajectories', []))}
Recommended Procedure: {rule.get('recovery_procedure')}
"""

    def select_action(
        self,
        task_desc: str,
        current_obs: str,
        history: List[Tuple[str, str]],
        valid_actions: List[str],
        extra_context: str = ""
    ) -> Tuple[str, str, Dict[str, Any]]:
        rule = self.retrieve_matching_rule(task_desc, current_obs)
        self.active_rule = rule

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
        2. Propose candidate specializing condition.
        3. Verify against supporting cases to ensure no regression.
        """
        if not self.active_rule:
            return {"status": "SKIPPED", "reason": "No active rule was applied."}

        rule = self.active_rule
        support_cases = rule.get("support_trajectories", [])
        support_summaries = [f"- Task: {c.get('task_description')} (target: {c.get('target', 'N/A')})" for c in support_cases]

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
Output ONLY a JSON object:
{{
  "distinguishing_feature": "e.g., target is non-metallic, or substance is solid chocolate",
  "specializing_condition": "exact condition that must hold for the rule to apply (e.g. 'material must be metal' or 'substance must be liquid')",
  "applies_to_historical_successes": true or false,
  "excludes_counterexample": true or false
}}
"""
        diag_json, stats = self.llm.generate_json(diagnosis_prompt, max_new_tokens=256)
        spec_cond = diag_json.get("specializing_condition", "")
        applies_hist = diag_json.get("applies_to_historical_successes", False)
        excludes_cnt = diag_json.get("excludes_counterexample", False)

        # Regression Verification
        if spec_cond and applies_hist and excludes_cnt:
            # Verified: specialize the rule without deleting or corrupting
            rule_id = rule.get("rule_id")
            for i, r in enumerate(self.rule_library):
                if r.get("rule_id") == rule_id:
                    if spec_cond not in self.rule_library[i]["applicability_conditions"]:
                        self.rule_library[i]["applicability_conditions"].append(spec_cond)
                    self.rule_library[i]["status"] = "specialized"
                    return {
                        "status": "REVISED_SUCCESS",
                        "rule_id": rule_id,
                        "added_condition": spec_cond,
                        "distinguishing_feature": diag_json.get("distinguishing_feature"),
                        "stats": stats
                    }
        else:
            # Fallback: flag as uncertain
            rule_id = rule.get("rule_id")
            for i, r in enumerate(self.rule_library):
                if r.get("rule_id") == rule_id:
                    self.rule_library[i]["status"] = "uncertain"
                    return {
                        "status": "MARKED_UNCERTAIN",
                        "rule_id": rule_id,
                        "reason": "Could not find a clean discriminating condition that preserves all historical successes.",
                        "stats": stats
                    }

        return {"status": "NO_CHANGE", "stats": stats}
