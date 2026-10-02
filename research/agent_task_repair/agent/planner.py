"""
ReAct-style Structured Planner for FailMem Stage 2 Robot Agent.
Enforces:
  - Strict JSON tool schemas with verifiable decision_summary.
  - Comprehensive operational topology and checklist shared across all methods.
  - Multi-attribute memory retrieval over shared known state.
  - Zero heuristic guessing on parse failure (strict format validation & 1-shot retry).
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

MAP_ADJACENCY = {
    "Lobby": ["Corridor_North", "Corridor_South"],
    "Corridor_North": ["Lobby", "Office_A", "Office_B", "Corridor_South"],
    "Corridor_South": ["Lobby", "Corridor_North", "Office_A", "Lab_Secure"],
    "Office_A": ["Corridor_North", "Corridor_South"],
    "Office_B": ["Corridor_North"],
    "Lab_Secure": ["Corridor_South"],
}

SYSTEM_PROMPT = """You are an autonomous mobile delivery robot operating in an indoor office and lab environment.
Your goal is to complete all delivery tasks step-by-step safely, efficiently, and without violating constraints.

### Map Topology & Routing:
- Lobby <-> Corridor_North (via door_north), Lobby <-> Corridor_South (via door_south)
- Corridor_North <-> Office_A, Corridor_North <-> Office_B, Corridor_North <-> Corridor_South
- Corridor_South <-> Office_A, Corridor_South <-> Lab_Secure (REQUIRES security_badge)
- Key Connectivity:
  * Office_A is reachable from BOTH Corridor_North and Corridor_South.
  * Office_B is reachable ONLY from Corridor_North.
  * Lab_Secure is reachable ONLY from Corridor_South (and requires security_badge from Office_A).
  * You cannot jump between rooms directly without going through the connecting corridor.

### Available Tools (You MUST use ONLY these 7 tools; never use noop, none, or check_inventory):
1. `pickup(package_id, from_location)`: Pick up package from current room into your inventory bag (max capacity: 2).
   * Example: `{"action": "pickup", "params": {"package_id": "pkg_docs", "from_location": "Lobby"}}`
2. `deliver(package_id, recipient)`: Hand over package from inventory bag to recipient in current room.
   * Example: `{"action": "deliver", "params": {"package_id": "pkg_docs", "recipient": "Alice"}}`
3. `navigate(target_zone)`: Move to an adjacent zone.
   * Example: `{"action": "navigate", "params": {"target_zone": "Corridor_North"}}`
4. `observe(target)`: Scan door or inspect room.
   * Example: `{"action": "observe", "params": {"target": "door_north"}}`
5. `query_status(entity)`: Query recipient availability ('Alice', 'Bob', 'Charlie') or 'battery'.
   * Example: `{"action": "query_status", "params": {"entity": "Alice"}}`
6. `acquire_credential(credential_name)`: Pick up badge in current room (e.g. 'security_badge' in Office_A).
   * Example: `{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}`
7. `recharge()`: Fully recharge battery at Lobby charging station.
   * Example: `{"action": "recharge", "params": {}}`

### Action Selection Protocol:
1. Deliver Now: If you are holding a package whose target room is your current location (see Deliverable Packages), execute `deliver` immediately! (NEVER leave room or call noop without delivering first).
2. Pickup Now: If there are pickable packages in your current room (see Pickable Packages) and bag has space (< 2), execute `pickup` immediately! (Pick up all available packages at current location before leaving).
3. Target Navigation:
   - If holding package for Room X and Room X is in Allowed Adjacent Zones, execute `navigate(Room X)`.
   - If holding package for Office_B, navigate to Corridor_North.
   - If holding package for Lab_Secure, navigate to Corridor_South (with security_badge).
   - If not holding packages, navigate to the room where undelivered packages are located.
   - Choose target_zone ONLY from Allowed Adjacent Zones. Never navigate to your current zone.
4. Blockage Detour: If `navigate` fails with `DOORWAY_BLOCKED`, take the other corridor (e.g. Corridor_South).
5. Credentials: If entering `Lab_Secure`, visit `Office_A` to call `acquire_credential('security_badge')` first.

### Output JSON Format:
Output strictly a single JSON codeblock:
```json
{
  "decision_summary": "1-2 sentence verifiable ground for choosing this action.",
  "action": "<tool_name>",
  "params": { "<param_name>": "<param_value>" }
}
```"""


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
        run_id: str = "run_default",
        method_name: str = "B0",
        seq_id: str = "seq_default",
        task_index: int = 0,
        step_index: int = 1,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Plans the next action.
        Returns: (parsed_decision_dict, llm_metadata)
        """
        robot_loc = current_state.get("robot_location", "Lobby")
        inventory = current_state.get("inventory", [])
        avail_pkgs = current_state.get("available_packages", [])
        adjacent_zones = MAP_ADJACENCY.get(robot_loc, [])

        # Check immediate affordances in current room (public logic)
        pickable_here = [
            {"package_id": p["id"], "pickup_location": p["pickup_location"], "target_room": p["target_room"], "recipient": p["recipient"]}
            for p in avail_pkgs
            if p.get("pickup_location") == robot_loc and p["id"] not in inventory
        ]
        deliverable_here = [
            {"package_id": p["id"], "recipient": p["recipient"], "target_room": p["target_room"]}
            for p in avail_pkgs
            if p["id"] in inventory and p.get("target_room") == robot_loc
        ]
        held_packages_destinations = [
            {"package_id": p["id"], "target_room": p["target_room"], "recipient": p["recipient"]}
            for p in avail_pkgs
            if p["id"] in inventory
        ]

        # 1. Multi-attribute memory query context
        context_query = {
            "current_location": robot_loc,
            "inventory": inventory,
            "target": robot_loc,
            "credentials": current_state.get("credentials", []),
            "task_instruction": task_instruction,
            "undelivered_packages": [p.get("id") for p in avail_pkgs],
        }
        retrieved_memories = self.memory.retrieve_relevant_memories(known_state, context_query)

        # 2. Build User Prompt with explicit public state
        user_prompt_lines = [
            f"### Current Delivery Task: {task_instruction}",
            f"### Current Robot Status:",
            f"- Current Location: {robot_loc}",
            f"- Allowed Adjacent Zones for 'navigate': {adjacent_zones}",
            f"- Packages Currently Held in Bag (Capacity {len(inventory)}/2): {held_packages_destinations}",
            f"- Deliverable Packages at Current Location ({robot_loc}): {deliverable_here}",
            f"- Pickable Packages Available at Current Location ({robot_loc}): {pickable_here}",
            f"- Undelivered Packages in Environment: {avail_pkgs}",
            f"- Held Credentials: {current_state.get('credentials')}",
            f"- Battery Level: {current_state.get('battery')}%",
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

        # 3. Call LLM (Attempt 1)
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
                "content": f"Formatting Error: Output could not be parsed as valid JSON matching schema. Please output ONLY a valid JSON object matching the format:\n```json\n{{\"decision_summary\": \"...\", \"action\": \"<tool_name>\", \"params\": {{...}}}}\n```"
            })
            retry_res = self.llm.generate(retry_messages)
            retry_content = retry_res.get("content", "")
            decision, parse_ok = self._strict_parse_json(retry_content)

            gen_res["prompt_tokens"] += retry_res.get("prompt_tokens", 0)
            gen_res["generated_tokens"] += retry_res.get("generated_tokens", 0)
            gen_res["latency_s"] += retry_res.get("latency_s", 0.0)

            if not parse_ok:
                decision = {
                    "decision_summary": "PARSE_FAILURE: Failed to produce valid JSON tool call after retry.",
                    "action": "parse_error",
                    "params": {"raw_output": retry_content or content},
                }

        metadata = {
            "event_id": f"evt_{run_id}_{method_name}_{seq_id}_{task_id}_s{step_index:02d}_att1",
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
