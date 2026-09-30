# FailMem Milestone P2b Offline Replay & Scoring Engine Closeout Report

**Date**: 2026-09-30  
**Phase**: Milestone P2b Closeout  
**Codebase HEAD**: `c2b5c6f` (Branch `audit/r0-authenticity`)  
**Target Suite**: Milestone P2a-v3 (18 episodes) & Milestone P2b (24 episodes)  

---

## 1. Summary of Replay Engine Fixes & Verification

The offline replay and objective scoring suite [`scripts/replay_and_score_p2a.py`](file:///code/failmem-ros2-agent/scripts/replay_and_score_p2a.py) (v3.3) has been hardened to eliminate all mechanism inference flaws, circular dependencies, and retrospective tolerances:

1. **Failure Category Disambiguation**:
   - Explicitly distinguishes between **Action Failures** (`ABORTED`, `CANCELED`, `TIMEOUT`, `BUDGET_DEADLINE_EXCEEDED`), **Online Verification Failures** (Nav2 succeeded but AMCL covariance / staleness / displacement checks failed), and **Infrastructure Failures** (`INFRASTRUCTURE_FAILURE`, ROS communication crash, unhandled watchdog terminations).
   - Only action failures accompanied by fresh, verified physical `OCCUPIED` observations within 5.0s qualify for doorway blockage memory creation.

2. **Elimination of Retrospective Time Tolerances**:
   - Completely removed the previous `first_fail_time - 0.5s` and `inval_time - 0.5s` tolerances.
   - Enforces strict temporal monotonicity and causality:
     $$\text{Failure Time } t_{\text{fail}} < \text{Invalidation Evidence Stamp } t_{\text{obs}} \le \text{Recovery Dispatch Sim Time } t_{\text{disp}} < \text{Arrival Time } t_{\text{arr}}$$
   - Non-monotonic, retrograde, or non-finite timestamps immediately flag the episode as `status: UNVERIFIABLE`.

3. **Strict Memory Lifecycle & Action-Binding Verification**:
   - Reconstructs memory state strictly by instantiating an independent `FailureMemoryStore`.
   - Invalidation strictly requires:
     * Matching `map_version` (e.g. `chokepoint_world_v1`).
     * Matching `region_id` (e.g. `room2_corridor_chokepoint`).
     * Raw observation `doorway_state == FREE` with $t_{\text{obs}} > t_{\text{fail}}$.
   - Recovery verification strictly requires:
     * Dispatching a recovery action explicitly bound to the invalidated memory entry.
     * Verified physical and online arrival for that specific bound recovery action.
     * Does NOT infer memory recovery from an arbitrary second action success.

4. **Rigorous `episode_valid` Computation**:
   - Validates configuration presence, artifact completeness, timestamp finite monotonicity, simulation budget constraints, and absence of external infrastructure terminations.

5. **Multi-Layer Anti-Tamper & Discrepancy Detection**:
   - Tracks `raw_checksum_tamper_detected` via `checksums.sha256`.
   - Tracks `summary_discrepancy_detected` against pre-existing `episode_summary.json`.
   - Tracks `policy_state_discrepancy_detected` against `memory_events.json`.

---

## 2. Comprehensive Negative Unit Test Coverage

All 135 unit tests pass (`pytest /workspace/tests`: 127 passed, 8 xfailed, 0 failed), including targeted negative verification cases in [`tests/test_p2a_v3_targeted.py`](file:///code/failmem-ros2-agent/tests/test_p2a_v3_targeted.py):
- `test_replay_negative_free_before_failure`: Observation of `FREE` before failure does not invalidate memory.
- `test_replay_negative_other_region_free`: Observation of `FREE` in an unrelated region does not invalidate memory.
- `test_replay_negative_infrastructure_failure_not_memory_eligible`: Infrastructure crash does not instantiate blockage memory.
- `test_replay_negative_retrograde_timestamps_unverifiable`: Non-monotonic timestamps flag episode as `UNVERIFIABLE`.
- `test_replay_missing_frozen_config_unverifiable`: Missing `runtime_config.json` flags run as `UNVERIFIABLE`.
- `test_replay_raw_checksum_tamper_detection`: Mutation of raw attempt artifacts triggers tamper detection.
- `test_replay_policy_state_injection_ignored`: Injection of fake `recovery_verified_count` into event logs is ignored by pure raw reconstruction.

---

## 3. Re-scoring Audit of Formal Datasets

### 3.1 P2b Formal Suite (`p2b_20260930_023426_385655`, 24 Episodes)
- **Frozen Baseline (0.05 m/s / 0.08 rad/s)**: Total = 24, Mechanism Verified = 23/24, Unverifiable = 0, Raw Tampered = 0.
  * Note: `M0_S2_ep1` had peak angular velocity $0.0893\,\text{rad/s}$ during stability window $\to$ physical evaluator halt failure.
  * Summary Discrepancies noted in `M0_S2_ep2` and `M0_S2_ep3`: Historical summaries erroneously logged `evaluator_verified_recovery = True` for M0; replayer correctly scored M0 recovery as `False` (zero memory).
- **Sensitivity Rescore (0.03 m/s / 0.03 rad/s)**: Total = 24, Mechanism Verified = 22/24.
  * `M2_S2_ep1` experienced ODE caster wheel transient angular velocity of $0.0353\,\text{rad/s}$ (displacement $0.0002\,\text{m}$), failing strict $0.03\,\text{rad/s}$ threshold while passing $0.08\,\text{rad/s}$ baseline.

### 3.2 P2a-v3 Formal Suite (`p2a_v3_20260929_180106_011df4`, 18 Episodes)
- **Frozen Baseline (0.05 m/s / 0.08 rad/s)**: Total = 18, Mechanism Verified = 18/18, Unverifiable = 0, Raw Tampered = 0.
- **Sensitivity Rescore (0.03 m/s / 0.03 rad/s)**: Total = 18, Mechanism Verified = 16/18.
