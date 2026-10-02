"""
Objective Grounded Evaluation Scorer for FailMem Stage 2.
Calculates rigorous, event-grounded metrics across task sequences.
"""
from typing import Dict, Any, List


class PilotScorer:
    @staticmethod
    def score_sequence_results(sequence_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Computes aggregate metrics for a single method on a task sequence.
        """
        if not sequence_runs:
            return {}

        total_tasks = len(sequence_runs)
        success_tasks = [r.get("success", False) for r in sequence_runs]
        success_count = sum(1 for s in success_tasks if s)
        sequence_full_success = 1.0 if all(success_tasks) else 0.0

        # Acquisition task (Task 0) vs subsequent Evaluation tasks (Task 1+)
        acq_success = 1.0 if (len(success_tasks) > 0 and success_tasks[0]) else 0.0
        eval_success_count = sum(1 for s in success_tasks[1:]) if len(success_tasks) > 1 else 0
        eval_tasks_total = max(1, len(success_tasks) - 1)
        eval_success_rate = round(eval_success_count / eval_tasks_total, 4)

        # Constraint Violations & Termination Breakdown
        hard_violations = 0
        dead_loops = 0
        parse_errors = 0
        budget_exhausts = 0

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

        for r_idx, r in enumerate(sequence_runs):
            violations = r.get("constraint_violations", [])
            for v in violations:
                if "DEAD_LOOP_ABORT" in v:
                    dead_loops += 1
                elif "BATTERY_DEPLETED" in v or "WRONG_RECIPIENT" in v:
                    hard_violations += 1
                else:
                    hard_violations += 1

            for trace in r.get("llm_traces", []):
                total_prompt_tokens += trace.get("prompt_tokens", 0)
                total_gen_tokens += trace.get("generated_tokens", 0)

            step_hist = r.get("step_history", [])
            for step in step_hist:
                res = step.get("result", {})
                if step.get("tool") == "parse_error" or res.get("status") == "PARSE_ERROR":
                    parse_errors += 1

                if not res.get("success", True):
                    # Group by action, target, and error_code
                    sig = (step.get("tool"), str(step.get("params")), res.get("error_code") or res.get("status"))
                    if sig in failed_action_signatures:
                        repeated_failures += 1
                    failed_action_signatures.add(sig)

                # Grounded Unwarranted Detour:
                # In Stale tasks (r_idx >= 1), if robot at Lobby navigates via Corridor_South
                # when going to Office_A or Office_B (where door_north was available and unblocked)
                if r_idx >= 1 and step.get("tool") == "navigate":
                    params = step.get("params", {})
                    if params.get("target_zone") == "Corridor_South":
                        unwarranted_detours += 1

            if len(step_hist) >= 25 or len(r.get("llm_traces", [])) >= 20 or r.get("sim_time_s", 0.0) >= 300.0:
                budget_exhausts += 1

        return {
            "total_tasks": total_tasks,
            "task_success_rate": round(success_count / total_tasks, 4),
            "sequence_full_success": sequence_full_success,
            "acquisition_task_success": acq_success,
            "evaluation_task_success_rate": eval_success_rate,
            "hard_violations": hard_violations,
            "hard_violation_rate": round(hard_violations / total_tasks, 4),
            "dead_loop_aborts": dead_loops,
            "parse_errors": parse_errors,
            "budget_exhausts": budget_exhausts,
            "repeated_failures": repeated_failures,
            "unwarranted_detour_count": unwarranted_detours,
            "avg_steps_per_task": round(total_steps / total_tasks, 2),
            "avg_sim_time_per_task_s": round(total_sim_time / total_tasks, 2),
            "total_sim_time_s": round(total_sim_time, 2),
            "total_battery_consumed": total_battery_used,
            "total_llm_calls": total_llm_calls,
            "total_prompt_tokens": total_prompt_tokens,
            "total_gen_tokens": total_gen_tokens,
            "total_tokens": total_prompt_tokens + total_gen_tokens,
            "total_wall_time_s": round(total_wall_time, 2),
        }
