"""
Stateful Agent Execution Runner for FailMem Stage 2.
Integrates:
  - TaskStateTracker (task_state.py)
  - PersistentPlan (plan_manager.py)
  - ActionValidator (action_validator.py) with 2-pass validation & strict budget enforcement
  - RepairController (repair_controller.py)
  - CompletionChecker (completion_checker.py)
  - RepairMemoryStore (repair_memory.py)
  - Traceable per-step logging of raw prompts, responses, validation, and tool outcomes.
"""
from typing import Dict, Any, List, Optional, Tuple
import time
import copy

from .llm_backend import LLMBackend
from .planner import TOOL_SCHEMAS, MAP_ADJACENCY, SYSTEM_PROMPT, format_map_topology_description
from .task_state import TaskStateTracker, ObligationStatus, ObservedFact
from .plan_manager import PersistentPlan, PlanNode, PlanNodeStatus
from .action_validator import ActionValidator, ValidationStatus
from .repair_controller import RepairController
from .completion_checker import CompletionChecker
from ..env.task_env import DeliveryTaskEnv
from ..env.tools import StatusCode, ActionResult


class StatefulAgentRunner:
    def __init__(
        self,
        llm_backend: LLMBackend,
        adjacency_map: Optional[Dict[str, List[str]]] = None,
        max_tool_calls: int = 25,
        max_llm_calls: int = 20,
        max_sim_time_s: float = 300.0,
        run_id: str = "run_stateful",
        repair_memory_store: Optional[Any] = None,
        include_historical_facts: bool = False,
        is_static: bool = False,
    ):
        self.llm = llm_backend
        self.adjacency_map = adjacency_map or MAP_ADJACENCY
        self.max_tool_calls = max_tool_calls
        self.max_llm_calls = max_llm_calls
        self.max_sim_time_s = max_sim_time_s
        self.run_id = run_id
        self.repair_memory_store = repair_memory_store
        self.include_historical_facts = include_historical_facts
        self.is_static = is_static

        self.validator = ActionValidator(self.adjacency_map)
        self.repair_controller = RepairController(self.adjacency_map)

    def run_task(
        self,
        task_spec: Dict[str, Any],
        task_index: int = 0,
        seq_id: str = "seq_default",
        initial_known_state: Optional[Dict[str, Any]] = None,
        historical_failure_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        task_id = task_spec.get("task_id", f"task_{task_index}")
        instruction = task_spec.get("instruction", "")
        env_config = copy.deepcopy(task_spec.get("env_config", {}))
        env_config["time_limit_s"] = self.max_sim_time_s

        env = DeliveryTaskEnv(env_config)
        t_wall_start = time.time()

        # 1. Initialize Task State Tracker
        initial_agent_state = env.get_agent_initial_state()
        task_state = TaskStateTracker(
            task_instruction=instruction,
            initial_state=initial_agent_state,
            max_inventory_capacity=env.max_inventory_capacity,
            is_static=self.is_static,
        )

        # Ingest shared known state (e.g. from current shared sensory observation)
        if initial_known_state:
            for k, v in initial_known_state.items():
                if isinstance(v, ObservedFact):
                    task_state.observed_facts[k] = copy.deepcopy(v)
                elif isinstance(v, dict):
                    task_state.observed_facts[k] = ObservedFact(
                        key=k,
                        value=v.get("value", str(v)),
                        evidence_ref=v.get("evidence_ref", "evt_shared_seed"),
                        sim_time=v.get("sim_time", 0.0),
                        source_tool=v.get("source_tool", "observe"),
                    )
                else:
                    task_state.observed_facts[k] = ObservedFact(
                        key=k,
                        value=v,
                        evidence_ref="evt_shared_seed",
                        sim_time=0.0,
                        source_tool="observe",
                    )

        # 2. Initialize Persistent Plan
        persistent_plan = PersistentPlan(task_state, self.adjacency_map)
        persistent_plan.initialize_initial_plan()

        step_history: List[Dict[str, Any]] = []
        llm_traces: List[Dict[str, Any]] = []
        validation_records: List[Dict[str, Any]] = []
        intercepted_actions_count: int = 0
        total_revisions_count: int = 0

        while not env.is_terminated and len(step_history) < self.max_tool_calls and len(llm_traces) < self.max_llm_calls:
            step_idx = len(step_history) + 1
            robot_loc_before = env.robot_location

            # Check if all obligations are completed
            if task_state.is_all_completed():
                break

            active_node = persistent_plan.get_current_active_node()
            state_summary = task_state.get_public_state_summary()

            # 3. Build User Prompt from Plan & State
            user_prompt_lines = [
                f"### Current Delivery Task: {instruction}",
                format_map_topology_description(self.adjacency_map),
                f"### Robot Physical Status:",
                f"- Current Location: {task_state.robot_location}",
                f"- Allowed Adjacent Zones: {self.adjacency_map.get(task_state.robot_location, [])}",
                f"- Inventory (Capacity {len(task_state.inventory)}/{task_state.max_inventory_capacity}): {task_state.inventory}",
                f"- Credentials Held: {list(task_state.credentials)}",
                f"- Battery Level: {task_state.battery}%",
                persistent_plan.format_plan_prompt_section(),
            ]

            if active_node:
                user_prompt_lines.append(f"\n### Immediate Active Subgoal:\n-> {active_node.summary_str}")
                if active_node.preconditions:
                    user_prompt_lines.append(f"   Required Preconditions: {active_node.preconditions}")

            if task_state.observed_facts:
                fact_dict = {k: task_state.get_fact_value(k) for k in task_state.observed_facts}
                user_prompt_lines.append(f"### Known / Observed Environmental Facts: {fact_dict}")

            # Historical facts / failures for Group C / D
            if self.include_historical_facts and historical_failure_events:
                user_prompt_lines.append("### Structured Historical Failure Facts:")
                for h_evt in historical_failure_events:
                    user_prompt_lines.append(f"- Past Failure: {h_evt.get('action_name')}({h_evt.get('target')}) failed with [{h_evt.get('error_code')}]. Obs: {h_evt.get('observation')}")

            if step_history:
                user_prompt_lines.append("### Recent Step History in Current Task:")
                for h in step_history[-4:]:
                    res = h.get("result", {})
                    user_prompt_lines.append(f"- Step {h['step']}: {h['tool']}({h['params']}) -> [{res.get('status')}] {res.get('message')}")

            user_prompt_lines.append("\nPlease output your next action decision in JSON format matching the active plan node.")
            user_prompt = "\n".join(user_prompt_lines)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            # 4. Check LLM Budget Before Calling
            if len(llm_traces) >= self.max_llm_calls:
                break

            gen_res = self.llm.generate(messages)
            content = gen_res.get("content", "")
            decision, parse_ok, parse_err = self._parse_json(content)

            trace_att1 = {
                "event_id": f"evt_{self.run_id}_{seq_id}_{task_id}_s{step_idx:02d}",
                "prompt_tokens": gen_res.get("prompt_tokens", 0),
                "generated_tokens": gen_res.get("generated_tokens", 0),
                "latency_s": gen_res.get("latency_s", 0.0),
                "raw_response": content,
                "parse_ok": parse_ok,
                "first_call": True,
            }
            llm_traces.append(trace_att1)

            if not parse_ok:
                tool_name = "parse_error"
                params = {"raw_output": content}
            else:
                tool_name = decision.get("action", "parse_error")
                params = decision.get("params", {})

            # 5. Pre-Execution Action Validation (Pass 1)
            is_action_valid = True
            if tool_name != "parse_error":
                v_res = self.validator.validate_action(
                    tool_name=tool_name,
                    params=params,
                    current_state=state_summary,
                    known_facts=task_state.observed_facts,
                    active_plan_node=active_node,
                )
                validation_records.append({
                    "step": step_idx,
                    "tool": tool_name,
                    "params": params,
                    "status": v_res.status.value,
                    "reason": v_res.reason,
                    "pass_num": 1,
                })

                if v_res.status == ValidationStatus.FAIL:
                    intercepted_actions_count += 1
                    # Check remaining LLM budget for 1-shot revision
                    if len(llm_traces) < self.max_llm_calls:
                        total_revisions_count += 1
                        rev_messages = list(messages)
                        rev_messages.append({"role": "assistant", "content": content})
                        rev_messages.append({
                            "role": "user",
                            "content": f"Pre-Execution Conflict: {v_res.reason}. Conflicting Precondition: {v_res.conflicting_precondition}. Please revise your action decision."
                        })
                        rev_res = self.llm.generate(rev_messages)
                        rev_dec, rev_ok, _ = self._parse_json(rev_res.get("content", ""))
                        rev_trace = {
                            "event_id": f"evt_{self.run_id}_{seq_id}_{task_id}_s{step_idx:02d}_val_retry",
                            "prompt_tokens": rev_res.get("prompt_tokens", 0),
                            "generated_tokens": rev_res.get("generated_tokens", 0),
                            "latency_s": rev_res.get("latency_s", 0.0),
                            "raw_response": rev_res.get("content", ""),
                            "parse_ok": rev_ok,
                            "first_call": False,
                        }
                        llm_traces.append(rev_trace)

                        if rev_ok:
                            tool_name = rev_dec.get("action", tool_name)
                            params = rev_dec.get("params", params)

                            # Pass 2: Re-validate revised action
                            v_res2 = self.validator.validate_action(
                                tool_name=tool_name,
                                params=params,
                                current_state=state_summary,
                                known_facts=task_state.observed_facts,
                                active_plan_node=active_node,
                            )
                            validation_records.append({
                                "step": step_idx,
                                "tool": tool_name,
                                "params": params,
                                "status": v_res2.status.value,
                                "reason": v_res2.reason,
                                "pass_num": 2,
                            })
                            if v_res2.status == ValidationStatus.FAIL:
                                is_action_valid = False
                        else:
                            is_action_valid = False
                    else:
                        is_action_valid = False

            # 6. Execute or Intercept
            event_id = f"evt_{self.run_id}_{seq_id}_{task_id}_s{step_idx:02d}"
            env_state_snapshot = {
                "doors": copy.deepcopy(env.doors),
                "robot_location": env.robot_location,
                "battery": env.battery,
            }

            if not is_action_valid:
                # Intercepted illegal action - consume nominal turn resource without illegal physical breach
                env._consume_resources(1.0, 1)
                result = ActionResult(
                    status=StatusCode.INVALID_PARAMETER,
                    success=False,
                    message="Action intercepted by Pre-Execution Validator (illegal precondition violated after revision).",
                    time_cost_s=1.0,
                    battery_cost_pct=1,
                    error_code="INTERCEPTED_PRECONDITION_VIOLATION",
                )
            elif tool_name == "parse_error":
                env._consume_resources(1.0, 1)
                result = ActionResult(
                    status=StatusCode.PARSE_ERROR,
                    success=False,
                    message="JSON parsing error.",
                    time_cost_s=1.0,
                    battery_cost_pct=1,
                    error_code="PARSE_ERROR",
                )
            else:
                result = env.step(tool_name, params)

            # 7. Update Task State Tracker
            task_state.update_from_tool_result(
                tool_name=tool_name,
                params=params,
                result=result.to_dict(),
                event_id=event_id,
                sim_time=env.sim_time_s,
            )

            # Update repair memory store invalidation with observed facts
            if self.repair_memory_store and hasattr(self.repair_memory_store, "update_with_observation"):
                self.repair_memory_store.update_with_observation(
                    task_state.observed_facts,
                    target_run_id=self.run_id,
                    event_id=event_id,
                    sim_time=env.sim_time_s,
                )
                if result.observation:
                    self.repair_memory_store.update_with_observation(
                        result.observation,
                        target_run_id=self.run_id,
                        event_id=event_id,
                        sim_time=env.sim_time_s,
                    )

            # Log target step execution if this was a memory repair node
            if active_node and getattr(active_node, "is_repair_node", False) and self.repair_memory_store:
                mem_id = active_node.id.split("_")[1] if active_node.id.startswith("rmem_") else "mem_active"
                if hasattr(self.repair_memory_store, "log_target_step_executed"):
                    self.repair_memory_store.log_target_step_executed(
                        target_run_id=self.run_id,
                        memory_id=mem_id,
                        plan_node_id=active_node.id,
                        tool=tool_name,
                        params=params,
                        success=result.success,
                        event_id=event_id,
                        sim_time=env.sim_time_s,
                    )

            # 8. Handle Success vs Failure in Plan & Repair Controller
            if result.success:
                persistent_plan.on_step_success(tool_name, params, event_id, result.observation)
                if tool_name == "acquire_credential" and self.repair_memory_store and hasattr(self.repair_memory_store, "log_target_effect_verified"):
                    cname = params.get("credential_name", "security_badge")
                    self.repair_memory_store.log_target_effect_verified(
                        target_run_id=self.run_id,
                        memory_id="mem_active",
                        verified_effects=[f"has_credential({cname})"],
                        sim_time=env.sim_time_s,
                    )
            else:
                should_abort, rep_msg, rep_nodes = self.repair_controller.handle_failure(
                    failed_tool=tool_name,
                    failed_params=params,
                    error_code=result.error_code or result.status.value,
                    observation=result.observation or {},
                    task_state=task_state,
                    plan=persistent_plan,
                    repair_memory_adapter=self.repair_memory_store,
                    target_run_id=self.run_id,
                )
                if should_abort:
                    env.constraint_violations.append(rep_msg)
                    env.is_terminated = True

            step_entry = {
                "step": step_idx,
                "event_id": event_id,
                "tool": tool_name,
                "params": params,
                "robot_location_before": robot_loc_before,
                "robot_location_after": env.robot_location,
                "env_state_snapshot": env_state_snapshot,
                "result": result.to_dict(),
                "sim_time_s": env.sim_time_s,
                "battery": env.battery,
            }
            step_history.append(step_entry)

        # 9. Tool Evidence Verification
        is_succ, comp_reason, comp_details = CompletionChecker.verify_completion(
            task_state=task_state,
            step_history=step_history,
            constraint_violations=env.constraint_violations,
        )

        t_wall_total = time.time() - t_wall_start

        return {
            "task_id": task_id,
            "instruction": instruction,
            "success": is_succ,
            "completion_reason": comp_reason,
            "completion_details": comp_details,
            "step_count": len(step_history),
            "step_history": step_history,
            "llm_calls": len(llm_traces),
            "llm_traces": llm_traces,
            "validation_records": validation_records,
            "intercepted_actions_count": intercepted_actions_count,
            "total_revisions_count": total_revisions_count,
            "sim_time_s": env.sim_time_s,
            "battery_consumed": env.cumulative_battery_consumed,
            "final_battery": env.battery,
            "constraint_violations": list(env.constraint_violations),
            "wall_time_s": round(t_wall_total, 2),
            "plan_revisions": len(persistent_plan.revision_history),
            "plan_revision_log": persistent_plan.revision_history,
            "initial_known_state": initial_known_state or {},
            "source_history_events": historical_failure_events or [],
            "memory_audit_log": list(self.repair_memory_store.audit_log) if (self.repair_memory_store and hasattr(self.repair_memory_store, "audit_log")) else [],
            "target_audit_log": list(self.repair_memory_store.target_audit_log) if (self.repair_memory_store and hasattr(self.repair_memory_store, "target_audit_log")) else [],
            "memory_items": [m.to_dict() for m in self.repair_memory_store.get_all_memories()] if (self.repair_memory_store and hasattr(self.repair_memory_store, "get_all_memories")) else [],
        }

    def _parse_json(self, text: str) -> Tuple[Dict[str, Any], bool, str]:
        import re
        import json
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            raw = m.group(1)
        else:
            m2 = re.search(r"(\{.*\})", text, re.DOTALL)
            raw = m2.group(1) if m2 else text

        try:
            p = json.loads(raw)
            if isinstance(p, dict) and "action" in p:
                return p, True, ""
            return {}, False, "JSON missing 'action' field"
        except Exception as e:
            return {}, False, str(e)
