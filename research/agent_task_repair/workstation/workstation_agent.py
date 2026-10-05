"""
Unified Agent Runner with Common Local Plan Executor for Workstation Multi-Fault Benchmark.

Implements 5 strictly fair evaluation groups:
  1. Group_B2_step: Structured facts + single-step LLM planning.
  2. Group_B2_plan: Structured facts + multi-step LLM planning via CommonLocalPlanExecutor.
  3. Group_B1_plan: Full raw source trajectories + multi-step LLM planning via CommonLocalPlanExecutor.
  4. Group_Replay: Naive trajectory replay matching observed fault via CommonLocalPlanExecutor.
  5. Group_D: Structured facts + conditional procedural memory via CommonLocalPlanExecutor.

All groups share the identical:
  - Unified action execution pipeline (Pop -> Precondition Validation -> env.step -> Known State Update -> Postcondition Verify)
  - CommonLocalPlanExecutor (max plan length = 4)
  - Pre-execution validation checks (same domain interlock rules for all groups)
  - ConstraintEvent feedback into prompt upon interception or tool error
  - Postcondition verification comparing expected vs observed effects
  - Budget accounting (32 LLM / 40 Tools / 300s timeout)
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import json
import time
import copy
import re
from dataclasses import dataclass, field, asdict

from .workstation_env import WorkstationEnv, StatusCode
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
)
from ..agent.llm_backend import LLMBackend


MAX_PLAN_LEN = 4

WORKSTATION_SYSTEM_PROMPT_STEP = """You are an autonomous robotic workstation diagnostic and recovery agent in a simulated environment.
The workstation consists of 5 subsystems:
  1. power_unit (Primary power & safety relay)
  2. pneumatic_line (Compressed air supply)
  3. arm_gripper (Robotic end-effector)
  4. camera_sensor (Vision inspection sensor)
  5. controller (Safety & sequence controller)

Available Tools:
  - inspect(subsystem="all"|"power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Query diagnostic state.
  - isolate(subsystem="power_unit"|"pneumatic_line", action="engage"|"release"): Safety lockout (engage) or restore energy line (release).
  - clear_fault(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Clear active fault.
  - reset(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Reset subsystem to operating/home state.
  - calibrate(subsystem="camera_sensor"|"arm_gripper"): Run precision calibration.
  - self_test(target="workstation"): Run comprehensive safety self-test (all subsystems must be nominal and calibrated).
  - resume(target="workstation"): Resume normal production (requires successful self_test).

Response Format:
Respond with a JSON object strictly following this schema:
```json
{
  "thought": "Your step-by-step diagnostic reasoning...",
  "tool": "<tool_name>",
  "args": {<argument_key>: <argument_value>}
}
```
"""

WORKSTATION_SYSTEM_PROMPT_PLAN = """You are an autonomous robotic workstation diagnostic and recovery agent in a simulated environment.
The workstation consists of 5 subsystems:
  1. power_unit (Primary power & safety relay)
  2. pneumatic_line (Compressed air supply)
  3. arm_gripper (Robotic end-effector)
  4. camera_sensor (Vision inspection sensor)
  5. controller (Safety & sequence controller)

Available Tools:
  - inspect(subsystem="all"|"power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Query diagnostic state.
  - isolate(subsystem="power_unit"|"pneumatic_line", action="engage"|"release"): Safety lockout (engage) or restore energy line (release).
  - clear_fault(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Clear active fault.
  - reset(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Reset subsystem to operating/home state.
  - calibrate(subsystem="camera_sensor"|"arm_gripper"): Run precision calibration.
  - self_test(target="workstation"): Run comprehensive safety self-test (all subsystems must be nominal and calibrated).
  - resume(target="workstation"): Resume normal production (requires successful self_test).

Response Format:
You can plan up to 4 local steps at once. Respond with a JSON object strictly following this schema:
```json
{
  "thought": "Your step-by-step diagnostic reasoning...",
  "plan": [
    {"tool": "<tool_name_1>", "args": {<arg_key>: <arg_val>}},
    {"tool": "<tool_name_2>", "args": {<arg_key>: <arg_val>}}
  ]
}
```
"""


@dataclass
class ConstraintEvent:
    event_type: str  # PRECONDITION_BLOCKED, TOOL_EXECUTION_ERROR, POSTCONDITION_MISMATCH, STAGNATION_LOOP
    blocked_action: Dict[str, Any]
    unmet_conditions: List[str]
    condition_status: str  # FALSE, UNKNOWN
    cancellation_reason: str
    observed_evidence: Dict[str, Any] = field(default_factory=dict)
    tried_invalid_repairs: List[Dict[str, Any]] = field(default_factory=list)

    def to_prompt_str(self) -> str:
        lines = [f"[{self.event_type}]: Action {self.blocked_action.get('tool')}({self.blocked_action.get('args')}) was blocked or failed."]
        if self.unmet_conditions:
            lines.append(f"  - Unmet Preconditions: {'; '.join(self.unmet_conditions)} (Status: {self.condition_status})")
        lines.append(f"  - Reason: {self.cancellation_reason}")
        if self.observed_evidence:
            lines.append(f"  - Current Evidence: {json.dumps(self.observed_evidence)}")
        if self.tried_invalid_repairs:
            lines.append(f"  - Tried Invalid Repairs: {json.dumps(self.tried_invalid_repairs)}")
        return "\n".join(lines)


class CommonLocalPlanExecutor:
    """
    Common Local Plan Execution & Verification Engine.
    Used uniformly across B2_step, B2_plan, B1_plan, Replay, and D.
    """
    MAX_QUEUE_LEN = MAX_PLAN_LEN

    def __init__(self, fact_store: Optional[StructuredFactStore] = None):
        self.fact_store = fact_store
        self.action_queue: List[Dict[str, Any]] = []

    def clear(self):
        self.action_queue.clear()

    def is_empty(self) -> bool:
        return len(self.action_queue) == 0

    def enqueue_plan(self, actions: List[Dict[str, Any]], source_tag: str = "llm_plan"):
        for a in actions[:self.MAX_QUEUE_LEN]:
            if not isinstance(a, dict) or "tool" not in a:
                continue
            self.action_queue.append({
                "tool": a.get("tool"),
                "args": copy.deepcopy(a.get("args", {})),
                "source_tag": source_tag,
                "expected_effects": copy.deepcopy(a.get("expected_effects", {})),
                "thought": a.get("thought", ""),
            })

    def pop(self) -> Optional[Dict[str, Any]]:
        if self.action_queue:
            return self.action_queue.pop(0)
        return None

    def validate_precondition(
        self,
        action: Dict[str, Any],
        known_state: Dict[str, Any],
        tried_repairs: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, Optional[ConstraintEvent]]:
        """
        Check public known state against verified domain preconditions.
        Applies identically to all groups.
        """
        tool = action.get("tool")
        args = action.get("args", {})
        sub = args.get("subsystem")

        # Check 1: Clearing energy faults requires isolation
        if tool == "clear_fault" and sub == "pneumatic_line":
            iso = known_state.get("pneumatic_line", {}).get("isolated")
            if iso is False:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["pneumatic_line.isolated == True"],
                    condition_status="FALSE",
                    cancellation_reason="pneumatic_line is not isolated; cannot clear fault while pressurized.",
                    observed_evidence=copy.deepcopy(known_state.get("pneumatic_line", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt
            elif iso is None:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["pneumatic_line.isolated state is UNKNOWN"],
                    condition_status="UNKNOWN",
                    cancellation_reason="pneumatic_line isolation state is unknown; inspect workstation first.",
                    observed_evidence=copy.deepcopy(known_state),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt

        if tool == "clear_fault" and sub == "power_unit":
            iso = known_state.get("power_unit", {}).get("isolated")
            if iso is False:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["power_unit.isolated == True"],
                    condition_status="FALSE",
                    cancellation_reason="power_unit is not isolated; cannot service live power relay.",
                    observed_evidence=copy.deepcopy(known_state.get("power_unit", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt
            elif iso is None:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["power_unit.isolated state is UNKNOWN"],
                    condition_status="UNKNOWN",
                    cancellation_reason="power_unit isolation state is unknown; inspect workstation first.",
                    observed_evidence=copy.deepcopy(known_state),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt

        # Check 2: Resetting arm gripper requires releasing load
        if tool == "reset" and sub == "arm_gripper":
            holding = known_state.get("arm_gripper", {}).get("holding_load")
            if holding is True:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["arm_gripper.holding_load == False"],
                    condition_status="FALSE",
                    cancellation_reason="arm_gripper is holding unsecured load; clear fault / release load first.",
                    observed_evidence=copy.deepcopy(known_state.get("arm_gripper", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt

        # Check 3: Calibration and Arm Reset requires active nominal power
        if (tool == "calibrate" and sub in ["camera_sensor", "arm_gripper"]) or (tool == "reset" and sub == "arm_gripper"):
            pw_stat = known_state.get("power_unit", {}).get("status")
            pw_iso = known_state.get("power_unit", {}).get("isolated")
            if pw_stat == "tripped" or pw_iso is True:
                evt = ConstraintEvent(
                    event_type="PRECONDITION_BLOCKED",
                    blocked_action={"tool": tool, "args": args},
                    unmet_conditions=["power_unit.status == nominal", "power_unit.isolated == False"],
                    condition_status="FALSE",
                    cancellation_reason=f"power_unit is unpowered or isolated; restore power before {tool}({sub}).",
                    observed_evidence=copy.deepcopy(known_state.get("power_unit", {})),
                    tried_invalid_repairs=copy.deepcopy(tried_repairs or []),
                )
                return False, evt

        return True, None


class WorkstationAgentRunner:
    def __init__(
        self,
        group_id: str,
        llm_backend: Optional[LLMBackend] = None,
        max_llm_calls: int = 32,
        max_tool_calls: int = 40,
        time_limit_s: float = 300.0,
        allow_fallback: bool = False,
    ):
        self.group_id = group_id
        self.llm_backend = llm_backend
        self.max_llm_calls = max_llm_calls
        self.max_tool_calls = max_tool_calls
        self.time_limit_s = time_limit_s
        self.allow_fallback = allow_fallback

    def run_task(
        self,
        task_config: Dict[str, Any],
        raw_source_episodes: Optional[List[Dict[str, Any]]] = None,
        structured_facts: Optional[StructuredFactStore] = None,
        procedural_memory_store: Optional[ProceduralMemoryStore] = None,
    ) -> Dict[str, Any]:
        """
        Execute one evaluation run on task_config with strictly unified execution pipeline.
        """
        t0 = time.time()
        env = WorkstationEnv(task_config.get("initial_state"))
        
        # State tracking
        known_state: Dict[str, Any] = {}
        trajectory: List[Dict[str, Any]] = []
        audit_events: List[Dict[str, Any]] = []
        active_constraint_events: List[ConstraintEvent] = []
        tried_memories: Set[str] = set()
        tried_invalid_repairs: List[Dict[str, Any]] = []
        stagnation_history: List[Tuple[str, str]] = []

        # Telemetry counters
        llm_calls = 0
        prompt_tokens_total = 0
        gen_tokens_total = 0
        tool_errors_count = 0
        plan_deviations = 0

        # Fine-grained mechanism metrics
        memory_selected_count = 0
        memory_action_executed_count = 0
        memory_postcondition_verified_count = 0
        memory_invalidated_count = 0
        online_recovery_attempted_count = 0
        online_recovery_succeeded = False

        # Common Multi-Step Plan Executor
        executor = CommonLocalPlanExecutor(fact_store=structured_facts)
        active_memory_id: Optional[str] = None
        has_invalidation_occurred = False

        # Termination status
        success = False
        termination_reason = "RUNNING"

        while True:
            # 1. Strict Timeout Check
            elapsed_time = time.time() - t0
            if elapsed_time >= self.time_limit_s:
                termination_reason = "TIME_LIMIT_EXCEEDED"
                success = False
                break

            # 2. Task Completion Check
            if env.is_task_completed():
                success = True
                termination_reason = "TASK_COMPLETED"
                if has_invalidation_occurred:
                    online_recovery_succeeded = True
                break

            # 3. Tool Budget Check
            if len(trajectory) >= self.max_tool_calls:
                termination_reason = "TOOL_BUDGET_EXHAUSTED"
                break

            # -------------------------------------------------------------
            # Stage A: Populate Execution Queue if Empty
            # -------------------------------------------------------------
            if executor.is_empty():
                # Option 1: Group D Procedural Memory Matching
                if self.group_id == "Group_D_Procedural_Memory" and procedural_memory_store:
                    cand_mem = self._match_candidate_memory(known_state, procedural_memory_store, tried_memories)
                    if cand_mem:
                        memory_selected_count += 1
                        active_memory_id = cand_mem.memory_id
                        audit_events.append({
                            "event": "PROCEDURAL_MEMORY_SELECTED",
                            "memory_id": cand_mem.memory_id,
                            "actions_count": len(cand_mem.actions),
                        })
                        plan_actions = [
                            {
                                "tool": a.tool,
                                "args": copy.deepcopy(a.args),
                                "expected_effects": copy.deepcopy(a.expected_postconditions),
                                "thought": f"Execute procedural memory {cand_mem.memory_id}",
                            }
                            for a in cand_mem.actions
                        ]
                        executor.enqueue_plan(plan_actions, source_tag="procedural_memory")

                # Option 2: Group Replay Trajectory Matching
                elif self.group_id == "Group_Replay" and raw_source_episodes:
                    replay_plan = self._match_naive_replay_segment(known_state, raw_source_episodes, tried_memories)
                    if replay_plan:
                        memory_selected_count += 1
                        active_memory_id = replay_plan["segment_id"]
                        audit_events.append({
                            "event": "NAIVE_REPLAY_SELECTED",
                            "segment_id": replay_plan["segment_id"],
                            "actions_count": len(replay_plan["actions"]),
                        })
                        executor.enqueue_plan(replay_plan["actions"], source_tag="naive_replay")

                # Option 3: LLM Planning (For B0, B1, B2_step, B2_plan, or fallback when queue empty)
                if executor.is_empty():
                    if llm_calls >= self.max_llm_calls:
                        termination_reason = "LLM_BUDGET_EXHAUSTED"
                        break

                    llm_calls += 1
                    is_multistep = self.group_id in ["Group_B2_plan", "Group_B1_plan", "Group_D_Procedural_Memory", "Group_Replay"]
                    prompt = self._construct_prompt(
                        task_config=task_config,
                        known_state=known_state,
                        trajectory=trajectory,
                        raw_source_episodes=raw_source_episodes,
                        structured_facts=structured_facts,
                        procedural_memory_store=procedural_memory_store if self.group_id == "Group_D_Procedural_Memory" else None,
                        active_constraint_events=active_constraint_events,
                        is_multistep=is_multistep,
                    )

                    response_text, p_tok, g_tok = self._call_llm(prompt, is_multistep=is_multistep)
                    prompt_tokens_total += p_tok
                    gen_tokens_total += g_tok

                    parsed = self._parse_llm_response(response_text)
                    if not parsed:
                        parsed = {"tool": "inspect", "args": {"subsystem": "all"}, "thought": "Inspect workstation status."}

                    # Unified Enqueue of LLM plan
                    if is_multistep and "plan" in parsed and isinstance(parsed["plan"], list) and len(parsed["plan"]) > 0:
                        plan_acts = [
                            {"tool": a.get("tool"), "args": a.get("args", {}), "thought": parsed.get("thought", "")}
                            for a in parsed["plan"] if isinstance(a, dict) and "tool" in a
                        ]
                        if not plan_acts:
                            plan_acts = [{"tool": "inspect", "args": {"subsystem": "all"}, "thought": parsed.get("thought", "")}]
                        executor.enqueue_plan(plan_acts, source_tag="llm_plan")
                    else:
                        tool_name = parsed.get("tool", "inspect")
                        tool_args = parsed.get("args", {})
                        executor.enqueue_plan([{"tool": tool_name, "args": tool_args, "thought": parsed.get("thought", "")}], source_tag="llm_plan")

            # If still empty (e.g. LLM returned empty plan), terminate or break
            if executor.is_empty():
                termination_reason = "NO_ACTIONS_GENERATED"
                break

            # -------------------------------------------------------------
            # Stage B: Unified Action Pop & Precondition Validation
            # -------------------------------------------------------------
            cand_action = executor.pop()
            if not cand_action:
                continue

            tool_name = cand_action.get("tool", "inspect")
            tool_args = cand_action.get("args", {})
            action_source = cand_action.get("source_tag", "llm_plan")
            thought = cand_action.get("thought", "")
            expected_effects = cand_action.get("expected_effects", {})

            # Stagnation check
            act_sig = (tool_name, json.dumps(tool_args, sort_keys=True))
            if len(stagnation_history) >= 2 and stagnation_history[-1] == act_sig and stagnation_history[-2] == act_sig:
                stag_evt = ConstraintEvent(
                    event_type="STAGNATION_LOOP",
                    blocked_action={"tool": tool_name, "args": tool_args},
                    unmet_conditions=["Repeated identical action yielded no progress."],
                    condition_status="FALSE",
                    cancellation_reason=f"Action {tool_name}({tool_args}) repeated without state progress. Please diagnose or choose different action.",
                    observed_evidence=copy.deepcopy(known_state),
                )
                active_constraint_events.append(stag_evt)
                audit_events.append(asdict(stag_evt))
                executor.clear()
                continue

            # Common Precondition Validation (Applied identically to all groups & all actions)
            valid, constraint_event = executor.validate_precondition(cand_action, known_state, tried_invalid_repairs)
            if not valid and constraint_event:
                audit_events.append(asdict(constraint_event))
                active_constraint_events.append(constraint_event)
                tried_invalid_repairs.append({"tool": tool_name, "args": tool_args, "reason": constraint_event.cancellation_reason})
                stagnation_history.append(act_sig)

                if action_source in ["procedural_memory", "naive_replay"]:
                    memory_invalidated_count += 1
                    has_invalidation_occurred = True
                    online_recovery_attempted_count += 1
                    if active_memory_id:
                        tried_memories.add(active_memory_id)
                        active_memory_id = None
                
                # Precondition violated: clear remaining plan queue to force re-planning
                executor.clear()
                continue

            # -------------------------------------------------------------
            # Stage C: Execute Action (env.step)
            # -------------------------------------------------------------
            if action_source in ["procedural_memory", "naive_replay"]:
                memory_action_executed_count += 1

            tool_res = env.step(tool_name, **tool_args)
            is_err = (tool_res.get("status") != StatusCode.SUCCESS)

            if is_err:
                tool_errors_count += 1
                stagnation_history.append(act_sig)
                err_evt = ConstraintEvent(
                    event_type="TOOL_EXECUTION_ERROR",
                    blocked_action={"tool": tool_name, "args": tool_args},
                    unmet_conditions=[tool_res.get("error", "Tool execution error")],
                    condition_status="FALSE",
                    cancellation_reason=tool_res.get("error", "Tool failed"),
                    observed_evidence=copy.deepcopy(known_state),
                    tried_invalid_repairs=copy.deepcopy(tried_invalid_repairs),
                )
                active_constraint_events.append(err_evt)
                audit_events.append(asdict(err_evt))

                if action_source in ["procedural_memory", "naive_replay"]:
                    memory_invalidated_count += 1
                    has_invalidation_occurred = True
                    online_recovery_attempted_count += 1
                    if active_memory_id:
                        tried_memories.add(active_memory_id)
                        active_memory_id = None
                executor.clear()

            else:
                # Clear active constraint events on successful progress
                active_constraint_events.clear()
                stagnation_history.clear()

                # Update public known state
                self._update_known_state(known_state, tool_name, tool_args, tool_res)

                # -------------------------------------------------------------
                # Stage D: Real Postcondition Verification
                # -------------------------------------------------------------
                if expected_effects and isinstance(expected_effects, dict):
                    postcond_ok = True
                    mismatches = []
                    for k, expected_v in expected_effects.items():
                        actual_v = tool_res.get("effects", {}).get(k)
                        if actual_v is None:
                            sub_state = known_state.get(tool_args.get("subsystem", ""), {})
                            actual_v = sub_state.get(k)

                        if actual_v is None or actual_v != expected_v:
                            postcond_ok = False
                            mismatches.append(f"{k} expected {expected_v}, observed {actual_v}")

                    if postcond_ok:
                        if action_source in ["procedural_memory", "naive_replay"]:
                            memory_postcondition_verified_count += 1
                    else:
                        post_evt = ConstraintEvent(
                            event_type="POSTCONDITION_MISMATCH",
                            blocked_action={"tool": tool_name, "args": tool_args},
                            unmet_conditions=mismatches,
                            condition_status="FALSE",
                            cancellation_reason="Postcondition verification failed after action execution.",
                            observed_evidence=copy.deepcopy(known_state),
                        )
                        active_constraint_events.append(post_evt)
                        audit_events.append(asdict(post_evt))
                        if action_source in ["procedural_memory", "naive_replay"]:
                            memory_invalidated_count += 1
                            has_invalidation_occurred = True
                            if active_memory_id:
                                tried_memories.add(active_memory_id)
                                active_memory_id = None
                        executor.clear()

                if not executor.action_queue and active_memory_id:
                    tried_memories.add(active_memory_id)
                    active_memory_id = None

            # Record step in trajectory
            step_record = {
                "step_index": len(trajectory) + 1,
                "action_source": action_source,
                "tool": tool_name,
                "args": copy.deepcopy(tool_args),
                "thought": thought,
                "result": copy.deepcopy(tool_res),
                "is_error": is_err,
            }
            trajectory.append(step_record)

        wall_time_s = round(time.time() - t0, 2)

        return {
            "group_id": self.group_id,
            "task_id": task_config.get("task_id"),
            "transfer_class": task_config.get("transfer_class", "source"),
            "success": success,
            "termination_reason": termination_reason,
            "step_count": len(trajectory),
            "llm_calls": llm_calls,
            "total_prompt_tokens": prompt_tokens_total,
            "total_generated_tokens": gen_tokens_total,
            "wall_time_s": wall_time_s,
            "tool_errors_count": tool_errors_count,
            "plan_deviations_count": plan_deviations,
            "memory_selected_count": memory_selected_count,
            "memory_action_executed_count": memory_action_executed_count,
            "memory_postcondition_verified_count": memory_postcondition_verified_count,
            "memory_invalidated_count": memory_invalidated_count,
            "online_recovery_attempted_count": online_recovery_attempted_count,
            "online_recovery_succeeded": online_recovery_succeeded,
            "trajectory": trajectory,
            "audit_events": audit_events,
            "final_env_summary": env.get_summary(),
        }

    def _match_candidate_memory(
        self,
        known_state: Dict[str, Any],
        memory_store: ProceduralMemoryStore,
        tried_memories: Set[str],
    ) -> Optional[ProceduralMemoryItem]:
        """Find matching validated procedural memory based on observed faults."""
        for sub, data in known_state.items():
            if not isinstance(data, dict):
                continue
            status = data.get("status")
            if status and status != "nominal":
                candidates = memory_store.retrieve(sub, status)
                for cand in candidates:
                    if cand.memory_id in tried_memories:
                        continue
                    if cand.status == "VERIFIED":
                        return cand
        return None

    def _match_naive_replay_segment(
        self,
        known_state: Dict[str, Any],
        raw_source_episodes: List[Dict[str, Any]],
        tried_memories: Set[str],
    ) -> Optional[Dict[str, Any]]:
        """Naive replay matching: selects successful source action sequence matching observed fault."""
        for sub, data in known_state.items():
            if not isinstance(data, dict):
                continue
            st = data.get("status")
            if st and st != "nominal":
                seg_id = f"replay_{sub}_{st}"
                if seg_id in tried_memories:
                    continue
                # Search source episodes for matching subsystem actions
                for ep in raw_source_episodes:
                    if not ep.get("success"):
                        continue
                    matching_actions = []
                    for step in ep.get("trajectory", []):
                        if step.get("args", {}).get("subsystem") == sub and not step.get("is_error"):
                            matching_actions.append({
                                "tool": step.get("tool"),
                                "args": copy.deepcopy(step.get("args")),
                                "expected_effects": copy.deepcopy(step.get("result", {}).get("effects", {})),
                            })
                    if matching_actions:
                        return {"segment_id": seg_id, "actions": matching_actions[:MAX_PLAN_LEN]}
        return None

    def _update_known_state(
        self,
        known_state: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_res: Dict[str, Any],
    ):
        """Update internal state representation based strictly on public tool observations and effects."""
        if tool_name == "inspect":
            if "data" in tool_res:
                data = tool_res["data"]
                if tool_args.get("subsystem") == "all" and isinstance(data, dict):
                    for sub, props in data.items():
                        known_state[sub] = copy.deepcopy(props)
                else:
                    sub = tool_args.get("subsystem")
                    if sub and isinstance(data, dict):
                        known_state[sub] = copy.deepcopy(data)

        elif tool_res.get("status") == StatusCode.SUCCESS:
            sub = tool_args.get("subsystem")
            effects = tool_res.get("effects", {})

            if tool_name == "isolate" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub]["isolated"] = (tool_args.get("action") == "engage")
                if "pressure_bar" in effects:
                    known_state[sub]["pressure_bar"] = effects["pressure_bar"]
                if "voltage_v" in effects:
                    known_state[sub]["voltage_v"] = effects["voltage_v"]

            elif tool_name == "clear_fault" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub]["status"] = "nominal"
                if "holding_load" in effects:
                    known_state[sub]["holding_load"] = effects["holding_load"]
                if sub in ["arm_gripper", "pneumatic_line"] and "camera_sensor" in known_state:
                    known_state["camera_sensor"]["calibrated"] = False
                if "controller" in known_state:
                    known_state["controller"]["self_test_passed"] = False

            elif tool_name == "reset" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                if "pressure_bar" in effects:
                    known_state[sub]["pressure_bar"] = effects["pressure_bar"]
                if "voltage_v" in effects:
                    known_state[sub]["voltage_v"] = effects["voltage_v"]
                if sub == "arm_gripper" and "camera_sensor" in known_state:
                    known_state["camera_sensor"]["calibrated"] = False
                if "controller" in known_state:
                    known_state["controller"]["self_test_passed"] = False

            elif tool_name == "calibrate" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub]["calibrated"] = True
                if "drift_offset_mm" in effects:
                    known_state[sub]["drift_offset_mm"] = effects["drift_offset_mm"]

            elif tool_name == "self_test":
                if "controller" not in known_state:
                    known_state["controller"] = {}
                known_state["controller"]["self_test_passed"] = (tool_res.get("passed") is True)

            elif tool_name == "resume":
                if "controller" not in known_state:
                    known_state["controller"] = {}
                known_state["controller"]["resumed"] = (tool_res.get("resumed") is True)

    def _construct_prompt(
        self,
        task_config: Dict[str, Any],
        known_state: Dict[str, Any],
        trajectory: List[Dict[str, Any]],
        raw_source_episodes: Optional[List[Dict[str, Any]]] = None,
        structured_facts: Optional[StructuredFactStore] = None,
        procedural_memory_store: Optional[ProceduralMemoryStore] = None,
        active_constraint_events: Optional[List[ConstraintEvent]] = None,
        is_multistep: bool = False,
    ) -> str:
        """Construct prompt according to group specifications with constraint event feedback."""
        sys_prompt = WORKSTATION_SYSTEM_PROMPT_PLAN if is_multistep else WORKSTATION_SYSTEM_PROMPT_STEP
        parts = [sys_prompt, "\n=== Current Task Objective ==="]
        parts.append(f"Task ID: {task_config.get('task_id')}")
        parts.append(f"Goal: {task_config.get('goal')}")

        # Group B1: Append full raw source episodes with complete feedback (effects, errors, data)
        if self.group_id in ["Group_B1_plan", "Group_Replay"] and raw_source_episodes:
            parts.append("\n=== Prior Cross-Task Experience (Complete Raw Trajectories) ===")
            for idx, ep in enumerate(raw_source_episodes):
                succ_tag = "SUCCESS" if ep.get("success") else "FAILED"
                parts.append(f"\n--- Episode {idx+1} ({ep.get('task_id')}, Status={succ_tag}) ---")
                for s in ep.get("trajectory", []):
                    r_obj = s.get("result", {})
                    msg = r_obj.get("message") or r_obj.get("error") or r_obj.get("status")
                    eff = r_obj.get("effects", {})
                    data_str = f", Data: {r_obj['data']}" if "data" in r_obj else ""
                    eff_str = f", Effects: {eff}" if eff else ""
                    parts.append(f"  Step {s.get('step_index')}: {s.get('tool')}({s.get('args')}) -> {r_obj.get('status')} ({msg}{eff_str}{data_str})")

        # Group B2 / Group D: Append rich structured facts with intervention evidence (no arbitrary truncation)
        if self.group_id in ["Group_B2_step", "Group_B2_plan", "Group_D_Procedural_Memory"] and structured_facts:
            facts_dict = structured_facts.to_dict()
            parts.append("\n=== Verified Structured Domain Facts (With Intervention Evidence) ===")
            if facts_dict.get("verified_transitions"):
                parts.append("Verified State Transitions:")
                for tr in facts_dict["verified_transitions"]:
                    parts.append(f"  - Action {tr.get('action')}: yielded effects {tr.get('observed_effects')}")
            if facts_dict.get("action_preconditions"):
                parts.append("Verified Action Preconditions:")
                for act, req_list in facts_dict["action_preconditions"].items():
                    req_strs = [f"{r.get('condition')} [Status: {r.get('status')}]" for r in req_list]
                    parts.append(f"  - {act}: requires {', '.join(req_strs)}")
            if facts_dict.get("invalidation_rules"):
                parts.append("Verified Invalidation Rules:")
                for inv in facts_dict["invalidation_rules"]:
                    parts.append(f"  - {inv.get('action')}: causes {inv.get('invalidated_state')} ({inv.get('reason')}) [Status: {inv.get('status')}]")
            if facts_dict.get("causal_order_constraints"):
                parts.append("Verified Causal Order Dependencies:")
                for dep in facts_dict["causal_order_constraints"]:
                    dep_before = dep.get('before')
                    dep_after = dep.get('after')
                    dep_sub = dep.get('subsystem')
                    dep_status = dep.get('status')
                    parts.append(f"  - In subsystem '{dep_sub}': {dep_before} must precede {dep_after} [Status: {dep_status}]")
            if facts_dict.get("commutative_subsystems"):
                parts.append("Commutative Independent Subsystems:")
                for c in facts_dict["commutative_subsystems"]:
                    parts.append(f"  - Subsystems {c.get('subsystems')} can be serviced in any order [Status: {c.get('status')}]")

        # Active Constraint & Interlock Feedback (Section 3)
        if active_constraint_events:
            parts.append("\n=== Active Constraint & Interlock Feedback ===")
            for evt in active_constraint_events:
                parts.append(evt.to_prompt_str())

        # Public Known State
        parts.append("\n=== Current Known Workstation State (Public Observations) ===")
        if known_state:
            parts.append(json.dumps(known_state, indent=2))
        else:
            parts.append("Workstation state unknown. Diagnostic inspect required.")

        # Trajectory History
        parts.append("\n=== Current Episode Execution History ===")
        if not trajectory:
            parts.append("No actions executed yet.")
        else:
            for s in trajectory:
                r_obj = s.get("result", {})
                msg = r_obj.get("message") or r_obj.get("error") or r_obj.get("status")
                parts.append(f"Step {s.get('step_index')}: [{s.get('action_source')}] {s.get('tool')}({s.get('args')}) -> {r_obj.get('status')} ({msg})")

        parts.append("\nWhat action should be taken next? Respond strictly in JSON.")
        return "\n".join(parts)

    def _call_llm(self, prompt: str, is_multistep: bool = False) -> Tuple[str, int, int]:
        """Call LLM backend or fallback mock in testing."""
        p_tok = len(prompt.split())
        if self.llm_backend is not None:
            messages = [{"role": "user", "content": prompt}]
            try:
                res = self.llm_backend.generate(messages)
            except Exception:
                res = self.llm_backend.generate(prompt)

            if isinstance(res, dict):
                content = res.get("content", "")
                p_tokens = res.get("prompt_tokens", p_tok)
                g_tokens = res.get("generated_tokens", len(content.split()))
                return content, p_tokens, g_tokens
            elif isinstance(res, str):
                g_tok = len(res.split())
                return res, p_tok, g_tok

        if not self.allow_fallback:
            raise RuntimeError("LLMBackend is None and allow_fallback=False!")

        # Mock fallback for test environment
        if "inspect" not in prompt:
            action = {"thought": "Inspect all workstation subsystems to diagnose status.", "tool": "inspect", "args": {"subsystem": "all"}}
        elif '"status": "overpressure_fault"' in prompt or '"status": "leak_fault"' in prompt:
            action = {"thought": "Repair pneumatic line.", "plan": [
                {"tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}},
                {"tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}},
                {"tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "release"}},
                {"tool": "reset", "args": {"subsystem": "pneumatic_line"}},
            ]} if is_multistep else {"thought": "Isolate pneumatic line.", "tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}}
        elif '"status": "jammed"' in prompt or '"status": "misaligned"' in prompt:
            action = {"thought": "Repair gripper and calibrate camera.", "plan": [
                {"tool": "clear_fault", "args": {"subsystem": "arm_gripper"}},
                {"tool": "reset", "args": {"subsystem": "arm_gripper"}},
                {"tool": "calibrate", "args": {"subsystem": "camera_sensor"}},
            ]} if is_multistep else {"thought": "Clear gripper fault.", "tool": "clear_fault", "args": {"subsystem": "arm_gripper"}}
        elif '"self_test_passed": true' in prompt or 'All 5 subsystems passed self-test' in prompt:
            action = {"thought": "Resume production.", "tool": "resume", "args": {"target": "workstation"}}
        else:
            action = {"thought": "Run system self-test.", "tool": "self_test", "args": {"target": "workstation"}}

        if is_multistep and "tool" in action and "plan" not in action:
            resp_obj = {"thought": action.get("thought", ""), "plan": [{"tool": action["tool"], "args": action.get("args", {})}]}
        else:
            resp_obj = action

        resp = json.dumps(resp_obj)
        g_tok = len(resp.split())
        return resp, p_tok, g_tok

    def _parse_llm_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response text into JSON action / plan dictionary."""
        try:
            return json.loads(text)
        except Exception:
            pass

        # Try markdown codeblock extraction
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        # Try regex search for first valid JSON object
        m_obj = re.search(r"\{[\s\S]*\}", text)
        if m_obj:
            try:
                return json.loads(m_obj.group(0))
            except Exception:
                pass

        return None
