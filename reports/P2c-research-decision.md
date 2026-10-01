# FailMem Milestone P2c Research Decision & Boundary Analysis

**Date**: 2026-10-01  
**Context**: FailMem Research Team (Milestone P2c Evaluation & H1 Design)  
**Reference Code Base**: Git Commit `ad4701e`  
**Primary Dataset**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/` (30 physical runs, exploratory $n=3$)

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
     - Retaining historical information (both FailMem $F$ and Spatial Cache $O$) eliminates redundant corridor entry ($0.0 \pm 0.0$ dead ends vs. Reactive $R$'s $1.0 \pm 0.0$ dead ends).
     - FailMem reduces decision distance by **$30.3\%$** ($7.54\,\text{m}$ vs. $10.82\,\text{m}$) and total distance by **$18.5\%$** ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) compared to Reactive $R$.
     - Total execution time is reduced by **$22.3\%$** ($109.5\,\text{s}$ vs. $141.0\,\text{s}$).
     - *Conclusion*: Proves that **historical information is useful**, but does not demonstrate independent value of failure semantics over spatial caching.
   - **Scenario D2 (Cleared / Restored Environment)**:
     - Dynamic invalidation in FailMem ($F$) unsuppresses Path A upon observing verified clearance (`FREE`), saving **$2.00\,\text{m}$** ($-11.0\%$) total distance ($16.25\,\text{m}$ vs. $18.25\,\text{m}$) compared to persistent suppression baseline ($M1$).
     - Total execution time between $F$ ($151.1\,\text{s}$) and $M1$ ($148.8\,\text{s}$) is comparable ($+1.5\%$). The advantage is strictly confined to distance/path length.

---

## 2. Unverified Advantages of Failure Memory over Spatial Cache (未验证优势)

In the current single-agent static dual-path environment, **FailMem ($F$) and Spatial Observation Cache ($O$) exhibited functional routing parity**:
- D1 Total Distance: $F = 14.03 \pm 0.25\,\text{m}$ vs. $O = 13.95 \pm 0.07\,\text{m}$ ($+0.6\%$).
- D1 Total Time: $F = 109.5 \pm 1.6\,\text{s}$ vs. $O = 108.7 \pm 2.7\,\text{s}$ ($+0.7\%$).
- D2 Total Distance: $F = 16.25 \pm 0.10\,\text{m}$ vs. $O = 16.40 \pm 0.24\,\text{m}$ ($-0.9\%$).
- D2 Total Time: $F = 151.1 \pm 7.8\,\text{s}$ vs. $O = 149.8 \pm 0.6\,\text{s}$ ($+0.9\%$).

The following hypothesized advantages of failure semantics remain **unverified**:
1. **Performance Superiority in Static Geometric Blockages**: When blockages are purely spatial/geometric (e.g. physical boxes), an unconditioned 2D spatial occupancy cache and an action-conditioned failure store make identical high-level topological decisions. Current exploratory $n=3$ data have **neither proved $F$ is superior to $O$, nor proved their mathematical/statistical equivalence**.
2. **Resilience Against Spatial Cache Corruption / Noise**: The theoretical claim that failure memory is more robust against spurious clearance or noisy occupancy updates was not tested, as the current environment features deterministic Gazebo laser sensing without synthetic sensor dropouts or adversarial noise.
3. **Action-Conditioned Failure Differentiation**: Scenarios where space is geometrically *free* but an action is dynamically *infeasible* (e.g., speed, footprint, orientation, payload limits) were not evaluated in P2c.
4. **Multi-Agent / Cross-Capability Generalization**: Transfer of failure records across heterogeneous agents with different mobility constraints was outside the single-robot scope.

---

## 3. Scope of Research Contributions Supported by Current Work (现有工作支持的贡献范围)

The current codebase, protocol, and empirical findings support a concrete study with the following boundaries:

1. **System & Protocol Contribution**:
   - A reproducible benchmarking protocol and evaluation framework for event-driven failure memory in ROS 2 / Nav2 autonomous systems.
   - An immutable observation bundle architecture and verifiable chronological offline replay engine with zero-bypass audit contracts.
2. **Empirical Boundary Characterization (Supported by Data)**:
   - *Supported*: Under tested dual-path conditions, historical information (both spatial caching and failure memory) reduces redundant corridor entry (0 dead ends vs. 1 dead end, saving $-18.5\%$ distance and $-22.3\%$ time relative to Reactive $R$).
   - *Supported*: Dynamic memory invalidation reduces path length ($-11.0\%$ distance) compared to persistent suppression baseline ($M1$) when the environment recovers.
   - *Supported*: In static 2D geometric environments, failure semantics and spatial caching exhibit functional routing parity (differences $<1\%$), delineating the applicability boundaries of failure memory systems.
3. **Claims Not Supported by Current Data**:
   - *Not Supported*: Independent advantage of FailMem ($F$) over Spatial Cache ($O$) in static 2D geometric obstruction scenarios.
   - *Not Supported*: Claim of mathematical or statistical equivalence between $F$ and $O$ (data is exploratory $n=3$, not a general proof of equivalence).
   - *Not Supported*: Guaranteed general superiority in arbitrary unexamined deployment scenarios.

---

## 4. Architectural Analysis: Conflicts in Current `failure_memory.py` with Action-Conditioned Failure

Reviewing `src/failure_memory.py` identifies fundamental conflicts with action-conditioned failure scenarios:

1. **Memory Admission Gate (`is_failure_eligible_for_doorway_memory`, Line 41)**:
   - Current implementation strictly requires `doorway_state == "OCCUPIED"`.
   - If an action fails due to controller oscillation/kinematics while the doorway is geometrically clear (`doorway_state == "FREE"`), `failure_memory.py` currently **rejects** failure memory creation.
2. **Memory Invalidation Rule (`update_memory_on_perception`, Line 350)**:
   - Current implementation automatically invalidates active failure memory whenever any observation of `doorway_state == "FREE"` is received.
   - For an action-conditioned failure, geometric `FREE` is the exact operational condition under which the action failed. Unconditionally wiping the memory upon seeing `FREE` causes an immediate cycle of repeated failures.

---

## 5. Conceptual Design of Extended Method F2 and Strong Baseline O+ (未实现与未比较的方案设计)

> [!NOTE]
> **Status**: The designs below represent **conceptual architectural specifications** for potential future extensions. They are **not implemented, not evaluated, and not claimed as completed empirical contributions** in the current study.

### 5.1 Extended Method: F2 (Action-Conditioned Failure Memory - Conceptual Design)
- **Separation of Legacy F and F2**: Legacy Method $F$ and its existing benchmark records are strictly preserved. $F2$ is explicitly defined as an extension.
- **Stable `action_profile_id`**:
  - `goal_uuid` identifies only a single execution instance and **cannot** be used as a matching key across episodes.
  - $F2$ defines a stable, deterministic key:
    $$\text{action\_profile\_id} = \text{hash}(\text{planner\_id}, \text{controller\_id}, v_{\text{max}}, \omega_{\text{max}}, \text{footprint\_spec}, \text{approach\_vector})$$
- **Dual-Category Failure Taxonomy**:
  1. *Type I: Spatial Obstruction Failure* (physical obstacle present, `doorway_state == "OCCUPIED"`). Invalidation condition: verified spatial `FREE`.
  2. *Type II: Action-Conditioned Kinematic Failure* (space geometrically open, action aborted by controller/planner). Invalidation condition: NOT invalidated by spatial `FREE`. Invalidation requires explicit capability verification (e.g. reconfiguration, capability reset, or verified alternative profile execution).
- **Asymmetric Action Binding**:
  - A failure under $a_{\text{fast}}$ suppresses $a_{\text{fast}}$ for the specified region, but does **not** suppress $a_{\text{slow}}$ if $a_{\text{slow}}$ has a compatible footprint/velocity profile.
  - A successful traversal under $a_{\text{slow}}$ does **not** automatically prove that $a_{\text{fast}}$ has been restored.

### 5.2 Strong Baseline: O+ (Spatial Cache + Action Retry Backoff - Conceptual Design)
- **Definition**: $O+$ consists of standard Spatial Observation Cache combined with a generic exponential action/region retry backoff mechanism.
- **Fairness & Symmetry**:
  - $O+$ receives the exact same sensor inputs (raw laser scans, TF transforms, costmap ROIs) and the exact same Nav2 action terminal results as $F2$.
  - $O+$ does not rely on failure semantics, but maintains a standard failure retry counter per region/action.
  - After $K$ consecutive action failures (default $K=1$), $O+$ suppresses the region/action for a backoff horizon.
- **Core Testable Distinction**:
  - $F2$ maintains explicit causal precondition bindings that distinguish *which* action configuration failed and under *what* physical profile.
  - $O+$ applies a generic retry suppression without causal parameter binding.

### 5.3 Clear Distinction of Spatial Representation Levels
To avoid ungrounded assumptions (such as "entire costmap = 0"), four distinct physical/representational layers are formally distinguished:
1. **LiDAR Ray Pass-Through**: Geometric line-of-sight clearance across sensor beams.
2. **Raw Grid Occupancy**: Static/dynamic cell values in the global costmap ($0$ = free, $-1$ = unknown, $\ge 100$ = lethal).
3. **Costmap Inflation & Clearance**: Non-lethal inscribed/inflation costs ($1 \dots 99$) reflecting proximity to walls.
4. **Kinematic / Controller Navigability**: Feasibility of the robot's local trajectory generator (`DWBLocalPlanner`) tracking a path given velocity, acceleration limits, footprint inflation, and doorway approach angle.

---

## 6. Follow-Up Feasibility Exploration (H1) and Stopping Conclusion

### 6.1 Bounded Physical Feasibility Check Outcome
A separate, strictly bounded 4-run feasibility check ([`reports/P2d-h1-feasibility-check.md`](reports/P2d-h1-feasibility-check.md)) was executed to test whether candidate goal placements (`act_aligned` vs. `act_oblique`) produce reproducible executability differences in geometrically unobstructed space:
- **Result**: Both candidate actions successfully navigated through the doorway (`SUCCEEDED`, 4/4 Nav2 success, 3/4 strict physical arrival). No action aborts or timeout cancellations occurred.
- **Verdict**: **本场景未建立 (Scenario Not Established - No-Go)**.
- **Formal Conclusion**:
  > *本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。*

### 6.2 Final Stopping Decision
In accordance with pre-established protocol stopping rules:
1. Zero parameter tuning or goal hunting was conducted.
2. The 20-run comparative experiment matrix for Hypothesis H1 is **strictly aborted**.
3. All research findings and contributions are consolidated upon the established P2c boundary results.

