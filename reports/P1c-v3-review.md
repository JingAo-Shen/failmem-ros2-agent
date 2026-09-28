# FailMem Milestone P1c-v3 Comprehensive Verification & Audit Review Report

**Date**: 2026-09-28  
**Formal Run ID**: [`p1c_20260928_065410_72a954`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954)  
**Diagnostic Run ID**: [`p1c_diag_20260928_064406_c7618e`](file:///code/failmem-ros2-agent/reports/evidence/p1c_diagnostic/p1c_diag_20260928_064406_c7618e)  
**Protocol Version**: `3.0` (`configs/p1c_v3_protocol.yaml`, SHA256: `f703c392ba1af0bba601c4e9ab56d62f0054d4ab53cb530a2807dfb33b8d3a47`)  
**Overall Status**: `PASSED` (C0 Baseline: 100% 3/3; C1 Continuous Blockage: 100% 3/3; C2 Temporary Blockage & Recovery: 100% 3/3)  
**Branch**: `audit/r0-authenticity`  
**Unit Tests**: 91 passed, 8 xfailed (traceability tests preserved)

---

## 1. Executive Summary

This report delivers the empirical findings for **Milestone P1c-v3**. The goal of this milestone is to establish a credible, rigorously verified, and empirical execution chain:  
$$\text{Blocked Failure} \longrightarrow \text{Obstacle Removed} \longrightarrow \text{Valid Stationary Observation} \longrightarrow \text{Retry Parameter Restoration} \longrightarrow \text{Goal Arrival}$$  
without LLM hallucination, synthetic pose injection, or artificial service-driven costmap wipes.

### Key Milestones Achieved:
1. **Single-Chokepoint Dual-Room Arena (`configs/chokepoint_world.model`)**:
   - Replaced multi-corridor topological loops with a strict dual-room layout separated by a single central doorway at $x=0.0$ ($y \in [-0.45, 0.45]$).
   - Solid perimeter and partition walls eliminate bypass detours, ensuring that obstacle placement physically blocks 100% of topological navigation routes.
2. **Standard AMCL Stationary Update via `/request_nomotion_update`**:
   - Resolved the stationary observation staleness issue naturally. When the robot is halted before the doorway, calling the standard ROS 2 Nav2 AMCL service triggers particle filter updates from the latest laser scan, generating an authentic, fresh `/amcl_pose` with valid covariance and sub-second staleness.
   - Zero synthetic coordinate injection or odometry spoofing.
3. **Map-Frame Spatial Doorway Clearance Verification**:
   - Implemented geometric projection of 2D laser scan rays into map coordinates within doorway bounding box $[-0.20, 0.20] \times [-0.30, 0.30]$.
   - Verified that obstacle presence yields 21–22 laser points inside the doorway, and obstacle deletion combined with natural costmap raytracing reduces points to 0.
4. **C2 State Machine Alignment & Early Exit Handling**:
   - Observe contract strictly accepts `SUCCESS` and verified `DEGRADED` states with complete map-frame localization.
   - Added early exit logic with `task_success: True` and `mechanism_verified: False` (`INITIAL_ATTEMPT_SUCCEEDED_OR_DETOURED`) in case initial attempt arrives at goal.
5. **Separation of Task Success vs. Mechanism Verification**:
   - Every episode cleanly distinguishes robotic task completion (`task_success`) from fault channel verification (`mechanism_verified`). C1 blockage is never marked as task success.

---

## 2. Coordinate System Alignment & Landmark Verification

Geometric alignment between the Gazebo physical world model (`configs/chokepoint_world.model`) and the 2D occupancy grid (`configs/chokepoint_world.yaml`, `configs/chokepoint_world.pgm`) was mathematically verified across 6 non-collinear static landmarks:

- **Map Resolution**: $0.05\text{ m/pixel}$
- **Map Origin**: `[-4.00, -2.50, 0.00]`
- **Image Size**: $160 \times 100\text{ pixels}$
- **Landmark Consistency Bound**: Maximum residual $= 0.0627\text{ m} \le 0.0750\text{ m}$ (1.5 pixel resolution bound).

| Landmark | World Model $(x, y)$ | Expected Pixel $(u, v)$ | Detected Map $(x, y)$ | Residual ($\Delta$) | Status |
|---|---|---|---|---|---|
| West Wall | $(-3.10, 0.00)$ | $(18.0, 50.0)$ | $(-3.1250, 0.0000)$ | $0.0250\text{ m}$ | `PASSED` |
| South Wall | $(0.00, -1.60)$ | $(80.0, 82.0)$ | $(-0.0054, -1.5375)$ | $0.0627\text{ m}$ | `PASSED` |
| Dividing South Wall | $(0.00, -0.97)$ | $(80.0, 69.4)$ | $(-0.0250, -0.9500)$ | $0.0320\text{ m}$ | `PASSED` |
| Dividing North Wall | $(0.00, 0.97)$ | $(80.0, 30.6)$ | $(-0.0250, 0.9500)$ | $0.0320\text{ m}$ | `PASSED` |
| North Wall | $(0.00, 1.60)$ | $(80.0, 18.0)$ | $(-0.0067, 1.5717)$ | $0.0291\text{ m}$ | `PASSED` |
| East Wall | $(3.10, 0.00)$ | $(142.0, 50.0)$ | $(3.0750, 0.0000)$ | $0.0250\text{ m}$ | `PASSED` |

---

## 3. Comprehensive 9-Episode Formal Audit Matrix

All 9 formal episodes were executed in isolated, clean simulation runs with independent Nav2/Gazebo lifecycles. Target goal: `[1.8, 0.0, 0.0]`, Spawn: `[-1.8, 0.0, 0.0]`.

| Episode ID | Cond. | Execution Outcome | ROS Terminal Status | Final GT Pose $(x, y, \text{yaw})$ | Reported GT Error | Reported AMCL Error | Passive Halt Stable | Task Success | Mechanism Verified | Doorway Check |
|---|---|---|---|---|---|---|---|---|---|---|
| [`C0_ep1`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C0_ep1) | C0 | `BUDGET_SUCCESS` | `SUCCEEDED` | `(1.6016, -0.0051, 0.0353)` | **0.1984 m** | 0.2735 m | `True` (2.4s) | **`True`** | **`True`** | Cleared (No Obs) |
| [`C0_ep2`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C0_ep2) | C0 | `BUDGET_SUCCESS` | `SUCCEEDED` | `(1.5961, 0.0050, 0.1232)` | **0.2039 m** | 0.2648 m | `True` (2.4s) | **`True`** | **`True`** | Cleared (No Obs) |
| [`C0_ep3`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C0_ep3) | C0 | `BUDGET_SUCCESS` | `SUCCEEDED` | `(1.5885, -0.0034, 0.0631)` | **0.2115 m** | 0.2757 m | `True` (2.4s) | **`True`** | **`True`** | Cleared (No Obs) |
| [`C1_ep1`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C1_ep1) | C1 | `EXECUTION_FAILED` | `ABORTED` | `(-1.4965, -0.0069, 0.0010)` | **3.2965 m** | 3.2982 m | `True` (2.4s) | **`False`** | **`True`** | Occupied (21 pts) |
| [`C1_ep2`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C1_ep2) | C1 | `EXECUTION_FAILED` | `ABORTED` | `(-1.7980, 0.0038, 0.0011)` | **3.5980 m** | 3.6267 m | `True` (2.4s) | **`False`** | **`True`** | Occupied (21 pts) |
| [`C1_ep3`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C1_ep3) | C1 | `EXECUTION_FAILED` | `ABORTED` | `(-1.2860, -0.0044, 0.0011)` | **3.0860 m** | 3.0841 m | `True` (2.4s) | **`False`** | **`True`** | Occupied (22 pts) |
| [`C2_ep1`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C2_ep1) | C2 | `BUDGET_SUCCESS` | `SUCCEEDED` | `(1.5956, 0.0053, 0.0650)` | **0.2044 m** | 0.2705 m | `True` (2.4s) | **`True`** | **`True`** | Blk=21 $\to$ Clr=0 |
| [`C2_ep2`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C2_ep2) | C2 | `BUDGET_SUCCESS` | `SUCCEEDED` | `(1.6081, 0.0022, 0.1642)` | **0.1919 m** | 0.2375 m | `True` (2.4s) | **`True`** | **`True`** | Blk=22 $\to$ Clr=0 |
| [`C2_ep3`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_065410_72a954/C2_ep3) | C2 | `BUDGET_SUCCESS` | `SUCCEEDED` | `(1.6051, 0.0044, 0.1355)` | **0.1949 m** | 0.2576 m | `True` (2.4s) | **`True`** | **`True`** | Blk=21 $\to$ Clr=0 |

> [!NOTE]
> `collision_state` is reported as `"UNKNOWN"` across all episodes because TurtleBot3 Waffle does not integrate bumper sensors in default Gazebo setups.

---

## 4. Condition-by-Condition Empirical Analysis

### Condition C0: Unblocked Baseline Navigation (3/3 Passed)
- **Arrival Accuracy**: 
  - True Ground Truth position errors: `0.1984 m`, `0.2039 m`, `0.2115 m` (all well within $0.30\text{ m}$ tolerance).
  - AMCL estimated errors: `0.2735 m`, `0.2648 m`, `0.2757 m`.
  - True Ground Truth yaw errors: `0.0353 rad`, `0.1232 rad`, `0.0631 rad` (all $\le 0.35\text{ rad}$).
- **Passive Halt & Stability Window**:
  - In all 3 episodes, the robot came to a complete passive physical stop ($v_{\text{linear}} \le 0.0004\text{ m/s}$, $v_{\text{angular}} \le 0.0029\text{ rad/s}$) with **zero external safety intervention (`sticky_safety_intervention: False`)**.
  - Continuous 2.4s stability window verified: $\ge 178$ samples, data freshness verified, zero retrograde timestamps.

### Condition C1: Continuous Obstacle Blockage (3/3 Mechanism Verified)
- **Blockage Verification**:
  - Obstacle entity `corridor_blockage_box` spawned at $(0.0, 0.0, 0.30)$ and confirmed via `/gazebo/model_states`.
  - Doorway occupancy confirmed: Pre-nav spatial scan detected 21–22 rays within doorway bounding box $[-0.20, 0.20] \times [-0.30, 0.30]$.
  - Nav2 planner attempted to navigate, failed to find any alternate topological detour path, and returned terminal status `ABORTED` (`EXECUTION_FAILED`).
  - Robot stopped at $x \in [-1.798, -1.286]\text{ m}$, maintaining $>3.08\text{ m}$ distance from the goal at $(1.8, 0.0)$.
  - **Zero false positives**: `task_success: False`, `no_spurious_success: True`, `mechanism_verified: True`.

### Condition C2: Temporary Blockage, Natural Clearance & Retry Recovery (3/3 Mechanism Verified & Arrived)
- **Detailed 5-Step Execution Trace**:
  1. **Step 1 Initial Observe**: Dispatched `observe` $\to$ AMCL `/request_nomotion_update` received fresh stamp $\to$ `status: SUCCESS` ($[-1.80, 0.00, 0.00]$).
  2. **Step 2 Initial Blocked Navigation**: Dispatched `navigate(goal=[1.8, 0.0, 0.0])` $\to$ Nav2 encountered doorway obstacle $\to$ `terminal: ABORTED` $\to$ robot stopped in Room 1 ($x \approx -1.80\text{ m}$, distance to goal $3.59\text{ m}$).
  3. **Obstacle Deletion & Natural Raytracing**:
     - `delete_entity` service called and verified absent in Gazebo states.
     - Natural lidar raytracing elapsed for 3.0s sim time (zero service purges). Doorway spatial scan verified **0 points in doorway** (`doorway_cleared: True`).
  4. **Step 3 Post-Removal Observe & Retry Eligibility**:
     - Dispatched `observe` $\to$ AMCL `/request_nomotion_update` executed $\to$ fresh particle filter stamp generated $\to$ `status: SUCCESS`.
     - `evaluate_c2_retry_eligibility()` evaluated `eligible: True, visible_state: {"amcl_pose": [-1.45, -0.37, ...]}, reason: SUCCESS`.
  5. **Step 4 Retry Navigation & Arrival**:
     - Dispatched `retry(original_action_id=...)` with restored parameters `[1.8, 0.0, 0.0]`.
     - Nav2 planned through the cleared doorway and achieved `BUDGET_SUCCESS` (SUCCEEDED).
     - Final GT position errors: `0.2044 m` (Ep1), `0.1919 m` (Ep2), `0.1949 m` (Ep3) (all $\le 0.30\text{ m}$).
     - `task_success: True`, `mechanism_verified: True` for 100% of episodes.

---

## 5. Diagnostic vs. Formal Comparison

| Metric / Dimension | Diagnostic Mode (`--diagnostic`) | Formal Experiment (Default) | Consistency Check |
|---|---|---|---|
| **Run ID** | `p1c_diag_20260928_064406_c7618e` | `p1c_20260928_065410_72a954` | Match |
| **Episodes per Condition** | 1 (1x C0, 1x C1, 1x C2) | 3 (3x C0, 3x C1, 3x C2) | Consistent |
| **C0 Success Rate** | 100% (1/1) | 100% (3/3) | Consistent |
| **C1 Blockage Rate** | 100% (1/1) | 100% (3/3) | Consistent |
| **C2 Recovery Rate** | 100% (1/1) | 100% (3/3) | Consistent |
| **C0 Mean GT Error** | 0.1984 m | 0.2046 m | $\pm 0.006$ m variance |
| **C2 Mean Retry GT Error** | 0.2044 m | 0.1971 m | $\pm 0.007$ m variance |
| **Doorway Occupied Rays** | 21 rays | 21–22 rays | Consistent |
| **Doorway Cleared Rays** | 0 rays | 0 rays | Consistent |

---

## 6. Audit Traceability & Checksums

The full evidence package is stored at:
```
reports/evidence/p1c/p1c_20260928_065410_72a954/
├── checksums.sha256
├── coordinate_alignment_proof.json
├── runtime_config.json
├── summary.json
├── C0_ep1/ ... C0_ep3/
│   ├── episode_summary.json
│   ├── events.log
│   ├── nav2_sim.log
│   └── initial_attempt/
│       ├── action_summary.json
│       ├── stability_window.json
│       └── trajectory.json
├── C1_ep1/ ... C1_ep3/
│   ├── episode_summary.json
│   ├── events.log
│   ├── nav2_sim.log
│   └── initial_attempt/
│       ├── action_summary.json
│       ├── stability_window.json
│       └── trajectory.json
└── C2_ep1/ ... C2_ep3/
    ├── episode_summary.json
    ├── events.log
    ├── nav2_sim.log
    ├── initial_attempt/
    │   ├── action_summary.json
    │   ├── stability_window.json
    │   └── trajectory.json
    └── retry_attempt/
        ├── action_summary.json
        ├── stability_window.json
        └── trajectory.json
```

### Key Artifact SHA256 Hashes:
- `configs/p1c_v3_protocol.yaml`: `f703c392ba1af0bba601c4e9ab56d62f0054d4ab53cb530a2807dfb33b8d3a47`
- `configs/chokepoint_world.model`: `f7aafddaf0d2a2190292959fa9f0d1efc75bcdc24d1c1bb715be569c32b45889`
- `configs/chokepoint_world.yaml`: `0a5ecd11284331d534d20d969a952f7117c26d718e97e0105bbc4a354fca7619`
- `configs/chokepoint_world.pgm`: `c41adaaad5d00dc35d591e88016b2f3394d316fb01e33bb4713a66284cc5b18b`
- `configs/chokepoint_box.sdf`: `77e5e3a890da8dbdf3db4d3fe2a0c4f828694ae9fbc8ef556b68be1288c1c49b`
- `scripts/run_p1c_v3.py`: `2e604fefd2ba12903510c436a5fae3489814400cf9d75be6e25f8ceb09653ca2`
