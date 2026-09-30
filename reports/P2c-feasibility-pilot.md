# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-09-30  
**Phase**: Milestone P2c Event-Driven Feasibility Pilot & Minimal Dual-Path Physical Diagnosis  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.1, SHA256: `7a38e8cf829adb25ea4b37842a95c664e99a1c309e7e43d836572c085e28d7ac`)  
**Evidence Artifacts**:
- Real ROS Physical Pilot Suite (10 Episodes): `reports/evidence/p2c_pilot/p2c_pilot_20260930_052812_f14f2b/`
- Independent Replay & Audit Summary: `reports/evidence/p2c_pilot/p2c_pilot_20260930_052812_f14f2b/p2c_replay_summary.json`
- Analytical Model Predictions: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`
- Map / Model / Protocol: `configs/p2c_dualpath_world.model`, `configs/p2c_dualpath_world.yaml`, `configs/p2c_dualpath_world.pgm`, `configs/p2c_pilot_protocol.yaml`

---

## 1. Scope, Positioning & Methodological Clarification

This report presents the findings of the Milestone P2c Feasibility Pilot on an asymmetric dual-path non-line-of-sight (NLOS) navigation environment.

### 1.1 Separation of Evidence Types
- **Analytical Model (`reports/evidence/p2c_analytical/`)**: Evaluates policy decision logic under idealized constant-velocity kinematic abstractions ($0.25\,\text{m/s}$ avg velocity, nominal segment geometry). Serves solely for policy unit demonstration.
- **Physical ROS 2 / Gazebo Simulation (`reports/evidence/p2c_pilot/`)**: Fully authentic end-to-end execution in Gazebo 11 with ROS 2 Humble Nav2, AMCL particle filter localization, LiDAR ray tracing, Nav2 global costmap updates, and continuous odometry/ground-truth trajectory integration.
- **Strict Event-Driven Lifecycle**:
  - Reaching the observation vantage point (`hist_reach_obs_vantage`) succeeds and produces live perception evidence, but does **not** register failure memory.
  - Failure memory is registered **only** when chokepoint traversal fails (`hist_attempt_chokepoint_traversal`) with linked `OCCUPIED` perception evidence.
  - Invalidation is strictly event-driven by live perception returning `FREE` ($\ge 8$ traversing rays, 0 obstacle hits, cleared costmap).
- **Status of Hypotheses**: Claims of universal theoretical superiority or Pareto optimality are withdrawn. Findings reflect empirical behaviors observed under the controlled conditions of this specific benchmark.

---

## 2. Environment Geometry, Observability & Costmap Audit

### 2.1 Calibrated Asymmetric Layout
- **Decision Junction $J_0$**: $(-2.50, 0.00, \text{yaw}=0.00)$.
- **Goal Target in Room 2**: $(+2.50, 0.00, \text{yaw}=0.00)$.
- **Central Dividing Island**: $X \in [-1.80, +1.80], Y \in [-1.00, +0.40]$ (Thickness $1.40\,\text{m}$, Length $3.60\,\text{m}$).
- **Path A (North Short Corridor)**: Nominal polyline length $6.124\,\text{m}$, passing through Chokepoint A at $(0.00, 1.20)$. Doorway width is $0.80\,\text{m}$ ($Y \in [0.80, 1.60]$).
- **Path B (South Detour Corridor)**: Nominal polyline length $9.105\,\text{m}$, passing along $Y=-2.40$, completely open.
- **Obstacle & Robot Dimensions**: TurtleBot3 Waffle footprint diameter $\approx 0.44\,\text{m}$, inflation radius $0.35\,\text{m}$. Blockage box size $0.40 \times 1.00 \times 0.60\,\text{m}$ at $(0.00, 1.20, 0.30)$ leaves $\le 0.10\,\text{m}$ clearance, guaranteeing physical and costmap blockage without leaks when present, and smooth passage when absent.

### 2.2 Sightline Occlusion Proof
From $J_0 (-2.50, 0.00)$ to Chokepoint A $(0.00, 1.20)$, the ray equation is $x(t) = -2.5 + 2.5t, y(t) = 1.2t$.  
At $x = -1.80$ ($t = 0.28$), $y = 0.336\,\text{m} \in [-1.00, +0.40]$.  
The ray strikes the solid central island wall, verifying $100\%$ physical line-of-sight occlusion.  
In real ROS 2 simulation at $J_0$, LiDAR ray projection confirms instantaneous local sensor observation is strictly **`UNKNOWN`** (`DOORWAY_NOT_IN_FOV_OR_OCCLUDED`).

### 2.3 Nav2 Costmap Shared State Audit
- In Scenario D1, when the robot probes Chokepoint A, the Nav2 global costmap registers lethal obstacle cells inside the doorway opening center ($X \in [-0.15, 0.15], Y \in [0.95, 1.45]$).
- After retreating to $J_0$, the global costmap retains these lethal cells (`COSTMAP_AFTER_RETREAT_TO_J0`).
- In Scenario D2, when the obstacle is removed and probed, opening center lethal cells drop to 0 and traversing rays reach Room 2 (`COSTMAP_PROBE_CLEARED_AT_CHOKEPOINT`).

---

## 3. Real ROS 2 Physical Execution Results (10-Episode Matrix)

All 10 episodes were executed inside Docker container `failmem_humble` (`run_id: p2c_pilot_20260930_052812_f14f2b`). Real distances are integrated from continuous odometry, and real durations are measured via simulation `/clock`.

| Scenario | Method | Description | Decision Route | Dead-End Traversals | History Dist ($m$) | History Time ($s$) | Decision Dist ($m$) | Decision Time ($s$) | Total Dist ($m$) | Total Time ($s$) | Physical Arrival | Episode Valid |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0 (Fresh)** | **R** | Reactive Only | Path A | 0 | 0.00 | 0.00 | 6.14 | 47.40 | 6.14 | 47.40 | **True** | **True** |
| **D0 (Fresh)** | **O** | Spatial Obs Cache | Path A | 0 | 0.00 | 0.00 | 6.16 | 49.00 | 6.16 | 49.00 | **True** | **True** |
| **D0 (Fresh)** | **F** | FailMem Memory | Path A | 0 | 0.00 | 0.00 | 6.14 | 47.40 | 6.14 | 47.40 | **True** | **True** |
| **D1 (Blocked)** | **R** | Reactive Only | Path A $\to$ Path B | **1** | 8.85 | 68.30 | **16.95** | **117.30** | **25.80** | **185.60** | **True** | **True** |
| **D1 (Blocked)** | **O** | Spatial Obs Cache | Path B | **0** | 8.54 | 67.90 | **7.51** | **46.70** | **16.05** | **114.60** | **True** | **True** |
| **D1 (Blocked)** | **F** | FailMem Memory | Path B | **0** | 8.54 | 67.90 | **7.45** | **49.00** | **15.99** | **116.90** | **True** | **True** |
| **D2 (Cleared)** | **R** | Reactive Only | Path A | 0 | 14.01 | 106.70 | 5.99 | 50.90 | 20.00 | 157.60 | **True** | **True** |
| **D2 (Cleared)** | **O** | Spatial Obs Cache | Path A | 0 | 14.06 | 106.70 | 5.89 | 46.40 | 19.95 | 153.10 | **True** | **True** |
| **D2 (Cleared)** | **F** | FailMem Memory | Path A | 0 | 14.12 | 106.70 | 5.93 | 48.40 | 20.05 | 155.10 | **True** | **True** |
| **D2 (Cleared)** | **M1**| Persistent Suppression| Path B (Detour) | 0 | 13.64 | 106.70 | **7.86** | **51.40** | **21.50** | **158.10** | **True** | **True** |

---

## 4. Analytical Model vs. Real Physical Simulation Comparison

| Scenario & Method | Analytical Decision Dist | Real Physical Decision Dist | Analytical Decision Time | Real Physical Decision Time | Deviation Rationale |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **D0 - R / O / F** | $6.12\,\text{m}$ | $6.14 \sim 6.16\,\text{m}$ | $25.2\,\text{s}$ | $47.4 \sim 49.0\,\text{s}$ | Close match in geometric distance ($< 0.04\,\text{m}$ diff); duration reflects Nav2 acceleration and settling. |
| **D1 - R (Blocked)** | $15.23\,\text{m}$ | $16.95\,\text{m}$ | $63.6\,\text{s}$ | $117.30\,\text{s}$ | Real physical dead-end includes approach, abort slowdown, retreat to $J_0$, and complete Path B detour. |
| **D1 - O / F (Bypass)**| $9.11\,\text{m}$ | $7.45 \sim 7.51\,\text{m}$ | $37.2\,\text{s}$ | $46.7 \sim 49.0\,\text{s}$ | Nav2 smooth path optimization across open corridor waypoint $(0.0, -2.40)$. |
| **D2 - R / O / F** | $6.12\,\text{m}$ | $5.89 \sim 5.99\,\text{m}$ | $25.2\,\text{s}$ | $46.4 \sim 50.9\,\text{s}$ | Successfully restored Path A routing with physical arrival verified. |
| **D2 - M1 (Persistent)**| $9.11\,\text{m}$ | $7.86\,\text{m}$ | $37.2\,\text{s}$ | $51.40\,\text{s}$ | Incurs continuous detour overhead ($+1.93\,\text{m}$ dist, $+3 \sim 5\,\text{s}$ time) relative to restored short path. |

---

## 5. Key Scientific Findings & Discussion

1. **Dead-End Elimination via Prior Knowledge (H1 Context)**:
   - In Scenario D1, purely reactive execution (Method R) suffers an avoidable dead-end entry ($16.95\,\text{m}$, $117.30\,\text{s}$ decision phase) before falling back to Path B.
   - Retaining historical evidence (Methods O and F) allows the robot at $J_0$ to route directly via Path B ($7.45 \sim 7.51\,\text{m}$, $46.70 \sim 49.00\,\text{s}$ decision phase), eliminating the dead-end traversal and saving $9.44 \sim 9.50\,\text{m}$ of unnecessary motion and $68 \sim 70\,\text{s}$ of execution time.

2. **Equivalence of O and F in Single-Robot Static Spatial Routing (H2 Context)**:
   - Method O (spatial observation cache) and Method F (FailMem failure memory) exhibit identical route selection (`Path_A` in D0, `Path_B` in D1, `Path_A` in D2), with negligible physical variance ($7.45\,\text{m}$ vs $7.51\,\text{m}$ in D1).
   - In single-robot static environments, execution failures at doorways are causally reducible to spatial occupancy. General spatial observation caching without action semantics is empirically sufficient for optimal routing.

3. **Avoidance of Detour Overhead via Invalidation (H3 Context)**:
   - In Scenario D2, conditional invalidation mechanisms in O and F re-enable Path A upon verified clearance ($5.89 \sim 5.93\,\text{m}$, $46.40 \sim 48.40\,\text{s}$), whereas persistent suppression (Method M1) continues taking the South detour ($7.86\,\text{m}$, $51.40\,\text{s}$), incurring an unnecessary detour penalty.

4. **Unverified Theoretical Hypotheses for Failure Memory**:
   The unique value of explicit failure memory (beyond spatial observation caching) remains an unverified hypothesis in this milestone, to be investigated in domains involving:
   - Non-spatial or dynamic action failures (e.g. payload weight, torque limits, kinematic feasibility where space is geometrically free).
   - Multi-robot capability asymmetries (e.g. large robot Waffle blocked while small robot Burger passes).
   - Causal action-precondition dependencies (e.g. requiring a specific prerequisite intervention).

---

## 6. Audit Closeout Summary

- All 10 physical episodes achieved verified physical arrival, stability, and validity ($10/10$ `episode_valid: true`).
- Independent replay tool `scripts/replay_and_score_p2c.py` re-scored all episodes from raw artifacts with $100\%$ checksum verification.
- Raw trajectories, action summaries, stability windows, and costmap snapshots are archived in `reports/evidence/p2c_pilot/p2c_pilot_20260930_052812_f14f2b/`.
- Analytical model artifacts are isolated in `reports/evidence/p2c_analytical/`.
- The benchmark codebase and evidence comply with all audit integrity guidelines.
