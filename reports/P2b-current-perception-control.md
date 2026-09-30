# FailMem P2b Reactive Perception Control & Failure Memory Benchmark Report

**Dataset ID**: `p2b_20260930_023426_385655`  
**Evaluation Date**: 2026-09-30  
**Benchmark Suite**: Milestone P2b (24 Formal Episodes: 4 Policies $\times$ 2 Sequences $\times$ 3 Runs)  
**Protocol Configuration**: `configs/p2b_reactive_control_protocol.yaml` (v3.1)  
**Scoring Evaluator**: `scripts/replay_and_score_p2a.py` (v3.2, Strict Replay & Ground-Truth Scoring)  
**Replay Evidence**:
- Frozen Baseline Report (0.05 / 0.08): `reports/evidence/p2b/p2b_20260930_023426_385655/replay_report.json`
- Sensitivity Rescore Report (0.03 / 0.03): `reports/evidence/p2b/p2b_20260930_023426_385655/sensitivity_report_003.json`

---

## 1. Executive Summary & Policy Overview

Milestone P2b provides an objective, four-way benchmark comparing failure memory architectures against a reactive, perception-driven baseline in the dual-room single-chokepoint arena:

1. **M0 (No Memory Baseline)**: Zero memory; repeatedly re-attempts failed goals until simulation budget exhaustion.
2. **M1 (Persistent Memory Baseline)**: Persistent failure memory; permanently suppresses repeat dispatches to failed targets without an invalidation mechanism.
3. **M2 (FailMem Conditional Memory)**: Deterministic conditional memory; suppresses repeat dispatches while precondition is unmet, invalidates memory upon verified physical perception evidence (`doorway_state == FREE`), and verifies recovery upon physical arrival.
4. **M3 (Current Perception Only)**: Zero memory entries; purely reactive dispatch gating based on instantaneous doorway state (`FREE` $\to$ permit dispatch, `OCCUPIED`/`UNKNOWN` $\to$ suppress dispatch).

---

## 2. Quantitative Performance Matrix (24 Formal Episodes)

| Policy | Sequence | Episodes | Task Success Rate (Frozen) | Task Success Rate (Sens 0.03) | Mean Dispatches / Ep | Redundant Retries / Ep | Suppressions / Ep | Mean Obs / Ep | Mechanism Verified |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **M0 (No Memory)** | **S1 (Block)** | 3 | 0 / 3 (0.0%) | 0 / 3 (0.0%) | 3.00 | 2.00 | 0.00 | 4.00 | **3 / 3 (100%)** |
| **M0 (No Memory)** | **S2 (Clear)** | 3 | 2 / 3 (66.7%)* | 2 / 3 (66.7%)* | 2.00 | 1.00 | 0.00 | 2.00 | **2 / 3 (66.7%)** |
| **M1 (Persistent)**| **S1 (Block)** | 3 | 0 / 3 (0.0%) | 0 / 3 (0.0%) | 1.00 | 0.00 | 20.00 | 21.00 | **3 / 3 (100%)** |
| **M1 (Persistent)**| **S2 (Clear)** | 3 | 0 / 3 (0.0%) | 0 / 3 (0.0%) | 1.00 | 0.00 | 20.00 | 21.00 | **3 / 3 (100%)** |
| **M2 (Conditional)**| **S1 (Block)** | 3 | 0 / 3 (0.0%) | 0 / 3 (0.0%) | 1.00 | 0.00 | 20.00 | 21.00 | **3 / 3 (100%)** |
| **M2 (Conditional)**| **S2 (Clear)** | 3 | **3 / 3 (100.0%)** | 2 / 3 (66.7%)** | 2.00 | 0.00 | 1.33 | 3.33 | **3 / 3 (100%)** |
| **M3 (Perception)** | **S1 (Block)** | 3 | 0 / 3 (0.0%) | 0 / 3 (0.0%) | **0.00** | **0.00** | 30.00 | 30.00 | **3 / 3 (100%)** |
| **M3 (Perception)** | **S2 (Clear)** | 3 | **3 / 3 (100.0%)** | **3 / 3 (100.0%)** | **1.00** | **0.00** | 13.00 | 14.00 | **3 / 3 (100%)** |

*\*Note on M0_S2_ep1: Robot reached goal online, but experienced a brief transient angular velocity of 0.0893 rad/s during the stability observation window, exceeding both 0.080 rad/s and 0.030 rad/s physical scoring limits.*  
*\*\*Note on M2_S2_ep1 (Sensitivity Rescore): Robot arrived at goal (ground truth displacement = 0.0002m), but transient contact solver chatter in the caster wheel produced peak angular velocity of 0.0353 rad/s, failing strict 0.030 rad/s threshold while passing 0.080 rad/s baseline.*

---

## 3. Full 24-Episode Detailed Audit Table

All timestamps are reported as `elapsed_sim_sec` (relative to episode start $t_0$, where $t_0 \approx 23.5\,\text{s}$ Gazebo sim clock):

| Episode ID | Policy | Seq | Nav Attempts | Redundant Retries | Suppressions | Inval. Elapsed | Recovery Disp. Elapsed | Recovery Arrival Elapsed | Online OK | Evaluator GT OK (0.05/0.08) | Sens GT OK (0.03/0.03) | Final GT Position Error | Mechanism Verified |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `M0_S1_ep1` | M0 | S1 | 3 | 2 | 0 | N/A | N/A | N/A | False | False | False | 3.0262m | **PASS** |
| `M0_S1_ep2` | M0 | S1 | 3 | 2 | 0 | N/A | N/A | N/A | False | False | False | 3.3233m | **PASS** |
| `M0_S1_ep3` | M0 | S1 | 3 | 2 | 0 | N/A | N/A | N/A | False | False | False | 3.3450m | **PASS** |
| `M0_S2_ep1` | M0 | S2 | 2 | 1 | 0 | N/A | N/A | N/A | True | False | False | 0.2183m | **FAIL (Halt Vel)** |
| `M0_S2_ep2` | M0 | S2 | 2 | 1 | 0 | N/A | N/A | N/A | True | True | True | 0.2009m | **PASS** |
| `M0_S2_ep3` | M0 | S2 | 2 | 1 | 0 | N/A | N/A | N/A | True | True | True | 0.1732m | **PASS** |
| `M1_S1_ep1` | M1 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5986m | **PASS** |
| `M1_S1_ep2` | M1 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M1_S1_ep3` | M1 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M1_S2_ep1` | M1 | S2 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M1_S2_ep2` | M1 | S2 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M1_S2_ep3` | M1 | S2 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M2_S1_ep1` | M2 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M2_S1_ep2` | M2 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.5998m | **PASS** |
| `M2_S1_ep3` | M2 | S1 | 1 | 0 | 20 | N/A | N/A | N/A | False | False | False | 3.6000m | **PASS** |
| `M2_S2_ep1` | M2 | S2 | 2 | 0 | 2 | 30.3s | 30.3s | 53.2s | True | True | False | 0.1874m | **PASS** |
| `M2_S2_ep2` | M2 | S2 | 2 | 0 | 1 | 27.7s | 27.7s | 43.6s | True | True | True | 0.2051m | **PASS** |
| `M2_S2_ep3` | M2 | S2 | 2 | 0 | 1 | 28.3s | 28.3s | 44.1s | True | True | True | 0.1783m | **PASS** |
| `M3_S1_ep1` | M3 | S1 | 0 | 0 | 30 | N/A | N/A | N/A | False | False | False | N/A (0 dispatches; stationary at spawn dist 3.60m) | **PASS** |
| `M3_S1_ep2` | M3 | S1 | 0 | 0 | 30 | N/A | N/A | N/A | False | False | False | N/A (0 dispatches; stationary at spawn dist 3.60m) | **PASS** |
| `M3_S1_ep3` | M3 | S1 | 0 | 0 | 30 | N/A | N/A | N/A | False | False | False | N/A (0 dispatches; stationary at spawn dist 3.60m) | **PASS** |
| `M3_S2_ep1` | M3 | S2 | 1 | 0 | 17 | N/A | 43.4s | 58.5s | True | True | True | 0.1973m | **PASS** |
| `M3_S2_ep2` | M3 | S2 | 1 | 0 | 11 | N/A | 28.5s | 43.7s | True | True | True | 0.1654m | **PASS** |
| `M3_S2_ep3` | M3 | S2 | 1 | 0 | 11 | N/A | 28.1s | 43.2s | True | True | True | 0.1878m | **PASS** |

---

## 4. Key Comparative Findings: Memory vs. Current Perception

### 4.1 Sequence S1: Continuous Blockage
- **M0**: Dispatches 3 navigation attempts, failing upon each timeout until simulation budget exhaustion (2 redundant retries).
- **M1 / M2**: Launches Attempt 1 at $t=0$, experiences navigation failure, records failure memory, and suppresses all subsequent 20 dispatches.
- **M3**: Gating purely on instantaneous perception, M3 detects `doorway_state == OCCUPIED` prior to dispatch and suppresses execution entirely, resulting in **0 navigation dispatches** and **30 observation cycles**.

### 4.2 Sequence S2: Clearance at Elapsed Simulation Time $t=25.0\,\text{s}$
- **M0**: Initial dispatch fails at $t=24.5\,\text{s}$. Unconditional retry Attempt 2 dispatched immediately at $t=24.5\,\text{s}$ succeeds after obstacle clearance.
- **M1**: Fails on Attempt 1, permanently suppresses future dispatches, resulting in permanent false negative ($0\%$ task success).
- **M2**: Fails on Attempt 1, suppresses dispatches during blockage, invalidates memory at $t=27.7\,\text{s}$ upon observing `doorway_state == FREE`, dispatches recovery Attempt 2 at $t=27.7\,\text{s}$, and reaches goal ($100\%$ task success).
- **M3**: Suppresses dispatches while blocked; at $t=28.1\,\text{s}$ observes `doorway_state == FREE`, dispatches its first navigation attempt, and reaches goal ($100\%$ task success, **1 total dispatch**).

---

## 5. Scientific Boundary & Research Decision

### 5.1 Line-of-Sight (LOS) Domain Boundary
In this single-chokepoint setup, the doorway is directly visible from the robot's spawn point. Under complete line-of-sight visibility:
1. Instantaneous reactive perception (M3) gates execution upfront, avoiding the initial failure.
2. Failure memory (M2) is execution-triggered, requiring an initial failure to instantiate state.
3. Therefore, in single-room LOS topologies, failure memory provides no advantage over reactive perception.

### 5.2 Transition to Milestone P2c (Non-Line-of-Sight & Multi-Route Topologies)
Failure memory is hypothesized to provide critical, non-substitutable utility when:
1. **The chokepoint is Non-Line-of-Sight (NLOS)**: Located around corners or beyond sensor range at the decision fork ($\mathcal{O}(s_t) = \text{UNKNOWN}$).
2. **Multi-Route Routing**: The robot must choose between navigating toward a potentially blocked chokepoint vs an alternative unblocked corridor without incurring exploration travel cost.
