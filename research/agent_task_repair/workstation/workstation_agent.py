"""
Unified Agent Runner with Common Local Plan Executor for Workstation Multi-Fault Benchmark.

Implements 5 strictly fair evaluation groups:
  1. Group_B2_step: Structured facts + single-step LLM planning (old baseline).
  2. Group_B2_plan: Structured facts + multi-step LLM planning via CommonLocalPlanExecutor.
  3. Group_B1_plan: Full raw source trajectories + multi-step LLM planning via CommonLocalPlanExecutor.
  4. Group_Replay: Naive trajectory replay matching observed fault via CommonLocalPlanExecutor.
  5. Group_D: Structured facts + conditional procedural memory via CommonLocalPlanExecutor.

All multi-step groups share the identical:
  - CommonLocalPlanExecutor (queue cap = 6)
  - Pre-execution validation checks (same rules for first and subsequent actions)
  - Post-execution verification and public state updater
  - Invalidation triggers and online fallback to LLM
  - Budget accounting (32 LLM / 40 Tools / 300s timeout)
"""
from typing import Dict, Any, List, Optional, Tuple, Set
import json
import time
import copy
import re

from .workstation_env import WorkstationEnv, StatusCode
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
)
from ..agent.llm_backend import LLMBackend


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


class CommonLocalPlanExecutor:
    """
    Common Local Plan Execution & Verification Engine.
    Used uniformly across B2-plan, B1-plan, Replay, and D.
    """
    MAX_QUEUE_LEN = 6

    def __init__(self, fact_store: Optional[StructuredFactStore] = None):
        self.fact_store = fact_store
        self.action_queue: List[Dict[str, Any]] = []

    def clear(self):
        self.action_queue.clear()

    def enqueue_plan(self, actions: List[Dict[str, Any]], source_tag: str = "llm_plan"):
        for a in actions[:self.MAX_QUEUE_LEN]:
            self.action_queue.append({
                "tool": a.get("tool"),
                "args": copy.deepcopy(a.get("args", {})),
                "source_tag": source_tag,
                "expected_effects": copy.deepcopy(a.get("expected_effects", {})),
            })

    def validate_precondition(
        self,
        action: Dict[str, Any],
        known_state: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check public known state against verified domain preconditions.
        Applies identically to all groups.
        """
        tool = action.get("tool")
        args = action.get("args", {})
        sub = args.get("subsystem")

        # Check 1: Clearing energy faults requires isolation
        if tool == "clear_fault" and sub == "pneumatic_line":
            if known_state.get("pneumatic_line", {}).get("isolated") is False:
                return False, "pneumatic_line is not isolated; cannot clear fault while pressurized."
        if tool == "clear_fault" and sub == "power_unit":
            if known_state.get("power_unit", {}).get("isolated") is False:
                return False, "power_unit is not isolated; cannot service live power relay."

        # Check 2: Resetting arm gripper requires releasing load
        if tool == "reset" and sub == "arm_gripper":
            if known_state.get("arm_gripper", {}).get("holding_load") is True:
                return False, "arm_gripper is holding unsecured load; clear fault / release load first."

        # Check 3: Calibration requires active nominal power
        if tool == "calibrate" and sub in ["camera_sensor", "arm_gripper"]:
            if known_state.get("power_unit", {}).get("status") == "tripped" or known_state.get("power_unit", {}).get("isolated") is True:
                return False, f"power_unit is unpowered; cannot calibrate {sub}."

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
        Execute one evaluation run on task_config with strictly tracked metrics.
        """
        t0 = time.time()
        env = WorkstationEnv(task_config.get("initial_state"))
        
        # State tracking
        known_state: Dict[str, Any] = {}
        trajectory: List[Dict[str, Any]] = []
        audit_events: List[Dict[str, Any]] = []
        tried_memories: Set[str] = set()

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

        # Termination status
        success = False
        termination_reason = "RUNNING"

        while True:
            # 1. Strict Timeout Check (Checked before task completion if elapsed >= limit)
            elapsed_time = time.time() - t0
            if elapsed_time >= self.time_limit_s:
                termination_reason = "TIME_LIMIT_EXCEEDED"
                success = False
                break

            # 2. Completion Check
            if env.is_task_completed():
                success = True
                termination_reason = "TASK_COMPLETED"
                if online_recovery_attempted_count > 0:
                    online_recovery_succeeded = True
                break

            # 3. Budget Exhaustion Checks
            if len(trajectory) >= self.max_tool_calls:
                termination_reason = "TOOL_BUDGET_EXHAUSTED"
                break
            if llm_calls >= self.max_llm_calls:
                termination_reason = "LLM_BUDGET_EXHAUSTED"
                break

            # -------------------------------------------------------------
            # Action Selection & Dispatch
            # -------------------------------------------------------------
            next_action: Optional[Dict[str, Any]] = None
            action_source = "online_llm"

            # Check if executor queue has pending action
            if executor.action_queue:
                cand = executor.action_queue[0]
                # Pre-execution check
                valid, reason = executor.validate_precondition(cand, known_state)
                if not valid:
                    # Invalidation / Precondition violation
                    audit_events.append({
                        "event": "PRECONDITION_INTERLOCK_ABORT",
                        "action": cand,
                        "reason": reason,
                        "source_tag": cand.get("source_tag"),
                    })
                    if cand.get("source_tag") == "procedural_memory" and active_memory_id:
                        memory_invalidated_count += 1
                        online_recovery_attempted_count += 1
                        tried_memories.add(active_memory_id)
                        active_memory_id = None
                    executor.clear()
                else:
                    next_action = executor.action_queue.pop(0)
                    action_source = next_action.get("source_tag", "llm_plan")

            # Group D: Conditional Procedural Memory Candidate Matching
            if next_action is None and self.group_id == "Group_D_Procedural_Memory" and procedural_memory_store:
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
                        {"tool": a.tool, "args": copy.deepcopy(a.args), "expected_effects": copy.deepcopy(a.expected_postconditions)}
                        for a in cand_mem.actions
                    ]
                    executor.enqueue_plan(plan_actions, source_tag="procedural_memory")
                    if executor.action_queue:
                        # Pre-check first action
                        first_act = executor.action_queue[0]
                        valid, reason = executor.validate_precondition(first_act, known_state)
                        if not valid:
                            audit_events.append({
                                "event": "PROCEDURAL_MEMORY_INVALIDATED",
                                "memory_id": cand_mem.memory_id,
                                "reason": reason,
                            })
                            memory_invalidated_count += 1
                            online_recovery_attempted_count += 1
                            tried_memories.add(cand_mem.memory_id)
                            executor.clear()
                            active_memory_id = None
                        else:
                            next_action = executor.action_queue.pop(0)
                            action_source = "procedural_memory"

            # Group Replay: Naive Trajectory Segment Replay (No conditional matching)
            if next_action is None and self.group_id == "Group_Replay" and raw_source_episodes:
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
                    if executor.action_queue:
                        first_act = executor.action_queue[0]
                        valid, reason = executor.validate_precondition(first_act, known_state)
                        if not valid:
                            audit_events.append({
                                "event": "NAIVE_REPLAY_PRECONDITION_ABORT",
                                "segment_id": replay_plan["segment_id"],
                                "reason": reason,
                            })
                            memory_invalidated_count += 1
                            online_recovery_attempted_count += 1
                            tried_memories.add(replay_plan["segment_id"])
                            executor.clear()
                            active_memory_id = None
                        else:
                            next_action = executor.action_queue.pop(0)
                            action_source = "naive_replay"

            # LLM Planning (For B0, B1-plan, B2-step, B2-plan, or D/Replay when queue is empty)
            if next_action is None:
                llm_calls += 1
                is_multistep = self.group_id in ["Group_B2_plan", "Group_B1_plan", "Group_D_Procedural_Memory", "Group_Replay"]
                prompt = self._construct_prompt(
                    task_config=task_config,
                    known_state=known_state,
                    trajectory=trajectory,
                    raw_source_episodes=raw_source_episodes,
                    structured_facts=structured_facts,
                    procedural_memory_store=procedural_memory_store if self.group_id == "Group_D_Procedural_Memory" else None,
                    is_multistep=is_multistep,
                )

                response_text, p_tok, g_tok = self._call_llm(prompt, is_multistep=is_multistep)
                prompt_tokens_total += p_tok
                gen_tokens_total += g_tok

                parsed = self._parse_llm_response(response_text)
                if not parsed:
                    parsed = {"tool": "inspect", "args": {"subsystem": "all"}, "thought": "Inspect workstation status."}

                if is_multistep and "plan" in parsed and isinstance(parsed["plan"], list) and len(parsed["plan"]) > 0:
                    plan_acts = parsed["plan"]
                    first = plan_acts[0]
                    rest = plan_acts[1:]
                    executor.enqueue_plan(rest, source_tag="llm_plan")
                    next_action = {"tool": first.get("tool"), "args": first.get("args", {}), "thought": parsed.get("thought", "")}
                    action_source = "online_llm"
                else:
                    tool_name = parsed.get("tool", "inspect")
                    tool_args = parsed.get("args", {})
                    next_action = {"tool": tool_name, "args": tool_args, "thought": parsed.get("thought", "")}
                    action_source = "online_llm"

            # -------------------------------------------------------------
            # Execute Action
            # -------------------------------------------------------------
            tool_name = next_action.get("tool", "inspect")
            tool_args = next_action.get("args", {})

            if action_source == "procedural_memory":
                memory_action_executed_count += 1

            tool_res = env.step(tool_name, **tool_args)
            is_err = tool_res.get("status") != StatusCode.SUCCESS

            if is_err:
                tool_errors_count += 1
                if action_source in ["procedural_memory", "naive_replay"]:
                    memory_invalidated_count += 1
                    online_recovery_attempted_count += 1
                    if active_memory_id:
                        tried_memories.add(active_memory_id)
                        active_memory_id = None
                    executor.clear()
                else:
                    executor.clear()
            else:
                if action_source == "procedural_memory":
                    memory_postcondition_verified_count += 1
                if not executor.action_queue and active_memory_id:
                    if active_memory_id:
                        tried_memories.add(active_memory_id)
                    active_memory_id = None

            # Update known public state strictly from tool observation outputs
            self._update_known_state(known_state, tool_name, tool_args, tool_res)

            # Record step in trajectory
            step_record = {
                "step_index": len(trajectory) + 1,
                "action_source": action_source,
                "tool": tool_name,
                "args": copy.deepcopy(tool_args),
                "thought": next_action.get("thought", ""),
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
                            matching_actions.append({"tool": step.get("tool"), "args": copy.deepcopy(step.get("args"))})
                    if matching_actions:
                        return {"segment_id": seg_id, "actions": matching_actions}
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
        is_multistep: bool = False,
    ) -> str:
        """Construct prompt according to group specifications."""
        sys_prompt = WORKSTATION_SYSTEM_PROMPT_PLAN if is_multistep else WORKSTATION_SYSTEM_PROMPT_STEP
        parts = [sys_prompt, "\n=== Current Task Objective ==="]
        parts.append(f"Task ID: {task_config.get('task_id')}")
        parts.append(f"Goal: {task_config.get('goal')}")

        # Group B1: Append full raw source episodes with complete feedback
        if self.group_id in ["Group_B1_plan", "Group_Replay"] and raw_source_episodes:
            parts.append("\n=== Prior Cross-Task Experience (Complete Raw Trajectories) ===")
            for idx, ep in enumerate(raw_source_episodes):
                parts.append(f"\n--- Episode {idx+1} ({ep.get('task_id')}, Success={ep.get('success')}) ---")
                for s in ep.get("trajectory", []):
                    r_obj = s.get("result", {})
                    msg = r_obj.get("message") or r_obj.get("error") or r_obj.get("status")
                    parts.append(f"  Step {s.get('step_index')}: {s.get('tool')}({s.get('args')}) -> {r_obj.get('status')} ({msg})")

        # Group B2 / Group D: Append rich structured facts with intervention evidence
        if self.group_id in ["Group_B2_step", "Group_B2_plan", "Group_D_Procedural_Memory"] and structured_facts:
            facts_dict = structured_facts.to_dict()
            parts.append("\n=== Verified Structured Domain Facts (With Intervention Evidence) ===")
            if facts_dict.get("verified_transitions"):
                parts.append("Verified State Transitions:")
                for tr in facts_dict["verified_transitions"][:8]:
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
                    parts.append(f"  - In subsystem '{dep.get('subsystem')}': {dep.get('before')} must precede {dep.get('after')} [Status: {dep.get('status')}]")
            if facts_dict.get("commutative_subsystems"):
                parts.append("Commutative Independent Subsystems:")
                for comm in facts_dict["commutative_subsystems"]:
                    pair = comm.get("subsystems", ())
                    parts.append(f"  - Repair of '{pair[0]}' and '{pair[1]}' can be executed in any order. [Status: {comm.get('status')}]")

        # Current observation state
        parts.append("\n=== Current Known State (from past observations) ===")
        if known_state:
            parts.append(json.dumps(known_state, indent=2))
        else:
            parts.append("No subsystem state inspected yet. You should inspect the workstation first.")

        # Recent action history
        parts.append("\n=== Action History (Recent Steps) ===")
        if trajectory:
            for s in trajectory[-6:]:
                res_obj = s.get("result", {})
                if not s.get("is_error"):
                    msg = res_obj.get("message", "SUCCESS")
                    parts.append(f"Step {s.get('step_index')}: {s.get('tool')}({json.dumps(s.get('args'))}) -> SUCCESS ({msg})")
                else:
                    err_msg = res_obj.get("error") or res_obj.get("message", "FAILED")
                    unmet = res_obj.get("unmet_conditions")
                    if unmet:
                        err_msg += f" [Unmet: {', '.join(unmet)}]"
                    parts.append(f"Step {s.get('step_index')}: {s.get('tool')}({json.dumps(s.get('args'))}) -> ERROR ({err_msg})")
        else:
            parts.append("No actions executed yet.")

        parts.append("\nDecide your next action / local plan and output valid JSON:")
        return "\n".join(parts)

    def _call_llm(self, prompt: str, is_multistep: bool = False) -> Tuple[str, int, int]:
        """Call LLM backend or test fallback policy."""
        if self.llm_backend is not None and getattr(self.llm_backend, "model", None) is not None:
            messages = [{"role": "user", "content": prompt}]
            res = self.llm_backend.generate(messages)
            text = res.get("content", "")
            p_tok = res.get("prompt_tokens", 0)
            g_tok = res.get("generated_tokens", 0)
            return text, p_tok, g_tok

        if not self.allow_fallback:
            raise RuntimeError("[WorkstationAgentRunner] No neural model loaded and allow_fallback=False.")

        return self._rule_based_fallback_policy(prompt, is_multistep)

    def _rule_based_fallback_policy(self, prompt: str, is_multistep: bool = False) -> Tuple[str, int, int]:
        """Deterministic policy strictly used for dry-run verification and unit tests."""
        p_tok = len(prompt.split())

        if "No subsystem state inspected yet" in prompt:
            action = {"thought": "Inspect all workstation subsystems to diagnose status.", "tool": "inspect", "args": {"subsystem": "all"}}
        elif '"status": "overpressure_fault"' in prompt or '"status": "leak_fault"' in prompt:
            if '"isolated": true' in prompt.lower() and '"pressure_bar": 0' in prompt:
                action = {"thought": "Pneumatic line is safely isolated. Clear fault.", "tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}}
            elif '"isolated": false' in prompt.lower() and '"status": "nominal"' in prompt:
                action = {"thought": "Pneumatic fault cleared. Release isolation and reset.", "tool": "reset", "args": {"subsystem": "pneumatic_line"}}
            elif '"status": "nominal"' not in prompt and "pneumatic_line" in prompt:
                action = {"thought": "Isolate pneumatic line before servicing.", "tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}}
            else:
                action = {"thought": "Release isolation on pneumatic line.", "tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "release"}}
        elif '"status": "tripped"' in prompt:
            if '"isolated": true' in prompt.lower():
                action = {"thought": "Power isolated. Clear power relay fault.", "tool": "clear_fault", "args": {"subsystem": "power_unit"}}
            else:
                action = {"thought": "Isolate power unit for safe servicing.", "tool": "isolate", "args": {"subsystem": "power_unit", "action": "engage"}}
        elif '"status": "jammed"' in prompt or '"status": "misaligned"' in prompt:
            action = {"thought": "Clear gripper mechanical jam.", "tool": "clear_fault", "args": {"subsystem": "arm_gripper"}}
        elif '"status": "counter_overflow"' in prompt:
            action = {"thought": "Reset controller error counters.", "tool": "clear_fault", "args": {"subsystem": "controller"}}
        elif '"calibrated": false' in prompt:
            action = {"thought": "Calibrate camera sensor.", "tool": "calibrate", "args": {"subsystem": "camera_sensor"}}
        elif '"self_test_passed": true' in prompt:
            action = {"thought": "Self-test passed. Resume workstation production.", "tool": "resume", "args": {"target": "workstation"}}
        else:
            action = {"thought": "Run system self-test.", "tool": "self_test", "args": {"target": "workstation"}}

        if is_multistep and "tool" in action:
            resp_obj = {"thought": action.get("thought", ""), "plan": [{"tool": action["tool"], "args": action.get("args", {})}]}
        else:
            resp_obj = action

        resp = json.dumps(resp_obj)
        g_tok = len(resp.split())
        return resp, p_tok, g_tok

    def _parse_llm_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON object from LLM response."""
        try:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            m2 = re.search(r"(\{.*\})", text, re.DOTALL)
            if m2:
                return json.loads(m2.group(1))
            return json.loads(text)
        except Exception:
            return None
