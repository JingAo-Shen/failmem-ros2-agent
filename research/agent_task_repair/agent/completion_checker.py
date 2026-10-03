"""
Task Completion Verifier for FailMem Stage 2 Stateful Agent Architecture.
Guarantees that task success is certified strictly by discrete tool execution evidence
(e.g., successful deliver tool returns for every obligation), never verbal self-proclamation.
"""
from typing import Dict, Any, List, Tuple
from .task_state import TaskStateTracker, ObligationStatus


class CompletionChecker:
    @staticmethod
    def verify_completion(
        task_state: TaskStateTracker,
        step_history: List[Dict[str, Any]],
        constraint_violations: List[str],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verifies task completion against ground execution evidence.
        Returns: (is_success, summary_reason, details_dict)
        """
        obligations = task_state.obligations
        total_obs = len(obligations)
        done_obs = [ob for ob in obligations.values() if ob.status == ObligationStatus.DONE]
        undone_obs = [ob for ob in obligations.values() if ob.status != ObligationStatus.DONE]

        # Check delivered packages from step history
        delivered_packages = set()
        for step in step_history:
            if step.get("tool") == "deliver" and step.get("result", {}).get("success"):
                pid = step.get("params", {}).get("package_id")
                if pid:
                    delivered_packages.add(pid)

        # 1. Hard constraint violation check
        if constraint_violations:
            return False, f"Failed: Constraint violations occurred ({constraint_violations}).", {
                "total_obligations": total_obs,
                "completed_obligations": len(done_obs),
                "undone_obligations": [ob.package_id for ob in undone_obs],
                "constraint_violations": constraint_violations,
            }

        # 2. Obligation check
        if len(done_obs) < total_obs or len(delivered_packages) < total_obs:
            missing_pids = [ob.package_id for ob in undone_obs if ob.package_id not in delivered_packages]
            return False, f"Incomplete: {len(missing_pids)} obligations pending delivery ({missing_pids}).", {
                "total_obligations": total_obs,
                "completed_obligations": len(done_obs),
                "missing_packages": missing_pids,
                "constraint_violations": [],
            }

        return True, f"Success: All {total_obs} delivery obligations verified completed with tool execution evidence.", {
            "total_obligations": total_obs,
            "completed_obligations": len(done_obs),
            "missing_packages": [],
            "constraint_violations": [],
        }
