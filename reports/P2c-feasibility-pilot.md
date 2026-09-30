# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-09-30  
**Phase**: Milestone P2c Event-Driven Feasibility Pilot & Minimal Dual-Path Physical Diagnosis  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.1, SHA256: `92502bb4fb1c17629b346eeac2cd3d792aa95fba4f54e95bc2db4e0df3cdbe92`)  
**Evidence Artifacts**:
- Real ROS Physical Pilot Suite (10 Episodes): `reports/evidence/p2c_pilot/p2c_pilot_20260930_102323_62b40e/`
- Independent Replay & Audit Summary: `reports/evidence/p2c_pilot/p2c_pilot_20260930_102323_62b40e/p2c_replay_summary.json`
- Analytical Model Demonstrations: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`
- Map / Model / Protocol: `configs/p2c_dualpath_world.model`, `configs/p2c_dualpath_world.yaml`, `configs/p2c_dualpath_world.pgm`, `configs/p2c_pilot_protocol.yaml`

---

## 1. Scope, Positioning & Methodological Clarification

This report presents the empirical findings of the Milestone P2c Feasibility Pilot on an asymmetric dual-path non-line-of-sight (NLOS) navigation environment.

### 1.1 Separation of Evidence Types
- **Analytical Model (`reports/evidence/p2c_analytical/`)**: Evaluates policy decision logic under idealized constant-velocity kinematic abstractions ($0.25\,\text{m/s}$ avg velocity, nominal segment geometry). Serves strictly as a deterministic unit baseline for policy logic demonstration.
- **Physical ROS 2 / Gazebo Simulation (`reports/evidence/p2c_pilot/`)**: Fully authentic end-to-end physical execution in Gazebo 11 with ROS 2 Humble Nav2, AMCL particle filter localization, LiDAR ray tracing, Nav2 global costmap updates, and continuous odometry/ground-truth trajectory integration.
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
- **Path A (North Short Corridor)**: Nominal polyline length $6.124\,\text{m}$, passing through Chokepoint A at $(0.00, 1.20)$. Doorway opening width is $0.80\,\text{m}$ ($Y \in [0.80, 1.60]$).
- **Path B (South Detour Corridor)**: Nominal polyline length $9.105\,\text{m}$, passing along $Y=-2.40$, completely open.
- **Obstacle & Robot Dimensions**: TurtleBot3 Waffle footprint diameter $\approx 0.44\,\text{m}$, inflation radius $0.35\,\text{m}$. Blockage box size $0.40 \times 1.00 \times 0.60\,\text{m}$ at $(0.00, 1.20, 0.30)$ leaves $\le 0.10\,\text{m}$ clearance, guaranteeing physical and costmap blockage without leaks when present, and smooth passage when absent.

### 2.2 Sightline Occlusion Proof
From $J_0 (-2.50, 0.00)$ to Chokepoint A $(0.00, 1.20)$, the ray equation is $x(t) = -2.5 + 2.5t, y(t) = 1.2t$.  
At $x = -1.80$ ($t = 0.28$), $y = 0.336\,\text{m} \in [-1.00, +0.40]$.  
The ray strikes the solid central island wall, verifying $100\%$ physical line-of-sight occlusion.  
In real ROS 2 simulation at $J_0$, LiDAR ray projection confirms instantaneous local sensor observation is strictly **`UNKNOWN`** (`DOORWAY_NOT_IN_FOV_OR_OCCLUDED`).

### 2.3 Nav2 Costmap Shared State Audit
- In Scenario D1, when the robot probes Chokepoint A, the Nav2 global costmap registers lethal obstacle cells inside the doorway opening.
- After retreating to $J_0$, the global costmap retains these lethal cells (`COSTMAP_AFTER_RETREAT_TO_J0`).
- In Scenario D2, when the obstacle is removed and probed, opening center lethal cells drop to 0 and traversing rays reach Room 2 (`COSTMAP_PROBE_CLEARED_AT_CHOKEPOINT`).

---

## 3. Legacy Audit vs. Final Physical Benchmark Comparison

| Dataset ID | Execution Type | Protocol Frozen | Checksums SHA256 | Stopping Thresholds | Audit Outcome | Audit Verdict / Failure Reason |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `p2c_pilot_20260930_051359_16dd42` | Physical ROS | ❌ Missing | ❌ Missing | Relaxed ($0.05/0.08$) | ❌ REJECTED | Missing frozen protocol snapshot & checksums (UNVERIFIABLE) |
| `p2c_pilot_20260930_051709_dc4324` | Physical ROS | ❌ Missing | ❌ Missing | Relaxed ($0.05/0.08$) | ❌ REJECTED | Missing frozen protocol snapshot & checksums (UNVERIFIABLE) |
| `p2c_pilot_20260930_052812_f14f2b` | Physical ROS | ⚠️ Incomplete | ⚠️ Incomplete | Strict ($0.05/0.08$) | ❌ REJECTED | Missing trajectory artifacts & checksum tree |
| `p2c_pilot_20260930_102323_62b40e` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **Strict ($0.05/0.08$)** | **✅ 10/10 PASS** | **100% Artifacts Complete, SHA256 Verified, All Episodes Valid** |

---

## 4. Real ROS 2 Physical Execution Results (10-Episode Matrix)

All 10 episodes were executed inside Docker container `failmem_humble` (`run_id: p2c_pilot_20260930_102323_62b40e`). Real distances are integrated from continuous odometry, and real durations are measured via simulation `/clock`.

| Scenario | Method | Description | Decision Route | Dead-End Traversals | History Dist ($m$) | History Time ($s$) | Decision Dist ($m$) | Decision Time ($s$) | Total Dist ($m$) | Total Time ($s$) | Physical Arrival | Episode Valid |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0 (Fresh)** | **R** | Reactive Only | Path A | 0 | 0.00 | 0.00 | 6.18 | 50.60 | 6.18 | 50.60 | **True** | **True** |
| **D0 (Fresh)** | **O** | Spatial Obs Cache | Path A | 0 | 0.00 | 0.00 | 6.17 | 49.30 | 6.17 | 49.30 | **True** | **True** |
| **D0 (Fresh)** | **F** | FailMem Memory | Path A | 0 | 0.00 | 0.00 | 6.15 | 52.10 | 6.15 | 52.10 | **True** | **True** |
| **D1 (Blocked)** | **R** | Reactive Only | Path B (Fallback) | 0 | 4.81 | 45.40 | 7.84 | 49.10 | 12.65 | 94.50 | **True** | **True** |
| **D1 (Blocked)** | **O** | Spatial Obs Cache | Path B (Bypass) | 0 | 4.79 | 45.30 | 7.82 | 49.50 | 12.61 | 94.80 | **True** | **True** |
| **D1 (Blocked)** | **F** | FailMem Memory | Path B (Bypass) | 0 | 4.82 | 49.80 | 7.86 | 52.10 | 12.68 | 101.90 | **True** | **True** |
| **D2 (Cleared)** | **R** | Reactive Only | Path A | 0 | 8.35 | 80.20 | 5.88 | 49.00 | 14.23 | 129.20 | **True** | **True** |
| **D2 (Cleared)** | **O** | Spatial Obs Cache | Path B (Detour) | 0 | 8.32 | 82.30 | 7.90 | 54.10 | 16.22 | 136.40 | **True** | **True** |
| **D2 (Cleared)** | **F** | FailMem Memory | Path A (Restored) | 0 | 8.36 | 80.40 | 5.89 | 49.00 | 14.25 | 129.40 | **True** | **True** |
| **D2 (Cleared)** | **M1**| Persistent Suppression| Path B (Detour) | 0 | 8.32 | 85.20 | 7.96 | 51.50 | 16.28 | 136.70 | **True** | **True** |

---

## 5. Offline Replay & Objective Scoring Summary

The independent replay engine (`scripts/replay_and_score_p2c.py`) evaluated `reports/evidence/p2c_pilot/p2c_pilot_20260930_102323_62b40e/`:

```
=======================================================================
Replaying P2c Run: p2c_pilot_20260930_102323_62b40e
=======================================================================
Checksum File Present: True
Episodes: 10, All Valid: True, All Audit Pass: True
-------------------------------------------------------------------------------------------------------------
| Episode | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| D0_F_ep1   | Path_A             | Path_A             |        0 |        6.15m | True    | True      | True  | True       |
| D0_O_ep1   | Path_A             | Path_A             |        0 |        6.17m | True    | True      | True  | True       |
| D0_R_ep1   | Path_A             | Path_A             |        0 |        6.18m | True    | True      | True  | True       |
| D1_F_ep1   | Path_B             | Path_B             |        0 |       12.68m | True    | True      | True  | True       |
| D1_O_ep1   | Path_B             | Path_B             |        0 |       12.61m | True    | True      | True  | True       |
| D1_R_ep1   | Path_B             | Path_B             |        0 |       12.65m | True    | True      | True  | True       |
| D2_F_ep1   | Path_A             | Path_A             |        0 |       14.25m | True    | True      | True  | True       |
| D2_M1_ep1  | Path_B             | Path_B             |        0 |       16.28m | True    | True      | True  | True       |
| D2_O_ep1   | Path_B             | Path_B             |        0 |       16.22m | True    | True      | True  | True       |
| D2_R_ep1   | Path_A             | Path_A             |        0 |       14.23m | True    | True      | True  | True       |
=============================================================================================================
```

---

## 6. Key Scientific Findings & Discussion

1. **Avoidance of Dead-End Traversal via Prior History**:
   - In Scenario D1, both spatial observation caching (Method O) and failure memory (Method F) successfully utilize historical evidence from the probe stage to route immediately via Path B ($7.82 \sim 7.86\,\text{m}$ decision phase), avoiding speculative entry into the blocked corridor.
   - When purely reactive (Method R), the robot uses the entrance gating observation to trigger fallback at the corridor threshold, completing within the $180\,\text{s}$ budget ($94.5\,\text{s}$).

2. **Empirical Equivalence of O and F in Static Spatial Routing**:
   - In static single-robot environments where obstacles are purely geometric blockages, Method O (Spatial Observation Cache) and Method F (FailMem Failure Memory) demonstrate equivalent routing capability.
   - Failures at static doorways reduce directly to spatial occupancy states. Spatial caching without action-semantic binding is empirically sufficient for optimal routing decisions under static conditions.

3. **Restoration of Short Path via Memory Invalidation**:
   - In Scenario D2, upon clearance of the doorway blockage, Method F invalidates the failure memory and safely restores the shorter Path A route ($14.25\,\text{m}$ total, $129.4\,\text{s}$ duration).
   - In contrast, persistent suppression baseline (Method M1) cannot invalidate historical failure records, incurring permanent detour overhead ($16.28\,\text{m}$ total, $136.7\,\text{s}$ duration, $+2.03\,\text{m}$ detour penalty).

4. **Unverified Hypotheses for Advanced Failure Memory Capabilities**:
   - The theoretical advantage of causal failure memory (beyond spatial caching) remains an unverified hypothesis in static environments.
   - Research extensions to test these hypotheses should target:
     - Kinematic/dynamic failures where space is geometrically free (e.g. slope traction, payload limits, narrow turn radius).
     - Capability asymmetries in heterogeneous multi-agent systems (e.g. small robot can traverse, large robot blocked).
     - Prerequisite-bound actions requiring environmental manipulation prior to re-traversal.

---

## 7. Audit Conclusion

- The Milestone P2c Validity Loop is fully closed.
- Production code in `src/p2c_pipeline.py` is shared across live runner and regression tests (135 passing tests).
- 10/10 physical episodes in `reports/evidence/p2c_pilot/p2c_pilot_20260930_102323_62b40e/` achieved verified physical arrival and $100\%$ audit pass status.

