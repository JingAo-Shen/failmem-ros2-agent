"""
Objective Grounded Evaluation Scorer for FailMem Stage 2.
Calculates rigorous, event-grounded metrics across task sequences.
"""
from typing import Dict, Any, List, Optional


class PilotScorer:
    @staticmethod
    def score_sequence_results(sequence_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Computes aggregate metrics for a single method on a task sequence.
        """
        if not sequence_runs:
            return {}

        total_tasks = len(sequence_runs)
        success_tasks = [bool(r.get("success", False)) for r in sequence_runs]
        success_count = sum(1 for s in success_tasks if s is True)
        sequence_full_success = 1.0 if (total_tasks > 0 and all(success_tasks)) else 0.0

        # Acquisition task (Task 0) vs subsequent Evaluation tasks (Task 1+)
        acq_success = 1.0 if (len(success_tasks) > 0 and success_tasks[0] is True) else 0.0
        
        if len(success_tasks) > 1:
            eval_success_count = sum(1 for s in success_tasks[1:] if s is True)
            eval_tasks_total = len(success_tasks) - 1
            eval_success_rate = round(eval_success_count / eval_tasks_total, 4)
        else:
            eval_success_count = None
            eval_tasks_total = 0
            eval_success_rate = None

        # Categorize 5 Distinct Failure / Termination Causes
        hard_violation_tasks = 0
        hard_violation_events = 0
        dead_loop_tasks = 0
        parse_error_events = 0
        parse_error_tasks = 0
        rejected_action_events = 0
        budget_exhaust_tasks = 0

        # Behavioral Metrics Grounded in Events
        repeated_failures = 0
        unwarranted_detours = 0
        failed_action_signatures = set()

        total_steps = sum(r.get("step_count", 0) for r in sequence_runs)
        total_sim_time = sum(r.get("sim_time_s", 0.0) for r in sequence_runs)
        total_battery_used = sum(r.get("battery_consumed", 0) for r in sequence_runs)
        total_llm_calls = sum(r.get("llm_calls", 0) for r in sequence_runs)
        total_wall_time = sum(r.get("wall_time_s", 0.0) for r in sequence_runs)

        total_prompt_tokens = 0
        total_gen_tokens = 0

        # Non-hard rejection error codes (rejected illegal attempts by executor)
        REJECTED_STATUS_CODES = {
            "WRONG_LOCATION",
            "NOT_HOLDING_PACKAGE",
            "NOT_AT_CHARGER",
            "INVENTORY_FULL",
            "ACCESS_DENIED_NO_BADGE",
            "DOOR_BLOCKED",
            "PACKAGE_NOT_FOUND",
            "RECIPIENT_BUSY",
            "RECIPIENT_AWAY",
            "INVALID_PARAMETER",
        }

        for r_idx, r in enumerate(sequence_runs):
            task_had_hard_violation = False
            task_had_dead_loop = False
            task_had_parse_error = False

            violations = r.get("constraint_violations", [])
            for v in violations:
                if "DEAD_LOOP_ABORT" in v:
                    task_had_dead_loop = True
                elif "BATTERY_DEPLETED" in v or "WRONG_RECIPIENT" in v:
                    hard_violation_events += 1
                    task_had_hard_violation = True
                else:
                    hard_violation_events += 1
                    task_had_hard_violation = True

            if task_had_hard_violation:
                hard_violation_tasks += 1
            if task_had_dead_loop:
                dead_loop_tasks += 1

            for trace in r.get("llm_traces", []):
                total_prompt_tokens += trace.get("prompt_tokens", 0)
                total_gen_tokens += trace.get("generated_tokens", 0)

            step_hist = r.get("step_history", [])
            for step in step_hist:
                res = step.get("result", {})
                status = res.get("status", "")
                tool = step.get("tool", "")
                params = step.get("params", {})

                if tool == "parse_error" or status == "PARSE_ERROR":
                    parse_error_events += 1
                    task_had_parse_error = True

                if status in REJECTED_STATUS_CODES:
                    rejected_action_events += 1

                if not res.get("success", True):
                    # Group by tool, target/params, error_code
                    err_code = res.get("error_code") or status
                    sig = (tool, str(params), err_code)
                    if sig in failed_action_signatures:
                        repeated_failures += 1
                    failed_action_signatures.add(sig)

                # Grounded Unwarranted Detour:
                # Robot is at Lobby, goal is Office_A or Office_B (not Lab_Secure),
                # door_north is physically FREE (unblocked), but robot navigates to Corridor_South.
                # If door_north is blocked or target is Lab_Secure, taking Corridor_South is direct/legal (not unwarranted).
                door_north_state = step.get("env_state_snapshot", {}).get("doors", {}).get("door_north", {}).get("blocked", None)
                robot_loc = step.get("robot_location_before") or step.get("robot_location")
                task_inst = r.get("instruction", "")
                is_lab_target = ("Lab_Secure" in task_inst) or any(
                    s.get("params", {}).get("target_zone") == "Lab_Secure" or s.get("params", {}).get("recipient") == "Bob"
                    for s in step_hist
                )
                if not is_lab_target and door_north_state is False and robot_loc == "Lobby" and tool == "navigate" and params.get("target_zone") == "Corridor_South":
                    unwarranted_detours += 1

            if task_had_parse_error:
                parse_error_tasks += 1

            if len(step_hist) >= 25 or len(r.get("llm_traces", [])) >= 20 or r.get("sim_time_s", 0.0) >= 300.0:
                if not r.get("success", False):
                    budget_exhaust_tasks += 1

        return {
            "total_tasks": total_tasks,
            "success_count": success_count,
            "task_success_rate": round(success_count / total_tasks, 4) if total_tasks > 0 else 0.0,
            "sequence_full_success": sequence_full_success,
            "acquisition_task_success": acq_success,
            "evaluation_success_count": eval_success_count,
            "evaluation_tasks_total": eval_tasks_total,
            "evaluation_task_success_rate": eval_success_rate,
            "hard_violation_events": hard_violation_events,
            "hard_violation_tasks": hard_violation_tasks,
            "hard_violation_rate": round(hard_violation_tasks / total_tasks, 4) if total_tasks > 0 else 0.0,
            "rejected_action_events": rejected_action_events,
            "dead_loop_aborts": dead_loop_tasks,
            "parse_error_events": parse_error_events,
            "parse_error_tasks": parse_error_tasks,
            "budget_exhaust_tasks": budget_exhaust_tasks,
            "repeated_failures": repeated_failures,
            "unwarranted_detour_count": unwarranted_detours,
            "avg_steps_per_task": round(total_steps / total_tasks, 2) if total_tasks > 0 else 0.0,
            "avg_sim_time_per_task_s": round(total_sim_time / total_tasks, 2) if total_tasks > 0 else 0.0,
            "total_sim_time_s": round(total_sim_time, 2),
            "total_battery_consumed": total_battery_used,
            "total_llm_calls": total_llm_calls,
            "total_prompt_tokens": total_prompt_tokens,
            "total_gen_tokens": total_gen_tokens,
            "total_tokens": total_prompt_tokens + total_gen_tokens,
            "total_wall_time_s": round(total_wall_time, 2),
        }
