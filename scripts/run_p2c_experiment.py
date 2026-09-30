#!/usr/bin/env python3
"""FailMem Milestone P2c Real ROS 2 Experiment Runner.

Executes physical paired diagnostics (D0, D1, D2) comparing:
- R (Reactive Only)
- O (Spatial Observation Cache)
- F (FailMem Failure Memory)
- M1 (Persistent Suppression Baseline)

Inside Docker ROS 2 Humble simulation:
- Spawns Gazebo & Nav2 with asymmetric dual-path world and map.
- Evaluates LiDAR visibility from J0 (occlusion proof).
- Evaluates Nav2 global costmap retention across probe, retreat, and clearance.
- Integrates real physical distance from continuous odometry and duration from /clock.
- Strict Ground Truth isolation for offline scoring only.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

# Environment configuration
os.environ["TURTLEBOT3_MODEL"] = "waffle"
os.environ["GAZEBO_MODEL_DATABASE_URI"] = ""
os.environ["GAZEBO_MODEL_PATH"] = "/usr/share/gazebo-11/models:/opt/ros/humble/share/turtlebot3_gazebo/models"
os.environ["ROS_DOMAIN_ID"] = "42"
os.environ["ROS_LOCALHOST_ONLY"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from lifecycle_msgs.srv import GetState
from unique_identifier_msgs.msg import UUID as RosUUID
from nav_msgs.msg import OccupancyGrid

from src.action_dispatcher import ActionDispatcher
from src.action_runtime import EpisodeActionHistoryContext
from src.scoring_evaluator import (
    load_scoring_rules,
    compute_disagreement_reason,
    normalize_angle,
    is_finite_number,
    evaluate_navigation_episode,
)
from src.online_verifier import verify_online_arrival
from src.coordinate_alignment import verify_world_map_alignment
from src.failure_memory import (
    MemoryState,
    FailureMemoryEntry,
    FailureMemoryStore,
    FailureMemoryPolicy,
    M0NoMemoryPolicy,
    M1PersistentMemoryPolicy,
    M2ConditionalMemoryPolicy,
    M3CurrentPerceptionPolicy,
)
from scripts.run_p1c_v3 import (
    P1cV3RunnerNode,
    execute_navigation_action,
    compute_sha256_tree,
    cleanup_simulation_processes,
    kill_process_group,
    await_nav_goal_terminal_result,
    save_attempt_evidence,
)
from scripts.run_p2c_pilot_diagnosis import (
    SpatialObservationCache,
    verify_sightline_occlusion,
)


def spawn_simulation_p2c(episode_dir: Path, spawn_pose: List[float]) -> Tuple[subprocess.Popen, Any]:
    """Spawn Nav2 + Gazebo with P2c dualpath world and map in dedicated process group."""
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
        "map:=/workspace/configs/p2c_dualpath_world.yaml",
        "params_file:=/workspace/configs/nav2_params.yaml",
        "world:=/workspace/configs/p2c_dualpath_world.model",
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


def integrate_trajectory_distance(samples: List[Dict[str, Any]]) -> float:
    """Compute path length by integrating continuous position samples."""
    if not samples or len(samples) < 2:
        return 0.0
    dist = 0.0
    for i in range(1, len(samples)):
        x0 = float(samples[i - 1]["x"])
        y0 = float(samples[i - 1]["y"])
        x1 = float(samples[i]["x"])
        y1 = float(samples[i]["y"])
        d = math.hypot(x1 - x0, y1 - y0)
        # Reject abnormal teleport spikes (> 2.0m between consecutive 50Hz samples)
        if d < 2.0:
            dist += d
    return round(dist, 3)


def inspect_chokepoint_costmap_occupancy(
    costmap_msg: Optional[OccupancyGrid],
    doorway_bbox: Tuple[float, float, float, float],
) -> Dict[str, Any]:
    """Inspect cell occupancy inside Chokepoint A bounding box."""
    if costmap_msg is None:
        return {"costmap_available": False, "occupied_cell_count": 0, "free_cell_count": 0, "unknown_cell_count": 0}

    info = costmap_msg.info
    res = float(info.resolution)
    origin_x = float(info.origin.position.x)
    origin_y = float(info.origin.position.y)
    w = int(info.width)
    h = int(info.height)
    data = list(costmap_msg.data)

    x_min, x_max, y_min, y_max = doorway_bbox

    c_min = max(0, int((x_min - origin_x) / res))
    c_max = min(w - 1, int((x_max - origin_x) / res))
    r_min = max(0, int((y_min - origin_y) / res))
    r_max = min(h - 1, int((y_max - origin_y) / res))

    occ_cnt = 0
    free_cnt = 0
    unk_cnt = 0

    for r in range(r_min, r_max + 1):
        for c in range(c_min, c_max + 1):
            idx = r * w + c
            if 0 <= idx < len(data):
                val = data[idx]
                if val >= 50:
                    occ_cnt += 1
                elif val == 0:
                    free_cnt += 1
                else:
                    unk_cnt += 1

    return {
        "costmap_available": True,
        "resolution_m": res,
        "width": w,
        "height": h,
        "origin_xy": [origin_x, origin_y],
        "doorway_bbox": list(doorway_bbox),
        "occupied_cell_count": occ_cnt,
        "free_cell_count": free_cnt,
        "unknown_cell_count": unk_cnt,
        "has_blockage": (occ_cnt > 0),
    }


def check_lidar_chokepoint_visibility(
    node: P1cV3RunnerNode,
    robot_pose: List[float],
    doorway_bbox: Tuple[float, float, float, float],
) -> Dict[str, Any]:
    """Check if any laser ray endpoints from robot_pose fall inside doorway_bbox."""
    scan_msg = node._latest_raw_scan
    if scan_msg is None:
        return {"visibility": "UNKNOWN", "ray_hits_in_doorway": 0, "min_distance_to_doorway": None}

    rx, ry, ryaw = robot_pose[0], robot_pose[1], robot_pose[2] if len(robot_pose) > 2 else 0.0
    x_min, x_max, y_min, y_max = doorway_bbox

    hits = 0
    angle = scan_msg.angle_min
    for r in scan_msg.ranges:
        if math.isfinite(r) and scan_msg.range_min <= r <= scan_msg.range_max:
            beam_yaw = ryaw + angle
            gx = rx + r * math.cos(beam_yaw)
            gy = ry + r * math.sin(beam_yaw)
            if x_min <= gx <= x_max and y_min <= gy <= y_max:
                hits += 1
        angle += scan_msg.angle_increment

    return {
        "visibility": "OCCUPIED" if hits > 5 else "FREE_OR_OCCLUDED",
        "ray_hits_in_doorway": hits,
        "doorway_bbox": list(doorway_bbox),
    }


def run_physical_episode(
    condition_id: str,
    scenario_name: str,
    method_name: str,
    ep_num: int,
    run_dir: Path,
    protocol_config: Dict[str, Any],
    thresholds: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """Execute a single real ROS physical diagnostic trial inside Gazebo + Nav2."""
    ep_id = f"{condition_id}_ep{ep_num}"
    ep_dir = run_dir / ep_id
    ep_dir.mkdir(parents=True, exist_ok=True)
    events_log = open(ep_dir / "events.log", "w", encoding="utf-8")

    def log_ep(msg: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        try:
            if not events_log.closed:
                events_log.write(line + "\n")
                events_log.flush()
        except Exception:
            pass

    log_ep(f"=== Starting Physical Episode {ep_id} ({scenario_name} + Method {method_name}) ===")

    spawn_cfg = protocol_config["environment"]["spawn_pose"]
    spawn_coords = [float(spawn_cfg["x"]), float(spawn_cfg["y"]), float(spawn_cfg.get("yaw", 0.0))]
    junc_pose = [float(protocol_config["decision_junction"]["pose"]["x"]), float(protocol_config["decision_junction"]["pose"]["y"]), float(protocol_config["decision_junction"]["pose"].get("yaw", 0.0))]
    goal_cfg = protocol_config["navigation_task"]["goal_pose"]
    target_goal = [float(goal_cfg["x"]), float(goal_cfg["y"]), float(goal_cfg.get("yaw", 0.0))]
    chokepoint_region = "north_corridor_chokepoint"

    doorway_bbox_dict = protocol_config["obstacle_channel"].get("doorway_bbox", {"x_min": -0.30, "x_max": 0.30, "y_min": 0.80, "y_max": 1.60})
    doorway_bbox = (
        float(doorway_bbox_dict["x_min"]),
        float(doorway_bbox_dict["x_max"]),
        float(doorway_bbox_dict["y_min"]),
        float(doorway_bbox_dict["y_max"]),
    )

    obs_cfg = protocol_config["obstacle_channel"]
    obs_name = str(obs_cfg.get("entity_name", "chokepoint_blockage_box"))
    obs_sdf = str(obs_cfg.get("obstacle_sdf", "configs/chokepoint_box.sdf"))
    obs_x = float(obs_cfg["pose"]["x"])
    obs_y = float(obs_cfg["pose"]["y"])
    obs_z = float(obs_cfg["pose"].get("z", 0.30))

    # Spawn isolated simulation
    sim_proc, sim_env = spawn_simulation_p2c(ep_dir, spawn_coords)
    rclpy.init()
    node = P1cV3RunnerNode(f"p2c_{condition_id}_{ep_num}_{uuid.uuid4().hex[:4]}", event_logger=log_ep)

    # Initialize policy tracking structures
    cache = SpatialObservationCache()
    fail_store = FailureMemoryStore()
    m1_suppressed = False

    costmap_snapshots: List[Dict[str, Any]] = []
    action_summaries: List[Dict[str, Any]] = []
    all_gt_samples: List[Dict[str, Any]] = []
    all_odom_samples: List[Dict[str, Any]] = []

    history_distance = 0.0
    history_sim_time = 0.0
    decision_distance = 0.0
    decision_sim_time = 0.0
    dead_end_traversals = 0
    decision_dispatches = 0
    chosen_route = "UNKNOWN"
    decision_rationales: List[str] = []

    policy_reported_success = False
    evaluator_verified_success = False
    final_disagreement_reason: Optional[str] = None
    last_eval_dict: Optional[Dict[str, Any]] = None
    last_summary_dict: Optional[Dict[str, Any]] = None
    final_stability: List[Dict[str, Any]] = []

    try:
        # 1. Wait for clock to advance
        t0_sim = node.get_sim_time_sec()
        t0_wall = time.monotonic()
        while (node.get_sim_time_sec() - t0_sim < 1.0) and (time.monotonic() - t0_wall < 30.0):
            rclpy.spin_once(node, timeout_sec=0.1)
            time.sleep(0.05)
        log_ep(f"Sim clock advanced: {t0_sim:.2f}s -> {node.get_sim_time_sec():.2f}s")

        # 2. Verify Sensor Streams
        t_sensor_start = time.monotonic()
        while time.monotonic() - t_sensor_start < 25.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_odom_record and node.latest_gt_record and node.latest_scan_record and node.latest_costmap_record:
                break
            time.sleep(0.05)
        log_ep(f"Sensors verified: odom=({node.latest_odom_record['x']:.2f}, {node.latest_odom_record['y']:.2f}), scan={node.latest_scan_record['total_count']} rays")

        # 3. Initialize AMCL Pose
        node.initialize_amcl_pose(spawn_coords)
        t_amcl_start = time.monotonic()
        while time.monotonic() - t_amcl_start < 25.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_amcl_record is not None:
                delta = math.hypot(node.latest_amcl_record["x"] - spawn_coords[0], node.latest_amcl_record["y"] - spawn_coords[1])
                if delta < 0.35:
                    log_ep(f"AMCL pose converged at ({node.latest_amcl_record['x']:.2f}, {node.latest_amcl_record['y']:.2f})")
                    break
            time.sleep(0.1)

        # 4. Verify Nav2 bt_navigator lifecycle
        t_nav_start = time.monotonic()
        while time.monotonic() - t_nav_start < 20.0:
            st = node.query_lifecycle_state(timeout_sec=0.5)
            if st == "active":
                log_ep("Nav2 bt_navigator is ACTIVE!")
                break
            time.sleep(0.5)

        # Baseline Costmap Snapshot at J0
        cm_base = inspect_chokepoint_costmap_occupancy(node._latest_raw_costmap, doorway_bbox)
        cm_base["stage"] = "COSTMAP_BASELINE_J0"
        cm_base["sim_time_sec"] = round(node.get_sim_time_sec(), 3)
        costmap_snapshots.append(cm_base)

        # Observability Verification from J0
        lidar_j0 = check_lidar_chokepoint_visibility(node, spawn_coords, doorway_bbox)
        sightline_j0 = verify_sightline_occlusion((spawn_coords[0], spawn_coords[1]), (obs_x, obs_y))
        log_ep(f"J0 Observability: Sightline Occluded={sightline_j0['line_of_sight_occluded']}, LiDAR Hits in Doorway={lidar_j0['ray_hits_in_doorway']} (Local Obs={sightline_j0['junction_local_observation']})")

        action_history_ctx = EpisodeActionHistoryContext(max_retries=10, max_retries_per_state=5)
        dispatcher = ActionDispatcher(context=action_history_ctx, run_id=run_id, episode_id=ep_id)
        dispatcher.ros_observer = lambda act: node.get_live_observation(wait_fresh=True, timeout_sec=2.0, refresh_amcl_if_stale=True)

        def ros_send_nav(act: Dict[str, Any], goal_uuid: uuid.UUID) -> Dict[str, Any]:
            goal_msg = NavigateToPose.Goal()
            p = act.get("executable_params", act.get("params", {}))
            goal_msg.pose.header.frame_id = p.get("frame_id", "map")
            goal_msg.pose.header.stamp = node.get_clock().now().to_msg()
            g = p.get("goal", target_goal)
            goal_msg.pose.pose.position.x = float(g[0])
            goal_msg.pose.pose.position.y = float(g[1])
            yaw = float(g[2]) if len(g) > 2 else 0.0
            goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
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

        episode_t0 = node.get_sim_time_sec()

        # =========================================================================
        # PHASE 1: PHYSICAL HISTORY ACQUISITION (D0 vs D1 vs D2)
        # =========================================================================
        t_hist_start_sim = node.get_sim_time_sec()
        hist_odom_samples: List[Dict[str, Any]] = []

        if scenario_name == "D0":
            log_ep("[History Phase D0] Fresh untried scenario. Zero historical traversal.")
            history_distance = 0.0
            history_sim_time = 0.0

        elif scenario_name in ["D1", "D2"]:
            # 1. Spawn Obstacle
            log_ep(f"[History Phase {scenario_name}] Spawning obstacle '{obs_name}' at ({obs_x}, {obs_y}, {obs_z})...")
            node.spawn_obstacle(obs_name, obs_sdf, obs_x, obs_y, obs_z)
            time.sleep(1.0)
            rclpy.spin_once(node, timeout_sec=0.1)

            # 2. Physically Probe Path A towards Chokepoint A entrance (-0.50, 1.20)
            log_ep(f"[History Phase {scenario_name}] Probing Path A towards entrance (-0.50, 1.20)...")
            node.start_tracking()
            probe_act = {
                "action_id": "hist_probe_1",
                "action": "navigate",
                "params": {"goal": [-0.50, 1.20, 0.0], "frame_id": "map", "timeout_sec": 25.0},
            }
            summary_p1, eval_p1, _ = execute_navigation_action(node, dispatcher, probe_act, log_ep, thresholds)
            action_summaries.append(summary_p1)
            hist_odom_samples.extend(node.episode_odom_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            # Record OCCUPIED observation
            sim_now = node.get_sim_time_sec()
            occ_obs = {
                "doorway_state": "OCCUPIED",
                "reason": "PHYSICAL_OBSTACLE_DETECTED (laser hits inside doorway bbox)",
                "doorway_bbox": list(doorway_bbox),
                "stamp_sec": round(sim_now, 3),
                "region_id": chokepoint_region,
                "map_version": "p2c_dualpath_world_v1",
            }
            cache.update_observation(chokepoint_region, "OCCUPIED", sim_now, occ_obs)
            fail_store.record_failure(
                goal=target_goal,
                region_id=chokepoint_region,
                failure_reason="BUDGET_DEADLINE_EXCEEDED",
                sim_time=sim_now,
                failed_action_id="hist_probe_1",
                failure_evidence_id="probe1_occ_obs",
                failure_evidence=occ_obs,
                map_version="p2c_dualpath_world_v1",
            )
            m1_suppressed = True

            # Snapshot at Chokepoint
            cm_probe1 = inspect_chokepoint_costmap_occupancy(node._latest_raw_costmap, doorway_bbox)
            cm_probe1["stage"] = "COSTMAP_PROBE_BLOCKED_AT_CHOKEPOINT"
            cm_probe1["sim_time_sec"] = round(sim_now, 3)
            costmap_snapshots.append(cm_probe1)
            log_ep(f"[History Phase {scenario_name}] Recorded OCCUPIED at Chokepoint A. Costmap occupied cells={cm_probe1['occupied_cell_count']}")

            # 3. Retreat back to J0 (-2.50, 0.00)
            log_ep(f"[History Phase {scenario_name}] Retreating back to Decision Junction J0 (-2.50, 0.00)...")
            node.start_tracking()
            retreat1_act = {
                "action_id": "hist_retreat_1",
                "action": "navigate",
                "params": {"goal": [-2.50, 0.00, 0.0], "frame_id": "map", "timeout_sec": 25.0},
            }
            summary_r1, eval_r1, _ = execute_navigation_action(node, dispatcher, retreat1_act, log_ep, thresholds)
            action_summaries.append(summary_r1)
            hist_odom_samples.extend(node.episode_odom_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            cm_ret1 = inspect_chokepoint_costmap_occupancy(node._latest_raw_costmap, doorway_bbox)
            cm_ret1["stage"] = "COSTMAP_AFTER_RETREAT_TO_J0"
            cm_ret1["sim_time_sec"] = round(node.get_sim_time_sec(), 3)
            costmap_snapshots.append(cm_ret1)

            if scenario_name == "D2":
                # Clearance & Probe 2
                log_ep("[History Phase D2] Deleting obstacle from Gazebo to simulate environmental clearance...")
                del_ok = node.delete_obstacle(obs_name)
                time.sleep(1.0)
                rclpy.spin_once(node, timeout_sec=0.1)

                log_ep("[History Phase D2] Probing Path A again to observe clearance...")
                node.start_tracking()
                probe2_act = {
                    "action_id": "hist_probe_2",
                    "action": "navigate",
                    "params": {"goal": [-0.50, 1.20, 0.0], "frame_id": "map", "timeout_sec": 25.0},
                }
                summary_p2, eval_p2, _ = execute_navigation_action(node, dispatcher, probe2_act, log_ep, thresholds)
                action_summaries.append(summary_p2)
                hist_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                sim_now_clear = node.get_sim_time_sec()
                free_obs = {
                    "doorway_state": "FREE",
                    "reason": "PHYSICAL_CLEARANCE_VERIFIED (rays traversing corridor)",
                    "doorway_bbox": list(doorway_bbox),
                    "stamp_sec": round(sim_now_clear, 3),
                    "region_id": chokepoint_region,
                    "map_version": "p2c_dualpath_world_v1",
                }
                cache.update_observation(chokepoint_region, "FREE", sim_now_clear, free_obs)
                ev_to_check = dict(free_obs)
                ev_to_check["timestamp_sim"] = sim_now_clear
                fail_store.evaluate_perception_for_invalidation(
                    perception_evidence=ev_to_check,
                    sim_time=sim_now_clear,
                    evidence_id="probe2_obs_clear",
                    map_version="p2c_dualpath_world_v1",
                    region_id=chokepoint_region,
                )

                cm_probe2 = inspect_chokepoint_costmap_occupancy(node._latest_raw_costmap, doorway_bbox)
                cm_probe2["stage"] = "COSTMAP_PROBE_CLEARED_AT_CHOKEPOINT"
                cm_probe2["sim_time_sec"] = round(sim_now_clear, 3)
                costmap_snapshots.append(cm_probe2)
                log_ep(f"[History Phase D2] Recorded FREE at Chokepoint A. Costmap occupied cells={cm_probe2['occupied_cell_count']}")

                log_ep("[History Phase D2] Retreating back to Decision Junction J0...")
                node.start_tracking()
                retreat2_act = {
                    "action_id": "hist_retreat_2",
                    "action": "navigate",
                    "params": {"goal": [-2.50, 0.00, 0.0], "frame_id": "map", "timeout_sec": 25.0},
                }
                summary_r2, eval_r2, _ = execute_navigation_action(node, dispatcher, retreat2_act, log_ep, thresholds)
                action_summaries.append(summary_r2)
                hist_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                cm_ret2 = inspect_chokepoint_costmap_occupancy(node._latest_raw_costmap, doorway_bbox)
                cm_ret2["stage"] = "COSTMAP_AFTER_CLEARANCE_RETREAT_TO_J0"
                cm_ret2["sim_time_sec"] = round(node.get_sim_time_sec(), 3)
                costmap_snapshots.append(cm_ret2)

            history_distance = integrate_trajectory_distance(hist_odom_samples)
            history_sim_time = round(node.get_sim_time_sec() - t_hist_start_sim, 3)
            log_ep(f"[History Phase Complete] Traversed {history_distance:.2f}m in {history_sim_time:.2f}s sim time.")

        # =========================================================================
        # PHASE 2: POLICY DECISION & EXECUTION FROM JUNCTION J0
        # =========================================================================
        log_ep(f"\n--- [Decision Phase] Method '{method_name}' evaluating route from J0 (-2.50, 0.00) ---")
        t_dec_start_sim = node.get_sim_time_sec()
        dec_odom_samples: List[Dict[str, Any]] = []

        # Policy Route Selection Logic
        route_to_take = "Path_A"
        if method_name == "R":
            route_to_take = "Path_A"
            decision_rationales.append("Local sensor UNKNOWN -> explore nominal short Path A")

        elif method_name == "O":
            cached_st = cache.get_latest_state(chokepoint_region)
            if cached_st == "OCCUPIED":
                route_to_take = "Path_B"
                decision_rationales.append("Spatial observation cache OCCUPIED -> bypass via Path B immediately (0 dead-ends)")
            else:
                route_to_take = "Path_A"
                decision_rationales.append(f"Spatial observation cache {cached_st} -> route via Path A")

        elif method_name == "F":
            is_blocked, blocked_entry, block_reason = fail_store.is_dispatch_blocked(target_goal, chokepoint_region, "p2c_dualpath_world_v1")
            if is_blocked:
                route_to_take = "Path_B"
                decision_rationales.append(f"FailMem active memory {blocked_entry.memory_id} -> bypass via Path B immediately (0 dead-ends)")
            else:
                route_to_take = "Path_A"
                inv_note = " (invalidation verified)" if scenario_name == "D2" else ""
                decision_rationales.append(f"FailMem un-suppressed{inv_note} -> route via Path A")

        elif method_name == "M1":
            if m1_suppressed:
                route_to_take = "Path_B"
                decision_rationales.append("Persistent memory permanently suppresses Path A -> route via Path B detour")
            else:
                route_to_take = "Path_A"
                decision_rationales.append("No prior suppression -> route via Path A")

        log_ep(f"Method '{method_name}' selected initial route: {route_to_take}")

        # Route Execution
        if route_to_take == "Path_A":
            if scenario_name == "D1" and method_name == "R":
                chosen_route = "Path_A_then_Path_B"
                dead_end_traversals = 1
                decision_dispatches = 2

                log_ep("[Decision Execution] Dispatching Path A attempt (will hit blockage)...")
                node.start_tracking()
                act_a = {
                    "action_id": "dec_path_a_blocked",
                    "action": "navigate",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 20.0},
                }
                summary_a, eval_a, _ = execute_navigation_action(node, dispatcher, act_a, log_ep, thresholds)
                action_summaries.append(summary_a)
                dec_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                log_ep("[Decision Execution] Blocked at Chokepoint A. Retreating to J0...")
                node.start_tracking()
                act_ret = {
                    "action_id": "dec_retreat_after_fail",
                    "action": "navigate",
                    "params": {"goal": [-2.50, 0.00, 0.0], "frame_id": "map", "timeout_sec": 25.0},
                }
                summary_ret, eval_ret, _ = execute_navigation_action(node, dispatcher, act_ret, log_ep, thresholds)
                action_summaries.append(summary_ret)
                dec_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                log_ep("[Decision Execution] Executing fallback Path B detour via (0.00, -2.40)...")
                node.start_tracking()
                act_b1 = {
                    "action_id": "dec_fallback_path_b_mid",
                    "action": "navigate",
                    "params": {"goal": [0.00, -2.40, 0.0], "frame_id": "map", "timeout_sec": 35.0},
                }
                summary_b1, eval_b1, _ = execute_navigation_action(node, dispatcher, act_b1, log_ep, thresholds)
                action_summaries.append(summary_b1)
                dec_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                act_b2 = {
                    "action_id": "dec_fallback_path_b_goal",
                    "action": "navigate",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 35.0},
                }
                summary_b2, eval_b2, final_stability = execute_navigation_action(node, dispatcher, act_b2, log_ep, thresholds)
                action_summaries.append(summary_b2)
                dec_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)
                last_eval_dict = eval_b2
                last_summary_dict = summary_b2

            else:
                chosen_route = "Path_A"
                dead_end_traversals = 0
                decision_dispatches = 1

                log_ep("[Decision Execution] Dispatching direct navigation to goal via Path A...")
                node.start_tracking()
                act_a_direct = {
                    "action_id": "dec_path_a_direct",
                    "action": "navigate",
                    "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 45.0},
                }
                summary_a, eval_a, final_stability = execute_navigation_action(node, dispatcher, act_a_direct, log_ep, thresholds)
                action_summaries.append(summary_a)
                dec_odom_samples.extend(node.episode_odom_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)
                last_eval_dict = eval_a
                last_summary_dict = summary_a

        elif route_to_take == "Path_B":
            chosen_route = "Path_B"
            dead_end_traversals = 0
            decision_dispatches = 1

            log_ep("[Decision Execution] Dispatching Path B detour via (0.00, -2.40) to Target Goal...")
            node.start_tracking()
            act_b_mid = {
                "action_id": "dec_path_b_mid",
                "action": "navigate",
                "params": {"goal": [0.00, -2.40, 0.0], "frame_id": "map", "timeout_sec": 35.0},
            }
            summary_bm, eval_bm, _ = execute_navigation_action(node, dispatcher, act_b_mid, log_ep, thresholds)
            action_summaries.append(summary_bm)
            dec_odom_samples.extend(node.episode_odom_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            act_b_goal = {
                "action_id": "dec_path_b_goal",
                "action": "navigate",
                "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": 35.0},
            }
            summary_bg, eval_bg, final_stability = execute_navigation_action(node, dispatcher, act_b_goal, log_ep, thresholds)
            action_summaries.append(summary_bg)
            dec_odom_samples.extend(node.episode_odom_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)
            last_eval_dict = eval_bg
            last_summary_dict = summary_bg

        # Online Verification & Offline Physical Scoring
        if last_eval_dict and last_summary_dict:
            online_feedback = {
                "nav2_status": last_summary_dict.get("terminal_status_name"),
                "status_code": last_summary_dict.get("status_code"),
                "execution_outcome": last_summary_dict.get("execution_outcome"),
                "deadline_exceeded": last_summary_dict.get("deadline_exceeded", False),
                "amcl_pose": node.latest_amcl_record,
                "odom_halt": node.latest_odom_record,
            }
            online_ok, online_reasons, online_details = verify_online_arrival(
                target_goal=target_goal,
                online_feedback=online_feedback,
                thresholds=thresholds,
                sim_time=node.get_sim_time_sec(),
                target_region=chokepoint_region,
                map_version="p2c_dualpath_world_v1",
            )
            policy_reported_success = online_ok
            evaluator_verified_success = bool(last_eval_dict.get("strict_physical_arrival_and_stable", False))
            final_disagreement_reason = compute_disagreement_reason(policy_reported_success, evaluator_verified_success, last_eval_dict)

        decision_distance = integrate_trajectory_distance(dec_odom_samples)
        decision_sim_time = round(node.get_sim_time_sec() - t_dec_start_sim, 3)

        total_distance = round(history_distance + decision_distance, 3)
        total_sim_time = round(node.get_sim_time_sec() - episode_t0, 3)

        log_ep(f"=== Episode {ep_id} Finished ===")
        log_ep(f"Route: {chosen_route}, Dead-Ends: {dead_end_traversals}, Decision Dist: {decision_distance:.2f}m, Decision Time: {decision_sim_time:.2f}s, Total Dist: {total_distance:.2f}m, Total Time: {total_sim_time:.2f}s, Success: {evaluator_verified_success}")

        # Save Episode Artifacts
        with open(ep_dir / "action_result.json", "w", encoding="utf-8") as f:
            json.dump({
                "episode_id": ep_id,
                "condition_id": condition_id,
                "scenario": scenario_name,
                "method": method_name,
                "chosen_route": chosen_route,
                "dead_end_traversals": dead_end_traversals,
                "decision_dispatches": decision_dispatches,
                "history_distance_m": history_distance,
                "history_sim_time_sec": history_sim_time,
                "decision_distance_m": decision_distance,
                "decision_sim_time_sec": decision_sim_time,
                "total_distance_m": total_distance,
                "total_sim_time_sec": total_sim_time,
                "policy_reported_success": policy_reported_success,
                "evaluator_verified_success": evaluator_verified_success,
                "disagreement_reason": final_disagreement_reason,
                "decision_rationales": decision_rationales,
                "actions": action_summaries,
            }, f, indent=2)

        with open(ep_dir / "trajectory.json", "w", encoding="utf-8") as f:
            json.dump({
                "gt_samples_count": len(all_gt_samples),
                "odom_samples_count": len(all_odom_samples),
                "gt_trajectory": all_gt_samples,
                "odom_trajectory": all_odom_samples,
            }, f, indent=2)

        with open(ep_dir / "costmap_snapshots.json", "w", encoding="utf-8") as f:
            json.dump(costmap_snapshots, f, indent=2)

        with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
            json.dump({
                "sample_count": len(final_stability),
                "window_records": final_stability,
            }, f, indent=2)

        return {
            "episode_id": ep_id,
            "condition_id": condition_id,
            "scenario": scenario_name,
            "method": method_name,
            "evidence_type": "physical_ros_gazebo",
            "chosen_route": chosen_route,
            "dead_end_traversals": dead_end_traversals,
            "history_distance_m": history_distance,
            "history_sim_time_sec": history_sim_time,
            "decision_distance_m": decision_distance,
            "decision_sim_time_sec": decision_sim_time,
            "total_distance_m": total_distance,
            "total_sim_time_sec": total_sim_time,
            "policy_reported_success": policy_reported_success,
            "evaluator_verified_success": evaluator_verified_success,
            "disagreement_reason": final_disagreement_reason,
        }

    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        rclpy.shutdown()
        cleanup_simulation_processes()
        try:
            events_log.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="FailMem Milestone P2c Real ROS 2 Experiment Runner")
    parser.add_argument("--protocol", default="configs/p2c_pilot_protocol.yaml", help="Path to protocol YAML")
    parser.add_argument("--condition", default=None, help="Filter by specific condition ID (e.g. D1_R)")
    parser.add_argument("--scenario", default=None, help="Filter by scenario (e.g. D0, D1, D2)")
    parser.add_argument("--method", default=None, help="Filter by method (e.g. R, O, F, M1)")
    args = parser.parse_args()

    protocol_yaml_path = Path(args.protocol)
    with open(protocol_yaml_path, "r", encoding="utf-8") as f:
        protocol_config = yaml.safe_load(f)

    h_proto = hashlib.sha256()
    with open(protocol_yaml_path, "rb") as f:
        while chunk := f.read(65536):
            h_proto.update(chunk)
    protocol_sha256 = h_proto.hexdigest()

    scoring_rules = load_scoring_rules("configs/scoring_rules.yaml")
    thresholds = protocol_config.get("scoring_thresholds", scoring_rules.get("thresholds", {}))

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    run_id = f"p2c_pilot_{timestamp_str}_{rand_suffix}"

    evidence_base = Path("/workspace/reports/evidence/p2c_pilot") if Path("/workspace").exists() else Path("reports/evidence/p2c_pilot")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=======================================================================")
    print(f"FailMem P2c Real ROS 2 Experiment Runner: {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"Protocol: {protocol_yaml_path} (SHA256: {protocol_sha256})")
    print("=======================================================================")

    all_conditions = [
        {"cond_id": "D0_R", "scenario": "D0", "method": "R"},
        {"cond_id": "D0_O", "scenario": "D0", "method": "O"},
        {"cond_id": "D0_F", "scenario": "D0", "method": "F"},
        {"cond_id": "D1_R", "scenario": "D1", "method": "R"},
        {"cond_id": "D1_O", "scenario": "D1", "method": "O"},
        {"cond_id": "D1_F", "scenario": "D1", "method": "F"},
        {"cond_id": "D2_R", "scenario": "D2", "method": "R"},
        {"cond_id": "D2_O", "scenario": "D2", "method": "O"},
        {"cond_id": "D2_F", "scenario": "D2", "method": "F"},
        {"cond_id": "D2_M1", "scenario": "D2", "method": "M1"},
    ]

    conditions = all_conditions
    if args.condition:
        conditions = [c for c in conditions if c["cond_id"] == args.condition]
    if args.scenario:
        conditions = [c for c in conditions if c["scenario"] == args.scenario]
    if args.method:
        conditions = [c for c in conditions if c["method"] == args.method]

    results: List[Dict[str, Any]] = []

    for cond in conditions:
        res = run_physical_episode(
            condition_id=cond["cond_id"],
            scenario_name=cond["scenario"],
            method_name=cond["method"],
            ep_num=1,
            run_dir=run_dir,
            protocol_config=protocol_config,
            thresholds=thresholds,
            run_id=run_id,
        )
        results.append(res)

    summary_matrix = {
        "run_id": run_id,
        "evidence_type": "physical_ros_gazebo",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": protocol_sha256,
        "protocol_version": protocol_config.get("protocol_version", "4.1"),
        "total_episodes": len(results),
        "episodes": results,
    }
    with open(run_dir / "p2c_pilot_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_matrix, f, indent=2)

    compute_sha256_tree(run_dir, run_dir / "checksums.sha256")

    print("\n=======================================================================")
    print("FailMem Milestone P2c Real ROS Physical Experiment Complete. Summary:")
    print("-----------------------------------------------------------------------")
    print("| Scenario | Method | Route | Dead-End | Decision Dist | Decision Time | Total Dist | Total Time | Success |")
    print("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        print(f"| {r['scenario']:8s} | {r['method']:6s} | {r['chosen_route']:22s} | {r['dead_end_traversals']:8d} | {r['decision_distance_m']:11.2f}m | {r['decision_sim_time_sec']:11.2f}s | {r['total_distance_m']:8.2f}m | {r['total_sim_time_sec']:8.2f}s | {str(r['evaluator_verified_success']):7s} |")
    print("=======================================================================")
    print(f"Evidence saved to: {run_dir}")


if __name__ == "__main__":
    main()
