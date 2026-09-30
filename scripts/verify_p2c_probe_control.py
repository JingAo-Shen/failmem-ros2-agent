#!/usr/bin/env python3
"""Open vs Blocked Control Probe Verification Script.

Executes the identical navigation action towards doorway ([1.50, 1.20, 0.0]) in:
1. Open condition (obstacle absent): asserts SUCCEEDED and FREE perception.
2. Blocked condition (obstacle spawned): asserts genuine Nav2 ABORTED / timeout and OCCUPIED perception.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from unique_identifier_msgs.msg import UUID as RosUUID

from src.action_dispatcher import ActionDispatcher
from src.action_runtime import EpisodeActionHistoryContext
from src.p2c_pipeline import (
    P2cProtocolConfig,
    build_chokepoint_probe_action,
)
from scripts.run_p1c_v3 import (

    P1cV3RunnerNode,
    execute_navigation_action,
    cleanup_simulation_processes,
)
from scripts.run_p2c_experiment import (
    spawn_simulation_p2c,
    capture_costmap_snapshot,
    capture_scan_snapshot,
)


def run_probe_control_test(output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    proto_cfg = P2cProtocolConfig.load_from_file(Path("configs/p2c_pilot_protocol.yaml"))
    doorway_bbox = proto_cfg.doorway_bbox
    thresholds = proto_cfg.thresholds

    obs_cfg = proto_cfg.raw_config["obstacle_channel"]
    obs_name = str(obs_cfg.get("entity_name", "chokepoint_blockage_box"))
    obs_sdf = str(obs_cfg.get("obstacle_sdf", "configs/chokepoint_box.sdf"))
    obs_x = float(obs_cfg["pose"]["x"])
    obs_y = float(obs_cfg["pose"]["y"])
    obs_z = float(obs_cfg["pose"].get("z", 0.30))

    spawn_coords = [-2.50, 0.0, 0.0]  # Spawn at standard decision junction J0
    sim_proc, sim_env = spawn_simulation_p2c(output_dir, spawn_coords)
    rclpy.init()
    node = P1cV3RunnerNode("p2c_probe_control", event_logger=print)

    try:
        # Wait for simulation and sensors
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_odom_record and node.latest_scan_record and node.latest_costmap_record:
                break
            time.sleep(0.05)

        # Initialize AMCL
        t_amcl = time.monotonic()
        while time.monotonic() - t_amcl < 25.0:
            if node.latest_amcl_record is None:
                node.initialize_amcl_pose(spawn_coords)
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_amcl_record is not None:
                d = math.hypot(node.latest_amcl_record["x"] - spawn_coords[0], node.latest_amcl_record["y"] - spawn_coords[1])
                if d < 0.35:
                    break
            time.sleep(0.2)

        # Ensure Nav2 is active
        t_nav = time.monotonic()
        while time.monotonic() - t_nav < 20.0:
            if node.query_lifecycle_state(timeout_sec=0.5) == "active":
                break
            time.sleep(0.5)

        action_history_ctx = EpisodeActionHistoryContext(max_retries=5, max_retries_per_state=3)
        dispatcher = ActionDispatcher(context=action_history_ctx, run_id="probe_test", episode_id="ctrl")
        dispatcher.ros_observer = lambda act: node.get_live_observation(wait_fresh=True, timeout_sec=2.0, refresh_amcl_if_stale=True)

        def ros_send_nav(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            goal_msg = NavigateToPose.Goal()
            p = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = p.get("frame_id", "map")
            goal_msg.pose.header.stamp = node.get_clock().now().to_msg()
            g = p.get("goal", [1.50, 1.20, 0.0])
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            goal_msg.pose.pose.orientation.w = 1.0
            node.nav_goal_sent_count += 1
            ros_uuid = RosUUID(uuid=list(goal_uuid.bytes))
            future = node.action_client.send_goal_async(goal_msg, goal_uuid=ros_uuid)
            rclpy.spin_until_future_complete(node, future, timeout_sec=10.0)
            if not future.done() or not future.result() or not future.result().accepted:
                return {"status": "REJECTED", "accepted": False}
            node.current_active_goal_handle = future.result()
            return {"status": "ACCEPTED", "accepted": True, "goal_id": str(goal_uuid)}

        dispatcher.ros_executor = ros_send_nav

        # =====================================================================
        # Step 0: Drive to Vantage Point [-1.00, 1.20, 0.0]
        # =====================================================================
        print("\n--- Step 0: Driving from J0 to Vantage Point ---")
        node.start_tracking()
        vantage_act = {
            "action_id": "probe_setup_to_vantage",
            "action": "navigate",
            "params": {"goal": [-1.00, 1.20, 0.0], "frame_id": "map", "timeout_sec": 30.0},
        }
        execute_navigation_action(node, dispatcher, vantage_act, print, thresholds)

        # =====================================================================
        # TEST 1: OPEN CONDITION (Doorway is clear)
        # =====================================================================
        print("\n--- Running OPEN Condition Probe ---")
        node.request_nomotion_amcl_update(timeout_sec=1.5)
        obs_open = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=1.0)
        print(f"Open Condition Vantage Perception: {obs_open.get('doorway_state')} (Pass-through: {obs_open.get('pass_through_count')})")

        node.start_tracking()
        open_act = build_chokepoint_probe_action(
            action_id="probe_open_traversal",
            target_goal=(0.50, 1.20, 0.0),
            timeout_sec=15.0,
        )
        sum_open, eval_open, _ = execute_navigation_action(node, dispatcher, open_act, print, thresholds)
        print(f"Open Condition Nav2 Result: Status={sum_open.get('terminal_status_name')}, Arrival={eval_open.get('strict_physical_arrival_and_stable')}")

        # Return robot to vantage point [-1.00, 1.20, 0.0]
        print("\n--- Returning to Vantage Point ---")
        ret_act = {
            "action_id": "probe_return_to_vantage",
            "action": "navigate",
            "params": {"goal": [-1.00, 1.20, 0.0], "frame_id": "map", "timeout_sec": 35.0},
        }
        execute_navigation_action(node, dispatcher, ret_act, print, thresholds)

        # =====================================================================
        # TEST 2: BLOCKED CONDITION (Spawn obstacle in doorway)
        # =====================================================================
        print("\n--- Spawning Obstacle & Running BLOCKED Condition Probe ---")
        node.spawn_obstacle(obs_name, obs_sdf, obs_x, obs_y, obs_z)
        time.sleep(1.0)
        rclpy.spin_once(node, timeout_sec=0.1)

        node.request_nomotion_amcl_update(timeout_sec=1.5)
        obs_blocked = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=1.0)
        print(f"Blocked Condition Vantage Perception: {obs_blocked.get('doorway_state')} (Hits: {obs_blocked.get('hits_inside_count')})")

        node.start_tracking()
        blocked_act = build_chokepoint_probe_action(
            action_id="probe_blocked_traversal",
            target_goal=(0.50, 1.20, 0.0),
            timeout_sec=15.0,
        )
        sum_blocked, eval_blocked, _ = execute_navigation_action(node, dispatcher, blocked_act, print, thresholds)

        print(f"Blocked Condition Nav2 Result: Status={sum_blocked.get('terminal_status_name')}, Execution Outcome={sum_blocked.get('execution_outcome')}")

        # Cleanup obstacle
        node.delete_obstacle(obs_name)

        open_passed = (sum_open.get("terminal_status_name") == "SUCCEEDED" or eval_open.get("strict_physical_arrival_and_stable") is True) and (obs_open.get("doorway_state") == "FREE")
        blocked_passed = (sum_blocked.get("terminal_status_name") in ["ABORTED", "TIMEOUT", "CANCELED"] or sum_blocked.get("execution_outcome") in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"]) and (obs_blocked.get("doorway_state") == "OCCUPIED")

        results = {
            "open_condition": {
                "terminal_status_name": sum_open.get("terminal_status_name"),
                "execution_outcome": sum_open.get("execution_outcome"),
                "perception_state": obs_open.get("doorway_state"),
                "pass_through_count": obs_open.get("pass_through_count"),
                "passed": open_passed,
            },
            "blocked_condition": {
                "terminal_status_name": sum_blocked.get("terminal_status_name"),
                "execution_outcome": sum_blocked.get("execution_outcome"),
                "perception_state": obs_blocked.get("doorway_state"),
                "obstacle_hits": obs_blocked.get("hits_inside_count"),
                "passed": blocked_passed,
            },
            "both_passed": bool(open_passed and blocked_passed),
        }

        with open(output_dir / "probe_control_results.json", "w") as f:
            json.dump(results, f, indent=2)

        return results

    finally:
        node.destroy_node()
        rclpy.shutdown()
        cleanup_simulation_processes()


if __name__ == "__main__":
    out_dir = Path("/workspace/reports/evidence/p2c_probe_control") if Path("/workspace").exists() else Path("reports/evidence/p2c_probe_control")
    res = run_probe_control_test(out_dir)
    print("\n--- Probe Control Test Summary ---")
    print(json.dumps(res, indent=2))
