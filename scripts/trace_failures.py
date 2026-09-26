#!/usr/bin/env python3
"""
Failure Attribution & Trajectory Tracing Script:
Accurately traces formal_task_008 (target_moved) and formal_task_012 (action_timeout)
step-by-step. Explains the exact failure attribution: step counts, action allocations,
effective navigation counts, distance budgets, and recovery mechanisms.
"""

import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import RobotSimEnvironment
from src.failmem import FailureMemoryStore

def trace_single_task(task, use_memory=True):
    env = RobotSimEnvironment(task)
    store = FailureMemoryStore()
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
    
    trajectory = []
    initial_goal = np.array(task.get("goal_coord", [0.0, 0.0]))
    initial_pos = np.array(task.get("initial_robot_pos", [0.0, 0.0]))
    initial_dist = float(np.linalg.norm(initial_goal - initial_pos))
    
    effective_nav_count = 0
    recovery_count = 0
    
    for st in range(6):
        pos_before = env.pos.copy()
        goal_before = env.goal.copy()
        dist_before = float(np.linalg.norm(env.goal - env.pos))
        
        success, msg, obs = env.step("navigate")
        dist_after = float(np.linalg.norm(env.goal - env.pos))
        
        step_record = {
            "loop_iteration": st + 1,
            "action": "navigate",
            "pos_before": pos_before.tolist(),
            "pos_after": env.pos.tolist(),
            "goal_before": goal_before.tolist(),
            "goal_after": env.goal.tolist(),
            "dist_before": round(dist_before, 4),
            "dist_after": round(dist_after, 4),
            "step_success": success,
            "message": msg,
            "env_step_count": env.step_count
        }
        
        if success:
            effective_nav_count += 1
            if env.is_success():
                step_record["event"] = "GOAL_REACHED"
                trajectory.append(step_record)
                break
            else:
                step_record["event"] = "ADVANCED_TOWARDS_GOAL"
                trajectory.append(step_record)
        else:
            # Fault encountered
            symptom = msg
            recovery = store.retrieve_recovery(symptom, obs["map_version"], use_memory=use_memory)
            step_record["event"] = "FAULT_ENCOUNTERED"
            step_record["symptom"] = symptom
            step_record["retrieved_recovery"] = recovery
            trajectory.append(step_record)
            
            # Execute recovery or fallback
            if recovery:
                recovery_count += 1
                r_succ, r_msg, r_obs = env.step(recovery)
                trajectory.append({
                    "loop_iteration": st + 1,
                    "action": recovery,
                    "is_recovery": True,
                    "step_success": r_succ,
                    "message": r_msg,
                    "env_step_count": env.step_count,
                    "pos_after": env.pos.tolist(),
                    "goal_after": env.goal.tolist(),
                    "remaining_dist": round(float(np.linalg.norm(env.goal - env.pos)), 4)
                })
            else:
                r_succ, r_msg, r_obs = env.step("retry")
                trajectory.append({
                    "loop_iteration": st + 1,
                    "action": "retry",
                    "is_recovery": False,
                    "step_success": r_succ,
                    "message": r_msg,
                    "env_step_count": env.step_count,
                    "pos_after": env.pos.tolist(),
                    "goal_after": env.goal.tolist(),
                    "remaining_dist": round(float(np.linalg.norm(env.goal - env.pos)), 4)
                })
                
    store.close()
    
    final_dist = float(np.linalg.norm(env.goal - env.pos))
    return {
        "task_id": task["id"],
        "fault_type": task["fault_type"],
        "use_memory": use_memory,
        "initial_pos": initial_pos.tolist(),
        "initial_goal": initial_goal.tolist(),
        "final_goal": env.goal.tolist(),
        "final_pos": env.pos.tolist(),
        "initial_dist_m": round(initial_dist, 4),
        "final_dist_m": round(final_dist, 4),
        "is_success": env.is_success(),
        "total_env_steps": env.step_count,
        "effective_navigation_steps": effective_nav_count,
        "recovery_actions_count": recovery_count,
        "trajectory": trajectory
    }

def main():
    task_008 = {
        "id": "formal_task_008",
        "layout_id": "unseen_layout_2",
        "fault_type": "target_moved",
        "goal_coord": [9.0, 4.0],
        "initial_robot_pos": [0.0, 0.0],
        "injected_fault_step": 2
    }
    task_012 = {
        "id": "formal_task_012",
        "layout_id": "unseen_layout_6",
        "fault_type": "action_timeout",
        "goal_coord": [9.0, 8.0],
        "initial_robot_pos": [0.0, 0.0],
        "injected_fault_step": 2
    }
    
    t008_mem_on = trace_single_task(task_008, use_memory=True)
    t008_mem_off = trace_single_task(task_008, use_memory=False)
    t012_mem_on = trace_single_task(task_012, use_memory=True)
    t012_mem_off = trace_single_task(task_012, use_memory=False)
    
    attribution_report = {
        "analysis_target": "Detailed failure mechanism for formal_task_008 and formal_task_012",
        "formal_task_008_target_moved": {
            "initial_state": "pos=[0,0], goal=[9,4], initial_distance=9.8489m",
            "step_breakdown": {
                "step_1": "navigate successfully advances 2.0m towards [9,4]. Remaining distance: 7.8489m.",
                "step_2_fault": "navigate encounters fault. Target relocates to [10,5]. Distance jumps to 9.1830m. Memory has no heuristic for 'target_moved', so fallback retry is executed. Robot does not move (advancement: 0.0m).",
                "steps_3_to_6": "4 navigate steps advance 4 * 2.0m = 8.0m towards [10,5].",
                "termination": "Loop finishes 6 iterations. Robot reaches [8.9473, 4.4606]. Final distance to [10,5] is 1.1830m > 0.3m. Task fails.",
                "effective_nav_steps": 5,
                "total_effective_distance_covered": "10.0m",
                "distance_needed": "11.1803m (from origin to [10,5])"
            },
            "root_cause_explanation": "Task fails not because of recovery failure, but because: (1) target relocation increased total distance required from 9.85m to 11.18m; (2) memory store contains no recovery rule for target_moved, forcing fallback retry; (3) losing 1 iteration to fault/retry left only 5 navigation steps (max 10m range), which mathematically cannot cover 11.18m within the fixed 6-iteration loop budget."
        },
        "formal_task_012_action_timeout": {
            "initial_state": "pos=[0,0], goal=[9,8], initial_distance=12.0416m",
            "step_breakdown": {
                "step_1": "navigate successfully advances 2.0m towards [9,8]. Remaining distance: 10.0416m.",
                "step_2_fault": "navigate times out. In memory ON, clear_costmap is executed; in memory OFF, retry is executed. Neither action moves the robot (advancement: 0.0m).",
                "steps_3_to_6": "4 navigate steps advance 4 * 2.0m = 8.0m towards [9,8].",
                "termination": "Loop finishes 6 iterations. Robot reaches [7.4741, 6.6436]. Final distance to [9,8] is 2.0416m > 0.3m. Task fails.",
                "effective_nav_steps": 5,
                "total_effective_distance_covered": "10.0m",
                "distance_needed": "12.0416m"
            },
            "root_cause_explanation": "Task fails because: (1) initial distance is 12.0416m; (2) in the ideal fault-free case with 6 full navigation steps, robot covers 12.0m, arriving within 0.0416m (<0.3m); (3) when fault occurs at step 2, 1 step is spent on recovery/retry with 0m forward progress; (4) with only 5 navigation steps available (10.0m max), the robot remains 2.0416m short of goal. Furthermore, clear_costmap is a dummy action that cannot accelerate or rescue a pure distance/timeout deficit."
        },
        "traces": {
            "task_008_mem_on": t008_mem_on,
            "task_008_mem_off": t008_mem_off,
            "task_012_mem_on": t012_mem_on,
            "task_012_mem_off": t012_mem_off
        }
    }
    
    os.makedirs("reports/evidence/r0", exist_ok=True)
    out_path = "reports/evidence/r0/failure_attribution_trace.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(attribution_report, f, indent=2, ensure_ascii=False)
        
    print(f"Failure attribution traces written to {out_path}")

if __name__ == "__main__":
    main()
