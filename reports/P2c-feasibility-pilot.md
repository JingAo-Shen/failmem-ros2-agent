# FailMem Milestone P2c Feasibility Pilot Report: Non-Line-of-Sight Multi-Route Evaluation

**Date**: 2026-10-01  
**Phase**: Milestone P2c Authenticity Audit, Immutable Observation Bundles, Event-Driven Memory Architecture & 30-Run Exploratory Comparative Experiment  
**Execution Code Base**: Git Commit `84fd245` (Branch: `audit/r0-authenticity`)  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.2, SHA256: `fdbe35c90e53b0e80fa106cdee06d942033491cb212a616df815efc7c0b37a5f`)  
**Frozen Environment Checksums**:
- World Model: `configs/p2c_dualpath_world.model` (SHA256: `7b5d5638bbe4ecc17a18cec3c7cb38750c6bb513ce6be296a3ee4634129486f4`)
- Map YAML: `configs/p2c_dualpath_world.yaml` (SHA256: `f517f75c2b674bde8388d59866d7c0479bf5d59586b98231828ce6523c3445ce`)
- Map PGM: `configs/p2c_dualpath_world.pgm` (SHA256: `51bb9141354f494f25d8819e18fea735c18e811197a987b6d544d667d8bc4d43`)
- Nav2 Parameters: `configs/nav2_params.yaml` (SHA256: `f27cffe253064202d0dc6bf7a93f47a2243b96afddade72e798d6477bb0471d8`)

**Evidence Artifacts**:
- **30-Run Comparative Physical Experiment Batch**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/` (10 conditions $\times$ 3 repeats = 30 episodes, 100% Valid & 100% Audit Pass)
  - Automated CSV Records: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/episodes.csv`
  - Aggregated Statistics: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/condition_summary.csv`
  - Pairwise Contrasts: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/contrasts.csv`
  - Visualizations: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/p2c_distances_by_condition.png`, `p2c_durations_by_condition.png`, `p2c_dead_ends_and_contrasts.png`
- **Separate Execution Smoke Test**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022540_d13df9/` (`D0_R_ep1`, executed prior to the 30-run batch to verify simulation pipeline startup, not pooled in the 30-run comparative stats)
- Open vs. Blocked Control Probe Verification: `reports/evidence/p2c_probe_control/probe_control_results.json`
- Analytical Baseline Demonstrations: `reports/evidence/p2c_analytical/p2c_pilot_diagnosis_results.json`

---

## 1. Scope, Positioning & Methodological Clarification

This report presents empirical findings of Milestone P2c on an asymmetric dual-path non-line-of-sight (NLOS) navigation benchmark in ROS 2 Humble and Gazebo 11.

### 1.1 Study Positioning & Methodological Constraints
- **Exploratory Repetition Experiment**: The 30-run batch ($n=3$ per condition) serves as an exploratory repetition study to demonstrate mechanism functioning, pipeline reproducibility, and offline auditability. It is **not** an asymptotic or high-powered statistical verification.
- **Execution Order & Determinism**: The runner executed the 3 repetitions per condition consecutively (e.g. D0_R ep1 $\to$ ep2 $\to$ ep3, then D0_O ...) rather than using a randomized execution sequence. Explicit random seeds were not varied across runs.
- **Code Freeze & Pre-Registration Status**: **未证实事前独立代码冻结**。虽然协议与评估逻辑已在代码库中实现，但归档提交（Commit `84fd245`）同时包含了实验运行产物，缺乏运行前独立的第三方时间戳或外部预注册记录；因此不属于预注册实验。
- **Sample Observations vs. Universal Reliability**: The observed $3/3$ success rate describes the outcomes in the current sample under nominal simulation conditions. It does not constitute a statistical proof of $100\%$ reliability.
- **Definition of "$\pm$"**: All "$\pm$" values in this report represent the **sample standard deviation** ($s$) computed with Bessel's correction ($ddof=1$):
  $$s = \sqrt{\frac{1}{n-1}\sum_{i=1}^n (x_i - \bar{x})^2}$$
- **Unpaired Samples**: Runs with identical episode indices (e.g., ep1 in D1_R vs ep1 in D1_F) are treated as independent, non-paired samples, as they did not share randomized seed conditions. No large-scale hypothesis significance testing or claims of statistical equivalence are made on $n=3$.

### 1.2 Separation of Evidence Types
- **Analytical Model (`reports/evidence/p2c_analytical/`)**: Evaluates policy decision logic under idealized constant-velocity kinematic abstractions ($0.25\,\text{m/s}$ avg velocity, nominal segment geometry). Serves as a deterministic baseline for policy logic demonstration.
- **Physical ROS 2 / Gazebo Simulation (`reports/evidence/p2c_pilot/`)**: Authentic physical execution in Gazebo 11 with ROS 2 Humble Nav2, AMCL particle filter localization, LiDAR ray tracing, Nav2 global costmap updates, and continuous odometry/ground-truth trajectory integration.
- **Immutable Observation Bundle**:
  - `create_observation_bundle` is captured first, followed immediately by `evaluate_observation_bundle`. Online decision-making and disk serialization share the exact same bundle object.
  - Bundles preserve `observation_id`, raw `scan_data`, matching `tf_transform`, raw `costmap_roi` (`subgrid_matrix` & metadata), `msg_times`, `capture_times`, and `evaluation_times` with untruncated float precision.
  - In replay, costmap summaries are recalculated directly from `costmap_roi.subgrid_matrix` via `recompute_costmap_subgrid_stats`, ignoring any recorded summary.
- **Strict Event-Driven Lifecycle**:
  - Reaching the observation vantage point (`hist_reach_obs_vantage`) succeeds and produces live perception evidence, but does **not** register failure memory.
  - Failure memory is registered **only** when chokepoint traversal fails (`hist_attempt_chokepoint_traversal`) with linked `OCCUPIED` perception evidence.
  - Invalidation is strictly event-driven by subsequent live perception returning `FREE` ($\ge 8$ traversing rays, 0 obstacle hits, cleared costmap).

---

## 2. Authenticity Audit & Legacy Dataset Status

A methodological audit identified defects in earlier experimental runs, leading to the designation of all legacy suites lacking immutable observation bundles as `UNVERIFIABLE` (not backfilled).

### 2.1 Audit Defects Identified in Legacy Suites
1. **Manufactured Traversal Failure**: Earlier scripts sent direct `cmd_vel` twists without dispatching a genuine ROS 2 `NavigateToPose` action goal, generating synthetic failure return values rather than receiving an authentic Nav2 action server outcome.
2. **Observation Stream Asymmetry**: Method O (Spatial Observation Cache) was overwritten by `UNKNOWN` observations upon retreating to junction $J_0$, whereas Method F retained failure memory across the same transition.
3. **Decoupled Perception Snapshots**: Perception snapshots were re-read after evaluation rather than sharing an immutable observation bundle, preventing independent verification of sensor age and raw subgrid cell occupancy.

### 2.2 Dataset Verification Matrix

| Dataset ID | Execution Type | Immutable Bundles | Frozen Protocol | Checksums SHA256 | Failure Authenticity | Replay Verdict | Status & Purpose |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `p2c_pilot_20260930_051359_16dd42` | Physical ROS | ❌ Missing | ❌ Missing | ❌ Missing | ❌ Manufactured | ❌ REJECTED | Missing frozen protocol snapshot & checksums (`UNVERIFIABLE`) |
| `p2c_pilot_20260930_051709_dc4324` | Physical ROS | ❌ Missing | ❌ Missing | ❌ Missing | ❌ Manufactured | ❌ REJECTED | Missing frozen protocol snapshot & checksums (`UNVERIFIABLE`) |
| `p2c_pilot_20260930_052812_f14f2b` | Physical ROS | ❌ Missing | ⚠️ Incomplete | ⚠️ Incomplete | ❌ Manufactured | ❌ REJECTED | Missing trajectory artifacts & checksum tree (`UNVERIFIABLE`) |
| `p2c_pilot_20260930_102323_62b40e` | Physical ROS | ❌ Missing | ✅ Verified | ✅ Verified | ❌ Manufactured | ❌ REJECTED | Lacks immutable observation bundles & authentic Nav2 failure (`UNVERIFIABLE`) |
| `p2c_pilot_20261001_022540_d13df9` | Physical ROS (1 Run) | ✅ Verified | ✅ Verified (v4.2) | ✅ Verified | ✅ Authentic Nav2 | ✅ AUDIT PASS | Pre-batch execution smoke test (`D0_R_ep1`), listed separately |
| `p2c_pilot_20261001_022711_0d3c35` | **Physical ROS (30 Runs)** | **✅ Verified** | **✅ Verified (v4.2)** | **✅ Verified** | **✅ Authentic Nav2** | **✅ AUDIT PASS (30/30)** | **Complete 30-Run Comparative Experiment Matrix** |

---

## 3. Authentic Event-Driven Architecture & Navigation Boundaries

### 3.1 Genuine Nav2 Action Server Traversal & Probe Control
- Traversal probing (`hist_attempt_chokepoint_traversal`) is dispatched via `build_chokepoint_probe_action` (`goal=[0.50, 1.20, 0.0]`, `timeout=15.0s`, Nav2 action client) across runner and verification harnesses.
- The open vs. blocked control probe test (`scripts/verify_p2c_probe_control.py`) demonstrates causal distinction:
  - **Open Condition**: Nav2 navigates towards `[0.50, 1.20, 0.0]` through the clear doorway; action succeeds (`SUCCEEDED`, physical arrival confirmed), and perception verifies `FREE` (30 pass-through rays).
  - **Blocked Condition**: The identical navigation action is dispatched with the doorway obstacle spawned; Nav2 is physically blocked by lethal costmap cells, times out (`BUDGET_DEADLINE_EXCEEDED`), and perception verifies `OCCUPIED` (laser hits inside doorway bounding box).
  - `both_passed = True` confirms identical execution configuration without manufactured outcomes.

### 3.2 R Baseline & Navigation Stack Contribution Boundaries
Analysis of D1-R logs and continuous trajectory data clarifies the division of responsibilities:
1. **Perception Acquisition Location**: In Scenario D1-R, the robot starts at $J_0$ with local perception returning `UNKNOWN` due to wall occlusion. It navigates to Leg 1 corridor entrance waypoint `[-1.50, 1.20, 0.0]`. At this waypoint, the robot's LiDAR acquires direct line-of-sight and evaluates the doorway bounding box as `OCCUPIED` (20 hits, costmap occupied = 27).
2. **Proactive Entrance Fallback vs. Traversal Failure**: The retreat in D1-R is triggered proactively by the high-level policy state machine upon evaluating the live perception gate at `[-1.50, 1.20, 0.0]`, rather than allowing the robot to crash into the obstacle or waiting for a Nav2 planner timeout.
3. **Costmap State & Waypoint Constraints**: The shared Nav2 global costmap retains lethal obstacle cells at the doorway. However, high-level policy execution dispatches discrete sequential waypoints (`dec_path_a_approach` $\to$ `dec_fallback_retreat_to_j0` $\to$ `dec_fallback_path_b_mid` $\to$ `dec_fallback_path_b_goal`). Nav2 was not tasked with autonomous global multi-corridor replanning directly from `[-1.50, 1.20]`; the detour is structured by the high-level fallback state machine.
4. **Definition of `dead_end_traversals`**: In this protocol, `dead_end_traversals` is strictly defined as **"entering the north corridor approach leg under UNKNOWN local state, detecting blockage at the entrance gate, and returning to J0"**. It measures redundant corridor entry, not physical collision or unhandled action failure.

### 3.3 Strict Invalid-History Hard-Stop
- If history acquisition fails to produce protocol-compliant physical evidence (e.g. traversal does not fail with verified `OCCUPIED` perception, or clearance does not produce verified `FREE` perception), the episode **halts immediately**.
- The runner logs `[HARD STOP] History acquisition invalid!`, dispatches **0 decision goals**, sets `chosen_route = "HISTORY_INVALID_ABORTED"`, serializes all 7 artifacts, and marks `episode_valid = False`.

---

## 4. 30-Run Comparative Experiment Matrix Results

The full comparative experiment matrix (10 conditions $\times$ 3 repetitions = 30 physical episodes) was executed in Gazebo 11 / ROS 2 Humble under Protocol `v4.2` (`p2c_pilot_20261001_022711_0d3c35`). All metrics were automatically extracted by `scripts/analyze_p2c_results.py`.

### 4.1 Condition-Level Summary Statistics ($n=3$ per condition, Sample Std Dev $ddof=1$)

| Scenario | Method | $n$ | Route | Dead-Ends | Decision Dist ($m$) | Decision Sim Time ($s$) | Total Dist ($m$) | Total Sim Time ($s$) | Arrival Rate | Budget OK | Valid Rate | Audit Pass |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0 (Fresh)** | **R** | 3 | Path_A | 0.0 | $6.16 \pm 0.04$ | $51.5 \pm 1.7$ | $6.16 \pm 0.04$ | $51.5 \pm 1.7$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D0 (Fresh)** | **O** | 3 | Path_A | 0.0 | $6.20 \pm 0.01$ | $50.0 \pm 0.8$ | $6.20 \pm 0.01$ | $50.0 \pm 0.8$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D0 (Fresh)** | **F** | 3 | Path_A | 0.0 | $6.20 \pm 0.03$ | $49.9 \pm 0.5$ | $6.20 \pm 0.03$ | $49.9 \pm 0.5$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D1 (Blocked)** | **R** | 3 | Path_A $\to$ Path_B | **1.0** | **$10.82 \pm 0.07$** | **$82.1 \pm 4.4$** | **$17.22 \pm 0.24$** | **$141.0 \pm 5.9$** | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D1 (Blocked)** | **O** | 3 | Path_B | 0.0 | $7.55 \pm 0.05$ | $50.0 \pm 2.0$ | $13.95 \pm 0.07$ | $108.7 \pm 2.7$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D1 (Blocked)** | **F** | 3 | Path_B | 0.0 | $7.54 \pm 0.00$ | $48.2 \pm 1.0$ | $14.03 \pm 0.25$ | $109.5 \pm 1.6$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2 (Cleared)** | **R** | 3 | Path_A | 0.0 | $5.92 \pm 0.04$ | $49.6 \pm 1.6$ | $16.34 \pm 0.03$ | $148.2 \pm 3.2$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2 (Cleared)** | **O** | 3 | Path_A | 0.0 | $5.94 \pm 0.07$ | $52.0 \pm 1.7$ | $16.40 \pm 0.24$ | $149.8 \pm 0.6$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2 (Cleared)** | **F** | 3 | Path_A | 0.0 | $5.89 \pm 0.02$ | $51.1 \pm 1.0$ | $16.25 \pm 0.10$ | $151.1 \pm 7.8$ | 100% (3/3) | 100% | 100% | **100% (3/3)** |
| **D2 (Cleared)** | **M1** | 3 | Path_B | 0.0 | **$7.89 \pm 0.02$** | **$51.3 \pm 2.0$** | **$18.25 \pm 0.09$** | **$148.8 \pm 2.4$** | 100% (3/3) | 100% | 100% | **100% (3/3)** |

*Note: All values report mean $\pm$ sample standard deviation ($ddof=1$). Decision phase reports metrics measured from decision dispatch at J0 to final goal arrival; Total phase includes historical acquisition traversal costs.*

### 4.2 Pairwise Method Contrasts (Unpaired Sample Differences)

| Scenario | Comparison | Metric | Method A ($F$) Mean $\pm$ Std | Method B Mean $\pm$ Std | Absolute Difference ($A - B$) | Relative Difference (%) |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: |
| **D1** | **FailMem vs Reactive ($F - R$)** | Dead Ends | $0.00 \pm 0.00$ | $1.00 \pm 0.00$ | $-1.00$ | $-100.0\%$ |
| | | Decision Dist ($m$) | $7.54 \pm 0.00$ | $10.82 \pm 0.07$ | $-3.28$ | $-30.3\%$ |
| | | Decision Time ($s$) | $48.20 \pm 0.95$ | $82.07 \pm 4.39$ | $-33.87$ | $-41.3\%$ |
| | | Total Dist ($m$) | $14.03 \pm 0.25$ | $17.22 \pm 0.24$ | $-3.19$ | $-18.5\%$ |
| | | Total Time ($s$) | $109.50 \pm 1.57$ | $141.00 \pm 5.91$ | $-31.50$ | $-22.3\%$ |
| **D1** | **FailMem vs Spatial Cache ($F - O$)** | Dead Ends | $0.00 \pm 0.00$ | $0.00 \pm 0.00$ | $0.00$ | $0.0\%$ |
| | | Decision Dist ($m$) | $7.54 \pm 0.00$ | $7.55 \pm 0.05$ | $-0.01$ | $-0.2\%$ |
| | | Decision Time ($s$) | $48.20 \pm 0.95$ | $50.03 \pm 1.99$ | $-1.83$ | $-3.7\%$ |
| | | Total Dist ($m$) | $14.03 \pm 0.25$ | $13.95 \pm 0.07$ | $+0.08$ | $+0.6\%$ |
| | | Total Time ($s$) | $109.50 \pm 1.57$ | $108.70 \pm 2.72$ | $+0.80$ | $+0.7\%$ |
| **D2** | **FailMem vs Persistent Memory ($F - M1$)** | Dead Ends | $0.00 \pm 0.00$ | $0.00 \pm 0.00$ | $0.00$ | $0.0\%$ |
| | | Decision Dist ($m$) | $5.89 \pm 0.02$ | $7.89 \pm 0.02$ | $-2.01$ | $-25.4\%$ |
| | | Decision Time ($s$) | $51.10 \pm 0.95$ | $51.30 \pm 2.00$ | $-0.20$ | $-0.4\%$ |
| | | Total Dist ($m$) | $16.25 \pm 0.10$ | $18.25 \pm 0.09$ | $-2.00$ | $-11.0\%$ |
| | | Total Time ($s$) | $151.10 \pm 7.76$ | $148.83 \pm 2.40$ | $+2.27$ | $+1.5\%$ |
| **D2** | **FailMem vs Spatial Cache ($F - O$)** | Dead Ends | $0.00 \pm 0.00$ | $0.00 \pm 0.00$ | $0.00$ | $0.0\%$ |
| | | Decision Dist ($m$) | $5.89 \pm 0.02$ | $5.94 \pm 0.07$ | $-0.05$ | $-0.9\%$ |
| | | Decision Time ($s$) | $51.10 \pm 0.95$ | $52.03 \pm 1.75$ | $-0.93$ | $-1.8\%$ |
| | | Total Dist ($m$) | $16.25 \pm 0.10$ | $16.40 \pm 0.24$ | $-0.15$ | $-0.9\%$ |
| | | Total Time ($s$) | $151.10 \pm 7.76$ | $149.77 \pm 0.55$ | $+1.33$ | $+0.9\%$ |
| **D2** | **FailMem vs Reactive ($F - R$)** | Dead Ends | $0.00 \pm 0.00$ | $0.00 \pm 0.00$ | $0.00$ | $0.0\%$ |
| | | Decision Dist ($m$) | $5.89 \pm 0.02$ | $5.92 \pm 0.04$ | $-0.03$ | $-0.5\%$ |
| | | Decision Time ($s$) | $51.10 \pm 0.95$ | $49.57 \pm 1.59$ | $+1.53$ | $+3.1\%$ |
| | | Total Dist ($m$) | $16.25 \pm 0.10$ | $16.34 \pm 0.03$ | $-0.10$ | $-0.6\%$ |
| | | Total Time ($s$) | $151.10 \pm 7.76$ | $148.17 \pm 3.16$ | $+2.93$ | $+2.0\%$ |

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
- **Reduction of Redundant Corridor Entry**: Method $R$ entered the blocked corridor in all 3 runs ($1.0 \pm 0.0$ dead ends), requiring physical detection at the entrance waypoint, retreat to $J_0$, and fallback detour. Both FailMem ($F$) and Spatial Cache ($O$) achieved **0.0 dead ends**.
- **Distance & Time Comparison**:
  - Decision Distance: FailMem dispatched Path B directly ($7.54 \pm 0.00\,\text{m}$), saving **$3.28\,\text{m}$** ($-30.3\%$) over $R$ ($10.82 \pm 0.07\,\text{m}$).
  - Total Distance: FailMem traversed **$14.03 \pm 0.25\,\text{m}$** vs. $R$'s **$17.22 \pm 0.24\,\text{m}$** ($-18.5\%$ total distance difference).
  - Decision Sim Time: FailMem required **$48.2 \pm 1.0\,\text{s}$** vs. $R$'s **$82.1 \pm 4.4\,\text{s}$** ($-41.3\%$ decision time difference).
  - Total Sim Time: FailMem required **$109.5 \pm 1.6\,\text{s}$** vs. $R$'s **$141.0 \pm 5.9\,\text{s}$** ($-22.3\%$ total time difference).
- **Core Interpretation**: This result demonstrates that **retaining historical evidence avoids redundant exploration costs** compared to instantaneous local sensing. However, this comparison alone does **not** demonstrate that failure semantics offer independent value beyond standard spatial observation caching.

### 6.2 Research Question 2: FailMem ($F$) vs. Spatial Observation Cache ($O$)
- In both D1 and D2, FailMem ($F$) and Spatial Observation Cache ($O$) exhibited nearly identical routing performance on this benchmark:
  - D1 Total Distance: $F = 14.03 \pm 0.25\,\text{m}$ vs. $O = 13.95 \pm 0.07\,\text{m}$ (Difference: $+0.08\,\text{m}$, $+0.6\%$).
  - D1 Total Sim Time: $F = 109.5 \pm 1.6\,\text{s}$ vs. $O = 108.7 \pm 2.7\,\text{s}$ (Difference: $+0.80\,\text{s}$, $+0.7\%$).
  - D2 Total Distance: $F = 16.25 \pm 0.10\,\text{m}$ vs. $O = 16.40 \pm 0.24\,\text{m}$ (Difference: $-0.15\,\text{m}$, $-0.9\%$).
  - D2 Total Sim Time: $F = 151.1 \pm 7.8\,\text{s}$ vs. $O = 149.8 \pm 0.6\,\text{s}$ (Difference: $+1.33\,\text{s}$, $+0.9\%$).
- **Scientific Implication**:
  - In this static single-agent layout, $F$ and $O$ produce identical high-level route choices with $<1\%$ metric differences.
  - Current exploratory data **does not demonstrate a performance advantage for FailMem over Spatial Cache** in this static single-agent layout.
  - Conversely, with exploratory $n=3$, these data do **not prove mathematical or statistical equivalence** between $F$ and $O$ across arbitrary topologies.
  - The primary distinction remains structural: $F$ binds failure records to specific action goals and precondition evidence, whereas $O$ maintains an unconditioned 2D spatial grid.

### 6.3 Research Question 3: Dynamic Invalidation ($F$) vs. Persistent Suppression ($M1$) in Restored Environments (D2)
- **Distance Benefit**: Upon observing verified doorway clearance (`FREE`), FailMem invalidates the failure memory, unsuppressing Path A and selecting the short route ($5.89 \pm 0.02\,\text{m}$ decision distance, $16.25 \pm 0.10\,\text{m}$ total distance). In contrast, persistent baseline $M1$ permanently suppresses Path A, executing the south detour ($7.89 \pm 0.02\,\text{m}$ decision distance, $18.25 \pm 0.09\,\text{m}$ total distance). Invalidation saves **$2.00\,\text{m}$** ($-11.0\%$) total distance.
- **Execution Time Limitation**: Despite traversing $2.00\,\text{m}$ less distance, FailMem required **$151.1 \pm 7.8\,\text{s}$** total sim time vs. $M1$'s **$148.8 \pm 2.4\,\text{s}$** (Difference: $+2.27\,\text{s}$, $+1.5\%$). 耗时差异的可能原因（如北侧较窄走廊中的局部加减速或航向调整等）仅能列为**待验证的候选假设**，不能直接断定为唯一确因。
- **Conclusion**: The advantage of event-driven invalidation in this scenario is **strictly confined to navigation distance / path length**, and cannot be generalized to an improvement across all efficiency metrics (such as total execution duration).

---

## 7. Limitations & Research Boundaries

1. **Structural Feature vs. Unverified Robustness**: Causal event binding (`goal_uuid`, `failed_action_id`, `observation_id`) is an implemented architectural feature that enables rigorous offline auditing. However, resilience against corrupted caches, partial sensor dropout, or adversarial noise has not been experimentally tested in this setup.
2. **Benchmark Scope**: Results are restricted to the static dual-path layout with deterministic geometric blockages.
3. **Exploratory Sample Size ($n=3$)**: Sample size $n=3$ per condition is appropriate for exploratory validation and audit confirmation, but insufficient for high-dimensional generalization.

