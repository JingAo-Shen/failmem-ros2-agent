#!/usr/bin/env python3
"""FailMem Milestone P2a-v3 Experiment Runner: Deterministic Failure Memory Verification Suite.

Evaluates deterministic memory policies on the dual-room single-doorway chokepoint arena:
- Policies:
  * M0 (No Memory): Always permits repeat navigation dispatches.
  * M1 (Persistent Memory): Permanently suppresses repeat dispatches to failed goals/regions.
  * M2 (Conditional Memory): Suppresses repeat dispatches while doorway is blocked,
                            invalidates memory upon verified clearance (doorway_state == FREE),
                            verifies recovery upon confirmed arrival.

- Sequences:
  * S1 (Continuous Blockage): Obstacle remains in doorway for entire episode.
  * S2 (Timed Clearance at elapsed_sim=25s): Obstacle spawned at t=0, cleared at elapsed_sim=25s by concurrent controller.

- Decoupled Online Control & Evaluation:
  * Online termination & policy state transitions use ONLY public Nav2/AMCL feedback.
  * Ground Truth is strictly isolated to offline evaluator scoring.
  * Computes policy_reported_success, evaluator_verified_success, and disagreement_reason.

- Strict Budget & Watchdogs:
  * Absolute simulation deadline (75.0s sim time) strictly enforced across all phases.
  * Per-attempt artifacts saved in attempt_1/, attempt_2/ ... for standalone replay.

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
from src.scoring_evaluator import (
    load_scoring_rules,
    compute_disagreement_reason,
    normalize_angle,
    is_finite_number,
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
    spawn_simulation,
    execute_navigation_action,
    compute_sha256_tree,
    cleanup_simulation_processes,
    kill_process_group,
)


class EnvironmentTimelineController:
    """Independent concurrent environment controller managing obstacle timelines.
    
    Operates completely decoupled from policy state and navigation action status
    using a dedicated ROS node and SingleThreadedExecutor.
    """

    def __init__(
        self,
        sequence_name: str,
        obstacle_name: str,
        clear_target_elapsed_sec: Optional[float] = 25.0,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.sequence_name = sequence_name
        self.obstacle_name = obstacle_name
        self.clear_target_elapsed_sec = clear_target_elapsed_sec if sequence_name == "S2" else None
        self.logger = logger or print

        self.episode_t0: Optional[float] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.latest_sim_time: Optional[float] = None

        self.planned_removal_elapsed_sec = self.clear_target_elapsed_sec
        self.removal_requested = False
        self.service_call_sim_time: Optional[float] = None
        self.service_call_elapsed_sim: Optional[float] = None
        self.service_completed_sim_time: Optional[float] = None
        self.service_completed_elapsed_sim: Optional[float] = None
        self.model_states_confirmed_disappeared_sim_time: Optional[float] = None
        self.model_states_confirmed_disappeared_elapsed_sim: Optional[float] = None
        self.scheduling_error_sec: Optional[float] = None
        self.deletion_success: bool = False
        self.latest_model_names: List[str] = []

    def start(self, episode_t0: float):
        self.episode_t0 = episode_t0
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)

    def _run_loop(self):
        from rosgraph_msgs.msg import Clock
        from gazebo_msgs.msg import ModelStates
        from gazebo_msgs.srv import DeleteEntity
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.parameter import Parameter
        from rclpy.qos import qos_profile_sensor_data

        env_node = rclpy.create_node(
            f"env_timeline_{uuid.uuid4().hex[:6]}",
            parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)],
        )
        executor = SingleThreadedExecutor()
        executor.add_node(env_node)

        def _clock_cb(msg: Clock):
            self.latest_sim_time = msg.clock.sec + msg.clock.nanosec * 1e-9

        def _model_states_cb(msg: ModelStates):
            self.latest_model_names = list(msg.name)

        clock_sub = env_node.create_subscription(Clock, "/clock", _clock_cb, qos_profile_sensor_data)
        model_sub = env_node.create_subscription(ModelStates, "/gazebo/model_states", _model_states_cb, qos_profile_sensor_data)
        del_client = env_node.create_client(DeleteEntity, "/delete_entity")

        try:
            while self.running:
                executor.spin_once(timeout_sec=0.04)
                sim_now = env_node.get_clock().now().nanoseconds * 1e-9
                if sim_now > 0.0:
                    self.latest_sim_time = sim_now

                if (
                    self.sequence_name == "S2"
                    and not self.removal_requested
                    and self.episode_t0 is not None
                    and self.latest_sim_time is not None
                ):
                    elapsed_sim = self.latest_sim_time - self.episode_t0
                    if elapsed_sim >= (self.clear_target_elapsed_sec or 25.0):
                        self.removal_requested = True
                        self.service_call_sim_time = self.latest_sim_time
                        self.service_call_elapsed_sim = round(elapsed_sim, 4)
                        self.scheduling_error_sec = round(self.service_call_elapsed_sim - (self.clear_target_elapsed_sec or 25.0), 4)
                        self.logger(f"[Environment Timeline] Triggering S2 obstacle removal service call at elapsed_sim={self.service_call_elapsed_sim:.3f}s (scheduling_error={self.scheduling_error_sec:+.3f}s)")

                        if del_client.wait_for_service(timeout_sec=5.0):
                            req = DeleteEntity.Request()
                            req.name = self.obstacle_name
                            future = del_client.call_async(req)

                            t_del_wait = time.monotonic()
                            while self.running and not future.done() and (time.monotonic() - t_del_wait < 5.0):
                                executor.spin_once(timeout_sec=0.04)

                            if future.done() and future.result() and future.result().success:
                                self.deletion_success = True
                                self.service_completed_sim_time = env_node.get_clock().now().nanoseconds * 1e-9
                                self.service_completed_elapsed_sim = round(self.service_completed_sim_time - self.episode_t0, 4)
                                self.logger(f"[Environment Timeline] Obstacle '{self.obstacle_name}' delete_entity service succeeded at elapsed_sim={self.service_completed_elapsed_sim:.3f}s")

                                # Check ModelStates confirmation
                                t_ms_wait = time.monotonic()
                                while self.running and (self.obstacle_name in self.latest_model_names) and (time.monotonic() - t_ms_wait < 5.0):
                                    executor.spin_once(timeout_sec=0.04)
                                    time.sleep(0.02)

                                if self.obstacle_name not in self.latest_model_names:
                                    self.model_states_confirmed_disappeared_sim_time = env_node.get_clock().now().nanoseconds * 1e-9
                                    self.model_states_confirmed_disappeared_elapsed_sim = round(self.model_states_confirmed_disappeared_sim_time - self.episode_t0, 4)
                                    self.logger(f"[Environment Timeline] Obstacle '{self.obstacle_name}' confirmed absent from ModelStates at elapsed_sim={self.model_states_confirmed_disappeared_elapsed_sim:.3f}s")
                                else:
                                    self.model_states_confirmed_disappeared_sim_time = self.service_completed_sim_time
                                    self.model_states_confirmed_disappeared_elapsed_sim = self.service_completed_elapsed_sim
                            else:
                                self.logger(f"[Environment Timeline ERROR] Obstacle '{self.obstacle_name}' deletion service failed or timed out!")
                        else:
                            self.logger(f"[Environment Timeline ERROR] /delete_entity service unavailable!")
                time.sleep(0.02)
        finally:
            env_node.destroy_node()

    def export_summary(self) -> Dict[str, Any]:
        return {
            "sequence_name": self.sequence_name,
            "planned_removal_elapsed_sec": self.planned_removal_elapsed_sec,
            "removal_requested": self.removal_requested,
            "service_call_sim_time": self.service_call_sim_time,
            "service_call_elapsed_sim": self.service_call_elapsed_sim,
            "service_completed_sim_time": self.service_completed_sim_time,
            "service_completed_elapsed_sim": self.service_completed_elapsed_sim,
            "model_states_confirmed_disappeared_sim_time": self.model_states_confirmed_disappeared_sim_time,
            "model_states_confirmed_disappeared_elapsed_sim": self.model_states_confirmed_disappeared_elapsed_sim,
            "scheduling_error_sec": self.scheduling_error_sec,
            "deletion_success": self.deletion_success,
        }


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
    """Execute a single formal P2a-v3 episode with decoupled timeline, strict budget, and per-attempt persistence."""
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

    map_version = str(protocol_config["environment"].get("map_version", "chokepoint_world_v1"))
    spawn_cfg = protocol_config["environment"]["spawn_pose"]
    spawn_coords = [float(spawn_cfg["x"]), float(spawn_cfg["y"]), float(spawn_cfg.get("yaw", 0.0))]
    goal_cfg = protocol_config["navigation_task"]["goal_pose"]
    target_goal = [float(goal_cfg["x"]), float(goal_cfg["y"]), float(goal_cfg.get("yaw", 0.0))]
    target_region = str(protocol_config["navigation_task"].get("target_region", "room2_corridor_chokepoint"))
    sim_timeout = float(protocol_config["navigation_task"]["action_sim_timeout_sec"])
    episode_total_sim_budget_sec = float(protocol_config["navigation_task"].get("episode_total_sim_budget_sec", 75.0))
    observation_period_sim_sec = float(protocol_config["navigation_task"].get("observation_period_sim_sec", 2.0))
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
        policy = M1PersistentMemoryPolicy(tolerance_m=float(thresholds.get("position_tolerance_m", 0.30)) + 0.20)
    elif policy_name == "M2":
        policy = M2ConditionalMemoryPolicy(tolerance_m=float(thresholds.get("position_tolerance_m", 0.30)) + 0.20)
    elif policy_name == "M3":
        policy = M3CurrentPerceptionPolicy()
    else:
        raise ValueError(f"Unknown policy: {policy_name}")

    timeline_controller: Optional[EnvironmentTimelineController] = None
    memory_events: List[Dict[str, Any]] = []
    doorway_perception_records: List[Dict[str, Any]] = []
    action_summaries: List[Dict[str, Any]] = []

    policy_reported_success = False
    evaluator_verified_success = False
    final_disagreement_reason: Optional[str] = None
    episode_valid = True
    terminal_reason = "EPISODE_COMPLETED"
    observation_count = 0
    suppression_count = 0
    navigation_attempt_count = 0
    retry_count = 0
    redundant_retries_count = 0
    obstacle_spawned = False
    episode_t0: Optional[float] = None
    abs_sim_deadline: Optional[float] = None

    try:
        # 1. Wait for simulation clock to advance
        t0_sim = node.get_sim_time_sec()
        t0_wall = time.monotonic()
        while (node.get_sim_time_sec() - t0_sim < 1.0) and (time.monotonic() - t0_wall < 30.0):
            rclpy.spin_once(node, timeout_sec=0.1)
            time.sleep(0.05)
        log_ep(f"Sim clock advanced: {t0_sim:.2f}s -> {node.get_sim_time_sec():.2f}s")

        # 2. Wait for sensor streams
        t_sensor_start = time.monotonic()
        while time.monotonic() - t_sensor_start < 25.0:
            rclpy.spin_once(node, timeout_sec=0.1)
            if node.latest_odom_record and node.latest_gt_record and node.latest_scan_record and node.latest_costmap_record:
                break
            time.sleep(0.05)
        log_ep(f"Sensors streaming verified: odom={node.latest_odom_record['x'] if node.latest_odom_record else 'None'}, scan={node.latest_scan_record['total_count'] if node.latest_scan_record else 'None'} rays")

        # 3. Initialize AMCL pose strictly at spawn
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

        # 4. Verify Nav2 bt_navigator lifecycle
        t_nav_start = time.monotonic()
        while time.monotonic() - t_nav_start < 20.0:
            st = node.query_lifecycle_state(timeout_sec=0.5)
            if st == "active":
                log_ep("Nav2 bt_navigator is verified ACTIVE!")
                break
            time.sleep(0.5)

        # 5. Spawn obstacle at t=0 for S1 and S2
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

        # -----------------------------------------------------------------
        # Define Unified Episode t0 after Readiness
        # -----------------------------------------------------------------
        episode_t0 = node.get_sim_time_sec()
        abs_sim_deadline = episode_t0 + episode_total_sim_budget_sec
        log_ep(f"Readiness Complete. Defined episode_t0 = {episode_t0:.3f}s, abs_sim_deadline = {abs_sim_deadline:.3f}s. Starting concurrent EnvironmentTimelineController...")

        # Start Independent Environment Timeline Controller (S1 vs S2)
        timeline_controller = EnvironmentTimelineController(
            sequence_name=sequence_name,
            obstacle_name=obs_name,
            clear_target_elapsed_sec=float(protocol_config["environment_sequences"]["S2"].get("obstacle_clear_elapsed_sim_sec", 25.0)),
            logger=log_ep,
        )
        timeline_controller.start(episode_t0=episode_t0)

        # Set up ActionDispatcher
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

        # -----------------------------------------------------------------
        # Generic Agent Execution Loop (Sequence-Agnostic, Unified Budget)
        # -----------------------------------------------------------------
        while True:
            sim_now = node.get_sim_time_sec()
            elapsed_sim = round(sim_now - episode_t0, 4)

            # Check Unified Episode Total Sim Budget
            if sim_now >= abs_sim_deadline or elapsed_sim >= episode_total_sim_budget_sec:
                log_ep(f"Total episode sim budget reached ({elapsed_sim:.2f}s >= {episode_total_sim_budget_sec:.2f}s). Ending execution loop.")
                terminal_reason = "TOTAL_BUDGET_EXHAUSTED"
                break

            if policy_reported_success:
                terminal_reason = "POLICY_REPORTED_SUCCESS"
                break

            # Step 1: Observation & Physical Perception
            observation_count += 1
            obs_id = f"{ep_id}_obs_{observation_count}"
            node.request_nomotion_amcl_update(timeout_sec=1.5)
            obs_dict = dispatcher.dispatch({
                "action": "observe",
                "action_id": obs_id,
                "params": {"target_id": "doorway"},
            })
            doorway_eval = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
            doorway_perception_records.append({
                "observation_index": observation_count,
                "action_id": obs_id,
                "elapsed_sim_sec": elapsed_sim,
                "sim_time": sim_now,
                "evaluation": doorway_eval,
            })
            log_ep(f"[Obs #{observation_count}] elapsed={elapsed_sim:.2f}s: doorway={doorway_eval.get('doorway_state')} (pass_through={doorway_eval.get('pass_through_count', 0)}, hits={doorway_eval.get('hits_inside_count', 0)})")

            # Update Policy with Observation (No GT Leakage!)
            policy.on_observation_update(
                perception_evidence=doorway_eval,
                sim_time=elapsed_sim,
                evidence_id=obs_id,
                map_version=map_version,
                region_id=target_region,
            )

            # Step 2: Policy Dispatch Gate Check
            allowed, gate_reason, blocked_by_id = policy.check_dispatch_allowed(
                target_goal=target_goal,
                target_region=target_region,
                sim_time=elapsed_sim,
                map_version=map_version,
            )
            mem_event = {
                "observation_index": observation_count,
                "elapsed_sim_sec": elapsed_sim,
                "sim_time": sim_now,
                "event_type": "DISPATCH_GATE_CHECK",
                "allowed": allowed,
                "reason": gate_reason,
                "blocked_by_memory_id": blocked_by_id,
                "policy_state": policy.export_state(),
            }
            memory_events.append(mem_event)

            if not allowed:
                suppression_count += 1
                log_ep(f"[Gate Check #{observation_count}] Dispatch SUPPRESSED by policy ({gate_reason})")
                
                # Fixed cadence sleep (2.0s sim time) while spinning ROS
                t_sim_wait_start = node.get_sim_time_sec()
                while (node.get_sim_time_sec() - t_sim_wait_start < observation_period_sim_sec) and (node.get_sim_time_sec() < abs_sim_deadline):
                    rclpy.spin_once(node, timeout_sec=0.05)
                    time.sleep(0.02)
                continue

            # Dispatch Allowed by Policy
            # Check remaining budget for navigation
            rem_budget = round(abs_sim_deadline - node.get_sim_time_sec(), 4)
            if rem_budget <= 1.0:
                log_ep(f"Remaining budget too low for navigation dispatch ({rem_budget:.2f}s <= 1.0s). Ending loop.")
                terminal_reason = "TOTAL_BUDGET_EXHAUSTED"
                break

            # Check retry quota (1 initial attempt + max_retries retries)
            if navigation_attempt_count > 0 and retry_count >= max_retries:
                log_ep(f"Max retries exhausted ({retry_count} >= {max_retries}). Ending loop.")
                terminal_reason = "MAX_RETRIES_EXHAUSTED"
                break

            navigation_attempt_count += 1
            retry_count = max(0, navigation_attempt_count - 1)
            nav_action_id = f"{ep_id}_nav_attempt{navigation_attempt_count}"

            # If recovering, bind recovery action ID to invalidated memory entry
            bound_memory_id = policy.bind_recovery_action(
                target_goal=target_goal,
                target_region=target_region,
                recovery_action_id=nav_action_id,
                sim_time=elapsed_sim,
                map_version=map_version,
            )

            if navigation_attempt_count > 1 and doorway_eval.get("doorway_state") == "OCCUPIED":
                redundant_retries_count += 1
                log_ep(f"[REDUNDANT RETRY #{redundant_retries_count}] Policy {policy_name} dispatched repeat navigation into OCCUPIED doorway!")

            clamped_nav_timeout = min(sim_timeout, rem_budget)
            nav_action = {
                "action": "navigate",
                "action_id": nav_action_id,
                "params": {
                    "goal": target_goal,
                    "frame_id": "map",
                    "timeout_sec": clamped_nav_timeout,
                },
            }

            log_ep(f"[Nav Attempt #{navigation_attempt_count}] Dispatching action '{nav_action_id}' (timeout={clamped_nav_timeout:.1f}s, rem_budget={rem_budget:.1f}s, bound_memory={bound_memory_id})...")
            step_summary, eval_dict, stability_records = execute_navigation_action(
                node=node,
                dispatcher=dispatcher,
                action_dict=nav_action,
                logger=log_ep,
                thresholds=thresholds,
                abs_sim_deadline=abs_sim_deadline,
            )
            action_summaries.append(step_summary)

            attempt_gt = copy.deepcopy(node.episode_gt_samples)
            attempt_odom = copy.deepcopy(node.episode_odom_samples)
            exec_outcome = step_summary["execution_outcome"]

            # Online Check from Public Whitelisted Feedback (ZERO GT Inspection!)
            odom_rec = node.latest_odom_record
            raw_online_feedback = {
                "attempt_index": navigation_attempt_count,
                "action_id": nav_action_id,
                "nav2_status": step_summary["terminal_status_name"],
                "status_code": step_summary["status_code"],
                "execution_outcome": exec_outcome,
                "deadline_exceeded": step_summary["deadline_exceeded"],
                "amcl_pose": copy.deepcopy(node.latest_amcl_record),
                "halt_velocity": {
                    "linear_v": odom_rec.get("linear_v") if odom_rec else None,
                    "angular_v": odom_rec.get("angular_v") if odom_rec else None,
                },
            }
            online_action_succeeded, online_reasons, online_details = verify_online_arrival(
                target_goal=target_goal,
                online_feedback=raw_online_feedback,
                thresholds=thresholds,
                sim_time=node.get_sim_time_sec(),
                target_region=target_region,
                map_version=map_version,
            )
            online_feedback = {
                **raw_online_feedback,
                "online_action_succeeded": online_action_succeeded,
                "online_verification_details": online_details,
                "online_failure_reasons": online_reasons,
            }

            # Offline Physical Evaluation & Disagreement Scoring (Evaluator Independent)
            eval_arrival = eval_dict.get("strict_physical_arrival_and_stable", False)
            if eval_arrival:
                evaluator_verified_success = True
            disagreement = compute_disagreement_reason(online_action_succeeded, eval_arrival, eval_dict)
            final_disagreement_reason = disagreement

            # Per-attempt directory persistence
            attempt_dir = ep_dir / f"attempt_{navigation_attempt_count}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            with open(attempt_dir / "action_result.json", "w", encoding="utf-8") as f:
                json.dump({
                    "action_id": nav_action_id,
                    "attempt_index": navigation_attempt_count,
                    "target_goal": target_goal,
                    "target_region": target_region,
                    "map_version": map_version,
                    "dispatch_time_sim": round(sim_now, 4),
                    "dispatch_elapsed_sim": elapsed_sim,
                    "timeout_sec": clamped_nav_timeout,
                    "execution_outcome": exec_outcome,
                    "terminal_status_name": step_summary["terminal_status_name"],
                    "status_code": step_summary["status_code"],
                    "deadline_exceeded": step_summary["deadline_exceeded"],
                    "failure_reason": step_summary["failure_reason"],
                    "settled_ok": step_summary["settled_ok"],
                    "safety_intervention": step_summary["safety_intervention"],
                    "online_action_succeeded": online_action_succeeded,
                    "evaluator_verified_success": eval_arrival,
                    "disagreement_reason": disagreement,
                    "evaluation": eval_dict,
                }, f, indent=2)

            with open(attempt_dir / "trajectory.json", "w", encoding="utf-8") as f:
                json.dump({
                    "attempt_index": navigation_attempt_count,
                    "gt_samples_count": len(attempt_gt),
                    "odom_samples_count": len(attempt_odom),
                    "gt_trajectory": attempt_gt,
                    "odom_trajectory": attempt_odom,
                }, f, indent=2)

            with open(attempt_dir / "stability_window.json", "w", encoding="utf-8") as f:
                json.dump({
                    "attempt_index": navigation_attempt_count,
                    "sample_count": len(stability_records),
                    "watchdog_triggered": step_summary["evaluation"]["window_evaluation"]["watchdog_triggered"],
                    "window_records": stability_records,
                }, f, indent=2)

            with open(attempt_dir / "online_feedback.json", "w", encoding="utf-8") as f:
                json.dump(online_feedback, f, indent=2)

            final_geom = eval_dict.get("final_geometric_errors", {})
            log_ep(f"[Nav Attempt #{navigation_attempt_count} Result] online_success={online_action_succeeded}, physical_eval={eval_arrival}, disagreement={disagreement}, gt_dist={final_geom.get('gt_position_error_m', 99.0):.4f}m, amcl_dist={final_geom.get('amcl_position_error_m', 99.0):.4f}m")

            if online_action_succeeded:
                policy_reported_success = True
                policy.on_navigation_success(
                    target_goal=target_goal,
                    target_region=target_region,
                    action_id=nav_action_id,
                    online_feedback=online_feedback,
                    sim_time=round(node.get_sim_time_sec() - episode_t0, 4),
                    map_version=map_version,
                    memory_id=bound_memory_id,
                    thresholds=thresholds,
                )
                log_ep(f"Goal arrived online in Attempt #{navigation_attempt_count}! Ending retry loop.")
                break
            else:
                node.request_nomotion_amcl_update(timeout_sec=1.5)
                post_fail_doorway = node.evaluate_doorway_perception(doorway_bbox=doorway_bbox, spin_for_fresh_sec=0.5)
                post_fail_obs_id = f"{ep_id}_postfail_obs_{navigation_attempt_count}"
                policy.on_navigation_failure(
                    target_goal=target_goal,
                    target_region=target_region,
                    failure_reason=exec_outcome,
                    sim_time=round(node.get_sim_time_sec() - episode_t0, 4),
                    failed_action_id=nav_action_id,
                    failure_evidence_id=post_fail_obs_id,
                    perception_evidence=post_fail_doorway,
                    map_version=map_version,
                )

    except Exception as e:
        episode_valid = False
        terminal_reason = f"EXCEPTION: {str(e)}"
        log_ep(f"[ERROR] Exception during episode execution: {e}")
        import traceback
        log_ep(traceback.format_exc())

    finally:
        if timeline_controller:
            timeline_controller.stop()
        node.destroy_node()
        rclpy.shutdown()
        kill_process_group(sim_proc.pid)
        sim_proc.wait()
        cleanup_simulation_processes()

    timeline_summary = timeline_controller.export_summary() if timeline_controller else {}

    # Determine Invalidation and Recovery Status
    policy_state = policy.export_state()
    invalidation_verified = (
        policy_state.get("invalidated_count", 0) > 0
        or policy_state.get("ever_invalidated_count", 0) > 0
        or any(e.get("invalidation_time") is not None for e in policy_state.get("entries", []))
    )
    policy_reported_recovery = (policy_state.get("recovery_verified_count", 0) > 0)
    evaluator_verified_recovery = (evaluator_verified_success is True and navigation_attempt_count >= 2)
    task_success = evaluator_verified_success

    if final_disagreement_reason is None and action_summaries:
        final_disagreement_reason = compute_disagreement_reason(policy_reported_success, evaluator_verified_success, action_summaries[-1].get("evaluation"))

    # Determine Causal Mechanism Verification Status
    mechanism_verified = False
    if episode_valid:
        if sequence_name == "S1":
            if policy_name == "M0":
                mechanism_verified = (task_success is False and navigation_attempt_count > 1 and redundant_retries_count >= 1)
            elif policy_name in ("M1", "M2"):
                mechanism_verified = (task_success is False and navigation_attempt_count == 1 and redundant_retries_count == 0 and suppression_count >= 1)
            elif policy_name == "M3":
                mechanism_verified = (task_success is False and navigation_attempt_count == 0 and suppression_count >= 1)
        elif sequence_name == "S2":
            if policy_name == "M0":
                mechanism_verified = (task_success is True and navigation_attempt_count >= 2)
            elif policy_name == "M1":
                mechanism_verified = (task_success is False and navigation_attempt_count == 1 and suppression_count >= 1)
            elif policy_name == "M2":
                mechanism_verified = (task_success is True and invalidation_verified is True and policy_reported_recovery is True and evaluator_verified_recovery is True)
            elif policy_name == "M3":
                mechanism_verified = (task_success is True and navigation_attempt_count == 1 and suppression_count >= 1)

    ep_summary = {
        "episode_id": ep_id,
        "condition_id": condition_id,
        "policy_name": policy_name,
        "sequence_name": sequence_name,
        "map_version": map_version,
        "episode_valid": episode_valid,
        "policy_reported_success": policy_reported_success,
        "evaluator_verified_success": evaluator_verified_success,
        "disagreement_reason": final_disagreement_reason,
        "task_success": task_success,
        "mechanism_verified": mechanism_verified,
        "terminal_reason": terminal_reason,
        "observation_count": observation_count,
        "suppression_count": suppression_count,
        "navigation_attempt_count": navigation_attempt_count,
        "retry_count": retry_count,
        "redundant_retries_count": redundant_retries_count,
        "invalidation_verified": invalidation_verified,
        "policy_reported_recovery": policy_reported_recovery,
        "evaluator_verified_recovery": evaluator_verified_recovery,
        "timeline_summary": timeline_summary,
        "policy_final_state": policy_state,
        "action_summaries": action_summaries,
    }

    with open(ep_dir / "episode_summary.json", "w", encoding="utf-8") as f:
        json.dump(ep_summary, f, indent=2)
    with open(ep_dir / "memory_events.json", "w", encoding="utf-8") as f:
        json.dump(memory_events, f, indent=2)
    with open(ep_dir / "doorway_perception.json", "w", encoding="utf-8") as f:
        json.dump(doorway_perception_records, f, indent=2)

    log_ep(f"=== Episode {ep_id} Complete: valid={episode_valid}, policy_ok={policy_reported_success}, eval_ok={evaluator_verified_success}, mech_verified={mechanism_verified}, attempts={navigation_attempt_count}, suppressions={suppression_count}, obs={observation_count} ===")
    events_log.close()
    compute_sha256_tree(ep_dir, ep_dir / "checksums.sha256")
    return ep_summary


def main():
    parser = argparse.ArgumentParser(description="FailMem Milestone P2a-v3 Experiment Runner")
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
    run_prefix = "p2a_v3_smoke" if args.smoke else "p2a_v3"
    run_id = f"{run_prefix}_{timestamp_str}_{rand_suffix}"

    evidence_base = Path("/workspace/reports/evidence/p2a_v3") if Path("/workspace").exists() else Path("reports/evidence/p2a_v3")
    if args.smoke:
        evidence_base = Path("/workspace/reports/evidence/p2a_v3_smoke") if Path("/workspace").exists() else Path("reports/evidence/p2a_v3_smoke")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=======================================================================")
    print(f"FailMem P2a-v3 Memory Mechanism Verification Runner: {run_id}")
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
        "protocol_version": protocol_config.get("protocol_version", "3.0"),
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
    print("P2a-v3 Experiment Suite Complete. Summary:")
    print("-----------------------------------------------------------------------")
    for r in results:
        print(f"[{r['episode_id']}] Valid: {r['episode_valid']}, PolicyOK: {r['policy_reported_success']}, EvalOK: {r['evaluator_verified_success']}, MechOK: {r['mechanism_verified']}, Attempts: {r['navigation_attempt_count']}, Suppressions: {r['suppression_count']}, Obs: {r['observation_count']}, Redundant: {r['redundant_retries_count']}")
    print("=======================================================================")
    print(f"Evidence saved to: {run_dir}")


if __name__ == "__main__":
    main()
