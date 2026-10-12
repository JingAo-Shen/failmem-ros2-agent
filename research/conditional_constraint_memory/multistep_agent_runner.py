"""
Symmetric 4-Arm Agent Runner for Multi-Step Service Deployment Task.
Enforces:
1. Zero hidden state leakage (no A/B/C/D labels or internal instance flags).
2. Symmetrical prompt structure without hard-coded repair recipes.
3. Strict budget limits: <= 20 LLM calls, <= 30 tool calls, <= 600s per episode (checked before each call).
4. Four arms:
   - B0: Pure online ReAct agent (no cross-task memory).
   - B2: Dynamic Fact Memory (contextual environment facts in prompt, autonomous reasoning).
   - B2-G: Generic Predicate Gating (evaluates dynamic predicates, probes UNKNOWN, blocks if fresh True, allows if False).
   - M: Candidate Lifecycle Gate (validity states: CANDIDATE probation trial, SUPPORTED blocking, UNKNOWN probing, contradiction downgrade).
"""

import os
import sys
import time
import json
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from research.agent_task_repair.agent.llm_backend import LLMBackend
from research.conditional_constraint_memory.constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision,
    ConstraintLifecycleManager,
)
from research.conditional_constraint_memory.multistep_deployment_env import (
    MultiStepDeploymentEnv,
    is_port_listening,
)
from research.conditional_constraint_memory.memory_pipeline import FailureTrace, StructuredFact


class BudgetExceededError(Exception):
    """Raised when an episode exceeds allowed call or time budget."""
    pass


def parse_action_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Robust parser for ReAct JSON action response."""
    raw = raw_text.strip()
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


class MultiStepAgentRunner:
    def __init__(
        self,
        llm_backend: LLMBackend,
        max_llm_calls_per_episode: int = 20,
        max_tool_calls_per_episode: int = 30,
        max_time_per_episode_s: float = 600.0,
    ):
        self.llm = llm_backend
        self.max_llm_calls = max_llm_calls_per_episode
        self.max_tool_calls = max_tool_calls_per_episode
        self.max_time_s = max_time_per_episode_s

    def build_system_prompt(self, memory_text: str = "") -> str:
        prompt = """You are an autonomous system administration agent running as non-root user 'agentuser'.
Your objective is to successfully configure and deploy the 'telemetry_agent' service on an available localhost port.

### Available Tools:
1. `discover_environment()`: Inspect environment, candidate ports, and candidate config paths.
   Params: `{}`
2. `probe_port(port)`: Passively check if a network port is currently occupied or free.
   Params: `{"port": <int>}`
3. `probe_directory(dirpath)`: Check if a directory exists and is writable by agentuser.
   Params: `{"dirpath": "<string>"}`
4. `probe_file(filepath)`: Check if a configuration file is writable (or creatable in its parent directory) by agentuser.
   Params: `{"filepath": "<string>"}`
5. `write_config(config_path, port, service_name)`: Write service configuration file to disk.
   Params: `{"config_path": "<string>", "port": <int>, "service_name": "<string>"}`
6. `start_service(config_path)`: Launch the service daemon using the specified config file.
   Params: `{"config_path": "<string>"}`
7. `check_health(port)`: Query the live service health endpoint on the specified port.
   Params: `{"port": <int>}`

### Output Format:
Output strictly a single JSON block adhering to this schema:
```json
{
  "decision_summary": "1-2 sentence rationale for choosing this action.",
  "action": "<tool_name>",
  "params": { ... }
}
```
"""
        if memory_text:
            prompt += f"\n{memory_text}\n"
        return prompt

    def _render_memory_text(
        self,
        group: str,
        facts: Optional[List[StructuredFact]] = None,
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
    ) -> str:
        """Renders up-to-date memory text using UnifiedKnowledgeView for strict prompt parity."""
        if group == "B0":
            return ""
        from .knowledge_view import UnifiedKnowledgeView
        view = UnifiedKnowledgeView.from_manager_and_facts(
            lifecycle_manager=lifecycle_manager,
            facts=facts,
            freshness_ttl_s=30.0,
        )
        return view.render_knowledge_text(lifecycle_manager=lifecycle_manager)


    def run_episode(
        self,
        group: str,
        env: MultiStepDeploymentEnv,
        instance_id: str,
        run_id: str,
        facts: Optional[List[StructuredFact]] = None,
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
        max_steps: int = 20,
    ) -> Dict[str, Any]:
        """Runs a complete multi-step deployment episode."""
        start_time = time.time()
        env.setup(instance_id)

        # Integrity tracking
        if lifecycle_manager:
            initial_memory_hash = lifecycle_manager.compute_hash()
        elif facts:
            initial_memory_hash = hashlib.sha256(json.dumps([f.to_dict() for f in facts], sort_keys=True).encode()).hexdigest()
        else:
            initial_memory_hash = hashlib.sha256(b"empty_initial_memory").hexdigest()
        lifecycle_transitions: List[Dict[str, Any]] = []

        # Telemetry metrics
        proposed_error_actions = 0
        executed_error_actions = 0
        tp_blocks = 0
        fp_blocks = 0
        unknown_probes = 0
        candidate_trials = 0
        total_prompt_tokens = 0
        total_generated_tokens = 0
        total_inference_latency = 0.0
        llm_calls = 0
        tool_calls = 0
        llm_records = []
        gate_events = []

        # Prepare memory text for initial prompt
        memory_text = self._render_memory_text(group, facts=facts, lifecycle_manager=lifecycle_manager)
        system_prompt = self.build_system_prompt(memory_text)
        conversation = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Begin task: Discover the environment, choose valid placement, write config, start service, and verify health."}
        ]

        success = False
        step = 0
        budget_exhausted = False
        termination_reason = "max_steps_reached"

        while step < max_steps and not success:
            step += 1

            # Budget check before LLM call
            if llm_calls >= self.max_llm_calls or (time.time() - start_time) >= self.max_time_s:
                budget_exhausted = True
                termination_reason = "llm_budget_or_timeout_exhausted"
                break

            llm_res = self.llm.generate(conversation)
            llm_calls += 1
            total_prompt_tokens += llm_res.get("prompt_tokens", 0)
            total_generated_tokens += llm_res.get("generated_tokens", 0)
            total_inference_latency += llm_res.get("latency_s", 0.0)
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
            if tool_name in ("finish", "stop", "exit"):
                success = False
                termination_reason = "agent_finished"
                break

            action_sig = self._derive_action_signature(tool_name, params)

            # Check if proposed action is objectively failing in current environment
            is_failing_action = self._check_if_action_failing(env, tool_name, params)
            if is_failing_action:
                proposed_error_actions += 1

            # -------------------------------------------------------------
            # GATING LOGIC (Unified Pending Action Flow for B2-G and M)
            # -------------------------------------------------------------
            gate_blocked = False
            gate_reason = ""
            pre_action_applicability = None
            deferred_unknown = False

            if group == "B2-G" and lifecycle_manager:
                gate_eval = self._evaluate_generic_predicate_gate(action_sig, lifecycle_manager=lifecycle_manager)
                # Auto-probe loop for UNKNOWN premises (up to 2 retries)
                probe_retries = 0
                max_probe_retries = 2
                while gate_eval["decision"] == GateDecision.PROBE and probe_retries < max_probe_retries:
                    probe_retries += 1
                    if tool_calls >= self.max_tool_calls or (time.time() - start_time) >= self.max_time_s:
                        budget_exhausted = True
                        termination_reason = "tool_budget_or_timeout_exhausted"
                        break
                    unknown_probes += 1
                    probe_info = gate_eval.get("probe_info")
                    if not probe_info:
                        matching_rule_id = gate_eval.get("matching_rule_id")
                        target_rule = lifecycle_manager.rules.get(matching_rule_id) if matching_rule_id else None
                        unknown_pred = self._find_unknown_predicate_for_rule(lifecycle_manager, target_rule)
                        probe_info = self._resolve_probe_for_predicate(unknown_pred, params)
                    if not probe_info:
                        break
                    tool_calls += 1
                    probe_tool = probe_info["tool"]
                    probe_params = probe_info["params"]
                    probe_res = self._execute_tool(env, probe_tool, probe_params)
                    self._update_observations_from_probe_result(
                        probe_tool, probe_params, probe_res,
                        lifecycle_manager=lifecycle_manager,
                        facts=facts,
                    )
                    conversation[0]["content"] = self.build_system_prompt(
                        self._render_memory_text(group, facts=facts, lifecycle_manager=lifecycle_manager)
                    )
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "PROBE",
                        "probe_tool": probe_tool,
                        "probe_params": probe_params,
                        "probe_res": probe_res,
                    })
                    # Re-evaluate the same pending action without calling model
                    gate_eval = self._evaluate_generic_predicate_gate(action_sig, lifecycle_manager=lifecycle_manager)

                decision = gate_eval["decision"]
                if decision == GateDecision.BLOCK:
                    gate_blocked = True
                    gate_reason = gate_eval["reason"]
                    if is_failing_action:
                        tp_blocks += 1
                    else:
                        fp_blocks += 1
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "BLOCK",
                        "reason": gate_reason,
                        "is_tp": is_failing_action,
                    })
                elif decision == GateDecision.PROBE:
                    deferred_unknown = True
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "DEFERRED_UNKNOWN",
                        "reason": gate_eval["reason"],
                    })
                elif decision == GateDecision.ALLOW:
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "ALLOW",
                        "reason": gate_eval.get("reason", "Generic gate allowed."),
                    })

            elif group == "M" and lifecycle_manager:
                pre_app = {}
                for r_id, r in lifecycle_manager.rules.items():
                    if r.action_signature == action_sig:
                        pre_app[r_id] = lifecycle_manager.evaluate_applicability(r)
                gate_eval = lifecycle_manager.make_gate_decision(action_sig)
                pre_action_applicability = pre_app

                # Auto-probe loop for UNKNOWN premises (up to 2 retries)
                probe_retries = 0
                max_probe_retries = 2
                while gate_eval["decision"] == GateDecision.PROBE and probe_retries < max_probe_retries:
                    probe_retries += 1
                    if tool_calls >= self.max_tool_calls or (time.time() - start_time) >= self.max_time_s:
                        budget_exhausted = True
                        termination_reason = "tool_budget_or_timeout_exhausted"
                        break
                    unknown_probes += 1
                    matching_rule_id = gate_eval.get("matching_rule_id")
                    target_rule = lifecycle_manager.rules.get(matching_rule_id) if matching_rule_id else None
                    unknown_pred = self._find_unknown_predicate_for_rule(lifecycle_manager, target_rule)
                    probe_info = self._resolve_probe_for_predicate(unknown_pred, params)
                    if not probe_info:
                        break
                    tool_calls += 1
                    probe_tool = probe_info["tool"]
                    probe_params = probe_info["params"]
                    probe_res = self._execute_tool(env, probe_tool, probe_params)
                    self._update_observations_from_probe_result(
                        probe_tool, probe_params, probe_res,
                        lifecycle_manager=lifecycle_manager,
                        facts=facts,
                    )
                    conversation[0]["content"] = self.build_system_prompt(
                        self._render_memory_text(group, facts=facts, lifecycle_manager=lifecycle_manager)
                    )
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "PROBE",
                        "probe_tool": probe_tool,
                        "probe_params": probe_params,
                        "probe_res": probe_res,
                    })
                    # Re-evaluate pre_action_applicability and gate decision
                    pre_app = {}
                    for r_id, r in lifecycle_manager.rules.items():
                        if r.action_signature == action_sig:
                            pre_app[r_id] = lifecycle_manager.evaluate_applicability(r)
                    pre_action_applicability = pre_app
                    gate_eval = lifecycle_manager.make_gate_decision(action_sig)

                decision = gate_eval["decision"]
                if decision == GateDecision.BLOCK:
                    gate_blocked = True
                    gate_reason = gate_eval["reason"]
                    if is_failing_action:
                        tp_blocks += 1
                    else:
                        fp_blocks += 1
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "BLOCK",
                        "reason": gate_reason,
                        "is_tp": is_failing_action,
                    })
                elif decision == GateDecision.PROBE:
                    deferred_unknown = True
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "DEFERRED_UNKNOWN",
                        "reason": gate_eval["reason"],
                    })
                elif decision == GateDecision.ALLOW and "candidate" in gate_eval.get("reason", "").lower():
                    candidate_trials += 1
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "CANDIDATE_TRIAL",
                        "reason": gate_eval["reason"],
                    })
                elif decision == GateDecision.ALLOW:
                    gate_events.append({
                        "step": step,
                        "action": action_sig,
                        "decision": "ALLOW",
                        "reason": gate_eval.get("reason", "Lifecycle gate allowed."),
                    })

            if budget_exhausted:
                break

            if gate_blocked:
                conversation.append({"role": "assistant", "content": raw_output})
                conversation.append({"role": "user", "content": f"[Constraint Gate Blocked] Action '{action_sig}' blocked: {gate_reason}. Original action was NOT executed. Please select an alternative action."})
                continue

            if deferred_unknown:
                conversation.append({"role": "assistant", "content": raw_output})
                conversation.append({"role": "user", "content": f"[Constraint Gate Deferred] Action '{action_sig}' deferred: Precondition remains UNKNOWN after probe. Original action was NOT executed. Please inspect environment or select an alternative action."})
                continue

            # Check budget before executing tool
            if tool_calls >= self.max_tool_calls or (time.time() - start_time) >= self.max_time_s:
                budget_exhausted = True
                termination_reason = "tool_budget_or_timeout_exhausted"
                break

            # Execute Tool (Pending Action allowed)
            tool_calls += 1
            tool_res = self._execute_tool(env, tool_name, params)
            if tool_name in ("probe_port", "probe_directory", "probe_file"):
                self._update_observations_from_probe_result(
                    tool_name, params, tool_res,
                    lifecycle_manager=lifecycle_manager,
                    facts=facts,
                )
                conversation[0]["content"] = self.build_system_prompt(
                    self._render_memory_text(group, facts=facts, lifecycle_manager=lifecycle_manager)
                )
            tool_success = tool_res.get("success", tool_res.get("healthy", True) if tool_name == "check_health" else True)
            tool_exit_code = tool_res.get("exit_code", 0)

            if not tool_success or tool_exit_code != 0:
                executed_error_actions += 1

            # Update lifecycle outcomes if M
            if group == "M" and lifecycle_manager:
                real_evidence_id = tool_res.get("call_id") or f"ev_tool_{step}_{int(time.time()*1000)}"
                trans = lifecycle_manager.record_action_outcome(
                    action_signature=action_sig,
                    success=tool_success,
                    error_details={
                        "error_code": tool_res.get("error_code", tool_exit_code),
                        "error_type": tool_res.get("error_type"),
                        "evidence_id": real_evidence_id,
                    },
                    pre_action_applicability=pre_action_applicability,
                    evidence_id=real_evidence_id,
                )
                if trans:
                    lifecycle_transitions.extend(trans)

            # Check if overall task reached successful completion
            if tool_name == "check_health" and tool_res.get("healthy"):
                is_verified, verifier_msg = env.verify_completion()
                if is_verified:
                    success = True
                    termination_reason = "completed_and_verified"
                    break

            # Feed tool output back to agent
            conversation.append({"role": "assistant", "content": raw_output})
            conversation.append({"role": "user", "content": f"[Tool Output: {tool_name}]\n{json.dumps(tool_res, indent=2)}"})

        end_time = time.time()
        end_to_end_latency = round(end_time - start_time, 3)

        # Final verifier check
        is_verified, verifier_msg = env.verify_completion()
        final_success = success and is_verified

        if lifecycle_manager:
            final_memory_hash = lifecycle_manager.compute_hash()
        elif facts:
            final_memory_hash = hashlib.sha256(json.dumps([f.to_dict() for f in facts], sort_keys=True).encode()).hexdigest()
        else:
            final_memory_hash = hashlib.sha256(b"empty_final_memory").hexdigest()

        return {
            "run_id": run_id,
            "group": group,
            "instance_id": instance_id,
            "success": final_success,
            "steps": step,
            "termination_reason": termination_reason,
            "budget_exhausted": budget_exhausted,
            "proposed_error_actions": proposed_error_actions,
            "executed_error_actions": executed_error_actions,
            "tp_blocks": tp_blocks,
            "fp_blocks": fp_blocks,
            "unknown_probes": unknown_probes,
            "candidate_trials": candidate_trials,
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "prompt_tokens": total_prompt_tokens,
            "generated_tokens": total_generated_tokens,
            "total_tokens": total_prompt_tokens + total_generated_tokens,
            "inference_latency_s": round(total_inference_latency, 3),
            "end_to_end_latency_s": end_to_end_latency,
            "verifier_message": verifier_msg,
            "tool_records": env.tool_call_history,
            "llm_records": llm_records,
            "gate_events": gate_events,
            "state_events": env.state_events_log,
            "initial_memory_hash": initial_memory_hash,
            "final_memory_hash": final_memory_hash,
            "lifecycle_transitions": lifecycle_transitions,
        }

    def _derive_action_signature(self, tool_name: str, params: Dict[str, Any]) -> str:
        if tool_name == "start_service":
            port = params.get("port")
            if port is None and "config_path" in params:
                cfg_path = params["config_path"]
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            cfg = json.load(f)
                        port = cfg.get("port")
                    except Exception:
                        pass
            if port is not None:
                return f"start_service:port={port}"
            return f"start_service:{params.get('config_path', '')}"
        elif tool_name == "write_config":
            fp = params.get("config_path", params.get("filepath", ""))
            return f"write_config:filepath={fp}"
        elif tool_name == "probe_port":
            return f"probe_port:{params.get('port')}"
        elif tool_name == "probe_directory":
            return f"probe_directory:{params.get('dirpath')}"
        elif tool_name == "probe_file":
            return f"probe_file:{params.get('filepath')}"
        elif tool_name == "check_health":
            return f"check_health:{params.get('port')}"
        return f"{tool_name}"

    def _check_if_action_failing(self, env: MultiStepDeploymentEnv, tool_name: str, params: Dict[str, Any]) -> bool:
        """Ground truth offline scoring only. Does not leak to agent."""
        if tool_name == "write_config":
            cfg_path = params.get("config_path", "")
            if cfg_path.startswith("/etc/service_demo"):
                return True
        elif tool_name == "start_service":
            cfg_path = params.get("config_path", "")
            if not os.path.exists(cfg_path):
                return True
            try:
                with open(cfg_path, "r") as f:
                    cfg = json.load(f)
                port = cfg.get("port")
                if is_port_listening(port):
                    return True
            except Exception:
                return True
        elif tool_name == "check_health":
            port = params.get("port", 0)
            if not is_port_listening(port):
                return True
        return False

    def _execute_tool(self, env: MultiStepDeploymentEnv, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "discover_environment":
            return env.discover_environment()
        elif tool_name == "probe_port":
            return env.probe_port(params.get("port", 18080))
        elif tool_name == "probe_directory":
            return env.probe_directory(params.get("dirpath", "/etc/service_demo"))
        elif tool_name == "probe_file":
            return env.probe_file(params.get("filepath", "/home/agentuser/service_conf/app.json"))
        elif tool_name == "write_config":
            return env.write_config(
                config_path=params.get("config_path", "/home/agentuser/service_conf/app.json"),
                port=params.get("port", 18080),
                service_name=params.get("service_name", "telemetry_agent"),
            )
        elif tool_name == "start_service":
            return env.start_service(params.get("config_path", "/home/agentuser/service_conf/app.json"))
        elif tool_name == "check_health":
            return env.check_health(params.get("port", 18080))
        else:
            return {"success": False, "exit_code": 1, "error": f"Unknown tool: {tool_name}"}

    def _evaluate_generic_predicate_gate(
        self,
        action_sig: str,
        lifecycle_manager: ConstraintLifecycleManager,
    ) -> Dict[str, Any]:
        """
        Generic predicate gate for B2-G using structured predicate evaluation over lifecycle_manager.rules.
        Evaluates precondition predicates:
        - APPLICABLE (premise True) -> BLOCK (no candidate probation)
        - UNKNOWN (premise missing or expired) -> PROBE
        - NOT_APPLICABLE (premise False) -> ALLOW
        """
        if not lifecycle_manager or not lifecycle_manager.rules:
            return {"decision": GateDecision.ALLOW, "reason": "No rules available."}

        matching_rules = [r for r in lifecycle_manager.rules.values() if r.action_signature == action_sig]
        for r in matching_rules:
            if r.validity_state in (ValidityState.RETIRED, ValidityState.CONTRADICTED):
                continue
            app = lifecycle_manager.evaluate_applicability(r)
            if app == ApplicabilityState.APPLICABLE:
                return {
                    "decision": GateDecision.BLOCK,
                    "matching_rule_id": r.rule_id,
                    "reason": f"Generic predicate gate blocked: rule {r.rule_id} premise confirmed APPLICABLE.",
                }
            elif app == ApplicabilityState.UNKNOWN:
                unknown_pred = self._find_unknown_predicate_for_rule(lifecycle_manager, r)
                probe_info = self._resolve_probe_for_predicate(unknown_pred, {})
                return {
                    "decision": GateDecision.PROBE,
                    "matching_rule_id": r.rule_id,
                    "probe_info": probe_info,
                    "probe_tool": probe_info["tool"] if probe_info else "probe_port",
                    "probe_params": probe_info["params"] if probe_info else {},
                    "reason": f"Generic predicate gate deferred: rule {r.rule_id} premise is UNKNOWN; probe required.",
                }
        return {"decision": GateDecision.ALLOW, "reason": "No blocking predicate matches."}

    def _find_unknown_predicate_for_rule(self, lifecycle_manager: ConstraintLifecycleManager, rule: Optional[ConstraintRule]):
        if not rule:
            return None
        now = lifecycle_manager.time_provider()
        for pred in rule.predicates:
            obs = lifecycle_manager.observations.get(pred.key)
            if obs is None or (now - obs.timestamp) > pred.ttl:
                return pred
        return rule.predicates[0] if rule.predicates else None

    def _resolve_probe_for_predicate(self, predicate: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not predicate:
            return None
        res_type = getattr(predicate, "resource_type", "")
        res_path = getattr(predicate, "resource_path", "")
        var_name = getattr(predicate, "key", getattr(predicate, "variable_name", ""))

        if res_type == "port" or ("port" in var_name):
            if res_path and res_path.isdigit():
                p = int(res_path)
            else:
                match = re.search(r"port:(\d+)", var_name)
                p = int(match.group(1)) if match else params.get("port", 18080)
            return {"tool": "probe_port", "params": {"port": p}, "key": var_name}
        elif res_type in ("dir", "directory") or var_name.startswith("dir:"):
            target_path = res_path or (var_name.split(":", 1)[1] if ":" in var_name else "/etc/service_demo")
            if target_path.endswith(":writable"):
                target_path = target_path.replace(":writable", "")
            return {"tool": "probe_directory", "params": {"dirpath": target_path}, "key": var_name}
        elif res_type == "file" or var_name.startswith("file:"):
            target_path = res_path or (var_name.split(":", 1)[1] if ":" in var_name else "/etc/service_demo/app.conf")
            if target_path.endswith(":writable"):
                target_path = target_path.replace(":writable", "")
            if not target_path and "filepath" in params:
                target_path = params["filepath"]
            elif not target_path and "config_path" in params:
                target_path = params["config_path"]
            return {"tool": "probe_file", "params": {"filepath": target_path}, "key": var_name}
        return None

    def _update_observations_from_probe_result(
        self,
        tool_name: str,
        params: Dict[str, Any],
        tool_res: Dict[str, Any],
        lifecycle_manager: Optional[ConstraintLifecycleManager] = None,
        facts: Optional[List[StructuredFact]] = None,
    ):
        """
        Unified observation update entry point for BOTH normal tool calls and gate auto-probes.
        Updates B2 facts, B2-G cache, and M observation store with call_id and timestamp.
        """
        ts = tool_res.get("timestamp", time.time())
        cid = tool_res.get("call_id", "")
        success = tool_res.get("success", True)
        exit_code = tool_res.get("exit_code", 0)

        if tool_name == "probe_port":
            port = params.get("port")
            if port is not None:
                key = f"port:{port}:occupied"
                if not success or exit_code != 0 or "is_occupied" not in tool_res:
                    # Invalidate old observation: probe failed or missing field -> UNKNOWN
                    if lifecycle_manager and key in lifecycle_manager.observations:
                        del lifecycle_manager.observations[key]
                    if facts is not None:
                        res_str = f"port:{port}"
                        for f in facts:
                            if f.resource == res_str:
                                f.state_description = "UNKNOWN"
                                f.timestamp = ts
                else:
                    is_occupied = tool_res["is_occupied"]
                    if lifecycle_manager:
                        lifecycle_manager.register_observation(
                            key,
                            is_occupied,
                            timestamp=ts,
                            call_id=cid,
                        )
                    if facts is not None:
                        res_str = f"port:{port}"
                        state_desc = "occupied" if is_occupied else "free"
                        found = False
                        for f in facts:
                            if f.resource == res_str:
                                f.state_description = state_desc
                                f.timestamp = ts
                                f.evidence_id = cid or f.evidence_id
                                found = True
                                break
                        if not found:
                            facts.append(
                                StructuredFact(
                                    fact_id=f"fact_probe_{port}_{int(ts*1000)}",
                                    resource=res_str,
                                    state_description=state_desc,
                                    error_signature="",
                                    evidence_id=cid or f"ev_{port}_{int(ts*1000)}",
                                    run_id="runtime_probe",
                                    step=0,
                                    timestamp=ts,
                                )
                            )

        elif tool_name == "probe_directory":
            dirpath = params.get("dirpath")
            if dirpath:
                key = f"dir:{dirpath}:writable"
                if not success or exit_code != 0 or "writable_by_user" not in tool_res:
                    # Invalidate old observation: probe failed or missing field -> UNKNOWN
                    if lifecycle_manager and key in lifecycle_manager.observations:
                        del lifecycle_manager.observations[key]
                    if facts is not None:
                        for f in facts:
                            if f.resource == dirpath or f.resource == f"dir:{dirpath}":
                                f.state_description = "UNKNOWN"
                                f.timestamp = ts
                else:
                    is_writable = tool_res["writable_by_user"]
                    if lifecycle_manager:
                        lifecycle_manager.register_observation(
                            key,
                            is_writable,
                            timestamp=ts,
                            call_id=cid,
                        )
                        # NOTE: Directory probe ONLY registers dir:<dirpath>:writable.
                        # Do NOT bulk-assign to file:* rules or path prefix matches!
                    if facts is not None:
                        res_str = dirpath
                        state_desc = "writable directory" if is_writable else "non-writable directory"
                        found = False
                        for f in facts:
                            if f.resource == res_str or f.resource == f"dir:{dirpath}":
                                f.state_description = state_desc
                                f.timestamp = ts
                                f.evidence_id = cid or f.evidence_id
                                found = True
                                break
                        if not found:
                            facts.append(
                                StructuredFact(
                                    fact_id=f"fact_probe_dir_{int(ts*1000)}",
                                    resource=res_str,
                                    state_description=state_desc,
                                    error_signature="",
                                    evidence_id=cid or f"ev_dir_{int(ts*1000)}",
                                    run_id="runtime_probe",
                                    step=0,
                                    timestamp=ts,
                                )
                            )

        elif tool_name == "probe_file":
            filepath = params.get("filepath")
            if filepath:
                key = f"file:{filepath}:writable"
                if not success or exit_code != 0 or "writable_by_user" not in tool_res:
                    # Invalidate old observation: probe failed or missing field -> UNKNOWN
                    if lifecycle_manager and key in lifecycle_manager.observations:
                        del lifecycle_manager.observations[key]
                    if facts is not None:
                        for f in facts:
                            if f.resource == filepath or f.resource == f"file:{filepath}":
                                f.state_description = "UNKNOWN"
                                f.timestamp = ts
                else:
                    is_writable = tool_res["writable_by_user"]
                    if lifecycle_manager:
                        lifecycle_manager.register_observation(
                            key,
                            is_writable,
                            timestamp=ts,
                            call_id=cid,
                        )
                    if facts is not None:
                        res_str = filepath
                        state_desc = "writable file" if is_writable else "non-writable file"
                        found = False
                        for f in facts:
                            if f.resource == res_str or f.resource == f"file:{filepath}":
                                f.state_description = state_desc
                                f.timestamp = ts
                                f.evidence_id = cid or f.evidence_id
                                found = True
                                break
                        if not found:
                            facts.append(
                                StructuredFact(
                                    fact_id=f"fact_probe_file_{int(ts*1000)}",
                                    resource=res_str,
                                    state_description=state_desc,
                                    error_signature="",
                                    evidence_id=cid or f"ev_file_{int(ts*1000)}",
                                    run_id="runtime_probe",
                                    step=0,
                                    timestamp=ts,
                                )
                            )
