# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-09-30  
**Phase**: Milestone P2c Feasibility Pilot & Minimal Dual-Path Diagnosis  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.1, SHA256: `e300c2e5ba6872ea2ab084856afa591198f364bc39e3be874d1172a49c50b30a`)  
**Evidence Artifacts**:
- Real ROS Physical Pilot Suite: `reports/evidence/p2c_pilot/p2c_pilot_20260930_043612_8c91be/`
- Analytical Model Predictions: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`
- Analytical Sightline Occlusion: `reports/evidence/p2c_analytical/sightline_occlusion_proof.json`
- Map / Model / Protocol: `configs/p2c_dualpath_world.model`, `configs/p2c_dualpath_world.yaml`, `configs/p2c_dualpath_world.pgm`, `configs/p2c_pilot_protocol.yaml`

---

## 1. Scope, Positioning & Methodological Clarification

This report presents the findings of the Milestone P2c Feasibility Pilot on an asymmetric dual-path non-line-of-sight (NLOS) navigation environment.

### 1.1 Separation of Evidence Types
- **Analytical Model (`reports/evidence/p2c_analytical/`)**: Evaluates policy decision logic under idealized constant-velocity kinematic abstractions ($0.25\,\text{m/s}$ avg velocity, nominal segment geometry). Serves solely for policy unit demonstration.
- **Physical ROS 2 / Gazebo Simulation (`reports/evidence/p2c_pilot/`)**: Fully authentic end-to-end execution in Gazebo 11 with ROS 2 Humble Nav2, AMCL particle filter localization, LiDAR ray tracing, Nav2 global costmap updates, and continuous odometry/ground-truth trajectory integration.
- **Status of Hypotheses**: Claims of universal theoretical superiority or Pareto optimality are withdrawn. Findings reflect empirical behaviors observed under the controlled conditions of this specific benchmark.

---

## 2. Environment Geometry, Observability & Costmap Audit

### 2.1 Calibrated Asymmetric Layout
- **Decision Junction $J_0$**: $(-2.50, 0.00, \text{yaw}=0.00)$.
- **Goal Target in Room 2**: $(+2.50, 0.00, \text{yaw}=0.00)$.
- **Central Dividing Island**: $X \in [-1.80, +1.80], Y \in [-1.00, +0.40]$ (Thickness $1.40\,\text{m}$, Length $3.60\,\text{m}$).
- **Path A (North Short Corridor)**: Nominal polyline length $\approx 5.82\,\text{m}$, passes through Chokepoint A at $(0.00, 1.20)$. Doorway width is $0.80\,\text{m}$ ($Y \in [0.80, 1.60]$).
- **Path B (South Detour Corridor)**: Nominal polyline length $\approx 8.83\,\text{m}$, passing along $Y=-2.40$, completely open.
- **Obstacle & Robot Dimensions**: TurtleBot3 Waffle footprint diameter $\approx 0.44\,\text{m}$, inflation radius $0.35\,\text{m}$. Blockage box size $0.60 \times 0.60 \times 0.60\,\text{m}$ at $(0.00, 1.20, 0.30)$ leaves $\le 0.10\,\text{m}$ clearance, guaranteeing physical and costmap blockage without leaks when present, and smooth passage when absent.

### 2.2 Sightline Occlusion Proof
From $J_0 (-2.50, 0.00)$ to Chokepoint A $(0.00, 1.20)$, the ray equation is $x(t) = -2.5 + 2.5t, y(t) = 1.2t$.  
At $x = -1.80$ ($t = 0.28$), $y = 0.336\,\text{m} \in [-1.00, +0.40]$.  
The ray strikes the solid central island wall, verifying $100\%$ physical line-of-sight occlusion.  
In real ROS 2 simulation at $J_0$, LiDAR returns $1 \sim 2$ spurious peripheral rays in the doorway bounding box ($\le 5$ threshold), confirming instantaneous local sensor observation is strictly **`UNKNOWN`**.

### 2.3 Nav2 Costmap Shared State Audit
- In Scenario D1, when the robot probes Chokepoint A, the Nav2 global costmap registers $221$ occupied cells inside the doorway bounding box ($X \in [-0.3, 0.3], Y \in [0.8, 1.6]$).
- After retreating to $J_0$, the global costmap retains these occupied cells (`COSTMAP_AFTER_RETREAT_TO_J0`).
- This confirms that underlying costmap retention provides shared spatial history across algorithms unless explicitly cleared.

---

## 3. Real ROS 2 Physical Execution Results (10-Episode Matrix)

All 10 episodes were executed inside Docker container `failmem_humble` (`run_id: p2c_pilot_20260930_043612_8c91be`). Real distances are integrated from continuous odometry, and real durations are measured via simulation `/clock`.

| Scenario | Method | Description | Decision Route | Dead-End Traversals | History Dist ($m$) | History Time ($s$) | Decision Dist ($m$) | Decision Time ($s$) | Total Dist ($m$) | Total Time ($s$) | Strict Physical Success |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0 (Fresh)** | **R** | Reactive Only | Path A | 0 | 0.00 | 0.00 | 7.45 | 39.30 | 7.45 | 39.30 | **True** |
| **D0 (Fresh)** | **O** | Spatial Obs Cache | Path A | 0 | 0.00 | 0.00 | 7.44 | 39.40 | 7.44 | 39.40 | **True** |
| **D0 (Fresh)** | **F** | FailMem Memory | Path A | 0 | 0.00 | 0.00 | 7.44 | 39.30 | 7.44 | 39.30 | **True** |
| **D1 (Blocked)** | **R** | Reactive Only | Path A $\to$ Path B | **1** | 4.87 | 38.00 | **17.12** | **106.10** | **21.99** | **144.10** | **True** |
| **D1 (Blocked)** | **O** | Spatial Obs Cache | Path B | **0** | 4.87 | 38.60 | **7.86** | **47.50** | **12.72** | **86.10** | **True** |
| **D1 (Blocked)** | **F** | FailMem Memory | Path B | **0** | 4.78 | 38.80 | **7.88** | **51.00** | **12.66** | **89.80** | **True** |
| **D2 (Cleared)** | **R** | Reactive Only | Path A | 0 | 9.45 | 79.90 | 7.69 | 39.40 | 17.13 | 119.30 | **True** |
| **D2 (Cleared)** | **O** | Spatial Obs Cache | Path A | 0 | 9.47 | 77.60 | 7.61 | 39.30 | 17.08 | 116.90 | **True** |
| **D2 (Cleared)** | **F** | FailMem Memory | Path A | 0 | 9.57 | 77.70 | 7.64 | 41.60 | 17.21 | 119.30 | **True** |
| **D2 (Cleared)** | **M1**| Persistent Suppression| Path B (Detour) | 0 | 9.35 | 74.40 | **7.86** | **47.50** | **17.21** | **121.90** | **True** |

---

## 4. Analytical Model vs. Real Physical Simulation Comparison

| Scenario & Method | Analytical Decision Dist | Real Physical Decision Dist | Analytical Decision Time | Real Physical Decision Time | Deviation Rationale |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **D0 - R / O / F** | $5.8\,\text{m}$ | $7.44 \sim 7.45\,\text{m}$ | $25.2\,\text{s}$ | $39.3 \sim 39.4\,\text{s}$ | Real Nav2 generates curved clearance around corners; smooth acceleration/deceleration. |
| **D1 - R (Blocked)** | $14.4\,\text{m}$ | $17.12\,\text{m}$ | $63.6\,\text{s}$ | $106.10\,\text{s}$ | Real physical dead-end includes slowdown, in-place rotation, retreat, and detour navigation. |
| **D1 - O / F (Bypass)**| $8.8\,\text{m}$ | $7.86 \sim 7.88\,\text{m}$ | $37.2\,\text{s}$ | $47.5 \sim 51.0\,\text{s}$ | Intermediate waypoint $(0.0, -2.40)$ smooth cut-through; acceleration profile. |
| **D2 - R / O / F** | $5.8\,\text{m}$ | $7.61 \sim 7.69\,\text{m}$ | $25.2\,\text{s}$ | $39.3 \sim 41.6\,\text{s}$ | Successfully restored Path A routing with physical arrival verified. |
| **D2 - M1 (Persistent)**| $8.8\,\text{m}$ | $7.86\,\text{m}$ | $37.2\,\text{s}$ | $47.50\,\text{s}$ | Incurs continuous detour overhead relative to restored short path. |

---

## 5. Key Scientific Findings & Discussion

1. **Dead-End Elimination via History (H1 Context)**:
   - In Scenario D1, purely reactive execution (Method R) suffers an avoidable dead-end entry ($17.12\,\text{m}$, $106.10\,\text{s}$ decision phase) before falling back to Path B.
   - Retaining historical evidence (Methods O and F) allows the robot at $J_0$ to route directly via Path B ($7.86 \sim 7.88\,\text{m}$, $47.50 \sim 51.00\,\text{s}$ decision phase), eliminating the dead-end traversal and saving $9.24\,\text{m}$ of unnecessary motion and $55 \sim 58\,\text{s}$ of execution time.

2. **Equivalence of O and F in Single-Robot Static Spatial Routing (H2 Context)**:
   - Method O (spatial observation cache) and Method F (FailMem failure memory) exhibit identical route selection (`Path_A` in D0, `Path_B` in D1, `Path_A` in D2), with negligible physical variance ($7.86\,\text{m}$ vs $7.88\,\text{m}$ in D1).
   - In single-robot static environments, execution failures at doorways are causally reducible to spatial occupancy. General spatial observation caching without action semantics is empirically sufficient for optimal routing.

3. **Avoidance of Detour Overhead via Invalidation (H3 Context)**:
   - In Scenario D2, conditional invalidation mechanisms in O and F re-enable Path A upon verified clearance ($7.61 \sim 7.64\,\text{m}$, $39.30 \sim 41.60\,\text{s}$), whereas persistent suppression (Method M1) continues taking the South detour ($7.86\,\text{m}$, $47.50\,\text{s}$), incurring an additional detour penalty.

4. **Unverified Theoretical Hypotheses for Failure Memory**:
   The unique value of explicit failure memory (beyond spatial observation caching) remains an unverified hypothesis in this milestone, to be investigated in domains involving:
   - Non-spatial or dynamic action failures (e.g. payload weight, torque limits, kinematic feasibility where space is geometrically free).
   - Multi-robot capability asymmetries (e.g. large robot Waffle blocked while small robot Burger passes).
   - Causal action-precondition dependencies (e.g. requiring a specific prerequisite intervention).

---

## 6. Audit Closeout Summary

- All 10 physical episodes achieved verified physical arrival and stability.
- Raw trajectories, action summaries, stability windows, and costmap snapshots are archived in `reports/evidence/p2c_pilot/p2c_pilot_20260930_043612_8c91be/`.
- Analytical model artifacts are isolated in `reports/evidence/p2c_analytical/`.
- The benchmark codebase and evidence comply with all audit integrity guidelines.
