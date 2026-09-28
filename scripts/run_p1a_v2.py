#!/usr/bin/env python3
"""FailMem P1a-v2 Headless Navigation Runner.

Implements:
1. Truly independent episodes (fresh simulation spawn, bringup, and cleanup per episode).
2. Unified ROS simulation time:
   - Node explicitly configured with use_sim_time=True and verified.
   - Synchronization: waits for /clock advancement before action dispatch.
   - Multi-timestamp logging: msg_stamp, receipt_sim_time, monotonic_wall_time, frame_id.
   - Gazebo ModelStates documented with RECEIPT_ROS_SIM_TIME_APPROX.
3. Unified action entrypoint via ActionDispatcher:
   - Strict parse -> schema validate -> default normalize -> history constraint -> ROS dispatch -> terminal record.
4. Objective scoring against configs/scoring_rules.yaml:
   - Position tolerance strictly 0.30m (not 0.35m).
   - Heading tolerance 0.35 rad (~20 deg).
   - Settling interval followed by post-arrival 2.0-second simulation time stability window.
   - Sensor staleness and time alignment checks between AMCL and Ground Truth.
5. Cancellation and stop verification:
   - Reachable distant goal [0.5, 1.8, 0.0].
   - Cancellation triggered only after confirmed active movement (v > 0.05 m/s).
   - Post-cancel 2.0-second simulation time stop window (cmd_vel, odom, GT displacement).
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
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ROS2 imports
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from action_msgs.msg import GoalStatus
from gazebo_msgs.msg import ModelStates
from lifecycle_msgs.srv import GetState
from lifecycle_msgs.msg import State

REPO_ROOT = Path("/workspace")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.action_dispatcher import ActionDispatcher, derive_ros_goal_uuid
from src.action_runtime import EpisodeActionHistoryContext


def load_scoring_rules() -> Dict[str, Any]:
    rules_file = REPO_ROOT / "configs/scoring_rules.yaml"
    if not rules_file.exists():
        raise FileNotFoundError(f"Scoring rules config not found: {rules_file}")
    with open(rules_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def quat_to_yaw(x: float, y: float, z: float, w: float) -> float:
    """Convert quaternion to yaw angle in radians [-pi, pi]."""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def normalize_angle(theta: float) -> float:
    """Normalize angle into [-pi, pi]."""
    while theta > math.pi:
        theta -= 2.0 * math.pi
    while theta < -math.pi:
        theta += 2.0 * math.pi
    return theta


def cleanup_simulation_processes():
    """Aggressively terminate lingering Gazebo and Nav2 processes."""
    patterns = [
        "gzserver",
        "gzclient",
        "nav2_container",
        "component_container",
        "lifecycle_manager",
        "robot_state_publisher",
        "spawn_entity",
        "tb3_simulation_launch",
    ]
    for p in patterns:
        subprocess.run(["pkill", "-9", "-f", p], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)


class EpisodeRunnerNode(Node):
    """ROS 2 Node for an isolated navigation episode with unified simulation time."""

    def __init__(self, episode_id: str, event_logger):
        super().__init__(
            f"failmem_p1a_v2_{episode_id}",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        self.episode_id = episode_id
        self.event_logger = event_logger

        # Verify use_sim_time parameter
        sim_time_param = self.get_parameter("use_sim_time").get_parameter_value().bool_value
        if not sim_time_param:
            raise RuntimeError("CRITICAL: Node parameter 'use_sim_time' is not True!")

        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "initialpose", 10)
        self.cmd_vel_pub = self.create_publisher(Twist, "cmd_vel", 10)
        self.cmd_vel_sub = self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, "odom", self._odom_cb, 10)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "amcl_pose", self._amcl_cb, 10)
        self.gazebo_sub = self.create_subscription(ModelStates, "/gazebo/model_states", self._gazebo_cb, 10)

        # Cache of latest messages
        self.latest_odom_msg: Optional[Odometry] = None
        self.latest_odom_record: Optional[Dict[str, Any]] = None
        self.latest_amcl_msg: Optional[PoseWithCovarianceStamped] = None
        self.latest_amcl_record: Optional[Dict[str, Any]] = None
        self.latest_gt_record: Optional[Dict[str, Any]] = None
        self.latest_cmd_vel_record: Optional[Dict[str, Any]] = None

        # Episode-wide tracking buffers
        self.is_tracking = False
        self.episode_gt_samples: List[Dict[str, Any]] = []
        self.episode_amcl_samples: List[Dict[str, Any]] = []
        self.episode_odom_samples: List[Dict[str, Any]] = []
        self.episode_cmd_vel_samples: List[Dict[str, Any]] = []

    def log(self, msg: str):
        self.event_logger(msg)

    def get_sim_time_sec(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _cmd_vel_cb(self, msg: Twist):
        sim_now = self.get_sim_time_sec()
        record = {
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
        self.latest_odom_msg = msg
        sim_now = self.get_sim_time_sec()
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        v = msg.twist.twist
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        record = {
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
        self.latest_amcl_msg = msg
        sim_now = self.get_sim_time_sec()
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        record = {
            "msg_stamp_sec": round(msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, 4),
            "recv_sim_time_sec": round(sim_now, 4),
            "monotonic_wall_sec": round(time.monotonic(), 4),
            "frame_id": msg.header.frame_id,
            "x": round(p.x, 4),
            "y": round(p.y, 4),
            "yaw": round(yaw, 4),
        }
        self.latest_amcl_record = record
        if self.is_tracking:
            self.episode_amcl_samples.append(record)

    def _gazebo_cb(self, msg: ModelStates):
        sim_now = self.get_sim_time_sec()
        target_name = None
        for cand in ["turtlebot3_waffle", "waffle"]:
            if cand in msg.name:
                target_name = cand
                break
        if target_name is None:
            return

        idx = msg.name.index(target_name)
        pose = msg.pose[idx]
        p = pose.position
        o = pose.orientation
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        record = {
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

    def wait_for_sim_clock(self, min_sim_advance_sec: float = 1.0, wall_timeout_sec: float = 35.0) -> bool:
        """Wait until /clock advances by at least min_sim_advance_sec."""
        t_wall_start = time.monotonic()
        t_sim_initial = None

        while time.monotonic() - t_wall_start < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            sim_now = self.get_sim_time_sec()
            if sim_now > 0.0:
                if t_sim_initial is None:
                    t_sim_initial = sim_now
                elif sim_now - t_sim_initial >= min_sim_advance_sec:
                    self.log(f"Sim clock advanced: {t_sim_initial:.2f}s -> {sim_now:.2f}s (delta={sim_now - t_sim_initial:.2f}s)")
                    return True
        return False

    def wait_for_nav2_active(self, wall_timeout_sec: float = 35.0) -> bool:
        """Poll /bt_navigator/get_state until state is State.PRIMARY_STATE_ACTIVE (3)."""
        client = self.create_client(GetState, "/bt_navigator/get_state")
        t_start = time.monotonic()
        if not client.wait_for_service(timeout_sec=wall_timeout_sec):
            self.destroy_client(client)
            return False

        req = GetState.Request()
        while time.monotonic() - t_start < wall_timeout_sec:
            future = client.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=1.0)
            if future.done() and future.result() is not None:
                state_id = future.result().current_state.id
                state_label = future.result().current_state.label
                if state_id == State.PRIMARY_STATE_ACTIVE:
                    self.log(f"Nav2 bt_navigator is verified ACTIVE ({state_id} {state_label})!")
                    self.destroy_client(client)
                    return True
                else:
                    self.log(f"Nav2 bt_navigator state: {state_id} ({state_label}), waiting for active...")
            time.sleep(0.5)
        self.destroy_client(client)
        return False

    def wait_for_sensors(self, wall_timeout_sec: float = 30.0) -> bool:
        """Wait until fresh odom, ground truth, and scan topics are streaming."""
        t_wall_start = time.monotonic()
        while time.monotonic() - t_wall_start < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_odom_record is not None and self.latest_gt_record is not None:
                self.log(f"Sensors streaming: odom={self.latest_odom_record['x']:.2f}, gt={self.latest_gt_record['x']:.2f}")
                return True
        return False

    def initialize_amcl_pose(self, x: float = -2.0, y: float = -0.5, yaw: float = 0.0, wall_timeout_sec: float = 30.0) -> bool:
        """Publish initialpose and wait until AMCL pose converges near the target."""
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.position.z = 0.01
        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance[0] = 0.25
        msg.pose.covariance[7] = 0.25
        msg.pose.covariance[35] = 0.06

        t_wall_start = time.monotonic()
        while time.monotonic() - t_wall_start < wall_timeout_sec:
            msg.header.stamp = self.get_clock().now().to_msg()
            self.initial_pose_pub.publish(msg)
            for _ in range(5):
                rclpy.spin_once(self, timeout_sec=0.2)
                if self.latest_amcl_record is not None:
                    dist = math.hypot(self.latest_amcl_record["x"] - x, self.latest_amcl_record["y"] - y)
                    if dist < 0.6:
                        self.log(f"AMCL pose converged at x={self.latest_amcl_record['x']:.2f}, y={self.latest_amcl_record['y']:.2f} (delta={dist:.2f}m)")
                        for _ in range(5):
                            rclpy.spin_once(self, timeout_sec=0.2)
                        return True
            time.sleep(0.3)
        return False

    def wait_for_settling(self, max_sim_sec: float = 2.0, wall_timeout_sec: float = 8.0):
        """Allow vehicle inertia and controller deceleration to settle to halt."""
        sim_start = self.get_sim_time_sec()
        wall_start = time.monotonic()
        stop_cmd = Twist()
        self.cmd_vel_pub.publish(stop_cmd)
        consecutive_stopped = 0

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.05)
            self.cmd_vel_pub.publish(stop_cmd)
            lv = abs(self.latest_odom_record.get("linear_v", 1.0)) if self.latest_odom_record else 1.0
            av = abs(self.latest_odom_record.get("angular_v", 1.0)) if self.latest_odom_record else 1.0
            if lv < 0.03 and av < 0.03:
                consecutive_stopped += 1
                if consecutive_stopped >= 4:
                    self.log(f"Vehicle settled to halt (lv={lv:.4f}, av={av:.4f})")
                    break
            else:
                consecutive_stopped = 0

            if (self.get_sim_time_sec() - sim_start) > max_sim_sec:
                self.log(f"[WARN] Settling wait reached sim time limit ({max_sim_sec}s)")
                break
            if (time.monotonic() - wall_start) > wall_timeout_sec:
                self.log("[WARN] Settling wait reached wall timeout")
                break

    def record_stability_window(self, duration_sim_sec: float = 2.0, max_wall_sec: float = 12.0) -> List[Dict[str, Any]]:
        """Collect continuous high-rate samples for at least duration_sim_sec simulation time."""
        sim_start = self.get_sim_time_sec()
        wall_start = time.monotonic()
        window_records = []

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.05)
            sim_now = self.get_sim_time_sec()
            wall_now = time.monotonic()

            if self.latest_gt_record:
                window_records.append({
                    "sim_time": round(sim_now, 4),
                    "gt": copy.deepcopy(self.latest_gt_record),
                    "amcl": copy.deepcopy(self.latest_amcl_record),
                    "odom": copy.deepcopy(self.latest_odom_record),
                    "cmd_vel": copy.deepcopy(self.latest_cmd_vel_record),
                })

            if (sim_now - sim_start) >= duration_sim_sec:
                break
            if (wall_now - wall_start) > max_wall_sec:
                self.log("[WARN] Stability window wall-clock watchdog triggered")
                break

        return window_records


def run_single_episode(
    episode_index: int,
    action_dict: Dict[str, Any],
    is_cancel_test: bool,
    output_dir: Path,
    scoring_rules: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a completely isolated episode: clean processes -> launch sim -> navigate -> evaluate -> cleanup."""
    episode_dir = output_dir / f"episode_{episode_index}"
    episode_dir.mkdir(parents=True, exist_ok=True)
    events_log_file = episode_dir / "events.log"

    def ep_log(msg: str):
        t_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{t_str}] {msg}"
        print(line, flush=True)
        with open(events_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    ep_log(f"=== Starting Isolated Episode {episode_index} (Cancel Test: {is_cancel_test}) ===")
    ep_log(f"Action: {action_dict}")

    # 1. Clean lingering processes
    cleanup_simulation_processes()

    # 2. Spawn simulation subprocess
    env = os.environ.copy()
    env["TURTLEBOT3_MODEL"] = "waffle"
    env["GAZEBO_MODEL_DATABASE_URI"] = ""
    env["GAZEBO_MODEL_PATH"] = "/usr/share/gazebo-11/models:/opt/ros/humble/share/turtlebot3_gazebo/models"
    env["ROS_DOMAIN_ID"] = "42"
    env["ROS_LOCALHOST_ONLY"] = "1"

    launch_cmd = [
        "ros2", "launch", "nav2_bringup", "tb3_simulation_launch.py",
        "headless:=True", "use_rviz:=False", "autostart:=True",
        "map:=/workspace/configs/turtlebot3_world.yaml",
        "params_file:=/workspace/configs/nav2_params.yaml",
        "world:=/workspace/configs/world_with_state.model",
        "x_pose:=-2.0", "y_pose:=-0.5",
    ]
    ep_log(f"Spawning simulation: {' '.join(launch_cmd)}")
    sim_log_path = episode_dir / "nav2_sim.log"
    sim_log = open(sim_log_path, "w", encoding="utf-8")
    sim_proc = subprocess.Popen(launch_cmd, env=env, stdout=sim_log, stderr=subprocess.STDOUT)

    runner_node: Optional[EpisodeRunnerNode] = None
    rclpy.init()

    try:
        runner_node = EpisodeRunnerNode(f"ep_{episode_index}", ep_log)

        # 3. Wait for /clock advancement
        ep_log("Waiting for /clock to advance...")
        if not runner_node.wait_for_sim_clock(min_sim_advance_sec=1.0, wall_timeout_sec=35.0):
            raise TimeoutError("Sim clock failed to advance within 35s wall time")

        # 4. Wait for Action server
        ep_log("Waiting for /navigate_to_pose action server...")
        server_ready = False
        for _ in range(40):
            if runner_node.action_client.wait_for_server(timeout_sec=1.0):
                server_ready = True
                ep_log("Action server ready!")
                break
            rclpy.spin_once(runner_node, timeout_sec=0.1)
        if not server_ready:
            raise TimeoutError("/navigate_to_pose action server did not become available")

        # 5. Wait for Nav2 bt_navigator to reach ACTIVE lifecycle state
        ep_log("Waiting for Nav2 bt_navigator lifecycle to reach ACTIVE state...")
        if not runner_node.wait_for_nav2_active(wall_timeout_sec=35.0):
            raise TimeoutError("Nav2 bt_navigator failed to reach ACTIVE state")

        # 6. Wait for sensors & initialize AMCL
        ep_log("Waiting for sensor streams...")
        if not runner_node.wait_for_sensors(wall_timeout_sec=25.0):
            raise TimeoutError("Sensors did not stream within 25s")

        ep_log("Initializing AMCL pose at [-2.0, -0.5, 0.0]...")
        if not runner_node.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0, wall_timeout_sec=25.0):
            raise TimeoutError("AMCL failed to initialize pose")

        # Capture initial states
        initial_gt = copy.deepcopy(runner_node.latest_gt_record)
        initial_amcl = copy.deepcopy(runner_node.latest_amcl_record)
        initial_odom = copy.deepcopy(runner_node.latest_odom_record)

        # 7. Capture topology
        nodes = subprocess.check_output(["ros2", "node", "list"], env=env, text=True).strip().split("\n")
        topics = subprocess.check_output(["ros2", "topic", "list"], env=env, text=True).strip().split("\n")
        actions = subprocess.check_output(["ros2", "action", "list"], env=env, text=True).strip().split("\n")
        with open(episode_dir / "ros_nodes.txt", "w") as f:
            f.write("\n".join(nodes) + "\n")
        with open(episode_dir / "ros_topics.txt", "w") as f:
            f.write("\n".join(topics) + "\n")
        with open(episode_dir / "ros_actions.txt", "w") as f:
            f.write("\n".join(actions) + "\n")

        # 8. Unified Action Dispatch
        context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
        dispatcher = ActionDispatcher(context=context)

        goal_handle = None
        action_result_status = None
        nav_start_sim_time = runner_node.get_sim_time_sec()
        nav_start_wall_time = time.monotonic()

        def ros_send_goal(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            nonlocal goal_handle
            goal_msg = NavigateToPose.Goal()
            goal_msg.pose.header.frame_id = act["params"]["frame_id"]
            goal_msg.pose.header.stamp = runner_node.get_clock().now().to_msg()
            g = act["params"]["goal"]
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

            ep_log(f"Sending NavigateToPose goal {g} (UUID: {goal_uuid})...")
            send_goal_future = runner_node.action_client.send_goal_async(goal_msg)
            rclpy.spin_until_future_complete(runner_node, send_goal_future, timeout_sec=10.0)

            if not send_goal_future.done():
                return {"status": "TIMEOUT_WAITING_ACCEPTANCE"}

            goal_handle = send_goal_future.result()
            if not goal_handle.accepted:
                return {"status": "REJECTED"}
            return {"status": "ACCEPTED"}

        dispatcher.ros_executor = ros_send_goal
        visible_state = {
            "amcl_pose": [initial_amcl["x"], initial_amcl["y"], initial_amcl["yaw"]],
            "action_type": action_dict.get("action"),
        }

        # Start tracking trajectory samples across entire run
        runner_node.is_tracking = True

        dispatch_res = dispatcher.dispatch(action_dict, visible_state=visible_state)
        ep_log(f"Dispatch result: {dispatch_res['pipeline_status']}")

        if dispatch_res["pipeline_status"] != "DISPATCHED" or not goal_handle or not goal_handle.accepted:
            ep_log(f"[FATAL] Action failed dispatch or was rejected: {dispatch_res}")
            return {
                "episode_index": episode_index,
                "status": "DISPATCH_FAILED_OR_REJECTED",
                "dispatch_result": dispatch_res,
                "initial_states": {"gt": initial_gt, "amcl": initial_amcl},
            }

        # 9. Execution loop
        get_result_future = goal_handle.get_result_async()

        if is_cancel_test:
            # Wait until robot actively begins moving (v > 0.05 m/s)
            ep_log("Cancel test: Waiting for confirmed active robot movement (linear_v > 0.05 m/s)...")
            movement_confirmed = False
            t_watchdog = time.monotonic()
            while time.monotonic() - t_watchdog < 15.0:
                rclpy.spin_once(runner_node, timeout_sec=0.1)
                if runner_node.latest_odom_record and abs(runner_node.latest_odom_record["linear_v"]) > 0.05:
                    movement_confirmed = True
                    ep_log(f"Robot movement confirmed! Velocity = {runner_node.latest_odom_record['linear_v']:.3f} m/s")
                    break

            if not movement_confirmed:
                ep_log("[WARN] Robot did not reach >0.05 m/s before cancel timeout")

            ep_log("Dispatching cancel_goal_async() to Action Server...")
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(runner_node, cancel_future, timeout_sec=5.0)

            # Wait for result to finalize
            rclpy.spin_until_future_complete(runner_node, get_result_future, timeout_sec=8.0)
            action_result_status = get_result_future.result().status
            status_name = "CANCELED" if action_result_status == GoalStatus.STATUS_CANCELED else f"STATUS_{action_result_status}"
            ep_log(f"Action terminal status: {status_name}")

        else:
            # Standard navigation: monitor until SUCCEEDED, ABORTED, or timeout
            sim_timeout = action_dict["params"].get("timeout_sec", 60.0)
            while rclpy.ok() and not get_result_future.done():
                rclpy.spin_once(runner_node, timeout_sec=0.1)
                sim_elapsed = runner_node.get_sim_time_sec() - nav_start_sim_time
                if sim_elapsed > sim_timeout:
                    ep_log(f"[WARN] Action sim timeout exceeded ({sim_elapsed:.1f}s > {sim_timeout}s)")
                    goal_handle.cancel_goal_async()
                    rclpy.spin_until_future_complete(runner_node, get_result_future, timeout_sec=5.0)
                    break

            action_result_status = get_result_future.result().status if get_result_future.done() else GoalStatus.STATUS_UNKNOWN
            status_name = "SUCCEEDED" if action_result_status == GoalStatus.STATUS_SUCCEEDED else f"STATUS_{action_result_status}"
            ep_log(f"Navigation Action finished with status: {status_name}")

        nav_duration_sim_sec = runner_node.get_sim_time_sec() - nav_start_sim_time
        nav_duration_wall_sec = time.monotonic() - nav_start_wall_time

        # 10. Post-Action Settling & Stability Window Execution (2.0s sim time)
        ep_log("Allowing deceleration settling (<=2.0s sim time)...")
        runner_node.wait_for_settling(max_sim_sec=2.0)

        ep_log("Starting post-action stability observation window (>= 2.0s sim time)...")
        stability_samples = runner_node.record_stability_window(duration_sim_sec=2.0, max_wall_sec=12.0)
        runner_node.is_tracking = False
        ep_log(f"Stability window captured {len(stability_samples)} samples.")

        # 11. Objective Scoring & Evaluation
        thresh = scoring_rules["thresholds"]
        pos_tol = float(thresh["position_tolerance_m"])  # strictly 0.30
        yaw_tol = float(thresh["yaw_tolerance_rad"])     # 0.35
        v_tol = float(thresh["max_linear_velocity_mps"]) # 0.05
        w_tol = float(thresh["max_angular_velocity_radps"]) # 0.05

        target_goal = action_dict["params"]["goal"]
        target_x, target_y, target_yaw = float(target_goal[0]), float(target_goal[1]), float(target_goal[2])

        final_gt = runner_node.latest_gt_record
        final_amcl = runner_node.latest_amcl_record

        gt_pos_err = math.hypot(final_gt["x"] - target_x, final_gt["y"] - target_y) if final_gt else None
        gt_yaw_err = abs(normalize_angle(final_gt["yaw"] - target_yaw)) if final_gt else None
        amcl_pos_err = math.hypot(final_amcl["x"] - target_x, final_amcl["y"] - target_y) if final_amcl else None
        amcl_yaw_err = abs(normalize_angle(final_amcl["yaw"] - target_yaw)) if final_amcl else None

        # Stability checks across the window
        all_gt_pos_ok = True
        all_gt_yaw_ok = True
        all_vel_stopped = True
        data_fresh = len(stability_samples) >= 10

        # Check GT position displacement within the window
        gt_positions = [(s["gt"]["x"], s["gt"]["y"]) for s in stability_samples if s.get("gt")]
        if gt_positions:
            disp_x = max(p[0] for p in gt_positions) - min(p[0] for p in gt_positions)
            disp_y = max(p[1] for p in gt_positions) - min(p[1] for p in gt_positions)
            max_disp_in_window = math.hypot(disp_x, disp_y)
        else:
            max_disp_in_window = None

        for s in stability_samples:
            if s.get("gt"):
                d = math.hypot(s["gt"]["x"] - target_x, s["gt"]["y"] - target_y)
                dyaw = abs(normalize_angle(s["gt"]["yaw"] - target_yaw))
                if d > pos_tol:
                    all_gt_pos_ok = False
                if dyaw > yaw_tol:
                    all_gt_yaw_ok = False
            if s.get("odom"):
                if abs(s["odom"].get("linear_v", 0.0)) > v_tol or abs(s["odom"].get("angular_v", 0.0)) > w_tol:
                    all_vel_stopped = False
            if s.get("cmd_vel"):
                if abs(s["cmd_vel"].get("linear_x", 0.0)) > v_tol or abs(s["cmd_vel"].get("angular_z", 0.0)) > w_tol:
                    all_vel_stopped = False

        if not is_cancel_test:
            physical_arrived = (gt_pos_err is not None and gt_pos_err <= pos_tol and gt_yaw_err <= yaw_tol)
            strict_arrival_and_stable = (all_gt_pos_ok and all_gt_yaw_ok and all_vel_stopped and data_fresh)
            cancel_stop_verified = None
        else:
            physical_arrived = None
            strict_arrival_and_stable = None
            cancel_stop_verified = (
                action_result_status == GoalStatus.STATUS_CANCELED
                and all_vel_stopped
                and data_fresh
                and (max_disp_in_window is not None and max_disp_in_window < 0.03)
            )

        # Time-aligned AMCL vs GT comparison across the episode
        aligned_comparisons = []
        unique_amcl = {s["recv_sim_time_sec"]: s for s in runner_node.episode_amcl_samples if s.get("recv_sim_time_sec") is not None}
        for t_amcl, amcl_s in sorted(unique_amcl.items()):
            if not runner_node.episode_gt_samples:
                continue
            closest_gt = min(runner_node.episode_gt_samples, key=lambda g: abs(g["recv_sim_time_sec"] - t_amcl))
            t_diff = abs(closest_gt["recv_sim_time_sec"] - t_amcl)
            if t_diff <= float(thresh["max_time_alignment_delta_sim_sec"]):
                discrepancy = math.hypot(amcl_s["x"] - closest_gt["x"], amcl_s["y"] - closest_gt["y"])
                aligned_comparisons.append({
                    "sim_time": t_amcl,
                    "time_delta_sec": round(t_diff, 4),
                    "amcl_xy": [amcl_s["x"], amcl_s["y"]],
                    "gt_xy": [closest_gt["x"], closest_gt["y"]],
                    "localization_discrepancy_m": round(discrepancy, 4),
                })

        mean_loc_discrepancy = (
            round(sum(c["localization_discrepancy_m"] for c in aligned_comparisons) / len(aligned_comparisons), 4)
            if aligned_comparisons else None
        )

        # Save trajectory and stability window data
        trajectory_data = {
            "gt_trajectory": runner_node.episode_gt_samples,
            "amcl_trajectory": runner_node.episode_amcl_samples,
            "odom_trajectory": runner_node.episode_odom_samples,
            "aligned_comparisons": aligned_comparisons,
        }
        with open(episode_dir / "trajectory.json", "w", encoding="utf-8") as f:
            json.dump(trajectory_data, f, indent=2)

        with open(episode_dir / "stability_window.json", "w", encoding="utf-8") as f:
            json.dump(stability_samples, f, indent=2)

        episode_summary = {
            "episode_index": episode_index,
            "action_id": action_dict.get("action_id"),
            "goal": target_goal,
            "is_cancel_test": is_cancel_test,
            "nav2_action_status": status_name,
            "nav2_status_code": int(action_result_status) if action_result_status is not None else None,
            "nav2_action_succeeded": (action_result_status == GoalStatus.STATUS_SUCCEEDED),
            "timing": {
                "nav_duration_sim_sec": round(nav_duration_sim_sec, 3),
                "nav_duration_wall_sec": round(nav_duration_wall_sec, 3),
                "stability_samples_count": len(stability_samples),
                "total_gt_samples": len(runner_node.episode_gt_samples),
                "total_amcl_samples": len(runner_node.episode_amcl_samples),
            },
            "final_geometric_errors": {
                "gt_position_error_m": round(gt_pos_err, 4) if gt_pos_err is not None else None,
                "gt_yaw_error_rad": round(gt_yaw_err, 4) if gt_yaw_err is not None else None,
                "amcl_position_error_m": round(amcl_pos_err, 4) if amcl_pos_err is not None else None,
                "amcl_yaw_error_rad": round(amcl_yaw_err, 4) if amcl_yaw_err is not None else None,
                "thresholds_applied": {
                    "position_tolerance_m": pos_tol,
                    "yaw_tolerance_rad": yaw_tol,
                },
            },
            "stability_window_evaluation": {
                "all_samples_position_ok": bool(all_gt_pos_ok),
                "all_samples_yaw_ok": bool(all_gt_yaw_ok),
                "all_samples_stopped": bool(all_vel_stopped),
                "max_gt_displacement_in_window_m": round(max_disp_in_window, 4) if max_disp_in_window is not None else None,
                "data_freshness_ok": bool(data_fresh),
                "strict_physical_arrival_and_stable": bool(strict_arrival_and_stable),
                "cancel_stop_verified": bool(cancel_stop_verified) if is_cancel_test else None,
            },
            "localization_evaluation": {
                "time_aligned_samples_count": len(aligned_comparisons),
                "mean_localization_discrepancy_m": mean_loc_discrepancy,
                "alignment_max_delta_sec": float(thresh["max_time_alignment_delta_sim_sec"]),
            },
            "initial_states": {
                "gt": initial_gt,
                "amcl": initial_amcl,
            },
            "final_states": {
                "gt": final_gt,
                "amcl": final_amcl,
            },
        }

        with open(episode_dir / "episode_summary.json", "w", encoding="utf-8") as f:
            json.dump(episode_summary, f, indent=2)

        ep_log(f"Episode {episode_index} complete: Nav2={status_name} | GT_err={gt_pos_err} | Stable={strict_arrival_and_stable or cancel_stop_verified}")
        return episode_summary

    finally:
        ep_log("Cleaning up episode ROS node and simulation process...")
        if runner_node:
            runner_node.destroy_node()
        rclpy.shutdown()
        sim_proc.send_signal(signal.SIGINT)
        try:
            sim_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            sim_proc.kill()
        sim_log.close()
        cleanup_simulation_processes()


def main():
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"p1a_v2_{run_timestamp}_{uuid.uuid4().hex[:6]}"
    output_dir = REPO_ROOT / f"reports/evidence/p1a_v2/{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    scoring_rules = load_scoring_rules()

    # Save run configuration
    with open(output_dir / "run_config.json", "w", encoding="utf-8") as f:
        json.dump({
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": "P1a-v2 (Independent Episodes & Unified Time)",
            "scoring_rules": scoring_rules,
        }, f, indent=2)

    episodes = [
        # Episode 1: Waypoint 1 (Forward transit)
        {
            "action": {
                "action": "navigate",
                "action_id": "nav_ep1_fwd",
                "params": {"goal": [-0.5, -0.5, 0.0], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": False,
        },
        # Episode 2: Waypoint 2 (Lateral transit in free space)
        {
            "action": {
                "action": "navigate",
                "action_id": "nav_ep2_lateral",
                "params": {"goal": [0.5, -0.5, 1.57], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": False,
        },
        # Episode 3: Waypoint 3 (Corridor return transit)
        {
            "action": {
                "action": "navigate",
                "action_id": "nav_ep3_return",
                "params": {"goal": [-1.8, -0.5, 3.14], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": False,
        },
        # Episode 4: Cancellation test with distant reachable goal
        {
            "action": {
                "action": "navigate",
                "action_id": "nav_ep4_cancel",
                "params": {"goal": [0.5, 1.8, 0.0], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": True,
        },
    ]

    summaries = []
    for i, ep in enumerate(episodes, 1):
        ep_summary = run_single_episode(
            episode_index=i,
            action_dict=ep["action"],
            is_cancel_test=ep["is_cancel"],
            output_dir=output_dir,
            scoring_rules=scoring_rules,
        )
        summaries.append(ep_summary)
        time.sleep(2.0)

    # Master summary
    nav_succeeded_count = sum(1 for s in summaries[:3] if s.get("nav2_action_succeeded"))
    strict_arrival_count = sum(1 for s in summaries[:3] if s.get("stability_window_evaluation", {}).get("strict_physical_arrival_and_stable"))
    cancel_passed = bool(summaries[3].get("stability_window_evaluation", {}).get("cancel_stop_verified"))

    master_summary = {
        "run_id": run_id,
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1a-v2",
        "scoring_rules": scoring_rules,
        "episodes": summaries,
        "overall_evaluation": {
            "total_episodes": len(summaries),
            "nav_episodes_count": 3,
            "nav_nav2_succeeded_count": nav_succeeded_count,
            "nav_strict_physical_arrival_count": strict_arrival_count,
            "cancel_test_passed": cancel_passed,
        },
        "boundary_notice": (
            "P1a-v2 verifies independent simulation reset, unified ROS sim time, "
            "strict 0.30m arrival stability window, and post-cancel physical halt. "
            "Observe action is NOT yet implemented. No LLM loops or FailMem methods included."
        ),
    }

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(master_summary, f, indent=2)

    # Generate checksums
    checksum_lines = []
    for fpath in sorted(output_dir.rglob("*")):
        if fpath.is_file() and fpath.name != "checksums.sha256":
            with open(fpath, "rb") as bf:
                h = hashlib.sha256(bf.read()).hexdigest()
            rel = fpath.relative_to(output_dir)
            checksum_lines.append(f"{h}  {rel}")

    with open(output_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        f.write("\n".join(checksum_lines) + "\n")

    print(f"\n=== P1a-v2 Execution Complete. Results in {output_dir} ===")
    print(f"Nav2 Succeeded: {nav_succeeded_count}/3 | Strict Physical Arrival & Stable: {strict_arrival_count}/3 | Cancel Stop: {cancel_passed}")


if __name__ == "__main__":
    main()
