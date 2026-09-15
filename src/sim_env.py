import numpy as np
import time
from typing import Dict, Any, Tuple

class RobotSimEnvironment:
    def __init__(self, task_spec: Dict[str, Any]):
        self.task_spec = task_spec
        self.goal = np.array(task_spec.get("goal_coord", [5.0, 5.0]))
        self.pos = np.array(task_spec.get("initial_robot_pos", [0.0, 0.0]))
        self.fault_type = task_spec.get("fault_type", "path_blocked")
        self.step_count = 0
        self.map_version = 1
        self.costmap_cleared = False
        self.retry_count = 0

    def step(self, action: str, params: Dict[str, Any] = None) -> Tuple[bool, str, Dict[str, Any]]:
        self.step_count += 1
        obs = {"pos": self.pos.tolist(), "map_version": self.map_version}

        if action == "clear_costmap":
            self.costmap_cleared = True
            self.map_version += 1
            return True, "Costmap cleared successfully.", obs

        elif action == "navigate":
            target = np.array(params.get("goal", self.goal.tolist()) if params else self.goal)
            
            # Simulate fault injection
            if self.step_count == self.task_spec.get("injected_fault_step", 2):
                if self.fault_type == "path_blocked" and not self.costmap_cleared:
                    return False, "ERROR: Path blocked by dynamic obstacle.", obs
                elif self.fault_type == "target_moved":
                    self.goal = self.goal + np.array([1.0, 1.0])
                    return False, "ERROR: Target object relocated.", obs
                elif self.fault_type == "action_timeout":
                    return False, "ERROR: Navigation action timed out.", obs

            # Move towards goal
            direction = target - self.pos
            dist = np.linalg.norm(direction)
            if dist > 0:
                self.pos = self.pos + (direction / dist) * min(dist, 2.0)
            
            if np.linalg.norm(self.goal - self.pos) < 0.3:
                return True, "Goal reached successfully.", obs
            return True, "Moving towards goal.", obs

        elif action == "observe":
            dist = np.linalg.norm(self.goal - self.pos)
            return (dist < 0.5), f"Observed target at distance {dist:.2f}m", obs

        elif action == "retry":
            self.retry_count += 1
            return True, "Retrying previous action.", obs

        return False, "Unknown action", obs

    def is_success(self) -> bool:
        return float(np.linalg.norm(self.goal - self.pos)) < 0.3
