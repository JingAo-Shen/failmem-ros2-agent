"""
Closest Literature Baseline (Group C: BASM + ExpeL):
Maintains boundary-aware rules (BASM-style schema: goal, applicability_conditions, recovery_procedure).
When a rule fails on a new counterexample, performs unconstrained textual rewrite (ExpeL-style EDIT operator)
WITHOUT verifying retention or consistency against prior supporting trajectories.
"""

from typing import List, Dict, Any, Tuple, Optional
import json
from agents.base_agent import BaseAgent


STOP_WORDS = {"the", "and", "for", "are", "was", "were", "with", "from", "that", "this", "have", "has", "must", "should", "been", "there", "some", "also", "then", "into", "their", "here"}


def extract_keywords(text: str) -> List[str]:
    return [w for w in text.lower().split() if w not in STOP_WORDS and len(w) >= 3]


class LiteratureMemoryAgent(BaseAgent):
    def __init__(self, llm_client, rule_library: List[Dict[str, Any]] = None):
        super().__init__(llm_client)
        self.name = "C_Literature_BASM_ExpeL"
        self.rule_library = rule_library or []
        self.active_rule = None
        self.last_applied_rule = None

    def reset_episode_state(self):
        self.active_rule = None
        self.last_applied_rule = None

    def retrieve_matching_rule(self, task_desc: str, current_obs: str) -> Optional[Dict[str, Any]]:
        task_lower = task_desc.lower()
        obs_lower = current_obs.lower()

        for rule in self.rule_library:
            goal = rule.get("goal", "").lower()
            goal_words = extract_keywords(goal)
            if any(w in task_lower for w in goal_words):
                # Check applicability conditions (keyword matching)
                conds = rule.get("applicability_conditions", [])
                match_all = True
                for c in conds:
                    c_words = extract_keywords(c)
                    # If condition keywords are not satisfied by task_desc or observation
                    if c_words and not any(w in task_lower or w in obs_lower for w in c_words):
                        match_all = False
                        break
                if match_all:
                    return rule
        return None

    def format_rule_context(self, rule: Dict[str, Any]) -> str:
        return f"""### Retrieved Boundary-Aware Skill Memory (BASM):
Goal: {rule.get('goal')}
Applicability Conditions: {', '.join(rule.get('applicability_conditions', []))}
Avoidance Rules: {', '.join(rule.get('avoidance_rules', []))}
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
        if rule:
            self.active_rule = rule
            self.last_applied_rule = rule

        rule_context = self.format_rule_context(self.active_rule or self.last_applied_rule) if (self.active_rule or self.last_applied_rule) else ""
        combined_context = f"{rule_context}\n\n{extra_context}" if extra_context else rule_context

        return super().select_action(
            task_desc=task_desc,
            current_obs=current_obs,
            history=history,
            valid_actions=valid_actions,
            extra_context=combined_context
        )

    def update_on_counterexample(self, failed_task_desc: str, failed_trace: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        ExpeL-style unconstrained prompt rewrite:
        Asks LLM to EDIT the rule based on the failure trace, with no provenance check.
        """
        target_rule = self.active_rule or self.last_applied_rule
        if not target_rule:
            return {"updated": False, "reason": "No active rule was applied."}

        prompt = f"""You are maintaining a decision rule library.
The following rule was applied to a task, but the agent FAILED to complete the task.

Existing Rule:
{json.dumps(target_rule, indent=2)}

Failed Task Description:
{failed_task_desc}

Execution Failure Trace (Last 5 steps):
{json.dumps(failed_trace[-5:], indent=2)}

Following the ExpeL EDIT operator:
Revise this rule to account for this failure.
Output ONLY a JSON object with the revised rule:
{{
  "goal": "{target_rule.get('goal')}",
  "applicability_conditions": ["revised or new condition list"],
  "avoidance_rules": ["revised avoidance rules"],
  "recovery_procedure": "revised procedure string"
}}
"""
        revised_json, stats = self.llm.generate_json(prompt, max_new_tokens=256)
        if "goal" in revised_json and "applicability_conditions" in revised_json:
            old_rule_id = self.active_rule.get("rule_id", "rule_0")
            revised_json["rule_id"] = old_rule_id
            # Replace directly in library without checking historical support
            for i, r in enumerate(self.rule_library):
                if r.get("rule_id") == old_rule_id:
                    self.rule_library[i] = revised_json
                    break
            return {"updated": True, "old_rule": self.active_rule, "new_rule": revised_json, "stats": stats}
        return {"updated": False, "reason": "Failed to parse revised JSON.", "stats": stats}
