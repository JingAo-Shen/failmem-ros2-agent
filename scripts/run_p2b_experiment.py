#!/usr/bin/env python3
"""FailMem Milestone P2b Experiment Runner: Reactive Perception Control & Failure Memory Evaluation Suite.

Evaluates 4 policies across 2 sequences:
- Policies:
  * M0 (No Memory): Always permits repeat navigation dispatches until budget exhaustion.
  * M1 (Persistent Memory): Permanently suppresses repeat dispatches to failed targets/regions.
  * M2 (Conditional Memory): Suppresses repeat dispatches while doorway is blocked,
                            invalidates memory upon verified clearance (doorway_state == FREE),
                            verifies recovery upon confirmed arrival.
  * M3 (Current Perception Only): Zero failure memory entries, purely reactive dispatch gating
                                  based on instantaneous doorway state (FREE -> permit, OCCUPIED/UNKNOWN -> suppress).

- Sequences:
  * S1 (Continuous Blockage): Obstacle remains in doorway for entire episode.
  * S2 (Timed Clearance at elapsed_sim=25s): Obstacle spawned at t=0, cleared at elapsed_sim=25s by concurrent controller.

- Formal Suite: 4 policies x 2 sequences x 3 runs = 24 formal episodes.
- Diagnostic / Smoke Mode: 4 policies x 2 sequences x 1 run = 8 episodes.
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
from scripts.run_p2a_experiment import EnvironmentTimelineController, run_episode


def main():
    parser = argparse.ArgumentParser(description="FailMem Milestone P2b Experiment Runner")
    parser.add_argument("--protocol", default="configs/p2b_reactive_control_protocol.yaml", help="Path to protocol YAML")
    parser.add_argument("--smoke", "--diagnostic", dest="smoke", action="store_true", help="Run in smoke/diagnostic mode (1 episode per condition)")
    parser.add_argument("--policy", default=None, help="Filter by specific policy (e.g. M3)")
    parser.add_argument("--sequence", default=None, help="Filter by specific sequence (e.g. S1 or S2)")
    parser.add_argument("--condition", default=None, help="Filter by specific condition ID (e.g. M3_S1)")
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
    run_prefix = "p2b_smoke" if args.smoke else "p2b"
    run_id = f"{run_prefix}_{timestamp_str}_{rand_suffix}"

    evidence_base = Path("/workspace/reports/evidence/p2b") if Path("/workspace").exists() else Path("reports/evidence/p2b")
    if args.smoke:
        evidence_base = Path("/workspace/reports/evidence/p2b_smoke") if Path("/workspace").exists() else Path("reports/evidence/p2b_smoke")
    run_dir = evidence_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=======================================================================")
    print(f"FailMem P2b Reactive Perception Control Runner: {run_id}")
    print(f"Evidence Directory: {run_dir}")
    print(f"Protocol: {protocol_yaml_path} (SHA256: {protocol_sha256})")
    print(f"Mode: {'SMOKE (1 ep/cond)' if args.smoke else 'FORMAL (3 eps/cond)'}")
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
        "protocol_version": protocol_config.get("protocol_version", "3.1"),
        "smoke_mode": args.smoke,
        "protocol": protocol_config,
    }
    with open(run_dir / "runtime_config.json", "w", encoding="utf-8") as f:
        json.dump(runtime_config, f, indent=2)

    all_conditions = [
        {"cond_id": "M0_S1", "policy": "M0", "sequence": "S1"},
        {"cond_id": "M0_S2", "policy": "M0", "sequence": "S2"},
        {"cond_id": "M1_S1", "policy": "M1", "sequence": "S1"},
        {"cond_id": "M1_S2", "policy": "M1", "sequence": "S2"},
        {"cond_id": "M2_S1", "policy": "M2", "sequence": "S1"},
        {"cond_id": "M2_S2", "policy": "M2", "sequence": "S2"},
        {"cond_id": "M3_S1", "policy": "M3", "sequence": "S1"},
        {"cond_id": "M3_S2", "policy": "M3", "sequence": "S2"},
    ]

    # Apply filters
    conditions = all_conditions
    if args.condition:
        conditions = [c for c in conditions if c["cond_id"] == args.condition]
    if args.policy:
        conditions = [c for c in conditions if c["policy"] == args.policy]
    if args.sequence:
        conditions = [c for c in conditions if c["sequence"] == args.sequence]

    episodes_per_cond = 1 if args.smoke else int(protocol_config.get("formal_suite", {}).get("episodes_per_condition", 3))
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
    with open(run_dir / "p2b_summary_matrix.json", "w", encoding="utf-8") as f:
        json.dump(summary_matrix, f, indent=2)

    compute_sha256_tree(run_dir, run_dir / "checksums.sha256")

    print("\n=======================================================================")
    print("P2b Experiment Suite Complete. Summary:")
    print("-----------------------------------------------------------------------")
    for r in results:
        print(f"[{r['episode_id']}] Valid: {r['episode_valid']}, PolicyOK: {r['policy_reported_success']}, EvalOK: {r['evaluator_verified_success']}, MechOK: {r['mechanism_verified']}, Attempts: {r['navigation_attempt_count']}, Suppressions: {r['suppression_count']}, Obs: {r['observation_count']}, Redundant: {r['redundant_retries_count']}")
    print("=======================================================================")
    print(f"Evidence saved to: {run_dir}")


if __name__ == "__main__":
    main()
