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


TOOL_SCHEMAS = {
    "navigate": {
        "required": ["target_zone"],
        "types": {"target_zone": str},
        "allowed_extra": [],
    },
    "observe": {
        "required": ["target"],
        "types": {"target": str},
        "allowed_extra": [],
    },
    "query_status": {
        "required": ["entity"],
        "types": {"entity": str},
        "allowed_extra": [],
    },
    "pickup": {
        "required": ["package_id", "from_location"],
        "types": {"package_id": str, "from_location": str},
        "allowed_extra": [],
    },
    "deliver": {
        "required": ["package_id", "recipient"],
        "types": {"package_id": str, "recipient": str},
        "allowed_extra": [],
    },
    "recharge": {
        "required": [],
        "types": {},
        "allowed_extra": [],
    },
    "acquire_credential": {
        "required": ["credential_name"],
        "types": {"credential_name": str},
        "allowed_extra": [],
    },
}

MAP_ADJACENCY = {
    "Lobby": ["Corridor_North", "Corridor_South"],
    "Corridor_North": ["Lobby", "Office_A", "Office_B", "Corridor_South"],
    "Corridor_South": ["Lobby", "Corridor_North", "Office_A", "Lab_Secure"],
    "Office_A": ["Corridor_North", "Corridor_South"],
    "Office_B": ["Corridor_North"],
    "Lab_Secure": ["Corridor_South"],
}


def format_map_topology_description(adjacency_map: Optional[Dict[str, List[str]]] = None) -> str:
    """Dynamically generates a declarative topological description from environment adjacency."""
    adj = adjacency_map or MAP_ADJACENCY
    lines = ["### Environmental Map Topology:"]
    for zone, neighbors in adj.items():
        lines.append(f"- Zone '{zone}' connects directly to: {neighbors}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are an autonomous mobile delivery robot operating in an indoor office and lab environment.
Your goal is to complete all delivery tasks step-by-step safely, efficiently, and without violating constraints.

### Available Tools:
1. `pickup(package_id, from_location)`: Pick up package from current room into inventory (max capacity: 2).
2. `deliver(package_id, recipient)`: Hand over package from inventory to recipient in current room.
3. `navigate(target_zone)`: Move to an allowed adjacent zone.
4. `observe(target)`: Scan door or inspect room contents.
5. `query_status(entity)`: Query recipient availability or battery.
6. `acquire_credential(credential_name)`: Pick up credential in current room.
7. `recharge()`: Fully recharge battery at Lobby charging station.

### Action Selection Protocol:
1. Deliver: If you are holding a package whose target room is your current location, execute `deliver` immediately.
2. Pickup: If there are pickable packages in your current room and inventory has space (< 2), execute `pickup`.
3. Navigate: Move towards target locations using allowed adjacent zones. Do not navigate to current zone.
4. Experience & Conditions: Inspect retrieved failure memories and current known facts to avoid known obstacles or satisfy missing preconditions.

### Output JSON Format:
Output strictly a single JSON codeblock:
```json
{
  "decision_summary": "1-2 sentence verifiable ground for choosing this action.",
  "action": "<tool_name>",
  "params": { "<param_name>": "<param_value>" }
}
```"""


from .task_skeleton import PublicTaskSkeleton


class AgentPlanner:
    def __init__(
        self,
        llm_backend: LLMBackend,
        memory_adapter: BaseMemoryAdapter,
        adjacency_map: Optional[Dict[str, List[str]]] = None,
        use_task_skeleton: bool = False,
    ):
        self.llm = llm_backend
        self.memory = memory_adapter
        self.adjacency_map = adjacency_map or MAP_ADJACENCY
        self.use_task_skeleton = use_task_skeleton
        self.task_skeleton = PublicTaskSkeleton(self.adjacency_map, max_inventory_capacity=2)

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
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Plans the next action.
        Returns: (parsed_decision_dict, list_of_llm_trace_dicts)
        """
        robot_loc = current_state.get("robot_location", "Lobby")
        inventory = current_state.get("inventory", [])
        avail_pkgs = current_state.get("available_packages", [])
        adjacent_zones = self.adjacency_map.get(robot_loc, [])

        # Check immediate affordances in current room
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

        # 1. Derive Task Skeleton & Active Subgoal (Pre-Memory Step)
        skeleton_section, active_subgoal = self.task_skeleton.format_skeleton_prompt_section(
            current_state, known_state, step_history
        )

        # 2. Decoupled Multi-Attribute Memory Query Context
        task_targets = [p["target_room"] for p in avail_pkgs if p["id"] in inventory] or [p["pickup_location"] for p in avail_pkgs]
        task_recipients = [p.get("recipient") for p in avail_pkgs if p.get("recipient")]
        candidate_action_entities = list(set(adjacent_zones + task_targets + task_recipients + [robot_loc]))

        context_query = {
            "step_index": step_index,
            "current_location": robot_loc,
            "adjacent_zones": adjacent_zones,
            "task_targets": task_targets,
            "task_recipients": task_recipients,
            "candidate_entities": candidate_action_entities,
            "inventory": inventory,
            "credentials": current_state.get("credentials", []),
            "task_instruction": task_instruction,
            "undelivered_packages": [p.get("id") for p in avail_pkgs],
            "pickable_here": pickable_here,
            "deliverable_here": deliverable_here,
            "active_subgoal": active_subgoal,
            "max_inventory_capacity": current_state.get("max_inventory_capacity", self.task_skeleton.max_inventory_capacity),
        }
        retrieved_memories = self.memory.retrieve_relevant_memories(known_state, context_query)

        # 3. Build User Prompt
        user_prompt_lines = [
            f"### Current Delivery Task: {task_instruction}",
            format_map_topology_description(self.adjacency_map),
            f"### Current Robot Status:",
            f"- Current Location: {robot_loc}",
            f"- Allowed Adjacent Zones for 'navigate': {adjacent_zones}",
            f"- Packages Currently Held in Bag (Capacity {len(inventory)}/{current_state.get('max_inventory_capacity', self.task_skeleton.max_inventory_capacity)}): {held_packages_destinations}",
            f"- Deliverable Packages at Current Location ({robot_loc}): {deliverable_here}",
            f"- Pickable Packages Available at Current Location ({robot_loc}): {pickable_here}",
            f"- Undelivered Packages in Environment: {avail_pkgs}",
            f"- Held Credentials: {current_state.get('credentials')}",
            f"- Battery Level: {current_state.get('battery')}%",
        ]

        # S1: Public Task Skeleton Injection (if enabled)
        if self.use_task_skeleton:
            user_prompt_lines.append(skeleton_section)

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

        llm_traces_recorded = []

        # 3. Call LLM (Attempt 1)
        gen_res = self.llm.generate(messages)
        content = gen_res.get("content", "")

        trace_att1 = {
            "event_id": f"evt_{run_id}_{method_name}_{seq_id}_{task_id}_s{step_index:02d}_call1",
            "prompt_tokens": gen_res.get("prompt_tokens", 0),
            "generated_tokens": gen_res.get("generated_tokens", 0),
            "latency_s": gen_res.get("latency_s", 0.0),
            "raw_response": content,
            "retry_used": False,
            "parse_ok": False,
            "retrieved_memories": list(retrieved_memories),
        }

        # 4. Strict Schema & JSON Validation
        decision, parse_ok, parse_err = self._strict_validate_schema(content)
        trace_att1["parse_ok"] = parse_ok
        llm_traces_recorded.append(trace_att1)

        if not parse_ok:
            # Attempt 2: Strict format retry (recorded as independent LLM invocation)
            retry_messages = list(messages)
            retry_messages.append({"role": "assistant", "content": content})
            retry_messages.append({
                "role": "user",
                "content": f"Schema Validation Error: {parse_err}. Please output ONLY a valid JSON object matching the format:\n```json\n{{\"decision_summary\": \"...\", \"action\": \"<tool_name>\", \"params\": {{...}}}}\n```"
            })
            retry_res = self.llm.generate(retry_messages)
            retry_content = retry_res.get("content", "")

            trace_att2 = {
                "event_id": f"evt_{run_id}_{method_name}_{seq_id}_{task_id}_s{step_index:02d}_call2_retry",
                "prompt_tokens": retry_res.get("prompt_tokens", 0),
                "generated_tokens": retry_res.get("generated_tokens", 0),
                "latency_s": retry_res.get("latency_s", 0.0),
                "raw_response": retry_content,
                "retry_used": True,
                "parse_ok": False,
                "retrieved_memories": list(retrieved_memories),
            }

            decision, parse_ok, retry_err = self._strict_validate_schema(retry_content)
            trace_att2["parse_ok"] = parse_ok
            llm_traces_recorded.append(trace_att2)

            if not parse_ok:
                decision = {
                    "decision_summary": f"PARSE_FAILURE: Schema validation failed after retry ({retry_err}).",
                    "action": "parse_error",
                    "params": {"raw_output": retry_content or content},
                }

        return decision, llm_traces_recorded

    def _strict_validate_schema(self, text: str) -> Tuple[Dict[str, Any], bool, str]:
        """Strict JSON and schema validation ensuring tool name, required parameters, and types."""
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            json_match2 = re.search(r"(\{.*\})", text, re.DOTALL)
            raw_json = json_match2.group(1) if json_match2 else text

        try:
            parsed = json.loads(raw_json)
        except Exception as e:
            return {}, False, f"Invalid JSON syntax: {e}"

        if not isinstance(parsed, dict):
            return {}, False, "Output is not a JSON dictionary"

        if "action" not in parsed:
            return {}, False, "Missing 'action' key in JSON"

        action = parsed["action"]
        if action not in TOOL_SCHEMAS:
            return {}, False, f"Unknown tool action '{action}'. Allowed: {list(TOOL_SCHEMAS.keys())}"

        if "params" not in parsed or not isinstance(parsed["params"], dict):
            return {}, False, "'params' must be a dictionary"

        schema = TOOL_SCHEMAS[action]
        params = parsed["params"]

        # Check required fields
        for req_key in schema["required"]:
            if req_key not in params:
                return {}, False, f"Missing required parameter '{req_key}' for tool '{action}'"
            if not isinstance(params[req_key], str) or not params[req_key].strip():
                return {}, False, f"Parameter '{req_key}' must be a non-empty string"

        # Check type correctness
        for param_key, val in params.items():
            if param_key in schema["types"]:
                expected_type = schema["types"][param_key]
                if not isinstance(val, expected_type):
                    return {}, False, f"Parameter '{param_key}' has type {type(val).__name__}, expected {expected_type.__name__}"
            elif param_key not in schema.get("allowed_extra", []):
                return {}, False, f"Unexpected extra parameter '{param_key}' for tool '{action}'"

        if "decision_summary" not in parsed:
            parsed["decision_summary"] = parsed.get("thought", "Action planned.")

        return parsed, True, ""

    def _strict_parse_json(self, raw_text: str) -> Tuple[Dict[str, Any], bool]:
        """Wrapper around schema validation returning (decision, parse_ok)."""
        decision, parse_ok, _ = self._strict_validate_schema(raw_text)
        return decision, parse_ok

