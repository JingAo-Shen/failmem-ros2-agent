"""
Closed-loop Agent Runner executing task episodes under strict budget constraints.
Logs all decisions, tool results, memory updates, and environment violations.
"""
from typing import Dict, Any, List, Optional
import time
import copy
from .llm_backend import LLMBackend
from .planner import AgentPlanner
from ..env.task_env import DeliveryTaskEnv
from ..env.tools import StatusCode, ActionResult
from ..memory.baselines import BaseMemoryAdapter


class AgentRunner:
    def __init__(
        self,
        llm_backend: LLMBackend,
        memory_adapter: BaseMemoryAdapter,
        max_tool_calls: int = 25,
        max_llm_calls: int = 20,
        max_sim_time_s: float = 300.0,
        run_id: str = "run_default",
    ):
        self.llm = llm_backend
        self.memory = memory_adapter
        self.planner = AgentPlanner(llm_backend, memory_adapter)
        self.max_tool_calls = max_tool_calls
        self.max_llm_calls = max_llm_calls
        self.max_sim_time_s = max_sim_time_s
        self.run_id = run_id

    def run_task(
        self,
        task_spec: Dict[str, Any],
        task_index: int = 0,
        seq_id: str = "seq_default",
    ) -> Dict[str, Any]:
        task_id = task_spec.get("task_id", f"task_{task_index}")
        instruction = task_spec.get("instruction", "")
        env_config = task_spec.get("env_config", {})
        env_config["time_limit_s"] = self.max_sim_time_s

        env = DeliveryTaskEnv(env_config)
        self.memory.on_task_start(task_id, task_index)

        step_history: List[Dict[str, Any]] = []
        llm_traces: List[Dict[str, Any]] = []
        consecutive_failures = 0
        last_failed_sig = None
        known_state: Dict[str, Any] = {}

        t_wall_start = time.time()

        while not env.is_terminated and len(step_history) < self.max_tool_calls and len(llm_traces) < self.max_llm_calls:
            step_idx = len(step_history) + 1
            robot_loc_before = env.robot_location

            # Visible public state only
            current_state = {
                "robot_location": env.robot_location,
                "battery": env.battery,
                "inventory": list(env.inventory),
                "credentials": list(env.credentials),
                "available_packages": [
                    {"id": pid, "pickup_location": pdata["location"], "target_room": pdata["target_room"], "recipient": pdata["recipient"]}
                    for pid, pdata in env.packages.items() if not pdata["delivered"]
                ],
            }

            # 1. Plan next step
            decision, meta_traces = self.planner.decide_next_action(
                task_instruction=instruction,
                current_state=current_state,
                known_state=known_state,
                step_history=step_history,
                task_id=task_id,
                run_id=self.run_id,
                method_name=self.memory.method_name,
                seq_id=seq_id,
                task_index=task_index,
                step_index=step_idx,
            )
            if isinstance(meta_traces, list):
                llm_traces.extend(meta_traces)
            else:
                llm_traces.append(meta_traces)

            tool_name = decision.get("action", "parse_error")
            params = decision.get("params", {})
            event_id = f"evt_{self.run_id}_{self.memory.method_name}_{seq_id}_{task_id}_s{step_idx:02d}"

            # Capture environment ground truth snapshot for offline scoring (never exposed to Agent)
            env_state_snapshot = {
                "doors": copy.deepcopy(env.doors),
                "robot_location": env.robot_location,
            }

            # 2. Execute on Environment or Handle Parse Error
            if tool_name == "parse_error":
                env._consume_resources(1.0, 1)
                result = ActionResult(
                    status=StatusCode.PARSE_ERROR,
                    success=False,
                    message="Decision JSON parsing failed after retry.",
                    time_cost_s=1.0,
                    battery_cost_pct=1,
                    error_code="PARSE_ERROR",
                )
            else:
                result = env.step(tool_name, params)

            sim_time = env.sim_time_s

            # Update known state from direct observations
            if result.observation:
                if "door" in result.observation and "passage_state" in result.observation:
                    door_k = f"{result.observation['door']}_state"
                    known_state[door_k] = result.observation["passage_state"]
                if "credentials" in result.observation:
                    known_state["credentials"] = result.observation["credentials"]
                if "recipient" in result.observation and "status" in result.observation:
                    rec_k = f"{result.observation['recipient']}_status"
                    known_state[rec_k] = result.observation["status"]

            step_entry = {
                "step": step_idx,
                "event_id": event_id,
                "decision_summary": decision.get("decision_summary", ""),
                "tool": tool_name,
                "params": params,
                "robot_location_before": robot_loc_before,
                "robot_location_after": env.robot_location,
                "env_state_snapshot": env_state_snapshot,
                "result": result.to_dict(),
                "sim_time_s": sim_time,
                "battery": env.battery,
            }
            step_history.append(step_entry)

            # 3. Update Memory (Do not record system parsing / syntax errors into environmental memory)
            target_str = str(params.get("target_zone") or params.get("target") or params.get("package_id") or params.get("recipient") or "")
            if not result.success:
                error_code = result.error_code or result.status.value
                if result.status not in (StatusCode.PARSE_ERROR, StatusCode.INVALID_PARAMETER):
                    self.memory.record_action_failure(
                        event_id=event_id,
                        task_id=task_id,
                        action_name=tool_name,
                        target=target_str,
                        error_code=error_code,
                        raw_message=result.message,
                        observation=result.observation,
                        sim_time=sim_time,
                    )
                sig = f"{tool_name}:{params}"
                if sig == last_failed_sig:
                    consecutive_failures += 1
                else:
                    last_failed_sig = sig
                    consecutive_failures = 1
            else:
                consecutive_failures = 0
                last_failed_sig = None
                if result.observation:
                    self.memory.record_observation(event_id, result.observation, sim_time)

            # Dead-loop check
            if consecutive_failures >= 3:
                env.constraint_violations.append(f"DEAD_LOOP_ABORT: Repeatedly executed failing action: {last_failed_sig}")
                env.is_terminated = True
                break

        t_wall_end = time.time()
        env_summary = env.get_summary()

        return {
            "task_id": task_id,
            "task_index": task_index,
            "instruction": instruction,
            "method": self.memory.method_name,
            "success": env_summary["success"],
            "all_packages_delivered": env_summary["all_packages_delivered"],
            "delivered_count": env_summary["delivered_count"],
            "total_packages": env_summary["total_packages"],
            "final_battery": env_summary["final_battery"],
            "battery_consumed": env_summary["cumulative_battery_consumed"],
            "sim_time_s": env_summary["final_sim_time_s"],
            "wall_time_s": round(t_wall_end - t_wall_start, 3),
            "step_count": len(step_history),
            "llm_calls": len(llm_traces),
            "constraint_violations": env_summary["constraint_violations"],
            "step_history": step_history,
            "llm_traces": llm_traces,
            "memory_stats": self.memory.get_stats(),
        }
