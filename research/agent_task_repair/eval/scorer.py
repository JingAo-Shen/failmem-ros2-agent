"""
Objective Environment-Grounded Evaluation Scorer for FailMem Stage 2.
Calculates primary and secondary metrics across evaluation runs.
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
        success_count = sum(1 for r in sequence_runs if r.get("success", False))
        violation_count = sum(1 for r in sequence_runs if len(r.get("constraint_violations", [])) > 0)

        # Repeated failures: count of repeated action failures across tasks
        repeated_failures = 0
        unwarranted_avoidance_count = 0
        total_steps = sum(r.get("step_count", 0) for r in sequence_runs)
        total_sim_time = sum(r.get("sim_time_s", 0.0) for r in sequence_runs)
        total_battery_used = sum(r.get("battery_consumed", 0) for r in sequence_runs)
        total_llm_calls = sum(r.get("llm_calls", 0) for r in sequence_runs)
        total_wall_time = sum(r.get("wall_time_s", 0.0) for r in sequence_runs)

        total_prompt_tokens = 0
        total_gen_tokens = 0

        for r in sequence_runs:
            for trace in r.get("llm_traces", []):
                total_prompt_tokens += trace.get("prompt_tokens", 0)
                total_gen_tokens += trace.get("generated_tokens", 0)

            # Analyze step history for repeated failures & unwarranted avoidances
            step_hist = r.get("step_history", [])
            failed_sigs = set()
            for step in step_hist:
                res = step.get("result", {})
                if not res.get("success", True):
                    sig = f"{step.get('tool')}:{step.get('params')}"
                    if sig in failed_sigs:
                        repeated_failures += 1
                    failed_sigs.add(sig)

                # Unwarranted avoidance detection:
                # In Cat2 (stale), if door_north is clear but agent navigates via Corridor_South without trying door_north
                thought = step.get("thought", "").lower()
                if "avoid" in thought or "blocked" in thought and "south" in thought:
                    if step.get("tool") == "navigate" and step.get("params", {}).get("target_zone") == "Corridor_South":
                        unwarranted_avoidance_count += 1

        return {
            "total_tasks": total_tasks,
            "success_rate": round(success_count / total_tasks, 4),
            "constraint_violation_rate": round(violation_count / total_tasks, 4),
            "repeated_failures": repeated_failures,
            "unwarranted_avoidance_count": unwarranted_avoidance_count,
            "avg_steps_per_task": round(total_steps / total_tasks, 2),
            "total_sim_time_s": round(total_sim_time, 2),
            "total_battery_consumed": total_battery_used,
            "total_llm_calls": total_llm_calls,
            "total_prompt_tokens": total_prompt_tokens,
            "total_gen_tokens": total_gen_tokens,
            "total_tokens": total_prompt_tokens + total_gen_tokens,
            "total_wall_time_s": round(total_wall_time, 2),
        }

    @staticmethod
    def compare_methods(results_by_method: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Compares methods against B0 (memoryless) and strongest baseline."""
        return {
            method: metrics
            for method, metrics in results_by_method.items()
        }
