#!/usr/bin/env python3
"""Limited Scenario Feasibility Check Script for Hypothesis H1 (Max 4 Physical Runs).

Evaluates whether two distinct action configurations exhibit reproducible executability
differences in the same unobstructed doorway geometry under authentic Nav2 execution.

Fixed 4-Run Sequence:
1. H1_aligned_run1: Goal [1.50, 1.20, 0.0] (Aligned through corridor axis, expected SUCCEEDED)
2. H1_aligned_run2: Goal [1.50, 1.20, 0.0] (Aligned through corridor axis, expected SUCCEEDED)
3. H1_oblique_run1: Goal [0.50, 0.88, 0.0] (Doorpost inflation boundary, expected ABORTED/TIMEOUT)
4. H1_oblique_run2: Goal [0.50, 0.88, 0.0] (Doorpost inflation boundary, expected ABORTED/TIMEOUT)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from unique_identifier_msgs.msg import UUID as RosUUID

from src.action_dispatcher import ActionDispatcher
from src.action_runtime import EpisodeActionHistoryContext
from src.doorway_evaluator import (
    evaluate_doorway_clearance,
    create_observation_bundle,
    evaluate_observation_bundle,
)
from src.p2c_pipeline import (
    P2cProtocolConfig,
    build_chokepoint_probe_action,
)
from scripts.run_p1c_v3 import (
    P1cV3RunnerNode,
    execute_navigation_action,
    compute_sha256_tree,
    cleanup_simulation_processes,
    kill_process_group,
    await_nav_goal_terminal_result,
)
from scripts.run_p2c_experiment import (
    spawn_simulation_p2c,
    capture_costmap_snapshot,
    acquire_doorway_observation_bundle,
)


def run_single_h1_check(
    run_name: str,
    profile_id: str,
    target_goal: List[float],
    timeout_sec: float,
    output_dir: Path,
    proto_cfg: P2cProtocolConfig,
) -> Dict[str, Any]:
    """Execute a single physical run in Gazebo/Nav2 to check action feasibility."""
    ep_dir = output_dir / run_name
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

    log_ep(f"=== Starting H1 Feasibility Check: {run_name} (Profile: {profile_id}, Goal: {target_goal}) ===")

    spawn_coords = [-2.50, 0.00, 0.0]
    doorway_bbox = proto_cfg.doorway_bbox
    opening_bbox = proto_cfg.opening_bbox
    thresholds = proto_cfg.thresholds

    sim_proc, sim_env = spawn_simulation_p2c(ep_dir, spawn_coords)
    rclpy.init()
    node = P1cV3RunnerNode(f"h1_check_{profile_id}_{uuid.uuid4().hex[:4]}", event_logger=log_ep)

    scan_snapshots: List[Dict[str, Any]] = []
    costmap_snapshots: List[Dict[str, Any]] = []
    action_summaries: List[Dict[str, Any]] = []

    try:
        # 1. Sim clock advance
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
        log_ep("Sensor streams verified.")

        # 3. AMCL Convergence
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

        # 4. Verify Nav2 lifecycle
        t_nav_start = time.monotonic()
        while time.monotonic() - t_nav_start < 20.0:
            st = node.query_lifecycle_state(timeout_sec=0.5)
            if st == "active":
                log_ep("Nav2 bt_navigator is ACTIVE!")
                break
            time.sleep(0.5)

        # Baseline Costmap Snapshot
        cm_base = capture_costmap_snapshot(node, "COSTMAP_BASELINE_J0", node.get_sim_time_sec(), doorway_bbox, opening_bbox)
        costmap_snapshots.append(cm_base)

        # Setup ActionDispatcher with ROS executor and observer
        action_history_ctx = EpisodeActionHistoryContext(max_retries=10, max_retries_per_state=5)
        dispatcher = ActionDispatcher(context=action_history_ctx, run_id="h1_feasibility", episode_id=run_name)
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

        # Navigate to Corridor Entrance [-1.50, 1.20, 0.0]
        log_ep("Step 1: Approaching corridor entrance [-1.50, 1.20, 0.0]...")
        node.start_tracking()
        app_act = {
            "action_id": "h1_approach_corridor",
            "action": "navigate",
            "params": {"goal": [-1.50, 1.20, 0.0], "frame_id": "map", "timeout_sec": 45.0},
        }
        sum_app, eval_app, stab_app = execute_navigation_action(node, dispatcher, app_act, log_ep, thresholds)
        action_summaries.append(sum_app)

        # Verify geometric clearance at corridor entrance
        bundle_ent = acquire_doorway_observation_bundle(node, "H1_CORRIDOR_ENTRANCE", doorway_bbox, opening_bbox, spin_for_fresh_sec=1.0)
        scan_snapshots.append(bundle_ent)
        obs_ent = bundle_ent["perception_result"]
        log_ep(f"Corridor Entrance Perception: State={obs_ent.get('doorway_state')}, Hits={obs_ent.get('hits_inside_count')}, Pass-Through={obs_ent.get('rays_intersecting_count')}, Reason: {obs_ent.get('reason')}")

        cm_ent = capture_costmap_snapshot(node, "COSTMAP_CORRIDOR_ENTRANCE", node.get_sim_time_sec(), doorway_bbox, opening_bbox)
        costmap_snapshots.append(cm_ent)

        # Execute Test Action Profile
        log_ep(f"Step 2: Dispatching test action '{profile_id}' towards target {target_goal} (timeout={timeout_sec}s)...")
        node.start_tracking()
        test_act = {
            "action_id": f"h1_test_{profile_id}",
            "action": "navigate",
            "params": {"goal": target_goal, "frame_id": "map", "timeout_sec": timeout_sec},
        }
        t_test_start = node.get_sim_time_sec()
        sum_test, eval_test, stab_test = execute_navigation_action(node, dispatcher, test_act, log_ep, thresholds)
        t_test_end = node.get_sim_time_sec()
        action_summaries.append(sum_test)

        test_outcome = sum_test.get("execution_outcome", "UNKNOWN")
        term_status = sum_test.get("terminal_status_name", "UNKNOWN")
        term_code = sum_test.get("terminal_status_code", -1)
        deadline_exceeded = sum_test.get("deadline_exceeded", False)
        nav2_autonomous_aborted = (term_status == "ABORTED" and not deadline_exceeded)
        timeout_canceled = (term_status in ["CANCELED", "ABORTED"] and deadline_exceeded)

        log_ep(f"Test Action Result: Outcome={test_outcome}, Status={term_status} (code={term_code}), Nav2_Aborted={nav2_autonomous_aborted}, Timeout_Canceled={timeout_canceled}")

        record_result = {
            "run_name": run_name,
            "profile_id": profile_id,
            "target_goal": target_goal,
            "timeout_sec": timeout_sec,
            "doorway_state_before_action": obs_ent.get("doorway_state"),
            "hits_inside_before_action": obs_ent.get("hits_inside_count"),
            "pass_through_rays": obs_ent.get("rays_intersecting_count"),
            "terminal_status_name": term_status,
            "terminal_status_code": term_code,
            "execution_outcome": test_outcome,
            "nav2_autonomous_aborted": nav2_autonomous_aborted,
            "timeout_canceled": timeout_canceled,
            "test_action_duration_sec": round(t_test_end - t_test_start, 2),
            "physical_arrival_verified": bool(eval_test.get("strict_physical_arrival_and_stable", False)),
            "actions": action_summaries,
        }

        with open(ep_dir / "feasibility_result.json", "w", encoding="utf-8") as f:
            json.dump(record_result, f, indent=2)

        with open(ep_dir / "scan_snapshots.json", "w", encoding="utf-8") as f:
            json.dump(scan_snapshots, f, indent=2)

        with open(ep_dir / "costmap_snapshots.json", "w", encoding="utf-8") as f:
            json.dump(costmap_snapshots, f, indent=2)

        with open(ep_dir / "trajectory.json", "w", encoding="utf-8") as f:
            json.dump({
                "odom_trajectory": node.episode_odom_samples,
                "gt_trajectory": node.episode_gt_samples,
            }, f, indent=2)

        return record_result

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
    parser = argparse.ArgumentParser(description="H1 Scenario Feasibility Check (Max 4 Runs)")
    parser.add_argument("--protocol", default="configs/p2c_pilot_protocol.yaml", help="Path to protocol YAML")
    parser.add_argument("--output-dir", default="reports/evidence/p2d_h1_feasibility", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    proto_cfg = P2cProtocolConfig.load_from_file(Path(args.protocol))

    # Pre-defined 4-run matrix (strict budget, zero tuning)
    planned_runs = [
        {"run_name": "H1_aligned_run1", "profile_id": "act_aligned", "target_goal": [1.50, 1.20, 0.0], "timeout": 15.0},
        {"run_name": "H1_aligned_run2", "profile_id": "act_aligned", "target_goal": [1.50, 1.20, 0.0], "timeout": 15.0},
        {"run_name": "H1_oblique_run1", "profile_id": "act_oblique", "target_goal": [0.50, 0.88, 0.0], "timeout": 15.0},
        {"run_name": "H1_oblique_run2", "profile_id": "act_oblique", "target_goal": [0.50, 0.88, 0.0], "timeout": 15.0},
    ]

    print("=======================================================================")
    print("Starting H1 Limited Scenario Feasibility Check (Max 4 Runs)")
    print(f"Output Directory: {output_dir}")
    print("=======================================================================")

    results: List[Dict[str, Any]] = []
    for r_plan in planned_runs:
        res = run_single_h1_check(
            run_name=r_plan["run_name"],
            profile_id=r_plan["profile_id"],
            target_goal=r_plan["target_goal"],
            timeout_sec=r_plan["timeout"],
            output_dir=output_dir,
            proto_cfg=proto_cfg,
        )
        results.append(res)

    summary_file = output_dir / "h1_feasibility_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_runs": len(results),
            "results": results,
        }, f, indent=2)

    compute_sha256_tree(output_dir, output_dir / "checksums.sha256")

    # Evaluate Go / No-Go
    aligned_successes = [r for r in results if r["profile_id"] == "act_aligned" and r["terminal_status_name"] == "SUCCEEDED"]
    oblique_failures = [r for r in results if r["profile_id"] == "act_oblique" and r["terminal_status_name"] in ["ABORTED", "CANCELED"]]

    go_condition = (len(aligned_successes) == 2 and len(oblique_failures) == 2)
    verdict = "GO (Preliminary Scenario Usable)" if go_condition else "NO-GO (Scenario Not Established - 本场景未建立)"

    print("\n=======================================================================")
    print(f"H1 Feasibility Check Summary: {verdict}")
    print("-----------------------------------------------------------------------")
    print("| Run Name | Profile ID | Target Goal | Doorway State | Terminal Status | Outcome | Nav2 Aborted | Timeout Canceled | Arrival OK |")
    print("| :--- | :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: |")
    for r in results:
        print(f"| {r['run_name']:17s} | {r['profile_id']:12s} | {str(r['target_goal']):16s} | {r['doorway_state_before_action']:7s} | {r['terminal_status_name']:15s} | {r['execution_outcome']:15s} | {str(r['nav2_autonomous_aborted']):12s} | {str(r['timeout_canceled']):16s} | {str(r['physical_arrival_verified']):10s} |")
    print("=======================================================================\n")


if __name__ == "__main__":
    main()
