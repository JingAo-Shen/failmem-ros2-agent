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


def quat_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """Extract yaw from quaternion (roll-pitch-yaw)."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def map_goal_status_code_to_name(status_code: Optional[int]) -> str:
    """Strictly map ROS 2 GoalStatus code to canonical name without default success."""
    if status_code is None:
        return "UNKNOWN"
    if status_code == GoalStatus.STATUS_SUCCEEDED:
        return "SUCCEEDED"
    elif status_code == GoalStatus.STATUS_CANCELED:
        return "CANCELED"
    elif status_code == GoalStatus.STATUS_ABORTED:
        return "ABORTED"
    elif status_code == GoalStatus.STATUS_ACCEPTED:
        return "ACCEPTED"
    elif status_code == GoalStatus.STATUS_EXECUTING:
        return "EXECUTING"
    elif status_code == GoalStatus.STATUS_CANCELING:
        return "CANCELING"
    else:
        return f"STATUS_{status_code}"


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

        # Input gating for real ROS message layer anomaly testing
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

        self.is_tracking = False
        self.episode_gt_samples: List[Dict[str, Any]] = []
        self.episode_amcl_samples: List[Dict[str, Any]] = []
        self.episode_odom_samples: List[Dict[str, Any]] = []
        self.episode_scan_samples: List[Dict[str, Any]] = []
        self.episode_cmd_vel_samples: List[Dict[str, Any]] = []

    def log(self, msg: str):
        self.event_logger(msg)

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
            return  # Dropped at ROS message callback / reception layer
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
        if self.is_tracking:
            self.episode_odom_samples.append(record)

    def _amcl_cb(self, msg: PoseWithCovarianceStamped):
        if not self.gate_amcl_enabled:
            return  # Dropped at ROS message callback / reception layer
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
            return  # Dropped at ROS message callback / reception layer
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

    def get_live_observation(
        self,
        target_id: Optional[str] = None,
        current_goal_status: Optional[str] = "IDLE",
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

                if not self.gate_scan_enabled or self.latest_scan_record is None:
                    scan_fresh = True
                if not self.gate_odom_enabled or self.latest_odom_record is None:
                    odom_fresh = True

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

        res = self.obs_interface.extract_observation(
            current_sim_time=sim_now,
            latest_amcl=self.latest_amcl_record,
            latest_odom=self.latest_odom_record,
            latest_scan=self.latest_scan_record,
            nav2_lifecycle_state=lifecycle,
            current_goal_status=current_goal_status,
            odom_history=self.episode_odom_samples if self.episode_odom_samples else None,
            wall_clock_timeout=timed_out,
            clock_frozen=clock_frozen,
        )
        res["wait_timed_out"] = timed_out
        res["clock_frozen"] = clock_frozen
        res["wall_duration_sec"] = round(wall_now - wall_start, 4)
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
        max_sim_sec: float = 3.0,
        wall_timeout_sec: float = 12.0,
    ) -> Tuple[bool, bool]:
        """Passively observe deceleration to halt without cmd_vel interference.
        
        Returns:
            (settled_ok, safety_intervention)
        """
        t_start_sim = self.get_sim_time_sec()
        t_start_wall = time.monotonic()
        last_seen_odom_seq = None
        consecutive_stopped_count = 0

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.04)
            sim_now = self.get_sim_time_sec()
            wall_now = time.monotonic()

            if self.latest_odom_record:
                curr_seq = self.latest_odom_record.get("seq")
                if curr_seq != last_seen_odom_seq:
                    last_seen_odom_seq = curr_seq
                    lv = abs(self.latest_odom_record.get("linear_v", 999.0))
                    av = abs(self.latest_odom_record.get("angular_v", 999.0))
                    if lv < 0.05 and av < 0.05:
                        consecutive_stopped_count += 1
                        if consecutive_stopped_count >= 5:
                            self.log(f"Robot passively settled to halt (lv={lv:.4f} m/s, av={av:.4f} rad/s, NO safety intervention)")
                            return True, False
                    else:
                        consecutive_stopped_count = 0

            if (sim_now - t_start_sim) > max_sim_sec or (wall_now - t_start_wall) > wall_timeout_sec:
                self.log("[SAFETY] Passive settling timed out! Triggering emergency brake...")
                stop_twist = Twist()
                for _ in range(5):
                    self.emergency_cmd_pub.publish(stop_twist)
                    rclpy.spin_once(self, timeout_sec=0.05)
                return False, True

        return False, False

    def record_stability_window(
        self,
        duration_sim_sec: float = 2.5,
        max_wall_sec: float = 15.0,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Collect high-rate stability samples for at least duration_sim_sec simulation time."""
        sim_start_sample = None
        wall_start = time.monotonic()
        window_records = []
        last_recorded_odom_seq = None
        watchdog_triggered = False

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.04)
            sim_now = self.get_sim_time_sec()
            wall_now = time.monotonic()

            current_odom_seq = self.latest_odom_record.get("seq") if self.latest_odom_record else None
            if current_odom_seq != last_recorded_odom_seq and self.latest_gt_record:
                last_recorded_odom_seq = current_odom_seq
                if sim_start_sample is None:
                    sim_start_sample = sim_now
                window_records.append({
                    "seq": len(window_records) + 1,
                    "sim_time": round(sim_now, 4),
                    "gt": copy.deepcopy(self.latest_gt_record),
                    "amcl": copy.deepcopy(self.latest_amcl_record),
                    "odom": copy.deepcopy(self.latest_odom_record),
                    "scan": copy.deepcopy(self.latest_scan_record),
                    "cmd_vel": copy.deepcopy(self.latest_cmd_vel_record),
                })

            if sim_start_sample is not None and (sim_now - sim_start_sample) >= duration_sim_sec:
                break
            if (wall_now - wall_start) > max_wall_sec:
                self.log("[WARN] Stability window wall-clock watchdog triggered!")
                watchdog_triggered = True
                break

        return window_records, watchdog_triggered


def await_nav_goal_terminal_result(
    node: P1bRunnerNode,
    goal_handle: Any,
    timeout_sec: float,
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[str, Optional[int], Optional[str]]:
    """Awaits navigation goal completion with strict timeout, cancellation, and error handling.
    
    Returns:
        (terminal_status_name, status_code, failure_reason)
    """
    if goal_handle is None:
        return "ERROR", None, "GOAL_HANDLE_NONE"

    get_res_future = goal_handle.get_result_async()
    t_start = time.monotonic()
    timed_out = False

    while rclpy.ok() and not get_res_future.done():
        rclpy.spin_once(node, timeout_sec=0.04)
        if time.monotonic() - t_start > timeout_sec:
            timed_out = True
            if logger:
                logger(f"Navigation timed out ({timeout_sec:.1f}s). Requesting cancel...")
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(node, cancel_future, timeout_sec=5.0)
            break

    if timed_out:
        t_cancel_wait = time.monotonic()
        while rclpy.ok() and not get_res_future.done() and time.monotonic() - t_cancel_wait < 8.0:
            rclpy.spin_once(node, timeout_sec=0.04)

        if get_res_future.done():
            try:
                res = get_res_future.result()
                if res is not None:
                    code = res.status
                    status_name = map_goal_status_code_to_name(code)
                    return status_name, int(code), "TIMEOUT_CANCELED"
            except Exception as e:
                return "ERROR", None, f"RESULT_EXCEPTION: {e}"
        return "TIMEOUT", None, "TIMEOUT_NO_TERMINAL_RESULT"

    if get_res_future.done():
        try:
            res = get_res_future.result()
            if res is not None:
                code = res.status
                status_name = map_goal_status_code_to_name(code)
                return status_name, int(code), None
            else:
                return "ERROR", None, "RESULT_IS_NONE"
        except Exception as e:
            return "ERROR", None, f"RESULT_EXCEPTION: {e}"

    return "UNKNOWN", None, "FUTURE_NOT_DONE"


def await_nav_goal_cancel(
    node: P1bRunnerNode,
    goal_handle: Any,
    cancel_timeout_sec: float = 6.0,
    result_timeout_sec: float = 8.0,
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """Sends and awaits goal cancellation, strictly validating both cancel acceptance and CANCELED status.
    
    Returns:
        (cancel_accepted, terminal_status_name, status_code, failure_reason)
    """
    if goal_handle is None:
        return False, "ERROR", None, "GOAL_HANDLE_NONE"

    cancel_future = goal_handle.cancel_goal_async()
    rclpy.spin_until_future_complete(node, cancel_future, timeout_sec=cancel_timeout_sec)

    cancel_accepted = False
    if cancel_future.done():
        try:
            cancel_res = cancel_future.result()
            if cancel_res is not None and cancel_res.return_code == 0:
                cancel_accepted = True
        except Exception as e:
            if logger:
                logger(f"Cancel future exception: {e}")

    get_res_fut = goal_handle.get_result_async()
    t0 = time.monotonic()
    while rclpy.ok() and not get_res_fut.done() and time.monotonic() - t0 < result_timeout_sec:
        rclpy.spin_once(node, timeout_sec=0.04)

    if get_res_fut.done():
        try:
            res = get_res_fut.result()
            if res is not None:
                code = res.status
                status_name = map_goal_status_code_to_name(code)
                return cancel_accepted, status_name, int(code), None
            else:
                return cancel_accepted, "ERROR", None, "RESULT_IS_NONE"
        except Exception as e:
            return cancel_accepted, "ERROR", None, f"RESULT_EXCEPTION: {e}"

    return cancel_accepted, "TIMEOUT", None, "CANCEL_RESULT_TIMEOUT"


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
    """Save raw trajectory samples to trajectory.json."""
    traj_data = {
        "gt_trajectory": [
            {"seq": s["seq"], "sim_time": s["recv_sim_time_sec"], "x": s["x"], "y": s["y"], "yaw": s["yaw"]}
            for s in gt_samples if is_finite_number(s.get("x")) and is_finite_number(s.get("y"))
        ],
        "odom_trajectory": [
            {"seq": s["seq"], "stamp_sec": s["msg_stamp_sec"], "sim_time": s["recv_sim_time_sec"], "x": s["x"], "y": s["y"], "yaw": s["yaw"], "lv": s.get("linear_v"), "av": s.get("angular_v")}
            for s in odom_samples if is_finite_number(s.get("x")) and is_finite_number(s.get("y"))
        ],
    }
    with open(episode_dir / "trajectory.json", "w", encoding="utf-8") as f:
        json.dump(traj_data, f, indent=2)


def compute_sha256_tree(base_dir: Path) -> Dict[str, str]:
    """Compute sha256 for all files under base_dir."""
    hashes = {}
    for p in sorted(base_dir.rglob("*")):
        if p.is_file() and p.name != "checksums.sha256":
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            hashes[str(p.relative_to(base_dir))] = h
    return hashes


def main():
    print("=== Launching FailMem P1b Final Verification & Integration Suite ===")
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    run_id = f"p1b_{ts_str}_{rand_suffix}"

    repo_root = Path(__file__).resolve().parent.parent
    run_dir = repo_root / "reports" / "evidence" / "p1b" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rules_config = load_scoring_rules(str(repo_root / "configs" / "scoring_rules.yaml"))
    thresholds = rules_config["thresholds"]

    # 1. Dynamic Coordinate Alignment Proof
    coord_proof = verify_world_map_alignment()
    with open(run_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    suite_results: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1b-final",
        "scoring_rules": rules_config,
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
        "overall_status": "PENDING",
    }

    # =========================================================================
    # SUITE 1: Live Observe -> Navigate -> Observe Execution Chain
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

    suite1_safety_intervention = False

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

        # Step 1: Initial Observe Action
        obs1_act = {"action": "observe", "action_id": "s1_obs_initial", "params": {"target_id": "front_corridor"}}
        obs1_res = dispatcher.dispatch(obs1_act)
        log1(f"Step 1 Observe Result: status={obs1_res['ros_result']['status']}")

        # Step 2: Navigate Action
        nav_goal_handle = None

        def ros_send_nav(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            nonlocal nav_goal_handle
            goal_msg = NavigateToPose.Goal()
            p = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = p.get("frame_id", "map")
            goal_msg.pose.header.stamp = node.get_clock().now().to_msg()
            g = p["goal"]
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

            ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
            future = node.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
            rclpy.spin_until_future_complete(node, future, timeout_sec=10.0)
            if not future.done() or not future.result() or not future.result().accepted:
                return {"status": "REJECTED", "accepted": False}
            nav_goal_handle = future.result()
            uuid_match = (bytes(nav_goal_handle.goal_id.uuid) == goal_uuid.bytes)
            return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid), "uuid_verified": uuid_match}

        dispatcher.ros_executor = ros_send_nav
        nav_act = {"action": "navigate", "action_id": "s1_nav_target", "params": {"goal": [-0.5, -0.5, 0.0], "frame_id": "map", "timeout_sec": 60.0}}

        node.is_tracking = True
        obs1_obs = obs1_res.get("ros_result", {}).get("observation")
        visible_pose = obs1_obs["localization"]["pose"] if obs1_obs and "localization" in obs1_obs and "pose" in obs1_obs["localization"] else [-2.0, -0.5, 0.0]
        nav_dispatch_res = dispatcher.dispatch(nav_act, visible_state={"amcl_pose": visible_pose})
        log1(f"Step 2 Navigate Dispatched: {nav_dispatch_res['pipeline_status']}")

        effective_timeout = float(nav_dispatch_res.get("effective_action", {}).get("executable_params", {}).get("timeout_sec", 60.0))
        effective_goal = list(nav_dispatch_res.get("effective_action", {}).get("executable_params", {}).get("goal", [-0.5, -0.5, 0.0]))

        nav_term_status, nav_code, nav_fail_reason = await_nav_goal_terminal_result(
            node=node,
            goal_handle=nav_goal_handle,
            timeout_sec=effective_timeout,
            logger=log1,
        )
        dispatcher.record_terminal_status("s1_nav_target", terminal_status=nav_term_status, status_code=nav_code)

        settled_ok, safety_int = node.wait_for_passive_settling(max_sim_sec=2.5)
        suite1_safety_intervention = suite1_safety_intervention or safety_int
        if node.latest_odom_record:
            node.initialize_amcl_pose(x=node.latest_odom_record["x"], y=node.latest_odom_record["y"], yaw=node.latest_odom_record["yaw"], wall_timeout_sec=5.0)

        stability_samples, watchdog = node.record_stability_window(duration_sim_sec=2.5)
        node.is_tracking = False

        # Save raw stability window and trajectory
        with open(ep1_dir / "stability_window.json", "w", encoding="utf-8") as f:
            json.dump(stability_samples, f, indent=2)
        save_raw_trajectory(ep1_dir, node.episode_gt_samples, node.episode_odom_samples)

        nav_eval = evaluate_navigation_episode(
            target_goal=effective_goal,
            nav2_status=nav_term_status,
            final_gt=node.latest_gt_record,
            final_amcl=node.latest_amcl_record,
            stability_samples=stability_samples,
            thresholds=thresholds,
            watchdog_triggered=watchdog,
            safety_intervention=suite1_safety_intervention,
        )

        # Step 3: Final Observe Action
        obs2_act = {"action": "observe", "action_id": "s1_obs_final", "params": {"target_id": "box_target"}}
        obs2_res = dispatcher.dispatch(obs2_act)
        log1(f"Step 3 Final Observe Result: status={obs2_res['ros_result']['status']}")

        suite1_data = {
            "chain": ["observe", "navigate", "observe"],
            "step1_observe": obs1_res,
            "step2_navigate": {
                "dispatch": nav_dispatch_res,
                "terminal_status_name": nav_term_status,
                "status_code": nav_code,
                "terminal_failure_reason": nav_fail_reason,
                "settled_ok": settled_ok,
                "safety_intervention": suite1_safety_intervention,
                "evaluation": nav_eval,
            },
            "step3_observe": obs2_res,
            "action_history": context.action_history,
            "chain_verified": (
                obs1_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and nav_eval["strict_physical_arrival_and_stable"]
                and not suite1_safety_intervention
                and obs2_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
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

    suite2_safety_intervention = False

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

        active_goal_handle = None
        dispatched_goal_ids = []

        def ros_send_nav2(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            nonlocal active_goal_handle
            goal_msg = NavigateToPose.Goal()
            p = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = p.get("frame_id", "map")
            goal_msg.pose.header.stamp = node2.get_clock().now().to_msg()
            g = p["goal"]
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

            ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
            future = node2.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
            rclpy.spin_until_future_complete(node2, future, timeout_sec=10.0)
            if not future.done() or not future.result() or not future.result().accepted:
                return {"status": "REJECTED", "accepted": False}
            active_goal_handle = future.result()
            dispatched_goal_ids.append(str(goal_uuid))
            uuid_match = (bytes(active_goal_handle.goal_id.uuid) == goal_uuid.bytes)
            return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid), "uuid_verified": uuid_match}

        dispatcher2.ros_executor = ros_send_nav2

        # Step 1: Initial Navigate Action
        nav_init_act = {"action": "navigate", "action_id": "s2_nav_orig", "params": {"goal": [0.5, -0.5, 1.57], "frame_id": "map", "timeout_sec": 60.0}}
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

        cancel_accepted, cancel_term_status, cancel_code, cancel_fail = await_nav_goal_cancel(
            node=node2,
            goal_handle=active_goal_handle,
            cancel_timeout_sec=6.0,
            result_timeout_sec=8.0,
            logger=log2,
        )
        dispatcher2.record_terminal_status("s2_nav_orig", terminal_status=cancel_term_status, status_code=cancel_code)

        settled_ok1, safety_int1 = node2.wait_for_passive_settling(max_sim_sec=2.5)
        suite2_safety_intervention = suite2_safety_intervention or safety_int1

        stability_samples_cancel, watchdog_cancel = node2.record_stability_window(duration_sim_sec=2.5)
        with open(ep2_dir / "step1_cancel_stability_window.json", "w", encoding="utf-8") as f:
            json.dump(stability_samples_cancel, f, indent=2)

        cancel_eval = evaluate_cancellation_episode(
            nav2_status=cancel_term_status,
            movement_confirmed_before_cancel=movement_confirmed,
            cancel_request_accepted=cancel_accepted,
            stability_samples=stability_samples_cancel,
            thresholds=thresholds,
            watchdog_triggered=watchdog_cancel,
            safety_intervention=suite2_safety_intervention,
        )

        # Step 3: Valid Retry Action (Parameter restoration from s2_nav_orig)
        current_visible = {"amcl_pose": [node2.latest_amcl_record["x"], node2.latest_amcl_record["y"], node2.latest_amcl_record["yaw"]]}
        retry_act = {"action": "retry", "action_id": "s2_retry_nav", "params": {"original_action_id": "s2_nav_orig"}}
        node2.is_tracking = True
        res_retry = dispatcher2.dispatch(retry_act, visible_state=current_visible)
        
        retry_effective_timeout = float(res_retry.get("effective_action", {}).get("executable_params", {}).get("timeout_sec", 60.0))
        retry_effective_goal = list(res_retry.get("effective_action", {}).get("executable_params", {}).get("goal", [0.5, -0.5, 1.57]))
        log2(f"Step 3 Retry Dispatched (UUID={res_retry['goal_uuid']}) | Restored Goal: {retry_effective_goal}")

        retry_term_status, retry_code, retry_fail = await_nav_goal_terminal_result(
            node=node2,
            goal_handle=active_goal_handle,
            timeout_sec=retry_effective_timeout,
            logger=log2,
        )
        dispatcher2.record_terminal_status("s2_retry_nav", terminal_status=retry_term_status, status_code=retry_code)

        settled_ok2, safety_int2 = node2.wait_for_passive_settling(max_sim_sec=2.5)
        suite2_safety_intervention = suite2_safety_intervention or safety_int2
        if node2.latest_odom_record:
            node2.initialize_amcl_pose(x=node2.latest_odom_record["x"], y=node2.latest_odom_record["y"], yaw=node2.latest_odom_record["yaw"], wall_timeout_sec=5.0)

        stability_samples2, watchdog2 = node2.record_stability_window(duration_sim_sec=2.5)
        node2.is_tracking = False

        with open(ep2_dir / "step3_retry_stability_window.json", "w", encoding="utf-8") as f:
            json.dump(stability_samples2, f, indent=2)
        save_raw_trajectory(ep2_dir, node2.episode_gt_samples, node2.episode_odom_samples)

        retry_eval = evaluate_navigation_episode(
            target_goal=retry_effective_goal,
            nav2_status=retry_term_status,
            final_gt=node2.latest_gt_record,
            final_amcl=node2.latest_amcl_record,
            stability_samples=stability_samples2,
            thresholds=thresholds,
            watchdog_triggered=watchdog2,
            safety_intervention=suite2_safety_intervention,
        )

        # Step 4: Final Observe Action
        obs_post_retry = {"action": "observe", "action_id": "s2_obs_post_retry", "params": {"target_id": "target_marker"}}
        obs_post_res = dispatcher2.dispatch(obs_post_retry)
        log2(f"Step 4 Post-Retry Observe Result: status={obs_post_res['ros_result']['status']}")

        # Step 5: Constraint Check - Disallow redundant retry under identical state fingerprint
        redundant_retry = {"action": "retry", "action_id": "s2_retry_blocked", "params": {"original_action_id": "s2_nav_orig"}}
        blocked_res = dispatcher2.dispatch(redundant_retry, visible_state=current_visible)
        log2(f"Step 5 Duplicate State Retry Blocked Check: pipeline_status={blocked_res['pipeline_status']} (error={blocked_res.get('error_type')})")

        suite2_data = {
            "chain": ["navigate", "cancel", "retry", "observe"],
            "step1_original_navigate": res_init,
            "step2_cancel": {
                "movement_confirmed": movement_confirmed,
                "cancel_accepted": cancel_accepted,
                "terminal_status_name": cancel_term_status,
                "status_code": cancel_code,
                "evaluation": cancel_eval,
            },
            "step3_retry": {
                "dispatch": res_retry,
                "executable_goal_restored": retry_effective_goal,
                "terminal_status_name": retry_term_status,
                "status_code": retry_code,
                "evaluation": retry_eval,
            },
            "step4_observe": obs_post_res,
            "step5_constraint_blocked": blocked_res,
            "dispatched_goal_uuids": dispatched_goal_ids,
            "distinct_uuids_verified": len(dispatched_goal_ids) == 2 and dispatched_goal_ids[0] != dispatched_goal_ids[1],
            "action_history": context2.action_history,
            "safety_intervention_sticky": suite2_safety_intervention,
            "chain_verified": (
                res_init["pipeline_status"] == "DISPATCHED"
                and movement_confirmed
                and cancel_accepted
                and cancel_term_status == "CANCELED"
                and cancel_eval["cancel_stop_verified"]
                and not suite2_safety_intervention
                and res_retry["pipeline_status"] == "DISPATCHED"
                and retry_term_status == "SUCCEEDED"
                and retry_eval["strict_physical_arrival_and_stable"]
                and obs_post_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and blocked_res["pipeline_status"] == "FAILED"
                and blocked_res.get("error_type") == "STATE_FINGERPRINT_RETRY_EXHAUSTED"
                and not blocked_res.get("ros_dispatched", False)
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
    # SUITE 3: Real ROS Observation Anomaly & Degraded Test Suite
    # =========================================================================
    ep3_dir = run_dir / "suite3_observe_anomalies"
    ep3_dir.mkdir(parents=True, exist_ok=True)
    events_log3 = open(ep3_dir / "events.log", "w", encoding="utf-8")

    def log3(msg: str):
        line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        events_log3.write(line + "\n")
        events_log3.flush()

    log3("=== Starting Suite 3: Real ROS Observation Anomaly & Degraded Contract Tests ===")
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
        if not node3.wait_for_nav2_active(wall_timeout_sec=50.0):
            suite_results["readiness_failures"].append("Suite 3: Nav2 lifecycle not ACTIVE")
            raise RuntimeError("Nav2 lifecycle not ACTIVE")

        context3 = EpisodeActionHistoryContext(max_retries=5, max_retries_per_state=2)
        dispatcher3 = ActionDispatcher(context=context3, run_id=run_id, episode_id="suite3")
        dispatcher3.ros_observer = lambda act: node3.get_live_observation(target_id=act.get("params", {}).get("target_id"))

        # --- Sub-suite 3A: Interface Unit Checks (Static Schema / Contract Checks) ---
        interface_checks = {}
        # Interface check 1: direct extract with missing odom
        if_missing_odom = node3.obs_interface.extract_observation(
            current_sim_time=node3.get_sim_time_sec(),
            latest_amcl=node3.latest_amcl_record,
            latest_odom=None,
            latest_scan=node3.latest_scan_record,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
        )
        interface_checks["if_missing_odom"] = if_missing_odom
        log3(f"Interface Check (Missing Odom): status={if_missing_odom['status']}, error_type={if_missing_odom.get('error_type')}")

        # Interface check 2: direct extract with missing scan
        if_missing_scan = node3.obs_interface.extract_observation(
            current_sim_time=node3.get_sim_time_sec(),
            latest_amcl=node3.latest_amcl_record,
            latest_odom=node3.latest_odom_record,
            latest_scan=None,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
        )
        interface_checks["if_missing_scan"] = if_missing_scan
        log3(f"Interface Check (Missing Scan): status={if_missing_scan['status']}, error_type={if_missing_scan.get('error_type')}")

        # --- Sub-suite 3B: Real ROS Message Layer Topic Relay / Gate Tests ---
        real_ros_tests = {}

        # 3.1 Normal Observation via Dispatcher
        res_3_1 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_1_normal", "params": {"target_id": "normal_test"}})
        real_ros_tests["test_3_1_normal"] = res_3_1
        log3(f"Test 3.1 (Real Normal Obs): status={res_3_1['ros_result']['status']}")

        # 3.2 Cut Scan Stream at ROS Callback Layer (Natural Ageing -> DEGRADED)
        log3("Cutting /scan topic reception gate...")
        node3.gate_scan_enabled = False
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 2.5:
            rclpy.spin_once(node3, timeout_sec=0.04)
        
        res_3_2 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_2_stale_scan", "params": {"target_id": "stale_scan_test"}})
        real_ros_tests["test_3_2_stale_scan"] = res_3_2
        log3(f"Test 3.2 (Natural Stale Scan): status={res_3_2['ros_result']['status']}, error_type={res_3_2['ros_result'].get('error_type')}")

        # 3.3 Restore Scan Stream (Recovery -> SUCCESS)
        log3("Restoring /scan topic reception gate...")
        node3.gate_scan_enabled = True
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 0.6:
            rclpy.spin_once(node3, timeout_sec=0.04)
        
        res_3_3 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_3_scan_recovered", "params": {"target_id": "recovered_scan_test"}})
        real_ros_tests["test_3_3_scan_recovered"] = res_3_3
        log3(f"Test 3.3 (Scan Stream Recovered): status={res_3_3['ros_result']['status']}")

        # 3.4 Missing Scan from Node Startup (Clear Cache & Gate Off -> DEGRADED / SCAN_UNAVAILABLE)
        node3.latest_scan_record = None
        node3.gate_scan_enabled = False
        res_3_4 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_4_missing_scan", "params": {"target_id": "missing_scan_test"}})
        real_ros_tests["test_3_4_missing_scan"] = res_3_4
        log3(f"Test 3.4 (Missing Scan Stream): status={res_3_4['ros_result']['status']}, error_type={res_3_4['ros_result'].get('error_type')}")
        node3.gate_scan_enabled = True

        # 3.5 Cut Odometry Stream at ROS Callback Layer (Natural Ageing -> ERROR / ODOMETRY_STALE)
        log3("Cutting /odom topic reception gate...")
        node3.gate_odom_enabled = False
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 2.5:
            rclpy.spin_once(node3, timeout_sec=0.04)

        res_3_5 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_5_stale_odom", "params": {"target_id": "stale_odom_test"}})
        real_ros_tests["test_3_5_stale_odom"] = res_3_5
        log3(f"Test 3.5 (Natural Stale Odom): status={res_3_5['ros_result']['status']}, error_type={res_3_5['ros_result'].get('error_type')}")

        # 3.6 Restore Odometry Stream (Recovery -> SUCCESS)
        log3("Restoring /odom topic reception gate...")
        node3.gate_odom_enabled = True
        t_spin_start = node3.get_sim_time_sec()
        while node3.get_sim_time_sec() - t_spin_start < 0.6:
            rclpy.spin_once(node3, timeout_sec=0.04)

        res_3_6 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_6_odom_recovered", "params": {"target_id": "recovered_odom_test"}})
        real_ros_tests["test_3_6_odom_recovered"] = res_3_6
        log3(f"Test 3.6 (Odom Stream Recovered): status={res_3_6['ros_result']['status']}")

        # 3.7 Simulation Clock Paused / Frozen Resilience Test
        log3("Calling /pause_physics service to pause simulation clock...")
        pause_ok = node3.pause_gazebo_physics(timeout_sec=2.0)
        time.sleep(1.2)  # Wall clock ticks while sim clock is stopped

        res_3_7 = dispatcher3.dispatch({"action": "observe", "action_id": "obs_3_7_clock_pause", "params": {"target_id": "clock_pause_test"}})
        real_ros_tests["test_3_7_clock_pause"] = res_3_7
        log3(f"Test 3.7 (Simulation Clock Paused): status={res_3_7['ros_result']['status']}, error_type={res_3_7['ros_result'].get('error_type')}, wall_time={res_3_7['ros_result'].get('wall_duration_sec', 0.0):.3f}s")

        log3("Calling /unpause_physics service to resume simulation...")
        unpause_ok = node3.unpause_gazebo_physics(timeout_sec=2.0)
        time.sleep(0.5)
        while node3.get_sim_time_sec() - t_spin_start < 0.5:
            rclpy.spin_once(node3, timeout_sec=0.04)

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
                and res_3_5["ros_result"].get("error_type") in ("ODOMETRY_STALE", "ODOMETRY_UNAVAILABLE")
                and res_3_6["ros_result"]["status"] == "SUCCESS"
                and res_3_7["ros_result"]["status"] == "ERROR"
                and res_3_7["ros_result"].get("error_type") in ("SIMULATION_CLOCK_FROZEN", "SIMULATION_CLOCK_STALLED_OR_TIMEOUT", "ODOMETRY_STALE")
                and res_3_7["ros_result"].get("wall_duration_sec", 999.0) <= 3.0
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
        {"action_id": "reg_ep3_ret", "goal": [-1.8, -0.5, 3.14], "is_cancel": False, "dir_name": "regression_episode_3"},
        {"action_id": "reg_ep4_cancel", "goal": [0.5, 1.8, 0.0], "is_cancel": True, "dir_name": "regression_episode_4"},
    ]

    regression_episodes_data = []

    for ep_idx, r_spec in enumerate(regression_specs, 1):
        ep_dir = run_dir / r_spec["dir_name"]
        ep_dir.mkdir(parents=True, exist_ok=True)
        r_events = open(ep_dir / "events.log", "w", encoding="utf-8")

        def log_r(msg: str):
            line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
            print(line, flush=True)
            r_events.write(line + "\n")
            r_events.flush()

        log_r(f"=== Starting Regression Episode {ep_idx} ({r_spec['action_id']}) ===")
        sim_proc_r, _ = spawn_simulation(ep_dir)
        rclpy.init()

        ep_safety_intervention = False

        try:
            node_r = P1bRunnerNode(f"p1b_reg_ep{ep_idx}", log_r)
            # Strict Readiness Checks (Dependency Order: Clock -> Sensors -> AMCL Initial Pose -> Nav2 Active -> Action Server)
            if not node_r.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
                suite_results["readiness_failures"].append(f"Regression Ep {ep_idx}: Simulation clock failed to advance")
                raise RuntimeError("Simulation clock failed to advance")
            if not node_r.wait_for_sensors(wall_timeout_sec=50.0):
                suite_results["readiness_failures"].append(f"Regression Ep {ep_idx}: Sensors not streaming")
                raise RuntimeError("Sensors not streaming")
            if not node_r.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=35.0):
                suite_results["readiness_failures"].append(f"Regression Ep {ep_idx}: AMCL pose failed to converge")
                raise RuntimeError("AMCL pose failed to converge")
            if not node_r.wait_for_nav2_active(wall_timeout_sec=50.0):
                suite_results["readiness_failures"].append(f"Regression Ep {ep_idx}: Nav2 lifecycle not ACTIVE")
                raise RuntimeError("Nav2 lifecycle not ACTIVE")
            if not node_r.action_client.wait_for_server(timeout_sec=45.0):
                suite_results["readiness_failures"].append(f"Regression Ep {ep_idx}: Action server unavailable")
                raise RuntimeError("Action server unavailable")

            context_r = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
            dispatcher_r = ActionDispatcher(context=context_r, run_id=run_id, episode_id=f"reg_{ep_idx}")

            goal_handle_r = None

            def ros_send_nav_r(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
                nonlocal goal_handle_r
                goal_msg = NavigateToPose.Goal()
                p = act.get("executable_params", act.get("params", {}))
                goal_msg.pose.header.frame_id = p.get("frame_id", "map")
                goal_msg.pose.header.stamp = node_r.get_clock().now().to_msg()
                g = p["goal"]
                goal_msg.pose.pose.position.x = float(g[0])
                goal_msg.pose.pose.position.y = float(g[1])
                goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
                goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

                ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
                future = node_r.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
                rclpy.spin_until_future_complete(node_r, future, timeout_sec=10.0)
                if not future.done() or not future.result() or not future.result().accepted:
                    return {"status": "REJECTED", "accepted": False}
                goal_handle_r = future.result()
                uuid_match = (bytes(goal_handle_r.goal_id.uuid) == goal_uuid.bytes)
                return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid), "uuid_verified": uuid_match}

            dispatcher_r.ros_executor = ros_send_nav_r

            nav_action = {"action": "navigate", "action_id": r_spec["action_id"], "params": {"goal": r_spec["goal"], "frame_id": "map", "timeout_sec": 60.0}}
            node_r.is_tracking = True
            dispatch_res_r = dispatcher_r.dispatch(nav_action)

            effective_timeout_r = float(dispatch_res_r.get("effective_action", {}).get("executable_params", {}).get("timeout_sec", 60.0))
            effective_goal_r = list(dispatch_res_r.get("effective_action", {}).get("executable_params", {}).get("goal", r_spec["goal"]))

            mv_confirmed = False
            cancel_acc = False

            if r_spec["is_cancel"]:
                t_w = time.monotonic()
                while time.monotonic() - t_w < 15.0:
                    rclpy.spin_once(node_r, timeout_sec=0.04)
                    if node_r.latest_odom_record and abs(node_r.latest_odom_record.get("linear_v", 0.0)) > 0.05:
                        mv_confirmed = True
                        break
                
                cancel_acc, status_name_r, term_code_r, fail_reason_r = await_nav_goal_cancel(
                    node=node_r,
                    goal_handle=goal_handle_r,
                    cancel_timeout_sec=6.0,
                    result_timeout_sec=8.0,
                    logger=log_r,
                )
            else:
                status_name_r, term_code_r, fail_reason_r = await_nav_goal_terminal_result(
                    node=node_r,
                    goal_handle=goal_handle_r,
                    timeout_sec=effective_timeout_r,
                    logger=log_r,
                )

            dispatcher_r.record_terminal_status(r_spec["action_id"], terminal_status=status_name_r, status_code=term_code_r)

            settled_ok_r, safety_int_r = node_r.wait_for_passive_settling(max_sim_sec=2.5)
            ep_safety_intervention = ep_safety_intervention or safety_int_r

            stability_samples_r, watchdog_r = node_r.record_stability_window(duration_sim_sec=2.5)
            node_r.is_tracking = False

            with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                json.dump(stability_samples_r, f, indent=2)
            save_raw_trajectory(ep_dir, node_r.episode_gt_samples, node_r.episode_odom_samples)

            if not r_spec["is_cancel"]:
                eval_r = evaluate_navigation_episode(
                    target_goal=effective_goal_r,
                    nav2_status=status_name_r,
                    final_gt=node_r.latest_gt_record,
                    final_amcl=node_r.latest_amcl_record,
                    stability_samples=stability_samples_r,
                    thresholds=thresholds,
                    watchdog_triggered=watchdog_r,
                    safety_intervention=ep_safety_intervention,
                )
            else:
                eval_r = evaluate_cancellation_episode(
                    nav2_status=status_name_r,
                    movement_confirmed_before_cancel=mv_confirmed,
                    cancel_request_accepted=cancel_acc,
                    stability_samples=stability_samples_r,
                    thresholds=thresholds,
                    watchdog_triggered=watchdog_r,
                    safety_intervention=ep_safety_intervention,
                )

            # Localization audit
            amcl_audit = audit_localization_discrepancy(node_r.episode_amcl_samples, node_r.episode_gt_samples, thresholds)

            ep_data = {
                "episode_index": ep_idx,
                "action_id": r_spec["action_id"],
                "goal": r_spec["goal"],
                "is_cancel_test": r_spec["is_cancel"],
                "nav2_action_status": status_name_r,
                "status_code": term_code_r,
                "goal_uuid": dispatch_res_r["goal_uuid"],
                "evaluation": eval_r,
                "settled_ok": settled_ok_r,
                "safety_intervention": ep_safety_intervention,
                "localization_audit": amcl_audit,
                "initial_states": {
                    "gt": node_r.episode_gt_samples[0] if node_r.episode_gt_samples else None,
                },
                "final_states": {
                    "gt": node_r.latest_gt_record,
                    "amcl": node_r.latest_amcl_record,
                },
            }
            regression_episodes_data.append(ep_data)
            with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                json.dump(ep_data, f, indent=2)

            passed_str = eval_r.get("strict_physical_arrival_and_stable") if not r_spec["is_cancel"] else eval_r.get("cancel_stop_verified")
            log_r(f"Regression Episode {ep_idx} Complete: Status={status_name_r} | Strict Passed={passed_str}")

        finally:
            rclpy.shutdown()
            kill_process_group(os.getpgid(sim_proc_r.pid))
            r_events.close()

    suite_results["suite_4_regression_episodes"] = regression_episodes_data

    # =========================================================================
    # Compute Overall Authoritative Status
    # =========================================================================
    suite1_ok = suite_results["suite_1_observe_nav_observe"].get("chain_verified", False)
    suite2_ok = suite_results["suite_2_cancel_retry_observe"].get("chain_verified", False)
    suite3_ok = suite_results["suite_3_observe_anomalies"].get("anomalies_verified", False)
    
    reg_all_ok = True
    for rep in regression_episodes_data:
        ev = rep.get("evaluation", {})
        if rep.get("is_cancel_test"):
            if not ev.get("cancel_stop_verified", False):
                reg_all_ok = False
        else:
            if not ev.get("strict_physical_arrival_and_stable", False):
                reg_all_ok = False

    coord_ok = suite_results["coordinate_alignment"].get("verified", False)
    no_readiness_fails = len(suite_results["readiness_failures"]) == 0

    if suite1_ok and suite2_ok and suite3_ok and reg_all_ok and coord_ok and no_readiness_fails:
        suite_results["overall_status"] = "PASSED"
    else:
        suite_results["overall_status"] = "FAILED"

    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(suite_results, f, indent=2)

    # Compute and write SHA256 checksums
    checksums = compute_sha256_tree(run_dir)
    with open(run_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        for rel_p, h in sorted(checksums.items()):
            f.write(f"{h}  {rel_p}\n")

    print(f"=== P1b Suite Complete. Results in {run_dir} (Status: {suite_results['overall_status']}) ===")


if __name__ == "__main__":
    main()
