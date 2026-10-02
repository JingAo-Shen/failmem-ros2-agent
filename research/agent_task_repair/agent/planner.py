"""
ReAct-style Structured Planner for FailMem Stage 2 Robot Agent.
Handles prompt construction, memory injection, tool schema specification,
and robust JSON decision parsing.
"""
from typing import Dict, Any, List, Optional, Tuple
import json
import re
from .llm_backend import LLMBackend
from ..memory.baselines import BaseMemoryAdapter


SYSTEM_PROMPT = """You are an autonomous mobile delivery robot operating in an indoor office and lab environment.
Your goal is to complete the given delivery task safely, efficiently, and without violating constraints.

### Available Tools:
1. `navigate(target_zone)`: Move to an adjacent room/corridor.
   - Known zones: Lobby, Corridor_North, Corridor_South, Office_A, Office_B, Lab_Secure.
   - Adjacencies:
     * Lobby <-> Corridor_North (via door_north), Lobby <-> Corridor_South (via door_south)
     * Corridor_North <-> Office_A (via door_office_a), Corridor_North <-> Office_B (via door_office_b), Corridor_North <-> Corridor_South
     * Corridor_South <-> Office_A, Corridor_South <-> Lab_Secure (via door_lab, REQUIRES security_badge)
2. `observe(target)`: Perform sensor scan on a door (e.g. 'door_north', 'door_lab') or inspect current room.
3. `query_status(entity)`: Query directory service for recipient availability (e.g. 'Alice', 'Bob', 'Charlie') or 'battery'.
4. `pickup(package_id, from_location)`: Pick up package (max capacity 2 items).
5. `deliver(package_id, recipient)`: Hand over package to recipient in target room.
6. `recharge()`: Fully recharge battery when located at 'Lobby'.
7. `acquire_credential(credential_name)`: Pick up key/badge (e.g. 'security_badge' from Office_A).

### Strict Rules:
- You must output your decision strictly as a JSON object inside ```json ... ``` codeblock.
- Format:
```json
{
  "thought": "Brief step-by-step reasoning explaining your plan and how you handle past experiences or observations.",
  "action": "<tool_name>",
  "params": { "<param_name>": "<param_value>" }
}
```
- Ground truth environment state is hidden. Rely only on visible state and tool feedback.
- If a path is blocked or locked, check your experiences to find detours or acquire missing credentials.
"""


class AgentPlanner:
    def __init__(self, llm_backend: LLMBackend, memory_adapter: BaseMemoryAdapter):
        self.llm = llm_backend
        self.memory = memory_adapter

    def decide_next_action(
        self,
        task_instruction: str,
        current_state: Dict[str, Any],
        step_history: List[Dict[str, Any]],
        task_id: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Plans the next action.
        Returns: (parsed_decision_dict, llm_metadata)
        """
        # 1. Retrieve relevant memories for current context
        context_query = {
            "current_location": current_state.get("robot_location"),
            "inventory": current_state.get("inventory"),
            "target": current_state.get("robot_location"),
        }
        retrieved_memories = self.memory.retrieve_relevant_memories(context_query)

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

        if retrieved_memories:
            user_prompt_lines.append("### Retrieved Past Experiences / Failure Memories:")
            for m in retrieved_memories:
                user_prompt_lines.append(f"- {m}")

        if step_history:
            user_prompt_lines.append("### Action History in Current Task:")
            for h in step_history[-5:]:  # show recent 5 steps
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

        # 4. Parse JSON
        decision = self._parse_json_decision(content, current_state)
        
        metadata = {
            "prompt_tokens": gen_res.get("prompt_tokens", 0),
            "generated_tokens": gen_res.get("generated_tokens", 0),
            "latency_s": gen_res.get("latency_s", 0.0),
            "raw_response": content,
            "retrieved_memories": list(retrieved_memories),
        }

        return decision, metadata

    def _parse_json_decision(self, text: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
        """Robust parser for JSON tool call decisions."""
        # Try to find ```json ... ``` or first {...}
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            json_match2 = re.search(r"(\{.*\})", text, re.DOTALL)
            raw_json = json_match2.group(1) if json_match2 else text

        try:
            parsed = json.loads(raw_json)
            if "action" in parsed and "params" in parsed:
                return parsed
        except Exception:
            pass

        # Fallback heuristic parsing if JSON is malformed
        if "navigate" in text.lower():
            zone = "Corridor_South" if "south" in text.lower() else "Corridor_North"
            if "office_a" in text.lower(): zone = "Office_A"
            elif "office_b" in text.lower(): zone = "Office_B"
            elif "lab_secure" in text.lower(): zone = "Lab_Secure"
            elif "lobby" in text.lower(): zone = "Lobby"
            return {
                "thought": "Fallback navigation extracted from response.",
                "action": "navigate",
                "params": {"target_zone": zone}
            }
        elif "pickup" in text.lower():
            pkg = "pkg_docs" if "pkg_docs" in text else "pkg_hardware"
            return {
                "thought": "Fallback pickup extracted from response.",
                "action": "pickup",
                "params": {"package_id": pkg, "from_location": current_state.get("robot_location")}
            }
        elif "deliver" in text.lower():
            pkg = "pkg_docs" if "pkg_docs" in text else "pkg_hardware"
            rec = "Alice" if "alice" in text.lower() else "Bob"
            return {
                "thought": "Fallback delivery extracted from response.",
                "action": "deliver",
                "params": {"package_id": pkg, "recipient": rec}
            }

        return {
            "thought": "Could not parse JSON. Taking default navigation step.",
            "action": "navigate",
            "params": {"target_zone": "Corridor_North"}
        }
