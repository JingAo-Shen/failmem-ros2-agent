# FailMem Offline Reproduction and Verification Report

**Date**: 2026-10-01  
**Environment**: Ubuntu Linux 22.04 LTS x86_64, Python 3.13.5  
**Core Dependencies**: `pytest==8.3.4`, `pandas==2.2.3`, `numpy==2.1.3`, `matplotlib==3.10.0`, `scipy==1.15.3`, `pyyaml==6.0.2`  
**Purpose**: Document full end-to-end clean offline reproduction of P2c and H1 datasets, verifying SHA256 hashes, offline replaying, objective re-scoring, automated statistical aggregation, and pytest suite execution.

---

## 1. Raw Evidence Checksum Verification

All raw evidence files in the exploratory pilot datasets were verified against their respective frozen `checksums.sha256` files.

### 1.1 Milestone P2c (30 Physical Runs across D0, D1, D2)
- **Directory**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/`
- **Verification Command**:
  ```bash
  cd reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35 && sha256sum -c checksums.sha256
  ```
- **Exit Code**: `0`
- **Result**: `241/241` files matched SHA256 checksums (`OK`).

### 1.2 Hypothesis H1 Feasibility Check (4 Physical Runs)
- **Directory**: `reports/evidence/p2d_h1_feasibility/`
- **Verification Command**:
  ```bash
  cd reports/evidence/p2d_h1_feasibility && sha256sum -c checksums.sha256
  ```
- **Exit Code**: `0`
- **Result**: `25/25` files matched SHA256 checksums (`OK`).

---

## 2. Milestone P2c Clean Offline Replay & Objective Scoring

### 2.1 Replay Execution
The raw evidence directory was replayed into an independent reproduction directory without modifying raw files:
```bash
python3 scripts/replay_and_score_p2c.py reports/evidence/p2c_pilot_reproduced/
```
- **Exit Code**: `0`
- **Episodes Evaluated**: 30 / 30
- **Summary Verdict**: All 30 episodes passed multi-layer audit (`audit_pass: True`), including odometry trajectory integration, strict 180s simulation budget enforcement, physical halt stability window verification, and failure memory lifecycle validation.

### 2.2 Automated Statistical Analysis & Contrast Derivation
```bash
python3 scripts/analyze_p2c_results.py reports/evidence/p2c_pilot_reproduced/
```
- **Exit Code**: `0`
- **Output Artifacts Generated**:
  - `episodes.csv`: Per-episode records of metrics, routes, and audit verdicts.
  - `condition_summary.csv`: Aggregated group statistics ($n=3$, mean, sample std dev $\text{ddof}=1$, min, max).
  - `contrasts.csv`: Pairwise condition contrasts (FailMem $F$ vs. Reactive $R$, FailMem $F$ vs. Spatial Cache $O$, FailMem $F$ vs. Persistent Memory $M_1$).
  - `integrity_report.json`: Verification of 30 expected vs. discovered episodes and zero conflict between runner records and independent replay.

### 2.3 Reproduced Condition Metrics Summary (Gazebo 11 Simulation, $n=3$ per Condition)

| Scenario | Condition | $n$ | Actual Route | Dead-End Traversals | Decision Dist (m) | Decision Time (s) | Total Dist (m) | Total Time (s) | Replay Audit Pass |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0** | $R$ (Reactive) | 3 | `Path_A` | $0.0 \pm 0.0$ | $6.160 \pm 0.040$ | $51.533 \pm 1.662$ | $6.160 \pm 0.040$ | $51.533 \pm 1.662$ | 3/3 (100%) |
| **D0** | $O$ (Spatial Cache) | 3 | `Path_A` | $0.0 \pm 0.0$ | $6.203 \pm 0.012$ | $49.967 \pm 0.850$ | $6.203 \pm 0.012$ | $49.967 \pm 0.850$ | 3/3 (100%) |
| **D0** | $F$ (FailMem) | 3 | `Path_A` | $0.0 \pm 0.0$ | $6.196 \pm 0.031$ | $49.900 \pm 0.458$ | $6.196 \pm 0.031$ | $49.900 \pm 0.458$ | 3/3 (100%) |
| **D1** | $R$ (Reactive) | 3 | `Path_A_then_Path_B` | $1.0 \pm 0.0$ | $10.816 \pm 0.067$ | $82.067 \pm 4.388$ | $17.220 \pm 0.243$ | $141.000 \pm 5.912$ | 3/3 (100%) |
| **D1** | $O$ (Spatial Cache) | 3 | `Path_B` | $0.0 \pm 0.0$ | $7.550 \pm 0.053$ | $50.033 \pm 1.986$ | $13.947 \pm 0.071$ | $108.700 \pm 2.718$ | 3/3 (100%) |
| **D1** | $F$ (FailMem) | 3 | `Path_B` | $0.0 \pm 0.0$ | $7.536 \pm 0.005$ | $48.200 \pm 0.954$ | $14.027 \pm 0.252$ | $109.500 \pm 1.572$ | 3/3 (100%) |
| **D2** | $R$ (Reactive) | 3 | `Path_A` | $0.0 \pm 0.0$ | $5.915 \pm 0.038$ | $49.567 \pm 1.595$ | $16.344 \pm 0.031$ | $148.167 \pm 3.156$ | 3/3 (100%) |
| **D2** | $O$ (Spatial Cache) | 3 | `Path_A` | $0.0 \pm 0.0$ | $5.939 \pm 0.070$ | $52.033 \pm 1.747$ | $16.396 \pm 0.237$ | $149.767 \pm 0.551$ | 3/3 (100%) |
| **D2** | $F$ (FailMem) | 3 | `Path_A` | $0.0 \pm 0.0$ | $5.886 \pm 0.021$ | $51.100 \pm 0.954$ | $16.247 \pm 0.103$ | $151.100 \pm 7.763$ | 3/3 (100%) |
| **D2** | $M_1$ (Persistent) | 3 | `Path_B` | $0.0 \pm 0.0$ | $7.895 \pm 0.023$ | $51.300 \pm 2.000$ | $18.248 \pm 0.089$ | $148.833 \pm 2.401$ | 3/3 (100%) |

---

## 3. Hypothesis H1 Feasibility Derivation & Evaluation

### 3.1 Offline Derivation
```bash
python3 -c "from pathlib import Path; from scripts.verify_h1_feasibility import parse_and_derive_h1_evidence; parse_and_derive_h1_evidence(Path('reports/evidence/p2d_h1_feasibility'), Path('reports/evidence/p2d_h1_feasibility/derived'))"
```
- **Exit Code**: `0`
- **Output Artifact**: `reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json`

### 3.2 Evaluation Findings
- **Expected Runs**: Exactly 4 runs (`H1_aligned_run1`, `H1_aligned_run2`, `H1_oblique_run1`, `H1_oblique_run2`). All 4 discovered and verified.
- **Doorway FREE Precondition**: Verified in all 4/4 runs (0 laser hits, 22–23 pass-through rays).
- **Nav2 Autonomous Termination**: Returned `SUCCEEDED` (status code 4) in all 4/4 runs.
- **Strict Physical Arrival & Stability**: Verified in 3/4 runs (`H1_aligned_run1` failed angular velocity halt check during settling window).
- **Verdict**: `NO-GO (Scenario Not Established - 本场景未建立)`.
- **Scientific Rationale**: The candidate scenario failed to establish the prerequisite executability difference because Nav2 successfully executed the oblique profile without abortion. As pre-registered, physical testing was halted at 4 runs without tuning or goal shifting.

---

## 4. Test Suite Execution & Defect Reproduction Fixtures

### 4.1 Pytest Suite Execution
```bash
pytest
```
- **Exit Code**: `0`
- **Passed**: 176 tests
- **XFailed**: 8 tests
- **Total Duration**: ~2.0 seconds

### 4.2 Explanation of the 8 XFailed Tests
The 8 `xfailed` tests reside in `tests/test_audit_reproductions.py` (`TestR0DefectReproduction`). They are strictly marked with `@pytest.mark.xfail(raises=AssertionError, strict=True)`.

Their purpose is to serve as permanent regression fixtures documenting the specific logical and architectural flaws uncovered during the Phase R0 authenticity audit:
1. `test_reproduce_verifier_interface_and_feedback_missing`: Verifies that legacy mock `evaluate.py` ignored `use_verifier` without invoking verification or emitting feedback events.
2. `test_reproduce_stale_memory_leak_on_map_update`: Documents the flawed `map_ver <= current_map_version` comparison in legacy `src/failmem.py:44` that retrieved outdated obstacle memories across map versions.
3. `test_reproduce_four_quadrant_artificial_identical_success_rate`: Reproduces the mock state machine defect where all 4 configurations achieved identical 83.3% success due to auto-clearing faults and blind retries.
4. `test_reproduce_missing_ros_bridge_and_real_nav_stack`: Confirms legacy environment was a 60-line NumPy coordinate simulator with no ROS2 / Nav2 nodes.
5. `test_reproduce_unsupported_claim_paper_metrics_untraced`: Documents that claims of "86.7% recovery success rate" had zero raw data support.
6. `test_reproduce_cross_episode_unbounded_memory_growth`: Validates absence of memory invalidation or LRU eviction in legacy store.
7. `test_reproduce_missing_postcondition_sensor_checking`: Confirms legacy mock lacked ray-casting and costmap cell verification.
8. `test_reproduce_eval_metric_confusion_task_vs_recovery`: Documents confusion between total task completion rate and fault recovery rate in legacy evaluation scripts.

These fixtures guarantee that the legacy mock defects cannot silently reappear in future codebase iterations.
