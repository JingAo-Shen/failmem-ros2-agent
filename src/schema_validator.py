"""Action schema validator for FailMem model probe and agent proposals.

Validates action proposals according to docs/problem-lock.md v0.2.
Allowed actions: navigate, observe, inspect_status, clear_costmap, retry.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

ALLOWED_ACTIONS = {"navigate", "observe", "inspect_status", "clear_costmap", "retry"}


def extract_json_block(text: str) -> Optional[str]:
    """Extract first JSON block from string, handling markdown fences or raw JSON."""
    text = text.strip()
    # Check for markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # Check for first outer { ... }
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return brace_match.group(0).strip()
    return None


def validate_action_payload(payload: Any) -> Tuple[bool, bool, Optional[str], Optional[str]]:
    """Validate parsed JSON against Problem Lock v0.2 Schema.

    Returns:
        (schema_valid, action_executable, error_type, error_message)
    """
    if not isinstance(payload, dict):
        return False, False, "INVALID_ROOT_TYPE", "Root JSON must be an object (dict)"

    # Check top-level required keys
    for req_key in ("action", "action_id", "params"):
        if req_key not in payload:
            return False, False, "MISSING_REQUIRED_KEY", f"Missing required key: '{req_key}'"

    action = payload["action"]
    action_id = payload["action_id"]
    params = payload["params"]

    if not isinstance(action, str) or not action:
        return False, False, "INVALID_ACTION_NAME", "action must be a non-empty string"
    if action not in ALLOWED_ACTIONS:
        return False, False, "UNSUPPORTED_ACTION", f"Action '{action}' is not in allowed actions: {sorted(ALLOWED_ACTIONS)}"
    if not isinstance(action_id, str) or not action_id:
        return False, False, "INVALID_ACTION_ID", "action_id must be a non-empty string"
    if not isinstance(params, dict):
        return False, False, "INVALID_PARAMS_TYPE", f"params must be a dict, got {type(params).__name__}"

    # Action-specific schema & executability validation
    if action == "navigate":
        if "goal" not in params:
            return False, False, "MISSING_NAV_GOAL", "navigate params must contain 'goal'"
        goal = params["goal"]
        if not isinstance(goal, (list, tuple)) or len(goal) != 3:
            return False, False, "INVALID_NAV_GOAL_SHAPE", f"navigate goal must be [x, y, yaw] (3 numbers), got {goal}"
        for i, val in enumerate(goal):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                return False, False, "INVALID_NAV_GOAL_TYPE", f"navigate goal coordinate {i} must be a number, got {type(val).__name__}"

        # Executability check: coordinate bounds within realistic indoor area
        x, y, yaw = float(goal[0]), float(goal[1]), float(goal[2])
        if abs(x) > 50.0 or abs(y) > 50.0:
            return True, False, "NAV_GOAL_OUT_OF_BOUNDS", f"navigate goal [{x}, {y}] exceeds physical boundary [-50, 50]"

        if "timeout_sec" in params:
            t = params["timeout_sec"]
            if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
                return False, False, "INVALID_TIMEOUT", f"timeout_sec must be positive float, got {t}"

        return True, True, None, None

    elif action == "observe":
        if "target_id" not in params:
            return False, False, "MISSING_TARGET_ID", "observe params must contain 'target_id'"
        target_id = params["target_id"]
        if not isinstance(target_id, str) or not target_id.strip():
            return False, False, "INVALID_TARGET_ID", "observe target_id must be a non-empty string"
        return True, True, None, None

    elif action == "inspect_status":
        # inspect_status expects an empty dict or valid inspection flags
        return True, True, None, None

    elif action == "clear_costmap":
        # clear_costmap expects empty dict or valid service flags
        return True, True, None, None

    elif action == "retry":
        if "original_action_id" not in params:
            return False, False, "MISSING_ORIGINAL_ACTION_ID", "retry params must contain 'original_action_id'"
        orig_id = params["original_action_id"]
        if not isinstance(orig_id, str) or not orig_id.strip():
            return False, False, "INVALID_ORIGINAL_ACTION_ID", "original_action_id must be a non-empty string"
        if "replayed_params" in params and not isinstance(params["replayed_params"], dict):
            return False, False, "INVALID_REPLAYED_PARAMS", "replayed_params must be a dict"
        return True, True, None, None

    return False, False, "UNKNOWN_VALIDATION_ERROR", "Unhandled validation state"


def parse_and_validate_action(raw_text: str) -> Dict[str, Any]:
    """Complete validation pipeline from model raw output string to execution readiness."""
    extracted = extract_json_block(raw_text)
    if not extracted:
        return {
            "raw_text": raw_text,
            "json_parseable": False,
            "schema_valid": False,
            "action_executable": False,
            "parsed_json": None,
            "action_name": None,
            "error_type": "JSON_EXTRACTION_FAILED",
            "error_message": "No JSON block or curly braces detected in raw text",
        }

    try:
        data = json.loads(extracted)
    except Exception as e:
        return {
            "raw_text": raw_text,
            "json_parseable": False,
            "schema_valid": False,
            "action_executable": False,
            "parsed_json": None,
            "action_name": None,
            "error_type": "JSON_SYNTAX_ERROR",
            "error_message": str(e),
        }

    schema_valid, executable, err_type, err_msg = validate_action_payload(data)
    action_name = data.get("action") if isinstance(data, dict) else None

    return {
        "raw_text": raw_text,
        "json_parseable": True,
        "schema_valid": schema_valid,
        "action_executable": executable,
        "parsed_json": data,
        "action_name": action_name,
        "error_type": err_type,
        "error_message": err_msg,
    }
