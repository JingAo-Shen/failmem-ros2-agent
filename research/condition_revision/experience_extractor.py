"""
Natural Experience Extractor:
Extracts experiences from the Agent's own execution trajectories.
Maintains strict separation between:
1. Observed Facts (concrete states, actions, transitions)
2. LLM Explanation (causal interpretation of why it worked/failed)
3. Unverified Generalization (initial inductive leap/boundary hypothesis)

Unified Trajectory Interface (v2):
Accepts both 'task_desc' and 'task_description'.
Accepts 'executed_action', 'action', and 'model_action' across step logs.
Retains verifiable prompt-response debug logs.
"""

import json
from typing import Dict, List, Any, Optional


EXPERIENCE_EXTRACTION_PROMPT = """You are analyzing an agent's execution trajectory in a scientific interactive environment.
Your goal is to extract a reusable procedural lesson from this experience.

Task Description:
{task_description}

Final Task Success: {success}
Execution Steps:
{steps_text}

Analyze what happened and extract a reusable rule.
Maintain a strict distinction between observed facts, your explanation, and unverified generalizations.

Output ONLY a JSON object with this schema:
{{
  "goal": "concise description of the task goal (e.g., boil liquid substance)",
  "observed_facts": {{
    "trigger_state": "exact initial state or object configuration observed",
    "key_actions": ["key actions that led to success/recovery"],
    "outcome": "concrete final physical result"
  }},
  "llm_explanation": "why these actions produced this outcome",
  "applicability_conditions": ["list of explicit conditions under which this procedure applies"],
  "unverified_generalization": "broad generalization inferred from this single run",
  "avoidance_rules": ["actions to avoid based on this run"],
  "recovery_procedure": "step by step recommended action sequence"
}}
"""


class NaturalExperienceExtractor:
    def __init__(self, llm_client=None):
        self.llm = llm_client
        self.last_extraction_debug: Optional[Dict[str, Any]] = None

    def format_extraction_prompt(self, trajectory: Dict[str, Any]) -> str:
        """
        Formats the extraction prompt with robust interface support.
        Guarantees non-empty task description and executed action representation.
        """
        task_desc = trajectory.get("task_description") or trajectory.get("task_desc", "")
        success = trajectory.get("success", False)
        steps = trajectory.get("steps", [])

        steps_lines = []
        for i, s in enumerate(steps[:12]):
            act = s.get("executed_action") or s.get("action") or s.get("model_action", "")
            obs = s.get("observation", "")
            steps_lines.append(f"Step {i+1}: Action: '{act}' -> Obs: '{obs.strip()[:120]}'")

        return EXPERIENCE_EXTRACTION_PROMPT.format(
            task_description=task_desc,
            success=success,
            steps_text="\n".join(steps_lines)
        )

    def extract_from_trajectory(self, trajectory: Dict[str, Any]) -> Dict[str, Any]:
        task_desc = trajectory.get("task_description") or trajectory.get("task_desc", "")
        success = trajectory.get("success", False)
        prompt = self.format_extraction_prompt(trajectory)

        if not self.llm:
            raise ValueError("LLMClient is required to perform natural experience extraction.")

        extracted_json, stats = self.llm.generate_json(prompt, max_new_tokens=384)

        # Record extraction debug without circular reference
        self.last_extraction_debug = {
            "prompt": prompt,
            "raw_response": dict(extracted_json),
            "stats": stats,
            "trajectory_id": trajectory.get("episode_id", trajectory.get("task_id", "unknown"))
        }

        if "goal" not in extracted_json or "applicability_conditions" not in extracted_json:
            # Do NOT synthesize human-written fallback rule
            return {
                "status": "PARSE_ERROR",
                "rule_id": f"parse_error_{trajectory.get('task_name')}_{trajectory.get('variation', 0)}",
                "raw_response": dict(extracted_json),
                "stats": stats
            }

        extracted_json["rule_id"] = f"rule_{trajectory.get('task_name')}_{trajectory.get('variation', 0)}"
        extracted_json["source_interface"] = "unified_v2"
        extracted_json["support_trajectories"] = [{
            "task_name": trajectory.get("task_name"),
            "variation": trajectory.get("variation"),
            "task_description": task_desc,
            "task_desc": task_desc,
            "target": trajectory.get("target", "default"),
            "success": success
        }]
        extracted_json["status"] = "active"
        return extracted_json
