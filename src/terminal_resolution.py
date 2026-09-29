"""FailMem Nav2 Terminal Status & Execution Resolution Module.

Strictly handles:
1. Distinguishing simulation budget deadline exceeded from ROS terminal status.
2. Independent wall-clock watchdog vs simulation budget.
3. Separation of cancel acceptance from terminal CANCELED status.
4. Future uncompleted, None result, and exception mapping to structured error statuses.
5. Absolute refusal to default missing or late results to SUCCEEDED or CANCELED.
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, Optional, Tuple


def map_goal_status_code_to_name(status_code: Optional[int]) -> str:
    """Map Nav2 Action GoalStatus int code to canonical string."""
    if status_code is None:
        return "UNKNOWN"
    mapping = {
        1: "ACCEPTED",
        2: "EXECUTING",
        3: "CANCELING",
        4: "SUCCEEDED",
        5: "CANCELED",
        6: "ABORTED",
    }
    return mapping.get(status_code, f"UNKNOWN_CODE_{status_code}")


def await_nav_goal_terminal_result(
    node: Any,
    goal_handle: Any,
    sim_timeout_sec: float,
    wall_watchdog_sec: Optional[float] = None,
    logger: Optional[Callable[[str], None]] = None,
    spin_once_fn: Optional[Callable[[Any, float], None]] = None,
    abs_sim_deadline: Optional[float] = None,
) -> Dict[str, Any]:
    """Awaits navigation goal completion with strict simulation deadline, wall watchdog,
    and structured outcome taxonomy.

    Returns:
        Dict containing:
        - execution_outcome: "BUDGET_SUCCESS" | "BUDGET_DEADLINE_EXCEEDED" | "EXECUTION_FAILED" | "EXECUTION_CANCELED" | "EXECUTION_ERROR" | "EXECUTION_UNKNOWN"
        - ros_terminal_status: "SUCCEEDED" | "CANCELED" | "ABORTED" | "UNKNOWN" | "ERROR" | "TIMEOUT"
        - status_code: int or None
        - deadline_exceeded: bool
        - sim_deadline_exceeded: bool
        - wall_watchdog_triggered: bool
        - failure_reason: str or None
        - sim_duration_sec: float
        - wall_duration_sec: float
    """
    if wall_watchdog_sec is None:
        wall_watchdog_sec = max(60.0, sim_timeout_sec * 2.5 + 30.0)

    if goal_handle is None:
        return {
            "execution_outcome": "EXECUTION_ERROR",
            "ros_terminal_status": "ERROR",
            "status_code": None,
            "deadline_exceeded": False,
            "sim_deadline_exceeded": False,
            "wall_watchdog_triggered": False,
            "failure_reason": "GOAL_HANDLE_NONE",
            "sim_duration_sec": 0.0,
            "wall_duration_sec": 0.0,
        }

    def _spin(t_sec: float = 0.04):
        if spin_once_fn:
            spin_once_fn(node, t_sec)
        else:
            import rclpy
            if rclpy.ok():
                rclpy.spin_once(node, timeout_sec=t_sec)

    def _get_sim_time() -> float:
        if hasattr(node, "get_sim_time_sec"):
            return float(node.get_sim_time_sec())
        return time.monotonic()

    get_res_future = goal_handle.get_result_async()
    t_sim_start = _get_sim_time()
    t_wall_start = time.monotonic()

    deadline_exceeded = False
    sim_deadline_exceeded = False
    wall_watchdog_triggered = False

    while not get_res_future.done():
        _spin(0.04)
        now_sim = _get_sim_time()
        sim_elapsed = now_sim - t_sim_start
        wall_elapsed = time.monotonic() - t_wall_start

        if sim_elapsed > sim_timeout_sec or (abs_sim_deadline is not None and now_sim >= abs_sim_deadline):
            deadline_exceeded = True
            sim_deadline_exceeded = True
            if logger:
                logger(f"Simulation time budget exceeded ({sim_elapsed:.2f}s > {sim_timeout_sec:.2f}s, sim_now={now_sim:.2f}s, abs_deadline={abs_sim_deadline}). Requesting cancel...")
            break

        if wall_elapsed > wall_watchdog_sec:
            deadline_exceeded = True
            wall_watchdog_triggered = True
            if logger:
                logger(f"Wall-clock watchdog triggered ({wall_elapsed:.2f}s > {wall_watchdog_sec:.2f}s). Requesting cancel...")
            break

    # If deadline exceeded, request cancel and wait bounded time for settling
    if deadline_exceeded:
        cancel_future = goal_handle.cancel_goal_async()
        t_cancel_start = time.monotonic()
        while not cancel_future.done() and time.monotonic() - t_cancel_start < 5.0:
            _spin(0.04)

        t_res_wait = time.monotonic()
        while not get_res_future.done() and time.monotonic() - t_res_wait < 8.0:
            _spin(0.04)

        sim_duration = _get_sim_time() - t_sim_start
        wall_duration = time.monotonic() - t_wall_start

        ros_status = "UNKNOWN"
        status_code = None
        if get_res_future.done():
            try:
                res = get_res_future.result()
                if res is not None:
                    status_code = int(res.status)
                    ros_status = map_goal_status_code_to_name(status_code)
                else:
                    ros_status = "ERROR"
            except Exception as e:
                ros_status = "ERROR"
        else:
            ros_status = "TIMEOUT"

        failure_reason = "SIM_BUDGET_EXCEEDED" if sim_deadline_exceeded else "WALL_WATCHDOG_TRIGGERED"
        return {
            "execution_outcome": "BUDGET_DEADLINE_EXCEEDED",
            "ros_terminal_status": ros_status,
            "status_code": status_code,
            "deadline_exceeded": True,
            "sim_deadline_exceeded": sim_deadline_exceeded,
            "wall_watchdog_triggered": wall_watchdog_triggered,
            "failure_reason": failure_reason,
            "sim_duration_sec": round(sim_duration, 4),
            "wall_duration_sec": round(wall_duration, 4),
        }

    sim_duration = _get_sim_time() - t_sim_start
    wall_duration = time.monotonic() - t_wall_start

    if get_res_future.done():
        try:
            res = get_res_future.result()
            if res is None:
                return {
                    "execution_outcome": "EXECUTION_ERROR",
                    "ros_terminal_status": "ERROR",
                    "status_code": None,
                    "deadline_exceeded": False,
                    "sim_deadline_exceeded": False,
                    "wall_watchdog_triggered": False,
                    "failure_reason": "RESULT_IS_NONE",
                    "sim_duration_sec": round(sim_duration, 4),
                    "wall_duration_sec": round(wall_duration, 4),
                }

            status_code = int(res.status)
            ros_status = map_goal_status_code_to_name(status_code)

            if ros_status == "SUCCEEDED":
                outcome = "BUDGET_SUCCESS"
                fail_reason = None
            elif ros_status == "CANCELED":
                outcome = "EXECUTION_CANCELED"
                fail_reason = "ACTION_CANCELED"
            elif ros_status == "ABORTED":
                outcome = "EXECUTION_FAILED"
                fail_reason = "NAV2_ABORTED"
            else:
                outcome = "EXECUTION_ERROR"
                fail_reason = f"NAV2_STATUS_{ros_status}"

            return {
                "execution_outcome": outcome,
                "ros_terminal_status": ros_status,
                "status_code": status_code,
                "deadline_exceeded": False,
                "sim_deadline_exceeded": False,
                "wall_watchdog_triggered": False,
                "failure_reason": fail_reason,
                "sim_duration_sec": round(sim_duration, 4),
                "wall_duration_sec": round(wall_duration, 4),
            }
        except Exception as e:
            return {
                "execution_outcome": "EXECUTION_ERROR",
                "ros_terminal_status": "ERROR",
                "status_code": None,
                "deadline_exceeded": False,
                "sim_deadline_exceeded": False,
                "wall_watchdog_triggered": False,
                "failure_reason": f"RESULT_EXCEPTION: {e}",
                "sim_duration_sec": round(sim_duration, 4),
                "wall_duration_sec": round(wall_duration, 4),
            }

    return {
        "execution_outcome": "EXECUTION_UNKNOWN",
        "ros_terminal_status": "UNKNOWN",
        "status_code": None,
        "deadline_exceeded": False,
        "sim_deadline_exceeded": False,
        "wall_watchdog_triggered": False,
        "failure_reason": "FUTURE_NOT_DONE",
        "sim_duration_sec": round(sim_duration, 4),
        "wall_duration_sec": round(wall_duration, 4),
    }


def await_nav_goal_cancel(
    node: Any,
    goal_handle: Any,
    cancel_timeout_sec: float = 6.0,
    result_timeout_sec: float = 8.0,
    logger: Optional[Callable[[str], None]] = None,
    spin_once_fn: Optional[Callable[[Any, float], None]] = None,
) -> Dict[str, Any]:
    """Sends and awaits goal cancellation, strictly decoupling cancel acceptance from CANCELED status.
    """
    if goal_handle is None:
        return {
            "cancel_accepted": False,
            "ros_terminal_status": "ERROR",
            "status_code": None,
            "failure_reason": "GOAL_HANDLE_NONE",
            "cancel_verified": False,
        }

    def _spin(t_sec: float = 0.04):
        if spin_once_fn:
            spin_once_fn(node, t_sec)
        else:
            import rclpy
            if rclpy.ok():
                rclpy.spin_once(node, timeout_sec=t_sec)

    cancel_future = goal_handle.cancel_goal_async()
    t_cancel_start = time.monotonic()
    while not cancel_future.done() and time.monotonic() - t_cancel_start < cancel_timeout_sec:
        _spin(0.04)

    cancel_accepted = False
    if cancel_future.done():
        try:
            cancel_res = cancel_future.result()
            if cancel_res is not None and getattr(cancel_res, "return_code", -1) == 0:
                cancel_accepted = True
        except Exception as e:
            if logger:
                logger(f"Cancel future exception: {e}")

    get_res_fut = goal_handle.get_result_async()
    t0 = time.monotonic()
    while not get_res_fut.done() and time.monotonic() - t0 < result_timeout_sec:
        _spin(0.04)

    if get_res_fut.done():
        try:
            res = get_res_fut.result()
            if res is not None:
                code = int(res.status)
                status_name = map_goal_status_code_to_name(code)
                cancel_verified = (cancel_accepted and status_name == "CANCELED")
                return {
                    "cancel_accepted": cancel_accepted,
                    "ros_terminal_status": status_name,
                    "status_code": code,
                    "failure_reason": None if cancel_verified else ("CANCEL_STATUS_NOT_CANCELED" if cancel_accepted else "CANCEL_REJECTED"),
                    "cancel_verified": cancel_verified,
                }
            else:
                return {
                    "cancel_accepted": cancel_accepted,
                    "ros_terminal_status": "ERROR",
                    "status_code": None,
                    "failure_reason": "RESULT_IS_NONE",
                    "cancel_verified": False,
                }
        except Exception as e:
            return {
                "cancel_accepted": cancel_accepted,
                "ros_terminal_status": "ERROR",
                "status_code": None,
                "failure_reason": f"RESULT_EXCEPTION: {e}",
                "cancel_verified": False,
            }

    return {
        "cancel_accepted": cancel_accepted,
        "ros_terminal_status": "TIMEOUT",
        "status_code": None,
        "failure_reason": "CANCEL_RESULT_TIMEOUT",
        "cancel_verified": False,
    }
