# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-10-01  
**Phase**: Milestone P2c Authenticity Audit, Immutable Observation Bundles, Event-Driven Memory Architecture & Physical ROS 2 Verification  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.1, SHA256: `3bb66e51fb7fd4e8184bc511a993842a35dabab0d8b8ea719ab67b7c87d9b775`)  
**Evidence Artifacts**:
- Physical ROS 2 Single-Attempt Sampling Runs:
  - `D1_F_ep1`: `reports/evidence/p2c_pilot/p2c_pilot_20261001_014832_2efcc7/`
  - `D2_O_ep1`: `reports/evidence/p2c_pilot/p2c_pilot_20261001_015054_e95996/`
  - `D2_F_ep1`: `reports/evidence/p2c_pilot/p2c_pilot_20261001_015349_2f521f/`
- Open vs. Blocked Control Probe Verification: `reports/evidence/p2c_probe_control/probe_control_results.json`
- Analytical Baseline Demonstrations: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`
- Map / Model / Protocol: `configs/p2c_dualpath_world.model`, `configs/p2c_dualpath_world.yaml`, `configs/p2c_dualpath_world.pgm`, `configs/p2c_pilot_protocol.yaml`

---

## 1. Scope, Positioning & Methodological Clarification

This report presents empirical findings of Milestone P2c on an asymmetric dual-path non-line-of-sight (NLOS) navigation benchmark in ROS 2 Humble and Gazebo 11.

### 1.1 Separation of Evidence Types
- **Analytical Model (`reports/evidence/p2c_analytical/`)**: Evaluates policy decision logic under idealized constant-velocity kinematic abstractions ($0.25\,\text{m/s}$ avg velocity, nominal segment geometry). Serves as a deterministic baseline for policy logic demonstration.
- **Physical ROS 2 / Gazebo Simulation (`reports/evidence/p2c_pilot/`)**: Authentic physical execution in Gazebo 11 with ROS 2 Humble Nav2, AMCL particle filter localization, LiDAR ray tracing, Nav2 global costmap updates, and continuous odometry/ground-truth trajectory integration.
- **Immutable Observation Bundle**:
  - `create_observation_bundle` is captured first, followed immediately by `evaluate_observation_bundle`. Online decision-making and serialization share the exact same bundle object.
  - Bundles preserve `observation_id`, raw `scan_data`, matching `tf_transform`, raw `costmap_roi` (`subgrid_matrix` & metadata), `msg_times`, `capture_times`, and `evaluation_times` with untruncated float precision.
  - In replay, costmap summaries are recalculated directly from `costmap_roi.subgrid_matrix` via `recompute_costmap_subgrid_stats`, ignoring any recorded summary.
- **Strict Event-Driven Lifecycle**:
  - Reaching the observation vantage point (`hist_reach_obs_vantage`) succeeds and produces live perception evidence, but does **not** register failure memory.
  - Failure memory is registered **only** when chokepoint traversal fails (`hist_attempt_chokepoint_traversal`) with linked `OCCUPIED` perception evidence.
  - Invalidation is strictly event-driven by subsequent live perception returning `FREE` ($\ge 8$ traversing rays, 0 obstacle hits, cleared costmap).
- **Scope of Claims**: Empirical behaviors are reported for the evaluated benchmark scenario. Claims of universal superiority or generalized equivalence across arbitrary topologies are not made.

---

## 2. Authenticity Audit & Legacy Dataset Status

A methodological audit identified defects in earlier experimental runs, leading to the designation of all legacy suites lacking immutable observation bundles as `UNVERIFIABLE` (not backfilled).

### 2.1 Audit Defects Identified in Legacy Suites
1. **Manufactured Traversal Failure**: Earlier scripts sent direct `cmd_vel` twists without dispatching a genuine ROS 2 `NavigateToPose` action goal, generating synthetic failure return values rather than receiving an authentic Nav2 action server outcome.
2. **Observation Stream Asymmetry**: Method O (Spatial Observation Cache) was overwritten by `UNKNOWN` observations upon retreating to junction $J_0$, whereas Method F retained failure memory across the same transition.
3. **Decoupled Perception Snapshots**: Perception snapshots were re-read after evaluation rather than sharing an immutable observation bundle, preventing independent verification of sensor age and raw subgrid cell occupancy.

### 2.2 Dataset Verification Matrix

| Dataset ID | Execution Type | Immutable Bundles | Frozen Protocol | Checksums SHA256 | Failure Authenticity | Replay Verdict | Reason |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `p2c_pilot_20260930_051359_16dd42` | Physical ROS | ❌ Missing | ❌ Missing | ❌ Missing | ❌ Manufactured | ❌ REJECTED | Missing frozen protocol snapshot & checksums (`UNVERIFIABLE`) |
| `p2c_pilot_20260930_051709_dc4324` | Physical ROS | ❌ Missing | ❌ Missing | ❌ Missing | ❌ Manufactured | ❌ REJECTED | Missing frozen protocol snapshot & checksums (`UNVERIFIABLE`) |
| `p2c_pilot_20260930_052812_f14f2b` | Physical ROS | ❌ Missing | ⚠️ Incomplete | ⚠️ Incomplete | ❌ Manufactured | ❌ REJECTED | Missing trajectory artifacts & checksum tree (`UNVERIFIABLE`) |
| `p2c_pilot_20260930_102323_62b40e` | Physical ROS | ❌ Missing | ✅ Verified | ✅ Verified | ❌ Manufactured | ❌ REJECTED | Lacks immutable observation bundles & authentic Nav2 failure (`UNVERIFIABLE`) |
| `p2c_pilot_20261001_014832_2efcc7` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS** | **D1_F Single-Attempt Physical Sampling Run** |
| `p2c_pilot_20261001_015054_e95996` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS** | **D2_O Single-Attempt Physical Sampling Run** |
| `p2c_pilot_20261001_015349_2f521f` | **Physical ROS** | **✅ Verified** | **✅ Verified** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS** | **D2_F Single-Attempt Physical Sampling Run** |

---

## 3. Authentic Event-Driven Failure Architecture

### 3.1 Genuine Nav2 Action Server Traversal & Probe Control
- Traversal probing (`hist_attempt_chokepoint_traversal`) is dispatched via `build_chokepoint_probe_action` (`goal=[0.50, 1.20, 0.0]`, `timeout=15.0s`, Nav2 action client) across both runner and verification harnesses.
- The open vs. blocked control probe test (`scripts/verify_p2c_probe_control.py`) demonstrates causal distinction:
  - **Open Condition**: Nav2 navigates towards `[0.50, 1.20, 0.0]` through the clear doorway; action succeeds (`SUCCEEDED`, physical arrival confirmed), and perception verifies `FREE` (30 pass-through rays).
  - **Blocked Condition**: The identical navigation action is dispatched with the doorway obstacle spawned; Nav2 is physically blocked by lethal costmap cells, times out (`BUDGET_DEADLINE_EXCEEDED`), and perception verifies `OCCUPIED` (laser hits inside doorway bounding box).
  - `both_passed = True` confirms identical execution configuration without manufactured outcomes.

### 3.2 Strict Invalid-History Hard-Stop
- If history acquisition fails to produce protocol-compliant physical evidence (e.g. traversal does not fail with verified `OCCUPIED` perception, or clearance does not produce verified `FREE` perception), the episode **halts immediately**.
- The runner logs `[HARD STOP] History acquisition invalid!`, dispatches **0 decision goals**, sets `chosen_route = "HISTORY_INVALID_ABORTED"`, serializes all 7 artifacts, and marks `episode_valid = False`.

### 3.3 Symmetric Observation Stream
- `SpatialObservationCache` and `FailureMemoryStore` consume the identical time-aligned perception stream.
- In both models, instantaneous `UNKNOWN` observations (such as sightline occlusion from junction $J_0$) do **not** overwrite previously acquired known state (`OCCUPIED` or `FREE`).
- In Scenario D2, upon observing `FREE` during the clearance probe, $O$ caches `FREE` and $F$ invalidates failure memory. When retreating to $J_0$, both methods retain the cleared state and select Path A during the decision phase.

---

## 4. Single-Attempt Physical Matrix Sampling Results

The physical matrix (`D1_F`, `D2_O`, `D2_F`) was sampled exactly once per condition inside Docker container `failmem_humble` without iterative retries or cherry-picking. Distances are integrated from continuous `/odom`, durations are measured from `/clock`, and perception is evaluated via immutable observation bundles with synchronized AMCL TF poses.

| Episode ID | Scenario | Method | Requested Route | Actual Route | Dead-End Traversals | History Dist ($m$) | History Time ($s$) | Decision Dist ($m$) | Decision Time ($s$) | Total Dist ($m$) | Total Time ($s$) | Goal Arrived | Episode Valid | Audit Verdict |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `D1_F_ep1` | **D1 (Blocked)** | **F (FailMem)** | Path B | Path B | 0 | 6.45 | 59.90 | 7.50 | 47.50 | 13.95 | 107.40 | **True** | **True** | **✅ AUDIT PASS** |
| `D2_O_ep1` | **D2 (Cleared)** | **O (Spatial Cache)**| Path A | Path A | 0 | 10.23 | 94.10 | 5.95 | 48.60 | 16.18 | 142.70 | **True** | **True** | **✅ AUDIT PASS** |
| `D2_F_ep1` | **D2 (Cleared)** | **F (FailMem)** | Path A | Path A | 0 | 10.29 | 96.20 | 5.95 | 49.20 | 16.25 | 145.40 | **True** | **True** | **✅ AUDIT PASS** |

---

## 5. Offline Replay & Objective Scoring Verification

The independent replay engine (`scripts/replay_and_score_p2c.py`) evaluates physical evidence runs from first principles:
1. **Artifact Completeness**: Verifies presence of all 7 mandatory artifacts (`action_result.json`, `trajectory.json`, `costmap_snapshots.json`, `scan_snapshots.json`, `stability_window.json`, `memory_events.json`, `runtime_protocol.json`).
2. **SHA256 Integrity**: Validates SHA256 checksum tree against `checksums.sha256`.
3. **Raw Costmap ROI Recalculation**: Recomputes doorway subgrid cell counts directly from raw 2D `subgrid_matrix` via `recompute_costmap_subgrid_stats`, rejecting discrepancies (`COSTMAP_BUNDLE_ROI_DISCREPANCY`).
4. **Raw Perception Recomputation**: Recomputes doorway ray intersections and 3-valued occupancy directly from raw laser ranges, AMCL TF poses, and raw costmap ROI.
5. **Strict Chronological Memory Lifecycle**:
   - Reconstructs `FailureMemoryStore` step-by-step in chronological sequence ($t_i \le t_{i+1}$).
   - Verifies explicit bindings: `failed_action_id`, `goal_uuid`, `observation_id`, `memory_id`, `region_id`, `map_version`.
   - Invalidation requires existing active memory and subsequent verified `FREE` observation. Replay rejects duplicate events, orphan invalidations, and premature invalidation ($t_{inv} \le t_{fail}$).
   - Evaluates policy decisions at $t_{dec}$ using only events prior to $t_{dec}$ (future observations cannot alter past decisions).
6. **Unified Audit Verdict**: Aggregates all checks into a single verdict in `P2cEpisodeEvaluator.evaluate_episode`. Any check failure enforces `audit_pass = False`.

```
=======================================================================
Replaying P2c Run: p2c_pilot_20261001_014832_2efcc7 (D1_F)
Checksum File Present: True, All Valid: True, All Audit Pass: True
| Episode  | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| D1_F_ep1 | Path_B    | Path_B    |        0 |        13.95m | True    | True      | True  | True       |
=======================================================================
Replaying P2c Run: p2c_pilot_20261001_015054_e95996 (D2_O)
Checksum File Present: True, All Valid: True, All Audit Pass: True
| Episode  | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| D2_O_ep1 | Path_A    | Path_A    |        0 |        16.18m | True    | True      | True  | True       |
=======================================================================
Replaying P2c Run: p2c_pilot_20261001_015349_2f521f (D2_F)
Checksum File Present: True, All Valid: True, All Audit Pass: True
| Episode  | Req Route | Act Route | Dead-End | Replayed Dist | Goal OK | Budget OK | Valid | Audit Pass |
| D2_F_ep1 | Path_A    | Path_A    |        0 |        16.25m | True    | True      | True  | True       |
=======================================================================
```

### 5.1 Paired Positive-Negative Acceptance Testing

To ensure the replayer strictly detects corruptions and contract violations, 11 paired positive-negative tests were implemented in `tests/test_p2c_event_driven.py`. Each test verifies that the unmodified base fixture passes audit before asserting that a single mutation causes replay failure:

| Test Name | Mutation Description | Target Rejection Code | Audit Verdict |
| :--- | :--- | :--- | :---: |
| `test_negative_pair_1_tampered_memory_id_binding` | Mutates `memory_id` in failure/invalidation event | `MISMATCHED_INVALIDATED_MEMORY_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_2_tampered_goal_uuid_binding` | Mutates `goal_uuid` binding in recorded failure | `MISMATCHED_GOAL_UUID_BINDING` | ❌ `audit_pass = False` |
| `test_negative_pair_3_tampered_observation_id_binding` | Mutates `observation_id` linked to failure perception | `MISMATCHED_OBSERVATION_ID_BINDING` | ❌ `audit_pass = False` |
| `test_negative_pair_4_duplicate_record_failure` | Injects duplicate `RECORD_FAILURE` event in D1 | `DUPLICATE_RECORD_FAILURE_EVENT` | ❌ `audit_pass = False` |
| `test_negative_pair_5_invalidation_before_failure` | Sets invalidation timestamp before failure event | `UNSORTED_OR_PREMATURE_MEMORY_EVENT` | ❌ `audit_pass = False` |
| `test_negative_pair_6_future_free_does_not_alter_past_decision` | Appends post-decision `FREE` bundle; asserts past decision unchanged | `POLICY_DECISION_MISMATCH` (if altered) | ❌ `audit_pass = False` |
| `test_negative_pair_7_orphan_invalidation_without_free_evidence` | Records invalidation without matching `FREE` bundle | `INVALIDATION_EVIDENCE_NOT_FREE` | ❌ `audit_pass = False` |
| `test_negative_pair_8_tampered_bundle_costmap_summary_without_raw_roi` | Tampers recorded costmap summary without altering raw subgrid | `COSTMAP_BUNDLE_ROI_DISCREPANCY` | ❌ `audit_pass = False` |
| `test_negative_pair_9_stale_scan_timestamp_exceeds_threshold` | Sets scan timestamp $>1.5\,\text{s}$ prior to evaluation time | `STALE_SCAN_TIMESTAMP_IN_BUNDLE` | ❌ `audit_pass = False` |
| `test_negative_pair_10_hash_tampered_file_without_checksum_update` | Mutates payload without updating checksum file | `HASH_MISMATCH` | ❌ `audit_pass = False` |
| `test_negative_pair_11_missing_decision_j0_snapshot` | Removes mandatory `DECISION_J0` observation bundle | `MISSING_DECISION_J0_PERCEPTION_SNAPSHOT` | ❌ `audit_pass = False` |

All 11 paired tests pass in the automated test suite.

---

## 6. Key Empirical Findings & Discussion

1. **Dead-End Avoidance under Confirmed Blockage (D1)**:
   - In Scenario D1, FailMem ($F$) utilizes historical failure evidence bound to the failed traversal probe to select Path B ($7.50\,\text{m}$ decision phase), avoiding repetitive entry into the blocked corridor.
2. **Behavior of O and F in D2 Sampling Runs**:
   - In the sampled D2 runs, following verified doorway clearance, both Method O (Spatial Observation Cache) and Method F (FailMem) selected Path A ($5.95\,\text{m}$ decision phase, total distances $16.18\,\text{m}$ and $16.25\,\text{m}$ respectively).
   - In this static geometric clearance scenario, both mechanisms restored the shorter route upon observing `FREE` evidence. This reflects empirical routing behavior on the current dual-path layout rather than generalized mathematical equivalence across arbitrary network topologies.
3. **Event-Driven Memory Invalidation**:
   - Verified `FREE` observations ($\ge 8$ traversing rays, 0 obstacle hits, cleared costmap) consistently invalidated failure memory in $F$, preventing persistent detour suppression after environmental restoration.
4. **Scope for Future Research on Differentiated Failure Modalities**:
   - The distinction between causal failure memory and spatial occupancy caching becomes critical in scenarios involving:
     - Non-spatial or dynamic failure modes (e.g. terrain slippage, payload capacity, actuator limits).
     - Heterogeneous multi-agent coordination with agent-specific traversability.
     - Environmental prerequisites requiring external manipulation before re-attempting an action.

---

## 7. Conclusion

- The three acceptance criteria for Milestone P2c have been met:
  1. **Immutable Observation Bundles**: Raw scan, TF, and raw costmap ROI subgrids are captured prior to evaluation and shared identically between online execution and disk serialization.
  2. **Chronological Memory Replay**: Offline replayer reconstructs memory events strictly in time sequence with exact ID bindings, duplicate detection, and premature invalidation rejection.
  3. **Paired Positive-Negative Testing**: 11 paired tests verify rejection of corrupted, tampered, or desynchronized evidence.
- Physical sampling of `D1_F`, `D2_O`, and `D2_F` (1 run each) completed cleanly with verified arrival, zero dead-end traversals, and full offline replay pass.
