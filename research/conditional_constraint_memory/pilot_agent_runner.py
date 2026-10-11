"""
Symmetrical 4-Group Pilot Agent Runner.
Implements:
- B0: No-Memory baseline
- B2: Dynamic Fact Memory (contextual world facts, autonomous reasoning)
- B2-G: B2 + Static Action Gate (naive blocker on matched facts)
- M: Candidate Lifecycle Gate (validity, applicability, gate decision, probe on unknown)

Enforces:
- Strict JSON tool calling protocol.
- Identical tools, prompt structure, model, temperature=0.0.
- Telemetry: proposed vs executed error actions, TP/FP/FN blocks, probe calls, tokens, latency.
- Independent verifiers.
"""

import os
import sys
import time
import json
import re
from typing import Dict, Any, List, Optional, Tuple

from research.agent_task_repair.agent.llm_backend import LLMBackend
from .constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision,
    ConstraintLifecycleManager,
)
from .task_environment import (
    PortTaskEnvironment,
    FilePermissionTaskEnvironment,
)
from .memory_pipeline import FailureTrace, StructuredFact, MemoryPipeline


def parse_action_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Robust parser for ReAct JSON action response."""
    raw = raw_text.strip()
    # Check for markdown codeblocks
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    elif "{" in raw and "}" in raw:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        raw = raw[start:end]

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "action" in data:
            return data
    except Exception:
        pass
    return None


class PilotAgentRunner:
    def __init__(self, llm_backend: LLMBackend):
        self.llm = llm_backend

    def _build_port_system_prompt(self, memory_text: str = "") -> str:
        prompt = """You are an autonomous system administration agent.
Your objective is to ensure the network service is actively running on 127.0.0.1.

### Available Tools:
1. `probe_port(port)`: Check whether a local TCP port is occupied or free.
   Params: `{"port": <int>}`
2. `start_service(port)`: Attempt to bind and launch the service daemon on the specified port.
   Params: `{"port": <int>}`

### Instructions:
- Primary port to attempt is 18080. If 18080 is unavailable or in use, use fallback port 18081.
- Output strictly a single JSON code block in this exact schema:
```json
{
  "decision_summary": "1-2 sentence reason for choosing this action.",
  "action": "<tool_name>",
  "params": { ... }
}
```
"""
        if memory_text:
            prompt += f"\n{memory_text}\n"
        return prompt

    def _build_file_system_prompt(self, memory_text: str = "") -> str:
        prompt = """You are an autonomous system administration agent running as non-root user 'agentuser'.
Your objective is to apply configuration 'ENABLE_TELEMETRY=true' for the service.

### Available Tools:
1. `probe_file_permission(filepath)`: Check whether a file exists and if non-root 'agentuser' has write access.
   Params: `{"filepath": "<string>"}`
2. `write_config(filepath, key, value)`: Append configuration entry to specified file.
   Params: `{"filepath": "<string>", "key": "<string>", "value": "<string>"}`

### Instructions:
- Primary configuration file is '/etc/service_demo/app.conf'.
- If the primary file is not writable, write to fallback user override file '/home/agentuser/user_override.conf'.
- Output strictly a single JSON code block in this exact schema:
```json
{
  "decision_summary": "1-2 sentence reason for choosing this action.",
  "action": "<tool_name>",
  "params": { ... }
}
```
"""
        if memory_text:
            prompt += f"\n{memory_text}\n"
        return prompt

    def run_port_episode(
        self,
        group: str,
        env: PortTaskEnvironment,
        state: str,
        run_id: str,
        facts: Optional[List[StructuredFact]] = None,
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
        max_steps: int = 6,
        goal_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs a port task episode under specified comparison group."""
        start_time = time.time()
        env.setup(state)

        # Telemetry metrics
        proposed_error_actions = 0
        executed_error_actions = 0
        tp_blocks = 0
        fp_blocks = 0
        fn_blocks = 0
        active_probe_calls = 0
        total_prompt_tokens = 0
        total_generated_tokens = 0
        llm_calls = 0
        tool_records = []
        llm_records = []

        # Prepare memory text for prompt
        memory_text = ""
        now = time.time()
        if group in ("B2", "B2-G") and facts:
            memory_text = "### Known Environment Facts:\n" + "\n".join(
                [f.to_prompt_text(now) for f in facts]
            )
        elif group == "M" and lifecycle_manager:
            memory_text = "### Active Constraint Rules:\n"
            for r in lifecycle_manager.rules.values():
                app = lifecycle_manager.evaluate_applicability(r)
                memory_text += f"- Rule {r.rule_id} for '{r.action_signature}' (Validity: {r.validity_state.value}, Applicability: {app.value})\n"

        system_prompt = self._build_port_system_prompt(memory_text)
        user_goal = goal_instruction or "Begin task: Start the network service on port 18080 (or fallback to 18081 if 18080 is unavailable)."
        conversation = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_goal}
        ]

        success = False
        step = 0

        while step < max_steps and not success:
            step += 1
            llm_res = self.llm.generate(conversation)
            llm_calls += 1
            total_prompt_tokens += llm_res.get("prompt_tokens", 0)
            total_generated_tokens += llm_res.get("generated_tokens", 0)
            raw_output = llm_res.get("content", "")

            llm_records.append({
                "step": step,
                "output": raw_output,
                "prompt_tokens": llm_res.get("prompt_tokens", 0),
                "generated_tokens": llm_res.get("generated_tokens", 0),
                "latency_s": llm_res.get("latency_s", 0.0),
            })

            action_data = parse_action_response(raw_output)
            if not action_data:
                # Retry prompt
                conversation.append({"role": "assistant", "content": raw_output})
                conversation.append({"role": "user", "content": "Error: Output must be a valid JSON object with 'action' and 'params'."})
                continue

            tool_name = action_data.get("action", "")
            params = action_data.get("params", {})
            target_port = params.get("port", 18080)

            # Record proposed action
            action_sig = f"{tool_name}:port={target_port}"
            is_failing_action = (tool_name == "start_service" and target_port == 18080 and state in ("A", "C", "D"))
            if is_failing_action:
                proposed_error_actions += 1

            # --- Gating Logic ---
            gate_blocked = False
            gate_reason = ""

            if group == "B2-G":
                # Static gate: if action is start_service 18080 and fact recorded it as occupied
                if tool_name == "start_service" and target_port == 18080:
                    gate_blocked = True
                    gate_reason = "Static gate: port 18080 was recorded as occupied."
                    if state in ("A", "C", "D"):
                        tp_blocks += 1
                    else:
                        fp_blocks += 1  # False positive in State B!

            elif group == "M" and lifecycle_manager:
                gate_eval = lifecycle_manager.make_gate_decision(action_sig)
                decision = gate_eval["decision"]
                if decision == GateDecision.BLOCK:
                    gate_blocked = True
                    gate_reason = gate_eval["reason"]
                    if state in ("A", "C", "D"):
                        tp_blocks += 1
                    else:
                        fp_blocks += 1
                elif decision == GateDecision.PROBE:
                    # Probe triggered automatically on UNKNOWN
                    active_probe_calls += 1
                    probe_res = env.probe(target_port)
                    lifecycle_manager.register_observation(f"port:{target_port}:occupied", probe_res["is_occupied"])
                    feedback = f"[ConstraintGate Probe Result] Probed port {target_port}: status is {probe_res['status']}. Re-evaluate your next action."
                    conversation.append({"role": "assistant", "content": raw_output})
                    conversation.append({"role": "user", "content": feedback})
                    tool_records.append({
                        "step": step,
                        "tool": "probe_port",
                        "params": {"port": target_port},
                        "exit_code": 0,
                        "result": probe_res,
                    })
                    continue

            if gate_blocked:
                feedback = f"[Gate Blocked] {gate_reason} Please select an alternative action."
                conversation.append({"role": "assistant", "content": raw_output})
                conversation.append({"role": "user", "content": feedback})
                continue

            # --- Tool Execution ---
            if tool_name == "probe_port":
                active_probe_calls += 1
                tool_res = env.probe(target_port)
                exit_code = 0
                feedback = f"Probe Result: Port {target_port} is {tool_res['status']}."
                if group == "M" and lifecycle_manager:
                    lifecycle_manager.register_observation(f"port:{target_port}:occupied", tool_res["is_occupied"])
            elif tool_name == "start_service":
                tool_res = env.execute_start_service(target_port)
                exit_code = tool_res["error_code"]
                if tool_res["success"]:
                    feedback = tool_res["stdout"]
                    if group == "M" and lifecycle_manager:
                        lifecycle_manager.record_action_outcome(action_sig, True, tool_res)
                else:
                    feedback = tool_res["stderr"]
                    executed_error_actions += 1
                    fn_blocks += 1
                    if group == "M" and lifecycle_manager:
                        lifecycle_manager.record_action_outcome(action_sig, False, tool_res)
            else:
                exit_code = 1
                tool_res = {"success": False, "stderr": f"Unknown tool '{tool_name}'"}
                feedback = f"Error: Unknown tool '{tool_name}'"

            tool_records.append({
                "step": step,
                "tool": tool_name,
                "params": params,
                "exit_code": exit_code,
                "result": tool_res,
            })

            # Check task completion with independent verifier
            if env.verify_completion():
                success = True
                break

            conversation.append({"role": "assistant", "content": raw_output})
            conversation.append({"role": "user", "content": f"Tool Output: {feedback}"})

        return {
            "group": group,
            "task_family": "port",
            "state": state,
            "run_id": run_id,
            "success": success,
            "steps": step,
            "llm_calls": llm_calls,
            "total_prompt_tokens": total_prompt_tokens,
            "total_generated_tokens": total_generated_tokens,
            "latency_s": round(time.time() - start_time, 2),
            "proposed_error_actions": proposed_error_actions,
            "executed_error_actions": executed_error_actions,
            "tp_blocks": tp_blocks,
            "fp_blocks": fp_blocks,
            "fn_blocks": fn_blocks,
            "active_probe_calls": active_probe_calls,
            "tool_records": tool_records,
            "llm_records": llm_records,
        }

    def run_file_episode(
        self,
        group: str,
        env: FilePermissionTaskEnvironment,
        state: str,
        run_id: str,
        facts: Optional[List[StructuredFact]] = None,
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
        max_steps: int = 6,
        goal_instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs a file permission task episode under specified comparison group."""
        start_time = time.time()
        env.setup(state)

        # Telemetry metrics
        proposed_error_actions = 0
        executed_error_actions = 0
        tp_blocks = 0
        fp_blocks = 0
        fn_blocks = 0
        active_probe_calls = 0
        total_prompt_tokens = 0
        total_generated_tokens = 0
        llm_calls = 0
        tool_records = []
        llm_records = []

        memory_text = ""
        now = time.time()
        if group in ("B2", "B2-G") and facts:
            memory_text = "### Known Environment Facts:\n" + "\n".join(
                [f.to_prompt_text(now) for f in facts]
            )
        elif group == "M" and lifecycle_manager:
            memory_text = "### Active Constraint Rules:\n"
            for r in lifecycle_manager.rules.values():
                app = lifecycle_manager.evaluate_applicability(r)
                memory_text += f"- Rule {r.rule_id} for '{r.action_signature}' (Validity: {r.validity_state.value}, Applicability: {app.value})\n"

        system_prompt = self._build_file_system_prompt(memory_text)
        user_goal = goal_instruction or "Begin task: Set ENABLE_TELEMETRY=true in /etc/service_demo/app.conf (or fallback to /home/agentuser/user_override.conf if primary is not writable)."
        conversation = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_goal}
        ]

        success = False
        step = 0

        while step < max_steps and not success:
            step += 1
            llm_res = self.llm.generate(conversation)
            llm_calls += 1
            total_prompt_tokens += llm_res.get("prompt_tokens", 0)
            total_generated_tokens += llm_res.get("generated_tokens", 0)
            raw_output = llm_res.get("content", "")

            llm_records.append({
                "step": step,
                "output": raw_output,
                "prompt_tokens": llm_res.get("prompt_tokens", 0),
                "generated_tokens": llm_res.get("generated_tokens", 0),
                "latency_s": llm_res.get("latency_s", 0.0),
            })

            action_data = parse_action_response(raw_output)
            if not action_data:
                conversation.append({"role": "assistant", "content": raw_output})
                conversation.append({"role": "user", "content": "Error: Output must be a valid JSON object with 'action' and 'params'."})
                continue

            tool_name = action_data.get("action", "")
            params = action_data.get("params", {})
            target_filepath = params.get("filepath", "/etc/service_demo/app.conf")

            action_sig = f"{tool_name}:filepath={target_filepath}"
            is_failing_action = (tool_name == "write_config" and target_filepath == "/etc/service_demo/app.conf" and state in ("A", "C", "D"))
            if is_failing_action:
                proposed_error_actions += 1

            # --- Gating Logic ---
            gate_blocked = False
            gate_reason = ""

            if group == "B2-G":
                if tool_name == "write_config" and target_filepath == "/etc/service_demo/app.conf":
                    gate_blocked = True
                    gate_reason = "Static gate: /etc/service_demo/app.conf was recorded as non-writable."
                    if state in ("A", "C", "D"):
                        tp_blocks += 1
                    else:
                        fp_blocks += 1

            elif group == "M" and lifecycle_manager:
                gate_eval = lifecycle_manager.make_gate_decision(action_sig)
                decision = gate_eval["decision"]
                if decision == GateDecision.BLOCK:
                    gate_blocked = True
                    gate_reason = gate_eval["reason"]
                    if state in ("A", "C", "D"):
                        tp_blocks += 1
                    else:
                        fp_blocks += 1
                elif decision == GateDecision.PROBE:
                    active_probe_calls += 1
                    probe_res = env.probe(target_filepath)
                    lifecycle_manager.register_observation(f"file:{target_filepath}:writable", probe_res["writable_by_agentuser"])
                    feedback = f"[ConstraintGate Probe Result] Probed {target_filepath}: writable_by_agentuser={probe_res['writable_by_agentuser']}, mode={probe_res['mode']}. Re-evaluate your next action."
                    conversation.append({"role": "assistant", "content": raw_output})
                    conversation.append({"role": "user", "content": feedback})
                    tool_records.append({
                        "step": step,
                        "tool": "probe_file_permission",
                        "params": {"filepath": target_filepath},
                        "exit_code": 0,
                        "result": probe_res,
                    })
                    continue

            if gate_blocked:
                feedback = f"[Gate Blocked] {gate_reason} Please select an alternative action."
                conversation.append({"role": "assistant", "content": raw_output})
                conversation.append({"role": "user", "content": feedback})
                continue

            # --- Tool Execution ---
            if tool_name == "probe_file_permission":
                active_probe_calls += 1
                tool_res = env.probe(target_filepath)
                exit_code = 0
                feedback = f"Probe Result: {target_filepath} writable={tool_res['writable_by_agentuser']}, mode={tool_res['mode']}."
                if group == "M" and lifecycle_manager:
                    lifecycle_manager.register_observation(f"file:{target_filepath}:writable", tool_res["writable_by_agentuser"])
            elif tool_name == "write_config":
                key = params.get("key", "ENABLE_TELEMETRY")
                val = params.get("value", "true")
                tool_res = env.execute_write_config(target_filepath, key, val)
                exit_code = tool_res["error_code"]
                if tool_res["success"]:
                    feedback = tool_res["stdout"]
                    if group == "M" and lifecycle_manager:
                        lifecycle_manager.record_action_outcome(action_sig, True, tool_res)
                else:
                    feedback = tool_res["stderr"]
                    executed_error_actions += 1
                    fn_blocks += 1
                    if group == "M" and lifecycle_manager:
                        lifecycle_manager.record_action_outcome(action_sig, False, tool_res)
            else:
                exit_code = 1
                tool_res = {"success": False, "stderr": f"Unknown tool '{tool_name}'"}
                feedback = f"Error: Unknown tool '{tool_name}'"

            tool_records.append({
                "step": step,
                "tool": tool_name,
                "params": params,
                "exit_code": exit_code,
                "result": tool_res,
            })

            if env.verify_completion():
                success = True
                break

            conversation.append({"role": "assistant", "content": raw_output})
            conversation.append({"role": "user", "content": f"Tool Output: {feedback}"})

        return {
            "group": group,
            "task_family": "file",
            "state": state,
            "run_id": run_id,
            "success": success,
            "steps": step,
            "llm_calls": llm_calls,
            "total_prompt_tokens": total_prompt_tokens,
            "total_generated_tokens": total_generated_tokens,
            "latency_s": round(time.time() - start_time, 2),
            "proposed_error_actions": proposed_error_actions,
            "executed_error_actions": executed_error_actions,
            "tp_blocks": tp_blocks,
            "fp_blocks": fp_blocks,
            "fn_blocks": fn_blocks,
            "active_probe_calls": active_probe_calls,
            "tool_records": tool_records,
            "llm_records": llm_records,
        }
