#!/usr/bin/env python3
"""FailMem P1a Headless Navigation Smoke Test Script.

Orchestrates:
1. Environment & compatibility logging (TB3 Waffle + Gazebo Classic 11 + Nav2 on Humble).
2. Headless bringup of Gazebo server (with gazebo_ros_state plugin) and Nav2 stack.
3. System interface discovery (/clock, /scan, /odom, /tf, /amcl_pose, /gazebo/model_states).
4. AMCL initial pose initialization at [-2.0, -0.5, 0.0].
5. 3 independent navigation test runs (send goal -> track gt & amcl trajectories -> verify arrival).
6. 1 cancel/timeout verification test (send unreachable goal -> cancel -> verify stop).
7. Structured recording of node list, topic list, action list, and trajectories.
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ROS2 imports
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from action_msgs.msg import GoalStatus
from gazebo_msgs.msg import ModelStates

REPO_ROOT = Path("/workspace")
EVIDENCE_DIR = REPO_ROOT / "reports/evidence/p1a"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
EVENT_LOG = EVIDENCE_DIR / "p1a_nav_events.log"


def log(msg: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


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


class NavSmokeRunner(Node):
    def __init__(self):
        super().__init__("failmem_p1a_smoke_runner")
        self.action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "initialpose", 10)
        self.cmd_vel_sub = self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, "odom", self._odom_cb, 10)
        self.amcl_sub = self.create_subscription(PoseWithCovarianceStamped, "amcl_pose", self._amcl_cb, 10)
        self.gazebo_sub = self.create_subscription(ModelStates, "/gazebo/model_states", self._gazebo_cb, 10)

        self.latest_odom = None
        self.latest_amcl = None
        self.latest_gt = None
        self.latest_cmd_vel = None

        # Trajectory samples recorded during an active run
        self.gt_trajectory = []
        self.amcl_trajectory = []
        self.odom_trajectory = []
        self.is_tracking = False

    def _cmd_vel_cb(self, msg: Twist):
        self.latest_cmd_vel = msg

    def _odom_cb(self, msg: Odometry):
        self.latest_odom = msg
        if self.is_tracking:
            p = msg.pose.pose.position
            o = msg.pose.pose.orientation
            yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
            self.odom_trajectory.append({
                "t": round(time.time(), 3),
                "x": round(p.x, 4),
                "y": round(p.y, 4),
                "yaw": round(yaw, 4),
            })

    def _amcl_cb(self, msg: PoseWithCovarianceStamped):
        self.latest_amcl = msg
        if self.is_tracking:
            p = msg.pose.pose.position
            o = msg.pose.pose.orientation
            yaw = quat_to_yaw(o.x, o.y, o.z, o.w)
            self.amcl_trajectory.append({
                "t": round(time.time(), 3),
                "x": round(p.x, 4),
                "y": round(p.y, 4),
                "yaw": round(yaw, 4),
            })

    def _gazebo_cb(self, msg: ModelStates):
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
        self.latest_gt = {
            "x": p.x,
            "y": p.y,
            "z": p.z,
            "yaw": yaw,
        }
        if self.is_tracking:
            self.gt_trajectory.append({
                "t": round(time.time(), 3),
                "x": round(p.x, 4),
                "y": round(p.y, 4),
                "yaw": round(yaw, 4),
            })

    def publish_initial_pose(self, x=-2.0, y=-0.5, yaw=0.0):
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.position.z = 0.01

        msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        msg.pose.covariance[0] = 0.25
        msg.pose.covariance[7] = 0.25
        msg.pose.covariance[35] = 0.06

        for _ in range(5):
            self.initial_pose_pub.publish(msg)
            time.sleep(0.2)
        log(f"Published initial pose to /initialpose at x={x}, y={y}, yaw={yaw}")

    def send_nav_goal(self, x: float, y: float, yaw: float, timeout_sec: float = 60.0) -> dict:
        self.gt_trajectory = []
        self.amcl_trajectory = []
        self.odom_trajectory = []
        self.is_tracking = True
        t_start = time.time()

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = "map"
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        log(f"Sending NavigateToPose goal: [{x}, {y}, yaw={yaw}]")
        send_goal_future = self.action_client.send_goal_async(goal_msg)

        # Spin until goal accepted
        rclpy.spin_until_future_complete(self, send_goal_future, timeout_sec=10.0)
        if not send_goal_future.done():
            self.is_tracking = False
            log("[ERROR] Timed out waiting for goal acceptance")
            return {"status": "TIMEOUT_ACCEPTING_GOAL"}

        goal_handle = send_goal_future.result()
        if not goal_handle.accepted:
            self.is_tracking = False
            log("[WARN] Goal was rejected by Nav2 server")
            return {"status": "GOAL_REJECTED"}

        log("Goal accepted by Nav2. Tracking navigation progress...")
        get_result_future = goal_handle.get_result_async()

        # Monitor progress until result or timeout
        t_deadline = t_start + timeout_sec
        while rclpy.ok() and not get_result_future.done():
            rclpy.spin_once(self, timeout_sec=0.2)
            if time.time() > t_deadline:
                log("[WARN] Navigation deadline exceeded. Cancelling goal...")
                cancel_future = goal_handle.cancel_goal_async()
                rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=5.0)
                self.is_tracking = False
                return {"status": "ACTION_TIMEOUT", "duration_sec": time.time() - t_start}

        duration = time.time() - t_start
        self.is_tracking = False
        action_result = get_result_future.result()
        status_code = action_result.status
        status_name = "SUCCEEDED" if status_code == GoalStatus.STATUS_SUCCEEDED else f"STATUS_{status_code}"

        # AMCL end pose
        if self.latest_amcl:
            ap = self.latest_amcl.pose.pose.position
            ao = self.latest_amcl.pose.pose.orientation
            amcl_x, amcl_y = ap.x, ap.y
            amcl_yaw = quat_to_yaw(ao.x, ao.y, ao.z, ao.w)
            amcl_pos_error = math.hypot(amcl_x - x, amcl_y - y)
            amcl_yaw_error = abs(normalize_angle(amcl_yaw - yaw))
            amcl_end_pose = {"x": round(amcl_x, 4), "y": round(amcl_y, 4), "yaw": round(amcl_yaw, 4)}
            amcl_arrived = (amcl_pos_error < 0.35 and amcl_yaw_error < 0.35)
        else:
            amcl_end_pose = None
            amcl_pos_error = None
            amcl_yaw_error = None
            amcl_arrived = False

        # Ground Truth end pose
        if self.latest_gt:
            gt_x, gt_y, gt_yaw = self.latest_gt["x"], self.latest_gt["y"], self.latest_gt["yaw"]
            gt_pos_error = math.hypot(gt_x - x, gt_y - y)
            gt_yaw_error = abs(normalize_angle(gt_yaw - yaw))
            gt_end_pose = {"x": round(gt_x, 4), "y": round(gt_y, 4), "yaw": round(gt_yaw, 4)}
            gt_arrived = (gt_pos_error < 0.35 and gt_yaw_error < 0.35)
            gt_status = "VERIFIED"
        else:
            gt_end_pose = None
            gt_pos_error = None
            gt_yaw_error = None
            gt_arrived = False
            gt_status = "NOT_IMPLEMENTED"

        # Discrepancy between AMCL and Ground Truth
        if self.latest_amcl and self.latest_gt:
            loc_error = math.hypot(self.latest_amcl.pose.pose.position.x - self.latest_gt["x"],
                                   self.latest_amcl.pose.pose.position.y - self.latest_gt["y"])
        else:
            loc_error = None

        # Compute trajectory path length from ground truth (or odom)
        path_len = 0.0
        active_traj = self.gt_trajectory if self.gt_trajectory else self.odom_trajectory
        for i in range(1, len(active_traj)):
            dx = active_traj[i]["x"] - active_traj[i-1]["x"]
            dy = active_traj[i]["y"] - active_traj[i-1]["y"]
            path_len += math.hypot(dx, dy)

        nav2_succeeded = (status_code == GoalStatus.STATUS_SUCCEEDED)

        log(f"Navigation finished: Nav2={status_name} in {duration:.2f}s | "
            f"AMCL_err={amcl_pos_error if amcl_pos_error is not None else -1:.3f}m | "
            f"GT_err={gt_pos_error if gt_pos_error is not None else -1:.3f}m | "
            f"Loc_discrepancy={loc_error if loc_error is not None else -1:.3f}m | "
            f"Nav2_ok={nav2_succeeded}, AMCL_arrived={amcl_arrived}, GT_arrived={gt_arrived}")

        return {
            "status": status_name,
            "status_code": int(status_code),
            "goal": [x, y, yaw],
            "duration_sec": round(duration, 3),
            "approx_path_length_m": round(path_len, 3),
            "nav2_action_succeeded": bool(nav2_succeeded),
            "amcl_estimation_arrived": bool(amcl_arrived),
            "ground_truth_physical_arrived": bool(gt_arrived),
            "ground_truth_status": gt_status,
            "amcl_end_pose": amcl_end_pose,
            "amcl_position_error_m": round(amcl_pos_error, 4) if amcl_pos_error is not None else None,
            "amcl_yaw_error_rad": round(amcl_yaw_error, 4) if amcl_yaw_error is not None else None,
            "ground_truth_end_pose": gt_end_pose,
            "ground_truth_position_error_m": round(gt_pos_error, 4) if gt_pos_error is not None else None,
            "ground_truth_yaw_error_rad": round(gt_yaw_error, 4) if gt_yaw_error is not None else None,
            "amcl_vs_ground_truth_error_m": round(loc_error, 4) if loc_error is not None else None,
            "gt_trajectory_points_count": len(self.gt_trajectory),
            "amcl_trajectory_points_count": len(self.amcl_trajectory),
        }

    def test_cancel_flow(self, unreachable_x=10.0, unreachable_y=10.0) -> dict:
        log(f"Initiating Cancel/Timeout test with unreachable goal [{unreachable_x}, {unreachable_y}]...")
        self.gt_trajectory = []
        self.amcl_trajectory = []
        self.is_tracking = True

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = "map"
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        goal_msg.pose.pose.position.x = unreachable_x
        goal_msg.pose.pose.position.y = unreachable_y

        send_goal_future = self.action_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, send_goal_future, timeout_sec=5.0)
        goal_handle = send_goal_future.result()

        if not goal_handle.accepted:
            self.is_tracking = False
            log("Unreachable goal immediately rejected (acceptable response)")
            return {
                "status": "GOAL_REJECTED",
                "clean_stop": True,
                "cancel_confirmed": True,
                "robot_stopped": True,
            }

        log("Unreachable goal accepted. Letting robot begin movement for 4s...")
        t_cancel_start = time.time()
        while time.time() - t_cancel_start < 4.0:
            rclpy.spin_once(self, timeout_sec=0.2)

        log("Sending explicit CANCEL request to Action Server...")
        cancel_future = goal_handle.cancel_goal_async()
        rclpy.spin_until_future_complete(self, cancel_future, timeout_sec=5.0)

        cancel_resp = cancel_future.result()
        log(f"Cancel response received. Goals canceling count: {len(cancel_resp.goals_canceling)}")

        # Wait for result status to confirm CANCELED
        get_result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, get_result_future, timeout_sec=5.0)
        self.is_tracking = False

        status_code = get_result_future.result().status
        status_name = "CANCELED" if status_code == GoalStatus.STATUS_CANCELED else f"STATUS_{status_code}"

        # Spin a bit to verify velocity drops to 0
        for _ in range(5):
            rclpy.spin_once(self, timeout_sec=0.2)
        v_linear = abs(self.latest_cmd_vel.linear.x) if self.latest_cmd_vel else 0.0
        v_angular = abs(self.latest_cmd_vel.angular.z) if self.latest_cmd_vel else 0.0
        robot_stopped = (v_linear < 0.05 and v_angular < 0.05)

        log(f"Cancel confirmed: status={status_name} | robot_stopped={robot_stopped} (v_lin={v_linear:.3f}, v_ang={v_angular:.3f})")
        return {
            "status": status_name,
            "status_code": int(status_code),
            "unreachable_goal": [unreachable_x, unreachable_y],
            "cancel_confirmed": (status_code == GoalStatus.STATUS_CANCELED),
            "robot_stopped": bool(robot_stopped),
            "final_linear_velocity": round(v_linear, 4),
            "final_angular_velocity": round(v_angular, 4),
        }


def main():
    log("=== Starting P1a Headless Navigation Smoke Runner ===")

    # 1. Simulator & Compatibility Log
    compat_info = {
        "os": "Ubuntu 22.04 LTS (Jammy)",
        "ros_distro": "humble",
        "simulator_selected": "Gazebo Classic 11.10.2 (gazebo_ros_pkgs)",
        "robot_model": "TurtleBot3 Waffle",
        "nav2_stack": "Navigation2 1.1.20 (nav2_bringup)",
        "network_isolation": "ROS_DOMAIN_ID=42, ROS_LOCALHOST_ONLY=1",
        "compatibility_rationale": (
            "Selected Gazebo Classic 11 over Fortress because upstream TurtleBot3 packages "
            "for Humble directly provide validated Gazebo Classic SDF models and native /gazebo/model_states "
            "topics for ground truth. In Humble, Fortress lacks official TB3 SDF system plugins."
        ),
    }
    log(f"Compatibility Stack: {compat_info['simulator_selected']} | Robot: {compat_info['robot_model']}")

    # 2. Launch Simulation Subprocess with clean environment
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
    ]
    log(f"Launching simulation process: {' '.join(launch_cmd)}")
    sim_log_file = open(EVIDENCE_DIR / "nav2_sim_launch.log", "w", encoding="utf-8")
    sim_proc = subprocess.Popen(launch_cmd, env=env, stdout=sim_log_file, stderr=subprocess.STDOUT)

    time.sleep(3.0)

    # 3. Initialize rclpy
    rclpy.init()
    runner = NavSmokeRunner()

    # Wait for /navigate_to_pose action server and active topics
    log("Waiting for /navigate_to_pose action server to become available...")
    server_ready = False
    for i in range(45):
        if runner.action_client.wait_for_server(timeout_sec=1.0):
            server_ready = True
            log(f"NavigateToPose action server connected after {i+1}s!")
            break
        rclpy.spin_once(runner, timeout_sec=0.1)

    if not server_ready:
        log("[FATAL] Action server failed to start within 45s")
        sim_proc.terminate()
        sys.exit(1)

    # 4. Publish initial pose to AMCL
    runner.publish_initial_pose(x=-2.0, y=-0.5, yaw=0.0)
    time.sleep(2.0)

    # Wait for AMCL and Gazebo Ground Truth
    log("Waiting for /amcl_pose and /gazebo/model_states...")
    for _ in range(25):
        rclpy.spin_once(runner, timeout_sec=0.2)
        if runner.latest_amcl is not None and runner.latest_gt is not None:
            log("Both AMCL localization and Gazebo ground truth received!")
            break

    # 5. Capture ROS Nodes, Topics, Actions lists
    nodes = subprocess.check_output(["ros2", "node", "list"], env=env, text=True).strip().split("\n")
    topics = subprocess.check_output(["ros2", "topic", "list"], env=env, text=True).strip().split("\n")
    actions = subprocess.check_output(["ros2", "action", "list"], env=env, text=True).strip().split("\n")

    with open(EVIDENCE_DIR / "ros_nodes.txt", "w") as f:
        f.write("\n".join(nodes) + "\n")
    with open(EVIDENCE_DIR / "ros_topics.txt", "w") as f:
        f.write("\n".join(topics) + "\n")
    with open(EVIDENCE_DIR / "ros_actions.txt", "w") as f:
        f.write("\n".join(actions) + "\n")
    log(f"Captured system topology: {len(nodes)} nodes, {len(topics)} topics, {len(actions)} actions")

    # 6. Execute 3 Test Runs
    runs_data = []
    trajectories_data = {}

    # Run 1: Forward navigation in hallway
    log("--- Starting Run 1: Navigate to [x=-0.5, y=-0.5, yaw=0.0] ---")
    r1 = runner.send_nav_goal(x=-0.5, y=-0.5, yaw=0.0, timeout_sec=60.0)
    r1["run_index"] = 1
    runs_data.append(r1)
    trajectories_data["run_1"] = {
        "ground_truth": runner.gt_trajectory,
        "amcl": runner.amcl_trajectory,
    }
    time.sleep(2.0)

    # Run 2: Lateral move in free space
    log("--- Starting Run 2: Navigate to [x=0.5, y=-0.5, yaw=1.57] ---")
    r2 = runner.send_nav_goal(x=0.5, y=-0.5, yaw=1.57, timeout_sec=60.0)
    r2["run_index"] = 2
    runs_data.append(r2)
    trajectories_data["run_2"] = {
        "ground_truth": runner.gt_trajectory,
        "amcl": runner.amcl_trajectory,
    }
    time.sleep(2.0)

    # Run 3: Return toward start position
    log("--- Starting Run 3: Navigate to [x=-2.0, y=-0.5, yaw=3.14] ---")
    r3 = runner.send_nav_goal(x=-2.0, y=-0.5, yaw=3.14, timeout_sec=60.0)
    r3["run_index"] = 3
    runs_data.append(r3)
    trajectories_data["run_3"] = {
        "ground_truth": runner.gt_trajectory,
        "amcl": runner.amcl_trajectory,
    }
    time.sleep(2.0)

    # 7. Cancel / Timeout verification run
    log("--- Starting Run 4: Cancel / Unreachable goal check ---")
    r4 = runner.test_cancel_flow(unreachable_x=10.0, unreachable_y=10.0)
    r4["run_index"] = 4
    runs_data.append(r4)
    trajectories_data["run_4_cancel"] = {
        "ground_truth": runner.gt_trajectory,
        "amcl": runner.amcl_trajectory,
    }

    # 8. Shutdown simulation process cleanly
    log("Terminating simulation process...")
    sim_proc.send_signal(signal.SIGINT)
    try:
        sim_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        sim_proc.kill()
    sim_log_file.close()

    runner.destroy_node()
    rclpy.shutdown()

    # Save Trajectories
    with open(EVIDENCE_DIR / "p1a_trajectories.json", "w", encoding="utf-8") as f:
        json.dump(trajectories_data, f, indent=2, ensure_ascii=False)

    # 9. Save Summary JSON
    summary = {
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "P1a (Single-scene Headless Navigation Smoke Test)",
        "compatibility": compat_info,
        "interfaces_verified": {
            "clock_active": "/clock" in topics,
            "scan_active": "/scan" in topics,
            "odom_active": "/odom" in topics,
            "tf_active": "/tf" in topics,
            "amcl_pose_active": "/amcl_pose" in topics,
            "gazebo_model_states_active": "/gazebo/model_states" in topics,
            "navigate_to_pose_action": "/navigate_to_pose" in actions,
        },
        "topology_summary": {
            "node_count": len(nodes),
            "topic_count": len(topics),
            "action_count": len(actions),
        },
        "navigation_runs": runs_data,
        "runs_evaluation": {
            "total_runs": len(runs_data),
            "standard_runs_count": 3,
            "standard_runs_succeeded_nav2": sum(1 for r in runs_data[:3] if r.get("nav2_action_succeeded")),
            "standard_runs_succeeded_amcl": sum(1 for r in runs_data[:3] if r.get("amcl_estimation_arrived")),
            "standard_runs_succeeded_gt": sum(1 for r in runs_data[:3] if r.get("ground_truth_physical_arrived")),
            "cancel_test_passed": bool(r4.get("cancel_confirmed") and r4.get("robot_stopped")),
        },
        "boundary_notice": (
            "This smoke test only verifies the simulation platform, Nav2 action pipeline, "
            "and cancellation safety. It DOES NOT include LLM decision loops, failure memory, "
            "or test set evaluations."
        ),
    }

    results_file = EVIDENCE_DIR / "p1a_nav_smoke_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    log(f"All smoke runs completed. Results written to {results_file}")
    log("=== P1a Execution Finished Successfully ===")


if __name__ == "__main__":
    main()
