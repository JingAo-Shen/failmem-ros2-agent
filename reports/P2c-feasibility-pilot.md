# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-10-01  
**Phase**: Milestone P2c Authenticity Audit, Immutable Observation Bundles, Event-Driven Memory Architecture & 30-Run Comparative Experiment  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.2, SHA256: `fdbe35c90e53b0e80fa106cdee06d942033491cb212a616df815efc7c0b37a5f`)  
**Frozen Environment Checksums**:
- World Model: `configs/p2c_dualpath_world.model` (SHA256: `7b5d5638bbe4ecc17a18cec3c7cb38750c6bb513ce6be296a3ee4634129486f4`)
- Map YAML: `configs/p2c_dualpath_world.yaml` (SHA256: `f517f75c2b674bde8388d59866d7c0479bf5d59586b98231828ce6523c3445ce`)
- Map PGM: `configs/p2c_dualpath_world.pgm` (SHA256: `51bb9141354f494f25d8819e18fea735c18e811197a987b6d544d667d8bc4d43`)
- Nav2 Parameters: `configs/nav2_params.yaml` (SHA256: `f27cffe253064202d0dc6bf7a93f47a2243b96afddade72e798d6477bb0471d8`)

**Evidence Artifacts**:
- **30-Run Comparative Physical Experiment Batch**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/` (10 conditions $\times$ 3 repeats = 30 episodes, 100% Valid & 100% Audit Pass)
- Open vs. Blocked Control Probe Verification: `reports/evidence/p2c_probe_control/probe_control_results.json`
- Analytical Baseline Demonstrations: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`

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
| `p2c_pilot_20261001_022711_0d3c35` | **Physical ROS (30 Runs)** | **✅ Verified** | **✅ Verified (v4.2)** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS (30/30)** | **Complete 30-Run Comparative Experiment Matrix** |

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

## 4. 30-Run Comparative Experiment Matrix Results

The full comparative experiment matrix (10 conditions $\times$ 3 repetitions = 30 physical episodes) was executed in Gazebo 11 / ROS 2 Humble under Protocol `v4.2` (`p2c_pilot_20261001_022711_0d3c35`). Zero runs were discarded or retried.

### 4.1 Condition-Level Aggregated Metrics

| Scenario | Method | Runs | Selected Route | Actual Route | Dead-End Traversals | Decision Dist ($m$) | Decision Sim Time ($s$) | Total Dist ($m$) | Total Sim Time ($s$) | Arrival Rate | Budget OK | Valid Rate | Audit Pass Rate |
| :--- | :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0** | **R** (Reactive) | 3 | Path_A | Path_A | 0.0 | $6.16 \pm 0.03$ | $51.5 \pm 1.4$ | $6.16 \pm 0.03$ | $51.5 \pm 1.4$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D0** | **O** (Obs Cache) | 3 | Path_A | Path_A | 0.0 | $6.20 \pm 0.01$ | $50.0 \pm 0.7$ | $6.20 \pm 0.01$ | $50.0 \pm 0.7$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D0** | **F** (FailMem) | 3 | Path_A | Path_A | 0.0 | $6.20 \pm 0.02$ | $49.9 \pm 0.4$ | $6.20 \pm 0.02$ | $49.9 \pm 0.4$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D1** | **R** (Reactive) | 3 | Path_A_then_Path_B | Path_A_then_Path_B | **1.0** | **$10.82 \pm 0.06$** | **$82.1 \pm 3.6$** | **$17.22 \pm 0.20$** | **$141.0 \pm 4.8$** | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D1** | **O** (Obs Cache) | 3 | Path_B | Path_B | 0.0 | $7.55 \pm 0.04$ | $50.0 \pm 1.6$ | $13.95 \pm 0.06$ | $108.7 \pm 2.2$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D1** | **F** (FailMem) | 3 | Path_B | Path_B | 0.0 | $7.54 \pm 0.00$ | $48.2 \pm 0.8$ | $14.03 \pm 0.21$ | $109.5 \pm 1.3$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2** | **R** (Reactive) | 3 | Path_A | Path_A | 0.0 | $5.92 \pm 0.04$ | $49.6 \pm 1.3$ | $16.34 \pm 0.03$ | $148.2 \pm 2.6$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2** | **O** (Obs Cache) | 3 | Path_A | Path_A | 0.0 | $5.94 \pm 0.05$ | $52.0 \pm 1.4$ | $16.40 \pm 0.20$ | $149.8 \pm 0.4$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2** | **F** (FailMem) | 3 | Path_A | Path_A | 0.0 | $5.89 \pm 0.02$ | $51.1 \pm 0.8$ | $16.25 \pm 0.08$ | $151.1 \pm 6.3$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2** | **M1** (Persistent) | 3 | Path_B | Path_B | 0.0 | **$7.89 \pm 0.02$** | **$51.3 \pm 1.6$** | **$18.25 \pm 0.08$** | **$148.8 \pm 2.0$** | 100% (3/3) | 100% | 100% | **100% (3/3)** |

### 4.2 Detailed 30-Episode Replay & Audit Breakdown

```
=============================================================================================================
| Episode ID  | Scenario | Method | Req Route          | Act Route          | Dead-Ends | Total Dist | Sim Time | Goal OK | Budget OK | Valid | Audit Pass |
| :---        | :---     | :---   | :---               | :---               | :---:     | :---:      | :---:    | :---:   | :---:     | :---: | :---:      |
| D0_F_ep1    | D0       | F      | Path_A             | Path_A             | 0         | 6.16m      | 50.30s   | True    | True      | True  | True       |
| D0_F_ep2    | D0       | F      | Path_A             | Path_A             | 0         | 6.20m      | 49.40s   | True    | True      | True  | True       |
| D0_F_ep3    | D0       | F      | Path_A             | Path_A             | 0         | 6.22m      | 50.00s   | True    | True      | True  | True       |
| D0_O_ep1    | D0       | O      | Path_A             | Path_A             | 0         | 6.21m      | 49.10s   | True    | True      | True  | True       |
| D0_O_ep2    | D0       | O      | Path_A             | Path_A             | 0         | 6.20m      | 50.80s   | True    | True      | True  | True       |
| D0_O_ep3    | D0       | O      | Path_A             | Path_A             | 0         | 6.20m      | 50.00s   | True    | True      | True  | True       |
| D0_R_ep1    | D0       | R      | Path_A             | Path_A             | 0         | 6.12m      | 53.10s   | True    | True      | True  | True       |
| D0_R_ep2    | D0       | R      | Path_A             | Path_A             | 0         | 6.19m      | 49.80s   | True    | True      | True  | True       |
| D0_R_ep3    | D0       | R      | Path_A             | Path_A             | 0         | 6.17m      | 51.70s   | True    | True      | True  | True       |
| D1_F_ep1    | D1       | F      | Path_B             | Path_B             | 0         | 13.84m     | 107.70s  | True    | True      | True  | True       |
| D1_F_ep2    | D1       | F      | Path_B             | Path_B             | 0         | 14.31m     | 110.20s  | True    | True      | True  | True       |
| D1_F_ep3    | D1       | F      | Path_B             | Path_B             | 0         | 13.93m     | 110.60s  | True    | True      | True  | True       |
| D1_O_ep1    | D1       | O      | Path_B             | Path_B             | 0         | 13.92m     | 108.00s  | True    | True      | True  | True       |
| D1_O_ep2    | D1       | O      | Path_B             | Path_B             | 0         | 13.89m     | 111.70s  | True    | True      | True  | True       |
| D1_O_ep3    | D1       | O      | Path_B             | Path_B             | 0         | 14.03m     | 106.40s  | True    | True      | True  | True       |
| D1_R_ep1    | D1       | R      | Path_A_then_Path_B | Path_A_then_Path_B | 1         | 17.50m     | 147.80s  | True    | True      | True  | True       |
| D1_R_ep2    | D1       | R      | Path_A_then_Path_B | Path_A_then_Path_B | 1         | 17.09m     | 138.10s  | True    | True      | True  | True       |
| D1_R_ep3    | D1       | R      | Path_A_then_Path_B | Path_A_then_Path_B | 1         | 17.07m     | 137.10s  | True    | True      | True  | True       |
| D2_F_ep1    | D2       | F      | Path_A             | Path_A             | 0         | 16.23m     | 159.10s  | True    | True      | True  | True       |
| D2_F_ep2    | D2       | F      | Path_A             | Path_A             | 0         | 16.16m     | 143.60s  | True    | True      | True  | True       |
| D2_F_ep3    | D2       | F      | Path_A             | Path_A             | 0         | 16.35m     | 150.60s  | True    | True      | True  | True       |
| D2_M1_ep1   | D2       | M1     | Path_B             | Path_B             | 0         | 18.34m     | 147.50s  | True    | True      | True  | True       |
| D2_M1_ep2   | D2       | M1     | Path_B             | Path_B             | 0         | 18.15m     | 151.60s  | True    | True      | True  | True       |
| D2_M1_ep3   | D2       | M1     | Path_B             | Path_B             | 0         | 18.25m     | 147.40s  | True    | True      | True  | True       |
| D2_O_ep1    | D2       | O      | Path_A             | Path_A             | 0         | 16.33m     | 150.30s  | True    | True      | True  | True       |
| D2_O_ep2    | D2       | O      | Path_A             | Path_A             | 0         | 16.20m     | 149.80s  | True    | True      | True  | True       |
| D2_O_ep3    | D2       | O      | Path_A             | Path_A             | 0         | 16.66m     | 149.20s  | True    | True      | True  | True       |
| D2_R_ep1    | D2       | R      | Path_A             | Path_A             | 0         | 16.32m     | 148.90s  | True    | True      | True  | True       |
| D2_R_ep2    | D2       | R      | Path_A             | Path_A             | 0         | 16.34m     | 144.70s  | True    | True      | True  | True       |
| D2_R_ep3    | D2       | R      | Path_A             | Path_A             | 0         | 16.38m     | 150.90s  | True    | True      | True  | True       |
=============================================================================================================
```

---

## 5. Offline Replay & Objective Scoring Verification

The independent replay engine (`scripts/replay_and_score_p2c.py`) evaluates physical evidence runs from first principles:
1. **Artifact Completeness**: Verifies presence of all 7 mandatory artifacts (`action_result.json`, `trajectory.json`, `costmap_snapshots.json`, `scan_snapshots.json`, `stability_window.json`, `memory_events.json`, `runtime_protocol.json`).
2. **SHA256 Integrity**: Validates SHA256 checksum tree against `checksums.sha256`.
3. **Raw Costmap ROI Recalculation**: Recomputes doorway subgrid cell counts directly from raw 2D `subgrid_matrix` via `recompute_costmap_subgrid_stats`, rejecting discrepancies (`COSTMAP_BUNDLE_ROI_DISCREPANCY`).
4. **Raw Perception Recomputation**: Recomputes doorway ray intersections and 3-valued occupancy directly from raw laser ranges, AMCL TF poses, and raw costmap ROI.
5. **Strict Chronological Memory Lifecycle & Binding Validation**:
   - Reconstructs `FailureMemoryStore` step-by-step in chronological sequence ($t_i \le t_{i+1}$).
   - Rejects empty, `None`, or placeholder bindings (`memory_id`, `failed_action_id`, `goal_uuid`, `observation_id`, `region_id`, `map_version`).
   - Verifies causal temporal ordering:
     $$t_{rec} \ge \max(t_{action\_end}, t_{obs\_eval}) - 0.05\,\text{s}$$
     $$t_{inv} \ge \max(t_{fail}, t_{free\_obs\_eval}) - 0.05\,\text{s}, \quad t_{inv} > t_{fail}$$
   - Evaluates policy decisions at $t_{dec}$ using only memory events prior to $t_{dec} + 0.05\,\text{s}$ (future observations cannot retroactively alter past decisions).
6. **Unified Audit Verdict**: Aggregates all checks into a single verdict in `P2cEpisodeEvaluator.evaluate_episode`. Any check failure enforces `audit_pass = False`.

### 5.1 Paired Positive-Negative Acceptance Testing (21 Paired Tests)

To ensure the replayer strictly detects corruptions and contract violations, 21 paired positive-negative tests were implemented in `tests/test_p2c_event_driven.py`. Each test verifies that the unmodified base fixture passes audit before asserting that a single mutation causes replay failure:

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
| `test_negative_pair_12_empty_failed_action_id_in_record_failure` | Sets `failed_action_id=""` in `RECORD_FAILURE` | `MISSING_OR_EMPTY_FAILED_ACTION_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_13_empty_goal_uuid_in_record_failure` | Sets `goal_uuid=""` in `RECORD_FAILURE` | `MISSING_OR_EMPTY_GOAL_UUID` | ❌ `audit_pass = False` |
| `test_negative_pair_14_empty_observation_id_in_record_failure` | Sets `observation_id=""` in `RECORD_FAILURE` | `MISSING_OR_EMPTY_OBSERVATION_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_15_empty_memory_id_in_record_failure` | Sets `memory_id=""` in `RECORD_FAILURE` | `MISSING_OR_EMPTY_MEMORY_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_16_empty_memory_id_in_invalidate_memory` | Sets `memory_id=""` in `INVALIDATE_MEMORY` | `MISSING_OR_EMPTY_MEMORY_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_17_unknown_placeholder_memory_id_rejected` | Sets `memory_id="unknown"` in `RECORD_FAILURE` | `INVALID_PLACEHOLDER_MEMORY_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_18_d2_missing_region_id_in_record_failure` | Sets `region_id=""` in D2 `RECORD_FAILURE` | `MISSING_OR_EMPTY_REGION_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_19_duplicate_observation_id_in_scan_snapshots` | Injects duplicate `observation_id` into `scan_snapshots.json` | `DUPLICATE_OBSERVATION_ID` | ❌ `audit_pass = False` |
| `test_negative_pair_20_duplicate_stage_in_scan_snapshots` | Injects duplicate `stage` into `scan_snapshots.json` | `DUPLICATE_SCAN_SNAPSHOT_STAGE` | ❌ `audit_pass = False` |
| `test_negative_pair_21_premature_record_failure_before_action_termination`| Sets failure event timestamp before action termination | `PREMATURE_RECORD_FAILURE_TIMESTAMP` | ❌ `audit_pass = False` |

All 21 paired tests pass in the automated test suite (`pytest tests/test_p2c_event_driven.py`).

---

## 6. Key Empirical Findings & Discussion

### 6.1 Research Question 1: FailMem ($F$) vs. Reactive ($R$) under Confirmed Blockage (D1)
- **Dead-End Traversal Elimination**: Method $R$ entered the blocked corridor in 100% of runs ($1.0 \pm 0.0$ dead ends), requiring physical detection at the vantage point, retreat to $J_0$, and fallback detour. FailMem ($F$) achieved **0.0 dead ends** across all runs.
- **Distance & Time Reduction**:
  - Decision Distance: FailMem dispatched Path B directly ($7.54\,\text{m}$), saving **$3.28\,\text{m}$** ($-30.3\%$) over $R$ ($10.82\,\text{m}$).
  - Total Distance: FailMem traversed **$14.03\,\text{m}$** vs. $R$'s **$17.22\,\text{m}$** ($-18.5\%$ total distance savings).
  - Decision Sim Time: FailMem required **$48.2\,\text{s}$** vs. $R$'s **$82.1\,\text{s}$** ($-41.3\%$ decision time savings).
  - Total Sim Time: FailMem required **$109.5\,\text{s}$** vs. $R$'s **$141.0\,\text{s}$** ($-22.3\%$ total time savings).

### 6.2 Research Question 2: FailMem ($F$) vs. Spatial Observation Cache ($O$)
- In both D1 and D2, FailMem ($F$) and Spatial Observation Cache ($O$) yielded closely matched routing performance:
  - D1: $O$ total dist $13.95 \pm 0.06\,\text{m}$, $F$ total dist $14.03 \pm 0.21\,\text{m}$.
  - D2: $O$ total dist $16.40 \pm 0.20\,\text{m}$, $F$ total dist $16.25 \pm 0.08\,\text{m}$.
- **Structural Differences**:
  - Method $O$ maintains an unstructured spatial cell cache without action-level causal binding.
  - Method $F$ records an explicit precondition-action-outcome failure record (`failed_action_id`, `goal_uuid`, `failure_reason`, `region_id`). In single-agent static clearance, spatial caching and failure invalidation exhibit functional routing parity; however, $F$ provides verifiable auditability and resilience against unstructured cache corruption.

### 6.3 Research Question 3: Dynamic Invalidation ($F$) vs. Persistent Suppression ($M1$) in Restored Environments (D2)
- **Restoration Adaptability**: Upon observing verified doorway clearance (`FREE`), FailMem invalidates the failure memory, unsuppressing Path A and selecting the short route ($5.89\,\text{m}$ decision phase, $16.25\,\text{m}$ total distance).
- **Persistent Detour Suboptimality**: Baseline $M1$ permanently suppresses Path A, forcing the robot to execute the south detour ($7.89\,\text{m}$ decision phase, $18.25\,\text{m}$ total distance).
- **Quantified Benefit**: Event-driven invalidation saves **$2.00\,\text{m}$** of navigation distance ($-11.0\%$ total distance, $-25.3\%$ decision distance) compared to persistent memory.

---

## 7. Conclusion

Milestone P2c feasibility pilot has achieved complete verification:
1. **Immutable Observation Bundles**: Formally frozen with raw scans, TF, and raw costmap ROI subgrids.
2. **Strict Event Schema & Causal Audit**: Enforced across runner and independent replayer with 21 paired positive-negative tests.
3. **30-Run Comparative Experiment**: Full matrix (10 conditions $\times$ 3 runs = 30 runs) executed with 100% validity, 100% arrival rate, and 100% audit pass.
4. **Definitive Scientific Answers**:
   - $F$ eliminates dead-end traversals and saves $18.5\%$ distance / $22.3\%$ time over $R$ under blockage (D1).
   - $F$ restores optimal routing and saves $2.00\,\text{m}$ over persistent memory $M1$ upon environmental restoration (D2).
   - $F$ matches spatial cache $O$ in static clearance routing while providing verifiable causal binding.

