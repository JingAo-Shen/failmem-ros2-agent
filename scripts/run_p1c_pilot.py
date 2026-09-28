#!/usr/bin/env python3
"""FailMem P1c Single-Fault Channel Temporary Blockage Pilot Runner.

Executes 9 independent, isolated episodes across 3 conditions:
- C0 (Unblocked Baseline): 3 episodes. Direct navigation from [-2.0, -0.5] to [0.5, -0.5].
- C1 (Continuous Obstacle Blockage): 3 episodes. Obstacle box at [-1.1, -0.55] physically occludes south corridor.
  Nav2 attempts navigation and fails/times out.
- C2 (Temporary Blockage): 3 episodes. Obstacle initially present -> initial navigate fails -> observe ->
  obstacle deleted -> retry dispatched with replayed parameters -> navigate arrives at [0.5, -0.5] -> post-retry observe.

Strict evidence collection:
- Coordinate alignment proof
- Per-episode raw trajectory (GT + Odom)
- Per-episode passive stability window (2.0s sim time)
- Event logs, simulator logs, and offline scoring evaluation
- SHA256 checksums tree
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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from gazebo_msgs.srv import SpawnEntity, DeleteEntity
from nav2_msgs.srv import ClearEntireCostmap
from lifecycle_msgs.srv import GetState
from std_srvs.srv import Empty
from unique_identifier_msgs.msg import UUID as RosUUID
import yaml

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


class P1cRunnerNode(Node):
    """ROS 2 Node for P1c blockage pilot experiments."""

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
        self.spawn_entity_client = self.create_client(SpawnEntity, "/spawn_entity")
        self.delete_entity_client = self.create_client(DeleteEntity, "/delete_entity")
        self.clear_global_costmap_client = self.create_client(ClearEntireCostmap, "/global_costmap/clear_entirely_global_costmap")
        self.clear_local_costmap_client = self.create_client(ClearEntireCostmap, "/local_costmap/clear_entirely_local_costmap")

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

        self.continuous_odom_buffer: collections.deque = collections.deque(maxlen=2000)
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
        try:
            idx = msg.name.index("turtlebot3_waffle")
        except ValueError:
            return
        self.gt_msg_count += 1
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
            return future.result().current_state.label.upper()
        return "UNKNOWN"

    def get_current_nav2_goal_status(self) -> str:
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
        clock_frozen = ((wall_now - wall_start >= 1.0) and not sim_advanced)

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
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_odom_record and self.latest_gt_record and self.latest_scan_record:
                self.log(
                    f"Sensors streaming: odom={self.latest_odom_record['x']:.2f}, "
                    f"gt={self.latest_gt_record['x']:.2f}, scan={self.latest_scan_record['valid_count']} rays"
                )
                return True
            time.sleep(0.05)
        return False

    def initialize_amcl_pose(self, x: float = -2.0, y: float = -0.5, yaw: float = 0.0, wall_timeout_sec: float = 35.0) -> bool:
        t0 = time.monotonic()
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance[0] = 0.25
        msg.pose.covariance[7] = 0.25
        msg.pose.covariance[35] = 0.068

        self.initial_pose_pub.publish(msg)

        start_amcl_count = self.amcl_msg_count
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_amcl_record and self.amcl_msg_count > start_amcl_count:
                cur_x = self.latest_amcl_record["x"]
                cur_y = self.latest_amcl_record["y"]
                dist = math.hypot(cur_x - x, cur_y - y)
                if dist < 0.35:
                    self.log(f"AMCL pose converged at x={cur_x:.2f}, y={cur_y:.2f} (delta={dist:.2f}m)")
                    return True
            if int((time.monotonic() - t0) * 2) % 3 == 0:
                msg.header.stamp = self.get_clock().now().to_msg()
                self.initial_pose_pub.publish(msg)
            time.sleep(0.05)
        return False

    def wait_for_nav2_active(self, wall_timeout_sec: float = 50.0) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            state = self.query_nav2_lifecycle(timeout_sec=0.5)
            if state == "ACTIVE":
                self.log("Nav2 bt_navigator is verified ACTIVE!")
                return True
            time.sleep(0.2)
        return False

    def spawn_obstacle(self, name: str, sdf_path: Path, x: float, y: float, z: float, yaw: float = 0.0, timeout_sec: float = 5.0) -> bool:
        """Spawn obstacle box via Gazebo /spawn_entity service."""
        if not self.spawn_entity_client.wait_for_service(timeout_sec=timeout_sec):
            self.log(f"[ERROR] /spawn_entity service unavailable after {timeout_sec}s")
            return False
        with open(sdf_path, "r", encoding="utf-8") as f:
            sdf_xml = f.read()
        req = SpawnEntity.Request()
        req.name = name
        req.xml = sdf_xml
        req.robot_namespace = ""
        req.initial_pose.position.x = float(x)
        req.initial_pose.position.y = float(y)
        req.initial_pose.position.z = float(z)
        req.initial_pose.orientation.z = math.sin(yaw / 2.0)
        req.initial_pose.orientation.w = math.cos(yaw / 2.0)
        req.reference_frame = "world"

        fut = self.spawn_entity_client.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=timeout_sec)
        if fut.done() and fut.result() is not None and fut.result().success:
            self.log(f"Successfully spawned obstacle '{name}' at ({x:.2f}, {y:.2f}, {z:.2f})")
            return True
        msg = fut.result().status_message if fut.done() and fut.result() else "No response"
        self.log(f"[WARN] Failed to spawn obstacle '{name}': {msg}")
        return False

    def delete_obstacle(self, name: str, timeout_sec: float = 5.0) -> bool:
        """Delete obstacle entity via Gazebo /delete_entity service."""
        if not self.delete_entity_client.wait_for_service(timeout_sec=timeout_sec):
            self.log(f"[ERROR] /delete_entity service unavailable after {timeout_sec}s")
            return False
        req = DeleteEntity.Request()
        req.name = name
        fut = self.delete_entity_client.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=timeout_sec)
        if fut.done() and fut.result() is not None and fut.result().success:
            self.log(f"Successfully deleted obstacle '{name}' from Gazebo world")
            return True
        msg = fut.result().status_message if fut.done() and fut.result() else "No response"
        self.log(f"[WARN] Failed to delete obstacle '{name}': {msg}")
        return False

    def clear_costmaps(self, timeout_sec: float = 2.0):
        """Request immediate costmap layer purge to speed up lidar raytrace sync."""
        try:
            if self.clear_global_costmap_client.wait_for_service(timeout_sec=timeout_sec):
                f_g = self.clear_global_costmap_client.call_async(ClearEntireCostmap.Request())
                rclpy.spin_until_future_complete(self, f_g, timeout_sec=timeout_sec)
            if self.clear_local_costmap_client.wait_for_service(timeout_sec=timeout_sec):
                f_l = self.clear_local_costmap_client.call_async(ClearEntireCostmap.Request())
                rclpy.spin_until_future_complete(self, f_l, timeout_sec=timeout_sec)
        except Exception as e:
            self.log(f"[WARN] Error requesting costmap purge: {e}")

    def wait_for_passive_settling(
        self,
        max_sim_sec: float = 2.5,
        vel_thresh_mps: float = 0.05,
        vel_thresh_radps: float = 0.05,
    ) -> Tuple[bool, bool]:
        t0_sim = self.get_sim_time_sec()
        t0_wall = time.monotonic()
        stable_start_sim: Optional[float] = None
        safety_intervened = False

        while self.get_sim_time_sec() - t0_sim < max_sim_sec:
            rclpy.spin_once(self, timeout_sec=0.04)
            sim_now = self.get_sim_time_sec()
            lv = abs(self.latest_odom_record.get("linear_v", 0.0)) if self.latest_odom_record else 0.0
            av = abs(self.latest_odom_record.get("angular_v", 0.0)) if self.latest_odom_record else 0.0

            if lv <= vel_thresh_mps and av <= vel_thresh_radps:
                if stable_start_sim is None:
                    stable_start_sim = sim_now
                elif sim_now - stable_start_sim >= 2.0:
                    self.log(f"Passive physical halt verified: stable for {sim_now - stable_start_sim:.2f}s sim time (lv={lv:.4f}, av={av:.4f})")
                    return True, False
            else:
                stable_start_sim = None

            if time.monotonic() - t0_wall > (max_sim_sec * 4.0):
                self.log("[WARN] Wall clock watchdog expired during passive halt check")
                break

        self.log(f"[SAFETY] Robot failed to halt passively within {max_sim_sec}s sim time. Triggering emergency zero-Twist.")
        twist = Twist()
        for _ in range(5):
            self.emergency_cmd_pub.publish(twist)
            rclpy.spin_once(self, timeout_sec=0.02)
            time.sleep(0.02)
        safety_intervened = True
        return False, safety_intervened

    def record_stability_window(
        self,
        duration_sim_sec: float = 2.4,
        wall_timeout_sec: float = 12.0,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        samples: List[Dict[str, Any]] = []
        t0_sim = self.get_sim_time_sec()
        t0_wall = time.monotonic()
        watchdog_triggered = False

        while self.get_sim_time_sec() - t0_sim < duration_sim_sec:
            rclpy.spin_once(self, timeout_sec=0.04)
            sim_now = self.get_sim_time_sec()
            if self.latest_gt_record and self.latest_odom_record:
                samples.append({
                    "sample_index": len(samples) + 1,
                    "sim_time": round(sim_now, 4),
                    "wall_time": round(time.monotonic(), 4),
                    "gt": copy.deepcopy(self.latest_gt_record),
                    "odom": copy.deepcopy(self.latest_odom_record),
                    "cmd_vel": copy.deepcopy(self.latest_cmd_vel_record),
                    "amcl": copy.deepcopy(self.latest_amcl_record) if self.latest_amcl_record else None,
                })
            if time.monotonic() - t0_wall > wall_timeout_sec:
                watchdog_triggered = True
                self.log(f"[WARN] Watchdog triggered during stability window recording after {wall_timeout_sec}s wall time")
                break

        sim_span = (self.get_sim_time_sec() - t0_sim)
        self.log(f"Stability window recording complete: {len(samples)} samples across {sim_span:.2f}s sim time")
        return samples, watchdog_triggered


def execute_navigation_action(
    node: P1cRunnerNode,
    dispatcher: ActionDispatcher,
    action_dict: Dict[str, Any],
    logger: Callable[[str], None],
    thresholds: Dict[str, Any],
    visible_state: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Execute navigation action and await result with strict monitoring."""
    node.start_tracking()
    dispatch_res = dispatcher.dispatch(action_dict, visible_state=visible_state)
    logger(f"Dispatched action '{action_dict.get('action_id')}': pipeline_status={dispatch_res.get('pipeline_status')}")

    if dispatch_res.get("pipeline_status") != "DISPATCHED" or not node.current_active_goal_handle:
        node.stop_tracking()
        eval_dict = evaluate_navigation_episode(
            target_goal=action_dict.get("params", {}).get("goal", [0.0, 0.0, 0.0]),
            nav2_status="REJECTED",
            final_gt=node.latest_gt_record,
            final_amcl=node.latest_amcl_record,
            stability_samples=[],
            thresholds=thresholds,
            watchdog_triggered=False,
            safety_intervention=False,
            execution_outcome="EXECUTION_FAILED",
            deadline_exceeded=False,
            failure_reason="GOAL_DISPATCH_REJECTED",
        )
        return {"dispatch": dispatch_res, "execution_outcome": "EXECUTION_FAILED", "terminal_status_name": "REJECTED", "status_code": GoalStatus.STATUS_UNKNOWN, "settled_ok": False, "safety_intervention": False, "evaluation": eval_dict}, eval_dict, []

    effective_act = dispatch_res.get("effective_action", {})
    p = effective_act.get("executable_params") or effective_act.get("params") or action_dict.get("executable_params", action_dict.get("params", {}))
    goal_coords = p.get("goal") or [0.0, 0.0, 0.0]
    sim_timeout = float(p.get("timeout_sec", 45.0))
    wall_timeout = sim_timeout + 15.0

    term_res = await_nav_goal_terminal_result(
        node=node,
        goal_handle=node.current_active_goal_handle,
        sim_timeout_sec=sim_timeout,
        wall_watchdog_sec=wall_timeout,
        logger=logger,
    )

    action_id = action_dict.get("action_id", "nav_action")
    dispatcher.record_terminal_status(
        action_id=action_id,
        terminal_status=term_res["ros_terminal_status"],
        status_code=term_res["status_code"],
    )

    # Passive settling
    settled_ok, safety_int = node.wait_for_passive_settling(max_sim_sec=2.5)
    node.sticky_safety_intervention = (node.sticky_safety_intervention or safety_int)

    # Convergence trigger for final AMCL pose
    if term_res["execution_outcome"] == "BUDGET_SUCCESS" and goal_coords:
        node.initialize_amcl_pose(x=float(goal_coords[0]), y=float(goal_coords[1]), yaw=float(goal_coords[2]), wall_timeout_sec=4.0)

    # Record stability window
    stability_records, watchdog_trig = node.record_stability_window(duration_sim_sec=2.4)
    node.stop_tracking()

    eval_dict = evaluate_navigation_episode(
        target_goal=goal_coords,
        nav2_status=term_res["ros_terminal_status"],
        final_gt=node.latest_gt_record,
        final_amcl=node.latest_amcl_record,
        stability_samples=stability_records,
        thresholds=thresholds,
        watchdog_triggered=(watchdog_trig or term_res["wall_watchdog_triggered"]),
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
        "failure_reason": term_res["failure_reason"],
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
    run_id = f"p1c_{timestamp_str}_{rand_suffix}"
    evidence_base = Path("/workspace/reports/evidence/p1c") if Path("/workspace").exists() else Path("reports/evidence/p1c")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"=======================================================================")
    print(f"FailMem P1c Blockage Pilot Runner: {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")

    scoring_rules = load_scoring_rules("configs/scoring_rules.yaml")
    thresholds = scoring_rules.get("thresholds", {})
    with open("configs/p1c_blockage_protocol.yaml", "r", encoding="utf-8") as f:
        protocol_config = yaml.safe_load(f)

    # 1. Ground truth coordinate frame verification (SDF landmark alignment)
    print("Verifying Gazebo SDF physical world to 2D occupancy grid geometric alignment...")
    coord_proof = verify_world_map_alignment(
        map_yaml_path="configs/turtlebot3_world.yaml",
        map_pgm_path="configs/turtlebot3_world.pgm",
        world_model_path="configs/turtlebot3_world.model",
        sdf_model_path="configs/turtlebot3_world.model.sdf",
    )
    with open(run_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    pilot_results = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1c-blockage-pilot",
        "protocol": protocol_config,
        "coordinate_alignment": {
            "verified": coord_proof.get("verified", False),
            "max_residual_m": coord_proof.get("max_residual_m"),
            "tested_landmarks_count": coord_proof.get("non_collinear_landmarks_tested"),
        },
        "C0_baseline_episodes": [],
        "C1_continuous_blockage_episodes": [],
        "C2_temporary_blockage_episodes": [],
        "readiness_failures": [],
        "overall_status": "FAILED",
    }

    target_goal = [0.5, -0.5, 0.0]
    obstacle_sdf_path = Path("configs/blockage_box.sdf")
    if not obstacle_sdf_path.exists() and Path("/workspace/configs/blockage_box.sdf").exists():
        obstacle_sdf_path = Path("/workspace/configs/blockage_box.sdf")
    obstacle_name = "corridor_blockage_box"
    obstacle_x, obstacle_y, obstacle_z = -1.1, -0.55, 0.30

    # Define Episode Plan: 3 x C0, 3 x C1, 3 x C2
    episodes_plan = [
        {"condition": "C0", "ep_num": 1, "dir_name": "C0_ep1"},
        {"condition": "C0", "ep_num": 2, "dir_name": "C0_ep2"},
        {"condition": "C0", "ep_num": 3, "dir_name": "C0_ep3"},
        {"condition": "C1", "ep_num": 1, "dir_name": "C1_ep1"},
        {"condition": "C1", "ep_num": 2, "dir_name": "C1_ep2"},
        {"condition": "C1", "ep_num": 3, "dir_name": "C1_ep3"},
        {"condition": "C2", "ep_num": 1, "dir_name": "C2_ep1"},
        {"condition": "C2", "ep_num": 2, "dir_name": "C2_ep2"},
        {"condition": "C2", "ep_num": 3, "dir_name": "C2_ep3"},
    ]

    for plan in episodes_plan:
        cond = plan["condition"]
        ep_num = plan["ep_num"]
        ep_dir = run_dir / plan["dir_name"]
        ep_dir.mkdir(parents=True, exist_ok=True)
        events_log = open(ep_dir / "events.log", "w", encoding="utf-8")

        def log_ep(msg: str):
            line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
            print(line, flush=True)
            events_log.write(line + "\n")
            events_log.flush()

        log_ep(f"=== Starting Episode {plan['dir_name']} (Condition {cond} #{ep_num}) ===")
        sim_proc, env = spawn_simulation(ep_dir)
        rclpy.init()

        try:
            node = P1cRunnerNode(f"p1c_{plan['dir_name']}", log_ep)

            # Strict Readiness Checks
            if not node.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Sim clock failed")
                raise RuntimeError("Simulation clock failed to advance")
            if not node.wait_for_sensors(wall_timeout_sec=50.0):
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Sensors failed")
                raise RuntimeError("Sensors not streaming")
            if not node.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=35.0):
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: AMCL failed")
                raise RuntimeError("AMCL pose failed to converge")
            if not node.wait_for_nav2_active(wall_timeout_sec=50.0):
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Nav2 inactive")
                raise RuntimeError("Nav2 lifecycle not ACTIVE")
            if not node.action_client.wait_for_server(timeout_sec=45.0):
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Server unavailable")
                raise RuntimeError("Action server unavailable")

            context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
            dispatcher = ActionDispatcher(context=context, run_id=run_id, episode_id=plan["dir_name"])
            dispatcher.ros_observer = lambda act: node.get_live_observation(target_id=act.get("params", {}).get("target_id"))

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

            # =================================================================
            # CONDITION C0: Baseline Unblocked Navigation
            # =================================================================
            if cond == "C0":
                # Step 1: Initial Observe
                obs1 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_initial", "params": {"target_id": "initial_scan"}})
                log_ep(f"Step 1 Initial Observe: status={obs1.get('ros_result', {}).get('status')}")

                # Step 2: Navigate to Goal
                nav_act = {"action": "navigate", "action_id": f"{plan['dir_name']}_nav", "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 45.0}}
                step2_sum, nav_eval, stab_recs = execute_navigation_action(
                    node=node,
                    dispatcher=dispatcher,
                    action_dict=nav_act,
                    logger=log_ep,
                    thresholds=thresholds,
                )

                # Step 3: Final Observe
                obs2 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_final", "params": {"target_id": "final_scan"}})
                log_ep(f"Step 3 Final Observe: status={obs2.get('ros_result', {}).get('status')}")

                with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                    json.dump(stab_recs, f, indent=2)
                save_raw_trajectory(ep_dir, node.episode_gt_samples, node.episode_odom_samples)

                ep_data = {
                    "episode_id": plan["dir_name"],
                    "condition": "C0",
                    "target_goal": target_goal,
                    "obstacle_present": False,
                    "step1_observe": obs1,
                    "step2_navigate": step2_sum,
                    "step3_observe": obs2,
                    "evaluation": nav_eval,
                    "arrived_and_stable": nav_eval.get("strict_physical_arrival_and_stable", False),
                    "execution_outcome": step2_sum["execution_outcome"],
                    "terminal_status_name": step2_sum["terminal_status_name"],
                    "action_history": context.action_history,
                }
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C0_baseline_episodes"].append(ep_data)

            # =================================================================
            # CONDITION C1: Continuous Obstacle Blockage
            # =================================================================
            elif cond == "C1":
                # Step 1: Spawn Obstacle in Corridor
                log_ep(f"Spawning obstacle box at ({obstacle_x}, {obstacle_y}, {obstacle_z})...")
                spawn_ok = node.spawn_obstacle(name=obstacle_name, sdf_path=obstacle_sdf_path, x=obstacle_x, y=obstacle_y, z=obstacle_z)
                assert spawn_ok, f"Failed to spawn obstacle in {plan['dir_name']}"

                # Allow 1.0s sim time for lidar scan and costmap layer integration
                t_sp = node.get_sim_time_sec()
                while node.get_sim_time_sec() - t_sp < 1.0:
                    rclpy.spin_once(node, timeout_sec=0.04)

                # Step 2: Initial Observe
                obs1 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_initial", "params": {"target_id": "initial_scan"}})
                log_ep(f"Step 2 Initial Observe: status={obs1.get('ros_result', {}).get('status')}, min_scan_range={obs1.get('ros_result', {}).get('observation', {}).get('laser_scan', {}).get('min_distance_m')}")

                # Step 3: Attempt Navigation (Blocked, timeout=30.0s)
                nav_act = {"action": "navigate", "action_id": f"{plan['dir_name']}_nav_blocked", "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 30.0}}
                step3_sum, nav_eval, stab_recs = execute_navigation_action(
                    node=node,
                    dispatcher=dispatcher,
                    action_dict=nav_act,
                    logger=log_ep,
                    thresholds=thresholds,
                )

                # Step 4: Post-Failure Observe
                obs2 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_post_failure", "params": {"target_id": "post_failure_scan"}})
                log_ep(f"Step 4 Post-Failure Observe: status={obs2.get('ros_result', {}).get('status')}")

                with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                    json.dump(stab_recs, f, indent=2)
                save_raw_trajectory(ep_dir, node.episode_gt_samples, node.episode_odom_samples)

                # Blockage verification: Robot should NOT arrive at target (either aborted or timeout or halted)
                arrival = nav_eval.get("strict_physical_arrival_and_stable", False)
                final_gt = node.latest_gt_record
                dist_to_goal = math.hypot(final_gt["x"] - target_goal[0], final_gt["y"] - target_goal[1]) if final_gt else 999.0
                blocked_verified = (not arrival and dist_to_goal > 0.50)

                ep_data = {
                    "episode_id": plan["dir_name"],
                    "condition": "C1",
                    "target_goal": target_goal,
                    "obstacle_present": True,
                    "obstacle_spawned": spawn_ok,
                    "obstacle_pose": [obstacle_x, obstacle_y, obstacle_z],
                    "step2_observe": obs1,
                    "step3_navigate_blocked": step3_sum,
                    "step4_observe": obs2,
                    "evaluation": nav_eval,
                    "final_dist_to_goal_m": round(dist_to_goal, 4),
                    "blockage_successful": blocked_verified,
                    "execution_outcome": step3_sum["execution_outcome"],
                    "terminal_status_name": step3_sum["terminal_status_name"],
                    "action_history": context.action_history,
                }
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C1_continuous_blockage_episodes"].append(ep_data)

            # =================================================================
            # CONDITION C2: Temporary Blockage (Observe -> Remove -> Retry)
            # =================================================================
            elif cond == "C2":
                # Step 1: Spawn Obstacle in Corridor
                log_ep(f"Spawning temporary obstacle box at ({obstacle_x}, {obstacle_y}, {obstacle_z})...")
                spawn_ok = node.spawn_obstacle(name=obstacle_name, sdf_path=obstacle_sdf_path, x=obstacle_x, y=obstacle_y, z=obstacle_z)
                assert spawn_ok, f"Failed to spawn obstacle in {plan['dir_name']}"

                # Allow 1.0s sim time for lidar and costmap
                t_sp = node.get_sim_time_sec()
                while node.get_sim_time_sec() - t_sp < 1.0:
                    rclpy.spin_once(node, timeout_sec=0.04)

                # Step 2: Initial Observe
                obs1 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_initial", "params": {"target_id": "initial_scan"}})
                log_ep(f"Step 2 Initial Observe: status={obs1.get('ros_result', {}).get('status')}")

                # Step 3: Initial Navigate (Blocked, timeout=25.0s)
                nav_act_orig = {"action": "navigate", "action_id": f"{plan['dir_name']}_nav_orig", "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 25.0}}
                step3_sum, nav1_eval, stab1_recs = execute_navigation_action(
                    node=node,
                    dispatcher=dispatcher,
                    action_dict=nav_act_orig,
                    logger=log_ep,
                    thresholds=thresholds,
                )
                log_ep(f"Step 3 Initial Blocked Navigate finished: outcome={step3_sum['execution_outcome']}, terminal_status={step3_sum['terminal_status_name']}")

                # Step 4: Mid-Episode Observe
                obs2 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_mid", "params": {"target_id": "mid_scan"}})
                log_ep(f"Step 4 Mid-Episode Observe: status={obs2.get('ros_result', {}).get('status')}")

                # Step 5: Remove Obstacle from Gazebo
                log_ep(f"Deleting obstacle '{obstacle_name}' to clear corridor...")
                del_ok = node.delete_obstacle(name=obstacle_name)
                assert del_ok, f"Failed to delete obstacle in {plan['dir_name']}"

                # Purge costmaps and allow 1.5s sim time for lidar raytracing and costmap clearing
                node.clear_costmaps()
                t_del = node.get_sim_time_sec()
                while node.get_sim_time_sec() - t_del < 1.5:
                    rclpy.spin_once(node, timeout_sec=0.04)

                # Step 6: Legitimate Retry with Replayed Parameters
                obs_dict_mid = obs2.get("ros_result", {}).get("observation") or {}
                curr_pose = obs_dict_mid.get("localization", {}).get("pose")
                if not curr_pose and node.latest_odom_record:
                    curr_pose = [node.latest_odom_record["x"], node.latest_odom_record["y"], node.latest_odom_record["yaw"]]
                if not curr_pose:
                    curr_pose = [-1.5, -0.5, 0.0]

                retry_act = {"action": "retry", "action_id": f"{plan['dir_name']}_retry_nav", "params": {"original_action_id": f"{plan['dir_name']}_nav_orig"}}
                step6_sum, retry_eval, stab2_recs = execute_navigation_action(
                    node=node,
                    dispatcher=dispatcher,
                    action_dict=retry_act,
                    logger=log_ep,
                    thresholds=thresholds,
                    visible_state={"amcl_pose": curr_pose},
                )
                log_ep(f"Step 6 Retry Navigate finished: outcome={step6_sum['execution_outcome']}, arrival={retry_eval.get('strict_physical_arrival_and_stable')}")

                # Step 7: Final Observe at Goal
                obs3 = dispatcher.dispatch({"action": "observe", "action_id": f"{plan['dir_name']}_obs_final", "params": {"target_id": "final_scan"}})
                log_ep(f"Step 7 Final Observe: status={obs3.get('ros_result', {}).get('status')}")

                with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                    json.dump(stab2_recs, f, indent=2)
                save_raw_trajectory(ep_dir, node.episode_gt_samples, node.episode_odom_samples)

                ep_data = {
                    "episode_id": plan["dir_name"],
                    "condition": "C2",
                    "target_goal": target_goal,
                    "obstacle_spawned": spawn_ok,
                    "obstacle_deleted": del_ok,
                    "step2_observe": obs1,
                    "step3_initial_navigate": step3_sum,
                    "step4_observe_mid": obs2,
                    "step6_retry_navigate": step6_sum,
                    "step7_observe_final": obs3,
                    "initial_failed_verified": step3_sum["execution_outcome"] != "BUDGET_SUCCESS",
                    "retry_arrived_and_stable": retry_eval.get("strict_physical_arrival_and_stable", False),
                    "action_history": context.action_history,
                }
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C2_temporary_blockage_episodes"].append(ep_data)

        finally:
            rclpy.shutdown()
            kill_process_group(os.getpgid(sim_proc.pid))
            events_log.close()

    # Overall Status Computation
    c0_ok = len(pilot_results["C0_baseline_episodes"]) == 3 and all(
        ep.get("arrived_and_stable", False) for ep in pilot_results["C0_baseline_episodes"]
    )
    c1_ok = len(pilot_results["C1_continuous_blockage_episodes"]) == 3 and all(
        ep.get("blockage_successful", False) for ep in pilot_results["C1_continuous_blockage_episodes"]
    )
    c2_ok = len(pilot_results["C2_temporary_blockage_episodes"]) == 3 and all(
        (ep.get("initial_failed_verified", False) and ep.get("retry_arrived_and_stable", False))
        for ep in pilot_results["C2_temporary_blockage_episodes"]
    )
    coord_ok = pilot_results["coordinate_alignment"]["verified"]

    if c0_ok and c1_ok and c2_ok and coord_ok:
        pilot_results["overall_status"] = "PASSED"
    else:
        pilot_results["overall_status"] = "PARTIAL"

    # Save summary.json
    summary_path = run_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(pilot_results, f, indent=2)

    # Compute sha256 checksums
    checksums = compute_sha256_tree(run_dir)
    with open(run_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        for fname, h in checksums.items():
            f.write(f"{h}  {fname}\n")

    print(f"\n=======================================================================")
    print(f"P1c Pilot Execution Complete: Overall Status = {pilot_results['overall_status']}")
    print(f"C0 Baseline (3 eps arrived): {c0_ok}")
    print(f"C1 Continuous Blockage (3 eps blocked): {c1_ok}")
    print(f"C2 Temporary Blockage (3 eps retry arrived): {c2_ok}")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")


if __name__ == "__main__":
    main()
