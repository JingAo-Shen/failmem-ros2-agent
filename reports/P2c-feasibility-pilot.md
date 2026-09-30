# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-09-30  
**Phase**: Milestone P2c Authenticity Audit, Event-Driven Failure Architecture & Minimal ROS 2 Verification  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.1, SHA256: `3bb66e51fb7fd4e8184bc511a993842a35dabab0d8b8ea719ab67b7c87d9b775`)  
**Evidence Artifacts**:
- Verified Minimal Physical ROS 2 Runs:
  - `D1_F_ep1`: `reports/evidence/p2c_pilot/p2c_pilot_20260930_151400_e69f0b/`
  - `D2_O_ep1`: `reports/evidence/p2c_pilot/p2c_pilot_20260930_152015_b61bb5/`
  - `D2_F_ep1`: `reports/evidence/p2c_pilot/p2c_pilot_20260930_152709_7f733d/`
- Open vs. Blocked Control Probe Verification: `reports/evidence/p2c_probe_control/probe_control_results.json`
- Analytical Baseline Unit Demonstrations: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`
- Map / Model / Protocol: `configs/p2c_dualpath_world.model`, `configs/p2c_dualpath_world.yaml`, `configs/p2c_dualpath_world.pgm`, `configs/p2c_pilot_protocol.yaml`

---

## 1. Scope, Positioning & Methodological Clarification

This report presents the empirical findings of Milestone P2c on an asymmetric dual-path non-line-of-sight (NLOS) navigation benchmark in ROS 2 Humble and Gazebo 11.

### 1.1 Separation of Evidence Types
- **Analytical Model (`reports/evidence/p2c_analytical/`)**: Evaluates policy decision logic under idealized constant-velocity kinematic abstractions ($0.25\,\text{m/s}$ avg velocity, nominal segment geometry). Serves strictly as a deterministic unit baseline for policy logic demonstration.
- **Physical ROS 2 / Gazebo Simulation (`reports/evidence/p2c_pilot/`)**: Fully authentic end-to-end physical execution in Gazebo 11 with ROS 2 Humble Nav2, AMCL particle filter localization, LiDAR ray tracing, Nav2 global costmap updates, and continuous odometry/ground-truth trajectory integration.
- **Strict Event-Driven Lifecycle**:
  - Reaching the observation vantage point (`hist_reach_obs_vantage`) succeeds and produces live perception evidence, but does **not** register failure memory.
  - Failure memory is registered **only** when chokepoint traversal fails (`hist_attempt_chokepoint_traversal`) with linked `OCCUPIED` perception evidence.
  - Invalidation is strictly event-driven by live perception returning `FREE` ($\ge 8$ traversing rays, 0 obstacle hits, cleared costmap).
- **Status of Hypotheses**: Claims of universal theoretical superiority or Pareto optimality are withdrawn. Findings reflect empirical behaviors observed under the controlled conditions of this specific benchmark.

---

## 2. Authenticity Audit & Legacy Dataset Status

A comprehensive methodological audit identified critical defects in earlier experimental runs, leading to the formal retraction of all 10-episode claims prior to this audit.

### 2.1 Audit Defects Identified in Legacy Suites
1. **Manufactured Traversal Failure**: `execute_chokepoint_traversal_probe` in previous scripts sent direct 2-second `cmd_vel` twists without dispatching a genuine ROS 2 `NavigateToPose` action goal, fabricating a `BUDGET_ABORTED` terminal status code rather than receiving an authentic Nav2 action server response.
2. **Observation Stream Asymmetry**: Method O (Spatial Observation Cache) was overwritten by `UNKNOWN` observations upon retreating to junction $J_0$, whereas Method F retained failure memory across the same transition.
3. **Replay Engine Short-Circuits**: The previous offline replay engine inserted synthetic fallback dictionaries for doorway perception and failure evidence rather than recomputing ray intersections and occupancy strictly from raw laser scan snapshots (`scan_snapshots.json`) and TF transforms (`map -> base_scan`).

### 2.2 Legacy vs. Authentic Benchmark Status Comparison

| Dataset ID | Execution Type | Protocol Frozen | Checksums SHA256 | Failure Authenticity | Audit Verdict | Audit Reason |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `p2c_pilot_20260930_051359_16dd42` | Physical ROS | ❌ Missing | ❌ Missing | ❌ Manufactured | ❌ REJECTED | Missing frozen protocol snapshot & checksums (UNVERIFIABLE) |
| `p2c_pilot_20260930_051709_dc4324` | Physical ROS | ❌ Missing | ❌ Missing | ❌ Manufactured | ❌ REJECTED | Missing frozen protocol snapshot & checksums (UNVERIFIABLE) |
| `p2c_pilot_20260930_052812_f14f2b` | Physical ROS | ⚠️ Incomplete | ⚠️ Incomplete | ❌ Manufactured | ❌ REJECTED | Missing trajectory artifacts & checksum tree |
| `p2c_pilot_20260930_102323_62b40e` | Physical ROS | ✅ Verified | ✅ Verified | ❌ Manufactured | ❌ REJECTED | **Failed Authenticity Audit**: Traversal probe bypassed Nav2 action server; perception stream asymmetric |
| `p2c_pilot_20260930_151400_e69f0b` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS** | **D1_F Minimal Physical Verification: 100% Raw Replay Pass** |
| `p2c_pilot_20260930_152015_b61bb5` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS** | **D2_O Minimal Physical Verification: 100% Raw Replay Pass** |
| `p2c_pilot_20260930_152709_7f733d` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS** | **D2_F Minimal Physical Verification: 100% Raw Replay Pass** |

---

## 3. Authentic Event-Driven Failure Architecture

### 3.1 Genuine Nav2 Action Server Traversal & Probe Control
- Traversal probing (`hist_attempt_chokepoint_traversal`) is standardized via `build_chokepoint_probe_action` (`goal=[0.50, 1.20, 0.0]`, `timeout=15.0s`, Nav2 action client) across both runner and verification harnesses.
- The open vs. blocked control probe test (`scripts/verify_p2c_probe_control.py`) establishes causal fidelity:
  - **Open Condition**: Nav2 navigates towards `[0.50, 1.20, 0.0]` through the clear doorway; action succeeds (`SUCCEEDED`, physical arrival confirmed), and perception verifies `FREE` (30 pass-through rays).
  - **Blocked Condition**: The identical navigation action is dispatched with the doorway obstacle spawned; Nav2 is physically blocked by lethal costmap cells, times out / cancels (`CANCELED`, `BUDGET_DEADLINE_EXCEEDED`), and perception verifies `OCCUPIED` (51 obstacle hits inside doorway bounding box).
  - `both_passed = True` confirms identical execution configuration without manufactured outcomes.

### 3.2 Strict Invalid-History Hard-Stop
- If history acquisition fails to produce protocol-compliant physical evidence (e.g. traversal does not fail with verified `OCCUPIED` perception, or clearance does not produce verified `FREE` perception), the episode **halts immediately**.
- The runner logs `[HARD STOP] History acquisition invalid!`, dispatches **0 decision goals**, sets `chosen_route = "HISTORY_INVALID_ABORTED"`, serializes all 7 artifacts, and marks `episode_valid = False`.
- In trial run `p2c_pilot_20260930_151730_bdebfd`, when clearance validation failed, the pipeline halted immediately with 0 decision dispatches, yielding `data_valid=False`, `audit_pass=False`, demonstrating strict zero tolerance for invalid history.

### 3.3 Symmetric Observation Stream
- `SpatialObservationCache` and `FailureMemoryStore` consume the identical time-aligned perception stream.
- In both models, instantaneous `UNKNOWN` observations (such as sightline occlusion from junction $J_0$) do **not** overwrite previously acquired known state (`OCCUPIED` or `FREE`).
- In Scenario D2, upon observing `FREE` during the clearance probe, $O$ caches `FREE` and $F$ invalidates failure memory. When retreating to $J_0$, both methods retain the cleared state and select Path A during the decision phase.

---

## 4. Minimal Physical ROS 2 Execution Results

The minimal physical matrix (`D1_F`, `D2_O`, `D2_F`) was executed inside Docker container `failmem_humble`. Distances are integrated from continuous `/odom`, durations are measured from `/clock`, and perception is captured via raw `/scan` snapshots with synchronized AMCL TF poses.

| Episode ID | Scenario | Method | Requested Route | Actual Route | Dead-End Traversals | History Dist ($m$) | History Time ($s$) | Decision Dist ($m$) | Decision Time ($s$) | Total Dist ($m$) | Total Time ($s$) | Final Success | Episode Valid | Audit Verdict |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `D1_F_ep1` | **D1 (Blocked)** | **F (FailMem)** | Path B | Path B | 0 | 6.09 | 59.10 | 7.62 | 50.40 | 13.71 | 109.50 | **True** | **True** | **✅ AUDIT PASS** |
| `D2_O_ep1` | **D2 (Cleared)** | **O (Spatial Cache)**| Path A | Path A | 0 | 9.97 | 91.30 | 5.90 | 55.70 | 15.87 | 147.00 | **True** | **True** | **✅ AUDIT PASS** |
| `D2_F_ep1` | **D2 (Cleared)** | **F (FailMem)** | Path A | Path A | 0 | 10.02 | 96.50 | 5.88 | 49.70 | 15.90 | 146.20 | **True** | **True** | **✅ AUDIT PASS** |

---

## 5. Offline Replay & Objective Scoring Verification

The independent replay engine (`scripts/replay_and_score_p2c.py`) evaluated the verified physical evidence runs without synthetic fallbacks:
1. **Artifact Completeness**: Verified the presence of all 7 mandatory artifacts (`action_result.json`, `trajectory.json`, `costmap_snapshots.json`, `scan_snapshots.json`, `stability_window.json`, `memory_events.json`, `runtime_protocol.json`).
2. **SHA256 Integrity**: Validated full SHA256 checksum tree against `checksums.sha256`.
3. **Raw Costmap ROI Recalculation**: Recomputed doorway subgrid cell counts directly from raw 2D `subgrid_matrix` via `recompute_costmap_subgrid_stats`, verifying exact zero-tolerance match with recorded aggregates.
4. **Raw Perception Recomputation**: Recomputed doorway ray intersections and 3-valued occupancy directly from raw laser ranges and AMCL TF poses.
5. **Memory Event Reconstruction**: Reconstructed `FailureMemoryStore` and `SpatialObservationCache` event lifecycles step-by-step from raw recomputed perception events, verifying perfect alignment with recorded memory events.
6. **Unified Audit Verdict**: Consolidated perception, history, causal correlation, policy, route, budget, and integrity checks into a single verdict in `P2cEpisodeEvaluator.evaluate_episode`. Any failure strictly enforces `audit_pass = False`.

```
=======================================================================
Replaying P2c Run: p2c_pilot_20260930_151400_e69f0b (D1_F)
Checksum File Present: True, All Valid: True, All Audit Pass: True
| Episode  | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| D1_F_ep1 | Path_B    | Path_B    |        0 |        13.71m | True    | True      | True  | True       |
=======================================================================
Replaying P2c Run: p2c_pilot_20260930_152015_b61bb5 (D2_O)
Checksum File Present: True, All Valid: True, All Audit Pass: True
| Episode  | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| D2_O_ep1 | Path_A    | Path_A    |        0 |        15.87m | True    | True      | True  | True       |
=======================================================================
Replaying P2c Run: p2c_pilot_20260930_152709_7f733d (D2_F)
Checksum File Present: True, All Valid: True, All Audit Pass: True
| Episode  | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| D2_F_ep1 | Path_A    | Path_A    |        0 |        15.90m | True    | True      | True  | True       |
=======================================================================
```

### 5.1 Negative Acceptance Testing
To guarantee that the audit replay engine cannot be bypassed by tampered artifacts or corrupted lifecycles, 7 negative test cases were implemented in `tests/test_p2c_event_driven.py` and executed against isolated temporary sandbox copies of production runs:

| Test Function | Tampering Mutation | Replay Engine Detection | Audit Verdict |
| :--- | :--- | :--- | :---: |
| `test_negative_1_tampered_action_terminal_status_replay_fail` | Action terminal status altered from `CANCELED` $\to$ `SUCCEEDED` | `ACTION_OUTCOME_MISMATCH` / `DISPATCH_COUNT_MISMATCH` | ❌ `audit_pass = False` |
| `test_negative_2_missing_decision_j0_snapshot_replay_fail` | Deleted `DECISION_J0` raw perception snapshot | `MISSING_DECISION_J0_PERCEPTION_SNAPSHOT` | ❌ `audit_pass = False` |
| `test_negative_3_memory_event_without_causal_action_replay_fail` | Inserted orphan `RECORD_FAILURE` event without failed action | `UNEXPECTED_MEMORY_EVENTS_IN_D0` | ❌ `audit_pass = False` |
| `test_negative_4_stale_observation_timestamp_replay_fail` | Observation timestamp set $15.0\,\text{s}$ prior to action failure | `STALE_FAILURE_PERCEPTION_TIMESTAMP` | ❌ `audit_pass = False` |
| `test_negative_5_costmap_roi_subgrid_discrepancy_replay_fail` | Costmap summary says 0 lethal cells while raw subgrid has 100s | `COSTMAP_SUBGRID_DISCREPANCY` | ❌ `audit_pass = False` |
| `test_negative_6_d2_false_clearance_replay_fail` | Raw laser scan hits obstacle while runner recorded `FREE` | `PERCEPTION_RECOMPUTE_MISMATCH` | ❌ `audit_pass = False` |
| `test_negative_7_checksum_tampered_file_replay_fail` | Modified `action_result.json` payload without updating checksum | `HASH_MISMATCH` | ❌ `audit_pass = False` |

All 7 negative acceptance tests passed with 100% rejection accuracy.

---

## 6. Key Scientific Findings & Discussion

1. **Dead-End Avoidance via Authentic Failure History**:
   - In Scenario D1, FailMem ($F$) utilizes historical failure evidence bound to the failed traversal probe to select Path B immediately ($7.62\,\text{m}$ decision phase), avoiding speculative re-entry into the blocked corridor.
2. **Empirical Equivalence of O and F in Static Spatial Routing**:
   - In static environments where failures stem strictly from geometric blockage, spatial observation caching ($O$) and failure memory ($F$) demonstrate equivalent routing efficacy. Both restore the shorter Path A route in Scenario D2 ($15.87\,\text{m}$ vs. $15.90\,\text{m}$) once clearance is observed.
3. **Restoration of Short Path via Event-Driven Invalidation**:
   - Live perception returning `FREE` ($\ge 8$ traversing rays, 0 obstacle hits, cleared costmap) reliably invalidates failure memory entries in $F$, eliminating permanent detour suppression without manual state resets.
4. **Unverified Hypotheses for Advanced Failure Memory Capabilities**:
   - The specific advantage of causal failure memory (beyond spatial caching) remains an unverified hypothesis in static environments and requires domain extensions to:
     - Kinematic/dynamic failures where space is geometrically free (e.g. slope traction loss, payload limits, turn radius limits).
     - Capability asymmetries in heterogeneous multi-agent systems.
     - Prerequisite-bound actions requiring environmental manipulation prior to re-traversal.

---

## 7. Audit Conclusion

- The authenticity audit and offline replay verification loop have been fully closed and validated.
- All manufactured failure mocks have been replaced by standardized Nav2 action server goals, feedback, and terminal status evaluation.
- The open vs. blocked control probe confirms causal fidelity with identical execution parameters.
- Minimal physical ROS 2 runs (`D1_F`, `D2_O`, `D2_F`) achieved 100% physical arrival, 100% valid execution, and 100% offline replay pass from first-principles raw LiDAR, costmap subgrid, and TF recalculations.
- 7 negative acceptance tests confirmed the strictness and non-bypassability of the unified offline audit verdict.

