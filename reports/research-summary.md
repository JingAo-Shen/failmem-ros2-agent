# FailMem Research Summary & Synthesis Report

**Project**: Event-Driven Action Failure Memory for Autonomous Navigation (FailMem)  
**Target Platform**: ROS 2 Humble + Nav2 (`DWBLocalPlanner`, `NavFnPlanner`) + Gazebo 11  
**Date**: 2026-10-01  
**Repository Branch**: `audit/r0-authenticity`  

---

## 1. Research Question & Motivation

In mobile robot navigation within complex environments with non-line-of-sight (NLOS) passages, physical chokepoints, and dynamic blockages:
- **Core Research Question**: *Can explicit, causally-bound failure memory improve path planning efficiency and prevent repeated dead-end traversals compared to reactive planning and spatial occupancy caching?*
- **Investigated Methods**:
  1. **Reactive Baseline ($R$)**: No cross-episode memory; re-explores chokepoints until local sensors detect blockage.
  2. **Spatial Observation Cache ($O$)**: Caches 2D occupancy state observed at vantage points.
  3. **Event-Driven Failure Memory ($F$)**: Causally binds execution failure events ($t_{\text{fail}}, \text{goal\_uuid}, \text{action\_id}, \text{region}, \text{costmap\_roi}$) and performs dynamic perception-driven invalidation.
  4. **Persistent Suppression Memory ($M1$)**: Suppresses failed regions permanently without dynamic invalidation.

---

## 2. Actual System Architecture & Verified Implementation

1. **Authentic Action Client & Server Integration**:
   - Replaced synthetic mocks with genuine ROS 2 Nav2 `NavigateToPose` action clients ([`src/action_dispatcher.py`](file:///code/failmem-ros2-agent/src/action_dispatcher.py), [`scripts/run_p1c_v3.py`](file:///code/failmem-ros2-agent/scripts/run_p1c_v3.py)).
   - Authentic terminal status handling: `SUCCEEDED` (code 4), `CANCELED` (code 5), `ABORTED` (code 6).
2. **Immutable Observation Bundles**:
   - Pre-evaluation capture of raw LiDAR range arrays, TF transformations, and raw costmap subgrid ROI matrices ([`src/doorway_evaluator.py`](file:///code/failmem-ros2-agent/src/doorway_evaluator.py)).
   - Evaluated 3-valued doorway perception (`OCCUPIED` / `FREE` / `UNKNOWN`) based on ray intersection and cell costs.
3. **Zero-Bypass Offline Replay & Verification Engine**:
   - Independent replay script ([`scripts/replay_and_score_p2c.py`](file:///code/failmem-ros2-agent/scripts/replay_and_score_p2c.py)) recomputing perception and trajectory kinematics from raw recorded sensory data.
   - Strict chronological causality validation ($t_{rec} \ge \max(t_{act}, t_{obs})$, $t_{inv} \ge \max(t_{fail}, t_{free})$).

---

## 3. Empirical Results: 30-Run Exploratory Comparative Benchmark

Dataset: [`reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/`](file:///code/failmem-ros2-agent/reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/) (30 physical runs, $n=3$ per condition, Bessel-corrected sample std $ddof=1$).

| Scenario | Method | $n$ | Route Traversed | Dead-Ends | Decision Dist ($m$) | Decision Time ($s$) | Total Dist ($m$) | Total Time ($s$) | Replay Audit Pass |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0 (Clear)** | **R** | 3 | Path_A | 0.0 | $6.16 \pm 0.04$ | $51.5 \pm 1.7$ | $6.16 \pm 0.04$ | $51.5 \pm 1.7$ | 100% |
| **D0 (Clear)** | **O** | 3 | Path_A | 0.0 | $6.20 \pm 0.01$ | $50.0 \pm 0.8$ | $6.20 \pm 0.01$ | $50.0 \pm 0.8$ | 100% |
| **D0 (Clear)** | **F** | 3 | Path_A | 0.0 | $6.20 \pm 0.03$ | $49.9 \pm 0.5$ | $6.20 \pm 0.03$ | $49.9 \pm 0.5$ | 100% |
| **D1 (Blocked)** | **R** | 3 | Path_A $\to$ Path_B | **1.0** | **$10.82 \pm 0.07$** | **$82.1 \pm 4.4$** | **$17.22 \pm 0.24$** | **$141.0 \pm 5.9$** | 100% |
| **D1 (Blocked)** | **O** | 3 | Path_B | 0.0 | $7.55 \pm 0.05$ | $50.0 \pm 2.0$ | $13.95 \pm 0.07$ | $108.7 \pm 2.7$ | 100% |
| **D1 (Blocked)** | **F** | 3 | Path_B | 0.0 | $7.54 \pm 0.00$ | $48.2 \pm 1.0$ | $14.03 \pm 0.25$ | $109.5 \pm 1.6$ | 100% |
| **D2 (Recovered)**| **R** | 3 | Path_A | 0.0 | $5.92 \pm 0.04$ | $49.6 \pm 1.6$ | $16.34 \pm 0.03$ | $148.2 \pm 3.2$ | 100% |
| **D2 (Recovered)**| **O** | 3 | Path_A | 0.0 | $5.94 \pm 0.07$ | $52.0 \pm 1.7$ | $16.40 \pm 0.24$ | $149.8 \pm 0.6$ | 100% |
| **D2 (Recovered)**| **F** | 3 | Path_A | 0.0 | $5.89 \pm 0.02$ | $51.1 \pm 1.0$ | $16.25 \pm 0.10$ | $151.1 \pm 7.8$ | 100% |
| **D2 (Recovered)**| **M1** | 3 | Path_B | 0.0 | **$7.89 \pm 0.02$** | **$51.3 \pm 2.0$** | **$18.25 \pm 0.09$** | **$148.8 \pm 2.4$** | 100% |

---

## 4. Key Findings & Negative Results (核心结论与负结果)

1. **Utility of Historical Information ($F, O$ vs. $R$)**:
   - In D1, historical knowledge eliminates dead-end exploration (0 vs. 1 dead end), reducing total distance by **$-18.5\%$** and total time by **$-22.3\%$**.
2. **Negative Result 1: Parity between Failure Memory and Spatial Cache in Static 2D Geometry ($F$ vs. $O$)**:
   - In static physical blockages, FailMem ($F$) and Spatial Cache ($O$) yield identical high-level topological routes. Performance differences are $<1\%$ (D1 total distance: $14.03\,\text{m}$ vs. $13.95\,\text{m}$; D1 total time: $109.5\,\text{s}$ vs. $108.7\,\text{s}$).
   - **Conclusion**: **Current empirical data has NOT proved that Failure Memory provides an advantage over Spatial Observation Caching in static 2D geometric obstruction environments.**
3. **Benefit of Dynamic Invalidation ($F$ vs. $M1$)**:
   - In D2, dynamic invalidation upon observing `FREE` unsuppresses the shorter route, saving **$2.00\,\text{m}$ ($-11.0\%$)** total distance relative to permanent suppression ($M1$). Total execution time is comparable ($151.1\,\text{s}$ vs. $148.8\,\text{s}$).
4. **Negative Result 2: H1 Action-Conditioned Scenario Feasibility Check ($n=4$)**:
   - A bounded 4-run check ([`reports/P2d-h1-feasibility-check.md`](file:///code/failmem-ros2-agent/reports/P2d-h1-feasibility-check.md)) evaluated whether aligned vs. oblique goal positions in a geometrically clear doorway create executability divergence.
   - Both profiles traversed successfully (`SUCCEEDED`, 4/4 Nav2 success, 3/4 strict arrival).
   - **Conclusion**: **本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。**

---

## 5. Scope Boundaries & Research Limitations

1. **Sample Size**: The 30-run pilot is an exploratory evaluation ($n=3$ per condition) without pre-run formal pre-registration.
2. **Deterministic Sensing**: Evaluated in Gazebo simulation without sensor noise, partial dropouts, or adversarial cache tampering.
3. **Unimplemented Conceptual Designs**: Action-Conditioned Failure Memory ($F2$) and Backoff Spatial Baseline ($O+$) are documented as formal conceptual specifications ([`reports/P2c-research-decision.md`](file:///code/failmem-ros2-agent/reports/P2c-research-decision.md)) but were not implemented or comparatively benchmarked.

---

## 6. Final Research Positioning

The contribution of this work lies in:
1. Establishing an authentic, event-driven, causally-bound failure memory architecture and zero-bypass audit replay pipeline for ROS 2 / Nav2;
2. Demonstrating the empirical boundaries where failure memory prevents dead ends and dynamic invalidation prevents detour traps;
3. Transparently showing that in static geometric environments, failure semantics do not surpass standard spatial caching, providing clear empirical guidance for future action-conditioned and heterogeneous multi-agent memory designs.
