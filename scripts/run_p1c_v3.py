#!/usr/bin/env python3
"""FailMem Milestone P1c-v3 Pilot Runner.

Evaluates Single-Fault Temporary Corridor Blockage on a dual-room single-doorway chokepoint arena:
- C0 (Unblocked Baseline): 3 episodes, normal navigation from Room 1 to Room 2.
- C1 (Continuous Blockage): 3 episodes, obstacle completely blocks doorway for full duration.
- C2 (Temporary Blockage): 3 episodes, observe -> initial blocked -> delete -> natural raytrace -> observe -> retry.

Strict Execution Rules:
- Complete removal of runtime initialize_amcl_pose() injection.
- Natural laser raytracing only (no service-driven costmap purges).
- Real AMCL /request_nomotion_update service used when stationary.
- Map-frame spatial doorway clearance verification.
- Distinct per-attempt evidence directories: initial_attempt/ and retry_attempt/.
- Complete separation of task_success and mechanism_verified.
"""

from __future__ import annotations

import argparse
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
from datetime import datetime, timezone
from pathlib import Path

# Ensure repository root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

import yaml
from PIL import Image
import numpy as np

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data

from geometry_msgs.msg import PoseWithCovarianceStamped, Twist, Pose, Point, Quaternion
from nav_msgs.msg import Odometry, OccupancyGrid
from sensor_msgs.msg import LaserScan
from gazebo_msgs.msg import ModelStates
from gazebo_msgs.srv import SpawnEntity, DeleteEntity
from nav2_msgs.action import NavigateToPose
from nav2_msgs.srv import ClearEntireCostmap
from lifecycle_msgs.srv import GetState
from std_srvs.srv import Empty
from unique_identifier_msgs.msg import UUID as RosUUID
import tf2_ros

from src.observe_interface import ObserveInterface
from src.action_dispatcher import ActionDispatcher
from src.action_runtime import EpisodeActionHistoryContext
from src.terminal_resolution import await_nav_goal_terminal_result
from src.scoring_evaluator import (
    evaluate_navigation_episode,
    evaluate_physical_halt,
    load_scoring_rules,
)
from src.coordinate_alignment import verify_world_map_alignment
from src.doorway_evaluator import (
    evaluate_doorway_clearance,
    extract_costmap_doorway_subgrid,
    project_laser_scan_rays_tf,
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


class P1cV3RunnerNode(Node):
    """ROS 2 Node for P1c-v3 blockage pilot experiments."""

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
        self.nomotion_update_client = self.create_client(Empty, "/request_nomotion_update")

        # TF2 Buffer & Listener for map <- base_scan projection
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        # Subscriptions
        self.cmd_vel_sub = self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, "odom", self._odom_cb, 10)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "amcl_pose", self._amcl_cb, 10)
        self.scan_sub = self.create_subscription(LaserScan, "scan", self._scan_cb, qos_profile_sensor_data)
        self.costmap_sub = self.create_subscription(OccupancyGrid, "/global_costmap/costmap", self._costmap_cb, qos_profile_sensor_data)
        self.gazebo_sub = self.create_subscription(ModelStates, "/gazebo/model_states", self._gazebo_cb, qos_profile_sensor_data)

        self.latest_odom_record: Optional[Dict[str, Any]] = None
        self.latest_amcl_record: Optional[Dict[str, Any]] = None
        self.latest_scan_record: Optional[Dict[str, Any]] = None
        self.latest_costmap_record: Optional[Dict[str, Any]] = None
        self.latest_gt_record: Optional[Dict[str, Any]] = None
        self.latest_cmd_vel_record: Optional[Dict[str, Any]] = None
        self._latest_raw_scan: Any = None
        self._latest_raw_costmap: Optional[OccupancyGrid] = None
        self._gazebo_model_names: List[str] = []

        self.odom_msg_count = 0
        self.amcl_msg_count = 0
        self.scan_msg_count = 0
        self.costmap_msg_count = 0
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
        rec = {
            "seq": self.cmd_vel_msg_count,
            "recv_sim_time_sec": round(sim_now, 4),
            "linear_x": round(float(msg.linear.x), 4),
            "linear_y": round(float(msg.linear.y), 4),
            "angular_z": round(float(msg.angular.z), 4),
        }
        self.latest_cmd_vel_record = rec
        if self.is_tracking:
            self.episode_cmd_vel_samples.append(rec)

    def _odom_cb(self, msg: Odometry):
        self.odom_msg_count += 1
        sim_now = self.get_sim_time_sec()
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        rec = {
            "seq": self.odom_msg_count,
            "msg_stamp_sec": round(stamp_sec, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "x": round(float(msg.pose.pose.position.x), 4),
            "y": round(float(msg.pose.pose.position.y), 4),
            "yaw": round(quat_to_yaw(
                msg.pose.pose.orientation.x,
                msg.pose.pose.orientation.y,
                msg.pose.pose.orientation.z,
                msg.pose.pose.orientation.w,
            ), 4),
            "linear_v": round(float(msg.twist.twist.linear.x), 4),
            "angular_v": round(float(msg.twist.twist.angular.z), 4),
            "frame_id": msg.header.frame_id or "odom",
        }
        self.latest_odom_record = rec
        self.continuous_odom_buffer.append(rec)
        if self.is_tracking:
            self.episode_odom_samples.append(rec)

    def _amcl_cb(self, msg: PoseWithCovarianceStamped):
        self.amcl_msg_count += 1
        sim_now = self.get_sim_time_sec()
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        cov = [round(float(c), 6) for c in msg.pose.covariance]
        cov_diag = [cov[0], cov[7], cov[35]]
        rec = {
            "seq": self.amcl_msg_count,
            "msg_stamp_sec": round(stamp_sec, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "x": round(float(msg.pose.pose.position.x), 4),
            "y": round(float(msg.pose.pose.position.y), 4),
            "yaw": round(quat_to_yaw(
                msg.pose.pose.orientation.x,
                msg.pose.pose.orientation.y,
                msg.pose.pose.orientation.z,
                msg.pose.pose.orientation.w,
            ), 4),
            "covariance_diagonal": cov_diag,
            "frame_id": msg.header.frame_id or "map",
        }
        self.latest_amcl_record = rec
        if self.is_tracking:
            self.episode_amcl_samples.append(rec)

    def _scan_cb(self, msg: LaserScan):
        self.scan_msg_count += 1
        sim_now = self.get_sim_time_sec()
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        valid_ranges = [r for r in msg.ranges if math.isfinite(r) and msg.range_min <= r <= msg.range_max]
        min_r = min(valid_ranges) if valid_ranges else None
        self._latest_raw_scan = msg
        rec = {
            "seq": self.scan_msg_count,
            "msg_stamp_sec": round(stamp_sec, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "min_range": round(float(min_r), 4) if min_r is not None else None,
            "valid_count": len(valid_ranges),
            "total_count": len(msg.ranges),
            "frame_id": msg.header.frame_id or "base_scan",
        }
        self.latest_scan_record = rec
        if self.is_tracking:
            self.episode_scan_samples.append(rec)

    def _gazebo_cb(self, msg: ModelStates):
        self.gt_msg_count += 1
        sim_now = self.get_sim_time_sec()
        self._gazebo_model_names = list(msg.name)

        if "turtlebot3_waffle" not in msg.name:
            return
        idx = msg.name.index("turtlebot3_waffle")
        pose = msg.pose[idx]
        twist = msg.twist[idx]
        yaw = quat_to_yaw(pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w)
        rec = {
            "seq": self.gt_msg_count,
            "recv_sim_time_sec": round(sim_now, 4),
            "x": round(float(pose.position.x), 4),
            "y": round(float(pose.position.y), 4),
            "yaw": round(yaw, 4),
            "linear_v": round(float(math.hypot(twist.linear.x, twist.linear.y)), 4),
            "angular_v": round(float(twist.angular.z), 4),
        }
        self.latest_gt_record = rec
        if self.is_tracking:
            self.episode_gt_samples.append(rec)

    def request_nomotion_amcl_update(self, timeout_sec: float = 3.0) -> bool:
        """Explicitly request AMCL particle filter update from current laser scan when stationary.
        
        Uses standard /request_nomotion_update service.
        Verifies arrival of a new, valid AMCL message with strictly newer timestamp.
        """
        if not self.nomotion_update_client.service_is_ready():
            if not self.nomotion_update_client.wait_for_service(timeout_sec=1.0):
                self.log("[WARN] /request_nomotion_update service unavailable")
                return False

        prev_stamp = self.latest_amcl_record.get("msg_stamp_sec", 0.0) if self.latest_amcl_record else 0.0
        prev_seq = self.latest_amcl_record.get("seq", 0) if self.latest_amcl_record else 0

        req = Empty.Request()
        future = self.nomotion_update_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=timeout_sec)

        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.04)
            curr_stamp = self.latest_amcl_record.get("msg_stamp_sec", 0.0) if self.latest_amcl_record else 0.0
            curr_seq = self.latest_amcl_record.get("seq", 0) if self.latest_amcl_record else 0
            if curr_seq > prev_seq and curr_stamp > prev_stamp:
                self.log(f"AMCL nomotion update received: stamp {curr_stamp:.3f}s (seq={curr_seq})")
                return True
            time.sleep(0.02)

        self.log("[WARN] AMCL nomotion update timed out waiting for new amcl_pose message")
        return False

    def _costmap_cb(self, msg: OccupancyGrid):
        self.costmap_msg_count += 1
        sim_now = self.get_sim_time_sec()
        stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self._latest_raw_costmap = msg
        rec = {
            "seq": self.costmap_msg_count,
            "msg_stamp_sec": round(stamp_sec, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "width": msg.info.width,
            "height": msg.info.height,
            "resolution": round(float(msg.info.resolution), 4),
            "origin_x": round(float(msg.info.origin.position.x), 4),
            "origin_y": round(float(msg.info.origin.position.y), 4),
            "frame_id": msg.header.frame_id or "map",
        }
        self.latest_costmap_record = rec

    def get_laser_map_transform(self, stamp_sec: Optional[float] = None, timeout_sec: float = 0.5) -> Optional[Dict[str, Any]]:
        """Lookup TF transform from map to base_scan frame at exact timestamp."""
        try:
            target_time = rclpy.time.Time()
            if stamp_sec is not None:
                nanosec = int(round(stamp_sec * 1e9))
                target_time = rclpy.time.Time(nanoseconds=nanosec)
            transform = self.tf_buffer.lookup_transform(
                "map", "base_scan", target_time, timeout=rclpy.duration.Duration(seconds=timeout_sec)
            )
            t = transform.transform.translation
            r = transform.transform.rotation
            yaw = quat_to_yaw(r.x, r.y, r.z, r.w)
            return {
                "translation": [float(t.x), float(t.y), float(t.z)],
                "yaw": yaw,
                "stamp_sec": stamp_sec if stamp_sec is not None else (transform.header.stamp.sec + transform.header.stamp.nanosec * 1e-9),
                "frame_id": transform.header.frame_id,
                "child_frame_id": transform.child_frame_id,
            }
        except Exception:
            # Fallback: lookup latest transform if exact stamp not yet in buffer
            try:
                transform = self.tf_buffer.lookup_transform(
                    "map", "base_scan", rclpy.time.Time(), timeout=rclpy.duration.Duration(seconds=0.2)
                )
                t = transform.transform.translation
                r = transform.transform.rotation
                yaw = quat_to_yaw(r.x, r.y, r.z, r.w)
                return {
                    "translation": [float(t.x), float(t.y), float(t.z)],
                    "yaw": yaw,
                    "stamp_sec": stamp_sec if stamp_sec is not None else (transform.header.stamp.sec + transform.header.stamp.nanosec * 1e-9),
                    "frame_id": transform.header.frame_id,
                    "child_frame_id": transform.child_frame_id,
                }
            except Exception:
                return None

    def query_lifecycle_state(self, timeout_sec: float = 0.5) -> str:
        """Query real Nav2 lifecycle state."""
        if not self.lifecycle_client.service_is_ready():
            if not self.lifecycle_client.wait_for_service(timeout_sec=0.2):
                return "UNAVAILABLE"
        try:
            req = GetState.Request()
            future = self.lifecycle_client.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=timeout_sec)
            if future.done() and future.result():
                return future.result().current_state.label.upper()
        except Exception:
            pass
        return "UNKNOWN"

    def get_live_observation(self, wait_fresh: bool = True, timeout_sec: float = 2.0, refresh_amcl_if_stale: bool = True) -> Dict[str, Any]:
        """Extract live observation with real lifecycle & goal state query and nomotion AMCL refresh."""
        wall_start = time.monotonic()
        t0_sim = self.get_sim_time_sec()

        # Check if robot is stationary and AMCL is stale -> request nomotion update
        if refresh_amcl_if_stale and self.latest_odom_record:
            lv = abs(float(self.latest_odom_record.get("linear_v", 0.0)))
            av = abs(float(self.latest_odom_record.get("angular_v", 0.0)))
            if lv < 0.05 and av < 0.05:
                curr_sim = self.get_sim_time_sec()
                amcl_stamp = self.latest_amcl_record.get("msg_stamp_sec", 0.0) if self.latest_amcl_record else 0.0
                if (curr_sim - amcl_stamp) > 0.40:
                    self.request_nomotion_amcl_update(timeout_sec=1.5)

        if wait_fresh:
            while (time.monotonic() - wall_start) < timeout_sec:
                rclpy.spin_once(self, timeout_sec=0.04)
                curr_sim = self.get_sim_time_sec()
                odom_fresh = self.latest_odom_record and (curr_sim - self.latest_odom_record["recv_sim_time_sec"] <= 0.5)
                scan_fresh = self.latest_scan_record and (curr_sim - self.latest_scan_record["recv_sim_time_sec"] <= 0.5)
                if odom_fresh and scan_fresh:
                    break
                time.sleep(0.02)

        sim_now = self.get_sim_time_sec()
        wall_elapsed = time.monotonic() - wall_start
        clock_frozen = (wall_elapsed > 1.0 and abs(sim_now - t0_sim) < 0.01)

        # Real Nav2 lifecycle state
        lifecycle_state = self.query_lifecycle_state(timeout_sec=0.3)

        # Real goal status
        goal_status = "IDLE"
        if self.current_active_goal_handle is not None:
            gh_status = getattr(self.current_active_goal_handle, "status", None)
            if gh_status in (1, 2, 3):
                goal_status = "ACTIVE"

        obs_res = self.obs_interface.extract_observation(
            current_sim_time=sim_now,
            latest_amcl=self.latest_amcl_record,
            latest_odom=self.latest_odom_record,
            latest_scan=self.latest_scan_record,
            nav2_lifecycle_state=lifecycle_state,
            current_goal_status=goal_status,
            odom_history=list(self.continuous_odom_buffer),
            clock_frozen=clock_frozen,
        )
        obs_res["wall_duration_sec"] = round(time.monotonic() - wall_start, 4)
        return obs_res

    def evaluate_doorway_perception(
        self,
        doorway_bbox: Tuple[float, float, float, float] = (-0.20, 0.20, -0.30, 0.30),
        spin_for_fresh_sec: float = 0.5,
        refresh_amcl_if_stale: bool = True,
    ) -> Dict[str, Any]:
        """Perform rigorous 3-valued doorway clearance evaluation using TF laser projection & costmap subgrid."""
        # Ensure fresh AMCL if stationary
        if refresh_amcl_if_stale and self.latest_odom_record:
            lv = abs(float(self.latest_odom_record.get("linear_v", 0.0)))
            av = abs(float(self.latest_odom_record.get("angular_v", 0.0)))
            if lv < 0.05 and av < 0.05:
                curr_sim = self.get_sim_time_sec()
                amcl_stamp = self.latest_amcl_record.get("msg_stamp_sec", 0.0) if self.latest_amcl_record else 0.0
                if (curr_sim - amcl_stamp) > 0.40:
                    self.request_nomotion_amcl_update(timeout_sec=1.5)

        if spin_for_fresh_sec > 0.0:
            t0 = time.monotonic()
            prev_seq = self.latest_scan_record.get("seq", 0) if self.latest_scan_record else 0
            while time.monotonic() - t0 < spin_for_fresh_sec:
                rclpy.spin_once(self, timeout_sec=0.04)
                curr_seq = self.latest_scan_record.get("seq", 0) if self.latest_scan_record else 0
                if curr_seq > prev_seq + 1:
                    break
                time.sleep(0.02)

        if self._latest_raw_scan is None:
            return {
                "doorway_state": "UNKNOWN",
                "doorway_cleared": False,
                "reason": "SCAN_UNAVAILABLE",
                "doorway_bbox": list(doorway_bbox),
                "error": "LATEST_RAW_SCAN_IS_NONE",
            }

        scan = self._latest_raw_scan
        scan_stamp = scan.header.stamp.sec + scan.header.stamp.nanosec * 1e-9
        curr_sim = self.get_sim_time_sec()

        # Get TF map <- base_scan
        tf_info = self.get_laser_map_transform(stamp_sec=scan_stamp)
        tf_trans = tf_info["translation"] if tf_info else None
        tf_yaw = tf_info["yaw"] if tf_info else None
        tf_stamp = tf_info["stamp_sec"] if tf_info else None

        # Costmap subgrid extraction
        costmap_summary = None
        if self._latest_raw_costmap is not None:
            cm = self._latest_raw_costmap
            cm_stamp = cm.header.stamp.sec + cm.header.stamp.nanosec * 1e-9
            costmap_summary = extract_costmap_doorway_subgrid(
                costmap_data=list(cm.data),
                width=cm.info.width,
                height=cm.info.height,
                resolution=cm.info.resolution,
                origin_x=cm.info.origin.position.x,
                origin_y=cm.info.origin.position.y,
                doorway_bbox=doorway_bbox,
                costmap_stamp_sec=cm_stamp,
                current_sim_time=curr_sim,
            )

        doorway_res = evaluate_doorway_clearance(
            ranges=list(scan.ranges),
            angle_min=scan.angle_min,
            angle_increment=scan.angle_increment,
            range_min=scan.range_min,
            range_max=scan.range_max,
            tf_translation=tf_trans,
            tf_yaw=tf_yaw,
            tf_stamp_sec=tf_stamp,
            scan_stamp_sec=scan_stamp,
            current_sim_time=curr_sim,
            doorway_bbox=doorway_bbox,
            costmap_data_summary=costmap_summary,
        )
        # Backwards compatibility key
        doorway_res["doorway_cleared"] = (doorway_res["doorway_state"] == "FREE")
        doorway_res["points_count"] = doorway_res.get("hits_inside_count", 0)
        return doorway_res

    def check_doorway_clearance_evidence(
        self,
        doorway_bbox: Tuple[float, float, float, float] = (-0.20, 0.20, -0.30, 0.30),
        spin_for_fresh_sec: float = 0.5,
    ) -> Dict[str, Any]:
        """Wrapper for evaluate_doorway_perception."""
        return self.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=spin_for_fresh_sec)

    def check_model_in_gazebo_states(self, model_name: str, wall_timeout_sec: float = 3.0) -> bool:
        """Verify model presence in Gazebo model states."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.05)
            if model_name in self._gazebo_model_names:
                return True
            time.sleep(0.02)
        return model_name in self._gazebo_model_names

    def check_model_absent_from_gazebo_states(self, model_name: str, wall_timeout_sec: float = 3.0) -> bool:
        """Verify model absence from Gazebo model states."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.05)
            if model_name not in self._gazebo_model_names:
                return True
            time.sleep(0.02)
        return model_name not in self._gazebo_model_names

    def spawn_obstacle(self, name: str = "corridor_blockage_box", sdf_path: str = "configs/chokepoint_box.sdf", x: float = 0.0, y: float = 0.0, z: float = 0.30) -> bool:
        """Spawn obstacle box in Gazebo world."""
        if not self.spawn_entity_client.wait_for_service(timeout_sec=5.0):
            self.log("[ERROR] /spawn_entity service unavailable")
            return False

        full_sdf = Path(sdf_path)
        if not full_sdf.exists() and Path(f"/workspace/{sdf_path}").exists():
            full_sdf = Path(f"/workspace/{sdf_path}")

        with open(full_sdf, "r", encoding="utf-8") as f:
            xml = f.read()

        req = SpawnEntity.Request()
        req.name = name
        req.xml = xml
        req.initial_pose = Pose(position=Point(x=x, y=y, z=z), orientation=Quaternion(x=0.0, y=0.0, z=0.0, w=1.0))
        req.reference_frame = "world"

        future = self.spawn_entity_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        res = future.result()
        if res and res.success:
            self.log(f"Successfully spawned obstacle '{name}' at ({x:.2f}, {y:.2f}, {z:.2f})")
            return True
        else:
            msg = res.status_message if res else "timeout"
            self.log(f"[WARN] Failed to spawn obstacle '{name}': {msg}")
            return False

    def delete_obstacle(self, name: str = "corridor_blockage_box") -> bool:
        """Delete obstacle box from Gazebo world."""
        if not self.delete_entity_client.wait_for_service(timeout_sec=5.0):
            self.log("[ERROR] /delete_entity service unavailable")
            return False

        req = DeleteEntity.Request()
        req.name = name
        future = self.delete_entity_client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        res = future.result()
        if res and res.success:
            self.log(f"Successfully deleted obstacle '{name}' from Gazebo world")
            return True
        else:
            msg = res.status_message if res else "timeout"
            self.log(f"[WARN] Failed to delete obstacle '{name}': {msg}")
            return False

    def wait_for_passive_settling(
        self,
        min_duration_sec: float = 3.0,
        max_wait_sec: float = 16.0,
        linear_thresh: float = 0.04,
        angular_thresh: float = 0.04,
        abs_sim_deadline: Optional[float] = None,
    ) -> bool:
        """Strict passive physical halt verification (zero cmd_vel publisher intervention)."""
        t_start = self.get_sim_time_sec()
        stable_start: Optional[float] = None

        while self.get_sim_time_sec() - t_start < max_wait_sec:
            sim_now = self.get_sim_time_sec()
            if abs_sim_deadline is not None and sim_now >= abs_sim_deadline:
                self.log(f"[BUDGET] Absolute simulation deadline reached during passive settling ({sim_now:.2f}s >= {abs_sim_deadline:.2f}s)")
                break

            rclpy.spin_once(self, timeout_sec=0.04)
            odom = self.latest_odom_record
            if odom is not None:
                lv = abs(odom.get("linear_v", 999.0))
                av = abs(odom.get("angular_v", 999.0))
                now_sim = self.get_sim_time_sec()

                if lv < linear_thresh and av < angular_thresh:
                    if stable_start is None:
                        stable_start = now_sim
                    elif now_sim - stable_start >= min_duration_sec:
                        self.log(f"Passive physical halt verified: stable for {now_sim - stable_start:.2f}s sim time (lv={lv:.4f}, av={av:.4f})")
                        return True
                else:
                    stable_start = None
            time.sleep(0.02)

        # Safety override only if robot failed to stop passively
        self.log(f"[SAFETY] Robot failed to halt passively within {max_wait_sec}s sim time. Triggering emergency zero-Twist.")
        self.sticky_safety_intervention = True
        stop_cmd = Twist()
        for _ in range(5):
            self.emergency_cmd_pub.publish(stop_cmd)
            rclpy.spin_once(self, timeout_sec=0.02)
            time.sleep(0.02)
        return False

    def record_stability_window(
        self,
        duration_sim_sec: float = 2.4,
        sample_interval_wall_sec: float = 0.033,
        watchdog_wall_timeout_sec: float = 15.0,
        logger: Optional[Callable[[str], None]] = None,
        abs_sim_deadline: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Capture continuous stability window records conforming to scoring evaluator contract."""
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

            if abs_sim_deadline is not None and sim_now >= abs_sim_deadline:
                if logger:
                    logger(f"[ERROR] Absolute simulation deadline exceeded during stability window recording ({sim_now:.2f}s >= {abs_sim_deadline:.2f}s)!")
                watchdog_triggered = True
                break

            if time.monotonic() - t_start_wall > watchdog_wall_timeout_sec:
                if logger:
                    logger(f"[ERROR] Stability window watchdog triggered after {watchdog_wall_timeout_sec}s wall time!")
                watchdog_triggered = True
                break

        return window_records, watchdog_triggered

    def initialize_amcl_pose(self, coords: List[float]):
        """Publish initialpose strictly at episode spawn (never during/after navigation)."""
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(coords[0])
        msg.pose.pose.position.y = float(coords[1])
        msg.pose.pose.position.z = 0.01

        yaw = float(coords[2]) if len(coords) > 2 else 0.0
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance[0] = 0.05
        msg.pose.covariance[7] = 0.05
        msg.pose.covariance[35] = 0.05

        for _ in range(3):
            self.initial_pose_pub.publish(msg)
            rclpy.spin_once(self, timeout_sec=0.05)
            time.sleep(0.05)


def execute_navigation_action(
    node: P1cV3RunnerNode,
    dispatcher: ActionDispatcher,
    action_dict: Dict[str, Any],
    logger: Callable[[str], None],
    thresholds: Dict[str, Any],
    visible_state: Optional[Dict[str, Any]] = None,
    abs_sim_deadline: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Execute a single navigation action with strict observation and terminal resolution."""
    node.start_tracking()
    dispatch_res = dispatcher.dispatch(action_dict, visible_state=visible_state)
    logger(f"Dispatched action '{action_dict.get('action_id')}': pipeline_status={dispatch_res.get('pipeline_status')}")

    # Extract parameters
    eff_params = dispatch_res.get("effective_action", {}).get("params", {})
    target_goal = eff_params.get("goal", [1.8, 0.0, 0.0])
    target_frame = eff_params.get("frame_id", "map")
    sim_timeout = float(eff_params.get("timeout_sec", 45.0))

    term_res = await_nav_goal_terminal_result(
        node=node,
        goal_handle=node.current_active_goal_handle,
        sim_timeout_sec=sim_timeout,
        wall_watchdog_sec=60.0,
        logger=logger,
        abs_sim_deadline=abs_sim_deadline,
    )

    # Passive settling
    settled_ok = node.wait_for_passive_settling(
        min_duration_sec=3.0,
        max_wait_sec=16.0,
        linear_thresh=0.04,
        angular_thresh=0.04,
        abs_sim_deadline=abs_sim_deadline,
    )
    stability_records, wd_triggered = node.record_stability_window(
        duration_sim_sec=2.4,
        logger=logger,
        abs_sim_deadline=abs_sim_deadline,
    )
    node.stop_tracking()

    overall_deadline_exceeded = (
        term_res.get("deadline_exceeded", False)
        or (abs_sim_deadline is not None and node.get_sim_time_sec() > abs_sim_deadline)
    )

    # Physical evaluation
    eval_dict = evaluate_navigation_episode(
        target_goal=target_goal,
        nav2_status=term_res["ros_terminal_status"],
        final_gt=node.latest_gt_record,
        final_amcl=node.latest_amcl_record,
        stability_samples=stability_records,
        thresholds=thresholds,
        watchdog_triggered=wd_triggered or term_res.get("watchdog_triggered", False),
        safety_intervention=node.sticky_safety_intervention,
        execution_outcome="BUDGET_DEADLINE_EXCEEDED" if overall_deadline_exceeded and term_res["execution_outcome"] == "BUDGET_SUCCESS" else term_res["execution_outcome"],
        deadline_exceeded=overall_deadline_exceeded,
        failure_reason="SIM_BUDGET_EXCEEDED" if overall_deadline_exceeded and not term_res.get("failure_reason") else term_res["failure_reason"],
    )

    step_summary = {
        "dispatch": dispatch_res,
        "execution_outcome": eval_dict.get("execution_outcome", term_res["execution_outcome"]),
        "terminal_status_name": term_res["ros_terminal_status"],
        "status_code": term_res["status_code"],
        "deadline_exceeded": overall_deadline_exceeded,
        "failure_reason": eval_dict.get("failure_reason", term_res["failure_reason"]),
        "settled_ok": settled_ok,
        "safety_intervention": node.sticky_safety_intervention,
        "evaluation": eval_dict,
    }
    return step_summary, eval_dict, stability_records


def spawn_simulation(episode_dir: Path, spawn_pose: List[float]) -> Tuple[subprocess.Popen, Any]:
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
        "map:=/workspace/configs/chokepoint_world.yaml",
        "params_file:=/workspace/configs/nav2_params.yaml",
        "world:=/workspace/configs/chokepoint_world.model",
        f"x_pose:={spawn_pose[0]:.2f}", f"y_pose:={spawn_pose[1]:.2f}",
    ]
    proc = subprocess.Popen(
        launch_cmd,
        env=env,
        stdout=sim_log,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    return proc, env


def save_attempt_evidence(attempt_dir: Path, gt_samples: List[Dict[str, Any]], odom_samples: List[Dict[str, Any]], stability_records: List[Dict[str, Any]], action_summary: Dict[str, Any]):
    """Save raw attempt evidence files into dedicated subdirectory."""
    attempt_dir.mkdir(parents=True, exist_ok=True)
    with open(attempt_dir / "action_summary.json", "w", encoding="utf-8") as f:
        json.dump(action_summary, f, indent=2)

    with open(attempt_dir / "stability_window.json", "w", encoding="utf-8") as f:
        json.dump({
            "sample_count": len(stability_records),
            "window_records": stability_records,
        }, f, indent=2)

    with open(attempt_dir / "trajectory.json", "w", encoding="utf-8") as f:
        json.dump({
            "gt_samples_count": len(gt_samples),
            "odom_samples_count": len(odom_samples),
            "gt_trajectory": [
                {"seq": s["seq"], "recv_sim_time_sec": s.get("recv_sim_time_sec"), "x": s["x"], "y": s["y"], "yaw": s["yaw"]}
                for s in gt_samples
            ],
            "odom_trajectory": [
                {"seq": s["seq"], "msg_stamp_sec": s.get("msg_stamp_sec"), "x": s["x"], "y": s["y"], "yaw": s["yaw"]}
                for s in odom_samples
            ],
        }, f, indent=2)


def compute_sha256_tree(directory: Path, output_file: Path):
    """Compute sha256 checksums of all generated evidence files."""
    lines = []
    for p in sorted(directory.rglob("*")):
        if p.is_file() and p.name != "checksums.sha256":
            h = hashlib.sha256()
            with open(p, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            rel_p = p.relative_to(directory)
            lines.append(f"{h.hexdigest()}  {rel_p}\n")
    with open(output_file, "w", encoding="utf-8") as f:
        f.writelines(lines)


def evaluate_c2_retry_eligibility(
    obs_result: Dict[str, Any],
    doorway_evidence: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Pure logic function for evaluating C2 retry eligibility from observation result and doorway clearance."""
    # 1. Doorway spatial clearance gate (if evidence provided)
    if doorway_evidence is not None:
        doorway_state = doorway_evidence.get("doorway_state")
        if doorway_state != "FREE":
            return False, None, f"DOORWAY_NOT_FREE ({doorway_state})"

    # 2. Observation status & localization gate
    obs_status = obs_result.get("status")
    obs_data = obs_result.get("observation") or {}
    localization = obs_data.get("localization") or {}
    pose = localization.get("pose")
    frame_id = localization.get("frame_id")
    cov = localization.get("covariance_diagonal")

    if obs_status == "SUCCESS":
        if pose is not None and frame_id == "map" and isinstance(pose, (list, tuple)) and len(pose) >= 3:
            return True, {"amcl_pose": pose}, "SUCCESS"
        return False, None, "INVALID_SUCCESS_STRUCTURE"

    if obs_status == "DEGRADED":
        if (
            pose is not None
            and frame_id == "map"
            and isinstance(pose, (list, tuple))
            and len(pose) >= 3
            and all(math.isfinite(x) for x in pose[:3])
            and cov is not None
            and len(cov) >= 3
            and all(math.isfinite(c) for c in cov[:3])
        ):
            return True, {"amcl_pose": pose}, "DEGRADED_LOCALIZATION_VALID"
        return False, None, "DEGRADED_LOCALIZATION_MISSING"

    return False, None, f"OBSERVATION_UNAVAILABLE_{obs_status}"


def main():
    parser = argparse.ArgumentParser(description="FailMem P1c-v3 Pilot Runner")
    parser.add_argument("--protocol", default="configs/p1c_v3_protocol.yaml", help="Path to protocol YAML")
    parser.add_argument("--diagnostic", action="store_true", help="Run in diagnostic mode (1 episode per condition)")
    args = parser.parse_args()

    protocol_yaml_path = Path(args.protocol)
    with open(protocol_yaml_path, "r", encoding="utf-8") as f:
        protocol_config = yaml.safe_load(f)

    # Compute protocol checksum
    h_proto = hashlib.sha256()
    with open(protocol_yaml_path, "rb") as f:
        while chunk := f.read(65536):
            h_proto.update(chunk)
    protocol_sha256 = h_proto.hexdigest()

    scoring_rules = load_scoring_rules("configs/scoring_rules.yaml")
    thresholds = protocol_config.get("scoring_thresholds", scoring_rules.get("thresholds", {}))

    # Extract task parameters
    spawn_cfg = protocol_config["environment"]["spawn_pose"]
    spawn_coords = [float(spawn_cfg["x"]), float(spawn_cfg["y"]), float(spawn_cfg.get("yaw", 0.0))]
    goal_cfg = protocol_config["navigation_task"]["goal_pose"]
    target_goal = [float(goal_cfg["x"]), float(goal_cfg["y"]), float(goal_cfg.get("yaw", 0.0))]
    sim_timeout = float(protocol_config["navigation_task"]["sim_timeout_sec"])
    wall_watchdog = float(protocol_config["navigation_task"]["wall_watchdog_sec"])

    obstacle_cfg = protocol_config["obstacle_channel"]
    obstacle_name = str(obstacle_cfg.get("entity_name", "corridor_blockage_box"))
    obstacle_sdf_path = str(obstacle_cfg.get("obstacle_sdf", "configs/chokepoint_box.sdf"))
    obstacle_pos = obstacle_cfg["pose"]
    obs_x, obs_y, obs_z = float(obstacle_pos["x"]), float(obstacle_pos["y"]), float(obstacle_pos.get("z", 0.30))
    doorway_bbox_dict = obstacle_cfg.get("doorway_bbox", {"x_min": -0.20, "x_max": 0.20, "y_min": -0.30, "y_max": 0.30})
    doorway_bbox = (
        float(doorway_bbox_dict["x_min"]),
        float(doorway_bbox_dict["x_max"]),
        float(doorway_bbox_dict["y_min"]),
        float(doorway_bbox_dict["y_max"]),
    )

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    run_prefix = "p1c_diag" if args.diagnostic else "p1c"
    run_id = f"{run_prefix}_{timestamp_str}_{rand_suffix}"

    evidence_base = Path("/workspace/reports/evidence/p1c") if Path("/workspace").exists() else Path("reports/evidence/p1c")
    if args.diagnostic:
        evidence_base = Path("/workspace/reports/evidence/p1c_diagnostic") if Path("/workspace").exists() else Path("reports/evidence/p1c_diagnostic")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"=======================================================================")
    print(f"FailMem P1c Blockage Pilot Runner (v3.0): {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"Protocol: {protocol_yaml_path} (SHA256: {protocol_sha256})")
    print(f"Target goal: {target_goal}, Spawn: {spawn_coords}")
    print(f"Obstacle: {obstacle_name} at ({obs_x}, {obs_y}, {obs_z})")
    print(f"Mode: {'DIAGNOSTIC (1 ep/cond)' if args.diagnostic else 'FORMAL (3 eps/cond)'}")
    print(f"=======================================================================")

    # 1. World to map geometric alignment verification
    coord_proof = verify_world_map_alignment(
        map_yaml_path="configs/chokepoint_world.yaml",
        map_pgm_path="configs/chokepoint_world.pgm",
        world_model_path="configs/chokepoint_world.model",
        sdf_model_path="configs/chokepoint_world.model",
    )
    with open(run_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    # 2. Save runtime configuration
    runtime_config = {
        "run_id": run_id,
        "protocol_sha256": protocol_sha256,
        "protocol_version": "3.0",
        "diagnostic_mode": args.diagnostic,
        "spawn_pose": spawn_coords,
        "target_goal": target_goal,
        "sim_timeout_sec": sim_timeout,
        "wall_watchdog_sec": wall_watchdog,
        "obstacle_pose": [obs_x, obs_y, obs_z],
        "obstacle_name": obstacle_name,
        "obstacle_sdf_path": obstacle_sdf_path,
        "doorway_bbox": list(doorway_bbox),
        "thresholds": thresholds,
    }
    with open(run_dir / "runtime_config.json", "w", encoding="utf-8") as f:
        json.dump(runtime_config, f, indent=2)

    pilot_results = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1c-blockage-pilot-v3",
        "protocol_sha256": protocol_sha256,
        "protocol_version": "3.0",
        "diagnostic_mode": args.diagnostic,
        "runtime_config": runtime_config,
        "protocol": protocol_config,
        "coordinate_alignment": coord_proof,
        "C0_baseline_episodes": [],
        "C1_continuous_blockage_episodes": [],
        "C2_temporary_blockage_episodes": [],
    }

    episodes_per_cond = 1 if args.diagnostic else 3
    test_plans = []
    for i in range(1, episodes_per_cond + 1):
        test_plans.append({"cond": "C0", "ep_num": i, "dir_name": f"C0_ep{i}", "spawn_obstacle": False})
    for i in range(1, episodes_per_cond + 1):
        test_plans.append({"cond": "C1", "ep_num": i, "dir_name": f"C1_ep{i}", "spawn_obstacle": True})
    for i in range(1, episodes_per_cond + 1):
        test_plans.append({"cond": "C2", "ep_num": i, "dir_name": f"C2_ep{i}", "spawn_obstacle": True})

    for plan in test_plans:
        cond = plan["cond"]
        ep_dir = run_dir / plan["dir_name"]
        ep_dir.mkdir(parents=True, exist_ok=True)
        events_log = open(ep_dir / "events.log", "w", encoding="utf-8")

        def log_ep(msg: str):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            line = f"[{ts}] {msg}"
            print(line, flush=True)
            events_log.write(line + "\n")
            events_log.flush()

        log_ep(f"=== Starting Episode {plan['dir_name']} (Condition {cond} #{plan['ep_num']}) ===")
        log_ep(f"Protocol: sim_timeout={sim_timeout}s, wall_watchdog={wall_watchdog}s")

        sim_proc, sim_env = spawn_simulation(ep_dir, spawn_coords)
        ep_data: Dict[str, Any] = {
            "episode_id": plan["dir_name"],
            "condition": cond,
            "episode_number": plan["ep_num"],
            "target_goal": target_goal,
            "spawn_pose": spawn_coords,
            "protocol_sha256": protocol_sha256,
            "infrastructure_error": None,
        }

        try:
            rclpy.init()
            node = P1cV3RunnerNode(f"p1c_v3_{plan['dir_name']}", event_logger=log_ep)
            context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
            dispatcher = ActionDispatcher(context=context, run_id=run_id, episode_id=plan["dir_name"])
            dispatcher.ros_observer = lambda act: node.get_live_observation(
                wait_fresh=True, timeout_sec=2.0, refresh_amcl_if_stale=True
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

            # Wait for Gazebo clock advancement
            t0_wall = time.monotonic()
            t0_sim = node.get_sim_time_sec()
            while (node.get_sim_time_sec() - t0_sim < 1.0) and (time.monotonic() - t0_wall < 30.0):
                rclpy.spin_once(node, timeout_sec=0.1)
                time.sleep(0.05)
            log_ep(f"Sim clock advanced: {t0_sim:.2f}s -> {node.get_sim_time_sec():.2f}s")

            # Verify sensor streams
            t_sensor_start = time.monotonic()
            while time.monotonic() - t_sensor_start < 20.0:
                rclpy.spin_once(node, timeout_sec=0.1)
                if node.latest_odom_record and node.latest_gt_record and node.latest_scan_record and node.latest_costmap_record:
                    break
                time.sleep(0.05)
            log_ep(f"Sensors streaming: odom={node.latest_odom_record['x'] if node.latest_odom_record else 'None'}, scan={node.latest_scan_record['total_count'] if node.latest_scan_record else 'None'} rays, costmap={node.latest_costmap_record['width'] if node.latest_costmap_record else 'None'}")

            # Initialize AMCL pose strictly at spawn
            node.initialize_amcl_pose(spawn_coords)
            t_amcl_start = time.monotonic()
            while time.monotonic() - t_amcl_start < 20.0:
                rclpy.spin_once(node, timeout_sec=0.1)
                if node.latest_amcl_record is not None:
                    delta = math.hypot(node.latest_amcl_record["x"] - spawn_coords[0], node.latest_amcl_record["y"] - spawn_coords[1])
                    if delta < 0.35:
                        log_ep(f"AMCL pose converged at x={node.latest_amcl_record['x']:.2f}, y={node.latest_amcl_record['y']:.2f} (delta={delta:.2f}m)")
                        break
                time.sleep(0.1)

            # Verify Nav2 bt_navigator lifecycle
            t_nav_start = time.monotonic()
            while time.monotonic() - t_nav_start < 15.0:
                rclpy.spin_once(node, timeout_sec=0.1)
                if node.lifecycle_client.wait_for_service(timeout_sec=0.5):
                    req = GetState.Request()
                    fut = node.lifecycle_client.call_async(req)
                    rclpy.spin_until_future_complete(node, fut, timeout_sec=1.0)
                    if fut.result() and fut.result().current_state.label == "active":
                        log_ep("Nav2 bt_navigator is verified ACTIVE!")
                        break
                time.sleep(0.1)

            # ── Condition C0: Unblocked Baseline ──────────────────────────────
            if cond == "C0":
                doorway_check_pre = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)
                log_ep(f"C0: Pre-nav doorway check: state={doorway_check_pre.get('doorway_state')}, pass_through={doorway_check_pre.get('pass_through_count')}")

                obs1 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_initial",
                    "params": {"target_id": "initial_scan"},
                })
                log_ep(f"C0 Step 1 Observe: status={obs1.get('ros_result', {}).get('status')}")

                nav_act = {
                    "action": "navigate", "action_id": f"{plan['dir_name']}_nav",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": sim_timeout},
                }
                step_nav_sum, nav_eval, stab_records = execute_navigation_action(
                    node=node, dispatcher=dispatcher, action_dict=nav_act,
                    logger=log_ep, thresholds=thresholds,
                )
                log_ep(f"C0 Navigate: outcome={step_nav_sum['execution_outcome']}, terminal={step_nav_sum['terminal_status_name']}")

                save_attempt_evidence(
                    ep_dir / "initial_attempt",
                    node.episode_gt_samples, node.episode_odom_samples, stab_records,
                    {"step_summary": step_nav_sum, "evaluation": nav_eval},
                )

                obs2 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_final",
                    "params": {"target_id": "final_scan"},
                })
                log_ep(f"C0 Step 3 Final Observe: status={obs2.get('ros_result', {}).get('status')}")

                final_gt = node.latest_gt_record
                gt_pos_err = (
                    round(math.hypot(final_gt["x"] - target_goal[0], final_gt["y"] - target_goal[1]), 4)
                    if final_gt else None
                )
                task_success = nav_eval.get("strict_physical_arrival_and_stable", False)
                mechanism_verified = task_success

                ep_data.update({
                    "obstacle_present": False,
                    "collision_state": "UNKNOWN",
                    "step1_observe": obs1,
                    "step2_navigate": step_nav_sum,
                    "step3_observe": obs2,
                    "final_gt_pos_error_m": gt_pos_err,
                    "evaluation": nav_eval,
                    "task_success": task_success,
                    "mechanism_verified": mechanism_verified,
                    "execution_outcome": step_nav_sum["execution_outcome"],
                    "terminal_status_name": step_nav_sum["terminal_status_name"],
                    "action_history": context.action_history,
                })
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C0_baseline_episodes"].append(ep_data)

            # ── Condition C1: Continuous Obstacle Blockage ────────────────────
            elif cond == "C1":
                log_ep(f"C1: Spawning obstacle at ({obs_x}, {obs_y}, {obs_z})...")
                spawn_service_ok = node.spawn_obstacle(name=obstacle_name, sdf_path=obstacle_sdf_path, x=obs_x, y=obs_y, z=obs_z)
                spawn_gazebo_confirmed = False
                if spawn_service_ok:
                    spawn_gazebo_confirmed = node.check_model_in_gazebo_states(obstacle_name, wall_timeout_sec=5.0)
                log_ep(f"C1: spawn service_ok={spawn_service_ok}, gazebo_confirmed={spawn_gazebo_confirmed}")

                if not (spawn_service_ok and spawn_gazebo_confirmed):
                    ep_data["infrastructure_error"] = "OBSTACLE_SPAWN_FAILED"
                    raise RuntimeError(f"Failed to spawn+confirm obstacle in {plan['dir_name']}")

                doorway_check_pre = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)
                log_ep(f"C1: Pre-nav doorway check: state={doorway_check_pre.get('doorway_state')}, hits={doorway_check_pre.get('hits_inside_count')}")

                obs1 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_initial",
                    "params": {"target_id": "initial_scan"},
                })
                log_ep(f"C1 Observe: status={obs1.get('ros_result', {}).get('status')}")

                nav_act = {
                    "action": "navigate", "action_id": f"{plan['dir_name']}_nav_blocked",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": sim_timeout},
                }
                step_nav_sum, nav_eval, stab_records = execute_navigation_action(
                    node=node, dispatcher=dispatcher, action_dict=nav_act,
                    logger=log_ep, thresholds=thresholds,
                )
                log_ep(f"C1 Navigate: outcome={step_nav_sum['execution_outcome']}, terminal={step_nav_sum['terminal_status_name']}")

                save_attempt_evidence(
                    ep_dir / "initial_attempt",
                    node.episode_gt_samples, node.episode_odom_samples, stab_records,
                    {"step_summary": step_nav_sum, "evaluation": nav_eval},
                )

                obs2 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_post_nav",
                    "params": {"target_id": "post_nav_scan"},
                })
                doorway_check_post = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)

                final_gt = node.latest_gt_record
                gt_pos_err = (
                    round(math.hypot(final_gt["x"] - target_goal[0], final_gt["y"] - target_goal[1]), 4)
                    if final_gt else None
                )
                outcome = step_nav_sum["execution_outcome"]
                task_success = nav_eval.get("strict_physical_arrival_and_stable", False)

                mechanism_verified = (
                    spawn_service_ok
                    and spawn_gazebo_confirmed
                    and (doorway_check_pre.get("doorway_state") == "OCCUPIED")
                    and outcome in ("BUDGET_DEADLINE_EXCEEDED", "EXECUTION_FAILED", "EXECUTION_CANCELED")
                    and (not task_success)
                    and (gt_pos_err is not None and gt_pos_err > 0.50)
                    and (ep_data.get("infrastructure_error") is None)
                )
                log_ep(f"C1 mechanism_verified={mechanism_verified}: doorway_state={doorway_check_pre.get('doorway_state')}, not_arrived={not task_success}, dist_to_goal={gt_pos_err}m")

                ep_data.update({
                    "obstacle_present": True,
                    "obstacle_spawned_service": spawn_service_ok,
                    "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                    "collision_state": "UNKNOWN",
                    "doorway_check_pre_nav": doorway_check_pre,
                    "doorway_check_post_nav": doorway_check_post,
                    "step1_observe": obs1,
                    "step2_navigate_blocked": step_nav_sum,
                    "step3_observe": obs2,
                    "final_gt_pos_error_m": gt_pos_err,
                    "evaluation": nav_eval,
                    "task_success": task_success,
                    "mechanism_verified": mechanism_verified,
                    "execution_outcome": outcome,
                    "terminal_status_name": step_nav_sum["terminal_status_name"],
                    "action_history": context.action_history,
                })
                with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                    json.dump(ep_data, f, indent=2)
                pilot_results["C1_continuous_blockage_episodes"].append(ep_data)

            # ── Condition C2: Temporary Blockage & Recovery ───────────────────
            elif cond == "C2":
                log_ep(f"C2: Spawning temporary obstacle at ({obs_x}, {obs_y}, {obs_z})...")
                spawn_service_ok = node.spawn_obstacle(name=obstacle_name, sdf_path=obstacle_sdf_path, x=obs_x, y=obs_y, z=obs_z)
                spawn_gazebo_confirmed = False
                if spawn_service_ok:
                    spawn_gazebo_confirmed = node.check_model_in_gazebo_states(obstacle_name, wall_timeout_sec=5.0)
                log_ep(f"C2: spawn service_ok={spawn_service_ok}, gazebo_confirmed={spawn_gazebo_confirmed}")

                if not (spawn_service_ok and spawn_gazebo_confirmed):
                    ep_data["infrastructure_error"] = "OBSTACLE_SPAWN_FAILED"
                    raise RuntimeError(f"Failed to spawn obstacle in {plan['dir_name']}")

                doorway_check_blocked = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)
                log_ep(f"C2: Pre-initial-nav doorway check: state={doorway_check_blocked.get('doorway_state')}, hits={doorway_check_blocked.get('hits_inside_count')}")

                obs1 = dispatcher.dispatch({
                    "action": "observe", "action_id": f"{plan['dir_name']}_obs_initial",
                    "params": {"target_id": "initial_scan"},
                })
                log_ep(f"C2 Initial Observe: status={obs1.get('ros_result', {}).get('status')}")

                nav_act_orig_id = f"{plan['dir_name']}_nav_orig"
                nav_act_orig = {
                    "action": "navigate", "action_id": nav_act_orig_id,
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": sim_timeout},
                }
                step_orig_sum, nav1_eval, stab1_recs = execute_navigation_action(
                    node=node, dispatcher=dispatcher, action_dict=nav_act_orig,
                    logger=log_ep, thresholds=thresholds,
                )
                log_ep(f"C2 Initial blocked nav: outcome={step_orig_sum['execution_outcome']}, terminal={step_orig_sum['terminal_status_name']}")

                # Save initial_attempt evidence
                save_attempt_evidence(
                    ep_dir / "initial_attempt",
                    node.episode_gt_samples, node.episode_odom_samples, stab1_recs,
                    {"step_summary": step_orig_sum, "evaluation": nav1_eval},
                )

                initial_outcome = step_orig_sum["execution_outcome"]
                initial_strict_arrival = nav1_eval.get("strict_physical_arrival_and_stable", False)

                # Check if initial attempt unexpectedly arrived at goal (e.g. detoured)
                if initial_strict_arrival and initial_outcome == "BUDGET_SUCCESS":
                    log_ep("C2: Initial navigate arrived at goal unexpectedly. Early exit without recovery.")
                    ep_data.update({
                        "obstacle_present": True,
                        "obstacle_spawned_service": spawn_service_ok,
                        "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                        "collision_state": "UNKNOWN",
                        "doorway_check_blocked": doorway_check_blocked,
                        "step1_observe": obs1,
                        "step2_initial_navigate": step_orig_sum,
                        "initial_failed_genuine": False,
                        "task_success": True,
                        "mechanism_verified": False,
                        "mechanism_failure_reason": "INITIAL_ATTEMPT_SUCCEEDED_OR_DETOURED",
                        "action_history": context.action_history,
                    })
                    with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                        json.dump(ep_data, f, indent=2)
                    pilot_results["C2_temporary_blockage_episodes"].append(ep_data)
                    ep_data["_skip_retry_done"] = True
                else:
                    initial_failed_genuine = (
                        not initial_strict_arrival
                        and initial_outcome not in ("BUDGET_SUCCESS", "EXECUTION_ERROR", "EXECUTION_UNKNOWN")
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

                    # Natural lidar raytracing wait: wait 3.0s sim time for costmap clearing
                    t_del = node.get_sim_time_sec()
                    log_ep("C2: Waiting for natural lidar raytrace to clear doorway (no service purge)...")
                    wall_natural_wait_start = time.monotonic()
                    while (node.get_sim_time_sec() - t_del < 3.0) and (time.monotonic() - wall_natural_wait_start < 10.0):
                        rclpy.spin_once(node, timeout_sec=0.04)

                    # Spatial doorway clearance check
                    doorway_check_cleared = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)
                    log_ep(f"C2: Post-removal doorway check: state={doorway_check_cleared.get('doorway_state')}, pass_through={doorway_check_cleared.get('pass_through_count')}")

                    # Post-removal observe with AMCL nomotion refresh
                    obs2 = dispatcher.dispatch({
                        "action": "observe", "action_id": f"{plan['dir_name']}_obs_post_removal",
                        "params": {"target_id": "post_removal_scan"},
                    })
                    obs_res_dict = obs2.get("ros_result", {})
                    log_ep(f"C2 Post-removal Observe: status={obs_res_dict.get('status')}")

                    # Determine retry eligibility
                    retry_eligible, retry_visible_state, retry_reason = evaluate_c2_retry_eligibility(
                        obs_res_dict, doorway_evidence=doorway_check_cleared
                    )
                    log_ep(f"C2 Retry eligibility: eligible={retry_eligible}, reason={retry_reason}")

                    if not retry_eligible:
                        log_ep(f"C2: Observation unavailable for retry ({retry_reason}). Recording OBSERVATION_UNAVAILABLE.")
                        ep_data.update({
                            "obstacle_present": True,
                            "obstacle_spawned_service": spawn_service_ok,
                            "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                            "obstacle_deleted_service": del_service_ok,
                            "obstacle_delete_gazebo_confirmed": del_gazebo_confirmed,
                            "collision_state": "UNKNOWN",
                            "doorway_check_blocked": doorway_check_blocked,
                            "doorway_check_cleared": doorway_check_cleared,
                            "step1_observe": obs1,
                            "step2_initial_navigate": step_orig_sum,
                            "step3_post_removal_observe": obs2,
                            "initial_failed_genuine": initial_failed_genuine,
                            "observation_available": False,
                            "observation_unavailable_reason": retry_reason,
                            "retry_execute": False,
                            "task_success": False,
                            "mechanism_verified": False,
                            "mechanism_failure_reason": f"OBSERVATION_UNAVAILABLE_{retry_reason}",
                            "action_history": context.action_history,
                        })
                        with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                            json.dump(ep_data, f, indent=2)
                        pilot_results["C2_temporary_blockage_episodes"].append(ep_data)
                    else:
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
                        task_success = retry_eval.get("strict_physical_arrival_and_stable", False)

                        # mechanism_verified: all conditions must hold
                        mechanism_verified = (
                            spawn_service_ok
                            and spawn_gazebo_confirmed
                            and (doorway_check_blocked.get("doorway_state") == "OCCUPIED")
                            and initial_failed_genuine
                            and del_service_ok
                            and del_gazebo_confirmed
                            and (doorway_check_cleared.get("doorway_state") == "FREE")
                            and retry_eligible
                            and task_success
                        )
                        log_ep(f"C2 mechanism_verified={mechanism_verified}: spawn={spawn_service_ok}, init_fail={initial_failed_genuine}, del_ok={del_gazebo_confirmed}, doorway_cleared={doorway_check_cleared.get('doorway_state') == 'FREE'}, obs_ok={retry_eligible}, task_ok={task_success}")

                        ep_data.update({
                            "obstacle_present": True,
                            "obstacle_spawned_service": spawn_service_ok,
                            "obstacle_spawn_gazebo_confirmed": spawn_gazebo_confirmed,
                            "obstacle_deleted_service": del_service_ok,
                            "obstacle_delete_gazebo_confirmed": del_gazebo_confirmed,
                            "collision_state": "UNKNOWN",
                            "doorway_check_blocked": doorway_check_blocked,
                            "doorway_check_cleared": doorway_check_cleared,
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

        except Exception as exc:
            log_ep(f"[ERROR] Episode {plan['dir_name']} failed with exception: {exc}")
            if ep_data.get("infrastructure_error") is None:
                ep_data["infrastructure_error"] = f"EXCEPTION: {exc}"
            ep_data["task_success"] = False
            ep_data["mechanism_verified"] = False
            with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                json.dump(ep_data, f, indent=2)
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

    # Overall Summary Computation
    c0_eps = pilot_results["C0_baseline_episodes"]
    c1_eps = pilot_results["C1_continuous_blockage_episodes"]
    c2_eps = pilot_results["C2_temporary_blockage_episodes"]

    expected_ep_count = episodes_per_cond
    c0_task_ok = len(c0_eps) == expected_ep_count and all(ep.get("task_success", False) for ep in c0_eps)
    c0_mech_ok = len(c0_eps) == expected_ep_count and all(ep.get("mechanism_verified", False) for ep in c0_eps)

    c1_mech_ok = len(c1_eps) == expected_ep_count and all(ep.get("mechanism_verified", False) for ep in c1_eps)
    c1_no_spurious_arrive = all(not ep.get("task_success", True) for ep in c1_eps)

    c2_task_ok = len(c2_eps) == expected_ep_count and all(ep.get("task_success", False) for ep in c2_eps)
    c2_mech_ok = len(c2_eps) == expected_ep_count and all(ep.get("mechanism_verified", False) for ep in c2_eps)

    coord_ok = pilot_results["coordinate_alignment"]["verified"]
    all_ok = c0_task_ok and c0_mech_ok and c1_mech_ok and c1_no_spurious_arrive and c2_task_ok and c2_mech_ok and coord_ok
    pilot_results["overall_status"] = "PASSED" if all_ok else "PARTIAL"
    pilot_results["summary_table"] = {
        "C0": {"task_success": c0_task_ok, "mechanism_verified": c0_mech_ok, "episode_count": len(c0_eps)},
        "C1": {"no_spurious_arrival": c1_no_spurious_arrive, "mechanism_verified": c1_mech_ok, "episode_count": len(c1_eps)},
        "C2": {"task_success": c2_task_ok, "mechanism_verified": c2_mech_ok, "episode_count": len(c2_eps)},
        "coordinate_alignment": coord_ok,
    }

    # Save summary.json and checksums
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(pilot_results, f, indent=2)

    compute_sha256_tree(run_dir, run_dir / "checksums.sha256")

    print(f"\n=======================================================================")
    print(f"P1c-v3 Pilot Execution Complete: {pilot_results['overall_status']}")
    print(f"C0 (Baseline): task_ok={c0_task_ok}, mech_ok={c0_mech_ok}  ({len(c0_eps)} eps)")
    print(f"C1 (Blocked):  no_spurious={c1_no_spurious_arrive}, mech_ok={c1_mech_ok}  ({len(c1_eps)} eps)")
    print(f"C2 (Retry):    task_ok={c2_task_ok}, mech_ok={c2_mech_ok}  ({len(c2_eps)} eps)")
    print(f"Evidence Directory: {run_dir}")
    print(f"=======================================================================")


if __name__ == "__main__":
    main()
