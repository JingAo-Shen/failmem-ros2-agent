"""Unit tests for EpisodeExecutionContext and runtime precondition validation."""
import pytest
from src.action_runtime import EpisodeExecutionContext


class TestActionRuntime:
    """Test suite for runtime history, duplicate ID detection, and retry validation."""

    def test_valid_action_recording_and_retry(self):
        ctx = EpisodeExecutionContext(max_retries=3)
        act1 = {"action": "navigate", "action_id": "nav_001", "params": {"goal": [1.0, 0.0, 0.0], "frame_id": "map"}}
        status, err = ctx.validate_runtime_preconditions(act1)
        assert status == "PASSED"
        assert err is None
        ctx.record_action(act1)

        # Valid retry referencing nav_001 with identical params
        retry_act = {
            "action": "retry",
            "action_id": "retry_001",
            "params": {"original_action_id": "nav_001", "replayed_params": {"goal": [1.0, 0.0, 0.0], "frame_id": "map"}},
        }
        status, err = ctx.validate_runtime_preconditions(retry_act)
        assert status == "PASSED"
        assert err is None
        ctx.record_action(retry_act)

    def test_negative_duplicate_action_id(self):
        ctx = EpisodeExecutionContext()
        act1 = {"action": "clear_costmap", "action_id": "act_dup", "params": {}}
        ctx.record_action(act1)

        act2 = {"action": "inspect_status", "action_id": "act_dup", "params": {}}
        status, err = ctx.validate_runtime_preconditions(act2)
        assert status == "FAILED"
        assert "DUPLICATE_ACTION_ID" in err

    def test_negative_unknown_retry_reference(self):
        ctx = EpisodeExecutionContext()
        retry_act = {
            "action": "retry",
            "action_id": "retry_001",
            "params": {"original_action_id": "non_existent_id"},
        }
        status, err = ctx.validate_runtime_preconditions(retry_act)
        assert status == "FAILED"
        assert "UNKNOWN_RETRY_REFERENCE" in err

    def test_negative_self_referencing_retry(self):
        ctx = EpisodeExecutionContext()
        retry_act = {
            "action": "retry",
            "action_id": "retry_loop",
            "params": {"original_action_id": "retry_loop"},
        }
        status, err = ctx.validate_runtime_preconditions(retry_act)
        assert status == "FAILED"
        assert "SELF_REFERENCING_RETRY" in err

    def test_negative_parameter_tampering(self):
        ctx = EpisodeExecutionContext()
        act1 = {"action": "navigate", "action_id": "nav_001", "params": {"goal": [1.0, 0.0, 0.0], "frame_id": "map"}}
        ctx.record_action(act1)

        # Retry tries to tamper with goal coordinates!
        tampered_retry = {
            "action": "retry",
            "action_id": "retry_tamper",
            "params": {"original_action_id": "nav_001", "replayed_params": {"goal": [9.0, 9.0, 0.0], "frame_id": "map"}},
        }
        status, err = ctx.validate_runtime_preconditions(tampered_retry)
        assert status == "FAILED"
        assert "PARAMETER_TAMPERING_DETECTED" in err

    def test_negative_recursive_retry(self):
        ctx = EpisodeExecutionContext(max_retries=3)
        act1 = {"action": "clear_costmap", "action_id": "clear_01", "params": {}}
        ctx.record_action(act1)

        retry1 = {"action": "retry", "action_id": "retry_01", "params": {"original_action_id": "clear_01"}}
        ctx.record_action(retry1)

        # Cannot retry a retry!
        retry2 = {"action": "retry", "action_id": "retry_02", "params": {"original_action_id": "retry_01"}}
        status, err = ctx.validate_runtime_preconditions(retry2)
        assert status == "FAILED"
        assert "RECURSIVE_RETRY_FORBIDDEN" in err

    def test_negative_retry_budget_exceeded(self):
        ctx = EpisodeExecutionContext(max_retries=2)
        act1 = {"action": "clear_costmap", "action_id": "act_01", "params": {}}
        ctx.record_action(act1)

        # Record 2 retries
        ctx.record_action({"action": "retry", "action_id": "r1", "params": {"original_action_id": "act_01"}})
        ctx.record_action({"action": "retry", "action_id": "r2", "params": {"original_action_id": "act_01"}})

        # 3rd retry exceeds max_retries=2
        r3 = {"action": "retry", "action_id": "r3", "params": {"original_action_id": "act_01"}}
        status, err = ctx.validate_runtime_preconditions(r3)
        assert status == "FAILED"
        assert "RETRY_BUDGET_EXCEEDED" in err
