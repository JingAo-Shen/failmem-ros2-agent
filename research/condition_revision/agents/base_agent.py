"""
Base ReAct Agent (No Memory):
Acts as Control Group A without cross-task memory.
Provides disciplined candidate filtering preventing illegal room-focus actions,
and tracks proposed vs executed action telemetry.
"""

from typing import List, Dict, Any, Tuple, Optional
import json
import re

from condition_evaluator import extract_target_entity, KNOWN_ROOMS

try:
    from remote_llm_client import StepRequestBudgetExhaustedError
except ImportError:
    class StepRequestBudgetExhaustedError(Exception):
        pass


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

SYSTEM_PROMPT_NO_CANDIDATES = """You are an intelligent agent interacting with the ScienceWorld scientific virtual environment.
Your objective is to complete the specified task step by step.

Guidelines:
1. Check the task description for the target object and its location. To navigate to a room, use 'teleport to <room>' (e.g. 'teleport to kitchen' or 'teleport to workshop').
2. NEVER use 'focus on <room>' (e.g. never 'focus on kitchen', never 'focus on workshop'). In ScienceWorld, focusing on a room or door is illegal and causes failure. Focus ONLY on specific physical target objects (e.g. 'focus on ice', 'focus on water', 'focus on aluminum foil').
3. Choose the single most effective valid action.

Output ONLY a JSON object with this exact schema:
{
  "thought": "Your concise step-by-step reasoning",
  "action": "the exact action string to execute"
}
"""

SYSTEM_PROMPT_ACTION_TEMPLATES = """You are an intelligent agent interacting with the ScienceWorld scientific virtual environment.
Your objective is to complete the specified task step by step.

Guidelines:
1. Check the task description for the target object and its location. To navigate to a room, use 'teleport to <room>' (e.g. 'teleport to kitchen' or 'teleport to workshop').
2. NEVER use 'focus on <room>' (e.g. never 'focus on kitchen', never 'focus on workshop'). In ScienceWorld, focusing on a room or door is illegal and causes failure. Focus ONLY on specific physical target objects (e.g. 'focus on ice', 'focus on water', 'focus on aluminum foil').
3. Choose the single most effective valid action.

Output ONLY a JSON object with this exact schema:
{
  "thought": "Your concise step-by-step reasoning",
  "action": "the exact action string to execute"
}
"""

SCIENCEWORLD_ACTION_TEMPLATES: List[str] = [
    "activate OBJ",
    "close OBJ",
    "connect OBJ to OBJ",
    "deactivate OBJ",
    "disconnect OBJ",
    "dunk OBJ in OBJ",
    "eat OBJ",
    "flush OBJ",
    "focus on OBJ",
    "go OBJ",
    "inventory",
    "look around",
    "look at OBJ",
    "look in OBJ",
    "mix OBJ",
    "move OBJ to OBJ",
    "open OBJ",
    "pick up OBJ",
    "pour OBJ in OBJ",
    "put down OBJ",
    "read OBJ",
    "reset task",
    "task",
    "teleport OBJ",
    "use OBJ on OBJ",
    "wait",
    "wait1",
]


ILLEGAL_FOCUS_TARGETS = {
    "door", "air", "hallway", "room", "agent", "wall", "ceiling", "floor"
} | KNOWN_ROOMS


class BaseAgent:
    def __init__(
        self,
        llm_client,
        adapter_mode: str = "current",
        history_mode: str = "last5",
        max_new_tokens: Optional[int] = None,
        prompt_mode: str = "default",
        action_templates: Optional[List[str]] = None
    ):
        self.llm = llm_client
        self.name = "A_NoMemory"
        self.adapter_mode = adapter_mode
        self.history_mode = history_mode
        self.max_new_tokens = max_new_tokens
        self.prompt_mode = prompt_mode
        self.action_templates = list(action_templates) if action_templates is not None else None

    def select_action(
        self,
        task_desc: str,
        current_obs: str,
        history: List[Tuple[str, str]],
        valid_actions: List[str],
        extra_context: str = "",
        generic_semantics: str = "",
        action_templates: Optional[List[str]] = None
    ) -> Tuple[Optional[str], str, Dict[str, Any], Dict[str, Any]]:
        # Format history
        hist_str = ""
        if history:
            if self.history_mode == "all_steps":
                recent = history
            else:
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

        # Sample valid actions to show in prompt or log in telemetry
        sample_actions = self._filter_candidate_actions(valid_actions, task_desc, current_obs)
        active_templates = action_templates if action_templates is not None else self.action_templates

        if self.prompt_mode == "no_candidates":
            sys_prompt = SYSTEM_PROMPT_NO_CANDIDATES
            user_prompt = f"""Task Description:
{task_desc}

Current Observation:
{current_obs}

Recent Execution History:
{hist_str}
"""
        elif self.prompt_mode == "action_templates":
            if not active_templates or not isinstance(active_templates, (list, tuple)):
                raise ValueError("action_templates mode requires explicit action_templates from environment; silent fallback to hardcoded list is forbidden.")
            sys_prompt = SYSTEM_PROMPT_ACTION_TEMPLATES
            templates_formatted = "\n".join(f"- {tmpl}" for tmpl in active_templates)
            user_prompt = f"""Task Description:
{task_desc}

Current Observation:
{current_obs}

Recent Execution History:
{hist_str}

Action Syntax Reference:
These templates describe action syntax. They do not guarantee that an action is executable in the current state.
{templates_formatted}
"""
        else:
            sys_prompt = SYSTEM_PROMPT
            user_prompt = f"""Task Description:
{task_desc}

Current Observation:
{current_obs}

Recent Execution History:
{hist_str}

Candidate Valid Actions (select one from these or construct a valid action):
{chr(10).join(f"- {act}" for act in sample_actions[:25])}
"""
        prefix_slots = []
        if generic_semantics and isinstance(generic_semantics, str) and generic_semantics.strip():
            prefix_slots.append(generic_semantics.strip())
        if extra_context and isinstance(extra_context, str) and extra_context.strip():
            prefix_slots.append(extra_context.strip())

        if prefix_slots:
            user_prompt = "\n\n".join(prefix_slots) + "\n\n" + user_prompt

        gen_kwargs = {}
        if self.max_new_tokens is not None:
            gen_kwargs["max_new_tokens"] = self.max_new_tokens

        try:
            parsed_json, stats = self.llm.generate_json(
                user_prompt, system_prompt=sys_prompt, max_step_attempts=2, **gen_kwargs
            )
        except StepRequestBudgetExhaustedError as e:
            parsed_json = {
                "thought": "",
                "action": None,
                "budget_exhausted": True,
                "parse_error": False,
                "transport_error": True,
                "termination_reason": "step_request_budget_exhausted",
                "error": str(e)
            }
            stats = {
                "calls": getattr(e, "attempts_count", 2),
                "total_calls": getattr(e, "attempts_count", 2),
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "retry_attempted": (getattr(e, "attempts_count", 2) > 1),
                "finish_reason": "error",
                "empty_content": True,
                "hit_output_token_limit": False,
                "parse_error": False,
                "attempts": getattr(e, "attempts", []),
                "client_cumulative_calls": getattr(self.llm, "total_calls", 2),
                "client_known_cost_usd": round(getattr(self.llm, "known_cost_usd", 0.0), 6),
                "client_reserved_cost_usd": round(getattr(self.llm, "unknown_reserved_cost_usd", 0.0), 6),
                "client_total_cost_usd": round(getattr(self.llm, "known_cost_usd", 0.0) + getattr(self.llm, "unknown_reserved_cost_usd", 0.0), 6)
            }

        if parsed_json.get("budget_exhausted"):
            telemetry = {
                "system_prompt": sys_prompt,
                "user_prompt": user_prompt,
                "prompt_mode": self.prompt_mode,
                "raw_response": stats.get("raw_text", ""),
                "parsed_response": parsed_json,
                "proposed_action": "",
                "executed_action": None,
                "adapter_modified": True,
                "alias_applied": False,
                "adapter_reason": "step_request_budget_exhausted",
                "budget_exhausted": True,
                "termination_reason": "step_request_budget_exhausted",
                "valid_candidates_count": len(valid_actions),
                "sample_candidates": sample_actions[:10]
            }
            return None, "", stats, telemetry
        thought = parsed_json.get("thought", "")
        action = parsed_json.get("action", "")

        proposed_action = str(action) if action is not None else ""
        adapter_modified = False
        is_ambiguous_menu = (
            isinstance(current_obs, str) and
            "Ambiguous request:" in current_obs and
            "blank to cancel" in current_obs
        )
        has_action_key = isinstance(parsed_json, dict) and ("action" in parsed_json)
        raw_action = parsed_json.get("action") if has_action_key else None
        is_blank_str = (has_action_key and isinstance(raw_action, str) and raw_action.strip() == "")

        alias_applied = False
        if self.adapter_mode == "native":
            if is_ambiguous_menu and is_blank_str:
                # In ambiguous cancellation menu, pass raw empty string to cancel
                action = ""
                adapter_modified = False
                adapter_reason = "menu_blank_cancellation"
            elif not action or not isinstance(action, str) or not action.strip():
                action = None
                adapter_modified = True
                adapter_reason = "empty_or_non_string_terminate"
            else:
                action = action.strip()
                adapter_modified = (action != proposed_action)
                adapter_reason = "native_passthrough"
        elif self.adapter_mode in ("strict", "strict_alias"):
            clean_action = proposed_action.strip().lower()
            valid_lower = [v.lower() for v in valid_actions]

            look_around_action = None
            if "look around" in valid_lower:
                look_around_action = valid_actions[valid_lower.index("look around")]

            if not action or not isinstance(action, str):
                if look_around_action:
                    action = look_around_action
                    adapter_modified = True
                    adapter_reason = "empty_or_non_string_fallback_look_around"
                else:
                    action = None
                    adapter_modified = True
                    adapter_reason = "empty_look_around_unavailable_terminate"
            elif clean_action in valid_lower:
                idx = valid_lower.index(clean_action)
                action = valid_actions[idx]
                adapter_modified = (action != proposed_action)
                adapter_reason = "exact_match"
            elif self.adapter_mode == "strict_alias" and clean_action.startswith(("focus ", "move ", "place ", "put ")) and "book (the foundations of the origin of species)" in clean_action:
                aliased = clean_action.replace("book (the foundations of the origin of species)", "book")
                if aliased.startswith(("place ", "put ")):
                    m_in = re.match(r"^(?:place|put)\s+(.+?)\s+in\s+(.+)$", aliased)
                    m_to = re.match(r"^(?:place|put)\s+(.+?)\s+to\s+(.+)$", aliased)
                    converted = None
                    reason_tag = ""
                    if m_in:
                        obj = m_in.group(1).strip()
                        dest = m_in.group(2).strip()
                        converted = f"move {obj} to {dest}"
                        reason_tag = "alias_and_synonym_place_in_to_move_to"
                    elif m_to:
                        obj = m_to.group(1).strip()
                        dest = m_to.group(2).strip()
                        converted = f"move {obj} to {dest}"
                        reason_tag = "alias_and_synonym_place_to_to_move_to"

                    if converted and converted in valid_lower:
                        idx = valid_lower.index(converted)
                        action = valid_actions[idx]
                        adapter_modified = True
                        alias_applied = True
                        adapter_reason = reason_tag
                    elif aliased in valid_lower:
                        idx = valid_lower.index(aliased)
                        action = valid_actions[idx]
                        adapter_modified = True
                        alias_applied = True
                        adapter_reason = "alias_book_name_normalized"
                    else:
                        if look_around_action:
                            action = look_around_action
                            adapter_modified = True
                            adapter_reason = "unmatched_placement_fallback_look_around"
                        else:
                            action = None
                            adapter_modified = True
                            adapter_reason = "unmatched_placement_look_around_unavailable_terminate"
                elif aliased in valid_lower:
                    idx = valid_lower.index(aliased)
                    action = valid_actions[idx]
                    adapter_modified = True
                    alias_applied = True
                    adapter_reason = "alias_book_name_normalized"
                else:
                    if look_around_action:
                        action = look_around_action
                        adapter_modified = True
                        adapter_reason = "unmatched_alias_fallback_look_around"
                    else:
                        action = None
                        adapter_modified = True
                        adapter_reason = "unmatched_look_around_unavailable_terminate"
            elif clean_action.startswith(("place ", "put ")):
                m_in = re.match(r"^(?:place|put)\s+(.+?)\s+in\s+(.+)$", clean_action)
                m_to = re.match(r"^(?:place|put)\s+(.+?)\s+to\s+(.+)$", clean_action)
                converted = None
                reason_tag = ""
                if m_in:
                    obj = m_in.group(1).strip()
                    dest = m_in.group(2).strip()
                    converted = f"move {obj} to {dest}"
                    reason_tag = "synonym_place_in_to_move_to"
                elif m_to:
                    obj = m_to.group(1).strip()
                    dest = m_to.group(2).strip()
                    converted = f"move {obj} to {dest}"
                    reason_tag = "synonym_place_to_to_move_to"

                if converted and converted in valid_lower:
                    idx = valid_lower.index(converted)
                    action = valid_actions[idx]
                    adapter_modified = True
                    adapter_reason = reason_tag
                else:
                    if look_around_action:
                        action = look_around_action
                        adapter_modified = True
                        adapter_reason = "unmatched_placement_fallback_look_around"
                    else:
                        action = None
                        adapter_modified = True
                        adapter_reason = "unmatched_placement_look_around_unavailable_terminate"
            else:
                if look_around_action:
                    action = look_around_action
                    adapter_modified = True
                    adapter_reason = "unmatched_action_strict_fallback_look_around"
                else:
                    action = None
                    adapter_modified = True
                    adapter_reason = "unmatched_look_around_unavailable_terminate"
        else:
            # Fallback if action is empty or invalid string
            if not action or not isinstance(action, str):
                action = sample_actions[0] if sample_actions else "look around"
                adapter_modified = True
                adapter_reason = "empty_or_non_string"

            # Action matching and transparent normalization
            clean_action = action.strip().lower()
            valid_lower = [v.lower() for v in valid_actions]

            if clean_action in valid_lower:
                idx = valid_lower.index(clean_action)
                action = valid_actions[idx]
                adapter_reason = "exact_match"
            elif valid_actions:
                # 1. Place/put synonym normalization to move
                if clean_action.startswith(("place ", "put ")):
                    cand = re.sub(r"^(?:place|put)\s+", "move ", clean_action)
                    cand_to = re.sub(r"\s+in\s+", " to ", cand)
                    if cand_to in valid_lower:
                        action = valid_actions[valid_lower.index(cand_to)]
                        adapter_modified = True
                        adapter_reason = "synonym_place_in_to_move_to"
                    elif cand in valid_lower:
                        action = valid_actions[valid_lower.index(cand)]
                        adapter_modified = True
                        adapter_reason = "synonym_place_to_move"
                    else:
                        action = "look around" if "look around" in valid_actions else sample_actions[0]
                        adapter_modified = True
                        adapter_reason = "invalid_placement_fallback_look_around"
                else:
                    # 2. Strict verb-preserving match (never turn a move/place into focus or vice-versa)
                    verb = clean_action.split()[0] if clean_action.split() else ""
                    matched = False
                    for v in sample_actions:
                        if v.lower().startswith(verb):
                            target_nouns = [w for w in clean_action.split() if len(w) > 3 and w != verb]
                            if any(n in v.lower() for n in target_nouns):
                                action = v
                                matched = True
                                adapter_modified = True
                                adapter_reason = f"same_verb_match_{verb}"
                                break
                    if not matched:
                        # Neutral fallback to look around rather than executing an arbitrary action
                        action = "look around" if "look around" in valid_actions else (sample_actions[0] if sample_actions else "look around")
                        adapter_modified = True
                        adapter_reason = "unmatched_action_neutral_fallback"

        action_telemetry = {
            "system_prompt": sys_prompt,
            "user_prompt": user_prompt,
            "prompt_mode": self.prompt_mode,
            "raw_response": stats.get("raw_text", ""),
            "parsed_response": parsed_json,
            "proposed_action": proposed_action,
            "executed_action": action,
            "adapter_modified": adapter_modified,
            "alias_applied": alias_applied,
            "adapter_reason": adapter_reason,
            "candidate_actions": sample_actions if self.prompt_mode != "action_templates" else active_templates,
            "history_mode": self.history_mode,
            "proposed_action_in_candidate_list": (proposed_action.strip().lower() in [s.lower() for s in (active_templates if self.prompt_mode == "action_templates" else sample_actions)]),
            "executed_action_equals_trimmed_proposed": (action == proposed_action.strip()) if action is not None else False,
            "terminate_immediately": (action is None)
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
