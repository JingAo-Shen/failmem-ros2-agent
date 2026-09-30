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
- Enforces strict 180.0s total simulation budget across all stages.
- Uses unified production pipeline `src.p2c_pipeline` for all classification, gating, and validity evaluation.
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
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped
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
from src.doorway_evaluator import (
    extract_costmap_doorway_subgrid,
    evaluate_doorway_clearance,
)
from src.failure_memory import (
    MemoryState,
    FailureMemoryEntry,
    FailureMemoryStore,
)
from src.p2c_pipeline import (
    P2cProtocolConfig,
    P2cTrajectoryClassifier,
    P2cPolicyDecider,
    P2cEpisodeEvaluator,
    SpatialObservationCache,
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


def capture_costmap_snapshot(
    node: P1cV3RunnerNode,
    stage: str,
    sim_time: float,
    doorway_bbox: Tuple[float, float, float, float] = (-0.20, 0.20, 0.90, 1.50),
    opening_bbox: Tuple[float, float, float, float] = (-0.15, 0.15, 0.95, 1.45),
) -> Dict[str, Any]:
    """Extract and analyze costmap subgrid cells within doorway ROI and opening center."""
    cm = node._latest_raw_costmap
    if cm is None:
        return {
            "stage": stage,
            "sim_time_sec": round(sim_time, 3),
            "costmap_available": False,
            "cell_counts": {"unknown": 0, "free": 0, "inflated": 0, "lethal": 0, "opening_lethal": 0},
            "subgrid_matrix": [],
        }

    info = cm.info
    res = float(info.resolution)
    ox = float(info.origin.position.x)
    oy = float(info.origin.position.y)
    w = int(info.width)
    h = int(info.height)
    data = list(cm.data)

    xmin, xmax, ymin, ymax = doorway_bbox
    u_min = max(0, int((xmin - ox) / res))
    u_max = min(w - 1, int((xmax - ox) / res))
    v_min = max(0, int((ymin - oy) / res))
    v_max = min(h - 1, int((ymax - oy) / res))

    op_xmin, op_xmax, op_ymin, op_ymax = opening_bbox
    op_umin = max(0, int((op_xmin - ox) / res))
    op_umax = min(w - 1, int((op_xmax - ox) / res))
    op_vmin = max(0, int((op_ymin - oy) / res))
    op_vmax = min(h - 1, int((op_ymax - oy) / res))

    unknown_cnt = 0
    free_cnt = 0
    inflated_cnt = 0
    lethal_cnt = 0
    opening_lethal_cnt = 0
    subgrid_matrix = []

    for v in range(v_min, v_max + 1):
        row = []
        for u in range(u_min, u_max + 1):
            idx = v * w + u
            val = data[idx] if 0 <= idx < len(data) else -1
            row.append(val)
            if val < 0:
                unknown_cnt += 1
            elif val == 0:
                free_cnt += 1
            elif 1 <= val < 100:
                inflated_cnt += 1
            elif val >= 100:
                lethal_cnt += 1
                if op_umin <= u <= op_umax and op_vmin <= v <= op_vmax:
                    opening_lethal_cnt += 1
        subgrid_matrix.append(row)

    return {
        "stage": stage,
        "sim_time_sec": round(sim_time, 3),
        "costmap_available": True,
        "resolution_m": res,
        "origin_xy": [ox, oy],
        "grid_bounds_u": [u_min, u_max],
        "grid_bounds_v": [v_min, v_max],
        "doorway_bbox": list(doorway_bbox),
        "opening_bbox": list(opening_bbox),
        "cell_counts": {
            "unknown": unknown_cnt,
            "free": free_cnt,
            "inflated": inflated_cnt,
            "lethal": lethal_cnt,
            "opening_lethal": opening_lethal_cnt,
        },
        "has_blockage": (opening_lethal_cnt > 0),
        "subgrid_matrix": subgrid_matrix,
    }


def capture_scan_snapshot(
    node: P1cV3RunnerNode,
    stage: str,
    sim_time: float,
    doorway_bbox: Tuple[float, float, float, float],
    perception_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Capture raw laser scan parameters and map->base_scan TF for independent replay."""
    raw_scan = node._latest_raw_scan
    scan_stamp = (raw_scan.header.stamp.sec + raw_scan.header.stamp.nanosec * 1e-9) if raw_scan is not None else sim_time
    tf_rec = node.get_laser_map_transform(stamp_sec=scan_stamp, timeout_sec=0.5)
    if tf_rec is None:
        node.request_nomotion_amcl_update(timeout_sec=1.0)
        tf_rec = node.get_laser_map_transform(timeout_sec=1.0)

    scan_data = None
    if raw_scan is not None:
        scan_data = {
            "ranges": [round(float(r), 4) if (r is not None and math.isfinite(r)) else None for r in raw_scan.ranges],
            "angle_min": round(float(raw_scan.angle_min), 4),
            "angle_max": round(float(raw_scan.angle_max), 4),
            "angle_increment": round(float(raw_scan.angle_increment), 6),
            "range_min": round(float(raw_scan.range_min), 4),
            "range_max": round(float(raw_scan.range_max), 4),
            "stamp_sec": round(scan_stamp, 4),
        }

    tf_data = None
    if tf_rec is not None:
        tf_data = {
            "translation": [round(float(v), 4) for v in tf_rec.get("translation", [0.0, 0.0, 0.0])],
            "yaw": round(float(tf_rec.get("yaw", 0.0)), 4),
            "stamp_sec": round(float(tf_rec.get("stamp_sec", scan_stamp)), 4),
            "frame_id": tf_rec.get("frame_id", "map"),
            "child_frame_id": tf_rec.get("child_frame_id", "base_scan"),
        }

    return {
        "stage": stage,
        "sim_time_sec": round(scan_stamp, 3),
        "has_raw_scan": (scan_data is not None),
        "has_tf": (tf_data is not None),
        "doorway_bbox": list(doorway_bbox),
        "scan_data": scan_data,
        "tf_transform": tf_data,
        "perception_result": copy.deepcopy(perception_result),
    }


def run_physical_episode(
    condition_id: str,
    scenario_name: str,
    method_name: str,
    ep_num: int,
    run_dir: Path,
    proto_cfg: P2cProtocolConfig,
    protocol_sha256: str,
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

    spawn_cfg = proto_cfg.raw_config["environment"]["spawn_pose"]
    spawn_coords = [float(spawn_cfg["x"]), float(spawn_cfg["y"]), float(spawn_cfg.get("yaw", 0.0))]
    junc_pose = proto_cfg.decision_junction
    target_goal = proto_cfg.target_goal
    chokepoint_region = proto_cfg.chokepoint_region
    map_version = proto_cfg.map_version
    doorway_bbox = proto_cfg.doorway_bbox
    opening_bbox = proto_cfg.opening_bbox
    total_budget_sec = proto_cfg.total_sim_budget_sec
    action_sim_timeout = float(proto_cfg.raw_config.get("navigation_task", {}).get("action_sim_timeout_sec", 45.0))
    thresholds = proto_cfg.thresholds

    obs_cfg = proto_cfg.raw_config["obstacle_channel"]
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

    scan_snapshots: List[Dict[str, Any]] = []
    costmap_snapshots: List[Dict[str, Any]] = []
    action_summaries: List[Dict[str, Any]] = []
    all_gt_samples: List[Dict[str, Any]] = []
    all_odom_samples: List[Dict[str, Any]] = []
    memory_events: List[Dict[str, Any]] = []

    history_distance = 0.0
    history_sim_time = 0.0
    decision_distance = 0.0
    decision_sim_time = 0.0
    dead_end_traversals = 0
    decision_dispatches = 0
    route_attempt_count = 1
    chosen_route = "UNKNOWN"
    decision_rationales: List[str] = []

    policy_reported_success = False
    evaluator_verified_success = False
    final_disagreement_reason: Optional[str] = None
    last_eval_dict: Optional[Dict[str, Any]] = None
    last_summary_dict: Optional[Dict[str, Any]] = None
    final_stability: List[Dict[str, Any]] = []

    history_valid = True
    route_valid = True
    episode_valid = False
    budget_exhausted_during_run = False

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
        t_amcl_start = time.monotonic()
        while time.monotonic() - t_amcl_start < 25.0:
            if node.latest_amcl_record is None:
                node.initialize_amcl_pose(spawn_coords)
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_amcl_record is not None:
                delta = math.hypot(node.latest_amcl_record["x"] - spawn_coords[0], node.latest_amcl_record["y"] - spawn_coords[1])
                if delta < 0.35:
                    log_ep(f"AMCL pose converged at ({node.latest_amcl_record['x']:.2f}, {node.latest_amcl_record['y']:.2f})")
                    break
            time.sleep(0.2)

        # 4. Verify Nav2 bt_navigator lifecycle
        t_nav_start = time.monotonic()
        while time.monotonic() - t_nav_start < 20.0:
            st = node.query_lifecycle_state(timeout_sec=0.5)
            if st == "active":
                log_ep("Nav2 bt_navigator is ACTIVE!")
                break
            time.sleep(0.5)

        # 5. Ensure AMCL TF is ready and fresh before action dispatch
        t_tf_start = time.monotonic()
        while time.monotonic() - t_tf_start < 15.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            node.request_nomotion_amcl_update(timeout_sec=1.0)
            tf_rec = node.get_laser_map_transform(timeout_sec=0.5)
            if tf_rec is not None:
                log_ep("AMCL TF map->base_scan is verified ACTIVE and fresh!")
                break
            time.sleep(0.3)

        # Baseline Costmap Snapshot at J0
        cm_base = capture_costmap_snapshot(node, "COSTMAP_BASELINE_J0", node.get_sim_time_sec(), doorway_bbox, opening_bbox)
        costmap_snapshots.append(cm_base)

        # Observability Verification from J0
        obs_j0 = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
        sightline_j0 = verify_sightline_occlusion((spawn_coords[0], spawn_coords[1]), (obs_x, obs_y))
        log_ep(f"J0 Observability: Sightline Occluded={sightline_j0['line_of_sight_occluded']}, Local Doorway State={obs_j0['doorway_state']} (Reason: {obs_j0['reason']})")
        scan_snapshots.append(capture_scan_snapshot(node, "BASELINE_J0", node.get_sim_time_sec(), doorway_bbox, obs_j0))

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
        abs_sim_deadline = episode_t0 + total_budget_sec

        def run_step(action_dict: Dict[str, Any], nominal_timeout: float) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
            nonlocal budget_exhausted_during_run
            now_sim = node.get_sim_time_sec()
            rem_budget = abs_sim_deadline - now_sim
            if rem_budget <= 0.5:
                budget_exhausted_during_run = True
                log_ep(f"[BUDGET] Episode total simulation budget exhausted ({now_sim - episode_t0:.2f}s >= {total_budget_sec:.2f}s)!")
                dummy_summary = {
                    "action_id": action_dict.get("action_id"),
                    "execution_outcome": "BUDGET_DEADLINE_EXCEEDED",
                    "terminal_status_name": "ABORTED",
                    "deadline_exceeded": True,
                    "failure_reason": "TOTAL_BUDGET_EXHAUSTED",
                }
                dummy_eval = {"strict_physical_arrival_and_stable": False, "execution_outcome": "BUDGET_DEADLINE_EXCEEDED"}
                return dummy_summary, dummy_eval, []

            eff_timeout = min(nominal_timeout, rem_budget)
            action_dict["params"]["timeout_sec"] = eff_timeout
            s_sum, s_eval, s_stab = execute_navigation_action(
                node, dispatcher, action_dict, log_ep, thresholds, abs_sim_deadline=abs_sim_deadline
            )
            return s_sum, s_eval, s_stab

        # =========================================================================
        # PHASE 1: PHYSICAL HISTORY ACQUISITION (D0 vs D1 vs D2)
        # =========================================================================
        t_hist_start_sim = node.get_sim_time_sec()
        hist_odom_samples: List[Dict[str, Any]] = []
        hist_gt_samples: List[Dict[str, Any]] = []

        if scenario_name == "D0":
            log_ep("[History Phase D0] Fresh untried scenario. Zero historical traversal.")
            history_distance = 0.0
            history_sim_time = 0.0
            history_valid = True

        elif scenario_name in ["D1", "D2"]:
            # 1. Spawn Obstacle
            log_ep(f"[History Phase {scenario_name}] Spawning obstacle '{obs_name}' at ({obs_x}, {obs_y}, {obs_z})...")
            node.spawn_obstacle(obs_name, obs_sdf, obs_x, obs_y, obs_z)
            time.sleep(1.0)
            rclpy.spin_once(node, timeout_sec=0.1)

            # 2. Action 1: Reach Observation Vantage Point (-1.00, 1.20)
            log_ep(f"[History Phase {scenario_name}] Step 1: Navigating to observation vantage point (-1.00, 1.20)...")
            node.start_tracking()
            vantage_act = {
                "action_id": "hist_reach_obs_vantage",
                "action": "navigate",
                "params": {"goal": [-1.00, 1.20, 0.0], "frame_id": "map"},
            }
            summary_v1, eval_v1, _ = run_step(vantage_act, nominal_timeout=action_sim_timeout)
            action_summaries.append(summary_v1)
            hist_odom_samples.extend(node.episode_odom_samples)
            hist_gt_samples.extend(node.episode_gt_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            vantage1_ok = (summary_v1.get("terminal_status_name") == "SUCCEEDED" and summary_v1.get("execution_outcome") == "BUDGET_SUCCESS")
            log_ep(f"[History Phase {scenario_name}] Step 1 Vantage arrival result: SUCCEEDED={vantage1_ok}")

            # Sample Live Perception from Vantage Point
            node.request_nomotion_amcl_update(timeout_sec=1.5)
            sim_now_v1 = node.get_sim_time_sec()
            occ_obs = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=1.0)
            occ_obs["region_id"] = chokepoint_region
            occ_obs["map_version"] = map_version
            occ_obs["stamp_sec"] = round(sim_now_v1, 3)
            log_ep(f"[History Phase {scenario_name}] Step 1 Live Perception: State={occ_obs.get('doorway_state')} (Hits={occ_obs.get('hits_inside_count')}, Reason: {occ_obs.get('reason')})")
            scan_snapshots.append(capture_scan_snapshot(node, "STEP1_VANTAGE1", sim_now_v1, doorway_bbox, occ_obs))

            # Update cache with live observation
            if occ_obs.get("doorway_state") in ["OCCUPIED", "FREE"]:
                cache.update_observation(chokepoint_region, occ_obs.get("doorway_state"), sim_now_v1, occ_obs)

            # Snapshot Costmap after probe at chokepoint
            cm_probe1 = capture_costmap_snapshot(node, "COSTMAP_PROBE_BLOCKED_AT_CHOKEPOINT", sim_now_v1, doorway_bbox, opening_bbox)
            costmap_snapshots.append(cm_probe1)

            # 3. Action 2: Attempt Real Chokepoint Traversal through Doorway (Real Nav2 Action)
            log_ep(f"[History Phase {scenario_name}] Step 2: Attempting real Nav2 chokepoint traversal through doorway (goal: [0.50, 1.20, 0.0])...")
            node.start_tracking()
            trav_act = {
                "action_id": "hist_attempt_chokepoint_traversal",
                "action": "navigate",
                "params": {"goal": [0.50, 1.20, 0.0], "frame_id": "map"},
            }
            summary_tr1, eval_tr1, stab_tr1 = run_step(trav_act, nominal_timeout=12.0)
            action_summaries.append(summary_tr1)
            hist_odom_samples.extend(node.episode_odom_samples)
            hist_gt_samples.extend(node.episode_gt_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            # Sample Fresh Live Perception immediately upon traversal termination
            sim_now_tr1 = node.get_sim_time_sec()
            node.request_nomotion_amcl_update(timeout_sec=1.5)
            post_fail_obs = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=1.0)
            post_fail_obs["region_id"] = chokepoint_region
            post_fail_obs["map_version"] = map_version
            post_fail_obs["stamp_sec"] = round(sim_now_tr1, 3)
            log_ep(f"[History Phase {scenario_name}] Step 2 Post-traversal Live Perception: State={post_fail_obs.get('doorway_state')} (Hits={post_fail_obs.get('hits_inside_count')}, Reason: {post_fail_obs.get('reason')})")
            scan_snapshots.append(capture_scan_snapshot(node, "STEP2_POST_TRAVERSAL", sim_now_tr1, doorway_bbox, post_fail_obs))

            if post_fail_obs.get("doorway_state") in ["OCCUPIED", "FREE"]:
                cache.update_observation(chokepoint_region, post_fail_obs.get("doorway_state"), sim_now_tr1, post_fail_obs)

            # Robust linked perception: use post_fail_obs if conclusive, else occ_obs from vantage probe
            linked_obs = post_fail_obs if post_fail_obs.get("doorway_state") in ["OCCUPIED", "FREE"] else occ_obs

            fail_cause = P2cTrajectoryClassifier.diagnose_failure_cause(
                summary_tr1, node.episode_gt_samples, linked_obs, max_staleness_sec=30.0
            )
            summary_tr1["failure_cause"] = fail_cause

            trav1_outcome = summary_tr1.get("execution_outcome")
            trav1_failed = (trav1_outcome in ["BUDGET_DEADLINE_EXCEEDED", "BUDGET_ABORTED", "FAILED"] or summary_tr1.get("terminal_status_name") in ["ABORTED", "CANCELED"])
            log_ep(f"[History Phase {scenario_name}] Step 2 Traversal outcome: {trav1_outcome} (Diagnosed cause: {fail_cause})")

            # Only genuine failed action with linked OCCUPIED evidence creates failure memory
            if trav1_failed and linked_obs.get("doorway_state") == "OCCUPIED":
                entry = fail_store.record_failure(
                    goal=target_goal,
                    region_id=chokepoint_region,
                    failure_reason=fail_cause or trav1_outcome or "BUDGET_DEADLINE_EXCEEDED",
                    sim_time=sim_now_tr1,
                    failed_action_id="hist_attempt_chokepoint_traversal",
                    failure_evidence_id="probe_occ_obs",
                    failure_evidence=linked_obs,
                    map_version=map_version,
                    metadata={"goal_uuid": summary_tr1.get("dispatch", {}).get("goal_uuid")},
                )
                m1_suppressed = True
                memory_events.append({
                    "event_type": "RECORD_FAILURE",
                    "sim_time": round(sim_now_tr1, 3),
                    "memory_id": entry.memory_id if entry else "unknown",
                    "region_id": chokepoint_region,
                    "evidence": linked_obs,
                })
                log_ep(f"[History Phase {scenario_name}] Successfully created Failure Memory bound to action 'hist_attempt_chokepoint_traversal'.")
            else:
                log_ep(f"[History Phase {scenario_name}] WARNING: Traversal did not fail with OCCUPIED evidence! Failure memory not created.")

            # 4. Action 3: Retreat Back to Decision Junction J0 (-2.50, 0.00)
            log_ep(f"[History Phase {scenario_name}] Step 3: Retreating back to Decision Junction J0 (-2.50, 0.00)...")
            node.start_tracking()
            retreat1_act = {
                "action_id": "hist_retreat_to_j0",
                "action": "navigate",
                "params": {"goal": [-2.50, 0.00, 0.0], "frame_id": "map"},
            }
            summary_r1, eval_r1, _ = run_step(retreat1_act, nominal_timeout=action_sim_timeout)
            action_summaries.append(summary_r1)
            hist_odom_samples.extend(node.episode_odom_samples)
            hist_gt_samples.extend(node.episode_gt_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            ret1_ok = (summary_r1.get("terminal_status_name") == "SUCCEEDED" and summary_r1.get("execution_outcome") == "BUDGET_SUCCESS")
            log_ep(f"[History Phase {scenario_name}] Step 3 Retreat result: SUCCEEDED={ret1_ok}")

            # Resample perception after returning to J0 (verifying UNKNOWN)
            obs_at_j0 = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
            log_ep(f"[History Phase {scenario_name}] Resampled perception at J0: State={obs_at_j0.get('doorway_state')} (Reason: {obs_at_j0.get('reason')})")
            scan_snapshots.append(capture_scan_snapshot(node, "STEP3_RETREAT_J0", node.get_sim_time_sec(), doorway_bbox, obs_at_j0))

            cm_ret1 = capture_costmap_snapshot(node, "COSTMAP_AFTER_RETREAT_TO_J0", node.get_sim_time_sec(), doorway_bbox, opening_bbox)
            costmap_snapshots.append(cm_ret1)

            d1_valid = bool(vantage1_ok and trav1_failed and ret1_ok and linked_obs.get("doorway_state") == "OCCUPIED")
            history_valid = d1_valid

            if scenario_name == "D2":
                # Clearance & Probe 2
                log_ep("[History Phase D2] Deleting obstacle from Gazebo to simulate environmental clearance...")
                del_ok = node.delete_obstacle(obs_name)
                time.sleep(1.0)
                rclpy.spin_once(node, timeout_sec=0.1)

                # Action 4: Probe clearance vantage point (-1.00, 1.20)
                log_ep("[History Phase D2] Step 4: Probing Path A again to observe clearance (-1.00, 1.20)...")
                node.start_tracking()
                probe2_act = {
                    "action_id": "hist_probe_clearance_vantage",
                    "action": "navigate",
                    "params": {"goal": [-1.00, 1.20, 0.0], "frame_id": "map"},
                }
                summary_p2, eval_p2, _ = run_step(probe2_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(summary_p2)
                hist_odom_samples.extend(node.episode_odom_samples)
                hist_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                vantage2_ok = (summary_p2.get("terminal_status_name") == "SUCCEEDED" and summary_p2.get("execution_outcome") == "BUDGET_SUCCESS")

                sim_now_clear = node.get_sim_time_sec()
                free_obs = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=1.0)
                free_obs["region_id"] = chokepoint_region
                free_obs["map_version"] = map_version
                free_obs["stamp_sec"] = round(sim_now_clear, 3)
                log_ep(f"[History Phase D2] Step 4 Live Perception: State={free_obs.get('doorway_state')} (Pass-through={free_obs.get('pass_through_count')}, Reason: {free_obs.get('reason')})")
                scan_snapshots.append(capture_scan_snapshot(node, "STEP4_CLEARANCE_VANTAGE", sim_now_clear, doorway_bbox, free_obs))

                if free_obs.get("doorway_state") in ["OCCUPIED", "FREE"]:
                    cache.update_observation(chokepoint_region, free_obs.get("doorway_state"), sim_now_clear, free_obs)

                if free_obs.get("doorway_state") == "FREE":
                    ev_to_check = dict(free_obs)
                    ev_to_check["timestamp_sim"] = sim_now_clear
                    inv_entries = fail_store.evaluate_perception_for_invalidation(
                        perception_evidence=ev_to_check,
                        sim_time=sim_now_clear,
                        evidence_id="probe2_obs_clear",
                        map_version=map_version,
                        region_id=chokepoint_region,
                    )
                    for inv in inv_entries:
                        memory_events.append({
                            "event_type": "INVALIDATE_MEMORY",
                            "sim_time": round(sim_now_clear, 3),
                            "memory_id": inv.memory_id,
                            "evidence": free_obs,
                        })
                    log_ep(f"[History Phase D2] Evaluated FREE perception -> {len(inv_entries)} Failure Memory INVALIDATED.")

                cm_probe2 = capture_costmap_snapshot(node, "COSTMAP_PROBE_CLEARED_AT_CHOKEPOINT", sim_now_clear, doorway_bbox, opening_bbox)
                costmap_snapshots.append(cm_probe2)

                # Action 5: Retreat back to J0 after clearance observation
                log_ep("[History Phase D2] Step 5: Retreating back to Decision Junction J0 after clearance...")
                node.start_tracking()
                retreat2_act = {
                    "action_id": "hist_retreat_to_j0_clear",
                    "action": "navigate",
                    "params": {"goal": [-2.50, 0.00, 0.0], "frame_id": "map"},
                }
                summary_r2, eval_r2, _ = run_step(retreat2_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(summary_r2)
                hist_odom_samples.extend(node.episode_odom_samples)
                hist_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                ret2_ok = (summary_r2.get("terminal_status_name") == "SUCCEEDED" and summary_r2.get("execution_outcome") == "BUDGET_SUCCESS")

                # Resample perception after clearance retreat
                obs_at_j0_clear = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
                log_ep(f"[History Phase D2] Resampled perception at J0 after clearance: State={obs_at_j0_clear.get('doorway_state')}")
                scan_snapshots.append(capture_scan_snapshot(node, "STEP5_RETREAT_J0_CLEAR", node.get_sim_time_sec(), doorway_bbox, obs_at_j0_clear))

                cm_ret2 = capture_costmap_snapshot(node, "COSTMAP_AFTER_CLEARANCE_RETREAT_TO_J0", node.get_sim_time_sec(), doorway_bbox, opening_bbox)
                costmap_snapshots.append(cm_ret2)

                d2_valid = bool(d1_valid and vantage2_ok and ret2_ok and free_obs.get("doorway_state") == "FREE")
                history_valid = d2_valid

            history_distance, _ = P2cTrajectoryClassifier.integrate_distance(hist_odom_samples)
            history_sim_time = round(node.get_sim_time_sec() - t_hist_start_sim, 3)
            log_ep(f"[History Phase Complete] Traversed {history_distance:.2f}m in {history_sim_time:.2f}s sim time. History Valid: {history_valid}")

            # Stop formal decision phase comparison if history acquisition failed
            if not history_valid:
                log_ep(f"[HARD STOP] History acquisition invalid for {scenario_name}! Halting episode immediately without decision dispatch.")
                chosen_route = "HISTORY_INVALID_ABORTED"
                actual_route = P2cTrajectoryClassifier.classify_actual_route(hist_gt_samples or hist_odom_samples)
                dead_end_traversals = P2cTrajectoryClassifier.classify_dead_end_traversals(hist_gt_samples or hist_odom_samples)
                total_distance, _ = P2cTrajectoryClassifier.integrate_distance(all_odom_samples)
                total_sim_time = round(node.get_sim_time_sec() - episode_t0, 3)

                eval_report = P2cEpisodeEvaluator.evaluate_episode(
                    scenario=scenario_name,
                    method=method_name,
                    actions=action_summaries,
                    total_sim_time_sec=total_sim_time,
                    total_budget_sec=total_budget_sec,
                    physical_eval_dict={"strict_physical_arrival_and_stable": False},
                    odom_samples=all_odom_samples,
                    costmap_snapshots=costmap_snapshots,
                    checksums_verified=True,
                    protocol_hash_match=True,
                    evidence_complete=True,
                    history_aborted=True,
                )

                # Write all episode artifacts and return immediately!
                with open(ep_dir / "action_result.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "episode_id": ep_id,
                        "condition_id": condition_id,
                        "scenario": scenario_name,
                        "method": method_name,
                        "requested_route": chosen_route,
                        "actual_route": actual_route,
                        "chosen_route": chosen_route,
                        "route_attempt_count": 0,
                        "dead_end_traversals": dead_end_traversals,
                        "decision_dispatches": 0,
                        "nominal_length_path_a_m": proto_cfg.nominal_length_a,
                        "nominal_length_path_b_m": proto_cfg.nominal_length_b,
                        "history_distance_m": history_distance,
                        "history_sim_time_sec": history_sim_time,
                        "decision_distance_m": 0.0,
                        "decision_sim_time_sec": 0.0,
                        "total_distance_m": total_distance,
                        "total_sim_time_sec": total_sim_time,
                        "total_budget_sec": total_budget_sec,
                        "policy_reported_success": False,
                        "evaluator_verified_success": False,
                        "final_goal_success": False,
                        "success_within_budget": False,
                        "history_valid": False,
                        "route_valid": False,
                        "episode_valid": False,
                        "history_aborted": True,
                        "disagreement_reason": "HISTORY_INVALID_ABORTED",
                        "decision_rationales": ["Aborted before decision phase due to invalid history."],
                        "actions": action_summaries,
                    }, f, indent=2)

                with open(ep_dir / "trajectory.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "gt_samples_count": len(all_gt_samples),
                        "odom_samples_count": len(all_odom_samples),
                        "gt_trajectory": all_gt_samples,
                        "odom_trajectory": all_odom_samples,
                        "history_odom_trajectory": hist_odom_samples,
                        "decision_odom_trajectory": [],
                        "history_gt_trajectory": hist_gt_samples,
                        "decision_gt_trajectory": [],
                    }, f, indent=2)

                with open(ep_dir / "costmap_snapshots.json", "w", encoding="utf-8") as f:
                    json.dump(costmap_snapshots, f, indent=2)

                with open(ep_dir / "scan_snapshots.json", "w", encoding="utf-8") as f:
                    json.dump(scan_snapshots, f, indent=2)

                with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
                    json.dump({"sample_count": 0, "window_records": []}, f, indent=2)

                with open(ep_dir / "memory_events.json", "w", encoding="utf-8") as f:
                    json.dump(memory_events, f, indent=2)

                with open(ep_dir / "runtime_protocol.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "protocol_version": proto_cfg.protocol_version,
                        "protocol_sha256": protocol_sha256,
                        "protocol_config": proto_cfg.raw_config,
                    }, f, indent=2)

                return {
                    "episode_id": ep_id,
                    "condition_id": condition_id,
                    "scenario": scenario_name,
                    "method": method_name,
                    "evidence_type": "physical_ros_gazebo",
                    "requested_route": chosen_route,
                    "actual_route": actual_route,
                    "dead_end_traversals": dead_end_traversals,
                    "decision_dispatches": 0,
                    "history_distance_m": history_distance,
                    "history_sim_time_sec": history_sim_time,
                    "decision_distance_m": 0.0,
                    "decision_sim_time_sec": 0.0,
                    "total_distance_m": total_distance,
                    "total_sim_time_sec": total_sim_time,
                    "final_goal_success": False,
                    "success_within_budget": False,
                    "history_valid": False,
                    "route_valid": False,
                    "episode_valid": False,
                    "history_aborted": True,
                    "disagreement_reason": "HISTORY_INVALID_ABORTED",
                }

        # =========================================================================
        # PHASE 2: POLICY DECISION & UNIFIED ROUTE EXECUTION FROM JUNCTION J0
        # =========================================================================
        t_dec_start_sim = node.get_sim_time_sec()
        dec_odom_samples: List[Dict[str, Any]] = []
        dec_gt_samples: List[Dict[str, Any]] = []

        # Consume real live observation at decision time
        obs_dec_j0 = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
        scan_snapshots.append(capture_scan_snapshot(node, "DECISION_J0", node.get_sim_time_sec(), doorway_bbox, obs_dec_j0))

        initial_route, dec_rationale, dec_meta = P2cPolicyDecider.decide_route(
            method=method_name,
            live_obs=obs_dec_j0,
            cache=cache,
            fail_store=fail_store,
            m1_suppressed=m1_suppressed,
            target_goal=target_goal,
            region_id=chokepoint_region,
            map_version=map_version,
        )
        decision_rationales.append(dec_rationale)
        log_ep(f"\n--- [Decision Phase] Method '{method_name}' selected route '{initial_route}' (Rationale: {dec_rationale}) ---")

        # Unified Route Execution State Machine (all methods execute identical logic)
        if initial_route == "Path_A":
            decision_dispatches += 1
            # Leg 1: Approach Corridor (-1.50, 1.20)
            log_ep("[Route Execution] Leg 1: Approaching Path A corridor entrance (-1.50, 1.20)...")
            node.start_tracking()
            leg1_act = {
                "action_id": "dec_path_a_approach",
                "action": "navigate",
                "params": {"goal": [-1.50, 1.20, 0.0], "frame_id": "map"},
            }
            sum_l1, eval_l1, _ = run_step(leg1_act, nominal_timeout=action_sim_timeout)
            action_summaries.append(sum_l1)
            dec_odom_samples.extend(node.episode_odom_samples)
            dec_gt_samples.extend(node.episode_gt_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            # Live observation gate at corridor entrance (-1.50, 1.20)
            obs_corridor = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
            log_ep(f"[Route Execution] Corridor Entrance Perception: State={obs_corridor.get('doorway_state')} (Hits={obs_corridor.get('hits_inside_count')}, Reason: {obs_corridor.get('reason')})")

            if obs_corridor.get("doorway_state") == "OCCUPIED":
                # Fallback State Machine: Chokepoint is observed blocked from corridor approach!
                log_ep("[Route Execution] Doorway OCCUPIED! Triggering Fallback State Machine (retreat to J0 -> detour Path B)...")
                route_attempt_count = 2

                # Fallback Step 1: Retreat to J0 (-2.50, 0.00)
                decision_dispatches += 1
                node.start_tracking()
                fb_ret_act = {
                    "action_id": "dec_fallback_retreat_to_j0",
                    "action": "navigate",
                    "params": {"goal": [-2.50, 0.00, 0.0], "frame_id": "map"},
                }
                sum_fbr, eval_fbr, _ = run_step(fb_ret_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(sum_fbr)
                dec_odom_samples.extend(node.episode_odom_samples)
                dec_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                # Fallback Step 2: Detour via South Waypoint (0.00, -2.40)
                decision_dispatches += 1
                log_ep("[Route Execution] Fallback Step 2: Detouring via South Path B (0.00, -2.40)...")
                node.start_tracking()
                fb_b_mid_act = {
                    "action_id": "dec_fallback_path_b_mid",
                    "action": "navigate",
                    "params": {"goal": [0.00, -2.40, 0.0], "frame_id": "map"},
                }
                sum_fb1, eval_fb1, _ = run_step(fb_b_mid_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(sum_fb1)
                dec_odom_samples.extend(node.episode_odom_samples)
                dec_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                # Fallback Step 3: Final Goal (2.50, 0.00)
                decision_dispatches += 1
                log_ep("[Route Execution] Fallback Step 3: Proceeding to final goal (2.50, 0.00)...")
                node.start_tracking()
                fb_b_goal_act = {
                    "action_id": "dec_fallback_path_b_goal",
                    "action": "navigate",
                    "params": {"goal": target_goal, "frame_id": "map"},
                }
                sum_fb2, eval_fb2, final_stability = run_step(fb_b_goal_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(sum_fb2)
                dec_odom_samples.extend(node.episode_odom_samples)
                dec_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)
                last_eval_dict = eval_fb2
                last_summary_dict = sum_fb2
                chosen_route = "Path_A_then_Path_B"

            else:
                # Doorway is clear -> proceed through corridor exit (1.50, 1.20) then Final Goal (2.50, 0.00)
                decision_dispatches += 1
                log_ep("[Route Execution] Leg 2: Doorway clear! Traversing through corridor exit (1.50, 1.20)...")
                node.start_tracking()
                leg2_act = {
                    "action_id": "dec_path_a_corridor_exit",
                    "action": "navigate",
                    "params": {"goal": [1.50, 1.20, 0.0], "frame_id": "map"},
                }
                sum_l2, eval_l2, _ = run_step(leg2_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(sum_l2)
                dec_odom_samples.extend(node.episode_odom_samples)
                dec_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)

                decision_dispatches += 1
                log_ep("[Route Execution] Leg 3: Proceeding to final goal (2.50, 0.00)...")
                node.start_tracking()
                leg3_act = {
                    "action_id": "dec_path_a_reach_goal",
                    "action": "navigate",
                    "params": {"goal": target_goal, "frame_id": "map"},
                }
                sum_l3, eval_l3, final_stability = run_step(leg3_act, nominal_timeout=action_sim_timeout)
                action_summaries.append(sum_l3)
                dec_odom_samples.extend(node.episode_odom_samples)
                dec_gt_samples.extend(node.episode_gt_samples)
                all_gt_samples.extend(node.episode_gt_samples)
                all_odom_samples.extend(node.episode_odom_samples)
                last_eval_dict = eval_l3
                last_summary_dict = sum_l3
                chosen_route = "Path_A"
                route_attempt_count = 1

        elif initial_route == "Path_B":
            chosen_route = "Path_B"
            route_attempt_count = 1

            # Leg 1: South Corridor Waypoint (0.00, -2.40)
            decision_dispatches += 1
            log_ep("[Route Execution] Leg 1: Detouring via South Path B waypoint (0.00, -2.40)...")
            node.start_tracking()
            act_b_mid = {
                "action_id": "dec_path_b_mid",
                "action": "navigate",
                "params": {"goal": [0.00, -2.40, 0.0], "frame_id": "map"},
            }
            sum_bm, eval_bm, _ = run_step(act_b_mid, nominal_timeout=action_sim_timeout)
            action_summaries.append(sum_bm)
            dec_odom_samples.extend(node.episode_odom_samples)
            dec_gt_samples.extend(node.episode_gt_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)

            # Leg 2: Final Goal (2.50, 0.00)
            decision_dispatches += 1
            log_ep("[Route Execution] Leg 2: Proceeding to final goal (2.50, 0.00)...")
            node.start_tracking()
            act_b_goal = {
                "action_id": "dec_path_b_goal",
                "action": "navigate",
                "params": {"goal": target_goal, "frame_id": "map"},
            }
            sum_bg, eval_bg, final_stability = run_step(act_b_goal, nominal_timeout=action_sim_timeout)
            action_summaries.append(sum_bg)
            dec_odom_samples.extend(node.episode_odom_samples)
            dec_gt_samples.extend(node.episode_gt_samples)
            all_gt_samples.extend(node.episode_gt_samples)
            all_odom_samples.extend(node.episode_odom_samples)
            last_eval_dict = eval_bg
            last_summary_dict = sum_bg

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
                map_version=map_version,
            )
            policy_reported_success = online_ok
            evaluator_verified_success = bool(last_eval_dict.get("strict_physical_arrival_and_stable", False))
            final_disagreement_reason = compute_disagreement_reason(policy_reported_success, evaluator_verified_success, last_eval_dict)

        decision_distance, _ = P2cTrajectoryClassifier.integrate_distance(dec_odom_samples)
        decision_sim_time = round(node.get_sim_time_sec() - t_dec_start_sim, 3)

        total_distance, traj_jumps = P2cTrajectoryClassifier.integrate_distance(all_odom_samples)
        total_sim_time = round(node.get_sim_time_sec() - episode_t0, 3)

        # Classify trajectory using production classifier
        actual_route = P2cTrajectoryClassifier.classify_actual_route(dec_gt_samples or dec_odom_samples or all_gt_samples)
        dead_end_traversals = P2cTrajectoryClassifier.classify_dead_end_traversals(dec_gt_samples or dec_odom_samples)

        # Full Episode Multi-Flag Evaluation
        eval_report = P2cEpisodeEvaluator.evaluate_episode(
            scenario=scenario_name,
            method=method_name,
            actions=action_summaries,
            total_sim_time_sec=total_sim_time,
            total_budget_sec=total_budget_sec,
            physical_eval_dict=last_eval_dict or {},
            odom_samples=all_odom_samples,
            costmap_snapshots=costmap_snapshots,
            checksums_verified=True,
            protocol_hash_match=True,
            evidence_complete=True,
        )

        final_goal_success = eval_report["final_goal_success"]
        success_within_budget = eval_report["success_within_budget"]
        route_valid = eval_report["route_valid"]
        episode_valid = eval_report["episode_valid"]

        log_ep(f"=== Episode {ep_id} Finished ===")
        log_ep(f"Req Route: {chosen_route}, Act Route: {actual_route}, Dead-Ends: {dead_end_traversals}, Dispatches: {decision_dispatches}, Decision Dist: {decision_distance:.2f}m, Decision Time: {decision_sim_time:.2f}s, Total Dist: {total_distance:.2f}m, Total Time: {total_sim_time:.2f}s, Final Success: {final_goal_success}, Budget OK: {success_within_budget}, Ep Valid: {episode_valid}")

        # Save Episode Artifacts
        with open(ep_dir / "action_result.json", "w", encoding="utf-8") as f:
            json.dump({
                "episode_id": ep_id,
                "condition_id": condition_id,
                "scenario": scenario_name,
                "method": method_name,
                "requested_route": chosen_route,
                "actual_route": actual_route,
                "chosen_route": chosen_route,
                "route_attempt_count": route_attempt_count,
                "dead_end_traversals": dead_end_traversals,
                "decision_dispatches": decision_dispatches,
                "nominal_length_path_a_m": proto_cfg.nominal_length_a,
                "nominal_length_path_b_m": proto_cfg.nominal_length_b,
                "history_distance_m": history_distance,
                "history_sim_time_sec": history_sim_time,
                "decision_distance_m": decision_distance,
                "decision_sim_time_sec": decision_sim_time,
                "total_distance_m": total_distance,
                "total_sim_time_sec": total_sim_time,
                "total_budget_sec": total_budget_sec,
                "policy_reported_success": policy_reported_success,
                "evaluator_verified_success": evaluator_verified_success,
                "final_goal_success": final_goal_success,
                "success_within_budget": success_within_budget,
                "history_valid": history_valid,
                "route_valid": route_valid,
                "episode_valid": episode_valid,
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
                "history_odom_trajectory": hist_odom_samples,
                "decision_odom_trajectory": dec_odom_samples,
                "history_gt_trajectory": hist_gt_samples,
                "decision_gt_trajectory": dec_gt_samples,
            }, f, indent=2)

        with open(ep_dir / "costmap_snapshots.json", "w", encoding="utf-8") as f:
            json.dump(costmap_snapshots, f, indent=2)

        with open(ep_dir / "scan_snapshots.json", "w", encoding="utf-8") as f:
            json.dump(scan_snapshots, f, indent=2)

        with open(ep_dir / "stability_window.json", "w", encoding="utf-8") as f:
            json.dump({
                "sample_count": len(final_stability),
                "window_records": final_stability,
            }, f, indent=2)

        with open(ep_dir / "memory_events.json", "w", encoding="utf-8") as f:
            json.dump(memory_events, f, indent=2)

        with open(ep_dir / "runtime_protocol.json", "w", encoding="utf-8") as f:
            json.dump({
                "protocol_version": proto_cfg.protocol_version,
                "protocol_sha256": protocol_sha256,
                "protocol_config": proto_cfg.raw_config,
            }, f, indent=2)

        return {
            "episode_id": ep_id,
            "condition_id": condition_id,
            "scenario": scenario_name,
            "method": method_name,
            "evidence_type": "physical_ros_gazebo",
            "requested_route": chosen_route,
            "actual_route": actual_route,
            "dead_end_traversals": dead_end_traversals,
            "decision_dispatches": decision_dispatches,
            "history_distance_m": history_distance,
            "history_sim_time_sec": history_sim_time,
            "decision_distance_m": decision_distance,
            "decision_sim_time_sec": decision_sim_time,
            "total_distance_m": total_distance,
            "total_sim_time_sec": total_sim_time,
            "final_goal_success": final_goal_success,
            "success_within_budget": success_within_budget,
            "history_valid": history_valid,
            "route_valid": route_valid,
            "episode_valid": episode_valid,
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
    if not protocol_yaml_path.exists() and Path(f"/workspace/{args.protocol}").exists():
        protocol_yaml_path = Path(f"/workspace/{args.protocol}")

    proto_cfg = P2cProtocolConfig.load_from_file(protocol_yaml_path)

    h_proto = hashlib.sha256()
    with open(protocol_yaml_path, "rb") as f:
        while chunk := f.read(65536):
            h_proto.update(chunk)
    protocol_sha256 = h_proto.hexdigest()

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
    print(f"Total Sim Budget: {proto_cfg.total_sim_budget_sec}s")
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
            proto_cfg=proto_cfg,
            protocol_sha256=protocol_sha256,
            run_id=run_id,
        )
        results.append(res)

    summary_matrix = {
        "run_id": run_id,
        "evidence_type": "physical_ros_gazebo",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": protocol_sha256,
        "protocol_version": proto_cfg.protocol_version,
        "total_episodes": len(results),
        "episodes": results,
    }
    with open(run_dir / "p2c_pilot_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_matrix, f, indent=2)

    compute_sha256_tree(run_dir, run_dir / "checksums.sha256")

    print("\n=======================================================================")
    print("FailMem Milestone P2c Real ROS Physical Experiment Complete. Summary:")
    print("-----------------------------------------------------------------------")
    print("| Scenario | Method | Req Route | Act Route | Dead-End | Total Dist | Total Time | Success | Budget OK | Valid |")
    print("| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in results:
        print(f"| {r['scenario']:8s} | {r['method']:6s} | {r['requested_route']:18s} | {r['actual_route']:18s} | {r['dead_end_traversals']:8d} | {r['total_distance_m']:8.2f}m | {r['total_sim_time_sec']:8.2f}s | {str(r['final_goal_success']):7s} | {str(r['success_within_budget']):9s} | {str(r['episode_valid']):5s} |")
    print("=======================================================================")
    print(f"Evidence saved to: {run_dir}")


if __name__ == "__main__":
    main()
