"""
ScienceWorld Environment Wrapper:
Provides deterministic resetting, step execution, observation simplification,
valid action querying, and action-prefix replay.
"""

from typing import Tuple, List, Dict, Any, Optional
from scienceworld import ScienceWorldEnv


class ScienceWorldWrapper:
    def __init__(self, step_limit: int = 30):
        self.step_limit = step_limit
        self.env = ScienceWorldEnv("", "", envStepLimit=step_limit)
        self.current_task = None
        self.current_variation = None
        self.history = []

    def load_and_reset(self, task_name: str, variation: int) -> Tuple[str, str, List[str], Dict[str, Any]]:
        self.current_task = task_name
        self.current_variation = variation
        self.history = []
        self.env.load(task_name, variation, simplificationStr="teleportAction,openDoors")
        obs, info = self.env.reset()
        task_desc = self.env.get_task_description().strip()
        valid_actions = self.env.get_valid_action_object_combinations()
        return obs, task_desc, valid_actions, info

    def step(self, action: str) -> Tuple[str, float, bool, Dict[str, Any], List[str]]:
        self.history.append(action)
        obs, reward, done, info = self.env.step(action)
        valid_actions = self.env.get_valid_action_object_combinations()
        return obs, reward, done, info, valid_actions

    def replay_prefix(self, task_name: str, variation: int, actions: List[str]) -> Tuple[str, float, bool, Dict[str, Any], List[str]]:
        """Replays an exact action prefix from clean reset."""
        obs, task_desc, valid_actions, info = self.load_and_reset(task_name, variation)
        reward = 0.0
        done = False
        for act in actions:
            obs, reward, done, info, valid_actions = self.step(act)
            if done:
                break
        return obs, reward, done, info, valid_actions

    def get_task_description(self) -> str:
        return self.env.get_task_description().strip()

    def get_score(self) -> float:
        return float(self.env.lastStepScore)

    def close(self):
        try:
            self.env.close()
        except Exception:
            pass
