"""Unit tests for Nav2 Terminal Status & Execution Resolution Module."""
import unittest
from unittest.mock import MagicMock
from src.terminal_resolution import (
    await_nav_goal_terminal_result,
    await_nav_goal_cancel,
    map_goal_status_code_to_name,
)
from src.scoring_evaluator import evaluate_navigation_episode, evaluate_physical_halt


class MockFuture:
    def __init__(self, done=True, result_val=None, exception_val=None):
        self._done = done
        self._result_val = result_val
        self._exception_val = exception_val

    def done(self):
        return self._done

    def result(self):
        if self._exception_val:
            raise self._exception_val
        return self._result_val


class MockResultObject:
    def __init__(self, status_code):
        self.status = status_code


class MockGoalHandle:
    def __init__(self, res_future, cancel_future=None):
        self.res_future = res_future
        self.cancel_future = cancel_future or MockFuture(True, MagicMock(return_code=0))

    def get_result_async(self):
        return self.res_future

    def cancel_goal_async(self):
        return self.cancel_future


class MockRunnerNode:
    def __init__(self, sim_time=10.0):
        self.sim_time = sim_time

    def get_sim_time_sec(self):
        return self.sim_time


class TestTerminalStatusResolution(unittest.TestCase):
    def setUp(self):
        self.node = MockRunnerNode(sim_time=10.0)

    def test_normal_succeeded_within_budget(self):
        fut = MockFuture(done=True, result_val=MockResultObject(4))  # 4 = SUCCEEDED
        gh = MockGoalHandle(fut)
        res = await_nav_goal_terminal_result(self.node, gh, sim_timeout_sec=60.0, wall_watchdog_sec=10.0)
        self.assertEqual(res["execution_outcome"], "BUDGET_SUCCESS")
        self.assertEqual(res["ros_terminal_status"], "SUCCEEDED")
        self.assertFalse(res["deadline_exceeded"])
        self.assertIsNone(res["failure_reason"])

    def test_aborted_within_budget(self):
        fut = MockFuture(done=True, result_val=MockResultObject(6))  # 6 = ABORTED
        gh = MockGoalHandle(fut)
        res = await_nav_goal_terminal_result(self.node, gh, sim_timeout_sec=60.0, wall_watchdog_sec=10.0)
        self.assertEqual(res["execution_outcome"], "EXECUTION_FAILED")
        self.assertEqual(res["ros_terminal_status"], "ABORTED")
        self.assertFalse(res["deadline_exceeded"])
        self.assertEqual(res["failure_reason"], "NAV2_ABORTED")

    def test_canceled_within_budget(self):
        fut = MockFuture(done=True, result_val=MockResultObject(5))  # 5 = CANCELED
        gh = MockGoalHandle(fut)
        res = await_nav_goal_terminal_result(self.node, gh, sim_timeout_sec=60.0, wall_watchdog_sec=10.0)
        self.assertEqual(res["execution_outcome"], "EXECUTION_CANCELED")
        self.assertEqual(res["ros_terminal_status"], "CANCELED")
        self.assertFalse(res["deadline_exceeded"])

    def test_future_result_is_none(self):
        fut = MockFuture(done=True, result_val=None)
        gh = MockGoalHandle(fut)
        res = await_nav_goal_terminal_result(self.node, gh, sim_timeout_sec=60.0, wall_watchdog_sec=10.0)
        self.assertEqual(res["execution_outcome"], "EXECUTION_ERROR")
        self.assertEqual(res["ros_terminal_status"], "ERROR")
        self.assertEqual(res["failure_reason"], "RESULT_IS_NONE")

    def test_future_raises_exception(self):
        fut = MockFuture(done=True, exception_val=RuntimeError("ROS IPC Disconnected"))
        gh = MockGoalHandle(fut)
        res = await_nav_goal_terminal_result(self.node, gh, sim_timeout_sec=60.0, wall_watchdog_sec=10.0)
        self.assertEqual(res["execution_outcome"], "EXECUTION_ERROR")
        self.assertEqual(res["ros_terminal_status"], "ERROR")
        self.assertIn("RESULT_EXCEPTION", res["failure_reason"])

    def test_deadline_exceeded_then_late_succeeded_rejected_by_evaluator(self):
        """Critical test: Sim timeout exceeded, but goal later finished with SUCCEEDED.
        Must be marked BUDGET_DEADLINE_EXCEEDED and rejected by scoring evaluator."""
        # Node starts at 10.0, sim_timeout is 5.0. In spin loop, node clock jumps to 20.0
        class TimeAdvancingNode:
            def __init__(self):
                self.calls = 0

            def get_sim_time_sec(self):
                self.calls += 1
                return 10.0 if self.calls <= 1 else 20.0  # +10s > 5s timeout

        adv_node = TimeAdvancingNode()
        # Not done initially, but after timeout cancel it returns SUCCEEDED (4)
        fut = MockFuture(done=False, result_val=MockResultObject(4))
        
        def mock_spin(node, t_sec):
            # Once cancel is triggered, future completes with SUCCEEDED
            fut._done = True

        gh = MockGoalHandle(fut)
        res = await_nav_goal_terminal_result(
            adv_node, gh, sim_timeout_sec=5.0, wall_watchdog_sec=20.0, spin_once_fn=mock_spin
        )
        self.assertEqual(res["execution_outcome"], "BUDGET_DEADLINE_EXCEEDED")
        self.assertEqual(res["ros_terminal_status"], "SUCCEEDED")
        self.assertTrue(res["deadline_exceeded"])
        self.assertEqual(res["failure_reason"], "SIM_BUDGET_EXCEEDED")

        # Now score this with scoring evaluator
        eval_res = evaluate_navigation_episode(
            target_goal=[-0.5, -0.5, 0.0],
            nav2_status=res["ros_terminal_status"],
            final_gt={"x": -0.5, "y": -0.5, "yaw": 0.0},
            final_amcl={"x": -0.5, "y": -0.5, "yaw": 0.0},
            stability_samples=[
                {"seq": i, "sim_time": 10.0 + i * 0.1, "odom": {"seq": i, "msg_stamp_sec": 10.0 + i * 0.1, "linear_v": 0.0, "angular_v": 0.0}, "gt": {"seq": i, "recv_sim_time_sec": 10.0 + i * 0.1, "x": -0.5, "y": -0.5, "yaw": 0.0}}
                for i in range(25)
            ],
            thresholds={"position_tolerance_m": 0.3, "yaw_tolerance_rad": 0.35, "stability_window_duration_sim_sec": 2.0, "max_sensor_staleness_sim_sec": 0.5},
            execution_outcome=res["execution_outcome"],
            deadline_exceeded=res["deadline_exceeded"],
        )
        self.assertFalse(eval_res["nav2_action_succeeded"])
        self.assertFalse(eval_res["strict_physical_arrival_and_stable"])
        self.assertEqual(eval_res["execution_outcome"], "BUDGET_DEADLINE_EXCEEDED")

    def test_safety_intervention_fails_halt_and_episode(self):
        """Safety intervention flag causes halt verification and episode to fail."""
        eval_res = evaluate_navigation_episode(
            target_goal=[-0.5, -0.5, 0.0],
            nav2_status="SUCCEEDED",
            final_gt={"x": -0.5, "y": -0.5, "yaw": 0.0},
            final_amcl={"x": -0.5, "y": -0.5, "yaw": 0.0},
            stability_samples=[
                {"seq": i, "sim_time": 10.0 + i * 0.1, "odom": {"seq": i, "msg_stamp_sec": 10.0 + i * 0.1, "linear_v": 0.0, "angular_v": 0.0}, "gt": {"seq": i, "recv_sim_time_sec": 10.0 + i * 0.1, "x": -0.5, "y": -0.5, "yaw": 0.0}}
                for i in range(25)
            ],
            thresholds={"position_tolerance_m": 0.3, "yaw_tolerance_rad": 0.35, "stability_window_duration_sim_sec": 2.0, "max_sensor_staleness_sim_sec": 0.5},
            safety_intervention=True,
        )
        self.assertFalse(eval_res["halt_evaluation"]["halt_verified"])
        self.assertTrue(eval_res["halt_evaluation"]["safety_intervention"])
        self.assertFalse(eval_res["strict_physical_arrival_and_stable"])

    def test_cancel_acceptance_and_canceled_status_decoupling(self):
        """Cancel accepted=True but terminal status=SUCCEEDED is NOT cancel_verified."""
        fut = MockFuture(done=True, result_val=MockResultObject(4))  # SUCCEEDED instead of CANCELED
        cancel_fut = MockFuture(done=True, result_val=MagicMock(return_code=0))
        gh = MockGoalHandle(fut, cancel_fut)
        res = await_nav_goal_cancel(self.node, gh)
        self.assertTrue(res["cancel_accepted"])
        self.assertEqual(res["ros_terminal_status"], "SUCCEEDED")
        self.assertFalse(res["cancel_verified"])
        self.assertEqual(res["failure_reason"], "CANCEL_STATUS_NOT_CANCELED")


if __name__ == "__main__":
    unittest.main()
