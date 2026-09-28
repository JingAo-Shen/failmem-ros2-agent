"""Comprehensive static schema validation tests for Problem Lock v0.2."""
import pytest
from src.schema_validator import parse_and_validate_action


class TestStrictSchemaValidator:
    """Test suite for strict JSON parsing and schema validation."""

    # --- Positive Tests ---

    def test_valid_navigate(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [4.0, 3.0, 0.0], "frame_id": "map", "timeout_sec": 45.0}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["runtime_precondition_status"] == "NOT_CHECKED"
        assert res["action_name"] == "navigate"
        assert res["error_stage"] is None

    def test_valid_navigate_in_markdown_code_block(self):
        raw = '```json\n{"action": "navigate", "action_id": "act_002", "params": {"goal": [1.0, 2.0, 0.5]}}\n```'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_name"] == "navigate"

    def test_valid_observe(self):
        raw = '{"action": "observe", "action_id": "act_003", "params": {"target_id": "box_target_01"}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_name"] == "observe"

    def test_valid_inspect_status(self):
        raw = '{"action": "inspect_status", "action_id": "act_004", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_name"] == "inspect_status"

    def test_valid_clear_costmap(self):
        raw = '{"action": "clear_costmap", "action_id": "act_005", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_name"] == "clear_costmap"

    def test_valid_retry(self):
        raw = '{"action": "retry", "action_id": "act_006", "params": {"original_action_id": "act_001", "replayed_params": {"goal": [4.0, 3.0, 0.0]}}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_name"] == "retry"

    # --- Negative Parsing Tests (Strictness) ---

    def test_negative_conversational_text_outside_json(self):
        raw = 'Here is your next action:\n{"action": "navigate", "action_id": "act_001", "params": {"goal": [1.0, 0.0, 0.0]}}\nHope this helps!'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["error_stage"] == "JSON_PARSE"

    def test_negative_top_level_array(self):
        raw = '[{"action": "navigate", "action_id": "act_001", "params": {"goal": [1.0, 0.0, 0.0]}}]'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["error_stage"] == "JSON_PARSE"

    def test_negative_multiple_json_objects(self):
        raw = '{"action": "clear_costmap", "action_id": "act_001", "params": {}} {"action": "navigate", "action_id": "act_002", "params": {"goal": [1.0, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["error_stage"] == "JSON_PARSE"

    def test_negative_duplicate_keys(self):
        raw = '{"action": "navigate", "action_id": "act_001", "action_id": "act_dup", "params": {"goal": [1.0, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["error_stage"] == "JSON_PARSE"
        assert "Duplicate JSON key" in str(res["error_message"])

    def test_negative_nan_constant(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [NaN, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["error_stage"] == "JSON_PARSE"

    def test_negative_infinity_constant(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [Infinity, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["error_stage"] == "JSON_PARSE"

    # --- Negative Schema Tests ---

    def test_negative_float_overflow_non_finite(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [1e999, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        # 1e999 parses to float('inf') in standard json, which schema validator rejects as NON_FINITE
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_stage"] == "SCHEMA_VALIDATION"
        assert res["error_type"] == "NON_FINITE_COORDINATE"

    def test_negative_bool_coordinate(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [true, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "INVALID_NAV_GOAL_TYPE"

    def test_negative_empty_action_id(self):
        raw = '{"action": "navigate", "action_id": "   ", "params": {"goal": [1.0, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "INVALID_ACTION_ID"

    def test_negative_missing_field(self):
        raw = '{"action": "navigate", "params": {"goal": [1.0, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "MISSING_REQUIRED_FIELD"

    def test_negative_illegal_frame_id(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [1.0, 0.0, 0.0], "frame_id": "camera_link"}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "UNSUPPORTED_FRAME_ID"

    def test_negative_timeout_exceeds_budget(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [1.0, 0.0, 0.0], "timeout_sec": 120.0}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "TIMEOUT_EXCEEDS_BUDGET"

    def test_negative_inspect_status_with_extra_params(self):
        raw = '{"action": "inspect_status", "action_id": "act_001", "params": {"verbose": true}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "EXTRA_PARAMETERS"

    def test_negative_clear_costmap_with_extra_params(self):
        raw = '{"action": "clear_costmap", "action_id": "act_001", "params": {"layers": ["obstacle"]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "EXTRA_PARAMETERS"

    def test_negative_observe_missing_target(self):
        raw = '{"action": "observe", "action_id": "act_001", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "MISSING_TARGET_ID"
