"""
Base ReAct Agent (No Memory):
Acts as Control Group A without cross-task memory.
Provides disciplined candidate filtering preventing illegal room-focus actions,
and tracks proposed vs executed action telemetry.
"""

from typing import List, Dict, Any, Tuple
import json
import re

from condition_evaluator import extract_target_entity, KNOWN_ROOMS


SYSTEM_PROMPT = """You are an intelligent agent interacting with the ScienceWorld scientific virtual environment.
Your objective is to complete the specified task step by step.

Guidelines:
1. Check the task description for the target object and its location. To navigate to a room, use 'teleport to <room>' (e.g. 'teleport to kitchen' or 'teleport to workshop').
2. NEVER use 'focus on <room>' (e.g. never 'focus on kitchen', never 'focus on workshop'). In ScienceWorld, focusing on a room or door is illegal and causes failure. Focus ONLY on specific physical target objects (e.g. 'focus on ice', 'focus on water', 'focus on aluminum foil').
3. Choose the single most effective action from the candidate valid actions.

Output ONLY a JSON object with this exact schema:
{
  "thought": "Your concise step-by-step reasoning",
  "action": "the exact action string to execute"
}
"""


ILLEGAL_FOCUS_TARGETS = {
    "door", "air", "hallway", "room", "agent", "wall", "ceiling", "floor"
} | KNOWN_ROOMS


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
    ) -> Tuple[str, str, Dict[str, Any], Dict[str, Any]]:
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

        proposed_action = str(action) if action is not None else ""
        adapter_modified = False
        adapter_reason = "exact_match"

        # Fallback if action is empty or invalid string
        if not action or not isinstance(action, str):
            action = sample_actions[0] if sample_actions else "look around"
            adapter_modified = True
            adapter_reason = "empty_or_non_string"

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
                    adapter_modified = True
                    adapter_reason = "fuzzy_keyword_match"
                    break
            if not matched and sample_actions:
                action = sample_actions[0]
                adapter_modified = True
                adapter_reason = "fallback_to_candidate_zero"

        action_telemetry = {
            "proposed_action": proposed_action,
            "executed_action": action,
            "adapter_modified": adapter_modified,
            "adapter_reason": adapter_reason
        }

        return action, thought, stats, action_telemetry

    def _filter_candidate_actions(self, valid_actions: List[str], task_desc: str, current_obs: str) -> List[str]:
        if not valid_actions:
            return []
        task_words = set(re_word.lower() for re_word in task_desc.replace('.', ' ').replace(',', ' ').split() if len(re_word) > 2)
        obs_words = set(re_word.lower() for re_word in current_obs.replace('.', ' ').replace(',', ' ').split() if len(re_word) > 2)
        key_words = task_words | obs_words
        target = extract_target_entity(task_desc).lower()

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
                    score += 12
            elif act_lower.startswith(("pick up", "drop", "move", "pour", "activate", "connect")):
                score += 3
            elif act_lower.startswith("focus on "):
                # Penalize illegal focus actions (focus on rooms, doors, air, etc.)
                if any(bad in act_lower for bad in ILLEGAL_FOCUS_TARGETS):
                    score -= 30
                elif target and target in act_lower:
                    score += 15
                else:
                    score += 2

            scored.append((score, act))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored]
