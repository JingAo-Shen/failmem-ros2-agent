"""FailMem Episode Action History & Constraints Manager.

Enforces:
1. No duplicate action_ids within an episode.
2. Retry validation:
   - original_action_id must exist in current episode history.
   - Rejection of self-referencing retry.
   - Rejection of recursive retries (retrying a retry).
   - Parameter restoration / verification (replayed_params must strictly match original).
   - At most 1 retry per identical visible state fingerprint for the same original action.
   - Enforcement of episode retry budget limit (default max 3 per episode).

NOTE:
PASSED indicates ONLY that action history, retry references, state fingerprints,
and budget constraints are satisfied. It DOES NOT verify full physical preconditions
(such as robot kinematic feasibility, localization validity, or costmap status).
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


def compute_visible_state_fingerprint(visible_state: Optional[Dict[str, Any]]) -> str:
    """Compute a deterministic hash for agent-visible observation state.
    
    CRITICAL: Does NOT use ground truth or hidden simulator labels.
    Uses only agent-visible data (e.g. estimated pose, scan min distance, last observation).
    """
    if not visible_state:
        return "DEFAULT_INITIAL_STATE"
    # Filter to ensure no hidden or GT fields leaked
    clean_state = {}
    for k, v in sorted(visible_state.items()):
        if k in ("ground_truth", "gt_pose", "hidden_fault_label", "fault_injected"):
            continue
        clean_state[k] = v
    encoded = json.dumps(clean_state, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


class EpisodeActionHistoryContext:
    """Tracks action history and validates history-level constraints for an episode."""

    def __init__(self, max_retries: int = 3, max_retries_per_state: int = 1):
        self.max_retries = max_retries
        self.max_retries_per_state = max_retries_per_state
        self.action_history: List[Dict[str, Any]] = []
        self._action_id_set: set[str] = set()
        # Track (original_action_id, state_fingerprint) -> count
        self._retry_state_counts: Dict[Tuple[str, str], int] = {}

    def reset(self):
        """Reset episode history for a new episode."""
        self.action_history.clear()
        self._action_id_set.clear()
        self._retry_state_counts.clear()

    def get_action_by_id(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Find an action in the history by its action_id."""
        for act in self.action_history:
            if act.get("action_id") == action_id:
                return act
        return None

    def validate_action_history_constraints(
        self, action_dict: Dict[str, Any], visible_state: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """Validate action history constraints against current episode context.

        Returns:
            (history_status, error_type, error_message)
            history_status: 'PASSED' or 'FAILED'
        """
        action_id = action_dict.get("action_id")
        action_name = action_dict.get("action")
        params = action_dict.get("params", {})

        # 1. Check duplicate action_id
        if action_id in self._action_id_set:
            return (
                "FAILED",
                "DUPLICATE_ACTION_ID",
                f"Action ID '{action_id}' has already been used in this episode.",
            )

        # 2. Specific checks for 'retry' action
        if action_name == "retry":
            # Check episode retry budget
            current_retries = sum(1 for a in self.action_history if a.get("action") == "retry")
            if current_retries >= self.max_retries:
                return (
                    "FAILED",
                    "RETRY_BUDGET_EXCEEDED",
                    f"Episode retry budget exhausted ({current_retries}/{self.max_retries}).",
                )

            orig_id = params.get("original_action_id")

            # Check self-reference
            if orig_id == action_id:
                return (
                    "FAILED",
                    "SELF_REFERENCING_RETRY",
                    "retry cannot reference its own action_id.",
                )

            # Check existence in history
            orig_action = self.get_action_by_id(orig_id)
            if not orig_action:
                return (
                    "FAILED",
                    "UNKNOWN_RETRY_REFERENCE",
                    f"original_action_id '{orig_id}' not found in episode history.",
                )

            # Check recursive retry
            if orig_action.get("action") == "retry":
                return (
                    "FAILED",
                    "RECURSIVE_RETRY_FORBIDDEN",
                    "Cannot retry an action that is itself a retry.",
                )

            # Check state fingerprint retry limit
            fingerprint = compute_visible_state_fingerprint(visible_state)
            key = (orig_id, fingerprint)
            times_retried_in_state = self._retry_state_counts.get(key, 0)
            if times_retried_in_state >= self.max_retries_per_state:
                return (
                    "FAILED",
                    "STATE_FINGERPRINT_RETRY_EXHAUSTED",
                    (
                        f"Action '{orig_id}' has already been retried in the identical "
                        f"visible state (fingerprint: {fingerprint})."
                    ),
                )

            # Check parameter tampering
            if "replayed_params" in params and params["replayed_params"]:
                replayed = params["replayed_params"]
                actual_orig_params = orig_action.get("params", {})
                if replayed != actual_orig_params:
                    return (
                        "FAILED",
                        "PARAMETER_TAMPERING_DETECTED",
                        (
                            f"replayed_params {replayed} does not match "
                            f"original action params {actual_orig_params}."
                        ),
                    )

        return "PASSED", None, None

    # Maintain backward compatibility alias
    def validate_runtime_preconditions(self, action_dict: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        status, err_type, err_msg = self.validate_action_history_constraints(action_dict)
        if status != "PASSED" and err_type:
            return status, f"{err_type}: {err_msg}"
        return status, err_msg

    def record_action(self, action_dict: Dict[str, Any], visible_state: Optional[Dict[str, Any]] = None):
        """Record an executed action into the episode history."""
        action_copy = copy.deepcopy(action_dict)
        action_copy.setdefault("dispatch_status", "RECORDED")
        action_copy.setdefault("terminal_status", None)
        self.action_history.append(action_copy)
        self._action_id_set.add(action_dict["action_id"])

        if action_dict.get("action") == "retry":
            orig_id = action_dict.get("params", {}).get("original_action_id")
            fingerprint = compute_visible_state_fingerprint(visible_state)
            key = (orig_id, fingerprint)
            self._retry_state_counts[key] = self._retry_state_counts.get(key, 0) + 1

    def update_action_status(
        self,
        action_id: str,
        dispatch_status: str,
        terminal_status: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> bool:
        """Update dispatch and terminal status for an action in history."""
        for act in self.action_history:
            if act.get("action_id") == action_id:
                act["dispatch_status"] = dispatch_status
                if terminal_status is not None:
                    act["terminal_status"] = terminal_status
                if status_code is not None:
                    act["status_code"] = status_code
                return True
        return False


# Alias for compatibility with existing imports
EpisodeExecutionContext = EpisodeActionHistoryContext
