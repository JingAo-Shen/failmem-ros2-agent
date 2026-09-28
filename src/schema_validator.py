"""Strict Action Schema Validator for FailMem (Problem Lock v0.2 Compliant).

Provides strict two-phase validation:
1. Strict JSON parsing: enforces single top-level object, rejects duplicate keys,
   rejects NaN / Infinity / 1e999, rejects conversational text outside markdown code blocks,
   and rejects top-level arrays or multiple objects.
2. Static schema validation: verifies action name, non-whitespace action_id,
   parameter types, finite coordinates, supported frame_id, timeout budget,
   and rejects extra undefined parameters.
3. Explicit separation: json_parseable vs schema_valid vs runtime_precondition_status.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

ALLOWED_ACTIONS: Set[str] = {"navigate", "observe", "inspect_status", "clear_costmap", "retry"}
ALLOWED_FRAMES: Set[str] = {"map", "odom"}
MAX_NAV_TIMEOUT_SEC: float = 60.0


def _reject_constants(val: str):
    """Reject non-standard JSON numbers (NaN, Infinity, -Infinity)."""
    raise ValueError(f"Non-standard JSON numeric constant not allowed: {val}")


def _duplicate_key_detector(ordered_pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Detect and reject duplicate keys within the same JSON object."""
    seen: Set[str] = set()
    result: Dict[str, Any] = {}
    for k, v in ordered_pairs:
        if k in seen:
            raise ValueError(f"Duplicate JSON key detected: '{k}'")
        seen.add(k)
        result[k] = v
    return result


def extract_strict_json_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract strict single JSON text.

    Accepts ONLY:
    - A raw JSON object string with optional surrounding whitespace.
    - A single markdown code block (``` or ```json) enclosing ONLY the JSON object,
      with optional whitespace before/after the fence.
    Rejects:
    - Conversational text before/after the JSON.
    - Multiple JSON objects or multiple code blocks.
    - Top-level arrays.
    """
    stripped = text.strip()
    if not stripped:
        return None, "EMPTY_INPUT"

    # Check for markdown code block pattern
    # Must start with ``` and end with ```
    fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    fence_match = re.match(fence_pattern, stripped, re.DOTALL)
    if fence_match:
        inner = fence_match.group(1).strip()
        # Verify no second code block inside
        if "```" in inner:
            return None, "MULTIPLE_CODE_BLOCKS"
        if not inner.startswith("{") or not inner.endswith("}"):
            return None, "NOT_A_SINGLE_JSON_OBJECT"
        return inner, None

    # If no code fence, the entire text must start with { and end with }
    if stripped.startswith("{") and stripped.endswith("}"):
        # Check that there are no multiple objects concatenated
        # (e.g. {} {} or conversational text before/after)
        return stripped, None

    if stripped.startswith("["):
        return None, "TOP_LEVEL_ARRAY_FORBIDDEN"

    return None, "CONVERSATIONAL_TEXT_OR_NOT_JSON"


def parse_strict_json(raw_text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Strictly parse raw text into a single Python dict.

    Returns:
        (parsed_dict, error_type, error_message)
    """
    json_str, extract_err = extract_strict_json_text(raw_text)
    if extract_err:
        return None, "JSON_SYNTAX_ERROR", f"Failed strict JSON extraction: {extract_err}"

    try:
        data = json.loads(
            json_str,
            object_pairs_hook=_duplicate_key_detector,
            parse_constant=_reject_constants,
        )
    except Exception as e:
        return None, "JSON_SYNTAX_ERROR", f"JSON parsing failed: {str(e)}"

    if not isinstance(data, dict):
        return None, "JSON_SYNTAX_ERROR", f"Top-level element must be an object (dict), got {type(data).__name__}"

    return data, None, None


def validate_action_schema(data: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
    """Validate parsed JSON dictionary against Problem Lock v0.2 action schemas.

    Returns:
        (schema_valid, error_type, error_message)
    """
    # 1. Required top-level fields
    for req_field in ("action", "action_id", "params"):
        if req_field not in data:
            return False, "MISSING_REQUIRED_FIELD", f"Missing required top-level field: '{req_field}'"

    # Reject unexpected top-level fields
    allowed_top_keys = {"action", "action_id", "params"}
    extra_top = set(data.keys()) - allowed_top_keys
    if extra_top:
        return False, "EXTRA_TOP_LEVEL_FIELDS", f"Unexpected top-level fields: {sorted(extra_top)}"

    action = data["action"]
    action_id = data["action_id"]
    params = data["params"]

    # 2. Field type checks
    if not isinstance(action, str) or not action:
        return False, "INVALID_ACTION_NAME", "Field 'action' must be a non-empty string"
    if action not in ALLOWED_ACTIONS:
        return False, "UNSUPPORTED_ACTION", f"Action '{action}' is not in allowed actions: {sorted(ALLOWED_ACTIONS)}"

    if not isinstance(action_id, str) or not action_id.strip():
        return False, "INVALID_ACTION_ID", "Field 'action_id' must be a non-empty, non-whitespace string"

    if not isinstance(params, dict):
        return False, "INVALID_PARAMS_TYPE", f"Field 'params' must be an object (dict), got {type(params).__name__}"

    # 3. Action-specific parameter schemas
    if action == "navigate":
        allowed_params = {"goal", "frame_id", "timeout_sec"}
        extra_params = set(params.keys()) - allowed_params
        if extra_params:
            return False, "EXTRA_PARAMETERS", f"navigate params contains unexpected keys: {sorted(extra_params)}"

        if "goal" not in params:
            return False, "MISSING_NAV_GOAL", "navigate params must contain 'goal'"
        goal = params["goal"]
        if not isinstance(goal, (list, tuple)) or len(goal) != 3:
            return False, "INVALID_NAV_GOAL_SHAPE", f"navigate goal must be a list/tuple of 3 coordinates [x, y, yaw], got {goal}"

        for i, val in enumerate(goal):
            # Strict float/int check: booleans are subclasses of int in Python!
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                return False, "INVALID_NAV_GOAL_TYPE", f"navigate goal coordinate [{i}] must be a finite number, got {type(val).__name__}"
            if not math.isfinite(val):
                return False, "NON_FINITE_COORDINATE", f"navigate goal coordinate [{i}] must be finite (got {val})"

        if "frame_id" in params:
            frame_id = params["frame_id"]
            if not isinstance(frame_id, str) or not frame_id.strip():
                return False, "INVALID_FRAME_ID", "frame_id must be a non-empty string"
            if frame_id not in ALLOWED_FRAMES:
                return False, "UNSUPPORTED_FRAME_ID", f"frame_id '{frame_id}' is not supported. Allowed: {sorted(ALLOWED_FRAMES)}"

        if "timeout_sec" in params:
            t = params["timeout_sec"]
            if isinstance(t, bool) or not isinstance(t, (int, float)):
                return False, "INVALID_TIMEOUT", f"timeout_sec must be a positive number, got {type(t).__name__}"
            if not math.isfinite(t) or t <= 0.0:
                return False, "INVALID_TIMEOUT", f"timeout_sec must be a positive finite number, got {t}"
            if t > MAX_NAV_TIMEOUT_SEC:
                return False, "TIMEOUT_EXCEEDS_BUDGET", f"timeout_sec {t} exceeds maximum allowed budget ({MAX_NAV_TIMEOUT_SEC}s)"

        return True, None, None

    elif action == "observe":
        allowed_params = {"target_id"}
        extra_params = set(params.keys()) - allowed_params
        if extra_params:
            return False, "EXTRA_PARAMETERS", f"observe params contains unexpected keys: {sorted(extra_params)}"

        if "target_id" not in params:
            return False, "MISSING_TARGET_ID", "observe params must contain 'target_id'"
        target_id = params["target_id"]
        if not isinstance(target_id, str) or not target_id.strip():
            return False, "INVALID_TARGET_ID", "target_id must be a non-empty, non-whitespace string"
        return True, None, None

    elif action == "inspect_status":
        if params:
            return False, "EXTRA_PARAMETERS", f"inspect_status params must be empty {{}}, got {list(params.keys())}"
        return True, None, None

    elif action == "clear_costmap":
        if params:
            return False, "EXTRA_PARAMETERS", f"clear_costmap params must be empty {{}}, got {list(params.keys())}"
        return True, None, None

    elif action == "retry":
        allowed_params = {"original_action_id", "replayed_params"}
        extra_params = set(params.keys()) - allowed_params
        if extra_params:
            return False, "EXTRA_PARAMETERS", f"retry params contains unexpected keys: {sorted(extra_params)}"

        if "original_action_id" not in params:
            return False, "MISSING_ORIGINAL_ACTION_ID", "retry params must contain 'original_action_id'"
        orig_id = params["original_action_id"]
        if not isinstance(orig_id, str) or not orig_id.strip():
            return False, "INVALID_ORIGINAL_ACTION_ID", "original_action_id must be a non-empty, non-whitespace string"

        if "replayed_params" in params:
            if not isinstance(params["replayed_params"], dict):
                return False, "INVALID_REPLAYED_PARAMS", "replayed_params must be a dict"

        return True, None, None

    return False, "UNKNOWN_ACTION_VALIDATION_ERROR", f"Unhandled action validation for '{action}'"


def parse_and_validate_action(raw_text: str) -> Dict[str, Any]:
    """Main parsing and static schema validation pipeline.

    Separates:
    - json_parseable: True if parsed strictly as single JSON object.
    - schema_valid: True if fields and parameter types strictly match schema.
    - runtime_precondition_status: Always 'NOT_CHECKED' in static validation.
    """
    data, parse_err_type, parse_err_msg = parse_strict_json(raw_text)
    if data is None:
        return {
            "raw_text": raw_text,
            "json_parseable": False,
            "schema_valid": False,
            "runtime_precondition_status": "NOT_CHECKED",
            "parsed_json": None,
            "action_name": None,
            "error_stage": "JSON_PARSE",
            "error_type": parse_err_type,
            "error_message": parse_err_msg,
        }

    schema_valid, schema_err_type, schema_err_msg = validate_action_schema(data)
    action_name = data.get("action") if isinstance(data, dict) else None

    return {
        "raw_text": raw_text,
        "json_parseable": True,
        "schema_valid": schema_valid,
        "runtime_precondition_status": "NOT_CHECKED",
        "parsed_json": data,
        "action_name": action_name,
        "error_stage": None if schema_valid else "SCHEMA_VALIDATION",
        "error_type": schema_err_type,
        "error_message": schema_err_msg,
    }
