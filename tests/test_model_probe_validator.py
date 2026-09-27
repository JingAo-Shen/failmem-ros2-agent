"""Unit tests for FailMem Model Probe Action Schema Validator (Problem Lock v0.2)."""
import pytest
from src.schema_validator import parse_and_validate_action, extract_json_block


class TestSchemaValidator:
    """Test suite verifying positive and negative validation cases for action schema."""

    def test_valid_navigate_action(self):
        raw = '{"action": "navigate", "action_id": "act_001", "params": {"goal": [4.0, 3.0, 0.0], "frame_id": "map", "timeout_sec": 60.0}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_executable"] is True
        assert res["action_name"] == "navigate"
        assert res["error_type"] is None

    def test_valid_observe_action(self):
        raw = '```json\n{"action": "observe", "action_id": "act_002", "params": {"target_id": "target_box_01"}}\n```'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_executable"] is True
        assert res["action_name"] == "observe"

    def test_valid_inspect_status(self):
        raw = '{"action": "inspect_status", "action_id": "act_003", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_executable"] is True

    def test_valid_clear_costmap(self):
        raw = '{"action": "clear_costmap", "action_id": "act_004", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_executable"] is True

    def test_valid_retry_action(self):
        raw = '{"action": "retry", "action_id": "act_005", "params": {"original_action_id": "act_001", "replayed_params": {"goal": [4.0, 3.0, 0.0]}}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True
        assert res["action_executable"] is True

    # --- Negative Test Cases ---

    def test_negative_invalid_json_syntax(self):
        raw = '{"action": "navigate", "action_id": "act_001", broken json...'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is False
        assert res["schema_valid"] is False
        assert res["action_executable"] is False
        assert res["error_type"] in ("JSON_SYNTAX_ERROR", "JSON_EXTRACTION_FAILED")

    def test_negative_missing_action_id(self):
        raw = '{"action": "navigate", "params": {"goal": [1.0, 2.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "MISSING_REQUIRED_KEY"

    def test_negative_unsupported_action(self):
        raw = '{"action": "back_up", "action_id": "act_999", "params": {"distance": 0.5}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "UNSUPPORTED_ACTION"

    def test_negative_navigate_missing_goal(self):
        raw = '{"action": "navigate", "action_id": "act_006", "params": {"frame_id": "map"}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "MISSING_NAV_GOAL"

    def test_negative_navigate_wrong_goal_shape(self):
        raw = '{"action": "navigate", "action_id": "act_007", "params": {"goal": [1.0, 2.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "INVALID_NAV_GOAL_SHAPE"

    def test_negative_navigate_wrong_goal_type(self):
        raw = '{"action": "navigate", "action_id": "act_008", "params": {"goal": [1.0, "two", 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "INVALID_NAV_GOAL_TYPE"

    def test_negative_navigate_out_of_bounds(self):
        raw = '{"action": "navigate", "action_id": "act_009", "params": {"goal": [999.0, 0.0, 0.0]}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is True  # structurally valid schema
        assert res["action_executable"] is False  # physically unexecutable bounds
        assert res["error_type"] == "NAV_GOAL_OUT_OF_BOUNDS"

    def test_negative_observe_missing_target_id(self):
        raw = '{"action": "observe", "action_id": "act_010", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "MISSING_TARGET_ID"

    def test_negative_retry_missing_original_id(self):
        raw = '{"action": "retry", "action_id": "act_011", "params": {}}'
        res = parse_and_validate_action(raw)
        assert res["json_parseable"] is True
        assert res["schema_valid"] is False
        assert res["error_type"] == "MISSING_ORIGINAL_ACTION_ID"
