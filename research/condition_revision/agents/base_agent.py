"""
Base ReAct Agent (No Memory):
Acts as Control Group A without cross-task memory.
"""

from typing import List, Dict, Any, Tuple
import json


SYSTEM_PROMPT = """You are an intelligent agent interacting with the ScienceWorld scientific virtual environment.
Your objective is to complete the specified task step by step.

Guidelines:
1. Carefully check where the target object is located in the task description (e.g. 'located around the workshop' or 'near the kitchen').
2. If you are not in that room yet, your first action should be to navigate or teleport there (e.g. 'teleport to workshop' or 'teleport to kitchen').
3. Only use 'focus on <target>' once the target object is in your current room or inventory. Never focus on doors, air, or unrelated furniture.
4. Choose the single most effective action from the candidate valid actions.

Output ONLY a JSON object with this exact schema:
{
  "thought": "Your concise step-by-step reasoning",
  "action": "the exact action string to execute"
}
"""


class BaseAgent:
    def __init__(self, llm_client):
        self.llm = llm_client
        self.name = "A_NoMemory"

    def select_action(
        self,
        task_desc: str,
        current_obs: str,
        history: List[Tuple[str, str]],
        valid_actions: List[str],
        extra_context: str = ""
    ) -> Tuple[str, str, Dict[str, Any]]:
        # Format history
        hist_str = ""
        if history:
            recent = history[-5:]
            hist_lines = []
            for i, item in enumerate(recent):
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    a, o = item[0], item[1]
                    hist_lines.append(f"Step -{len(recent)-i}: Action='{a}' -> Obs='{str(o).strip()[:150]}'")
                else:
                    hist_lines.append(f"Step -{len(recent)-i}: Action='{item}'")
            hist_str = "\n".join(hist_lines)
        else:
            hist_str = "None (Initial Step)"

        # Sample valid actions to show in prompt (up to 25 relevant candidates)
        # Prioritize actions matching key words in task_desc or room
        sample_actions = self._filter_candidate_actions(valid_actions, task_desc, current_obs)

        user_prompt = f"""Task Description:
{task_desc}

Current Observation:
{current_obs}

Recent Execution History:
{hist_str}

Candidate Valid Actions (select one from these or construct a valid action):
{chr(10).join(f"- {act}" for act in sample_actions[:25])}
"""
        if extra_context:
            user_prompt = f"{extra_context}\n\n{user_prompt}"

        parsed_json, stats = self.llm.generate_json(user_prompt, system_prompt=SYSTEM_PROMPT, max_new_tokens=128)
        thought = parsed_json.get("thought", "")
        action = parsed_json.get("action", "")

        # Fallback if action is empty or invalid string
        if not action or not isinstance(action, str):
            action = sample_actions[0] if sample_actions else "look around"

        # If action not in valid actions, pick closest or first
        clean_action = action.strip().lower()
        valid_lower = [v.lower() for v in valid_actions]
        if clean_action in valid_lower:
            idx = valid_lower.index(clean_action)
            action = valid_actions[idx]
        elif valid_actions:
            # find candidate that contains key words or fallback to first
            matched = False
            for v in sample_actions:
                if any(w in v for w in clean_action.split() if len(w) > 3):
                    action = v
                    matched = True
                    break
            if not matched and sample_actions:
                action = sample_actions[0]

        return action, thought, stats

    def _filter_candidate_actions(self, valid_actions: List[str], task_desc: str, current_obs: str) -> List[str]:
        if not valid_actions:
            return []
        task_words = set(re_word.lower() for re_word in task_desc.replace('.', ' ').replace(',', ' ').split() if len(re_word) > 2)
        obs_words = set(re_word.lower() for re_word in current_obs.replace('.', ' ').replace(',', ' ').split() if len(re_word) > 2)
        key_words = task_words | obs_words

        scored = []
        for act in valid_actions:
            score = 0
            act_lower = act.lower()
            for kw in key_words:
                if kw in act_lower:
                    score += 2
            if act_lower.startswith("teleport to "):
                dest = act_lower.replace("teleport to ", "").strip()
                if dest in task_desc.lower():
                    score += 10
            elif act_lower.startswith(("focus on", "pick up", "drop", "move", "pour", "activate")):
                score += 3
            # Penalize degenerate focus actions (like focusing on doors/air)
            if act_lower.startswith("focus on ") and any(bad in act_lower for bad in ["door", "air", "hallway", "room", "agent"]):
                score -= 15
            scored.append((score, act))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored]
