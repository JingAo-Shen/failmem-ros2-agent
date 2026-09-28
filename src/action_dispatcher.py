"""FailMem Unified Action Dispatcher.

Orchestrates the complete execution pipeline:
1. Strict Parsing (single JSON object or clean markdown code block).
2. Static Schema Validation (field types, positive finite timeouts, coordinate bounds).
3. Parameter Normalization (defaults: frame_id="map", timeout_sec=60.0).
4. Runtime History Constraints (action_id uniqueness, retry validity, budget, state fingerprint).
5. Parameter Restoration (for retry: restore original executable action and params from history).
6. Scoped ROS Goal UUID derivation (deterministic mapping with run/episode scope).
7. Dispatch to ROS Action Server / Execution Layer.
8. Terminal Status Recording.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Callable, Dict, Optional, Tuple, Union

from src.action_runtime import EpisodeActionHistoryContext
from src.schema_validator import parse_and_validate_action, validate_action_schema

FAILMEM_UUID_NAMESPACE = uuid.UUID("79551a6b-151c-4311-ad4b-bb28a6dc589b")


def derive_ros_goal_uuid(
    action_id: str,
    run_id: Optional[str] = None,
    episode_id: Optional[Union[str, int]] = None,
) -> uuid.UUID:
    """Derive a deterministic 128-bit UUID for ROS 2 Action Goal with run and episode scoping."""
    scope_str = f"{run_id or 'global'}:{episode_id or 'default'}:{action_id}"
    return uuid.uuid5(FAILMEM_UUID_NAMESPACE, scope_str)


def normalize_action_parameters(action_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Apply standard default values to optional fields in action params.
    
    Returns a new normalized dictionary with complete explicit fields.
    """
    normalized = copy.deepcopy(action_dict)
    action_name = normalized.get("action")
    params = normalized.setdefault("params", {})

    if action_name == "navigate":
        params.setdefault("frame_id", "map")
        params.setdefault("timeout_sec", 60.0)
    elif action_name == "retry":
        params.setdefault("replayed_params", None)

    return normalized


class ActionDispatcher:
    """Unified entrypoint for robot action processing and dispatch."""

    def __init__(
        self,
        context: Optional[EpisodeActionHistoryContext] = None,
        ros_executor: Optional[Callable[[Dict[str, Any], uuid.UUID], Dict[str, Any]]] = None,
        run_id: Optional[str] = None,
        episode_id: Optional[Union[str, int]] = None,
    ):
        self.context = context or EpisodeActionHistoryContext()
        self.ros_executor = ros_executor
        self.run_id = run_id
        self.episode_id = episode_id
        self.goal_uuid_mapping: Dict[str, str] = {}
        self.dispatched_actions: list[Dict[str, Any]] = []

    def dispatch(
        self,
        raw_or_dict: Union[str, Dict[str, Any]],
        visible_state: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        episode_id: Optional[Union[str, int]] = None,
    ) -> Dict[str, Any]:
        """Process and dispatch an action through the verified pipeline.

        Returns structured result dictionary.
        """
        effective_run_id = run_id or self.run_id
        effective_ep_id = episode_id or self.episode_id

        # Step 1 & 2: Parse and Static Validate
        if isinstance(raw_or_dict, str):
            val_res = parse_and_validate_action(raw_or_dict)
            if not val_res["json_parseable"]:
                return {
                    "pipeline_status": "FAILED",
                    "failure_stage": "JSON_PARSE",
                    "error_type": val_res["error_type"],
                    "error_message": val_res["error_message"],
                    "ros_dispatched": False,
                }
            if not val_res["schema_valid"]:
                return {
                    "pipeline_status": "FAILED",
                    "failure_stage": "SCHEMA_VALIDATION",
                    "error_type": val_res["error_type"],
                    "error_message": val_res["error_message"],
                    "ros_dispatched": False,
                }
            action_dict = val_res["parsed_json"]
        elif isinstance(raw_or_dict, dict):
            schema_valid, err_type, err_msg = validate_action_schema(raw_or_dict)
            if not schema_valid:
                return {
                    "pipeline_status": "FAILED",
                    "failure_stage": "SCHEMA_VALIDATION",
                    "error_type": err_type,
                    "error_message": err_msg,
                    "ros_dispatched": False,
                }
            action_dict = copy.deepcopy(raw_or_dict)
        else:
            return {
                "pipeline_status": "FAILED",
                "failure_stage": "INPUT_TYPE",
                "error_type": "INVALID_INPUT_TYPE",
                "error_message": f"Expected str or dict, got {type(raw_or_dict).__name__}",
                "ros_dispatched": False,
            }

        # Step 3: Default Normalization
        normalized = normalize_action_parameters(action_dict)
        action_id = normalized["action_id"]
        action_name = normalized["action"]

        # Step 4: Runtime Action History & Constraints Check
        hist_status, err_type, err_msg = self.context.validate_action_history_constraints(
            normalized, visible_state=visible_state
        )
        if hist_status != "PASSED":
            return {
                "pipeline_status": "FAILED",
                "failure_stage": "RUNTIME_HISTORY_CONSTRAINTS",
                "error_type": err_type,
                "error_message": err_msg,
                "ros_dispatched": False,
                "action_id": action_id,
            }

        # Step 5: Parameter Restoration for retry
        # If retry, guarantee execution params are restored from original action
        effective_action = copy.deepcopy(normalized)
        if action_name == "retry":
            orig_id = normalized["params"]["original_action_id"]
            orig_act = self.context.get_action_by_id(orig_id)
            if orig_act is not None:
                # Restore original action params for execution
                effective_action["executable_action"] = orig_act.get("executable_action", orig_act.get("action"))
                effective_action["executable_params"] = copy.deepcopy(
                    orig_act.get("executable_params", orig_act.get("params", {}))
                )

        # Register in context
        self.context.record_action(normalized, visible_state=visible_state)

        # Step 6: Derive Scoped ROS Goal UUID
        goal_uuid = derive_ros_goal_uuid(action_id, run_id=effective_run_id, episode_id=effective_ep_id)
        self.goal_uuid_mapping[action_id] = str(goal_uuid)

        # Step 7: Dispatch to ROS executor if provided
        ros_result = None
        if self.ros_executor is not None:
            try:
                ros_result = self.ros_executor(effective_action, goal_uuid)
                dispatch_status = ros_result.get("status", "DISPATCHED") if isinstance(ros_result, dict) else "DISPATCHED"
                self.context.update_action_status(action_id, dispatch_status=dispatch_status)
                self.dispatched_actions.append({
                    "action_id": action_id,
                    "goal_uuid": str(goal_uuid),
                    "dispatched_action": effective_action,
                    "ros_result": ros_result,
                })
            except Exception as e:
                self.context.update_action_status(action_id, dispatch_status="DISPATCH_EXCEPTION")
                return {
                    "pipeline_status": "FAILED",
                    "failure_stage": "ROS_EXECUTION_EXCEPTION",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "ros_dispatched": True,
                    "action_id": action_id,
                    "goal_uuid": str(goal_uuid),
                }

        return {
            "pipeline_status": "DISPATCHED",
            "action_id": action_id,
            "goal_uuid": str(goal_uuid),
            "normalized_action": normalized,
            "effective_action": effective_action,
            "ros_dispatched": self.ros_executor is not None,
            "ros_result": ros_result,
        }

    def record_terminal_status(
        self,
        action_id: str,
        terminal_status: str,
        status_code: Optional[int] = None,
    ) -> bool:
        """Record final execution terminal status (SUCCEEDED, ABORTED, CANCELED, TIMEOUT) back to context."""
        return self.context.update_action_status(
            action_id,
            dispatch_status="COMPLETED",
            terminal_status=terminal_status,
            status_code=status_code,
        )
