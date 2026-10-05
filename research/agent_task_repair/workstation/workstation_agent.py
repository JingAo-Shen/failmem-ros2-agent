"""
Unified Agent Runner for Workstation Multi-Fault Diagnosis and Recovery.

Implements 4 strictly fair evaluation groups:
  - Group_B0: Online Agent without cross-task history.
  - Group_B1: Agent with retrieved raw source trajectories in context.
  - Group_B2: Agent with rich structured facts (transitions, pre/post conditions, invalidation rules).
  - Group_D: Agent with identical B2 facts + compiled conditional procedural repair memories.
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


WORKSTATION_SYSTEM_PROMPT = """You are an autonomous robotic workstation diagnostic and recovery agent.
The simulated workstation consists of 5 subsystems:
  1. power_unit (Primary power & safety relay)
  2. pneumatic_line (Compressed air supply)
  3. arm_gripper (Robotic end-effector)
  4. camera_sensor (Vision inspection sensor)
  5. controller (Safety & sequence controller)

Available Tools:
  - inspect(subsystem="all"|"power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Query diagnostic state.
  - isolate(subsystem="power_unit"|"pneumatic_line", action="engage"|"release"): Safety lockout (engage) or restore energy line (release).
  - clear_fault(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Clear fault on subsystem.
  - reset(subsystem="power_unit"|"pneumatic_line"|"arm_gripper"|"camera_sensor"|"controller"): Reset subsystem to operating/home state.
  - calibrate(subsystem="camera_sensor"|"arm_gripper"): Run precision calibration.
  - self_test(target="workstation"): Run comprehensive safety self-test (all subsystems must be nominal and calibrated).
  - resume(target="workstation"): Resume normal production (requires successful self_test).

Response Format:
You MUST respond with a JSON object strictly following this schema:
```json
{
  "thought": "Your step-by-step diagnostic reasoning...",
  "tool": "<tool_name>",
  "args": {<argument_key>: <argument_value>}
}
```
"""


class WorkstationAgentRunner:
    def __init__(
        self,
        group_id: str,
        llm_backend: Optional[LLMBackend] = None,
        max_llm_calls: int = 32,
        max_tool_calls: int = 40,
        time_limit_s: float = 300.0,
        enable_observation_guard: bool = True,
    ):
        self.group_id = group_id
        self.llm_backend = llm_backend
        self.max_llm_calls = max_llm_calls
        self.max_tool_calls = max_tool_calls
        self.time_limit_s = time_limit_s
        self.enable_observation_guard = enable_observation_guard

    def run_task(
        self,
        task_config: Dict[str, Any],
        raw_source_episodes: Optional[List[Dict[str, Any]]] = None,
        structured_facts: Optional[StructuredFactStore] = None,
        procedural_memory_store: Optional[ProceduralMemoryStore] = None,
    ) -> Dict[str, Any]:
        """
        Execute one evaluation run on task_config.
        """
        t0 = time.time()
        env = WorkstationEnv(task_config.get("initial_state"))
        
        # State tracking
        known_state: Dict[str, Any] = {}
        trajectory: List[Dict[str, Any]] = []
        audit_events: List[Dict[str, Any]] = []
        
        # Telemetry counters
        llm_calls = 0
        prompt_tokens_total = 0
        gen_tokens_total = 0
        tool_errors_count = 0
        plan_deviations = 0
        memory_reused = False
        memory_invalidated_recovered = False
        
        # Active procedural plan for Group D
        active_memory: Optional[ProceduralMemoryItem] = None
        procedural_queue: List[Dict[str, Any]] = []
        tried_memories: Set[str] = set()

        # Termination status
        success = False
        termination_reason = "RUNNING"

        while True:
            # Check budgets and termination
            if env.is_task_completed():
                success = True
                termination_reason = "TASK_COMPLETED"
                break
            if len(trajectory) >= self.max_tool_calls:
                termination_reason = "TOOL_BUDGET_EXHAUSTED"
                break
            if llm_calls >= self.max_llm_calls:
                termination_reason = "LLM_BUDGET_EXHAUSTED"
                break
            if (time.time() - t0) >= self.time_limit_s:
                termination_reason = "TIME_LIMIT_EXCEEDED"
                break

            # -------------------------------------------------------------
            # Group D: Procedural Memory Subgoal Dispatch
            # -------------------------------------------------------------
            next_action: Optional[Dict[str, Any]] = None
            action_source = "online_llm"

            if self.group_id == "Group_D_Procedural_Memory" and procedural_memory_store:
                # 1. If currently executing an active procedural plan
                if procedural_queue:
                    candidate_step = procedural_queue[0]
                    # Check invalidation condition
                    if self._check_invalidation_trigger(candidate_step, known_state, env):
                        audit_events.append({
                            "event": "PROCEDURAL_MEMORY_INVALIDATED",
                            "memory_id": active_memory.memory_id if active_memory else "",
                            "step": candidate_step,
                            "reason": "Condition drift or interlock change detected; abandoning procedural replay.",
                        })
                        if active_memory:
                            tried_memories.add(active_memory.memory_id)
                        procedural_queue.clear()
                        active_memory = None
                        memory_invalidated_recovered = True
                    else:
                        next_action = candidate_step
                        action_source = "procedural_memory"

                # 2. If no active procedural queue, check if symptoms match a candidate memory
                if next_action is None and not procedural_queue:
                    cand_mem = self._match_candidate_memory(known_state, procedural_memory_store, tried_memories)
                    if cand_mem:
                        active_memory = cand_mem
                        memory_reused = True
                        procedural_queue = [
                            {"tool": a.tool, "args": copy.deepcopy(a.args), "node_id": a.node_id}
                            for a in cand_mem.actions
                        ]
                        audit_events.append({
                            "event": "PROCEDURAL_MEMORY_INSTANTIATED",
                            "memory_id": cand_mem.memory_id,
                            "nodes_count": len(procedural_queue),
                        })
                        next_action = procedural_queue[0]
                        action_source = "procedural_memory"

            # -------------------------------------------------------------
            # LLM Decision (for B0, B1, B2, or D when no procedural action)
            # -------------------------------------------------------------
            if next_action is None:
                llm_calls += 1
                prompt = self._construct_prompt(
                    task_config=task_config,
                    known_state=known_state,
                    trajectory=trajectory,
                    raw_source_episodes=raw_source_episodes,
                    structured_facts=structured_facts,
                    procedural_memory_store=procedural_memory_store if self.group_id == "Group_D_Procedural_Memory" else None,
                )

                response_text, p_tok, g_tok = self._call_llm(prompt)
                prompt_tokens_total += p_tok
                gen_tokens_total += g_tok

                parsed_action = self._parse_llm_response(response_text)
                if not parsed_action or "tool" not in parsed_action:
                    # Fallback inspection if unparseable
                    parsed_action = {"tool": "inspect", "args": {"subsystem": "all"}, "thought": "Inspect workstation status."}

                next_action = parsed_action
                action_source = "online_llm"

            # -------------------------------------------------------------
            # Execute Action
            # -------------------------------------------------------------
            tool_name = next_action.get("tool", "inspect")
            tool_args = next_action.get("args", {})
            
            tool_res = env.step(tool_name, **tool_args)
            is_err = tool_res.get("status") != StatusCode.SUCCESS

            if is_err:
                tool_errors_count += 1
                if action_source == "procedural_memory" and active_memory:
                    audit_events.append({
                        "event": "PROCEDURAL_MEMORY_ERROR_INVALIDATION",
                        "memory_id": active_memory.memory_id,
                        "failed_tool": tool_name,
                        "error": tool_res.get("error"),
                    })
                    tried_memories.add(active_memory.memory_id)
                    procedural_queue.clear()
                    active_memory = None
                    memory_invalidated_recovered = True
            else:
                if action_source == "procedural_memory" and procedural_queue:
                    procedural_queue.pop(0)
                    if not procedural_queue:
                        audit_events.append({
                            "event": "PROCEDURAL_MEMORY_COMPLETED",
                            "memory_id": active_memory.memory_id if active_memory else "",
                        })
                        if active_memory:
                            tried_memories.add(active_memory.memory_id)
                        active_memory = None

            # Update known state from observations
            self._update_known_state(known_state, tool_name, tool_args, tool_res)

            # Record step in trajectory
            step_record = {
                "step_index": len(trajectory) + 1,
                "action_source": action_source,
                "tool": tool_name,
                "args": tool_args,
                "thought": next_action.get("thought", ""),
                "result": tool_res,
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
            "memory_reused": memory_reused,
            "memory_invalidated_recovered": memory_invalidated_recovered,
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
                    if cand.status == "VALIDATED":
                        return cand
        return None

    def _check_invalidation_trigger(
        self,
        step: Dict[str, Any],
        known_state: Dict[str, Any],
        env: WorkstationEnv,
    ) -> bool:
        """Check if dynamic state violates candidate step assumptions."""
        tool = step.get("tool")
        args = step.get("args", {})
        sub = args.get("subsystem")

        if tool == "reset" and sub == "arm_gripper":
            if known_state.get("arm_gripper", {}).get("holding_load") is True:
                # Load interlock: cannot home arm while holding workpiece
                return True
        if tool == "calibrate" and sub == "camera_sensor":
            if known_state.get("power_unit", {}).get("status") == "tripped":
                # Cannot calibrate without power
                return True
        return False

    def _update_known_state(
        self,
        known_state: Dict[str, Any],
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_res: Dict[str, Any],
    ):
        """Update internal state representation based on tool observations and effects."""
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
            if tool_name == "isolate" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub]["isolated"] = (tool_args.get("action") == "engage")
            elif tool_name == "clear_fault" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub]["status"] = "nominal"
                if sub in ["arm_gripper", "pneumatic_line"] and "camera_sensor" in known_state:
                    known_state["camera_sensor"]["calibrated"] = False
                if "controller" in known_state:
                    known_state["controller"]["self_test_passed"] = False
            elif tool_name == "reset" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                if sub == "arm_gripper" and "camera_sensor" in known_state:
                    known_state["camera_sensor"]["calibrated"] = False
                if "controller" in known_state:
                    known_state["controller"]["self_test_passed"] = False
            elif tool_name == "calibrate" and sub:
                if sub not in known_state:
                    known_state[sub] = {}
                known_state[sub]["calibrated"] = True
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
    ) -> str:
        """Construct prompt according to group specifications."""
        parts = [WORKSTATION_SYSTEM_PROMPT, "\n=== Current Task Objective ==="]
        parts.append(f"Task ID: {task_config.get('task_id')}")
        parts.append(f"Goal: {task_config.get('goal')}")

        # Group B1: Append raw source episodes
        if self.group_id == "Group_B1_Raw_Trajectories" and raw_source_episodes:
            parts.append("\n=== Prior Cross-Task Experience (Raw Trajectories) ===")
            for idx, ep in enumerate(raw_source_episodes):
                parts.append(f"\n--- Episode {idx+1} ({ep.get('task_id')}, Success={ep.get('success')}) ---")
                for s in ep.get("trajectory", []):
                    r_obj = s.get("result", {})
                    msg = r_obj.get("message") or r_obj.get("error") or r_obj.get("status")
                    parts.append(f"  Step {s.get('step_index')}: {s.get('tool')}({s.get('args')}) -> {r_obj.get('status')} ({msg})")

        # Group B2 / Group D: Append rich structured facts
        if self.group_id in ["Group_B2_Structured_Facts", "Group_D_Procedural_Memory"] and structured_facts:
            facts_dict = structured_facts.to_dict()
            parts.append("\n=== Verified Structured Domain Facts ===")
            if facts_dict.get("action_preconditions"):
                parts.append("Verified Action Preconditions:")
                for act, reqs in facts_dict["action_preconditions"].items():
                    parts.append(f"  - {act}: requires {', '.join(reqs)}")
            if facts_dict.get("invalidation_rules"):
                parts.append("Verified Invalidation Rules:")
                for inv in facts_dict["invalidation_rules"]:
                    parts.append(f"  - {inv.get('action')}: causes {inv.get('invalidated_state')} ({inv.get('reason')})")
            if facts_dict.get("causal_order_constraints"):
                parts.append("Verified Causal Order Dependencies:")
                for dep in facts_dict["causal_order_constraints"]:
                    parts.append(f"  - In subsystem '{dep.get('subsystem')}': {dep.get('before')} must precede {dep.get('after')}")
            if facts_dict.get("commutative_subsystems"):
                parts.append("Commutative Independent Subsystems:")
                for pair in facts_dict["commutative_subsystems"]:
                    parts.append(f"  - Repair of '{pair[0]}' and '{pair[1]}' can be executed in any order.")

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

        parts.append("\nDecide your next action and output valid JSON:")
        return "\n".join(parts)

    def _call_llm(self, prompt: str) -> Tuple[str, int, int]:
        """Call LLM backend or fallback policy."""
        if self.llm_backend is not None and getattr(self.llm_backend, "model", None) is not None:
            messages = [{"role": "user", "content": prompt}]
            res = self.llm_backend.generate(messages)
            text = res.get("content", "")
            p_tok = res.get("prompt_tokens", 0)
            g_tok = res.get("generated_tokens", 0)
            return text, p_tok, g_tok

        # Fast deterministic fallback policy when running fast mechanism tests without GPU
        return self._rule_based_fallback_policy(prompt)

    def _rule_based_fallback_policy(self, prompt: str) -> Tuple[str, int, int]:
        """Deterministic policy used for dry-run verification and unit tests."""
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

        resp = json.dumps(action)
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
