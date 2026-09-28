# FailMem P1a Review Report: Single-Scene Headless Navigation Smoke Test

- **Stage**: P1a Single-Scene Real Navigation Smoke Test
- **Status**: PASSED (Runtime Navigation Verified; Evidence Packaged)
- **Base Commit (Commit A)**: `6e7c1c2` (`fix(validator): strict action validator, runtime context, csv dictwriter, and probe rescoring`)
- **Review Date**: 2026-09-28
- **Domain Isolation**: `ROS_DOMAIN_ID=42`, `ROS_LOCALHOST_ONLY=1`

---

## 1. Executive Summary & Review Scope

Following research protocol requirements, P1a focuses strictly on establishing end-to-end headless navigation execution in a single fixed simulation environment without mockups, without LLM closed-loop decision making, and without benchmark performance claims.

All 3 independent navigation runs completed with Nav2 `SUCCEEDED` status, confirmed by physical ground truth arrival from Gazebo Classic. The cancellation safety test successfully interrupted active navigation and brought the robot to a complete halt ($v=0.0\,\text{m/s}$).

---

## 2. Environment & Simulation Stack

| Component | Specification / Version | Rationale & Evidence |
| :--- | :--- | :--- |
| **Base Container** | `ros:humble@sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` | Pinned official multi-arch digest for strict reproducibility |
| **OS** | Ubuntu 22.04 LTS (Jammy Jellyfish) | Standard ROS2 Humble tier 1 target |
| **Simulator** | Gazebo Classic 11.10.2 (`gazebo_ros_pkgs`) | Selected over Fortress because upstream TurtleBot3 packages natively provide validated SDF models, differential drive plugins, and `/gazebo/model_states` state publisher |
| **Ground Truth Plugin**| `libgazebo_ros_state.so` (`<plugin name="gazebo_ros_state">`) | Dynamically publishes 10 Hz true physical poses on `/gazebo/model_states` |
| **Robot Model** | TurtleBot3 Waffle (`TURTLEBOT3_MODEL=waffle`) | Standard indoor differential drive robot with 2D LiDAR (`/scan`) |
| **Navigation Stack** | Navigation2 1.1.20 (`nav2_bringup`) | Headless bringup, AMCL particle filter localization, NavfnPlanner, DWB controller |
| **Map & World** | `configs/turtlebot3_world.yaml` + `configs/world_with_state.model` | Standard 9-pillar environment with state plugin enabled |

---

## 3. Real Navigation Test Execution Results

Four distinct runs were executed sequentially on the live simulation container:

### Run 1: Forward Transit
- **Goal**: $[x=-0.50, y=-0.50, \text{yaw}=0.00\,\text{rad}]$
- **Duration**: $5.163\,\text{s}$ | **Path Length**: $1.202\,\text{m}$
- **Nav2 Action Status**: `SUCCEEDED` (GoalStatus code 4)
- **Gazebo Ground Truth**: End Pose $[-0.800, -0.556, \text{yaw}=0.027\,\text{rad}]$
  - Position Error: $0.305\,\text{m}$ (Within $0.35\,\text{m}$ goal tolerance)
  - Heading Error: $0.027\,\text{rad}$ ($1.53^\circ$)
  - **Ground Truth Physical Arrival**: `TRUE`
- **AMCL Localization**: End Pose $[-0.954, -0.552, \text{yaw}=0.001\,\text{rad}]$
  - AMCL Position Error: $0.457\,\text{m}$ | Heading Error: $0.001\,\text{rad}$
- **Localization Discrepancy** ($\|\mathbf{p}_{\text{AMCL}} - \mathbf{p}_{\text{GT}}\|$): $0.154\,\text{m}$

### Run 2: Lateral Movement
- **Goal**: $[x=0.50, y=-0.50, \text{yaw}=1.57\,\text{rad}]$
- **Duration**: $9.612\,\text{s}$ | **Path Length**: $1.113\,\text{m}$
- **Nav2 Action Status**: `SUCCEEDED` (GoalStatus code 4)
- **Gazebo Ground Truth**: End Pose $[0.301, -0.491, \text{yaw}=1.356\,\text{rad}]$
  - Position Error: $0.199\,\text{m}$ (Within $0.35\,\text{m}$ goal tolerance)
  - Heading Error: $0.214\,\text{rad}$ ($12.27^\circ$)
  - **Ground Truth Physical Arrival**: `TRUE`
- **AMCL Localization**: End Pose $[0.287, -0.495, \text{yaw}=1.183\,\text{rad}]$
  - AMCL Position Error: $0.213\,\text{m}$ | Heading Error: $0.387\,\text{rad}$ ($22.1^\circ$)
- **Localization Discrepancy** ($\|\mathbf{p}_{\text{AMCL}} - \mathbf{p}_{\text{GT}}\|$): $0.014\,\text{m}$ (Tight sensor convergence)

### Run 3: Return Transit
- **Goal**: $[x=-2.00, y=-0.50, \text{yaw}=3.14\,\text{rad}]$
- **Duration**: $10.212\,\text{s}$ | **Path Length**: $2.162\,\text{m}$
- **Nav2 Action Status**: `SUCCEEDED` (GoalStatus code 4)
- **Gazebo Ground Truth**: End Pose $[-1.804, -0.625, \text{yaw}=3.109\,\text{rad}]$
  - Position Error: $0.232\,\text{m}$ (Within $0.35\,\text{m}$ goal tolerance)
  - Heading Error: $0.031\,\text{rad}$ ($1.78^\circ$)
  - **Ground Truth Physical Arrival**: `TRUE`
- **AMCL Localization**: End Pose $[-1.647, -0.517, \text{yaw}=3.058\,\text{rad}]$
  - AMCL Position Error: $0.354\,\text{m}$ | Heading Error: $0.082\,\text{rad}$
- **Localization Discrepancy** ($\|\mathbf{p}_{\text{AMCL}} - \mathbf{p}_{\text{GT}}\|$): $0.191\,\text{m}$

### Run 4: Unreachable Goal & Cancellation Test
- **Unreachable Goal**: $[x=10.0, y=10.0]$ (Outside arena perimeter)
- **Process**: Action accepted, robot engaged movement for $4.0\,\text{s}$.
- **Cancellation**: Dispatched `cancel_goal_async()` to Action Server.
- **Result Status**: `CANCELED` (GoalStatus code 5). Goals canceling count: 1.
- **Physical Stop Verification**: Sampled `/cmd_vel` over 1 second:
  - Linear velocity: $0.000\,\text{m/s}$
  - Angular velocity: $0.000\,\text{rad/s}$
  - **Clean Stop Confirmed**: `TRUE`

---

## 4. Critical Distinction of Arrival States

In accordance with reviewer instructions, three arrival states are rigorously separated:

| Metric | Definition | Smoke Test Result | Analysis |
| :--- | :--- | :---: | :--- |
| **Nav2 Action Succeeded** | Action server returned `GoalStatus.STATUS_SUCCEEDED` | **3 / 3** (100%) | Controller server met internal local goal tolerance |
| **Physical Ground Truth Arrived** | $\|\mathbf{p}_{\text{GT}} - \mathbf{p}_{\text{goal}}\| < 0.35\,\text{m}$ and $\|\Delta\theta\| < 0.35\,\text{rad}$ | **3 / 3** (100%) | Robot physically reached target position ($0.199\,\text{m}$ to $0.305\,\text{m}$ error) |
| **AMCL Estimation Arrived** | $\|\mathbf{p}_{\text{AMCL}} - \mathbf{p}_{\text{goal}}\| < 0.35\,\text{m}$ and $\|\Delta\theta\| < 0.35\,\text{rad}$ | **0 / 3** (0%) | AMCL particle noise caused estimated pose to hover between $0.354\,\text{m}$ and $0.457\,\text{m}$ |

> **Key Finding**: In real robotics systems, AMCL estimates can exhibit 10-20 cm variance relative to true ground truth. Treating AMCL pose as ground truth or conflating Nav2 success with exact physical arrival introduces systemic measurement bias. Our logging architecture explicitly isolates all three channels.

---

## 5. Topological Metadata & Verification

Real ROS2 node topology verified at runtime:
- **Active Nodes (30)**: `/amcl`, `/controller_server`, `/planner_server`, `/behavior_server`, `/bt_navigator`, `/gazebo`, `/gazebo/gazebo_ros_state`, `/turtlebot3_diff_drive`, `/turtlebot3_laserscan`, `/turtlebot3_imu`, etc.
- **Active Topics (57)**: `/clock`, `/scan`, `/odom`, `/tf`, `/tf_static`, `/amcl_pose`, `/gazebo/model_states`, `/cmd_vel`, `/plan`, etc.
- **Active Actions (12)**: `/navigate_to_pose`, `/navigate_through_poses`, `/follow_path`, `/spin`, `/wait`, `/backup`, etc.

Full lists captured in `reports/evidence/p1a/ros_{nodes,topics,actions}.txt`.

---

## 6. Implementation Status Breakdown

| Item | Status | Verification Mechanism |
| :--- | :---: | :--- |
| **Strict JSON & Markdown Action Validator** | VERIFIED | 28 unit tests covering all positive schemas, NaN, Inf, overflow, whitespace IDs, top-level arrays |
| **Runtime Execution Context (`action_runtime.py`)** | VERIFIED | Unit tests for action ID uniqueness, retry precondition, parameter tampering, recursion, budget |
| **Headless Gazebo Classic + Nav2 Bringup** | VERIFIED | Headless simulation subprocess in isolated container |
| **Ground Truth State Publisher** | VERIFIED | `libgazebo_ros_state.so` world plugin streaming on `/gazebo/model_states` |
| **Nav2 Action Pipeline & Cancellation** | VERIFIED | 3 waypoint runs + 1 cancellation run executed with live tracking |
| **Literature Registry CSV Quoting** | VERIFIED | `csv.DictWriter(quoting=csv.QUOTE_MINIMAL)` validated (18 clean columns, no misalignments) |
| **Model Probe v2 Improvements** | VERIFIED | Seed, prompt content hash, run_id, decoupled executability, GiB/GB distinction |
| **Historical Probe Rescoring** | VERIFIED | `reports/evidence/p0/rescore_model_probe_v2.json` with 5/5 parseable & valid |
| *LLM Closed-Loop Navigation* | DEFERRED | Strictly excluded from P1a scope |
| *FailMem Memory Retrieval & Update* | DEFERRED | Strictly excluded from P1a scope |
| *Benchmark Dataset Evaluation* | DEFERRED | Strictly excluded from P1a scope |

---

## 7. Evidence Manifest & Checksums

All raw evidence files are stored in `reports/evidence/p1a/`:

| File | Size | Description |
| :--- | :--- | :--- |
| `docker_build.log` | 451 KB | Complete Docker image build log from pinned digest |
| `nav2_sim_launch.log` | 63 KB | Nav2 and Gazebo Classic launch stdout/stderr |
| `p1a_nav_events.log` | 5.1 KB | Microsecond-timestamped smoke test execution event trace |
| `p1a_nav_smoke_results.json` | 4.5 KB | Structured metrics (durations, errors, arrival statuses, topology counts) |
| `p1a_trajectories.json` | 40.5 KB | Time-indexed Ground Truth and AMCL trajectory coordinates |
| `ros_nodes.txt` | 741 B | Active ROS2 nodes during test |
| `ros_topics.txt` | 1.2 KB | Active ROS2 topics during test |
| `ros_actions.txt` | 191 B | Active ROS2 action servers during test |
| `checksums.sha256` | 640 B | SHA256 hashes of all evidence artifacts |

---

## 8. Exact Reproduction Commands

```bash
# 1. Build the isolated simulation Docker container
docker build -t failmem:ros2_humble_p1a -f docker/Dockerfile.ros2_humble .

# 2. Run the automated P1a navigation smoke test
docker run --rm -v $(pwd):/workspace failmem:ros2_humble_p1a python3 /workspace/scripts/run_p1a_nav.py

# 3. Run unit tests on host
pytest -v
```
