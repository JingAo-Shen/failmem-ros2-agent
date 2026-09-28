"""FailMem Episode Runtime Context & Action History Manager.

Enforces:
1. No duplicate action_ids within an episode.
2. Retry validation:
   - original_action_id must exist in current episode history.
   - Rejection of self-referencing retry.
   - Rejection of recursive retries (retrying a retry).
   - Rejection of parameter tampering (replayed_params must exactly match original params).
   - Enforcement of retry budget limit (default max 3 per episode).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple


class EpisodeExecutionContext:
    """Tracks action history and validates runtime execution preconditions for an episode."""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.action_history: List[Dict[str, Any]] = []
        self._action_id_set: set[str] = set()

    def reset(self):
        """Reset episode history for a new episode."""
        self.action_history.clear()
        self._action_id_set.clear()

    def get_action_by_id(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Find an action in the history by its action_id."""
        for act in self.action_history:
            if act.get("action_id") == action_id:
                return act
        return None

    def validate_runtime_preconditions(self, action_dict: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """Validate runtime preconditions against current episode context.

        Returns:
            (runtime_status, error_message)
            runtime_status: 'PASSED' or 'FAILED'
        """
        action_id = action_dict.get("action_id")
        action_name = action_dict.get("action")
        params = action_dict.get("params", {})

        # 1. Check duplicate action_id
        if action_id in self._action_id_set:
            return "FAILED", f"DUPLICATE_ACTION_ID: Action ID '{action_id}' has already been used in this episode."

        # 2. Specific checks for 'retry' action
        if action_name == "retry":
            # Check retry budget
            current_retries = sum(1 for a in self.action_history if a.get("action") == "retry")
            if current_retries >= self.max_retries:
                return "FAILED", f"RETRY_BUDGET_EXCEEDED: Episode retry budget exhausted ({current_retries}/{self.max_retries})."

            orig_id = params.get("original_action_id")

            # Check self-reference
            if orig_id == action_id:
                return "FAILED", "SELF_REFERENCING_RETRY: retry cannot reference its own action_id."

            # Check existence in history
            orig_action = self.get_action_by_id(orig_id)
            if not orig_action:
                return "FAILED", f"UNKNOWN_RETRY_REFERENCE: original_action_id '{orig_id}' not found in episode history."

            # Check recursive retry
            if orig_action.get("action") == "retry":
                return "FAILED", "RECURSIVE_RETRY_FORBIDDEN: Cannot retry an action that is itself a retry."

            # Check parameter tampering
            if "replayed_params" in params:
                replayed = params["replayed_params"]
                actual_orig_params = orig_action.get("params", {})
                if replayed != actual_orig_params:
                    return "FAILED", (
                        f"PARAMETER_TAMPERING_DETECTED: replayed_params {replayed} does not match "
                        f"original action params {actual_orig_params}."
                    )

        return "PASSED", None

    def record_action(self, action_dict: Dict[str, Any]):
        """Record an executed action into the episode history."""
        self.action_history.append(copy.deepcopy(action_dict))
        self._action_id_set.add(action_dict["action_id"])
