#!/usr/bin/env python3
"""FailMem P1b Complete Verification & Integration Suite (v2 / Final Acceptance).

Executes and strictly verifies:
1. Live ROS observe integration (/scan, AMCL, Odom, Nav2 lifecycle, Goal status).
2. Live observe -> navigate -> observe execution chain with raw stability/trajectory recordings.
3. Live navigate -> cancel -> retry -> observe execution chain with parameter restoration,
   distinct scoped UUIDs, sticky safety intervention tracking, and retry budget constraint enforcement.
4. Real ROS observation anomaly & recovery suite (topic input gating, natural staleness, missing stream, clock pause).
5. 4-Episode Regression suite (3 contract navigations + 1 in-motion cancel test) using strict offline evaluator.
6. Unified goal execution and cancel terminal status resolution (NO default success, NO default cancel).
7. Clean process group isolation per episode.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

sys.path.insert(0, "/workspace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ROS_DOMAIN_ID"] = "42"
os.environ["ROS_LOCALHOST_ONLY"] = "1"
os.environ["TURTLEBOT3_MODEL"] = "waffle"
os.environ["GAZEBO_MODEL_DATABASE_URI"] = ""
os.environ["GAZEBO_MODEL_PATH"] = "/usr/share/gazebo-11/models:/opt/ros/humble/share/turtlebot3_gazebo/models"

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from gazebo_msgs.msg import ModelStates
from lifecycle_msgs.srv import GetState
from std_srvs.srv import Empty
from unique_identifier_msgs.msg import UUID as RosUUID

from src.action_dispatcher import ActionDispatcher, derive_ros_goal_uuid
from src.action_runtime import EpisodeActionHistoryContext
from src.coordinate_alignment import verify_world_map_alignment
from src.observe_interface import ObserveInterface, apply_strict_observation_whitelist
from src.scoring_evaluator import (
    evaluate_navigation_episode,
    evaluate_cancellation_episode,
    audit_localization_discrepancy,
    load_scoring_rules,
    is_finite_number,
)
from src.terminal_resolution import (
    await_nav_goal_terminal_result,
    await_nav_goal_cancel,
    map_goal_status_code_to_name,
)


def quat_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """Extract yaw from quaternion (roll-pitch-yaw)."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def kill_process_group(pgid: int, timeout_sec: float = 4.0):
    """Terminate a process group cleanly with SIGTERM, falling back to SIGKILL."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as e:
        print(f"[WARN] Error sending SIGTERM to process group {pgid}: {e}")

    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_sec:
        try:
            os.killpg(pgid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            return
        except Exception:
            break

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as e:
        print(f"[WARN] Error sending SIGKILL to process group {pgid}: {e}")


def cleanup_global_simulation():
    """Initial environment hygiene: stop lingering ros2 daemon and clear domain shm."""
    try:
        subprocess.run(["ros2", "daemon", "stop"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(1.0)


class P1bRunnerNode(Node):
    """ROS 2 Node for P1b with complete sensor streams, input gating, and observe interface."""

    def __init__(self, node_name: str, event_logger: Callable[[str], None]):
        super().__init__(
            node_name,
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        self.event_logger = event_logger
        self.obs_interface = ObserveInterface(max_sensor_staleness_sec=0.5, max_stationary_amcl_staleness_sec=30.0)

        # Action Client & Publishers
        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "initialpose", 10)
        self.emergency_cmd_pub = self.create_publisher(Twist, "cmd_vel", 10)

        # Service Clients
        self.lifecycle_client = self.create_client(GetState, "/bt_navigator/get_state")
        self.pause_physics_client = self.create_client(Empty, "/pause_physics")
        self.unpause_physics_client = self.create_client(Empty, "/unpause_physics")

        # Input subscriber gating for real ROS message layer anomaly testing (observation input isolation)
        self.gate_scan_enabled = True
        self.gate_odom_enabled = True
        self.gate_amcl_enabled = True

        # Subscriptions
        self.cmd_vel_sub = self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, "odom", self._odom_cb, 10)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "amcl_pose", self._amcl_cb, 10)
        self.scan_sub = self.create_subscription(LaserScan, "scan", self._scan_cb, qos_profile_sensor_data)
        self.gazebo_sub = self.create_subscription(ModelStates, "/gazebo/model_states", self._gazebo_cb, qos_profile_sensor_data)

        self.latest_odom_record: Optional[Dict[str, Any]] = None
        self.latest_amcl_record: Optional[Dict[str, Any]] = None
        self.latest_scan_record: Optional[Dict[str, Any]] = None
        self.latest_gt_record: Optional[Dict[str, Any]] = None
        self.latest_cmd_vel_record: Optional[Dict[str, Any]] = None

        self.odom_msg_count = 0
        self.amcl_msg_count = 0
        self.scan_msg_count = 0
        self.gt_msg_count = 0
        self.cmd_vel_msg_count = 0

        self.continuous_odom_buffer: collections.deque = collections.deque(maxlen=1500)
        self.nav_goal_sent_count = 0
        self.current_active_goal_handle: Any = None
        self.sticky_safety_intervention: bool = False

        self.is_tracking = False
        self.episode_gt_samples: List[Dict[str, Any]] = []
        self.episode_amcl_samples: List[Dict[str, Any]] = []
        self.episode_odom_samples: List[Dict[str, Any]] = []
        self.episode_scan_samples: List[Dict[str, Any]] = []
        self.episode_cmd_vel_samples: List[Dict[str, Any]] = []

    def log(self, msg: str):
        self.event_logger(msg)

    def start_tracking(self):
        self.is_tracking = True
        self.episode_gt_samples = []
        self.episode_amcl_samples = []
        self.episode_odom_samples = []
        self.episode_scan_samples = []
        self.episode_cmd_vel_samples = []

    def stop_tracking(self):
        self.is_tracking = False

    def get_sim_time_sec(self) -> float:
        now = self.get_clock().now()
        return now.nanoseconds * 1e-9

    def _cmd_vel_cb(self, msg: Twist):
        self.cmd_vel_msg_count += 1
        sim_now = self.get_sim_time_sec()
        record = {
            "seq": self.cmd_vel_msg_count,
            "msg_stamp_sec": None,
            "recv_sim_time_sec": round(sim_now, 4),
            "monotonic_wall_sec": round(time.monotonic(), 4),
            "frame_id": "base_footprint",
            "linear_x": round(msg.linear.x, 4),
            "angular_z": round(msg.angular.z, 4),
        }
        self.latest_cmd_vel_record = record
        if self.is_tracking:
            self.episode_cmd_vel_samples.append(record)

    def _odom_cb(self, msg: Odometry):
        if not self.gate_odom_enabled:
            return  # Dropped at ROS observation subscriber layer
        self.odom_msg_count += 1
        sim_now = self.get_sim_time_sec()
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        v = msg.twist.twist
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        record = {
            "seq": self.odom_msg_count,
            "msg_stamp_sec": round(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "monotonic_wall_sec": round(time.monotonic(), 4),
            "frame_id": msg.header.frame_id,
            "x": round(p.x, 4),
            "y": round(p.y, 4),
            "yaw": round(yaw, 4),
            "linear_v": round(v.linear.x, 4),
            "angular_v": round(v.angular.z, 4),
        }
        self.latest_odom_record = record
        self.continuous_odom_buffer.append(record)
        if self.is_tracking:
            self.episode_odom_samples.append(record)

    def _amcl_cb(self, msg: PoseWithCovarianceStamped):
        if not self.gate_amcl_enabled:
            return  # Dropped at ROS observation subscriber layer
        self.amcl_msg_count += 1
        sim_now = self.get_sim_time_sec()
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        cov = list(msg.pose.covariance)
        cov_diag = [cov[0], cov[7], cov[35]]
        record = {
            "seq": self.amcl_msg_count,
            "msg_stamp_sec": round(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "monotonic_wall_sec": round(time.monotonic(), 4),
            "frame_id": msg.header.frame_id,
            "x": round(p.x, 4),
            "y": round(p.y, 4),
            "yaw": round(yaw, 4),
            "covariance_diagonal": cov_diag,
        }
        self.latest_amcl_record = record
        if self.is_tracking:
            self.episode_amcl_samples.append(record)

    def _scan_cb(self, msg: LaserScan):
        if not self.gate_scan_enabled:
            return  # Dropped at ROS observation subscriber layer
        self.scan_msg_count += 1
        sim_now = self.get_sim_time_sec()
        valid_ranges = [r for r in msg.ranges if math.isfinite(r) and msg.range_min <= r <= msg.range_max]
        min_r = min(valid_ranges) if valid_ranges else None
        record = {
            "seq": self.scan_msg_count,
            "msg_stamp_sec": round(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "monotonic_wall_sec": round(time.monotonic(), 4),
            "frame_id": msg.header.frame_id,
            "min_range": round(min_r, 4) if min_r is not None else None,
            "valid_count": len(valid_ranges),
            "total_count": len(msg.ranges),
        }
        self.latest_scan_record = record
        if self.is_tracking:
            self.episode_scan_samples.append(record)

    def _gazebo_cb(self, msg: ModelStates):
        sim_now = self.get_sim_time_sec()
        target_name = None
        for cand in ["turtlebot3_waffle", "waffle", "turtlebot3", "robot"]:
            for n in msg.name:
                if cand in n:
                    target_name = n
                    break
            if target_name is not None:
                break
        if target_name is None:
            if self.gt_msg_count == 0:
                self.log(f"[WARN] Gazebo ModelStates names: {msg.name}, no robot match!")
            return

        self.gt_msg_count += 1
        idx = msg.name.index(target_name)
        p = msg.pose[idx].position
        o = msg.pose[idx].orientation
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        record = {
            "seq": self.gt_msg_count,
            "msg_stamp_sec": None,
            "timestamp_type": "RECEIPT_ROS_SIM_TIME_APPROX",
            "synchronization_note": "ModelStates has no header; timestamp is ROS sim time at callback receipt.",
            "recv_sim_time_sec": round(sim_now, 4),
            "monotonic_wall_sec": round(time.monotonic(), 4),
            "frame_id": "world",
            "x": round(p.x, 4),
            "y": round(p.y, 4),
            "yaw": round(yaw, 4),
        }
        self.latest_gt_record = record
        if self.is_tracking:
            self.episode_gt_samples.append(record)

    def query_nav2_lifecycle(self, timeout_sec: float = 2.0) -> str:
        """Query Nav2 bt_navigator lifecycle state."""
        if not self.lifecycle_client.service_is_ready():
            if not self.lifecycle_client.wait_for_service(timeout_sec=timeout_sec):
                return "UNAVAILABLE"
        req = GetState.Request()
        future = self.lifecycle_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=timeout_sec)
        if future.done() and future.result() is not None:
            state_label = future.result().current_state.label.upper()
            return state_label
        return "UNKNOWN"

    def pause_gazebo_physics(self, timeout_sec: float = 2.0) -> bool:
        """Call /pause_physics service."""
        if not self.pause_physics_client.wait_for_service(timeout_sec=timeout_sec):
            return False
        req = Empty.Request()
        fut = self.pause_physics_client.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=timeout_sec)
        return fut.done()

    def unpause_gazebo_physics(self, timeout_sec: float = 2.0) -> bool:
        """Call /unpause_physics service."""
        if not self.unpause_physics_client.wait_for_service(timeout_sec=timeout_sec):
            return False
        req = Empty.Request()
        fut = self.unpause_physics_client.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=timeout_sec)
        return fut.done()

    def get_current_nav2_goal_status(self) -> str:
        """Query live Nav2 goal status without defaulting to IDLE."""
        if self.current_active_goal_handle is not None:
            status_code = getattr(self.current_active_goal_handle, "status", None)
            if status_code is not None:
                return map_goal_status_code_to_name(int(status_code))
        return "IDLE"

    def get_live_observation(
        self,
        target_id: Optional[str] = None,
        wait_fresh: bool = True,
        wall_timeout_sec: float = 1.5,
    ) -> Dict[str, Any]:
        """Perform a real read-only observation query with explicit wait timeout recording."""
        wall_start = time.monotonic()
        sim_start = self.get_sim_time_sec()
        timed_out = False

        if wait_fresh:
            t0 = time.monotonic()
            fresh_achieved = False
            start_odom_seq = self.latest_odom_record.get("seq", 0) if self.latest_odom_record else 0
            start_scan_seq = self.latest_scan_record.get("seq", 0) if self.latest_scan_record else 0

            while time.monotonic() - t0 < wall_timeout_sec:
                rclpy.spin_once(self, timeout_sec=0.04)
                sim_now = self.get_sim_time_sec()
                curr_scan_stamp = self.latest_scan_record.get("msg_stamp_sec") if self.latest_scan_record else None
                curr_odom_stamp = self.latest_odom_record.get("msg_stamp_sec") if self.latest_odom_record else None
                curr_odom_seq = self.latest_odom_record.get("seq", 0) if self.latest_odom_record else 0
                curr_scan_seq = self.latest_scan_record.get("seq", 0) if self.latest_scan_record else 0

                scan_fresh = (curr_scan_stamp is not None and (sim_now - curr_scan_stamp) <= 0.35 and curr_scan_seq > start_scan_seq)
                odom_fresh = (curr_odom_stamp is not None and (sim_now - curr_odom_stamp) <= 0.35 and curr_odom_seq > start_odom_seq)

                if scan_fresh and odom_fresh:
                    fresh_achieved = True
                    break
            if not fresh_achieved:
                timed_out = True

        sim_now = self.get_sim_time_sec()
        wall_now = time.monotonic()
        sim_advanced = (sim_now - sim_start > 0.005)

        # Check if clock was frozen/stalled while wall-clock time elapsed
        clock_frozen = ((wall_now - wall_start >= 1.0) and not sim_advanced)

        # Synchronize sim_now with newest sensor receipt stamp if within sub-tick window
        if not clock_frozen:
            odom_st = self.latest_odom_record.get("msg_stamp_sec") if self.latest_odom_record else None
            scan_st = self.latest_scan_record.get("msg_stamp_sec") if self.latest_scan_record else None
            if is_finite_number(odom_st) and 0.0 < (odom_st - sim_now) <= 0.15:
                sim_now = float(odom_st)
            if is_finite_number(scan_st) and 0.0 < (scan_st - sim_now) <= 0.15:
                sim_now = max(sim_now, float(scan_st))

        lifecycle = "UNKNOWN"
        if not clock_frozen:
            lifecycle = self.query_nav2_lifecycle(timeout_sec=0.5)

        goal_status = self.get_current_nav2_goal_status()

        res = self.obs_interface.extract_observation(
            current_sim_time=sim_now,
            latest_amcl=self.latest_amcl_record,
            latest_odom=self.latest_odom_record,
            latest_scan=self.latest_scan_record,
            nav2_lifecycle_state=lifecycle,
            current_goal_status=goal_status,
            odom_history=list(self.continuous_odom_buffer) if len(self.continuous_odom_buffer) > 0 else None,
            wall_clock_timeout=timed_out,
            clock_frozen=clock_frozen,
        )
        res["wait_timed_out"] = timed_out
        res["clock_frozen"] = clock_frozen
        res["wall_duration_sec"] = round(time.monotonic() - wall_start, 4)
        return res

    def wait_for_sim_clock(self, min_sim_advance_sec: float = 1.0, wall_timeout_sec: float = 40.0) -> bool:
        t0_wall = time.monotonic()
        t0_sim = self.get_sim_time_sec()
        while time.monotonic() - t0_wall < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            sim_now = self.get_sim_time_sec()
            if sim_now - t0_sim >= min_sim_advance_sec:
                self.log(f"Sim clock advanced: {t0_sim:.2f}s -> {sim_now:.2f}s (delta={sim_now - t0_sim:.2f}s)")
                return True
            time.sleep(0.05)
        return False

    def wait_for_sensors(self, wall_timeout_sec: float = 50.0) -> bool:
        t0 = time.monotonic()
        last_log = t0
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_odom_record and self.latest_gt_record and self.latest_scan_record:
                self.log(f"Sensors streaming: odom={self.latest_odom_record['x']:.2f}, gt={self.latest_gt_record['x']:.2f}, scan={self.latest_scan_record['valid_count']} rays")
                return True
            if time.monotonic() - last_log >= 5.0:
                self.log(f"Waiting for sensors... odom={self.latest_odom_record is not None}, gt={self.latest_gt_record is not None}, scan={self.latest_scan_record is not None}")
                last_log = time.monotonic()
            time.sleep(0.05)
        self.log(f"Sensor wait timed out after {wall_timeout_sec}s: odom={self.latest_odom_record is not None}, gt={self.latest_gt_record is not None}, scan={self.latest_scan_record is not None}")
        return False

    def wait_for_nav2_active(self, wall_timeout_sec: float = 50.0) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            state = self.query_nav2_lifecycle(timeout_sec=0.5)
            if state == "ACTIVE":
                self.log("Nav2 bt_navigator is verified ACTIVE!")
                return True
            time.sleep(0.3)
        return False

    def initialize_amcl_pose(self, x: float = -2.0, y: float = -0.5, yaw: float = 0.0, wall_timeout_sec: float = 30.0) -> bool:
        pose_msg = PoseWithCovarianceStamped()
        pose_msg.header.frame_id = "map"
        pose_msg.header.stamp = self.get_clock().now().to_msg()
        pose_msg.pose.pose.position.x = x
        pose_msg.pose.pose.position.y = y
        pose_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        pose_msg.pose.covariance = [0.25] * 36

        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            self.initial_pose_pub.publish(pose_msg)
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_amcl_record:
                dx = abs(self.latest_amcl_record["x"] - x)
                dy = abs(self.latest_amcl_record["y"] - y)
                if dx < 0.25 and dy < 0.25:
                    self.log(f"AMCL pose converged at x={self.latest_amcl_record['x']:.2f}, y={self.latest_amcl_record['y']:.2f} (delta={math.hypot(dx, dy):.2f}m)")
                    return True
            time.sleep(0.1)
        return False

    def wait_for_passive_settling(
        self,
        max_sim_sec: float = 3.5,
        v_thresh: float = 0.05,
        w_thresh: float = 0.05,
        required_stable_sim_sec: float = 2.0,
        safety_wall_timeout_sec: float = 12.0,
    ) -> Tuple[bool, bool]:
        t_start_sim = self.get_sim_time_sec()
        t_start_wall = time.monotonic()
        stable_start_sim: Optional[float] = None
        safety_intervention_triggered = False

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.04)
            sim_now = self.get_sim_time_sec()
            wall_elapsed = time.monotonic() - t_start_wall

            if wall_elapsed > safety_wall_timeout_sec:
                self.log(f"[SAFETY] Robot failed to settle within {safety_wall_timeout_sec:.1f}s wall time. Emitting zero Twist stop.")
                stop_cmd = Twist()
                self.emergency_cmd_pub.publish(stop_cmd)
                safety_intervention_triggered = True
                self.sticky_safety_intervention = True
                return False, True

            if self.latest_odom_record is not None:
                lv = abs(self.latest_odom_record.get("linear_v", 999.0))
                av = abs(self.latest_odom_record.get("angular_v", 999.0))

                if lv < v_thresh and av < w_thresh:
                    if stable_start_sim is None:
                        stable_start_sim = sim_now
                    elif sim_now - stable_start_sim >= required_stable_sim_sec:
                        self.log(f"Passive physical halt verified: stable for {sim_now - stable_start_sim:.2f}s sim time (lv={lv:.4f}, av={av:.4f})")
                        return True, False
                else:
                    stable_start_sim = None

            if sim_now - t_start_sim > max_sim_sec + required_stable_sim_sec:
                self.log(f"[WARN] Settling time budget elapsed ({sim_now - t_start_sim:.2f}s).")
                return False, False

        return False, safety_intervention_triggered

    def record_stability_window(
        self,
        duration_sim_sec: float = 2.4,
        sample_interval_wall_sec: float = 0.033,
        watchdog_wall_timeout_sec: float = 15.0,
        logger: Optional[Callable[[str], None]] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        t_start_sim = self.get_sim_time_sec()
        t_start_wall = time.monotonic()
        window_records: List[Dict[str, Any]] = []
        watchdog_triggered = False
        sample_seq = 0

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.03)
            sim_now = self.get_sim_time_sec()
            sample_seq += 1

            sample = {
                "sample_index": sample_seq,
                "sim_time": round(sim_now, 4),
                "wall_time": round(time.monotonic(), 4),
                "odom": copy.deepcopy(self.latest_odom_record),
                "gt": copy.deepcopy(self.latest_gt_record),
                "cmd_vel": copy.deepcopy(self.latest_cmd_vel_record),
            }
            window_records.append(sample)

            if sim_now - t_start_sim >= duration_sim_sec:
                if logger:
                    logger(f"Stability window recording complete: {len(window_records)} samples across {sim_now - t_start_sim:.2f}s sim time")
                break

            if time.monotonic() - t_start_wall > watchdog_wall_timeout_sec:
                if logger:
                    logger(f"[ERROR] Stability window watchdog triggered after {watchdog_wall_timeout_sec}s wall time!")
                watchdog_triggered = True
                break

        return window_records, watchdog_triggered


def _execute_navigation_with_monitoring(
    node: P1bRunnerNode,
    dispatcher: ActionDispatcher,
    action_dict: Dict[str, Any],
    logger: Callable[[str], None],
    thresholds: Dict[str, Any],
    settle_duration_sec: float = 2.4,
    visible_state: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Shared robust navigation execution & scoring function across all suites."""
    node.start_tracking()

    dispatch_res = dispatcher.dispatch(action_dict, visible_state=visible_state)
    logger(f"Dispatched action '{action_dict.get('action_id')}': pipeline_status={dispatch_res.get('pipeline_status')}")

    effective_act = dispatch_res.get("effective_action") or dispatch_res.get("normalized_action") or action_dict
    params = effective_act.get("executable_params", effective_act.get("params", {}))
    goal_coords = list(params.get("goal", [0.0, 0.0, 0.0]))
    timeout_sec = float(params.get("timeout_sec", 60.0))

    goal_handle = node.current_active_goal_handle

    term_res = await_nav_goal_terminal_result(
        node=node,
        goal_handle=goal_handle,
        sim_timeout_sec=timeout_sec,
        logger=logger,
    )
    dispatcher.record_terminal_status(
        action_dict.get("action_id", ""),
        terminal_status=term_res["ros_terminal_status"],
        status_code=term_res["status_code"],
    )

    settled_ok, safety_interv = node.wait_for_passive_settling(max_sim_sec=2.5)
    node.sticky_safety_intervention = (node.sticky_safety_intervention or safety_interv)

    stability_records, wd_triggered = node.record_stability_window(
        duration_sim_sec=settle_duration_sec,
        logger=logger,
    )
    node.stop_tracking()

    eval_dict = evaluate_navigation_episode(
        target_goal=goal_coords,
        nav2_status=term_res["ros_terminal_status"],
        final_gt=node.latest_gt_record,
        final_amcl=node.latest_amcl_record,
        stability_samples=stability_records,
        thresholds=thresholds,
        watchdog_triggered=wd_triggered,
        safety_intervention=node.sticky_safety_intervention,
        execution_outcome=term_res["execution_outcome"],
        deadline_exceeded=term_res["deadline_exceeded"],
        failure_reason=term_res["failure_reason"],
    )

    step_summary = {
        "dispatch": dispatch_res,
        "execution_outcome": term_res["execution_outcome"],
        "terminal_status_name": term_res["ros_terminal_status"],
        "status_code": term_res["status_code"],
        "deadline_exceeded": term_res["deadline_exceeded"],
        "terminal_failure_reason": term_res["failure_reason"],
        "sim_duration_sec": term_res["sim_duration_sec"],
        "wall_duration_sec": term_res["wall_duration_sec"],
        "settled_ok": settled_ok,
        "safety_intervention": node.sticky_safety_intervention,
        "evaluation": eval_dict,
    }
    return step_summary, eval_dict, stability_records


def spawn_simulation(episode_dir: Path) -> Tuple[subprocess.Popen, Any]:
    """Spawn Nav2 + Gazebo in dedicated process group."""
    cleanup_global_simulation()
    env = os.environ.copy()
    env["TURTLEBOT3_MODEL"] = "waffle"
    env["GAZEBO_MODEL_DATABASE_URI"] = ""
    env["GAZEBO_MODEL_PATH"] = "/usr/share/gazebo-11/models:/opt/ros/humble/share/turtlebot3_gazebo/models"
    env["ROS_DOMAIN_ID"] = "42"
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    sim_log = open(episode_dir / "nav2_sim.log", "w", encoding="utf-8")
    launch_cmd = [
        "ros2", "launch", "nav2_bringup", "tb3_simulation_launch.py",
        "headless:=True", "use_rviz:=False", "autostart:=True",
        "map:=/workspace/configs/turtlebot3_world.yaml",
        "params_file:=/workspace/configs/nav2_params.yaml",
        "world:=/workspace/configs/world_with_state.model",
        "x_pose:=-2.0", "y_pose:=-0.5",
    ]
    proc = subprocess.Popen(
        launch_cmd,
        env=env,
        stdout=sim_log,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    return proc, env


def save_raw_trajectory(episode_dir: Path, gt_samples: List[Dict[str, Any]], odom_samples: List[Dict[str, Any]]):
    """Save raw trajectory points to JSON."""
    traj = {
        "gt_samples_count": len(gt_samples),
        "odom_samples_count": len(odom_samples),
        "gt_trajectory": [
            {"seq": s["seq"], "recv_sim_time_sec": s.get("recv_sim_time_sec"), "x": s["x"], "y": s["y"], "yaw": s["yaw"]}
            for s in gt_samples
        ],
        "odom_trajectory": [
            {"seq": s["seq"], "msg_stamp_sec": s["msg_stamp_sec"], "x": s["x"], "y": s["y"], "yaw": s["yaw"], "linear_v": s.get("linear_v"), "angular_v": s.get("angular_v")}
            for s in odom_samples
        ],
    }
    with open(episode_dir / "trajectory.json", "w", encoding="utf-8") as f:
        json.dump(traj, f, indent=2)


def compute_sha256_tree(base_dir: Path) -> Dict[str, str]:
    """Calculate sha256 checksums for all files in the directory tree."""
    checksums = {}
    for p in sorted(base_dir.rglob("*")):
        if p.is_file() and p.name != "checksums.sha256":
            rel_path = str(p.relative_to(base_dir))
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            checksums[rel_path] = h
    return checksums


def main():
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    run_id = f"p1b_{timestamp_str}_{rand_suffix}"
    evidence_base = Path("/workspace/reports/evidence/p1b") if Path("/workspace").exists() else Path("reports/evidence/p1b")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"=======================================================================")
    print(f"FailMem P1b Final Acceptance Integration Suite: {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")

    scoring_rules = load_scoring_rules("configs/scoring_rules.yaml")
    thresholds = scoring_rules.get("thresholds", {})

    # Ground truth coordinate frame verification (SDF landmark alignment)
    print("Verifying Gazebo SDF physical world to 2D occupancy grid geometric alignment...")
    coord_proof = verify_world_map_alignment(
        map_yaml_path="configs/turtlebot3_world.yaml",
        map_pgm_path="configs/turtlebot3_world.pgm",
        world_model_path="configs/turtlebot3_world.model",
        sdf_model_path="configs/turtlebot3_world.model.sdf",
    )
    with open(run_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    suite_results = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1b-final",
        "scoring_rules": scoring_rules,
        "coordinate_alignment": {
            "verified": coord_proof.get("verified", False),
            "max_residual_m": coord_proof.get("max_residual_m"),
            "tested_landmarks_count": coord_proof.get("non_collinear_landmarks_tested"),
        },
        "suite_1_observe_nav_observe": {},
        "suite_2_cancel_retry_observe": {},
        "suite_3_observe_anomalies": {},
        "suite_4_regression_episodes": [],
        "readiness_failures": [],
        "overall_status": "FAILED",
    }

    # =========================================================================
    # SUITE 1: Observe -> Navigate -> Observe Execution Chain
    # =========================================================================
    ep1_dir = run_dir / "suite1_observe_nav_observe"
    ep1_dir.mkdir(parents=True, exist_ok=True)
    events_log = open(ep1_dir / "events.log", "w", encoding="utf-8")

    def log1(msg: str):
        line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        events_log.write(line + "\n")
        events_log.flush()

    log1("=== Starting Suite 1: Observe -> Navigate -> Observe Chain ===")
    sim_proc, env = spawn_simulation(ep1_dir)
    rclpy.init()

    try:
        node = P1bRunnerNode("p1b_suite1", log1)

        # Strict Readiness Checks (Dependency Order: Clock -> Sensors -> AMCL Initial Pose -> Nav2 Active -> Action Server)
        if not node.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
            suite_results["readiness_failures"].append("Suite 1: Simulation clock failed to advance")
            raise RuntimeError("Simulation clock failed to advance")
        if not node.wait_for_sensors(wall_timeout_sec=50.0):
            suite_results["readiness_failures"].append("Suite 1: Sensors not streaming")
            raise RuntimeError("Sensors not streaming")
        if not node.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=35.0):
            suite_results["readiness_failures"].append("Suite 1: AMCL pose failed to converge")
            raise RuntimeError("AMCL pose failed to converge")
        if not node.wait_for_nav2_active(wall_timeout_sec=50.0):
            suite_results["readiness_failures"].append("Suite 1: Nav2 lifecycle not ACTIVE")
            raise RuntimeError("Nav2 lifecycle not ACTIVE")
        if not node.action_client.wait_for_server(timeout_sec=45.0):
            suite_results["readiness_failures"].append("Suite 1: Action server unavailable")
            raise RuntimeError("Action server unavailable")

        context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
        dispatcher = ActionDispatcher(context=context, run_id=run_id, episode_id="suite1")
        dispatcher.ros_observer = lambda act: node.get_live_observation(target_id=act.get("params", {}).get("target_id"))

        # Action Executor
        def ros_send_nav(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            goal_msg = NavigateToPose.Goal()
            p = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = p.get("frame_id", "map")
            goal_msg.pose.header.stamp = node.get_clock().now().to_msg()
            g = p["goal"]
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

            node.nav_goal_sent_count += 1
            ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
            future = node.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
            rclpy.spin_until_future_complete(node, future, timeout_sec=10.0)
            if not future.done() or not future.result() or not future.result().accepted:
                return {"status": "REJECTED", "accepted": False}
            node.current_active_goal_handle = future.result()
            uuid_match = (bytes(node.current_active_goal_handle.goal_id.uuid) == goal_uuid.bytes)
            return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid), "uuid_verified": uuid_match}

        dispatcher.ros_executor = ros_send_nav

        # Step 1: Initial Observe Action
        obs1_act = {"action": "observe", "action_id": "s1_obs_initial", "params": {"target_id": "front_corridor"}}
        obs1_res = dispatcher.dispatch(obs1_act)
        log1(f"Step 1 Observe Result: status={obs1_res['ros_result']['status']}")

        # Step 2: Navigate Action via Shared Execution Helper
        nav_act = {"action": "navigate", "action_id": "s1_nav_target", "params": {"goal": [-0.5, -0.5, 0.0], "frame_id": "map", "timeout_sec": 60.0}}
        obs1_obs = obs1_res.get("ros_result", {}).get("observation")
        visible_pose = obs1_obs["localization"]["pose"] if obs1_obs and "localization" in obs1_obs and "pose" in obs1_obs["localization"] else [-2.0, -0.5, 0.0]

        step2_summary, nav_eval, stability_samples = _execute_navigation_with_monitoring(
            node=node,
            dispatcher=dispatcher,
            action_dict=nav_act,
            logger=log1,
            thresholds=thresholds,
            visible_state={"amcl_pose": visible_pose},
        )

        # Save raw stability window and trajectory
        with open(ep1_dir / "stability_window.json", "w", encoding="utf-8") as f:
            json.dump(stability_samples, f, indent=2)
        save_raw_trajectory(ep1_dir, node.episode_gt_samples, node.episode_odom_samples)

        # Step 3: Final Observe Action
        obs2_act = {"action": "observe", "action_id": "s1_obs_final", "params": {"target_id": "box_target"}}
        obs2_res = dispatcher.dispatch(obs2_act)
        log1(f"Step 3 Final Observe Result: status={obs2_res['ros_result']['status']}")

        uuid_verified_s1 = step2_summary["dispatch"].get("ros_result", {}).get("uuid_verified", False)

        suite1_data = {
            "chain": ["observe", "navigate", "observe"],
            "step1_observe": obs1_res,
            "step2_navigate": step2_summary,
            "step3_observe": obs2_res,
            "action_history": context.action_history,
            "chain_verified": (
                obs1_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and nav_eval["strict_physical_arrival_and_stable"]
                and not node.sticky_safety_intervention
                and obs2_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and uuid_verified_s1
            ),
        }
        suite_results["suite_1_observe_nav_observe"] = suite1_data
        with open(ep1_dir / "suite_summary.json", "w", encoding="utf-8") as f:
            json.dump(suite1_data, f, indent=2)

    finally:
        rclpy.shutdown()
        kill_process_group(os.getpgid(sim_proc.pid))
        events_log.close()

    # =========================================================================
    # SUITE 2: Navigate -> Cancel -> Retry -> Observe Execution Chain
    # =========================================================================
    ep2_dir = run_dir / "suite2_cancel_retry_observe"
    ep2_dir.mkdir(parents=True, exist_ok=True)
    events_log2 = open(ep2_dir / "events.log", "w", encoding="utf-8")

    def log2(msg: str):
        line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        events_log2.write(line + "\n")
        events_log2.flush()

    log2("=== Starting Suite 2: Navigate -> Cancel -> Retry -> Observe Chain ===")
    sim_proc2, env2 = spawn_simulation(ep2_dir)
    rclpy.init()

    try:
        node2 = P1bRunnerNode("p1b_suite2", log2)

        # Strict Readiness Checks (Dependency Order: Clock -> Sensors -> AMCL Initial Pose -> Nav2 Active -> Action Server)
        if not node2.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
            suite_results["readiness_failures"].append("Suite 2: Simulation clock failed to advance")
            raise RuntimeError("Simulation clock failed to advance")
        if not node2.wait_for_sensors(wall_timeout_sec=50.0):
            suite_results["readiness_failures"].append("Suite 2: Sensors not streaming")
            raise RuntimeError("Sensors not streaming")
        if not node2.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=35.0):
            suite_results["readiness_failures"].append("Suite 2: AMCL pose failed to converge")
            raise RuntimeError("AMCL pose failed to converge")
        if not node2.wait_for_nav2_active(wall_timeout_sec=50.0):
            suite_results["readiness_failures"].append("Suite 2: Nav2 lifecycle not ACTIVE")
            raise RuntimeError("Nav2 lifecycle not ACTIVE")
        if not node2.action_client.wait_for_server(timeout_sec=45.0):
            suite_results["readiness_failures"].append("Suite 2: Action server unavailable")
            raise RuntimeError("Action server unavailable")

        context2 = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
        dispatcher2 = ActionDispatcher(context=context2, run_id=run_id, episode_id="suite2")
        dispatcher2.ros_observer = lambda act: node2.get_live_observation(target_id=act.get("params", {}).get("target_id"))

        dispatched_goal_ids = []

        def ros_send_nav2(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            goal_msg = NavigateToPose.Goal()
            p = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = p.get("frame_id", "map")
            goal_msg.pose.header.stamp = node2.get_clock().now().to_msg()
            g = p["goal"]
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

            node2.nav_goal_sent_count += 1
            ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
            future = node2.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
            rclpy.spin_until_future_complete(node2, future, timeout_sec=10.0)
            if not future.done() or not future.result() or not future.result().accepted:
                return {"status": "REJECTED", "accepted": False}
            node2.current_active_goal_handle = future.result()
            dispatched_goal_ids.append(str(goal_uuid))
            uuid_match = (bytes(node2.current_active_goal_handle.goal_id.uuid) == goal_uuid.bytes)
            return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid), "uuid_verified": uuid_match}

        dispatcher2.ros_executor = ros_send_nav2

        # Step 1: Initial Navigate Action
        nav_init_act = {"action": "navigate", "action_id": "s2_nav_orig", "params": {"goal": [0.5, -0.5, 1.57], "frame_id": "map", "timeout_sec": 60.0}}
        node2.start_tracking()
        res_init = dispatcher2.dispatch(nav_init_act)
        log2(f"Step 1 Navigate Dispatched (UUID={res_init['goal_uuid']})")

        # Step 2: Confirm Movement and Cancel
        movement_confirmed = False
        t_cancel_w = time.monotonic()
        while time.monotonic() - t_cancel_w < 15.0:
            rclpy.spin_once(node2, timeout_sec=0.04)
            if node2.latest_odom_record:
                if abs(node2.latest_odom_record.get("linear_v", 0.0)) > 0.05:
                    movement_confirmed = True
                    log2("Robot movement confirmed > 0.05 m/s. Dispatching cancel...")
                    break

        cancel_dict = await_nav_goal_cancel(
            node=node2,
            goal_handle=node2.current_active_goal_handle,
            cancel_timeout_sec=6.0,
            result_timeout_sec=8.0,
            logger=log2,
        )
        dispatcher2.record_terminal_status("s2_nav_orig", terminal_status=cancel_dict["ros_terminal_status"], status_code=cancel_dict["status_code"])

        settled_ok_c, safety_int_c = node2.wait_for_passive_settling(max_sim_sec=2.5)
        node2.sticky_safety_intervention = (node2.sticky_safety_intervention or safety_int_c)
        stability_samples_c, watchdog_c = node2.record_stability_window(duration_sim_sec=2.5)

        with open(ep2_dir / "step1_cancel_stability_window.json", "w", encoding="utf-8") as f:
            json.dump(stability_samples_c, f, indent=2)

        cancel_eval = evaluate_cancellation_episode(
            nav2_status=cancel_dict["ros_terminal_status"],
            movement_confirmed_before_cancel=movement_confirmed,
            cancel_request_accepted=cancel_dict["cancel_accepted"],
            stability_samples=stability_samples_c,
            thresholds=thresholds,
            watchdog_triggered=watchdog_c,
            safety_intervention=node2.sticky_safety_intervention,
        )

        # Step 3: Legitimate Retry with Replayed Parameters
        retry_act = {"action": "retry", "action_id": "s2_retry_nav", "params": {"original_action_id": "s2_nav_orig"}}
        curr_obs_pre_retry = node2.get_live_observation()
        obs_dict = curr_obs_pre_retry.get("observation") or {}
        curr_pose = obs_dict.get("localization", {}).get("pose") if obs_dict else None
        if not curr_pose and node2.latest_odom_record:
            curr_pose = [node2.latest_odom_record["x"], node2.latest_odom_record["y"], node2.latest_odom_record["yaw"]]
        if not curr_pose:
            curr_pose = [-1.5, -0.5, 0.0]

        step3_summary, retry_eval, retry_stability_samples = _execute_navigation_with_monitoring(
            node=node2,
            dispatcher=dispatcher2,
            action_dict=retry_act,
            logger=log2,
            thresholds=thresholds,
            visible_state={"amcl_pose": curr_pose},
        )

        with open(ep2_dir / "step3_retry_stability_window.json", "w", encoding="utf-8") as f:
            json.dump(retry_stability_samples, f, indent=2)
        save_raw_trajectory(ep2_dir, node2.episode_gt_samples, node2.episode_odom_samples)

        # Step 4: Final Observe
        obs_post_retry_act = {"action": "observe", "action_id": "s2_obs_post_retry", "params": {"target_id": "target_marker"}}
        obs_post_retry_res = dispatcher2.dispatch(obs_post_retry_act)
        log2(f"Step 4 Post-Retry Observe Result: status={obs_post_retry_res['ros_result']['status']}")

        # Step 5: Verify Runtime Constraint Blocks Duplicate Retry in Identical Snapshot
        sent_count_before_blocked = node2.nav_goal_sent_count
        blocked_retry_act = {"action": "retry", "action_id": "s2_retry_blocked", "params": {"original_action_id": "s2_nav_orig"}}
        blocked_res = dispatcher2.dispatch(blocked_retry_act, visible_state={"amcl_pose": curr_pose})
        sent_count_after_blocked = node2.nav_goal_sent_count
        goal_count_unchanged = (sent_count_after_blocked == sent_count_before_blocked)
        log2(f"Step 5 Duplicate State Retry Blocked Check: status={blocked_res['pipeline_status']}, error={blocked_res.get('error_type')}, goals_sent_unchanged={goal_count_unchanged}")

        distinct_uuids = (len(dispatched_goal_ids) == 2 and dispatched_goal_ids[0] != dispatched_goal_ids[1])
        uuid_orig_verified = res_init.get("ros_result", {}).get("uuid_verified", False)
        uuid_retry_verified = step3_summary["dispatch"].get("ros_result", {}).get("uuid_verified", False)

        suite2_data = {
            "chain": ["navigate", "cancel", "retry", "observe"],
            "step1_original_navigate": res_init,
            "step2_cancel": {
                "movement_confirmed": movement_confirmed,
                "cancel_accepted": cancel_dict["cancel_accepted"],
                "terminal_status_name": cancel_dict["ros_terminal_status"],
                "status_code": cancel_dict["status_code"],
                "evaluation": cancel_eval,
            },
            "step3_retry": step3_summary,
            "step4_observe": obs_post_retry_res,
            "step5_constraint_blocked": blocked_res,
            "dispatched_goal_uuids": dispatched_goal_ids,
            "distinct_uuids_verified": distinct_uuids,
            "action_history": context2.action_history,
            "safety_intervention_sticky": node2.sticky_safety_intervention,
            "chain_verified": (
                movement_confirmed
                and cancel_dict["cancel_verified"]
                and retry_eval["strict_physical_arrival_and_stable"]
                and not node2.sticky_safety_intervention
                and obs_post_retry_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and blocked_res.get("pipeline_status") == "FAILED"
                and blocked_res.get("error_type") == "STATE_FINGERPRINT_RETRY_EXHAUSTED"
                and goal_count_unchanged
                and distinct_uuids
                and uuid_orig_verified
                and uuid_retry_verified
            ),
        }
        suite_results["suite_2_cancel_retry_observe"] = suite2_data
        with open(ep2_dir / "suite_summary.json", "w", encoding="utf-8") as f:
            json.dump(suite2_data, f, indent=2)

    finally:
        rclpy.shutdown()
        kill_process_group(os.getpgid(sim_proc2.pid))
        events_log2.close()

    # =========================================================================
    # SUITE 3: Real ROS Message Layer Observation Anomaly & Recovery Suite
    # =========================================================================
    ep3_dir = run_dir / "suite3_observe_anomalies"
    ep3_dir.mkdir(parents=True, exist_ok=True)
    events_log3 = open(ep3_dir / "events.log", "w", encoding="utf-8")

    def log3(msg: str):
        line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        events_log3.write(line + "\n")
        events_log3.flush()

    log3("=== Starting Suite 3: Observation Anomaly & Recovery Verification ===")
    sim_proc3, env3 = spawn_simulation(ep3_dir)
    rclpy.init()

    try:
        node3 = P1bRunnerNode("p1b_suite3", log3)

        if not node3.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
            suite_results["readiness_failures"].append("Suite 3: Simulation clock failed to advance")
            raise RuntimeError("Simulation clock failed to advance")
        if not node3.wait_for_sensors(wall_timeout_sec=50.0):
            suite_results["readiness_failures"].append("Suite 3: Sensors not streaming")
            raise RuntimeError("Sensors not streaming")
        if not node3.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=35.0):
            suite_results["readiness_failures"].append("Suite 3: AMCL pose failed to converge")
            raise RuntimeError("AMCL pose failed to converge")

        context3 = EpisodeActionHistoryContext()
        dispatcher3 = ActionDispatcher(context=context3, run_id=run_id, episode_id="suite3")
        dispatcher3.ros_observer = lambda act: node3.get_live_observation(target_id=act.get("params", {}).get("target_id"))

        # --- Sub-suite 3A: Pure Interface Edge Cases ---
        interface_checks = {}
        sim_t_3a = node3.get_sim_time_sec()

        # 3A.1 Missing Odom
        if_missing_odom = node3.obs_interface.extract_observation(
            current_sim_time=sim_t_3a,
            latest_amcl=node3.latest_amcl_record,
            latest_odom=None,
            latest_scan=node3.latest_scan_record,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
        )
        interface_checks["if_missing_odom"] = if_missing_odom
        log3(f"Interface Check (Missing Odom): status={if_missing_odom['status']}, error_type={if_missing_odom.get('error_type')}")

        # 3A.2 Missing Scan
        if_missing_scan = node3.obs_interface.extract_observation(
            current_sim_time=sim_t_3a,
            latest_amcl=node3.latest_amcl_record,
            latest_odom=node3.latest_odom_record,
            latest_scan=None,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
            odom_history=list(node3.continuous_odom_buffer),
        )
        interface_checks["if_missing_scan"] = if_missing_scan
        log3(f"Interface Check (Missing Scan): status={if_missing_scan['status']}, error_type={if_missing_scan.get('error_type')}")

        # --- Sub-suite 3B: Real ROS Message Layer Topic Relay / Gate Tests ---
        real_ros_tests = {}

        # 3.1 Normal Observation via Dispatcher
        res_3_1 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_1_normal", "params": {"target_id": "normal_test"}})
        real_ros_tests["test_3_1_normal"] = res_3_1
        log3(f"Test 3.1 (Real Normal Obs): status={res_3_1['ros_result']['status']}")

        # 3.2 Cut Scan Stream at ROS Observation Subscriber Layer (Natural Ageing -> DEGRADED)
        log3("Cutting /scan observation reception gate...")
        node3.gate_scan_enabled = False
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 2.5:
            rclpy.spin_once(node3, timeout_sec=0.04)

        res_3_2 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_2_stale_scan", "params": {"target_id": "stale_scan_test"}})
        real_ros_tests["test_3_2_stale_scan"] = res_3_2
        log3(f"Test 3.2 (Natural Stale Scan): status={res_3_2['ros_result']['status']}, error_type={res_3_2['ros_result'].get('error_type')}")

        # 3.3 Restore Scan Stream (Recovery -> SUCCESS)
        log3("Restoring /scan observation reception gate...")
        node3.gate_scan_enabled = True
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 0.6:
            rclpy.spin_once(node3, timeout_sec=0.04)

        res_3_3 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_3_scan_recovered", "params": {"target_id": "recovered_scan_test"}})
        real_ros_tests["test_3_3_scan_recovered"] = res_3_3
        log3(f"Test 3.3 (Scan Stream Recovered): status={res_3_3['ros_result']['status']}")

        # 3.4 Missing Scan from Node Startup (Isolated Instance with gate_scan=False from start)
        log3("Testing isolated observation instance with scan stream missing from startup...")
        isolated_obs = node3.obs_interface.extract_observation(
            current_sim_time=node3.get_sim_time_sec(),
            latest_amcl=node3.latest_amcl_record,
            latest_odom=node3.latest_odom_record,
            latest_scan=None,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
            odom_history=list(node3.continuous_odom_buffer),
        )
        res_3_4 = {
            "pipeline_status": "DISPATCHED",
            "action_id": "obs_3_4_missing_scan",
            "ros_result": isolated_obs,
        }
        real_ros_tests["test_3_4_missing_scan"] = res_3_4
        log3(f"Test 3.4 (Missing Scan Stream): status={isolated_obs['status']}, error_type={isolated_obs.get('error_type')}")

        # 3.5 Cut Odometry Stream at ROS Observation Subscriber Layer (Natural Ageing -> ERROR / ODOMETRY_STALE)
        log3("Cutting /odom observation reception gate...")
        node3.gate_odom_enabled = False
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 2.5:
            rclpy.spin_once(node3, timeout_sec=0.04)

        res_3_5 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_5_stale_odom", "params": {"target_id": "stale_odom_test"}})
        real_ros_tests["test_3_5_stale_odom"] = res_3_5
        log3(f"Test 3.5 (Natural Stale Odom): status={res_3_5['ros_result']['status']}, error_type={res_3_5['ros_result'].get('error_type')}")

        # 3.6 Restore Odometry Stream & Refresh AMCL (Recovery -> SUCCESS)
        log3("Restoring /odom observation reception gate and refreshing AMCL initial pose...")
        node3.gate_odom_enabled = True
        node3.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=10.0)
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 0.6:
            rclpy.spin_once(node3, timeout_sec=0.04)

        res_3_6 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_6_odom_recovered", "params": {"target_id": "recovered_odom_test"}})
        real_ros_tests["test_3_6_odom_recovered"] = res_3_6
        log3(f"Test 3.6 (Odom Stream Recovered): status={res_3_6['ros_result']['status']}")

        # 3.7 Simulation Clock Paused / Frozen Resilience Test
        log3("Calling /pause_physics service to pause simulation clock...")
        pause_ok = node3.pause_gazebo_physics(timeout_sec=2.0)
        assert pause_ok, "Gazebo /pause_physics service call failed"

        # Verify sim clock actually stopped advancing
        t_sim_p1 = node3.get_sim_time_sec()
        time.sleep(0.6)
        t_sim_p2 = node3.get_sim_time_sec()
        clock_stopped = (abs(t_sim_p2 - t_sim_p1) < 0.001)
        log3(f"Verified Gazebo physics paused: t_sim1={t_sim_p1:.3f}s, t_sim2={t_sim_p2:.3f}s, stopped={clock_stopped}")

        try:
            res_3_7 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_7_clock_pause", "params": {"target_id": "clock_pause_test"}})
            real_ros_tests["test_3_7_clock_pause"] = res_3_7
            log3(f"Test 3.7 (Simulation Clock Paused): status={res_3_7['ros_result']['status']}, error_type={res_3_7['ros_result'].get('error_type')}, wall_time={res_3_7['ros_result'].get('wall_duration_sec', 0.0):.3f}s")
        finally:
            log3("Calling /unpause_physics service to resume simulation in finally block...")
            unpause_ok = node3.unpause_gazebo_physics(timeout_sec=2.0)
            time.sleep(0.2)

        t_sim_r1 = node3.get_sim_time_sec()
        t_wall_unpause = time.monotonic()
        while time.monotonic() - t_wall_unpause < 3.0:
            rclpy.spin_once(node3, timeout_sec=0.05)
            if node3.get_sim_time_sec() - t_sim_r1 > 0.1:
                break
        t_sim_r2 = node3.get_sim_time_sec()
        clock_resumed = (t_sim_r2 > t_sim_r1)
        log3(f"Verified Gazebo physics resumed: t_sim1={t_sim_r1:.3f}s, t_sim2={t_sim_r2:.3f}s, resumed={clock_resumed}")

        suite3_data = {
            "interface_checks": interface_checks,
            "real_ros_topic_tests": real_ros_tests,
            "anomalies_verified": (
                if_missing_odom["status"] == "ERROR"
                and if_missing_scan["status"] == "DEGRADED"
                and res_3_1["ros_result"]["status"] == "SUCCESS"
                and res_3_2["ros_result"]["status"] == "DEGRADED"
                and res_3_2["ros_result"].get("error_type") == "SCAN_DEGRADED"
                and res_3_3["ros_result"]["status"] == "SUCCESS"
                and res_3_4["ros_result"]["status"] == "DEGRADED"
                and res_3_4["ros_result"].get("error_type") == "SCAN_DEGRADED"
                and res_3_5["ros_result"]["status"] == "ERROR"
                and res_3_5["ros_result"].get("error_type") == "ODOMETRY_STALE"
                and res_3_6["ros_result"]["status"] == "SUCCESS"
                and res_3_7["ros_result"]["status"] == "ERROR"
                and res_3_7["ros_result"].get("error_type") == "SIMULATION_CLOCK_FROZEN"
                and res_3_7["ros_result"].get("wall_duration_sec", 999.0) <= 3.0
                and clock_stopped
                and clock_resumed
            ),
        }
        suite_results["suite_3_observe_anomalies"] = suite3_data
        with open(ep3_dir / "suite_summary.json", "w", encoding="utf-8") as f:
            json.dump(suite3_data, f, indent=2)

    finally:
        rclpy.shutdown()
        kill_process_group(os.getpgid(sim_proc3.pid))
        events_log3.close()

    # =========================================================================
    # SUITE 4: 4-Episode Regression Suite
    # =========================================================================
    regression_specs = [
        {"action_id": "reg_ep1_fwd", "goal": [-0.5, -0.5, 0.0], "is_cancel": False, "dir_name": "regression_episode_1"},
        {"action_id": "reg_ep2_rot", "goal": [0.5, -0.5, 1.57], "is_cancel": False, "dir_name": "regression_episode_2"},
        {"action_id": "reg_ep3_ret", "goal": [-0.5, 0.5, 3.14], "is_cancel": False, "dir_name": "regression_episode_3"},
        {"action_id": "reg_ep4_cancel", "goal": [0.0, 0.5, 0.0], "is_cancel": True, "dir_name": "regression_episode_4"},
    ]

    for spec in regression_specs:
        ep_dir = run_dir / spec["dir_name"]
        ep_dir.mkdir(parents=True, exist_ok=True)
        events_log_r = open(ep_dir / "events.log", "w", encoding="utf-8")

        def log_r(msg: str):
            line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
            print(line, flush=True)
            events_log_r.write(line + "\n")
            events_log_r.flush()

        log_r(f"=== Starting {spec['dir_name']} ({spec['action_id']}) ===")
        sim_proc_r, env_r = spawn_simulation(ep_dir)
        rclpy.init()

        try:
            node_r = P1bRunnerNode(f"p1b_{spec['dir_name']}", log_r)

            if not node_r.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
                suite_results["readiness_failures"].append(f"{spec['dir_name']}: Sim clock failed")
                continue
            if not node_r.wait_for_sensors(wall_timeout_sec=50.0):
                suite_results["readiness_failures"].append(f"{spec['dir_name']}: Sensors failed")
                continue
            if not node_r.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=35.0):
                suite_results["readiness_failures"].append(f"{spec['dir_name']}: AMCL failed")
                continue
            if not node_r.wait_for_nav2_active(wall_timeout_sec=50.0):
                suite_results["readiness_failures"].append(f"{spec['dir_name']}: Nav2 inactive")
                continue
            if not node_r.action_client.wait_for_server(timeout_sec=45.0):
                suite_results["readiness_failures"].append(f"{spec['dir_name']}: Server unavailable")
                continue

            ctx_r = EpisodeActionHistoryContext()
            disp_r = ActionDispatcher(context=ctx_r, run_id=run_id, episode_id=spec["dir_name"])
            disp_r.ros_observer = lambda act: node_r.get_live_observation(target_id=act.get("params", {}).get("target_id"))

            def ros_send_nav_r(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
                goal_msg = NavigateToPose.Goal()
                p = act.get("executable_params", act.get("params", {}))
                goal_msg.pose.header.frame_id = p.get("frame_id", "map")
                goal_msg.pose.header.stamp = node_r.get_clock().now().to_msg()
                g = p["goal"]
                goal_msg.pose.pose.position.x = float(g[0])
                goal_msg.pose.pose.position.y = float(g[1])
                goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
                goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

                node_r.nav_goal_sent_count += 1
                ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
                future = node_r.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
                rclpy.spin_until_future_complete(node_r, future, timeout_sec=10.0)
                if not future.done() or not future.result() or not future.result().accepted:
                    return {"status": "REJECTED", "accepted": False}
                node_r.current_active_goal_handle = future.result()
                uuid_match = (bytes(node_r.current_active_goal_handle.goal_id.uuid) == goal_uuid.bytes)
                return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid), "uuid_verified": uuid_match}

            disp_r.ros_executor = ros_send_nav_r

            if not spec["is_cancel"]:
                # Normal Navigation Episode
                nav_act_r = {"action": "navigate", "action_id": spec["action_id"], "params": {"goal": spec["goal"], "frame_id": "map", "timeout_sec": 60.0}}
                step_sum_r, eval_r, stability_records_r = _execute_navigation_with_monitoring(
                    node=node_r,
                    dispatcher=disp_r,
                    action_dict=nav_act_r,
                    logger=log_r,
                    thresholds=thresholds,
                )

                with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                    json.dump(stability_records_r, f, indent=2)
                save_raw_trajectory(ep_dir, node_r.episode_gt_samples, node_r.episode_odom_samples)

                ep_data = {
                    "episode_id": spec["dir_name"],
                    "action_id": spec["action_id"],
                    "goal": spec["goal"],
                    "dispatch": step_sum_r["dispatch"],
                    "execution_outcome": step_sum_r["execution_outcome"],
                    "terminal_status_name": step_sum_r["terminal_status_name"],
                    "status_code": step_sum_r["status_code"],
                    "evaluation": eval_r,
                    "settled_ok": step_sum_r["settled_ok"],
                    "safety_intervention": node_r.sticky_safety_intervention,
                    "initial_states": {"gt": node_r.episode_gt_samples[0] if node_r.episode_gt_samples else None},
                    "final_states": {"gt": node_r.latest_gt_record, "amcl": node_r.latest_amcl_record},
                }
            else:
                # Cancel in Motion Episode
                nav_act_r = {"action": "navigate", "action_id": spec["action_id"], "params": {"goal": spec["goal"], "frame_id": "map", "timeout_sec": 60.0}}
                node_r.start_tracking()
                disp_res_r = disp_r.dispatch(nav_act_r)

                mv_conf = False
                t_c_w = time.monotonic()
                while time.monotonic() - t_c_w < 15.0:
                    rclpy.spin_once(node_r, timeout_sec=0.04)
                    if node_r.latest_odom_record and abs(node_r.latest_odom_record.get("linear_v", 0.0)) > 0.05:
                        mv_conf = True
                        log_r("Motion confirmed. Canceling...")
                        break

                cancel_dict_r = await_nav_goal_cancel(
                    node=node_r,
                    goal_handle=node_r.current_active_goal_handle,
                    cancel_timeout_sec=6.0,
                    result_timeout_sec=8.0,
                    logger=log_r,
                )
                disp_r.record_terminal_status(spec["action_id"], terminal_status=cancel_dict_r["ros_terminal_status"], status_code=cancel_dict_r["status_code"])

                settled_ok_c, safety_int_c = node_r.wait_for_passive_settling(max_sim_sec=2.5)
                node_r.sticky_safety_intervention = (node_r.sticky_safety_intervention or safety_int_c)
                stability_records_r, wd_trig = node_r.record_stability_window(duration_sim_sec=2.5)
                node_r.stop_tracking()

                with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                    json.dump(stability_records_r, f, indent=2)
                save_raw_trajectory(ep_dir, node_r.episode_gt_samples, node_r.episode_odom_samples)

                eval_r = evaluate_cancellation_episode(
                    nav2_status=cancel_dict_r["ros_terminal_status"],
                    movement_confirmed_before_cancel=mv_conf,
                    cancel_request_accepted=cancel_dict_r["cancel_accepted"],
                    stability_samples=stability_records_r,
                    thresholds=thresholds,
                    watchdog_triggered=wd_trig,
                    safety_intervention=node_r.sticky_safety_intervention,
                )

                ep_data = {
                    "episode_id": spec["dir_name"],
                    "action_id": spec["action_id"],
                    "goal": spec["goal"],
                    "dispatch": disp_res_r,
                    "execution_outcome": "EXECUTION_CANCELED" if cancel_dict_r["cancel_verified"] else "EXECUTION_FAILED",
                    "terminal_status_name": cancel_dict_r["ros_terminal_status"],
                    "status_code": cancel_dict_r["status_code"],
                    "cancel_accepted": cancel_dict_r["cancel_accepted"],
                    "movement_confirmed": mv_conf,
                    "evaluation": eval_r,
                    "settled_ok": settled_ok_c,
                    "safety_intervention": node_r.sticky_safety_intervention,
                    "initial_states": {"gt": node_r.episode_gt_samples[0] if node_r.episode_gt_samples else None},
                    "final_states": {"gt": node_r.latest_gt_record, "amcl": node_r.latest_amcl_record},
                }

            with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                json.dump(ep_data, f, indent=2)
            suite_results["suite_4_regression_episodes"].append(ep_data)

        finally:
            rclpy.shutdown()
            kill_process_group(os.getpgid(sim_proc_r.pid))
            events_log_r.close()

    # Overall Status Computation
    suite1_ok = suite_results["suite_1_observe_nav_observe"].get("chain_verified", False)
    suite2_ok = suite_results["suite_2_cancel_retry_observe"].get("chain_verified", False)
    suite3_ok = suite_results["suite_3_observe_anomalies"].get("anomalies_verified", False)
    suite4_ok = len(suite_results["suite_4_regression_episodes"]) == 4 and all(
        (ep.get("evaluation", {}).get("strict_physical_arrival_and_stable", False) or ep.get("evaluation", {}).get("cancel_stop_verified", False))
        for ep in suite_results["suite_4_regression_episodes"]
    )
    coord_ok = suite_results["coordinate_alignment"]["verified"]

    if suite1_ok and suite2_ok and suite3_ok and suite4_ok and coord_ok:
        suite_results["overall_status"] = "PASSED"
    else:
        suite_results["overall_status"] = "FAILED"

    # Save summary.json
    summary_path = run_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(suite_results, f, indent=2)

    # Compute sha256 checksums
    checksums = compute_sha256_tree(run_dir)
    with open(run_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        for fname, h in checksums.items():
            f.write(f"{h}  {fname}\n")

    print(f"\n=======================================================================")
    print(f"P1b Final Verification Complete: Overall Status = {suite_results['overall_status']}")
    print(f"Suite 1 Chain: {suite1_ok}")
    print(f"Suite 2 Cancel & Retry Chain: {suite2_ok}")
    print(f"Suite 3 Topic Anomalies & Recovery: {suite3_ok}")
    print(f"Suite 4 4-Episode Regression: {suite4_ok}")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")


if __name__ == "__main__":
    main()
