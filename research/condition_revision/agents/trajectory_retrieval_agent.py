"""
Raw Trajectory Retrieval Agent (Group B):
Stores raw execution trajectories without abstracting them into condition rules.
Retrieves the most semantically relevant trajectory as an in-context demonstration.
"""

from typing import List, Dict, Any, Tuple
from agents.base_agent import BaseAgent


class TrajectoryRetrievalAgent(BaseAgent):
    def __init__(self, llm_client, trajectory_store: List[Dict[str, Any]] = None):
        super().__init__(llm_client)
        self.name = "B_RawTrajectory"
        self.trajectory_store = trajectory_store or []

    def add_trajectory(self, trajectory: Dict[str, Any]):
        self.trajectory_store.append(trajectory)

    def retrieve_relevant_trajectory(self, task_desc: str) -> str:
        if not self.trajectory_store:
            return ""

        query_words = set(w.lower() for w in task_desc.split() if len(w) > 3)
        best_score = -1
        best_traj = None

        for t in self.trajectory_store:
            t_desc = t.get("task_description", "")
            t_words = set(w.lower() for w in t_desc.split() if len(w) > 3)
            overlap = len(query_words & t_words)
            if overlap > best_score:
                best_score = overlap
                best_traj = t

        if best_traj is None:
            return ""

        steps = best_traj.get("steps", [])
        step_summary = []
        for i, s in enumerate(steps[:10]):
            step_summary.append(f"  Step {i+1}: Action: {s.get('action')}")

        return f"""### Reference Past Trajectory (from task: {best_traj.get('task_name')}):
Task Goal: {best_traj.get('task_description')}
Outcome: {'SUCCEEDED' if best_traj.get('success') else 'FAILED'}
Action Sequence:
{chr(10).join(step_summary)}
"""

    def select_action(
        self,
        task_desc: str,
        current_obs: str,
        history: List[Tuple[str, str]],
        valid_actions: List[str],
        extra_context: str = ""
    ) -> Tuple[str, str, Dict[str, Any]]:
        ref_context = self.retrieve_relevant_trajectory(task_desc)
        combined_context = f"{ref_context}\n\n{extra_context}" if extra_context else ref_context
        return super().select_action(
            task_desc=task_desc,
            current_obs=current_obs,
            history=history,
            valid_actions=valid_actions,
            extra_context=combined_context
        )
