# FailMem Milestone P2c Research Decision & Boundary Analysis

**Date**: 2026-10-01  
**Author / Context**: FailMem Research Team (Milestone P2c Evaluation)  
**Reference Code Base**: Git Commit `84fd245`  
**Primary Dataset**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/` (30 physical runs)

---

## 1. What Has Been Verified So Far? (已验证内容)

Across the P2c development and evaluation phases, the following components and behaviors have been empirically verified:

1. **Authentic Action-Level Failure & Observation Architecture**:
   - Replaced synthetic mock failure returns with genuine ROS 2 Nav2 `NavigateToPose` action client dispatches, action server goal UUID tracking, feedback monitoring, and authentic terminal status codes (`ABORTED`, `CANCELED`, `SUCCEEDED`).
   - Implemented immutable observation bundles (`create_observation_bundle` + `evaluate_observation_bundle`) preserving raw laser scans, TF transforms, and raw 2D costmap ROI subgrid matrices (`subgrid_matrix`) with untruncated float timestamps before evaluation.
   - Enforced hard-stop execution: If historical data collection fails to produce protocol-compliant physical evidence, the system halts immediately with 0 decision goals dispatched.

2. **Strict Chronological Memory Lifecycle & Independent Replay Audit**:
   - Developed an independent replayer (`scripts/replay_and_score_p2c.py`) that recomputes raw subgrid cell counts and 3-valued perception from raw sensor data, ignoring disk summary claims.
   - Enforced zero-bypass schema validation rejecting missing, empty, or `"unknown"` placeholder fields across `memory_id`, `failed_action_id`, `goal_uuid`, `observation_id`, `region_id`, `map_version`, `target_goal`, and `failure_reason`.
   - Validated causality ($t_{rec} \ge \max(t_{action\_end}, t_{obs\_eval}) - 0.05\,\text{s}$; $t_{inv} \ge \max(t_{fail}, t_{free\_obs\_eval}) - 0.05\,\text{s}$) and time-boundary isolation (decisions at $t_{dec}$ only consume events prior to $t_{dec} + 0.05\,\text{s}$).
   - Verified 100% pass across 21 paired positive-negative corruption tests (`tests/test_p2c_event_driven.py`).

3. **Empirical Findings on the 30-Run Physical Comparative Benchmark (`p2c_pilot_20261001_022711_0d3c35`)**:
   - **Scenario D1 (Confirmed Blockage)**:
     - Retaining historical information (both FailMem $F$ and Spatial Cache $O$) completely eliminates redundant corridor entry ($0.0 \pm 0.0$ dead ends vs. Reactive $R$'s $1.0 \pm 0.0$ dead ends).
     - FailMem reduces decision distance by **$30.3\%$** ($7.54\,\text{m}$ vs. $10.82\,\text{m}$) and total distance by **$18.5\%$** ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) compared to Reactive $R$.
     - Total execution time is reduced by **$22.3\%$** ($109.5\,\text{s}$ vs. $141.0\,\text{s}$).
   - **Scenario D2 (Cleared / Restored Environment)**:
     - Dynamic invalidation in FailMem ($F$) successfully unsuppresses Path A upon observing verified clearance (`FREE`), saving **$2.00\,\text{m}$** ($-11.0\%$) total distance ($16.25\,\text{m}$ vs. $18.25\,\text{m}$) compared to the persistent suppression baseline ($M1$).
     - Total execution time between $F$ ($151.1\,\text{s}$) and $M1$ ($148.8\,\text{s}$) is comparable ($+1.5\%$) due to the narrow corridor turning dynamics.

---

## 2. Unverified Advantages of Failure Memory over Spatial Cache (未验证优势)

In the current single-agent static dual-path environment, **FailMem ($F$) and Spatial Observation Cache ($O$) exhibited functional routing parity**:
- D1 Total Distance: $F = 14.03 \pm 0.25\,\text{m}$ vs. $O = 13.95 \pm 0.07\,\text{m}$ ($+0.6\%$).
- D1 Total Time: $F = 109.5 \pm 1.6\,\text{s}$ vs. $O = 108.7 \pm 2.7\,\text{s}$ ($+0.7\%$).
- D2 Total Distance: $F = 16.25 \pm 0.10\,\text{m}$ vs. $O = 16.40 \pm 0.24\,\text{m}$ ($-0.9\%$).
- D2 Total Time: $F = 151.1 \pm 7.8\,\text{s}$ vs. $O = 149.8 \pm 0.6\,\text{s}$ ($+0.9\%$).

The following hypothesized advantages of failure semantics remain **unverified**:
1. **Performance Superiority in Static Geometric Blockages**: When blockages are purely spatial/geometric (e.g. physical boxes), an unconditioned 2D spatial occupancy cache and an action-conditioned failure store make identical high-level topological decisions.
2. **Resilience Against Spatial Cache Corruption / Noise**: The theoretical claim that failure memory is more robust against spurious clearance or noisy occupancy updates was not tested, as the current environment features deterministic Gazebo laser sensing without synthetic sensor dropouts or adversarial noise.
3. **Action-Conditioned Failure Differentiation**: Scenarios where space is geometrically *free* but an action is dynamically *infeasible* (e.g., speed, footprint, orientation, payload limits) were not evaluated.
4. **Multi-Agent / Cross-Capability Generalization**: Transfer of failure records across heterogeneous agents with different mobility constraints was outside the single-robot scope.

---

## 3. Scope of Research Contributions Supported by Current Work (现有工作支持的贡献范围)

The current codebase, protocol, and empirical findings fully support a solid, publication-grade contribution with the following positioning:

1. **System & Protocol Contribution**:
   - A rigorous, fully reproducible benchmarking protocol and evaluation framework for event-driven failure memory in ROS 2 / Nav2 autonomous systems.
   - An immutable observation bundle architecture and verifiable chronological offline replay engine with zero-bypass audit contracts.
2. **Empirical Boundary Characterization**:
   - Quantitative demonstration that historical information (both spatial caching and failure memory) significantly reduces redundant exploration in NLOS environments ($-18.5\%$ distance, $-22.3\%$ time).
   - Empirical proof that dynamic memory invalidation is essential to prevent permanent detour penalties ($-11.0\%$ distance overhead) when environments recover.
   - A transparent scientific finding that in static 2D geometric environments, failure semantics and spatial caching converge in routing efficiency, delineating the exact applicability boundaries of failure memory systems.

---

## 4. Decision: Is It Worthwhile to Seek Independent Value for Failure Semantics? (是否继续探索独立价值)

### 4.1 Decision Assessment
- **Option A (Conclude & Publish Current Boundary Results)**: Package the existing verified framework, the 30-run dataset, the 21-test audit engine, and the empirical convergence findings as a complete, transparent study titled *"Applicability Boundaries and Verifiable Evaluation of Event-Driven Failure Memory in Mobile Robot Navigation"*.
- **Option B (Test Exactly One Minimal Distinguishing Hypothesis)**: Formulate a single, fair, and tightly bounded hypothesis where spatial caching and failure memory diverge by construction, execute a strictly bounded trial ($n=5$, $\le 20$ runs), and terminate immediately if not confirmed.

**Recommendation**: We formulate **ONE minimal, falsifiable follow-up hypothesis** below. If this hypothesis is not confirmed within the allocated budget, we immediately default to Option A.

---

## 5. Single Minimal Follow-Up Hypothesis Design (单一最小后续假设)

### 5.1 Hypothesis Statement
> **Hypothesis H1 (Action-Conditioned Kinematic Infeasibility in Geometrically Free Space)**:  
> *In a navigation environment where a passage is geometrically unoccupied (LiDAR ray pass-through verified, costmap cell values = 0), but a specific high-level navigation action $a_{\text{fast}}$ (or directional entry) consistently fails due to local controller kinematic/oscillation limits in narrow geometry, a Spatial Observation Cache ($O$) will incorrectly treat the passage as navigable and repeatedly attempt $a_{\text{fast}}$, whereas FailMem ($F$) will bind the failure to $(a_{\text{fast}}, \text{region})$ and autonomously select the viable bypass route, achieving zero repeated action failures and significantly lower execution cost.*

### 5.2 Fairness & Symmetry Guarantees
1. **Identical Sensor & Action Feedback**: Both $F$ and $O$ receive the exact same raw laser scans, TF transforms, costmap ROIs, and Nav2 action server feedback.
2. **No Artificial Weakening of $O$**: Method $O$ uses the standard spatial occupancy logic (marking unobstructed space as `FREE`). It is not artificially degraded or impaired.
3. **Explicit Mechanism Distinction**:
   - $O$ operates on the premise: $\text{SpatialState}(\text{region}) = \text{FREE} \implies \text{Action Executable}$.
   - $F$ operates on the premise: $\text{ActionExecutable}(a, \text{region}) \iff \text{SpatialState} = \text{FREE} \land \neg \text{ActiveFailure}(a, \text{region})$.

### 5.3 Concrete Testbed Setup
- **Geometry**: The existing `p2c_dualpath_world` layout is retained.
- **Modification**: Doorway width is adjusted to $0.52\,\text{m}$ (robot width $0.38\,\text{m}$), and a directional entry angle or controller velocity profile is applied such that Nav2 local planner (`DWBLocalPlanner`) consistently times out / oscillates on action $a_1$ while spatial LiDAR rays pass through completely unobstructed.
- **Conditions**:
  - `D1_kin_R`: Reactive (local perception only).
  - `D1_kin_O`: Spatial Observation Cache (records `FREE` from history, dispatches $a_1$).
  - `D1_kin_F`: FailMem (records failure of $a_1$, suppresses $a_1$, dispatches Path B).
  - `D1_kin_M1`: Persistent baseline.

### 5.4 Falsification Criteria (证伪条件)
The hypothesis $H_1$ shall be deemed **refuted / falsified** if ANY of the following occur:
1. Nav2 standard recovery behaviors or costmap inflation allow Method $O$ to successfully execute $a_1$ through the narrow passage within nominal timeout.
2. Method $O$ with a generic single-retry limit achieves comparable total distance and time (difference $< 10\%$) without specialized failure memory.
3. Method $F$ fails to correctly invalidate or unsuppress when an alternative, viable action $a_{\text{slow}}$ is attempted.

### 5.5 Experiment Cost & Hard Stopping Criteria (实验成本与停止条件)
- **Sample Size**: Exactly $n=5$ per condition $\times$ 4 conditions = **20 physical simulation runs maximum**.
- **Execution Budget**: Maximum 1 hour of total simulation time.
- **Stopping Rule**: If after 20 runs, Method $F$ does not demonstrate a statistically distinct advantage ($\ge 20\%$ cost savings and $>0$ failure avoidance over $O$), **all further exploration of failure semantics shall be permanently halted**, and the paper shall be finalized based on the empirical boundary findings established in Milestone P2c.

---

## 6. Summary Conclusion

Milestone P2c has successfully established the authenticity, auditability, and empirical baseline of failure memory in ROS 2. Rather than pursuing unjustified claims of universal superiority, future efforts must strictly adhere to the bounded hypothesis $H_1$ or conclude with the rigorous boundary analysis already delivered.
