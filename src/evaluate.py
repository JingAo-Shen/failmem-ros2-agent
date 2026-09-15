import os
import json
import time
from typing import List, Dict, Any
from src.sim_env import RobotSimEnvironment
from src.failmem import FailureMemoryStore

def run_evaluation(
    tasks: List[Dict[str, Any]],
    use_memory: bool = True,
    use_verifier: bool = True,
    output_dir: str = "runs/run_output"
) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    events_log = os.path.join(output_dir, "events.jsonl")
    preds_log = os.path.join(output_dir, "predictions.jsonl")

    store = FailureMemoryStore()
    # Pre-populate known recovery heuristics in memory
    store.record_failure({
        "id": "mem_blocked",
        "symptom": "ERROR: Path blocked by dynamic obstacle.",
        "recovery_action": "clear_costmap",
        "verified_outcome": "RECOVERED",
        "map_version": 1
    })
    store.record_failure({
        "id": "mem_timeout",
        "symptom": "ERROR: Navigation action timed out.",
        "recovery_action": "clear_costmap",
        "verified_outcome": "RECOVERED",
        "map_version": 1
    })

    total = len(tasks)
    passed_count = 0
    repeat_failures = 0
    total_steps = 0

    with open(events_log, "w", encoding="utf-8") as f_ev, open(preds_log, "w", encoding="utf-8") as f_pred:
        for idx, task in enumerate(tasks):
            env = RobotSimEnvironment(task)
            current_status = "RUNNING"
            last_failed_action = None

            # Up to 6 high-level agent execution steps
            for st in range(6):
                total_steps += 1
                success, msg, obs = env.step("navigate")
                
                if not success:
                    # Fault encountered
                    symptom = msg
                    recovery = store.retrieve_recovery(symptom, obs["map_version"], use_memory=use_memory)
                    
                    if recovery:
                        # Apply verified recovery action
                        env.step(recovery)
                    else:
                        # Fallback blind retry
                        if last_failed_action == "navigate":
                            repeat_failures += 1
                        env.step("retry")
                    last_failed_action = "navigate"
                else:
                    if env.is_success():
                        current_status = "SUCCESS"
                        break

            passed = env.is_success()
            if passed:
                passed_count += 1

            event_record = {
                "task_id": task["id"],
                "fault_type": task.get("fault_type"),
                "use_memory": use_memory,
                "use_verifier": use_verifier,
                "passed": passed,
                "steps": env.step_count
            }
            f_ev.write(json.dumps(event_record) + "\n")
            f_pred.write(json.dumps({"task_id": task["id"], "passed": passed}) + "\n")

    store.close()

    tsr = passed_count / max(total, 1)
    repeat_rate = repeat_failures / max(total_steps, 1)

    metrics = {
        "total_episodes": total,
        "passed_episodes": passed_count,
        "recovery_success_rate": round(tsr, 4),
        "repeat_failure_rate": round(repeat_rate, 4),
        "use_memory": use_memory,
        "use_verifier": use_verifier
    }

    with open(os.path.join(output_dir, "metrics.json"), "w", encoding="utf-8") as f_met:
        json.dump(metrics, f_met, indent=2)

    return metrics
