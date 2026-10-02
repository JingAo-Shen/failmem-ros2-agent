"""
Closed-loop Agent Runner executing task episodes under strict budget constraints.
Logs all decisions, tool results, memory updates, and environment violations.
"""
from typing import Dict, Any, List, Optional
import time
from .llm_backend import LLMBackend
from .planner import AgentPlanner
from ..env.task_env import DeliveryTaskEnv
from ..memory.baselines import BaseMemoryAdapter, F_ConditionAwareMemory


class AgentRunner:
    def __init__(
        self,
        llm_backend: LLMBackend,
        memory_adapter: BaseMemoryAdapter,
        max_tool_calls: int = 25,
        max_llm_calls: int = 20,
        max_sim_time_s: float = 300.0,
    ):
        self.llm = llm_backend
        self.memory = memory_adapter
        self.planner = AgentPlanner(llm_backend, memory_adapter)
        self.max_tool_calls = max_tool_calls
        self.max_llm_calls = max_llm_calls
        self.max_sim_time_s = max_sim_time_s

    def run_task(self, task_spec: Dict[str, Any], task_index: int = 0) -> Dict[str, Any]:
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

        t_wall_start = time.time()

        while not env.is_terminated and len(step_history) < self.max_tool_calls and len(llm_traces) < self.max_llm_calls:
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
            decision, meta = self.planner.decide_next_action(
                task_instruction=instruction,
                current_state=current_state,
                step_history=step_history,
                task_id=task_id,
            )
            llm_traces.append(meta)

            tool_name = decision.get("action", "navigate")
            params = decision.get("params", {})

            # 2. Execute on Environment
            result = env.step(tool_name, params)
            sim_time = env.sim_time_s

            step_entry = {
                "step": len(step_history) + 1,
                "thought": decision.get("thought", ""),
                "tool": tool_name,
                "params": params,
                "result": result.to_dict(),
                "sim_time_s": sim_time,
                "battery": env.battery,
            }
            step_history.append(step_entry)

            # 3. Update Memory
            target_str = str(params.get("target_zone") or params.get("target") or params.get("package_id") or params.get("recipient") or "")
            if not result.success:
                error_code = result.error_code or result.status.value
                self.memory.record_action_failure(
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
                # On success / observation: update memory (e.g. dynamic invalidation)
                if result.observation:
                    self.memory.record_observation(result.observation, sim_time)

            # Check consecutive failure abort
            if consecutive_failures >= 3:
                env.constraint_violations.append(f"REPEATED_ACTION_ABORT: Stuck in loop on {last_failed_sig}")
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
            "battery_consumed": 100 - env_summary["final_battery"],
            "sim_time_s": env_summary["final_sim_time_s"],
            "wall_time_s": round(t_wall_end - t_wall_start, 3),
            "step_count": len(step_history),
            "llm_calls": len(llm_traces),
            "constraint_violations": env_summary["constraint_violations"],
            "step_history": step_history,
            "llm_traces": llm_traces,
            "memory_stats": self.memory.get_stats(),
        }
