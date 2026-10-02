"""
ReAct-style Structured Planner for FailMem Stage 2 Robot Agent.
Enforces:
  - Strict JSON tool schemas with verifiable decision_summary.
  - No heuristic guessing on parse failure (strict format validation & 1-shot retry).
  - Multi-attribute memory retrieval over shared known state.
"""
from typing import Dict, Any, List, Optional, Tuple
import json
import re
from .llm_backend import LLMBackend
from ..memory.baselines import BaseMemoryAdapter


VALID_TOOLS = {
    "navigate": ["target_zone"],
    "observe": ["target"],
    "query_status": ["entity"],
    "pickup": ["package_id", "from_location"],
    "deliver": ["package_id", "recipient"],
    "recharge": [],
    "acquire_credential": ["credential_name"],
}

SYSTEM_PROMPT = """You are an autonomous mobile delivery robot operating in an indoor office environment.
Your objective is to complete the specified delivery task safely, efficiently, and without violating constraints.

### Available Tools:
1. `navigate(target_zone)`: Move to an adjacent room/corridor.
   - Known zones: Lobby, Corridor_North, Corridor_South, Office_A, Office_B, Lab_Secure.
   - Adjacencies:
     * Lobby <-> Corridor_North (via door_north), Lobby <-> Corridor_South (via door_south)
     * Corridor_North <-> Office_A (via door_office_a), Corridor_North <-> Office_B (via door_office_b), Corridor_North <-> Corridor_South
     * Corridor_South <-> Office_A, Corridor_South <-> Lab_Secure (via door_lab, REQUIRES security_badge)
2. `observe(target)`: Perform sensor scan on a door ('door_north', 'door_south', 'door_lab', 'door_office_a', 'door_office_b') or inspect current room.
3. `query_status(entity)`: Query directory service for recipient availability ('Alice', 'Bob', 'Charlie') or 'battery'.
4. `pickup(package_id, from_location)`: Pick up package from current room.
5. `deliver(package_id, recipient)`: Hand over package to recipient in target room.
6. `recharge()`: Fully recharge battery (only works at 'Lobby').
7. `acquire_credential(credential_name)`: Pick up key/badge (e.g. 'security_badge' from Office_A).

### Response Format:
You must output strictly a single JSON object inside ```json ... ``` codeblock:
```json
{
  "decision_summary": "Brief 1-2 sentence verifiable ground for choosing this action.",
  "action": "<tool_name>",
  "params": { "<param_name>": "<param_value>" }
}
```
Ground-truth environment state is hidden. Rely only on visible robot status, tool feedback, and verified past experiences."""


class AgentPlanner:
    def __init__(self, llm_backend: LLMBackend, memory_adapter: BaseMemoryAdapter):
        self.llm = llm_backend
        self.memory = memory_adapter

    def decide_next_action(
        self,
        task_instruction: str,
        current_state: Dict[str, Any],
        known_state: Dict[str, Any],
        step_history: List[Dict[str, Any]],
        task_id: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Plans the next action.
        Returns: (parsed_decision_dict, llm_metadata)
        """
        # 1. Multi-attribute memory query context
        context_query = {
            "current_location": current_state.get("robot_location"),
            "inventory": current_state.get("inventory", []),
            "target": current_state.get("robot_location"),
            "credentials": current_state.get("credentials", []),
        }
        retrieved_memories = self.memory.retrieve_relevant_memories(known_state, context_query)

        # 2. Build User Prompt
        user_prompt_lines = [
            f"### Current Task: {task_instruction}",
            f"### Current Robot Status:",
            f"- Location: {current_state.get('robot_location')}",
            f"- Battery: {current_state.get('battery')}%",
            f"- Inventory: {current_state.get('inventory')}",
            f"- Credentials: {current_state.get('credentials')}",
            f"- Undelivered Packages: {current_state.get('available_packages')}",
        ]

        if known_state:
            user_prompt_lines.append(f"### Known / Observed Environmental Facts: {known_state}")

        if retrieved_memories:
            user_prompt_lines.append("### Retrieved Past Experiences / Failure Memories:")
            for m in retrieved_memories:
                user_prompt_lines.append(f"- {m}")

        if step_history:
            user_prompt_lines.append("### Recent Action History in Current Task:")
            for h in step_history[-5:]:
                res = h.get("result", {})
                user_prompt_lines.append(f"- Step {h['step']}: {h['tool']}({h['params']}) -> [{res.get('status')}] {res.get('message')}")

        user_prompt_lines.append("\nPlease output your next action decision in JSON format.")
        user_prompt = "\n".join(user_prompt_lines)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 3. Call LLM
        gen_res = self.llm.generate(messages)
        content = gen_res.get("content", "")

        # 4. Strict JSON Parse with 1-shot retry
        decision, parse_ok = self._strict_parse_json(content)
        retry_used = False

        if not parse_ok:
            retry_used = True
            retry_messages = list(messages)
            retry_messages.append({"role": "assistant", "content": content})
            retry_messages.append({
                "role": "user",
                "content": f"Formatting Error: Could not parse output as valid JSON matching schema. Please output ONLY the JSON object with keys 'decision_summary', 'action', and 'params'."
            })
            retry_res = self.llm.generate(retry_messages)
            retry_content = retry_res.get("content", "")
            decision, parse_ok = self._strict_parse_json(retry_content)
            
            gen_res["prompt_tokens"] += retry_res.get("prompt_tokens", 0)
            gen_res["generated_tokens"] += retry_res.get("generated_tokens", 0)
            gen_res["latency_s"] += retry_res.get("latency_s", 0.0)

            if not parse_ok:
                decision = {
                    "decision_summary": "PARSE_FAILURE: LLM failed to produce valid JSON tool call after retry.",
                    "action": "parse_error",
                    "params": {"raw_output": retry_content or content},
                }

        metadata = {
            "prompt_tokens": gen_res.get("prompt_tokens", 0),
            "generated_tokens": gen_res.get("generated_tokens", 0),
            "latency_s": gen_res.get("latency_s", 0.0),
            "raw_response": content,
            "retry_used": retry_used,
            "parse_ok": parse_ok,
            "retrieved_memories": list(retrieved_memories),
        }

        return decision, metadata

    def _strict_parse_json(self, text: str) -> Tuple[Dict[str, Any], bool]:
        """Strict JSON parser validating required keys and tool schema."""
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            json_match2 = re.search(r"(\{.*\})", text, re.DOTALL)
            raw_json = json_match2.group(1) if json_match2 else text

        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "action" in parsed and "params" in parsed:
                action = parsed["action"]
                if action in VALID_TOOLS and isinstance(parsed["params"], dict):
                    if "decision_summary" not in parsed:
                        parsed["decision_summary"] = parsed.get("thought", "Action planned.")
                    return parsed, True
        except Exception:
            pass

        return {}, False
