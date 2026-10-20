"""
Natural Experience Extractor:
Extracts experiences from the Agent's own execution trajectories.
Maintains strict separation between:
1. Observed Facts (concrete states, actions, transitions)
2. LLM Explanation (causal interpretation of why it worked/failed)
3. Unverified Generalization (initial inductive leap/boundary hypothesis)
"""

import json
from typing import Dict, List, Any


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
    def __init__(self, llm_client):
        self.llm = llm_client

    def extract_from_trajectory(self, trajectory: Dict[str, Any]) -> Dict[str, Any]:
        task_desc = trajectory.get("task_description", "")
        success = trajectory.get("success", False)
        steps = trajectory.get("steps", [])

        steps_lines = []
        for i, s in enumerate(steps[:12]):
            steps_lines.append(f"Step {i+1}: Action: '{s.get('action')}' -> Obs: '{s.get('observation', '').strip()[:120]}'")

        prompt = EXPERIENCE_EXTRACTION_PROMPT.format(
            task_description=task_desc,
            success=success,
            steps_text="\n".join(steps_lines)
        )

        extracted_json, stats = self.llm.generate_json(prompt, max_new_tokens=384)
        if "goal" not in extracted_json or "applicability_conditions" not in extracted_json:
            # Do NOT synthesize human-written fallback rule
            return {
                "status": "PARSE_ERROR",
                "rule_id": f"parse_error_{trajectory.get('task_name')}_{trajectory.get('variation', 0)}",
                "raw_response": extracted_json,
                "stats": stats
            }

        extracted_json["rule_id"] = f"rule_{trajectory.get('task_name')}_{trajectory.get('variation', 0)}"
        extracted_json["support_trajectories"] = [{
            "task_name": trajectory.get("task_name"),
            "variation": trajectory.get("variation"),
            "task_description": task_desc,
            "target": trajectory.get("target", "default"),
            "success": success
        }]
        extracted_json["status"] = "active"
        return extracted_json
