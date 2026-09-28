"""Unit tests for the unified ActionDispatcher and execution constraints.

Verifies:
1. Valid actions parse, normalize defaults, and dispatch to ROS with deterministic UUID.
2. Duplicate action_id NEVER reaches ROS execution.
3. Parameter tampering on retry NEVER reaches ROS execution.
4. Valid retry restores original params from history.
5. Multiple retries under identical visible state fingerprint NEVER reach ROS execution.
6. Exceeding retry budget NEVER reaches ROS execution.
7. Syntax or schema invalid inputs NEVER reach ROS execution.
8. Scoped UUID isolation across episodes and runs.
9. Integration execution of original action and retry with verified parameters and distinct goal IDs.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.action_dispatcher import ActionDispatcher, derive_ros_goal_uuid
from src.action_runtime import EpisodeActionHistoryContext


class TestActionDispatcher(unittest.TestCase):
    def setUp(self):
        self.context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
        self.mock_ros_executor = MagicMock(return_value={"status": "ACCEPTED", "code": 1})
        self.dispatcher = ActionDispatcher(context=self.context, ros_executor=self.mock_ros_executor)

    def test_valid_navigate_dispatch_with_defaults(self):
        action_input = {
            "action": "navigate",
            "action_id": "nav_01",
            "params": {"goal": [-0.5, -0.5, 0.0]},
        }
        res = self.dispatcher.dispatch(action_input, run_id="run_1", episode_id="ep_1")
        self.assertEqual(res["pipeline_status"], "DISPATCHED")
        self.assertTrue(res["ros_dispatched"])
        self.assertEqual(res["normalized_action"]["params"]["frame_id"], "map")
        self.assertEqual(res["normalized_action"]["params"]["timeout_sec"], 60.0)
        expected_uuid = str(derive_ros_goal_uuid("nav_01", run_id="run_1", episode_id="ep_1"))
        self.assertEqual(res["goal_uuid"], expected_uuid)
        self.mock_ros_executor.assert_called_once()

    def test_scoped_uuid_isolation_across_episodes_and_runs(self):
        u1 = derive_ros_goal_uuid("nav_goal", run_id="run_A", episode_id="ep_1")
        u2 = derive_ros_goal_uuid("nav_goal", run_id="run_A", episode_id="ep_2")
        u3 = derive_ros_goal_uuid("nav_goal", run_id="run_B", episode_id="ep_1")
        self.assertNotEqual(u1, u2)
        self.assertNotEqual(u1, u3)
        self.assertNotEqual(u2, u3)

    def test_duplicate_action_id_never_dispatches_to_ros(self):
        act1 = {
            "action": "navigate",
            "action_id": "duplicate_id_test",
            "params": {"goal": [0.0, 0.0, 0.0], "frame_id": "map", "timeout_sec": 60.0},
        }
        res1 = self.dispatcher.dispatch(act1)
        self.assertEqual(res1["pipeline_status"], "DISPATCHED")
        self.mock_ros_executor.assert_called_once()
        self.mock_ros_executor.reset_mock()

        # Second action with identical ID
        act2 = {
            "action": "navigate",
            "action_id": "duplicate_id_test",
            "params": {"goal": [1.0, 1.0, 0.0], "frame_id": "map", "timeout_sec": 60.0},
        }
        res2 = self.dispatcher.dispatch(act2)
        self.assertEqual(res2["pipeline_status"], "FAILED")
        self.assertEqual(res2["failure_stage"], "RUNTIME_HISTORY_CONSTRAINTS")
        self.assertEqual(res2["error_type"], "DUPLICATE_ACTION_ID")
        self.assertFalse(res2["ros_dispatched"])
        self.mock_ros_executor.assert_not_called()

    def test_parameter_tampering_on_retry_never_dispatches(self):
        orig_act = {
            "action": "navigate",
            "action_id": "act_orig",
            "params": {"goal": [1.0, 2.0, 0.0], "frame_id": "map", "timeout_sec": 60.0},
        }
        self.dispatcher.dispatch(orig_act)
        self.mock_ros_executor.reset_mock()

        # Tampered retry specifying different coordinates in replayed_params
        tampered_retry = {
            "action": "retry",
            "action_id": "act_retry_tampered",
            "params": {
                "original_action_id": "act_orig",
                "replayed_params": {"goal": [9.9, 9.9, 0.0], "frame_id": "map", "timeout_sec": 60.0},
            },
        }
        res = self.dispatcher.dispatch(tampered_retry)
        self.assertEqual(res["pipeline_status"], "FAILED")
        self.assertEqual(res["error_type"], "PARAMETER_TAMPERING_DETECTED")
        self.assertFalse(res["ros_dispatched"])
        self.mock_ros_executor.assert_not_called()

    def test_valid_retry_restores_original_params(self):
        orig_act = {
            "action": "navigate",
            "action_id": "act_nav_for_retry",
            "params": {"goal": [2.5, 1.5, 0.0], "frame_id": "map", "timeout_sec": 45.0},
        }
        self.dispatcher.dispatch(orig_act)
        self.mock_ros_executor.reset_mock()

        retry_act = {
            "action": "retry",
            "action_id": "act_retry_valid",
            "params": {"original_action_id": "act_nav_for_retry"},
        }
        res = self.dispatcher.dispatch(retry_act)
        self.assertEqual(res["pipeline_status"], "DISPATCHED")
        self.assertTrue(res["ros_dispatched"])
        self.assertEqual(res["effective_action"]["executable_action"], "navigate")
        self.assertEqual(res["effective_action"]["executable_params"]["goal"], [2.5, 1.5, 0.0])
        self.mock_ros_executor.assert_called_once()

    def test_repeated_retry_under_identical_visible_state_blocked(self):
        orig_act = {
            "action": "navigate",
            "action_id": "act_stuck",
            "params": {"goal": [1.0, 0.0, 0.0], "frame_id": "map", "timeout_sec": 60.0},
        }
        self.dispatcher.dispatch(orig_act)

        visible_state = {"amcl_pose": [-0.5, -0.5, 0.0], "scan_min": 0.25}

        # First retry in this visible state succeeds
        retry_1 = {
            "action": "retry",
            "action_id": "retry_1",
            "params": {"original_action_id": "act_stuck"},
        }
        res1 = self.dispatcher.dispatch(retry_1, visible_state=visible_state)
        self.assertEqual(res1["pipeline_status"], "DISPATCHED")

        # Second retry under IDENTICAL visible state must be blocked
        self.mock_ros_executor.reset_mock()
        retry_2 = {
            "action": "retry",
            "action_id": "retry_2",
            "params": {"original_action_id": "act_stuck"},
        }
        res2 = self.dispatcher.dispatch(retry_2, visible_state=visible_state)
        self.assertEqual(res2["pipeline_status"], "FAILED")
        self.assertEqual(res2["error_type"], "STATE_FINGERPRINT_RETRY_EXHAUSTED")
        self.assertFalse(res2["ros_dispatched"])
        self.mock_ros_executor.assert_not_called()

    def test_exceeding_retry_budget_blocked(self):
        orig_act = {
            "action": "navigate",
            "action_id": "act_base",
            "params": {"goal": [0.0, 0.0, 0.0], "frame_id": "map", "timeout_sec": 60.0},
        }
        self.dispatcher.dispatch(orig_act)

        # Execute 3 retries in 3 distinct states
        for i in range(1, 4):
            r = {
                "action": "retry",
                "action_id": f"retry_num_{i}",
                "params": {"original_action_id": "act_base"},
            }
            res = self.dispatcher.dispatch(r, visible_state={"amcl_pose": [i * 0.5, 0.0, 0.0]})
            self.assertEqual(res["pipeline_status"], "DISPATCHED")

        # 4th retry exceeds budget of 3
        self.mock_ros_executor.reset_mock()
        r4 = {
            "action": "retry",
            "action_id": "retry_num_4",
            "params": {"original_action_id": "act_base"},
        }
        res4 = self.dispatcher.dispatch(r4, visible_state={"amcl_pose": [4.0, 0.0, 0.0]})
        self.assertEqual(res4["pipeline_status"], "FAILED")
        self.assertEqual(res4["error_type"], "RETRY_BUDGET_EXCEEDED")
        self.assertFalse(res4["ros_dispatched"])
        self.mock_ros_executor.assert_not_called()

    def test_syntax_invalid_action_never_dispatches(self):
        invalid_raw = 'Here is the plan: {"action": "navigate", "action_id": "bad", "params": {"goal": [NaN, 0, 0]}}'
        res = self.dispatcher.dispatch(invalid_raw)
        self.assertEqual(res["pipeline_status"], "FAILED")
        self.assertFalse(res["ros_dispatched"])
        self.mock_ros_executor.assert_not_called()

    def test_integration_original_action_and_valid_retry_execution(self):
        """Integration test verifying original action dispatch, failure recording, and retry re-execution."""
        dispatched_goals = []

        def recording_ros_executor(act, goal_uuid):
            dispatched_goals.append((act, str(goal_uuid)))
            return {"status": "ACCEPTED", "ros_goal_id": str(goal_uuid)}

        dispatcher = ActionDispatcher(context=self.context, ros_executor=recording_ros_executor)

        # 1. Original navigate action
        orig_act = {
            "action": "navigate",
            "action_id": "act_initial_nav",
            "params": {"goal": [1.5, -0.5, 1.57]},
        }
        res1 = dispatcher.dispatch(orig_act, run_id="run_test", episode_id="ep_1")
        self.assertEqual(res1["pipeline_status"], "DISPATCHED")
        uuid1 = res1["goal_uuid"]

        # Record terminal failure for original action
        dispatcher.record_terminal_status("act_initial_nav", terminal_status="ABORTED", status_code=6)

        # 2. Dispatch retry action
        retry_act = {
            "action": "retry",
            "action_id": "act_retry_nav",
            "params": {"original_action_id": "act_initial_nav"},
        }
        res2 = dispatcher.dispatch(retry_act, visible_state={"amcl_pose": [-0.5, -0.5, 0.0]}, run_id="run_test", episode_id="ep_1")
        self.assertEqual(res2["pipeline_status"], "DISPATCHED")
        uuid2 = res2["goal_uuid"]

        # 3. Assertions
        # Distinct UUIDs
        self.assertNotEqual(uuid1, uuid2)
        self.assertEqual(len(dispatched_goals), 2)

        # Check executor received restored navigate parameters
        first_dispatched_act, first_uuid = dispatched_goals[0]
        second_dispatched_act, second_uuid = dispatched_goals[1]

        self.assertEqual(first_uuid, uuid1)
        self.assertEqual(first_dispatched_act["action"], "navigate")
        self.assertEqual(first_dispatched_act["params"]["goal"], [1.5, -0.5, 1.57])

        self.assertEqual(second_uuid, uuid2)
        self.assertEqual(second_dispatched_act["action"], "retry")
        self.assertEqual(second_dispatched_act["executable_action"], "navigate")
        self.assertEqual(second_dispatched_act["executable_params"]["goal"], [1.5, -0.5, 1.57])

        # Record terminal success for retry
        dispatcher.record_terminal_status("act_retry_nav", terminal_status="SUCCEEDED", status_code=4)

        # Check history reflects both terminal statuses
        hist = self.context.action_history
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["action_id"], "act_initial_nav")
        self.assertEqual(hist[0]["terminal_status"], "ABORTED")
        self.assertEqual(hist[1]["action_id"], "act_retry_nav")
        self.assertEqual(hist[1]["terminal_status"], "SUCCEEDED")

    def test_observe_routes_to_observer_never_executor(self):
        """Observe action routes exclusively to ros_observer and NEVER triggers ros_executor (NavigateToPose)."""
        mock_observer = MagicMock(return_value={"status": "SUCCESS", "observation": {"pose": [0, 0, 0]}})
        mock_executor = MagicMock(return_value={"status": "ACCEPTED"})
        dispatcher = ActionDispatcher(context=self.context, ros_executor=mock_executor, ros_observer=mock_observer)

        observe_act = {
            "action": "observe",
            "action_id": "act_obs_01",
            "params": {"target_id": "front"},
        }
        res = dispatcher.dispatch(observe_act, run_id="run_test", episode_id="ep_1")
        self.assertEqual(res["pipeline_status"], "DISPATCHED")
        self.assertTrue(res["ros_dispatched"])

        # Observer was called
        mock_observer.assert_called_once_with(res["effective_action"])
        # Executor (which sends NavigateToPose) was NEVER called
        mock_executor.assert_not_called()

        # Terminal status in history
        hist = self.context.action_history
        self.assertEqual(hist[-1]["action_id"], "act_obs_01")
        self.assertEqual(hist[-1]["terminal_status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()

