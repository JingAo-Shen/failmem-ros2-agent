#!/usr/bin/env python3
"""FailMem Milestone P2a Experiment Runner: Minimal Failure Memory Mechanism Verification.

Evaluates deterministic memory policies on the dual-room single-doorway chokepoint arena:
- Policies:
  * M0 (No Memory): Always permits repeat navigation dispatches.
  * M1 (Persistent Memory): Permanently suppresses repeat dispatches to failed goals/regions.
  * M2 (Conditional Memory): Suppresses repeat dispatches while doorway is blocked,
                            invalidates memory upon verified clearance (doorway_state == FREE),
                            verifies recovery upon confirmed arrival.

- Sequences:
  * S1 (Continuous Blockage): Obstacle remains in doorway for entire episode.
  * S2 (Timed Clearance at t=25s): Obstacle spawned at t=0, cleared at t=25s sim time.

- Formal Suite: 3 policies x 2 sequences x 3 runs = 18 formal episodes.
- Diagnostic / Smoke Mode: 3 policies x 2 sequences x 1 run = 6 episodes.
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

# Ensure repository root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from lifecycle_msgs.srv import GetState
from unique_identifier_msgs.msg import UUID as RosUUID

from src.action_dispatcher import ActionDispatcher
from src.action_runtime import EpisodeActionHistoryContext
from src.scoring_evaluator import load_scoring_rules
from src.coordinate_alignment import verify_world_map_alignment
from src.failure_memory import (
    MemoryState,
    FailureMemoryEntry,
    FailureMemoryStore,
    FailureMemoryPolicy,
    M0NoMemoryPolicy,
    M1PersistentMemoryPolicy,
    M2ConditionalMemoryPolicy,
)
from scripts.run_p1c_v3 import (
    P1cV3RunnerNode,
    spawn_simulation,
    execute_navigation_action,
    compute_sha256_tree,
    cleanup_simulation_processes,
    kill_process_group,
)


def run_episode(
    condition_id: str,
    policy_name: str,
    sequence_name: str,
    ep_num: int,
    run_dir: Path,
    protocol_config: Dict[str, Any],
    thresholds: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """Execute a single formal P2a episode for the given policy and environment sequence."""
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

    log_ep(f"=== Starting Episode {ep_id} ({condition_id} #{ep_num}) ===")
    log_ep(f"Policy: {policy_name}, Sequence: {sequence_name}")

    spawn_cfg = protocol_config["environment"]["spawn_pose"]
    spawn_coords = [float(spawn_cfg["x"]), float(spawn_cfg["y"]), float(spawn_cfg.get("yaw", 0.0))]
    goal_cfg = protocol_config["navigation_task"]["goal_pose"]
    target_goal = [float(goal_cfg["x"]), float(goal_cfg["y"]), float(goal_cfg.get("yaw", 0.0))]
    target_region = str(protocol_config["navigation_task"].get("target_region", "room2_corridor_chokepoint"))
    sim_timeout = float(protocol_config["navigation_task"]["action_sim_timeout_sec"])
    wall_watchdog = float(protocol_config["navigation_task"]["action_wall_watchdog_sec"])
    max_retries = int(protocol_config["navigation_task"].get("max_retries_per_episode", 5))

    doorway_bbox_dict = protocol_config["obstacle_channel"].get("doorway_bbox", {"x_min": -0.30, "x_max": 0.30, "y_min": -0.35, "y_max": 0.35})
    doorway_bbox = (
        float(doorway_bbox_dict["x_min"]),
        float(doorway_bbox_dict["x_max"]),
        float(doorway_bbox_dict["y_min"]),
        float(doorway_bbox_dict["y_max"]),
    )

    # Launch isolated simulation
    sim_proc, sim_env = spawn_simulation(ep_dir, spawn_coords)
    rclpy.init()
    node = P1cV3RunnerNode(f"p2a_{condition_id}_{ep_num}_{uuid.uuid4().hex[:4]}", event_logger=log_ep)

    # Initialize policy
    if policy_name == "M0":
        policy: FailureMemoryPolicy = M0NoMemoryPolicy()
    elif policy_name == "M1":
        policy = M1PersistentMemoryPolicy(tolerance_m=0.50)
    elif policy_name == "M2":
        policy = M2ConditionalMemoryPolicy(tolerance_m=0.50)
    else:
        raise ValueError(f"Unknown policy: {policy_name}")

    memory_events: List[Dict[str, Any]] = []
    doorway_perception_records: List[Dict[str, Any]] = []
    action_summaries: List[Dict[str, Any]] = []
    task_success = False
    invalidation_verified = False
    recovery_verified = False
    dispatches_attempted = 0
    redundant_retries_count = 0
    obstacle_spawned = False
    obstacle_deleted = False

    try:
        # Wait for simulation clock to advance
        t0_sim = node.get_sim_time_sec()
        t0_wall = time.monotonic()
        while (node.get_sim_time_sec() - t0_sim < 1.0) and (time.monotonic() - t0_wall < 30.0):
            rclpy.spin_once(node, timeout_sec=0.1)
            time.sleep(0.05)
        log_ep(f"Sim clock advanced: {t0_sim:.2f}s -> {node.get_sim_time_sec():.2f}s")

        # Wait for sensor streams
        t_sensor_start = time.monotonic()
        while time.monotonic() - t_sensor_start < 25.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_odom_record and node.latest_gt_record and node.latest_scan_record and node.latest_costmap_record:
                break
            time.sleep(0.05)
        log_ep(f"Sensors streaming: odom={node.latest_odom_record['x'] if node.latest_odom_record else 'None'}, scan={node.latest_scan_record['total_count'] if node.latest_scan_record else 'None'} rays, costmap={node.latest_costmap_record['width'] if node.latest_costmap_record else 'None'}")

        # Initialize AMCL pose strictly at spawn
        node.initialize_amcl_pose(spawn_coords)
        t_amcl_start = time.monotonic()
        while time.monotonic() - t_amcl_start < 25.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_amcl_record is not None:
                delta = math.hypot(node.latest_amcl_record["x"] - spawn_coords[0], node.latest_amcl_record["y"] - spawn_coords[1])
                if delta < 0.35:
                    log_ep(f"AMCL pose converged at x={node.latest_amcl_record['x']:.2f}, y={node.latest_amcl_record['y']:.2f} (delta={delta:.2f}m)")
                    break
            time.sleep(0.1)

        # Verify Nav2 bt_navigator lifecycle
        t_nav_start = time.monotonic()
        while time.monotonic() - t_nav_start < 20.0:
            st = node.query_lifecycle_state(timeout_sec=0.5)
            if st == "active":
                log_ep("Nav2 bt_navigator is verified ACTIVE!")
                break
            time.sleep(0.5)

        # Always spawn obstacle at t=0 for S1 and S2
        obs_cfg = protocol_config["obstacle_channel"]
        obs_name = str(obs_cfg.get("entity_name", "corridor_blockage_box"))
        obs_sdf = str(obs_cfg.get("obstacle_sdf", "configs/chokepoint_box.sdf"))
        obs_x = float(obs_cfg["pose"]["x"])
        obs_y = float(obs_cfg["pose"]["y"])
        obs_z = float(obs_cfg["pose"].get("z", 0.30))

        log_ep(f"Spawning obstacle '{obs_name}' at ({obs_x}, {obs_y}, {obs_z})...")
        spawn_ok = node.spawn_obstacle(obs_name, obs_sdf, obs_x, obs_y, obs_z)
        if spawn_ok:
            obstacle_spawned = True
            log_ep("Obstacle spawn confirmed in Gazebo")

        # Set up ActionDispatcher
        action_history_ctx = EpisodeActionHistoryContext(max_retries=5, max_retries_per_state=2)
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

        # -------------------------------------------------------------
        # Main Agent Execution Loop with Memory Gate & Environment Timeline
        # -------------------------------------------------------------
        step_idx = 0
        consecutive_suppressions = 0

        while step_idx < max_retries:
            step_idx += 1
            sim_now = node.get_sim_time_sec()
            log_ep(f"--- [Step {step_idx}] Sim Time: {sim_now:.2f}s ---")

            # Environment Timeline for Sequence S2 (Timed Clearance)
            if sequence_name == "S2" and not obstacle_deleted:
                # In S2, obstacle is cleared after initial attempt or at t >= 25.0s
                if step_idx > 1 or sim_now >= 25.0:
                    log_ep(f"[S2 Timeline] Triggering obstacle removal at sim_time={sim_now:.2f}s")
                    del_ok = node.delete_obstacle(obs_name)
                    if del_ok:
                        obstacle_deleted = True
                        log_ep("[S2 Timeline] Obstacle deleted from Gazebo. Waiting for natural laser raytrace...")
                        # Spin to let natural laser scans clear the costmap
                        t_clear_wait = time.monotonic()
                        while time.monotonic() - t_clear_wait < 3.0:
                            rclpy.spin_once(node, timeout_sec=0.05)
                            time.sleep(0.05)

            # Step 1: Physical Observation & Doorway Perception
            node.request_nomotion_amcl_update(timeout_sec=1.5)
            obs_dict = dispatcher.dispatch({
                "action": "observe",
                "action_id": f"{ep_id}_obs_step{step_idx}",
                "params": {"doorway_bbox": list(doorway_bbox)},
            })
            doorway_eval = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)
            doorway_perception_records.append({
                "step": step_idx,
                "timestamp_sim": node.get_sim_time_sec(),
                "evaluation": doorway_eval,
            })
            log_ep(f"Step {step_idx} Doorway Perception: state={doorway_eval['doorway_state']}, pass_through={doorway_eval.get('pass_through_count', 0)}, hits={doorway_eval.get('points_count', 0)}")

            # Update Policy with Observation
            policy.on_observation_update(doorway_eval, node.get_sim_time_sec())
            if isinstance(policy, M2ConditionalMemoryPolicy):
                store_summary = policy.store.get_summary()
                if store_summary["invalidated_count"] > 0:
                    invalidation_verified = True

            # Step 2: Check Policy Memory Gate for Navigation Dispatch
            allowed, gate_reason = policy.check_dispatch_allowed(target_goal, target_region, node.get_sim_time_sec())
            mem_event = {
                "step": step_idx,
                "timestamp_sim": node.get_sim_time_sec(),
                "event_type": "DISPATCH_GATE_CHECK",
                "allowed": allowed,
                "reason": gate_reason,
                "policy_state": policy.export_state(),
            }
            memory_events.append(mem_event)
            log_ep(f"Step {step_idx} Dispatch Gate: allowed={allowed}, reason='{gate_reason}'")

            if not allowed:
                # Dispatch suppressed by memory policy
                consecutive_suppressions += 1
                log_ep(f"Step {step_idx}: Navigation dispatch SUPPRESSED by policy ({gate_reason})")
                
                # In S1, once memory suppresses, there is no obstacle change expected -> verify suppression and terminate
                if sequence_name == "S1":
                    log_ep(f"Sequence S1 continuous blockage: suppression verified ({consecutive_suppressions} consecutive). Ending episode.")
                    break
                
                # In S2, allow multiple observation cycles for obstacle clearance and raytracing
                if sequence_name == "S2":
                    if consecutive_suppressions >= 4:
                        log_ep(f"Sequence S2: multiple suppressions ({consecutive_suppressions}) without clearance change. Ending episode.")
                        break
                    # Wait briefly for environment timeline / raytracing
                    t_wait = time.monotonic()
                    while time.monotonic() - t_wait < 2.5:
                        rclpy.spin_once(node, timeout_sec=0.1)
                        time.sleep(0.1)
                continue

            consecutive_suppressions = 0

            # Dispatch allowed by policy -> Execute Navigation Action
            dispatches_attempted += 1
            if dispatches_attempted > 1 and doorway_eval.get("doorway_state") == "OCCUPIED":
                redundant_retries_count += 1
                log_ep(f"[REDUNDANT RETRY] Policy {policy_name} dispatched repeat navigation into OCCUPIED doorway!")

            nav_action = {
                "action": "navigate",
                "action_id": f"{ep_id}_nav_step{step_idx}",
                "params": {
                    "goal": target_goal,
                    "frame_id": "map",
                    "timeout_sec": sim_timeout,
                },
            }

            step_summary, eval_dict, stability_records = execute_navigation_action(
                node=node,
                dispatcher=dispatcher,
                action_dict=nav_action,
                logger=log_ep,
                thresholds=thresholds,
            )
            action_summaries.append(step_summary)

            is_arrival = eval_dict.get("strict_physical_arrival_and_stable", False)
            exec_outcome = step_summary["execution_outcome"]
            log_ep(f"Step {step_idx} Nav Result: outcome={exec_outcome}, arrival={is_arrival}, dist_to_goal={eval_dict.get('final_geometric_errors', {}).get('gt_position_error_m', 99.0):.4f}m")

            if exec_outcome == "BUDGET_SUCCESS" and is_arrival:
                # Navigation Succeeded!
                task_success = True
                policy.on_navigation_success(target_goal, target_region, eval_dict, node.get_sim_time_sec())
                if isinstance(policy, M2ConditionalMemoryPolicy):
                    store_summary = policy.store.get_summary()
                    if store_summary["recovery_verified_count"] > 0:
                        recovery_verified = True
                log_ep(f"Goal arrived and stable in Step {step_idx}! Task Success confirmed.")
                break
            else:
                # Navigation Failed / Aborted / Blocked
                node.request_nomotion_amcl_update(timeout_sec=1.5)
                post_fail_doorway = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox)
                policy.on_navigation_failure(
                    target_goal=target_goal,
                    target_region=target_region,
                    failure_reason=exec_outcome,
                    sim_time=node.get_sim_time_sec(),
                    perception_evidence=post_fail_doorway,
                )
                mem_event_fail = {
                    "step": step_idx,
                    "timestamp_sim": node.get_sim_time_sec(),
                    "event_type": "FAILURE_RECORDED",
                    "failure_reason": exec_outcome,
                    "policy_state": policy.export_state(),
                }
                memory_events.append(mem_event_fail)
                log_ep(f"Failure recorded in policy: {policy_name}")

    except Exception as e:
        log_ep(f"[ERROR] Exception during episode execution: {e}")
        import traceback
        log_ep(traceback.format_exc())

    finally:
        # Save episode artifacts
        node.destroy_node()
        rclpy.shutdown()
        kill_process_group(sim_proc.pid)
        sim_proc.wait()
        cleanup_simulation_processes()

    # Determine Mechanism Verification Status
    mechanism_verified = False
    if sequence_name == "S1":
        if policy_name == "M0":
            # M0 on S1: Expected to blindly retry until retries/budget exhausted
            mechanism_verified = (task_success is False and dispatches_attempted > 1)
        elif policy_name in ("M1", "M2"):
            # M1 & M2 on S1: Expected to block redundant retries (dispatches_attempted == 1, redundant_retries == 0)
            mechanism_verified = (task_success is False and dispatches_attempted == 1 and redundant_retries_count == 0)
    elif sequence_name == "S2":
        if policy_name == "M0":
            # M0 on S2: Succeeded by blind retry
            mechanism_verified = (task_success is True and dispatches_attempted >= 2)
        elif policy_name == "M1":
            # M1 on S2: Deadlocked due to persistent block (dispatches_attempted == 1, task_success == False)
            mechanism_verified = (task_success is False and dispatches_attempted == 1)
        elif policy_name == "M2":
            # M2 on S2: Succeeded via verified invalidation and recovery
            mechanism_verified = (task_success is True and invalidation_verified is True and recovery_verified is True)

    ep_summary = {
        "episode_id": ep_id,
        "condition_id": condition_id,
        "policy_name": policy_name,
        "sequence_name": sequence_name,
        "task_success": task_success,
        "mechanism_verified": mechanism_verified,
        "dispatches_attempted": dispatches_attempted,
        "redundant_retries_count": redundant_retries_count,
        "invalidation_verified": invalidation_verified,
        "recovery_verified": recovery_verified,
        "obstacle_spawned": obstacle_spawned,
        "obstacle_deleted": obstacle_deleted,
        "policy_final_state": policy.export_state(),
        "action_summaries": action_summaries,
    }

    with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
        json.dump(ep_summary, f, indent=2)
    with open(ep_dir / "memory_events.json", "w", encoding="utf-8") as f:
        json.dump(memory_events, f, indent=2)
    with open(ep_dir / "doorway_perception.json", "w", encoding="utf-8") as f:
        json.dump(doorway_perception_records, f, indent=2)

    log_ep(f"=== Episode {ep_id} Complete: task_success={task_success}, mechanism_verified={mechanism_verified}, dispatches={dispatches_attempted} ===")
    events_log.close()
    compute_sha256_tree(ep_dir, ep_dir / "checksums.sha256")
    return ep_summary


def main():
    parser = argparse.ArgumentParser(description="FailMem Milestone P2a Experiment Runner")
    parser.add_argument("--protocol", default="configs/p2a_memory_protocol.yaml", help="Path to protocol YAML")
    parser.add_argument("--smoke", "--diagnostic", dest="smoke", action="store_true", help="Run in smoke/diagnostic mode (1 episode per condition)")
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
    run_prefix = "p2a_smoke" if args.smoke else "p2a"
    run_id = f"{run_prefix}_{timestamp_str}_{rand_suffix}"

    evidence_base = Path("/workspace/reports/evidence/p2a") if Path("/workspace").exists() else Path("reports/evidence/p2a")
    if args.smoke:
        evidence_base = Path("/workspace/reports/evidence/p2a_smoke") if Path("/workspace").exists() else Path("reports/evidence/p2a_smoke")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=======================================================================")
    print(f"FailMem P2a Memory Mechanism Verification Runner: {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"Protocol: {protocol_yaml_path} (SHA256: {protocol_sha256})")
    print(f"Mode: {'SMOKE (1 ep/cond, 6 total)' if args.smoke else 'FORMAL (3 eps/cond, 18 total)'}")
    print("=======================================================================")

    # World coordinate alignment verification
    coord_proof = verify_world_map_alignment(
        map_yaml_path="configs/chokepoint_world.yaml",
        map_pgm_path="configs/chokepoint_world.pgm",
        world_model_path="configs/chokepoint_world.model",
        sdf_model_path="configs/chokepoint_world.model",
    )
    with open(run_dir / "coordinate_alignment_proof.json", "w", encoding="utf-8") as f:
        json.dump(coord_proof, f, indent=2)

    runtime_config = {
        "run_id": run_id,
        "protocol_sha256": protocol_sha256,
        "protocol_version": protocol_config.get("protocol_version", "1.0"),
        "smoke_mode": args.smoke,
        "protocol": protocol_config,
    }
    with open(run_dir / "runtime_config.json", "w", encoding="utf-8") as f:
        json.dump(runtime_config, f, indent=2)

    conditions = [
        {"cond_id": "M0_S1", "policy": "M0", "sequence": "S1"},
        {"cond_id": "M0_S2", "policy": "M0", "sequence": "S2"},
        {"cond_id": "M1_S1", "policy": "M1", "sequence": "S1"},
        {"cond_id": "M1_S2", "policy": "M1", "sequence": "S2"},
        {"cond_id": "M2_S1", "policy": "M2", "sequence": "S1"},
        {"cond_id": "M2_S2", "policy": "M2", "sequence": "S2"},
    ]

    episodes_per_cond = 1 if args.smoke else 3
    results: List[Dict[str, Any]] = []

    for cond in conditions:
        for ep_i in range(1, episodes_per_cond + 1):
            ep_res = run_episode(
                condition_id=cond["cond_id"],
                policy_name=cond["policy"],
                sequence_name=cond["sequence"],
                ep_num=ep_i,
                run_dir=run_dir,
                protocol_config=protocol_config,
                thresholds=thresholds,
                run_id=run_id,
            )
            results.append(ep_res)

    # Compile Summary Matrix
    summary_matrix = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": protocol_sha256,
        "smoke_mode": args.smoke,
        "total_episodes": len(results),
        "conditions_evaluated": [c["cond_id"] for c in conditions],
        "episodes": results,
    }
    with open(run_dir / "p2a_summary_matrix.json", "w", encoding="utf-8") as f:
        json.dump(summary_matrix, f, indent=2)

    compute_sha256_tree(run_dir, run_dir / "checksums.sha256")

    print("\n=======================================================================")
    print("P2a Experiment Suite Complete. Summary:")
    print("-----------------------------------------------------------------------")
    for r in results:
        print(f"[{r['episode_id']}] Task OK: {r['task_success']}, Mech OK: {r['mechanism_verified']}, Dispatches: {r['dispatches_attempted']}, Redundant Retries: {r['redundant_retries_count']}")
    print("=======================================================================")
    print(f"Evidence saved to: {run_dir}")


if __name__ == "__main__":
    main()
