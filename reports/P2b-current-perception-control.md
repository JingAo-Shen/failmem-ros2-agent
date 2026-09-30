# FailMem P2b Reactive Perception Control & Failure Memory Benchmark Report

**Dataset ID**: `p2b_20260930_023426_385655`  
**Evaluation Date**: 2026-09-30  
**Benchmark Suite**: Milestone P2b (24 Formal Episodes: 4 Policies $\times$ 2 Sequences $\times$ 3 Runs)  
**Protocol Configuration**: `configs/p2b_reactive_control_protocol.yaml` (v3.1)  
**Scoring Evaluator**: `scripts/replay_and_score_p2a.py` (v3.0, Strict Replay & Ground-Truth Scoring)  

---

## 1. Executive Summary & Policy Overview

Milestone P2b establishes an objective, four-way benchmark comparing failure memory architectures against a reactive, perception-driven baseline in the dual-room single-chokepoint arena:

1. **M0 (No Memory Baseline)**: Zero memory; repeatedly re-attempts failed goals until simulation budget exhaustion.
2. **M1 (Persistent Memory Baseline)**: Persistent failure memory; permanently suppresses repeat dispatches to failed targets without an invalidation mechanism.
3. **M2 (FailMem Conditional Memory)**: Deterministic conditional memory; suppresses repeat dispatches while precondition is unmet, invalidates memory upon verified physical perception evidence (`doorway_state == FREE`), and verifies recovery upon physical arrival.
4. **M3 (Current Perception Only)**: Zero memory entries; purely reactive dispatch gating based on instantaneous doorway state (`FREE` $\to$ permit dispatch, `OCCUPIED`/`UNKNOWN` $\to$ suppress dispatch).

---

## 2. Quantitative Performance Matrix (24 Formal Episodes)

| Policy | Sequence | Episodes | Task Success Rate | Mean Dispatches / Ep | Redundant Retries / Ep | Suppressions / Ep | Mean Obs / Ep | Mechanism Verified |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **M0 (No Memory)** | **S1 (Block)** | 3 | 0 / 3 (0.0%) | 3.00 | 2.00 | 0.00 | 4.00 | **3 / 3 (100%)** |
| **M0 (No Memory)** | **S2 (Clear)** | 3 | 2 / 3 (66.7%)* | 2.00 | 1.00 | 0.00 | 2.00 | **2 / 3 (66.7%)** |
| **M1 (Persistent)**| **S1 (Block)** | 3 | 0 / 3 (0.0%) | 1.00 | 0.00 | 20.00 | 21.00 | **3 / 3 (100%)** |
| **M1 (Persistent)**| **S2 (Clear)** | 3 | 0 / 3 (0.0%) | 1.00 | 0.00 | 20.00 | 21.00 | **3 / 3 (100%)** |
| **M2 (Conditional)**| **S1 (Block)** | 3 | 0 / 3 (0.0%) | 1.00 | 0.00 | 20.00 | 21.00 | **3 / 3 (100%)** |
| **M2 (Conditional)**| **S2 (Clear)** | 3 | 3 / 3 (100.0%)| 2.00 | 0.00 | 1.33 | 3.33 | **3 / 3 (100%)** |
| **M3 (Perception)** | **S1 (Block)** | 3 | 0 / 3 (0.0%) | **0.00** | **0.00** | 30.00 | 30.00 | **3 / 3 (100%)** |
| **M3 (Perception)** | **S2 (Clear)** | 3 | **3 / 3 (100.0%)**| **1.00** | **0.00** | 13.00 | 14.00 | **3 / 3 (100%)** |

*\*Note on M0_S2_ep1: Robot reached goal online, but experienced a brief transient angular velocity of 0.0893 rad/s during the stability observation window, exceeding the strict 0.080 rad/s physical scoring limit.*

---

## 3. Full 24-Episode Detailed Audit Table

The table below reports all recomputed metrics, online results, and exact event timestamps reconstructed independently from raw simulation artifacts:

| Episode ID | Policy | Seq | Nav Attempts | Redundant Retries | Suppressions | Inval. Sim Time | Recovery Disp. Time | Recovery Arrival Time | Online OK | Evaluator GT OK | Final GT Err ($m$) | Mechanism OK |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `M0_S1_ep1` | M0 | S1 | 3 | 2 | 0 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M0_S1_ep2` | M0 | S1 | 3 | 2 | 0 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M0_S1_ep3` | M0 | S1 | 3 | 2 | 0 | N/A | N/A | N/A | False | False | 3.5997 | **PASS** |
| `M0_S2_ep1` | M0 | S2 | 2 | 1 | 0 | N/A | N/A | N/A | True | False | 0.2183 | **FAIL (Halt Vel)** |
| `M0_S2_ep2` | M0 | S2 | 2 | 1 | 0 | N/A | N/A | N/A | True | True | 0.1798 | **PASS** |
| `M0_S2_ep3` | M0 | S2 | 2 | 1 | 0 | N/A | N/A | N/A | True | True | 0.1654 | **PASS** |
| `M1_S1_ep1` | M1 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M1_S1_ep2` | M1 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M1_S1_ep3` | M1 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M1_S2_ep1` | M1 | S2 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M1_S2_ep2` | M1 | S2 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M1_S2_ep3` | M1 | S2 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M2_S1_ep1` | M2 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M2_S1_ep2` | M2 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M2_S1_ep3` | M2 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | 3.5998 | **PASS** |
| `M2_S2_ep1` | M2 | S2 | 2 | 0 | 2 | 27.6s | 51.1s | 67.24s | True | True | 0.1824 | **PASS** |
| `M2_S2_ep2` | M2 | S2 | 2 | 0 | 1 | 27.6s | 51.1s | 66.89s | True | True | 0.1791 | **PASS** |
| `M2_S2_ep3` | M2 | S2 | 2 | 0 | 1 | 27.6s | 51.1s | 67.12s | True | True | 0.1855 | **PASS** |
| `M3_S1_ep1` | M3 | S1 | 0 | 0 | 30 | N/A | N/A | N/A | False | False | 0.0000 | **PASS** |
| `M3_S1_ep2` | M3 | S1 | 0 | 0 | 30 | N/A | N/A | N/A | False | False | 0.0000 | **PASS** |
| `M3_S1_ep3` | M3 | S1 | 0 | 0 | 30 | N/A | N/A | N/A | False | False | 0.0000 | **PASS** |
| `M3_S2_ep1` | M3 | S2 | 1 | 0 | 17 | N/A | N/A | 67.31s | True | True | 0.1860 | **PASS** |
| `M3_S2_ep2` | M3 | S2 | 1 | 0 | 11 | N/A | N/A | 51.82s | True | True | 0.1842 | **PASS** |
| `M3_S2_ep3` | M3 | S2 | 1 | 0 | 11 | N/A | N/A | 51.90s | True | True | 0.1878 | **PASS** |

---

## 4. Key Comparative Findings: Memory vs. Current Perception

### A. Performance Under Continuous Blockage (Sequence S1)
- **M0**: Dispatches 3 full navigation attempts, blindly crashing into the blocked doorway each time until budget timeout (2 redundant retries).
- **M2**: Launches Attempt 1 at $t=0$, experiences navigation timeout, observes `OCCUPIED` doorway, creates failure memory, and suppresses all subsequent 20 dispatches (**66.7% dispatch reduction vs M0**, **100% redundant retry elimination**).
- **M3**: At $t=0$, instantaneous perception detects `doorway_state == OCCUPIED`. M3 suppresses dispatch immediately *before* ever launching a navigation action. It executes 30 observation cycles with **0 dispatches attempted** (**100% dispatch elimination vs M0**).

### B. Performance Under Timed Clearance at $t=25.0$s (Sequence S2)
- **M0**: Attempts at $t=0$ (fails at $t=24.5$s), then blind retry Attempt 2 dispatched at $t=24.5$s succeeds after obstacle clearance.
- **M1**: Attempts at $t=0$, fails, permanently suppresses all future attempts, resulting in a persistent false negative (0/3 task success).
- **M2**: Attempts at $t=0$ (fails at $t=24.5$s), suppresses during blockage, invalidates memory at $t=27.6$s when doorway is observed `FREE`, dispatches recovery Attempt 2, and succeeds (3/3 task success, 2 total dispatches).
- **M3**: Observes `OCCUPIED` from $t=0$ to $t=25$s, suppressing dispatches. At $t=28.1$s, observes `doorway_state == FREE`, launches its very first dispatch Attempt 1, and reaches the goal on its initial attempt (3/3 task success, **1 total dispatch**).

---

## 5. Honest Scientific Boundary & Domain Conclusion

### Why M3 Outperforms M2 in the Single-Chokepoint Arena
In this experimental setup (single doorway separating Room 1 and Room 2), the doorway is located along the direct line of sight from the robot's spawn position (at $x=-1.80, y=0.00$, facing $x=0.00$).

Because the chokepoint is **fully observable from the starting position upfront**:
1. Instantaneous reactive perception (M3) can evaluate whether the path is open *before* dispatching any navigation command.
2. M3 prevents the initial execution failure entirely, requiring **0 dispatches in S1** and **1 single dispatch in S2**.
3. In contrast, M2 operates as an execution-triggered mechanism: it requires an initial navigation failure to instantiate a failure memory entry, leading to **1 dispatch in S1** and **2 dispatches in S2**.

### Critical Domain Boundary: When is Failure Memory Actually Essential?
This benchmark demonstrates that **in a single-room direct line-of-sight environment with upfront visibility, failure memory provides no advantage over instantaneous perception gating.**

Failure memory becomes necessary under three specific structural conditions:
1. **Non-Line-of-Sight / Distant Blockages**: When the obstruction is located several rooms away or around opaque corners where laser rays cannot reach from the robot's current position. In such cases, M3 cannot perceive the blockage upfront and would dispatch blindly; once the robot navigates to the chokepoint and fails, failure memory is required to remember that the distant path is blocked when the robot returns to the starting room.
2. **Topological Multi-Route Planning**: When multiple topological routes exist (e.g., Corridor A vs. Corridor B), memory is needed to prune the blocked corridor from global route selection without repeatedly driving down the corridor to re-check it.
3. **Transient Sensor Occlusion / Asynchronous Invalidation**: When an agent must reason about previously observed blocked zones while focusing sensors on other tasks or exploring other regions.

This finding establishes an empirical foundation for expanding into multi-room, non-line-of-sight topological routing in subsequent milestones.
