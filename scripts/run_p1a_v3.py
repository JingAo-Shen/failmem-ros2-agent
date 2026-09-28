#!/usr/bin/env python3
"""FailMem P1a-v3 Execution & Verification Suite.

Features:
1. Isolated simulation lifecycle management per episode (process group isolation, clean teardown).
2. Unified ROS simulation time (use_sim_time=True, /clock progress check, wall-clock watchdogs).
3. Passive halt verification without active cmd_vel interference on normal acceptance path.
4. Movement confirmation before cancellation, cancel acceptance, and passive stop verification.
5. Strict contract arrival (0.30m position tolerance, 0.35rad yaw tolerance, >=2.0s sim stability window).
6. Scoped ROS Goal UUID derivation passed directly to ActionClient and verified on GoalHandle.
7. Retry execution parameter restoration and distinct UUID generation.
8. Time-aligned AMCL vs GT localization discrepancy audit (delta t <= 0.1s).
9. Empirical world == map coordinate alignment proof across 5 static landmarks.
10. Integrated offline scoring evaluator with JSON output and SHA256 checksums.
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
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, "/workspace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from gazebo_msgs.msg import ModelStates
from lifecycle_msgs.srv import GetState
from unique_identifier_msgs.msg import UUID as RosUUID

from src.action_dispatcher import ActionDispatcher, derive_ros_goal_uuid
from src.action_runtime import EpisodeActionHistoryContext
from src.coordinate_alignment import verify_world_map_alignment
from src.scoring_evaluator import (
    evaluate_navigation_episode,
    evaluate_cancellation_episode,
    audit_localization_discrepancy,
    load_scoring_rules,
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
            # Check if process group still exists
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


class EpisodeRunnerNode(Node):
    """ROS 2 Node for an isolated navigation episode with unified simulation time."""

    def __init__(self, episode_id: str, event_logger: Callable[[str], None]):
        super().__init__(
            f"failmem_runner_{episode_id}",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        self.episode_id = episode_id
        self.event_logger = event_logger

        sim_time_param = self.get_parameter("use_sim_time").get_parameter_value().bool_value
        if not sim_time_param:
            raise RuntimeError("CRITICAL: Node parameter 'use_sim_time' is not True!")

        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "initialpose", 10)
        self.emergency_cmd_pub = self.create_publisher(Twist, "cmd_vel", 10)

        self.cmd_vel_sub = self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, "odom", self._odom_cb, 10)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "amcl_pose", self._amcl_cb, 10)
        self.gazebo_sub = self.create_subscription(ModelStates, "/gazebo/model_states", self._gazebo_cb, 10)

        self.latest_odom_record: Optional[Dict[str, Any]] = None
        self.latest_amcl_record: Optional[Dict[str, Any]] = None
        self.latest_gt_record: Optional[Dict[str, Any]] = None
        self.latest_cmd_vel_record: Optional[Dict[str, Any]] = None

        self.odom_msg_count = 0
        self.amcl_msg_count = 0
        self.gt_msg_count = 0
        self.cmd_vel_msg_count = 0

        self.is_tracking = False
        self.episode_gt_samples: List[Dict[str, Any]] = []
        self.episode_amcl_samples: List[Dict[str, Any]] = []
        self.episode_odom_samples: List[Dict[str, Any]] = []
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
        self.amcl_msg_count += 1
        sim_now = self.get_sim_time_sec()
        p = msg.pose.pose.position
        o = msg.pose.pose.orientation
        yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
        cov = list(msg.pose.covariance)
        cov_diag = [cov[0], cov[7], cov[35]]  # var(x), var(y), var(yaw)
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

    def _gazebo_cb(self, msg: ModelStates):
        sim_now = self.get_sim_time_sec()
        target_name = None
        for cand in ["turtlebot3_waffle", "waffle"]:
            if cand in msg.name:
                target_name = cand
                break
        if target_name is None:
            return

        self.gt_msg_count += 1
        idx = msg.name.index(target_name)
        pose = msg.pose[idx]
        p = pose.position
        o = pose.orientation
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

    def wait_for_sim_clock(self, min_sim_advance_sec: float = 1.0, wall_timeout_sec: float = 35.0) -> bool:
        """Wait until /clock advances by min_sim_advance_sec simulation time."""
        t_wall_start = time.monotonic()
        t_sim_initial = None

        while time.monotonic() - t_wall_start < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            sim_now = self.get_sim_time_sec()
            if sim_now > 0.05:
                if t_sim_initial is None:
                    t_sim_initial = sim_now
                elif (sim_now - t_sim_initial) >= min_sim_advance_sec:
                    self.log(f"Sim clock advanced: {t_sim_initial:.2f}s -> {sim_now:.2f}s (delta={sim_now - t_sim_initial:.2f}s)")
                    return True
            time.sleep(0.05)
        return False

    def wait_for_nav2_active(self, wall_timeout_sec: float = 35.0) -> bool:
        """Verify bt_navigator reaches lifecycle state 3 (active)."""
        client = self.create_client(GetState, "/bt_navigator/get_state")
        t_wall_start = time.monotonic()

        while time.monotonic() - t_wall_start < wall_timeout_sec:
            if not client.service_is_ready():
                time.sleep(0.5)
                continue

            req = GetState.Request()
            future = client.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=1.0)

            if future.done() and future.result() is not None:
                state = future.result().current_state
                if state.id == 3:  # PRIMARY_STATE_ACTIVE
                    self.log(f"Nav2 bt_navigator is verified ACTIVE ({state.id} {state.label})!")
                    return True
                else:
                    self.log(f"Nav2 bt_navigator state: {state.id} ({state.label}), waiting for active...")
            time.sleep(0.5)
        return False

    def wait_for_sensors(self, wall_timeout_sec: float = 25.0) -> bool:
        """Wait until odom and ground truth streams are actively arriving."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_odom_record is not None and self.latest_gt_record is not None:
                self.log(f"Sensors streaming: odom={self.latest_odom_record['x']:.2f}, gt={self.latest_gt_record['x']:.2f}")
                return True
            time.sleep(0.1)
        return False

    def initialize_amcl_pose(self, x: float = -2.0, y: float = -0.5, yaw: float = 0.0, wall_timeout_sec: float = 25.0) -> bool:
        """Publish initialpose and wait for AMCL particle dispersion and convergence."""
        t_start = time.monotonic()
        for attempt in range(8):
            msg = PoseWithCovarianceStamped()
            msg.header.frame_id = "map"
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.pose.pose.position.x = x
            msg.pose.pose.position.y = y
            msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
            msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
            msg.pose.covariance[0] = 0.25
            msg.pose.covariance[7] = 0.25
            msg.pose.covariance[35] = 0.068

            self.initial_pose_pub.publish(msg)

            for _ in range(15):
                rclpy.spin_once(self, timeout_sec=0.1)
                if self.latest_amcl_record is not None:
                    dist = math.hypot(self.latest_amcl_record["x"] - x, self.latest_amcl_record["y"] - y)
                    if dist < 0.60:
                        self.log(f"AMCL pose converged at x={self.latest_amcl_record['x']:.2f}, y={self.latest_amcl_record['y']:.2f} (delta={dist:.2f}m)")
                        for _ in range(5):
                            rclpy.spin_once(self, timeout_sec=0.1)
                        return True
            time.sleep(0.3)
        return False

    def wait_for_passive_settling(
        self,
        max_sim_sec: float = 2.5,
        wall_timeout_sec: float = 10.0,
    ) -> Tuple[bool, bool]:
        """PASSIVE observation of robot halt without publishing cmd_vel.

        Returns:
            (settled_to_halt, safety_intervention)
        """
        sim_start = self.get_sim_time_sec()
        wall_start = time.monotonic()
        consecutive_stopped = 0
        safety_intervention = False

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.05)
            lv = abs(self.latest_odom_record.get("linear_v", 1.0)) if self.latest_odom_record else 1.0
            av = abs(self.latest_odom_record.get("angular_v", 1.0)) if self.latest_odom_record else 1.0

            if lv < 0.03 and av < 0.03:
                consecutive_stopped += 1
                if consecutive_stopped >= 4:
                    self.log(f"Robot passively settled to halt (lv={lv:.4f} m/s, av={av:.4f} rad/s, NO safety intervention)")
                    return True, False
            else:
                consecutive_stopped = 0

            if (self.get_sim_time_sec() - sim_start) > max_sim_sec or (time.monotonic() - wall_start) > wall_timeout_sec:
                self.log(f"[WARN] Passive settling timed out (sim={self.get_sim_time_sec() - sim_start:.2f}s, wall={time.monotonic() - wall_start:.2f}s). Triggering emergency stop intervention.")
                # Emergency intervention fallback
                safety_intervention = True
                stop_twist = Twist()
                for _ in range(5):
                    self.emergency_cmd_pub.publish(stop_twist)
                    rclpy.spin_once(self, timeout_sec=0.05)
                return False, True

        return False, False

    def record_stability_window(
        self,
        duration_sim_sec: float = 2.2,
        max_wall_sec: float = 15.0,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Collect continuous high-rate samples for at least duration_sim_sec simulation time.
        
        Returns:
            (window_records, watchdog_triggered)
        """
        sim_start_sample = None
        wall_start = time.monotonic()
        window_records = []
        last_recorded_odom_seq = None
        watchdog_triggered = False

        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.04)
            sim_now = self.get_sim_time_sec()
            wall_now = time.monotonic()

            # Record only on new sample
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
                    "cmd_vel": copy.deepcopy(self.latest_cmd_vel_record),
                })

            if sim_start_sample is not None and (sim_now - sim_start_sample) >= duration_sim_sec:
                break
            if (wall_now - wall_start) > max_wall_sec:
                self.log("[WARN] Stability window wall-clock watchdog triggered!")
                watchdog_triggered = True
                break

        return window_records, watchdog_triggered


def run_single_episode(
    episode_index: int,
    action_dict: Dict[str, Any],
    is_cancel_test: bool,
    output_dir: Path,
    scoring_rules: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """Execute a completely isolated episode with process group management and passive halt observation."""
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

    # 1. Clean simulation state before launch
    cleanup_global_simulation()

    # 2. Spawn simulation subprocess in dedicated process group
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

    sim_proc = subprocess.Popen(
        launch_cmd,
        env=env,
        stdout=sim_log,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,  # Dedicated process group for clean teardown
    )

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
        t_srv_start = time.monotonic()
        while time.monotonic() - t_srv_start < 40.0:
            if runner_node.action_client.wait_for_server(timeout_sec=0.5):
                server_ready = True
                ep_log("Action server ready!")
                break
            rclpy.spin_once(runner_node, timeout_sec=0.1)

        if not server_ready:
            raise TimeoutError("/navigate_to_pose action server did not become available")

        # 5. Wait for Nav2 bt_navigator lifecycle ACTIVE state
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

        initial_gt = copy.deepcopy(runner_node.latest_gt_record)
        initial_amcl = copy.deepcopy(runner_node.latest_amcl_record)
        initial_odom = copy.deepcopy(runner_node.latest_odom_record)

        # Capture topology
        try:
            nodes = subprocess.check_output(["ros2", "node", "list"], env=env, text=True).strip().split("\n")
            topics = subprocess.check_output(["ros2", "topic", "list"], env=env, text=True).strip().split("\n")
            actions = subprocess.check_output(["ros2", "action", "list"], env=env, text=True).strip().split("\n")
            with open(episode_dir / "ros_nodes.txt", "w") as f:
                f.write("\n".join(nodes) + "\n")
            with open(episode_dir / "ros_topics.txt", "w") as f:
                f.write("\n".join(topics) + "\n")
            with open(episode_dir / "ros_actions.txt", "w") as f:
                f.write("\n".join(actions) + "\n")
        except Exception as e:
            ep_log(f"[WARN] Failed to capture ROS topology: {e}")

        # 7. Unified Action Dispatch with Scoped UUID
        context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
        dispatcher = ActionDispatcher(context=context, run_id=run_id, episode_id=f"ep_{episode_index}")

        goal_handle = None
        action_result_status = None
        cancel_accepted = False
        movement_confirmed = False
        nav_start_sim_time = runner_node.get_sim_time_sec()
        nav_start_wall_time = time.monotonic()

        def ros_send_goal(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            nonlocal goal_handle
            goal_msg = NavigateToPose.Goal()
            target_params = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = target_params.get("frame_id", "map")
            goal_msg.pose.header.stamp = runner_node.get_clock().now().to_msg()
            g = target_params["goal"]
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.z = math.sin(float(g[2]) / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(float(g[2]) / 2.0)

            ros_goal_uuid = RosUUID(uuid=list(goal_uuid.bytes))
            ep_log(f"Sending NavigateToPose goal {g} with Scoped UUID: {goal_uuid}...")

            send_goal_future = runner_node.action_client.send_goal_async(goal_msg, goal_uuid=ros_goal_uuid)
            rclpy.spin_until_future_complete(runner_node, send_goal_future, timeout_sec=10.0)

            if not send_goal_future.done():
                return {"status": "TIMEOUT_WAITING_ACCEPTANCE", "accepted": False}

            goal_handle = send_goal_future.result()
            if goal_handle is None or not goal_handle.accepted:
                return {"status": "REJECTED", "accepted": False}

            returned_goal_id_bytes = bytes(goal_handle.goal_id.uuid)
            uuid_verified = (returned_goal_id_bytes == goal_uuid.bytes)
            ep_log(f"Goal accepted! Verified GoalHandle UUID match: {uuid_verified}")

            return {
                "status": "ACCEPTED",
                "accepted": True,
                "goal_id": str(goal_uuid),
                "goal_id_verified": uuid_verified,
            }

        dispatcher.ros_executor = ros_send_goal
        visible_state = {
            "amcl_pose": [initial_amcl["x"], initial_amcl["y"], initial_amcl["yaw"]] if initial_amcl else None,
            "action_type": action_dict.get("action"),
        }

        # Track trajectory samples throughout action execution
        runner_node.is_tracking = True

        dispatch_res = dispatcher.dispatch(action_dict, visible_state=visible_state)
        ep_log(f"Dispatch pipeline status: {dispatch_res['pipeline_status']}")

        if dispatch_res["pipeline_status"] != "DISPATCHED" or not goal_handle or not goal_handle.accepted:
            ep_log(f"[FATAL] Action failed dispatch or was rejected: {dispatch_res}")
            return {
                "episode_index": episode_index,
                "status": "DISPATCH_FAILED_OR_REJECTED",
                "dispatch_result": dispatch_res,
                "initial_states": {"gt": initial_gt, "amcl": initial_amcl},
            }

        # 8. Execution loop
        get_result_future = goal_handle.get_result_async()

        if is_cancel_test:
            # Wait for active motion confirmation (linear_v > 0.05 m/s) with fresh odom
            ep_log("Cancel test: Waiting for confirmed active robot movement (linear_v > 0.05 m/s)...")
            t_watchdog = time.monotonic()
            while time.monotonic() - t_watchdog < 15.0:
                rclpy.spin_once(runner_node, timeout_sec=0.05)
                if runner_node.latest_odom_record:
                    lv = abs(runner_node.latest_odom_record.get("linear_v", 0.0))
                    if lv > 0.05:
                        movement_confirmed = True
                        ep_log(f"Robot movement CONFIRMED! Current velocity = {lv:.3f} m/s")
                        break
                time.sleep(0.02)

            if not movement_confirmed:
                ep_log("[FATAL] Cancel test failed: Robot did not reach >0.05 m/s within 15s watchdog!")
                action_result_status = GoalStatus.STATUS_UNKNOWN
            else:
                ep_log("Dispatching cancel_goal_async() to Action Server...")
                cancel_future = goal_handle.cancel_goal_async()
                rclpy.spin_until_future_complete(runner_node, cancel_future, timeout_sec=6.0)

                if cancel_future.done() and cancel_future.result() is not None:
                    cancel_res = cancel_future.result()
                    cancel_accepted = (cancel_res.return_code == 0)  # ERROR_NONE / ACCEPTED
                    ep_log(f"Cancel request result: return_code={cancel_res.return_code} (accepted={cancel_accepted})")
                else:
                    ep_log("[ERROR] Cancel request timed out or returned None")
                    cancel_accepted = False

                # Wait for terminal status to finalize
                rclpy.spin_until_future_complete(runner_node, get_result_future, timeout_sec=8.0)
                if get_result_future.done() and get_result_future.result() is not None:
                    action_result_status = get_result_future.result().status
                else:
                    action_result_status = GoalStatus.STATUS_UNKNOWN

        else:
            # Navigation execution loop with sim timeout and independent wall watchdog
            sim_timeout = action_dict["params"].get("timeout_sec", 60.0)
            wall_start = time.monotonic()
            max_wall_timeout = sim_timeout * 2.5 + 15.0

            while rclpy.ok() and not get_result_future.done():
                rclpy.spin_once(runner_node, timeout_sec=0.05)
                sim_elapsed = runner_node.get_sim_time_sec() - nav_start_sim_time
                wall_elapsed = time.monotonic() - wall_start

                if sim_elapsed > sim_timeout:
                    ep_log(f"[WARN] Action sim timeout exceeded ({sim_elapsed:.1f}s > {sim_timeout}s)")
                    goal_handle.cancel_goal_async()
                    rclpy.spin_until_future_complete(runner_node, get_result_future, timeout_sec=5.0)
                    break

                if wall_elapsed > max_wall_timeout:
                    ep_log(f"[WARN] Action wall watchdog triggered ({wall_elapsed:.1f}s > {max_wall_timeout}s)")
                    goal_handle.cancel_goal_async()
                    rclpy.spin_until_future_complete(runner_node, get_result_future, timeout_sec=5.0)
                    break

            if get_result_future.done() and get_result_future.result() is not None:
                action_result_status = get_result_future.result().status
            else:
                action_result_status = GoalStatus.STATUS_UNKNOWN

        status_name_map = {
            GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
            GoalStatus.STATUS_CANCELED: "CANCELED",
            GoalStatus.STATUS_ABORTED: "ABORTED",
            GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
        }
        status_name = status_name_map.get(action_result_status, f"STATUS_{action_result_status}")
        ep_log(f"Navigation Action finished with terminal status: {status_name}")

        # Write back terminal status to action dispatcher context
        dispatcher.record_terminal_status(
            action_dict["action_id"],
            terminal_status=status_name,
            status_code=int(action_result_status) if action_result_status is not None else None,
        )

        nav_duration_sim_sec = runner_node.get_sim_time_sec() - nav_start_sim_time
        nav_duration_wall_sec = time.monotonic() - nav_start_wall_time

        # 9. Passive Settling & Stability Window Execution (>= 2.0s sim time)
        ep_log("Passively observing deceleration settling (NO cmd_vel interference)...")
        settled_ok, safety_intervention = runner_node.wait_for_passive_settling(max_sim_sec=2.5, wall_timeout_sec=10.0)

        ep_log("Starting post-action stability observation window (>= 2.0s sim time)...")
        stability_samples, watchdog_triggered = runner_node.record_stability_window(duration_sim_sec=2.5, max_wall_sec=15.0)
        runner_node.is_tracking = False
        ep_log(f"Stability window captured {len(stability_samples)} distinct samples (watchdog_triggered={watchdog_triggered}).")

        # 10. Objective Scoring & Localization Audit using scoring_evaluator
        thresh = scoring_rules["thresholds"]
        target_goal = action_dict["params"]["goal"]

        if not is_cancel_test:
            scoring_res = evaluate_navigation_episode(
                target_goal=target_goal,
                nav2_status=status_name,
                final_gt=runner_node.latest_gt_record,
                final_amcl=runner_node.latest_amcl_record,
                stability_samples=stability_samples,
                thresholds=thresh,
                watchdog_triggered=watchdog_triggered,
                safety_intervention=safety_intervention,
            )
        else:
            scoring_res = evaluate_cancellation_episode(
                nav2_status=status_name,
                movement_confirmed_before_cancel=movement_confirmed,
                cancel_request_accepted=cancel_accepted,
                stability_samples=stability_samples,
                thresholds=thresh,
                watchdog_triggered=watchdog_triggered,
                safety_intervention=safety_intervention,
            )

        loc_audit = audit_localization_discrepancy(
            amcl_samples=runner_node.episode_amcl_samples,
            gt_samples=runner_node.episode_gt_samples,
            thresholds=thresh,
        )

        # Save trajectory and stability window data
        trajectory_data = {
            "gt_trajectory": runner_node.episode_gt_samples,
            "amcl_trajectory": runner_node.episode_amcl_samples,
            "odom_trajectory": runner_node.episode_odom_samples,
            "cmd_vel_trajectory": runner_node.episode_cmd_vel_samples,
            "localization_audit": loc_audit,
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
            "goal_uuid": dispatcher.goal_uuid_mapping.get(action_dict.get("action_id")),
            "timing": {
                "nav_duration_sim_sec": round(nav_duration_sim_sec, 3),
                "nav_duration_wall_sec": round(nav_duration_wall_sec, 3),
                "stability_samples_count": len(stability_samples),
                "total_gt_samples": len(runner_node.episode_gt_samples),
                "total_amcl_samples": len(runner_node.episode_amcl_samples),
                "total_odom_samples": len(runner_node.episode_odom_samples),
            },
            "evaluation": scoring_res,
            "localization_audit": {
                "time_aligned_samples_count": loc_audit["time_aligned_samples_count"],
                "unmatched_amcl_samples_count": loc_audit["unmatched_amcl_samples_count"],
                "mean_localization_discrepancy_m": loc_audit["mean_localization_discrepancy_m"],
                "alignment_max_delta_sec": loc_audit["alignment_max_delta_sec"],
            },
            "initial_states": {
                "gt": initial_gt,
                "amcl": initial_amcl,
            },
            "final_states": {
                "gt": runner_node.latest_gt_record,
                "amcl": runner_node.latest_amcl_record,
            },
        }

        with open(episode_dir / "episode_summary.json", "w", encoding="utf-8") as f:
            json.dump(episode_summary, f, indent=2)

        ep_log(f"Episode {episode_index} complete: Nav2={status_name} | Eval={scoring_res.get('strict_physical_arrival_and_stable', scoring_res.get('cancel_stop_verified'))}")
        return episode_summary

    finally:
        # Clean shutdown of runner node
        if runner_node is not None:
            runner_node.destroy_node()
        rclpy.shutdown()

        # Clean shutdown of simulation process group
        ep_log("Cleaning up episode simulation process group...")
        kill_process_group(os.getpgid(sim_proc.pid))
        sim_proc.wait(timeout=10.0)
        sim_log.close()
        cleanup_global_simulation()


def main():
    run_id = f"p1a_v3_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_dir = Path(f"/workspace/reports/evidence/p1a_v3/{run_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    scoring_rules = load_scoring_rules("/workspace/configs/scoring_rules.yaml")

    # 1. Verify World == Map Coordinate Alignment Proof
    coord_proof = verify_world_map_alignment(
        "/workspace/configs/turtlebot3_world.yaml",
        "/workspace/configs/turtlebot3_world.pgm",
    )
    with open(output_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    run_config = {
        "run_id": run_id,
        "phase": "P1a-v3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scoring_rules": scoring_rules,
        "coordinate_alignment_proof_verified": coord_proof["verified"],
        "max_residual_m": coord_proof.get("max_residual_m"),
    }
    with open(output_dir / "run_config.json", "w", encoding="utf-8") as f:
        json.dump(run_config, f, indent=2)

    # 2. Four distinct episodes
    episodes_config = [
        {
            "index": 1,
            "description": "Forward corridor navigation (1.5m distance > 0.30m threshold)",
            "action": {
                "action": "navigate",
                "action_id": "nav_ep1_fwd_corridor",
                "params": {"goal": [-0.5, -0.5, 0.0], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": False,
        },
        {
            "index": 2,
            "description": "Long lateral navigation + 90 deg rotation (2.5m distance)",
            "action": {
                "action": "navigate",
                "action_id": "nav_ep2_lateral_rot",
                "params": {"goal": [0.5, -0.5, 1.57], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": False,
        },
        {
            "index": 3,
            "description": "Short return & rotation (0.2m translation, reorientation to 180 deg)",
            "action": {
                "action": "navigate",
                "action_id": "nav_ep3_return_rot",
                "params": {"goal": [-1.8, -0.5, 3.14], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": False,
        },
        {
            "index": 4,
            "description": "Distant in-motion cancellation safety test (>3.3m distance)",
            "action": {
                "action": "navigate",
                "action_id": "nav_ep4_cancel_test",
                "params": {"goal": [0.5, 1.8, 0.0], "frame_id": "map", "timeout_sec": 60.0},
            },
            "is_cancel": True,
        },
    ]

    summaries = []
    for ep in episodes_config:
        ep_summary = run_single_episode(
            episode_index=ep["index"],
            action_dict=ep["action"],
            is_cancel_test=ep["is_cancel"],
            output_dir=output_dir,
            scoring_rules=scoring_rules,
            run_id=run_id,
        )
        summaries.append(ep_summary)
        time.sleep(2.0)

    # 3. Master Summary Compilation
    nav_succeeded_count = sum(1 for s in summaries[:3] if s.get("nav2_action_status") == "SUCCEEDED")
    strict_arrival_count = sum(1 for s in summaries[:3] if s.get("evaluation", {}).get("strict_physical_arrival_and_stable"))
    cancel_passed = bool(summaries[3].get("evaluation", {}).get("cancel_stop_verified"))

    master_summary = {
        "run_id": run_id,
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1a-v3",
        "scoring_rules": scoring_rules,
        "coordinate_alignment": {
            "verified": coord_proof["verified"],
            "max_residual_m": coord_proof.get("max_residual_m"),
            "tested_landmarks_count": coord_proof.get("non_collinear_landmarks_tested"),
        },
        "episodes": summaries,
        "overall_evaluation": {
            "total_episodes": len(summaries),
            "nav_episodes_count": 3,
            "nav_nav2_succeeded_count": nav_succeeded_count,
            "nav_strict_physical_arrival_count": strict_arrival_count,
            "cancel_test_passed": cancel_passed,
        },
        "boundary_notice": (
            "P1a-v3 verifies independent simulation reset, unified ROS sim time, "
            "passive halt verification without active cmd_vel interference, "
            "strict 0.30m contract arrival, and in-motion cancel safety stop. "
            "Minimal observe action is implemented in P1b. No LLM loops or FailMem methods included."
        ),
    }

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(master_summary, f, indent=2)

    # 4. Generate SHA256 Checksums
    checksum_lines = []
    for fpath in sorted(output_dir.rglob("*")):
        if fpath.is_file() and fpath.name != "checksums.sha256":
            with open(fpath, "rb") as bf:
                h = hashlib.sha256(bf.read()).hexdigest()
            rel = fpath.relative_to(output_dir)
            checksum_lines.append(f"{h}  {rel}")

    with open(output_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        f.write("\n".join(checksum_lines) + "\n")

    print(f"\n=== P1a-v3 Execution Complete. Results in {output_dir} ===")
    print(f"Nav2 Succeeded: {nav_succeeded_count}/3 | Strict Physical Arrival & Stable: {strict_arrival_count}/3 | Cancel Stop: {cancel_passed}")


if __name__ == "__main__":
    main()
