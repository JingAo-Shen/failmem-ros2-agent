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


def cleanup_simulation_processes():
    """Aggressively terminate lingering Gazebo, ROS 2, and Nav2 processes."""
    patterns = [
        "gzserver",
        "gzclient",
        "nav2_container",
        "component_container",
        "component_container_isolated",
        "lifecycle_manager",
        "robot_state_publisher",
        "spawn_entity",
        "tb3_simulation_launch",
        "bt_navigator",
        "controller_server",
        "planner_server",
        "recoveries_server",
        "behavior_server",
        "amcl",
        "map_server",
    ]
    for p in patterns:
        subprocess.run(["pkill", "-9", "-f", p], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.run(["ros2", "daemon", "stop"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(1.5)


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
        self._latest_raw_scan: Any = None  # raw LaserScan msg for sector analysis
        self._gazebo_model_names: List[str] = []  # tracked Gazebo model names for verification

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
        self._latest_raw_scan = msg  # Keep raw for sector analysis
        if self.is_tracking:
            self.episode_scan_samples.append(record)

    def _gazebo_cb(self, msg: ModelStates):
        sim_now = self.get_sim_time_sec()
        # Always track all model names for obstacle presence verification
        self._gazebo_model_names = list(msg.name)
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

    def clear_costmaps_diagnostic(self, timeout_sec: float = 2.0) -> Dict[str, Any]:
        """Request immediate costmap layer purge (DIAGNOSTIC USE ONLY - not in primary experiment).
        
        WARNING: Calling this in the primary experiment confounds natural costmap clearance
        with service-driven purging. Only call in labelled diagnostic branches.
        """
        result = {"global_cleared": False, "local_cleared": False}
        try:
            if self.clear_global_costmap_client.wait_for_service(timeout_sec=timeout_sec):
                f_g = self.clear_global_costmap_client.call_async(ClearEntireCostmap.Request())
                rclpy.spin_until_future_complete(self, f_g, timeout_sec=timeout_sec)
                result["global_cleared"] = f_g.done()
            if self.clear_local_costmap_client.wait_for_service(timeout_sec=timeout_sec):
                f_l = self.clear_local_costmap_client.call_async(ClearEntireCostmap.Request())
                rclpy.spin_until_future_complete(self, f_l, timeout_sec=timeout_sec)
                result["local_cleared"] = f_l.done()
        except Exception as e:
            self.log(f"[WARN] Diagnostic costmap purge error: {e}")
        return result

    def check_model_in_gazebo_states(self, model_name: str, wall_timeout_sec: float = 3.0) -> bool:
        """Verify whether a model is present in /gazebo/model_states within the given wall timeout."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            # latest_gt_record is from ModelStates callback; the callback stores all model names
            # We directly subscribe to model_states for verification
            if hasattr(self, "_gazebo_model_names") and model_name in self._gazebo_model_names:
                return True
            time.sleep(0.05)
        return False

    def check_model_absent_from_gazebo_states(self, model_name: str, wall_timeout_sec: float = 5.0) -> bool:
        """Verify whether a model is absent from /gazebo/model_states within the given wall timeout."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if hasattr(self, "_gazebo_model_names") and model_name not in self._gazebo_model_names:
                return True
            time.sleep(0.05)
        return False

    def get_corridor_laser_sector_summary(
        self,
        sector_min_rad: float = -0.5,
        sector_max_rad: float = 0.5,
    ) -> Dict[str, Any]:
        """Sample the lidar sector ahead (sector_min_rad to sector_max_rad relative to robot front).
        
        Returns a snapshot of range distances in the specified angular sector.
        This is used to provide physical evidence that the obstacle is/isn't present.
        """
        if not self.latest_scan_record:
            return {"available": False, "reason": "NO_SCAN_RECORD"}
        scan = self._latest_raw_scan
        if scan is None:
            return {"available": False, "reason": "NO_RAW_SCAN"}
        
        ranges = list(scan.ranges)
        n = len(ranges)
        if n == 0:
            return {"available": False, "reason": "EMPTY_RANGES"}
        
        angle_min = scan.angle_min
        angle_increment = scan.angle_increment
        range_min = scan.range_min
        range_max = scan.range_max
        sim_stamp = round(scan.header.stamp.sec + scan.header.stamp.nanosec * 1e-9, 4)
        
        sector_ranges = []
        for i, r in enumerate(ranges):
            angle = angle_min + i * angle_increment
            if sector_min_rad <= angle <= sector_max_rad:
                if math.isfinite(r) and range_min <= r <= range_max:
                    sector_ranges.append(round(r, 4))
        
        return {
            "available": True,
            "sector_min_rad": sector_min_rad,
            "sector_max_rad": sector_max_rad,
            "sector_range_count": len(sector_ranges),
            "sector_min_range_m": round(min(sector_ranges), 4) if sector_ranges else None,
            "sector_max_range_m": round(max(sector_ranges), 4) if sector_ranges else None,
            "sector_mean_range_m": round(sum(sector_ranges) / len(sector_ranges), 4) if sector_ranges else None,
            "all_ranges_in_sector": sector_ranges,
            "scan_stamp_sec": sim_stamp,
        }

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

    # Passive settling (observe only, no cmd_vel injection)
    settled_ok, safety_int = node.wait_for_passive_settling(max_sim_sec=2.5)
    node.sticky_safety_intervention = (node.sticky_safety_intervention or safety_int)
    # NOTE: initialize_amcl_pose is NOT called here. Post-navigation AMCL must come
    # from natural sensor updates only. Any staleness will be reflected honestly in scoring.

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
    cleanup_simulation_processes()
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


def save_attempt_evidence(attempt_dir: Path, gt_samples: List[Dict[str, Any]], odom_samples: List[Dict[str, Any]], stability_samples: List[Dict[str, Any]], action_summary: Dict[str, Any]):
    """Save per-attempt evidence (trajectory, stability window, action summary) to dedicated subdirectory."""
    attempt_dir.mkdir(parents=True, exist_ok=True)
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
    with open(attempt_dir / "trajectory.json", "w", encoding="utf-8") as f:
        json.dump(traj, f, indent=2)
    with open(attempt_dir / "stability_window.json", "w", encoding="utf-8") as f:
        json.dump(stability_samples, f, indent=2)
    with open(attempt_dir / "action_summary.json", "w", encoding="utf-8") as f:
        json.dump(action_summary, f, indent=2)


def main():
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    run_id = f"p1c_{timestamp_str}_{rand_suffix}"
    evidence_base = Path("/workspace/reports/evidence/p1c") if Path("/workspace").exists() else Path("reports/evidence/p1c")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"=======================================================================")
    print(f"FailMem P1c Blockage Pilot Runner (v2): {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")

    # ── Load and checksum protocol config ──────────────────────────────────────
    protocol_yaml_path = Path("configs/p1c_blockage_protocol.yaml")
    if not protocol_yaml_path.exists():
        protocol_yaml_path = Path("/workspace/configs/p1c_blockage_protocol.yaml")
    protocol_raw = protocol_yaml_path.read_bytes()
    protocol_sha256 = hashlib.sha256(protocol_raw).hexdigest()
    with open(protocol_yaml_path, "r", encoding="utf-8") as f:
        protocol_config = yaml.safe_load(f)
    print(f"Protocol v{protocol_config.get('version','?')} SHA256: {protocol_sha256}")

    # ── Extract all runtime parameters from YAML ────────────────────────────────
    env_cfg    = protocol_config.get("environment", {})
    nav_cfg    = protocol_config.get("navigation_task", {})
    obs_cfg    = protocol_config.get("obstacle_channel", {})
    thresh_cfg = protocol_config.get("scoring_thresholds", {})

    spawn_pose_cfg = env_cfg.get("spawn_pose", {})
    spawn_x    = float(spawn_pose_cfg.get("x", -2.0))
    spawn_y    = float(spawn_pose_cfg.get("y", -0.5))
    spawn_yaw  = float(spawn_pose_cfg.get("yaw", 0.0))

    goal_pose_cfg = nav_cfg.get("goal_pose", {})
    target_goal = [
        float(goal_pose_cfg.get("x", 0.5)),
        float(goal_pose_cfg.get("y", -0.5)),
        float(goal_pose_cfg.get("yaw", 0.0)),
    ]
    sim_timeout_sec  = float(nav_cfg.get("sim_timeout_sec", 45.0))
    wall_watchdog_sec = float(nav_cfg.get("wall_watchdog_sec", 60.0))

    obs_pose_cfg = obs_cfg.get("pose", {})
    obstacle_x   = float(obs_pose_cfg.get("x", -1.1))
    obstacle_y   = float(obs_pose_cfg.get("y", -0.55))
    obstacle_z   = float(obs_pose_cfg.get("z", 0.30))
    obstacle_name = obs_cfg.get("entity_name", "corridor_blockage_box")

    obstacle_sdf_path = Path(obs_cfg.get("obstacle_sdf", "configs/blockage_box.sdf"))
    if not obstacle_sdf_path.exists():
        obstacle_sdf_path = Path("/workspace") / obstacle_sdf_path
    if not obstacle_sdf_path.exists():
        obstacle_sdf_path = Path("/workspace/configs/blockage_box.sdf")

    thresholds = {
        "position_tolerance_m": float(thresh_cfg.get("position_tolerance_m", 0.30)),
        "yaw_tolerance_rad":    float(thresh_cfg.get("yaw_tolerance_rad", 0.35)),
        "max_linear_velocity_mps":    float(thresh_cfg.get("max_linear_velocity_mps", 0.05)),
        "max_angular_velocity_radps": float(thresh_cfg.get("max_angular_velocity_radps", 0.05)),
        "stability_window_duration_sim_sec": float(thresh_cfg.get("stability_window_duration_sim_sec", 2.0)),
        "max_gt_displacement_m":      float(thresh_cfg.get("max_gt_displacement_m", 0.03)),
        "max_sensor_staleness_sim_sec": float(thresh_cfg.get("max_sensor_staleness_sim_sec", 0.50)),
        "max_stationary_amcl_staleness_sec": float(thresh_cfg.get("max_stationary_amcl_staleness_sec", 30.0)),
    }

    # Save resolved runtime config
    runtime_config = {
        "run_id": run_id,
        "protocol_sha256": protocol_sha256,
        "protocol_version": protocol_config.get("version"),
        "spawn_pose": [spawn_x, spawn_y, spawn_yaw],
        "target_goal": target_goal,
        "sim_timeout_sec": sim_timeout_sec,
        "wall_watchdog_sec": wall_watchdog_sec,
        "obstacle_pose": [obstacle_x, obstacle_y, obstacle_z],
        "obstacle_name": obstacle_name,
        "obstacle_sdf_path": str(obstacle_sdf_path),
        "thresholds": thresholds,
    }
    with open(run_dir / "runtime_config.json", "w", encoding="utf-8") as f:
        json.dump(runtime_config, f, indent=2)

    print(f"Unified sim_timeout_sec={sim_timeout_sec}s, wall_watchdog_sec={wall_watchdog_sec}s (all conditions)")
    print(f"Target goal: {target_goal}, Spawn: [{spawn_x}, {spawn_y}, {spawn_yaw}]")
    print(f"Obstacle: {obstacle_name} at [{obstacle_x}, {obstacle_y}, {obstacle_z}]")

    # ── Coordinate alignment proof ───────────────────────────────────────────────
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
        "phase": "P1c-blockage-pilot-v2",
        "protocol_sha256": protocol_sha256,
        "protocol_version": protocol_config.get("version"),
        "runtime_config": runtime_config,
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
        "overall_status": "IN_PROGRESS",
    }

    # ── Episode Plan: 3×C0, 3×C1, 3×C2 ─────────────────────────────────────────
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
        cond   = plan["condition"]
        ep_num = plan["ep_num"]
        ep_dir = run_dir / plan["dir_name"]
        ep_dir.mkdir(parents=True, exist_ok=True)
        events_log = open(ep_dir / "events.log", "w", encoding="utf-8")

        def log_ep(msg: str, _events_log=events_log):
            line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
            print(line, flush=True)
            _events_log.write(line + "\n")
            _events_log.flush()

        log_ep(f"=== Starting Episode {plan['dir_name']} (Condition {cond} #{ep_num}) ===")
        log_ep(f"Protocol: sim_timeout={sim_timeout_sec}s, wall_watchdog={wall_watchdog_sec}s")
        sim_proc, env = spawn_simulation(ep_dir)
        rclpy.init()
        ep_data: Dict[str, Any] = {
            "episode_id": plan["dir_name"],
            "condition": cond,
            "episode_number": ep_num,
            "target_goal": target_goal,
            "spawn_pose": [spawn_x, spawn_y, spawn_yaw],
            "protocol_sha256": protocol_sha256,
            "infrastructure_error": None,
        }

        try:
            node = P1cRunnerNode(f"p1c_{plan['dir_name']}", log_ep)

            # ── Strict Readiness Checks ────────────────────────────────────────
            if not node.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=40.0):
                ep_data["infrastructure_error"] = "SIM_CLOCK_FAILED"
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Sim clock failed")
                raise RuntimeError("Simulation clock failed to advance")
            if not node.wait_for_sensors(wall_timeout_sec=50.0):
                ep_data["infrastructure_error"] = "SENSORS_NOT_STREAMING"
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Sensors failed")
                raise RuntimeError("Sensors not streaming")
            # AMCL init: only permitted at episode startup at spawn pose
            if not node.initialize_amcl_pose(x=spawn_x, y=spawn_y, yaw=spawn_yaw, wall_timeout_sec=35.0):
                ep_data["infrastructure_error"] = "AMCL_CONVERGENCE_FAILED"
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: AMCL failed")
                raise RuntimeError("AMCL pose failed to converge at spawn pose")
            if not node.wait_for_nav2_active(wall_timeout_sec=50.0):
                ep_data["infrastructure_error"] = "NAV2_NOT_ACTIVE"
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Nav2 inactive")
                raise RuntimeError("Nav2 lifecycle not ACTIVE")
            if not node.action_client.wait_for_server(timeout_sec=45.0):
                ep_data["infrastructure_error"] = "ACTION_SERVER_UNAVAILABLE"
                pilot_results["readiness_failures"].append(f"{plan['dir_name']}: Server unavailable")
                raise RuntimeError("Action server unavailable")

            context    = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
            dispatcher = ActionDispatcher(context=context, run_id=run_id, episode_id=plan["dir_name"])
            dispatcher.ros_observer = lambda act: node.get_live_observation(
                target_id=act.get("params", {}).get("target_id")
            )

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
            # task_success expected: True (arrives at goal)
            # mechanism_verified: direct navigation without obstacle
            # =================================================================
            if cond == "C0":
                obs1 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_initial",
                    "params": {"target_id": "initial_scan"},
                })
                log_ep(f"C0 Step 1 Observe: status={obs1.get('ros_result', {}).get('status')}")

                nav_act = {
                    "action": "navigate", "action_id": f"{plan['dir_name']}_nav",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": sim_timeout_sec},
                }
                step2_sum, nav_eval, stab_recs = execute_navigation_action(
                    node=node, dispatcher=dispatcher, action_dict=nav_act,
                    logger=log_ep, thresholds=thresholds,
                )
                log_ep(f"C0 Navigate: outcome={step2_sum['execution_outcome']}, terminal={step2_sum['terminal_status_name']}")

                obs2 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_final",
                    "params": {"target_id": "final_scan"},
                })
                log_ep(f"C0 Step 3 Final Observe: status={obs2.get('ros_result', {}).get('status')}")

                # Per-attempt evidence
                save_attempt_evidence(
                    ep_dir / "initial_attempt",
                    node.episode_gt_samples, node.episode_odom_samples, stab_recs,
                    {"step_summary": step2_sum, "evaluation": nav_eval},
                )

                final_gt = node.latest_gt_record
                gt_pos_err = (
                    round(math.hypot(final_gt["x"] - target_goal[0], final_gt["y"] - target_goal[1]), 4)
                    if final_gt else None
                )
                task_success = nav_eval.get("strict_physical_arrival_and_stable", False)
                mechanism_verified = task_success  # C0: mechanism = direct arrival

                ep_data.update({
                    "obstacle_present": False,
                    "collision_state": "UNKNOWN",
                    "step1_observe": obs1,
                    "step2_navigate": step2_sum,
                    "step3_observe": obs2,
                    "final_gt_pos_error_m": gt_pos_err,
                    "evaluation": nav_eval,
                    "task_success": task_success,
                    "mechanism_verified": mechanism_verified,
                    "execution_outcome": step2_sum["execution_outcome"],
                    "terminal_status_name": step2_sum["terminal_status_name"],
                    "action_history": context.action_history,
                })
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C0_baseline_episodes"].append(ep_data)

            # =================================================================
            # CONDITION C1: Continuous Obstacle Blockage
            # task_success expected: False (robot blocked, does not arrive)
            # mechanism_verified: obstacle present + navigation fails in budget
            # Requires: obstacle service OK + gazebo model confirmed + scan evidence
            # =================================================================
            elif cond == "C1":
                log_ep(f"C1: Spawning obstacle at ({obstacle_x}, {obstacle_y}, {obstacle_z})...")
                spawn_service_ok = node.spawn_obstacle(
                    name=obstacle_name, sdf_path=obstacle_sdf_path,
                    x=obstacle_x, y=obstacle_y, z=obstacle_z,
                )
                # Verify spawn via model_states
                spawn_gazebo_confirmed = False
                if spawn_service_ok:
                    spawn_gazebo_confirmed = node.check_model_in_gazebo_states(obstacle_name, wall_timeout_sec=5.0)
                log_ep(f"C1: spawn service_ok={spawn_service_ok}, gazebo_confirmed={spawn_gazebo_confirmed}")

                if not spawn_service_ok or not spawn_gazebo_confirmed:
                    ep_data["infrastructure_error"] = "OBSTACLE_SPAWN_FAILED"
                    raise RuntimeError(f"Failed to spawn+confirm obstacle in {plan['dir_name']}")

                # Allow 2.0s sim time for lidar and costmap integration
                t_sp = node.get_sim_time_sec()
                while node.get_sim_time_sec() - t_sp < 2.0:
                    rclpy.spin_once(node, timeout_sec=0.04)

                # Scan evidence: capture sector summary before navigation
                scan_before = node.get_corridor_laser_sector_summary()
                log_ep(f"C1: Pre-nav scan sector: min_range={scan_before.get('sector_min_range_m')}m, count={scan_before.get('sector_range_count')}")

                obs1 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_initial",
                    "params": {"target_id": "initial_scan"},
                })
                log_ep(f"C1 Observe: status={obs1.get('ros_result', {}).get('status')}, min_range={obs1.get('ros_result', {}).get('observation', {}).get('laser_scan', {}).get('min_distance_m')}")

                # Navigate with YAML-specified timeout (NOT hardcoded 30s)
                nav_act = {
                    "action": "navigate", "action_id": f"{plan['dir_name']}_nav_blocked",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": sim_timeout_sec},
                }
                step_nav_sum, nav_eval, stab_recs = execute_navigation_action(
                    node=node, dispatcher=dispatcher, action_dict=nav_act,
                    logger=log_ep, thresholds=thresholds,
                )
                log_ep(f"C1 Navigate: outcome={step_nav_sum['execution_outcome']}, terminal={step_nav_sum['terminal_status_name']}")

                obs2 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_post",
                    "params": {"target_id": "post_failure_scan"},
                })
                log_ep(f"C1 Post-Navigate Observe: status={obs2.get('ros_result', {}).get('status')}")

                # Per-attempt evidence
                save_attempt_evidence(
                    ep_dir / "initial_attempt",
                    node.episode_gt_samples, node.episode_odom_samples, stab_recs,
                    {"step_summary": step_nav_sum, "evaluation": nav_eval},
                )

                final_gt = node.latest_gt_record
                dist_to_goal = (
                    math.hypot(final_gt["x"] - target_goal[0], final_gt["y"] - target_goal[1])
                    if final_gt else None
                )

                # task_success = did robot arrive at goal? (Expected: False for C1)
                task_success = nav_eval.get("strict_physical_arrival_and_stable", False)

                # mechanism_verified: strict requirements
                #  1. Obstacle service confirmed + gazebo presence confirmed
                #  2. Scan shows close obstacle (evidence of perception)
                #  3. Navigation did NOT succeed (BUDGET_SUCCESS must be False)
                #  4. Robot halted far from goal (>0.50m)
                #  5. Outcome is not an infrastructure error (not UNKNOWN/ERROR)
                nav_outcome = step_nav_sum["execution_outcome"]
                nav_terminal = step_nav_sum["terminal_status_name"]
                scan_evidence_ok = (
                    scan_before.get("available", False)
                    and scan_before.get("sector_min_range_m") is not None
                    and scan_before.get("sector_min_range_m") < 1.5
                )
                not_infra_error = nav_outcome not in ("EXECUTION_ERROR", "EXECUTION_UNKNOWN")
                not_arrived = not task_success
                far_from_goal = (dist_to_goal is not None and dist_to_goal > 0.50)
                mechanism_verified = (
                    spawn_service_ok
                    and spawn_gazebo_confirmed
                    and scan_evidence_ok
                    and not_infra_error
                    and not_arrived
                    and far_from_goal
                )
                log_ep(f"C1 mechanism_verified={mechanism_verified}: scan_ok={scan_evidence_ok}, not_arrived={not_arrived}, far={far_from_goal}, not_infra={not_infra_error}")

                ep_data.update({
                    "obstacle_present": True,
                    "obstacle_spawned_service": spawn_service_ok,
                    "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                    "obstacle_pose": [obstacle_x, obstacle_y, obstacle_z],
                    "collision_state": "UNKNOWN",
                    "scan_before_navigate": scan_before,
                    "step1_observe": obs1,
                    "step2_navigate_blocked": step_nav_sum,
                    "step3_observe_post": obs2,
                    "final_dist_to_goal_m": round(dist_to_goal, 4) if dist_to_goal is not None else None,
                    "evaluation": nav_eval,
                    "task_success": task_success,
                    "mechanism_verified": mechanism_verified,
                    "execution_outcome": nav_outcome,
                    "terminal_status_name": nav_terminal,
                    "action_history": context.action_history,
                })
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C1_continuous_blockage_episodes"].append(ep_data)

            # =================================================================
            # CONDITION C2: Temporary Blockage (Observe -> Remove -> Retry)
            # task_success expected: True (retry arrives)
            # mechanism_verified: initial blocked + natural costmap clear + retry arrives
            # NO clear_costmaps() in primary experiment
            # NO odom-as-amcl spoofing
            # =================================================================
            elif cond == "C2":
                log_ep(f"C2: Spawning temporary obstacle at ({obstacle_x}, {obstacle_y}, {obstacle_z})...")
                spawn_service_ok = node.spawn_obstacle(
                    name=obstacle_name, sdf_path=obstacle_sdf_path,
                    x=obstacle_x, y=obstacle_y, z=obstacle_z,
                )
                spawn_gazebo_confirmed = False
                if spawn_service_ok:
                    spawn_gazebo_confirmed = node.check_model_in_gazebo_states(obstacle_name, wall_timeout_sec=5.0)
                log_ep(f"C2: spawn service_ok={spawn_service_ok}, gazebo_confirmed={spawn_gazebo_confirmed}")

                if not spawn_service_ok or not spawn_gazebo_confirmed:
                    ep_data["infrastructure_error"] = "OBSTACLE_SPAWN_FAILED"
                    raise RuntimeError(f"Failed to spawn+confirm obstacle in {plan['dir_name']}")

                # Allow 2.0s sim time for lidar and costmap integration
                t_sp = node.get_sim_time_sec()
                while node.get_sim_time_sec() - t_sp < 2.0:
                    rclpy.spin_once(node, timeout_sec=0.04)

                # Scan evidence before initial navigate
                scan_blocked = node.get_corridor_laser_sector_summary()
                log_ep(f"C2: Pre-initial-nav scan: min_range={scan_blocked.get('sector_min_range_m')}m")

                obs1 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_initial",
                    "params": {"target_id": "initial_scan"},
                })
                log_ep(f"C2 Initial Observe: status={obs1.get('ros_result', {}).get('status')}")

                # Step: Initial Navigate (YAML timeout, no hardcoded 25s)
                nav_act_orig_id = f"{plan['dir_name']}_nav_orig"
                nav_act_orig = {
                    "action": "navigate", "action_id": nav_act_orig_id,
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": sim_timeout_sec},
                }
                # Snapshot GT/odom BEFORE tracking starts (episode_*_samples reset in start_tracking)
                step_orig_sum, nav1_eval, stab1_recs = execute_navigation_action(
                    node=node, dispatcher=dispatcher, action_dict=nav_act_orig,
                    logger=log_ep, thresholds=thresholds,
                )
                # Snapshot initial attempt samples BEFORE next tracking call resets them
                initial_gt_samples   = list(node.episode_gt_samples)
                initial_odom_samples = list(node.episode_odom_samples)
                log_ep(f"C2 Initial blocked nav: outcome={step_orig_sum['execution_outcome']}, terminal={step_orig_sum['terminal_status_name']}")

                # Save initial_attempt evidence immediately (before start_tracking() in retry clears them)
                save_attempt_evidence(
                    ep_dir / "initial_attempt",
                    initial_gt_samples, initial_odom_samples, stab1_recs,
                    {"step_summary": step_orig_sum, "evaluation": nav1_eval},
                )

                # Verify initial failure is genuine blockage (not infrastructure error)
                initial_outcome = step_orig_sum["execution_outcome"]
                initial_failed_genuine = (
                    initial_outcome not in ("BUDGET_SUCCESS", "EXECUTION_ERROR", "EXECUTION_UNKNOWN")
                )

                # Step: Delete obstacle from Gazebo
                log_ep(f"C2: Deleting obstacle '{obstacle_name}'...")
                del_service_ok = node.delete_obstacle(name=obstacle_name)
                del_gazebo_confirmed = False
                if del_service_ok:
                    del_gazebo_confirmed = node.check_model_absent_from_gazebo_states(obstacle_name, wall_timeout_sec=5.0)
                log_ep(f"C2: del service_ok={del_service_ok}, gazebo_absent={del_gazebo_confirmed}")

                if not del_service_ok:
                    ep_data["infrastructure_error"] = "OBSTACLE_DELETE_FAILED"
                    raise RuntimeError(f"Failed to delete obstacle in {plan['dir_name']}")

                # PRIMARY EXPERIMENT: NO clear_costmaps() here.
                # Wait for natural lidar raytrace to update costmap.
                # Use 3.0s sim time natural dwell + scan freshness condition.
                t_del = node.get_sim_time_sec()
                log_ep("C2: Waiting for natural lidar raytrace to update costmap (no service purge)...")
                # Bounded wait: up to 3.0s sim time or wall 10s, then proceed regardless
                wall_natural_wait_start = time.monotonic()
                while (node.get_sim_time_sec() - t_del < 3.0) and (time.monotonic() - wall_natural_wait_start < 10.0):
                    rclpy.spin_once(node, timeout_sec=0.04)

                # Scan evidence after obstacle removal
                scan_cleared = node.get_corridor_laser_sector_summary()
                log_ep(f"C2: Post-removal scan: min_range={scan_cleared.get('sector_min_range_m')}m (vs blocked={scan_blocked.get('sector_min_range_m')}m)")

                # Step: Post-removal observe – MUST use dispatcher, no pose injection
                obs2 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_post_removal",
                    "params": {"target_id": "post_removal_scan"},
                })
                log_ep(f"C2 Post-removal Observe: status={obs2.get('ros_result', {}).get('status')}")

                # Determine visible_state for retry STRICTLY from observe result
                # Do NOT use odom as amcl_pose, do NOT inject fixed fallback coordinates
                obs_result = obs2.get("ros_result", {})
                obs_status = obs_result.get("status")
                obs_localization = obs_result.get("observation", {}).get("localization", {}) if obs_result.get("observation") else {}
                amcl_pose_from_obs = obs_localization.get("pose")  # [x, y, yaw] from AMCL or None
                amcl_status_from_obs = obs_localization.get("status", "UNKNOWN")

                retry_visible_state: Optional[Dict[str, Any]] = None
                observation_available = False
                if obs_status in ("VALID", "DEGRADED") and amcl_pose_from_obs is not None:
                    # Only use AMCL pose if observation is valid and frame is map
                    retry_visible_state = {"amcl_pose": amcl_pose_from_obs}
                    observation_available = True
                    log_ep(f"C2: Retry visible_state from AMCL observe: pose={amcl_pose_from_obs}, amcl_status={amcl_status_from_obs}")
                else:
                    # Observation unavailable – do NOT fabricate pose, record as OBSERVATION_UNAVAILABLE
                    log_ep(f"C2: Post-removal observe status={obs_status}, amcl_status={amcl_status_from_obs}. Recording OBSERVATION_UNAVAILABLE.")
                    ep_data.update({
                        "obstacle_present": True,
                        "obstacle_spawned_service": spawn_service_ok,
                        "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                        "obstacle_deleted_service": del_service_ok,
                        "obstacle_delete_gazebo_confirmed": del_gazebo_confirmed,
                        "collision_state": "UNKNOWN",
                        "scan_before_initial_navigate": scan_blocked,
                        "scan_after_removal": scan_cleared,
                        "step1_observe": obs1,
                        "step2_initial_navigate": step_orig_sum,
                        "step3_post_removal_observe": obs2,
                        "initial_failed_genuine": initial_failed_genuine,
                        "observation_available": False,
                        "observation_unavailable_reason": f"obs_status={obs_status}, amcl_status={amcl_status_from_obs}",
                        "retry_execute": False,
                        "task_success": False,
                        "mechanism_verified": False,
                        "mechanism_failure_reason": "OBSERVATION_UNAVAILABLE_BEFORE_RETRY",
                        "action_history": context.action_history,
                    })
                    with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                        json.dump(ep_data, f, indent=2)
                    pilot_results["C2_temporary_blockage_episodes"].append(ep_data)
                    # No retry; finally block handles rclpy.shutdown and sim cleanup
                    # Use a flag to skip retry code below
                    observation_available = False
                    # Fall through to finally by setting a sentinel - do NOT continue here
                    # (finally must run; use ep_data to record that we stopped early)
                    ep_data["_skip_retry_done"] = True

                if observation_available:
                    # Step: Retry with parameters restored from original action
                    retry_act = {
                        "action": "retry", "action_id": f"{plan['dir_name']}_retry_nav",
                        "params": {"original_action_id": nav_act_orig_id},
                    }
                    step_retry_sum, retry_eval, stab2_recs = execute_navigation_action(
                        node=node, dispatcher=dispatcher, action_dict=retry_act,
                        logger=log_ep, thresholds=thresholds,
                        visible_state=retry_visible_state,
                    )
                    log_ep(f"C2 Retry nav: outcome={step_retry_sum['execution_outcome']}, arrival={retry_eval.get('strict_physical_arrival_and_stable')}")

                    # Save retry_attempt evidence
                    save_attempt_evidence(
                        ep_dir / "retry_attempt",
                        node.episode_gt_samples, node.episode_odom_samples, stab2_recs,
                        {"step_summary": step_retry_sum, "evaluation": retry_eval},
                    )

                    # Post-retry final observe
                    obs3 = dispatcher.dispatch({
                        "action": "observe", "action_id": f"{plan['dir_name']}_obs_final",
                        "params": {"target_id": "final_scan"},
                    })
                    log_ep(f"C2 Final Observe: status={obs3.get('ros_result', {}).get('status')}")

                    final_gt = node.latest_gt_record
                    gt_pos_err_retry = (
                        round(math.hypot(final_gt["x"] - target_goal[0], final_gt["y"] - target_goal[1]), 4)
                        if final_gt else None
                    )

                    # task_success: retry arrives at goal
                    task_success = retry_eval.get("strict_physical_arrival_and_stable", False)

                    scan_blocked_range = scan_blocked.get("sector_min_range_m")
                    scan_cleared_range = scan_cleared.get("sector_min_range_m")
                    natural_clearance_evidence = (
                        scan_blocked_range is not None
                        and scan_cleared_range is not None
                        and scan_cleared_range > scan_blocked_range + 0.10
                    )
                    mechanism_verified = (
                        spawn_service_ok
                        and spawn_gazebo_confirmed
                        and initial_failed_genuine
                        and del_service_ok
                        and del_gazebo_confirmed
                        and observation_available
                        and task_success
                    )
                    log_ep(f"C2 mechanism_verified={mechanism_verified}: spawn={spawn_service_ok}, init_fail={initial_failed_genuine}, del_ok={del_gazebo_confirmed}, obs_ok={observation_available}, task_ok={task_success}")

                    ep_data.update({
                        "obstacle_present": True,
                        "obstacle_spawned_service": spawn_service_ok,
                        "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                        "obstacle_deleted_service": del_service_ok,
                        "obstacle_delete_gazebo_confirmed": del_gazebo_confirmed,
                        "collision_state": "UNKNOWN",
                        "scan_before_initial_navigate": scan_blocked,
                        "scan_after_removal": scan_cleared,
                        "natural_clearance_evidence": natural_clearance_evidence,
                        "step1_observe": obs1,
                        "step2_initial_navigate": step_orig_sum,
                        "step3_post_removal_observe": obs2,
                        "retry_visible_state_source": "AMCL_FROM_OBSERVE",
                        "retry_visible_state": retry_visible_state,
                        "step4_retry_navigate": step_retry_sum,
                        "step5_observe_final": obs3,
                        "final_gt_pos_error_m_retry": gt_pos_err_retry,
                        "initial_failed_genuine": initial_failed_genuine,
                        "observation_available": True,
                        "retry_execute": True,
                        "task_success": task_success,
                        "mechanism_verified": mechanism_verified,
                        "evaluation_initial": nav1_eval,
                        "evaluation_retry": retry_eval,
                        "action_history": context.action_history,
                    })
                    with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                        json.dump(ep_data, f, indent=2)
                    pilot_results["C2_temporary_blockage_episodes"].append(ep_data)
                # If not observation_available, ep_data already saved and appended above

        except Exception as exc:
            log_ep(f"[ERROR] Episode {plan['dir_name']} failed with exception: {exc}")
            if ep_data.get("infrastructure_error") is None:
                ep_data["infrastructure_error"] = f"EXCEPTION: {exc}"
            ep_data["task_success"] = False
            ep_data["mechanism_verified"] = False
            with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                json.dump(ep_data, f, indent=2)
            # Append to correct results list
            if cond == "C0":
                pilot_results["C0_baseline_episodes"].append(ep_data)
            elif cond == "C1":
                pilot_results["C1_continuous_blockage_episodes"].append(ep_data)
            elif cond == "C2":
                pilot_results["C2_temporary_blockage_episodes"].append(ep_data)
        finally:
            try:
                rclpy.shutdown()
            except Exception:
                pass
            try:
                kill_process_group(os.getpgid(sim_proc.pid))
            except Exception:
                pass
            cleanup_simulation_processes()
            events_log.close()

    # ── Overall Status Computation ─────────────────────────────────────────────
    c0_eps = pilot_results["C0_baseline_episodes"]
    c1_eps = pilot_results["C1_continuous_blockage_episodes"]
    c2_eps = pilot_results["C2_temporary_blockage_episodes"]

    c0_task_ok = len(c0_eps) == 3 and all(ep.get("task_success", False) for ep in c0_eps)
    c0_mech_ok = len(c0_eps) == 3 and all(ep.get("mechanism_verified", False) for ep in c0_eps)

    c1_task_ok = True  # C1 task_success is expected to be False; evaluate mechanism separately
    c1_mech_ok = len(c1_eps) == 3 and all(ep.get("mechanism_verified", False) for ep in c1_eps)
    c1_no_spurious_arrive = all(not ep.get("task_success", True) for ep in c1_eps)

    c2_task_ok = len(c2_eps) == 3 and all(ep.get("task_success", False) for ep in c2_eps)
    c2_mech_ok = len(c2_eps) == 3 and all(ep.get("mechanism_verified", False) for ep in c2_eps)

    coord_ok = pilot_results["coordinate_alignment"]["verified"]

    all_ok = c0_task_ok and c0_mech_ok and c1_mech_ok and c1_no_spurious_arrive and c2_task_ok and c2_mech_ok and coord_ok
    pilot_results["overall_status"] = "PASSED" if all_ok else "PARTIAL"
    pilot_results["summary_table"] = {
        "C0": {"task_success": c0_task_ok, "mechanism_verified": c0_mech_ok, "episode_count": len(c0_eps)},
        "C1": {"no_spurious_arrival": c1_no_spurious_arrive, "mechanism_verified": c1_mech_ok, "episode_count": len(c1_eps)},
        "C2": {"task_success": c2_task_ok, "mechanism_verified": c2_mech_ok, "episode_count": len(c2_eps)},
        "coordinate_alignment": coord_ok,
    }

    # Save summary.json
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(pilot_results, f, indent=2)

    # Compute sha256 checksums
    checksums = compute_sha256_tree(run_dir)
    with open(run_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        for fname, h in checksums.items():
            f.write(f"{h}  {fname}\n")

    print(f"\n=======================================================================")
    print(f"P1c-v2 Pilot Execution Complete: {pilot_results['overall_status']}")
    print(f"C0 (Baseline): task_ok={c0_task_ok}, mech_ok={c0_mech_ok}  ({len(c0_eps)} eps)")
    print(f"C1 (Blocked):  no_spurious={c1_no_spurious_arrive}, mech_ok={c1_mech_ok}  ({len(c1_eps)} eps)")
    print(f"C2 (Retry):    task_ok={c2_task_ok}, mech_ok={c2_mech_ok}  ({len(c2_eps)} eps)")
    print(f"Coordinate alignment: {coord_ok}")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")


if __name__ == "__main__":
    main()
