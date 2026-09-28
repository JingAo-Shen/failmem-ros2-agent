#!/usr/bin/env python3
"""FailMem P1b Complete Verification & Integration Suite.

Executes and verifies:
1. Live ROS observe integration (/scan, AMCL, Odom, Nav2 lifecycle, Goal status).
2. Live observe -> navigate -> observe execution chain.
3. Live navigate -> cancel -> retry -> observe execution chain with parameter restoration,
   distinct scoped UUIDs, and retry budget constraint enforcement.
4. Real ROS observation anomaly test suite (degraded scan, stale scan, wall-clock timeout).
5. 4-Episode Regression suite (3 contract navigations + 1 in-motion cancel test) using strict offline evaluator.
6. Clean process group isolation per episode.
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

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from gazebo_msgs.msg import ModelStates
from lifecycle_msgs.srv import GetState
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
    """ROS 2 Node for P1b with complete sensor streams and observe interface."""

    def __init__(self, node_name: str, event_logger: Callable[[str], None]):
        super().__init__(
            node_name,
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        self.event_logger = event_logger
        self.obs_interface = ObserveInterface(max_sensor_staleness_sec=0.5, max_stationary_amcl_staleness_sec=5.0)

        # Action Client & Publishers
        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "initialpose", 10)
        self.emergency_cmd_pub = self.create_publisher(Twist, "cmd_vel", 10)

        # Service Client for Nav2 Lifecycle
        self.lifecycle_client = self.create_client(GetState, "/bt_navigator/get_state")

        # Subscriptions
        self.cmd_vel_sub = self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, "odom", self._odom_cb, 10)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "amcl_pose", self._amcl_cb, 10)
        self.scan_sub = self.create_subscription(LaserScan, "scan", self._scan_cb, 10)
        self.gazebo_sub = self.create_subscription(ModelStates, "/gazebo/model_states", self._gazebo_cb, 10)

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
        self.gt_msg_count += 1
        sim_now = self.get_sim_time_sec()
        target_name = "turtlebot3_waffle"
        if target_name in msg.name:
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

    def get_live_observation(self, target_id: Optional[str] = None, current_goal_status: Optional[str] = "IDLE", wait_fresh: bool = True) -> Dict[str, Any]:
        """Perform a real read-only observation query."""
        lifecycle = self.query_nav2_lifecycle(timeout_sec=1.0)

        if wait_fresh:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 4.0:
                rclpy.spin_once(self, timeout_sec=0.05)
                sim_now = self.get_sim_time_sec()
                curr_scan_stamp = self.latest_scan_record.get("msg_stamp_sec") if self.latest_scan_record else None
                curr_odom_stamp = self.latest_odom_record.get("msg_stamp_sec") if self.latest_odom_record else None
                if (
                    curr_scan_stamp is not None and (sim_now - curr_scan_stamp) <= 0.35
                    and curr_odom_stamp is not None and (sim_now - curr_odom_stamp) <= 0.35
                ):
                    break
        else:
            rclpy.spin_once(self, timeout_sec=0.05)

        sim_now = self.get_sim_time_sec()
        return self.obs_interface.extract_observation(
            current_sim_time=sim_now,
            latest_amcl=self.latest_amcl_record,
            latest_odom=self.latest_odom_record,
            latest_scan=self.latest_scan_record,
            nav2_lifecycle_state=lifecycle,
            current_goal_status=current_goal_status,
        )

    def wait_for_sim_clock(self, min_sim_advance_sec: float = 1.0, wall_timeout_sec: float = 30.0) -> bool:
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

    def wait_for_sensors(self, wall_timeout_sec: float = 25.0) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_odom_record and self.latest_gt_record and self.latest_scan_record:
                self.log(f"Sensors streaming: odom={self.latest_odom_record['x']:.2f}, gt={self.latest_gt_record['x']:.2f}, scan={self.latest_scan_record['valid_count']} rays")
                return True
            time.sleep(0.05)
        return False

    def wait_for_nav2_active(self, wall_timeout_sec: float = 30.0) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            state = self.query_nav2_lifecycle(timeout_sec=0.5)
            if state == "ACTIVE":
                self.log("Nav2 bt_navigator is verified ACTIVE!")
                return True
            time.sleep(0.4)
        return False

    def initialize_amcl_pose(self, x: float = -2.0, y: float = -0.5, yaw: float = 0.0, wall_timeout_sec: float = 25.0) -> bool:
        pose_msg = PoseWithCovarianceStamped()
        pose_msg.header.frame_id = "map"
        pose_msg.header.stamp = self.get_clock().now().to_msg()
        pose_msg.pose.pose.position.x = x
        pose_msg.pose.pose.position.y = y
        pose_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        pose_msg.pose.covariance = [0.25] * 36

        t0 = time.monotonic()
        for _ in range(5):
            self.initial_pose_pub.publish(pose_msg)
            rclpy.spin_once(self, timeout_sec=0.1)
            time.sleep(0.05)

        while time.monotonic() - t0 < wall_timeout_sec:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.latest_amcl_record:
                dx = abs(self.latest_amcl_record["x"] - x)
                dy = abs(self.latest_amcl_record["y"] - y)
                if dx < 0.20 and dy < 0.20:
                    self.log(f"AMCL pose converged at x={self.latest_amcl_record['x']:.2f}, y={self.latest_amcl_record['y']:.2f} (delta={math.hypot(dx, dy):.2f}m)")
                    return True
            time.sleep(0.1)
        return False

    def wait_for_passive_settling(
        self,
        max_sim_sec: float = 3.0,
        wall_timeout_sec: float = 12.0,
    ) -> Tuple[bool, bool]:
        """Passively observe deceleration to halt without cmd_vel interference."""
        t_start_sim = self.get_sim_time_sec()
        t_start_wall = time.monotonic()
        last_seen_odom_seq = None
        consecutive_stopped_count = 0
        safety_intervention = False

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
                safety_intervention = True
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


def spawn_simulation(episode_dir: Path) -> Tuple[subprocess.Popen, Any]:
    """Spawn Nav2 + Gazebo in dedicated process group."""
    cleanup_global_simulation()
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
    sim_log = open(episode_dir / "nav2_sim.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        launch_cmd,
        env=env,
        stdout=sim_log,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    return proc, env


def run_p1b_complete_suite(output_root: Path) -> Dict[str, Any]:
    """Run all P1b verification and regression suites."""
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"p1b_{run_timestamp}_{uuid.uuid4().hex[:6]}"
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    scoring_rules = load_scoring_rules("configs/scoring_rules.yaml")
    thresholds = scoring_rules["thresholds"]

    # 1. Empirical Coordinate Proof
    coord_proof = verify_world_map_alignment(
        map_yaml_path="configs/turtlebot3_world.yaml",
        map_pgm_path="configs/turtlebot3_world.pgm",
        world_model_path="configs/world_with_state.model",
        sdf_model_path="configs/turtlebot3_world.model.sdf",
    )
    with open(run_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    suite_results: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1b",
        "scoring_rules": scoring_rules,
        "coordinate_alignment": {
            "verified": coord_proof["verified"],
            "max_residual_m": coord_proof.get("max_residual_m"),
            "tested_landmarks_count": coord_proof.get("non_collinear_landmarks_tested"),
        },
        "suite_1_observe_nav_observe": {},
        "suite_2_cancel_retry_observe": {},
        "suite_3_observe_anomalies": {},
        "suite_4_regression_episodes": [],
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

    try:
        node = P1bRunnerNode("p1b_suite1", log1)
        node.wait_for_sim_clock(min_sim_advance_sec=1.0)
        node.action_client.wait_for_server(timeout_sec=40.0)
        node.wait_for_nav2_active(wall_timeout_sec=35.0)
        node.wait_for_sensors(wall_timeout_sec=25.0)
        node.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0)

        context = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
        dispatcher = ActionDispatcher(context=context, run_id=run_id, episode_id="suite1")
        dispatcher.ros_observer = lambda act: node.get_live_observation(target_id=act.get("params", {}).get("target_id"))

        # Step 1: Initial Observe Action
        obs1_act = {"action": "observe", "action_id": "s1_obs_initial", "params": {"target_id": "front_corridor"}}
        obs1_res = dispatcher.dispatch(obs1_act)
        log1(f"Step 1 Observe Result: status={obs1_res['ros_result']['status']}")

        # Step 2: Navigate Action
        nav_goal_handle = None
        nav_res_status = None

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
        nav_dispatch_res = dispatcher.dispatch(nav_act, visible_state={"amcl_pose": obs1_res["ros_result"]["observation"]["localization"]["pose"]})
        log1(f"Step 2 Navigate Dispatched: {nav_dispatch_res['pipeline_status']}")

        get_res_future = nav_goal_handle.get_result_async()
        t_nav_start = time.monotonic()
        while rclpy.ok() and not get_res_future.done():
            rclpy.spin_once(node, timeout_sec=0.05)
            if time.monotonic() - t_nav_start > 35.0:
                nav_goal_handle.cancel_goal_async()
                break

        if get_res_future.done() and get_res_future.result() is not None:
            nav_res_status = get_res_future.result().status
        status_name = "SUCCEEDED" if nav_res_status == GoalStatus.STATUS_SUCCEEDED else f"STATUS_{nav_res_status}"
        dispatcher.record_terminal_status("s1_nav_target", terminal_status=status_name, status_code=int(nav_res_status))

        node.wait_for_passive_settling(max_sim_sec=2.5)
        stability_samples, watchdog = node.record_stability_window(duration_sim_sec=2.5)
        node.is_tracking = False

        nav_eval = evaluate_navigation_episode(
            target_goal=[-0.5, -0.5, 0.0],
            nav2_status=status_name,
            final_gt=node.latest_gt_record,
            final_amcl=node.latest_amcl_record,
            stability_samples=stability_samples,
            thresholds=thresholds,
            watchdog_triggered=watchdog,
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
                "evaluation": nav_eval,
            },
            "step3_observe": obs2_res,
            "action_history": context.action_history,
            "chain_verified": (
                obs1_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and nav_eval["strict_physical_arrival_and_stable"]
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

    try:
        node2 = P1bRunnerNode("p1b_suite2", log2)
        node2.wait_for_sim_clock(min_sim_advance_sec=1.0)
        node2.action_client.wait_for_server(timeout_sec=40.0)
        node2.wait_for_nav2_active(wall_timeout_sec=35.0)
        node2.wait_for_sensors(wall_timeout_sec=25.0)
        node2.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0)

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
            rclpy.spin_once(node2, timeout_sec=0.05)
            if node2.latest_odom_record:
                if abs(node2.latest_odom_record.get("linear_v", 0.0)) > 0.05:
                    movement_confirmed = True
                    log2("Robot movement confirmed > 0.05 m/s. Dispatching cancel...")
                    break

        cancel_future = active_goal_handle.cancel_goal_async()
        rclpy.spin_until_future_complete(node2, cancel_future, timeout_sec=6.0)
        cancel_accepted = (cancel_future.done() and cancel_future.result() is not None and cancel_future.result().return_code == 0)

        get_res_fut = active_goal_handle.get_result_async()
        rclpy.spin_until_future_complete(node2, get_res_fut, timeout_sec=8.0)
        status_code = get_res_fut.result().status if get_res_fut.done() and get_res_fut.result() is not None else GoalStatus.STATUS_CANCELED
        dispatcher2.record_terminal_status("s2_nav_orig", terminal_status="CANCELED", status_code=int(status_code))

        node2.wait_for_passive_settling(max_sim_sec=2.5)

        # Step 3: Valid Retry Action (Parameter restoration from s2_nav_orig)
        current_visible = {"amcl_pose": [node2.latest_amcl_record["x"], node2.latest_amcl_record["y"], node2.latest_amcl_record["yaw"]]}
        retry_act = {"action": "retry", "action_id": "s2_retry_nav", "params": {"original_action_id": "s2_nav_orig"}}
        node2.is_tracking = True
        res_retry = dispatcher2.dispatch(retry_act, visible_state=current_visible)
        log2(f"Step 3 Retry Dispatched (UUID={res_retry['goal_uuid']}) | Restored Goal: {res_retry['effective_action']['executable_params']['goal']}")

        retry_res_future = active_goal_handle.get_result_async()
        t_retry_start = time.monotonic()
        while rclpy.ok() and not retry_res_future.done():
            rclpy.spin_once(node2, timeout_sec=0.05)
            if time.monotonic() - t_retry_start > 45.0:
                active_goal_handle.cancel_goal_async()
                break

        retry_terminal_code = retry_res_future.result().status if retry_res_future.done() and retry_res_future.result() is not None else 4
        retry_status_name = "SUCCEEDED" if retry_terminal_code == GoalStatus.STATUS_SUCCEEDED else f"STATUS_{retry_terminal_code}"
        dispatcher2.record_terminal_status("s2_retry_nav", terminal_status=retry_status_name, status_code=int(retry_terminal_code))

        node2.wait_for_passive_settling(max_sim_sec=2.5)
        stability_samples2, watchdog2 = node2.record_stability_window(duration_sim_sec=2.5)
        node2.is_tracking = False

        retry_eval = evaluate_navigation_episode(
            target_goal=[0.5, -0.5, 1.57],
            nav2_status=retry_status_name,
            final_gt=node2.latest_gt_record,
            final_amcl=node2.latest_amcl_record,
            stability_samples=stability_samples2,
            thresholds=thresholds,
            watchdog_triggered=watchdog2,
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
                "terminal_status": "CANCELED",
            },
            "step3_retry": {
                "dispatch": res_retry,
                "executable_goal_restored": res_retry["effective_action"]["executable_params"]["goal"],
                "evaluation": retry_eval,
            },
            "step4_observe": obs_post_res,
            "step5_constraint_blocked": blocked_res,
            "dispatched_goal_uuids": dispatched_goal_ids,
            "distinct_uuids_verified": len(dispatched_goal_ids) == 2 and dispatched_goal_ids[0] != dispatched_goal_ids[1],
            "action_history": context2.action_history,
            "chain_verified": (
                res_init["pipeline_status"] == "DISPATCHED"
                and cancel_accepted
                and res_retry["pipeline_status"] == "DISPATCHED"
                and retry_eval["strict_physical_arrival_and_stable"]
                and obs_post_res["ros_result"]["status"] in ("SUCCESS", "DEGRADED")
                and blocked_res["pipeline_status"] == "FAILED"
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

    log3("=== Starting Suite 3: Observation Anomaly & Degraded Contract Tests ===")
    sim_proc3, env3 = spawn_simulation(ep3_dir)
    rclpy.init()

    try:
        node3 = P1bRunnerNode("p1b_suite3", log3)
        node3.wait_for_sim_clock(min_sim_advance_sec=1.0)
        node3.wait_for_nav2_active(wall_timeout_sec=35.0)
        node3.wait_for_sensors(wall_timeout_sec=25.0)
        node3.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0)

        # 3a. Normal Observation
        norm_obs = node3.get_live_observation(target_id="normal_test")
        log3(f"Test 3a (Normal Observation): status={norm_obs['status']}")

        # 3b. Degraded Scan (Stale Scan injection: pause scan updates for 2.0s sim time)
        stale_scan_record = copy.deepcopy(node3.latest_scan_record)
        stale_scan_record["msg_stamp_sec"] = node3.get_sim_time_sec() - 2.5
        degraded_obs = node3.obs_interface.extract_observation(
            current_sim_time=node3.get_sim_time_sec(),
            latest_amcl=node3.latest_amcl_record,
            latest_odom=node3.latest_odom_record,
            latest_scan=stale_scan_record,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
        )
        log3(f"Test 3b (Stale Scan Degraded): status={degraded_obs['status']}, error_type={degraded_obs.get('error_type')}")

        # 3c. Missing Scan Degraded
        missing_scan_obs = node3.obs_interface.extract_observation(
            current_sim_time=node3.get_sim_time_sec(),
            latest_amcl=node3.latest_amcl_record,
            latest_odom=node3.latest_odom_record,
            latest_scan=None,
            nav2_lifecycle_state="ACTIVE",
            current_goal_status="IDLE",
        )
        log3(f"Test 3c (Missing Scan Degraded): status={missing_scan_obs['status']}, error_type={missing_scan_obs.get('error_type')}")

        # 3d. Wall-clock Timeout Resilience
        t_w_start = time.monotonic()
        # Query observe with non-finite sim time or missing required odom
        err_obs = node3.obs_interface.extract_observation(
            current_sim_time=node3.get_sim_time_sec(),
            latest_amcl=node3.latest_amcl_record,
            latest_odom=None,  # Missing required odom
            latest_scan=node3.latest_scan_record,
        )
        t_w_elapsed = time.monotonic() - t_w_start
        log3(f"Test 3d (Missing Odom Structured Error): status={err_obs['status']}, error_type={err_obs.get('error_type')}, wall_time={t_w_elapsed:.4f}s")

        suite3_data = {
            "test_3a_normal": norm_obs,
            "test_3b_stale_scan_degraded": degraded_obs,
            "test_3c_missing_scan_degraded": missing_scan_obs,
            "test_3d_missing_odom_error": err_obs,
            "anomalies_verified": (
                norm_obs["status"] == "SUCCESS"
                and degraded_obs["status"] == "DEGRADED"
                and missing_scan_obs["status"] == "DEGRADED"
                and err_obs["status"] == "ERROR"
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
    # SUITE 4: 4-Episode Full Navigation & Cancel Regression Suite
    # =========================================================================
    regression_goals = [
        {"action_id": "reg_ep1_fwd", "goal": [-0.5, -0.5, 0.0], "is_cancel": False},
        {"action_id": "reg_ep2_rot", "goal": [0.5, -0.5, 1.57], "is_cancel": False},
        {"action_id": "reg_ep3_ret", "goal": [-1.8, -0.5, 3.14], "is_cancel": False},
        {"action_id": "reg_ep4_cancel", "goal": [0.5, 1.8, 0.0], "is_cancel": True},
    ]

    reg_episodes_summary = []

    for r_idx, r_spec in enumerate(regression_goals, start=1):
        ep_dir = run_dir / f"regression_episode_{r_idx}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        r_events = open(ep_dir / "events.log", "w", encoding="utf-8")

        def log_r(msg: str):
            line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}"
            print(line, flush=True)
            r_events.write(line + "\n")
            r_events.flush()

        log_r(f"=== Starting Regression Episode {r_idx} ({r_spec['action_id']}) ===")
        sim_proc_r, env_r = spawn_simulation(ep_dir)
        rclpy.init()

        try:
            node_r = P1bRunnerNode(f"reg_ep_{r_idx}", log_r)
            node_r.wait_for_sim_clock(min_sim_advance_sec=1.0)
            node_r.action_client.wait_for_server(timeout_sec=40.0)
            node_r.wait_for_nav2_active(wall_timeout_sec=35.0)
            node_r.wait_for_sensors(wall_timeout_sec=25.0)
            node_r.initialize_amcl_pose(x=-2.0, y=-0.5, yaw=0.0)

            context_r = EpisodeActionHistoryContext(max_retries=3, max_retries_per_state=1)
            dispatcher_r = ActionDispatcher(context=context_r, run_id=run_id, episode_id=f"reg_ep_{r_idx}")

            goal_handle_r = None
            def ros_send_reg(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
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

            dispatcher_r.ros_executor = ros_send_reg

            nav_action = {"action": "navigate", "action_id": r_spec["action_id"], "params": {"goal": r_spec["goal"], "frame_id": "map", "timeout_sec": 60.0}}
            node_r.is_tracking = True
            dispatch_res_r = dispatcher_r.dispatch(nav_action)

            get_result_fut_r = goal_handle_r.get_result_async()
            mv_confirmed = False
            cancel_acc = False

            if r_spec["is_cancel"]:
                t_w = time.monotonic()
                while time.monotonic() - t_w < 15.0:
                    rclpy.spin_once(node_r, timeout_sec=0.05)
                    if node_r.latest_odom_record and abs(node_r.latest_odom_record.get("linear_v", 0.0)) > 0.05:
                        mv_confirmed = True
                        break
                cancel_fut_r = goal_handle_r.cancel_goal_async()
                rclpy.spin_until_future_complete(node_r, cancel_fut_r, timeout_sec=6.0)
                cancel_acc = (cancel_fut_r.done() and cancel_fut_r.result() is not None and cancel_fut_r.result().return_code == 0)
                rclpy.spin_until_future_complete(node_r, get_result_fut_r, timeout_sec=8.0)
                status_name_r = "CANCELED"
            else:
                t_start = time.monotonic()
                while rclpy.ok() and not get_result_fut_r.done():
                    rclpy.spin_once(node_r, timeout_sec=0.05)
                    if time.monotonic() - t_start > 35.0:
                        goal_handle_r.cancel_goal_async()
                        break
                term_code = get_result_fut_r.result().status if get_result_fut_r.done() and get_result_fut_r.result() is not None else 4
                status_name_r = "SUCCEEDED" if term_code == GoalStatus.STATUS_SUCCEEDED else f"STATUS_{term_code}"

            dispatcher_r.record_terminal_status(r_spec["action_id"], terminal_status=status_name_r)
            node_r.wait_for_passive_settling(max_sim_sec=2.5)
            stability_samples_r, watchdog_r = node_r.record_stability_window(duration_sim_sec=2.5)
            node_r.is_tracking = False

            if not r_spec["is_cancel"]:
                eval_r = evaluate_navigation_episode(
                    target_goal=r_spec["goal"],
                    nav2_status=status_name_r,
                    final_gt=node_r.latest_gt_record,
                    final_amcl=node_r.latest_amcl_record,
                    stability_samples=stability_samples_r,
                    thresholds=thresholds,
                    watchdog_triggered=watchdog_r,
                )
            else:
                eval_r = evaluate_cancellation_episode(
                    nav2_status=status_name_r,
                    movement_confirmed_before_cancel=mv_confirmed,
                    cancel_request_accepted=cancel_acc,
                    stability_samples=stability_samples_r,
                    thresholds=thresholds,
                    watchdog_triggered=watchdog_r,
                )

            loc_audit_r = audit_localization_discrepancy(
                amcl_samples=node_r.episode_amcl_samples,
                gt_samples=node_r.episode_gt_samples,
                thresholds=thresholds,
            )

            ep_summary = {
                "episode_index": r_idx,
                "action_id": r_spec["action_id"],
                "goal": r_spec["goal"],
                "is_cancel_test": r_spec["is_cancel"],
                "nav2_action_status": status_name_r,
                "goal_uuid": dispatcher_r.goal_uuid_mapping.get(r_spec["action_id"]),
                "evaluation": eval_r,
                "localization_audit": {
                    "time_aligned_samples_count": loc_audit_r["time_aligned_samples_count"],
                    "mean_localization_discrepancy_m": loc_audit_r["mean_localization_discrepancy_m"],
                },
                "initial_states": {"gt": node_r.episode_gt_samples[0] if node_r.episode_gt_samples else None},
                "final_states": {"gt": node_r.latest_gt_record, "amcl": node_r.latest_amcl_record},
            }

            with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
                json.dump(ep_summary, f, indent=2)
            with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                json.dump(stability_samples_r, f, indent=2)
            with open(ep_dir / "trajectory.json", "w", encoding="utf-8") as f:
                json.dump({"gt": node_r.episode_gt_samples, "amcl": node_r.episode_amcl_samples, "odom": node_r.episode_odom_samples}, f, indent=2)

            reg_episodes_summary.append(ep_summary)
            log_r(f"Regression Episode {r_idx} Complete: Status={status_name_r} | Strict Passed={eval_r.get('strict_physical_arrival_and_stable') or eval_r.get('cancel_stop_verified')}")

        finally:
            rclpy.shutdown()
            kill_process_group(os.getpgid(sim_proc_r.pid))
            r_events.close()

    suite_results["suite_4_regression_episodes"] = reg_episodes_summary

    # Check overall suite status
    all_passed = (
        suite_results["suite_1_observe_nav_observe"].get("chain_verified", False)
        and suite_results["suite_2_cancel_retry_observe"].get("chain_verified", False)
        and suite_results["suite_3_observe_anomalies"].get("anomalies_verified", False)
        and len(reg_episodes_summary) == 4
        and all((ep["evaluation"].get("strict_physical_arrival_and_stable") or ep["evaluation"].get("cancel_stop_verified")) for ep in reg_episodes_summary)
    )
    suite_results["overall_status"] = "PASSED" if all_passed else "FAILED"

    # Save summary.json
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(suite_results, f, indent=2)

    # Compute checksums
    checksum_lines = []
    for root, _, files in os.walk(run_dir):
        for fname in sorted(files):
            if fname == "checksums.sha256":
                continue
            fpath = Path(root) / fname
            h = hashlib.sha256(fpath.read_bytes()).hexdigest()
            rel_path = fpath.relative_to(run_dir)
            checksum_lines.append(f"{h}  {rel_path}")

    with open(run_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(checksum_lines)) + "\n")

    print(f"=== P1b Suite Complete. Results in {run_dir} (Status: {suite_results['overall_status']}) ===")
    return suite_results


if __name__ == "__main__":
    out_dir = Path("reports/evidence/p1b")
    if Path("/workspace").exists():
        out_dir = Path("/workspace/reports/evidence/p1b")
    run_p1b_complete_suite(out_dir)
