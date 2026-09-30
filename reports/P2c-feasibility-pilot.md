# FailMem Milestone P2c Feasibility Pilot Report

**Date**: 2026-09-30  
**Phase**: Milestone P2c Feasibility Pilot & Minimal Dual-Path Diagnosis  
**Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (v4.1)  
**Evidence Artifacts**:
- Diagnosis Output: `reports/evidence/p2c_pilot/p2c_pilot_diagnosis_results.json`
- Sightline Occlusion Proof: `reports/evidence/p2c_pilot/sightline_occlusion_proof.json`
- Map / Model: `configs/p2c_dualpath_world.model`, `configs/p2c_dualpath_world.yaml`, `configs/p2c_dualpath_world.pgm`

---

## 1. Executive Summary & Core Diagnostic Findings

This pilot investigates the three core hypotheses formulated in the revised Milestone P2c protocol:
- **H1 (History Utility)**: **CONFIRMED**. In Scenario D1 (Chokepoint A blocked), retaining history (O and F) eliminates repeated dead-end traversals into Path A, reducing decision phase distance from $13.0\,\text{m}$ (Method R) to $7.8\,\text{m}$ (Methods O and F), and decision time from $58.0\,\text{s}$ to $33.2\,\text{s}$ (a $42.8\%$ time reduction).
- **H2 (Failure Memory vs. Observation Cache)**: **MECHANICALLY EQUIVALENT IN SPATIAL ROUTING**. Method O (spatial observation cache) and Method F (FailMem failure memory) achieve identical routing decisions, identical trajectory lengths, and zero dead-end traversals across all scenarios (D0, D1, D2). For purely spatial reachability tasks, general historical observation caching without action semantics is sufficient.
- **H3 (Conditional Invalidation vs. Persistent Suppression)**: **CONFIRMED**. In Scenario D2 (Chokepoint A restored to FREE), conditional invalidation (O and F) successfully re-enables the shorter Path A ($4.8\,\text{m}$, $21.2\,\text{s}$), avoiding the persistent detour penalty incurred by M1 ($7.8\,\text{m}$, $33.2\,\text{s}$, $+3.0\,\text{m}$ distance penalty, $+12.0\,\text{s}$ time penalty).

---

## 2. Environment Verification & Sightline Occlusion Proof

### 2.1 Geometric Setup
- **Decision Junction $J_0$**: $(-2.20, 0.00)$.
- **Goal Target in Room 2**: $(+2.20, 0.00)$.
- **Central Island**: $[-1.60, +1.60] \times [-0.40, +0.40]$ (Thickness $0.80\,\text{m}$).
- **Path A (Nominal Short Route)**: Length $4.8\,\text{m}$, passes through Chokepoint A at $(0.00, 0.95)$.
- **Path B (Detour Route)**: Length $7.8\,\text{m}$, completely open along the South corridor ($y=-0.95$).

### 2.2 Sightline Occlusion Audit
From Junction $J_0 (-2.20, 0.00)$ to Chokepoint A $(0.00, 0.95)$, the line-of-sight ray enters the Central Island at $x=-1.60, y=0.259$, intersecting the interior wall.  
- Direct ray distance: $2.396\,\text{m}$.
- Line-of-sight status: **Strictly Occluded (`line_of_sight_occluded: True`)**.
- Junction local sensor observation: **`UNKNOWN`** (`junction_local_observation: UNKNOWN`).

### 2.3 Nav2 Costmap Shared State & Memory Contribution
- **Global Costmap Behavior**: When a robot detects an obstacle at Chokepoint A during the probe in D1, the Nav2 global costmap marks the corresponding grid cells as occupied. If the global costmap retains these cells, the global planner itself can route around the obstacle.
- **Shared Memory Source**: The Nav2 global costmap operates as a spatial occupancy memory shared across all algorithms. Unless the costmap is explicitly flushed, the underlying navigation stack retains spatial history.
- **Attribution Rule**: In benchmark evaluations, routing advantages arising from costmap occupancy must be recognized as shared spatial memory, not exclusively attributed to higher-level failure memory.

---

## 3. Full Diagnostic Execution Matrix (D0, D1, D2)

| Scenario | Method | Description | Decision Route | Dead-End Traversals | Decision Dist ($m$) | Decision Time ($s$) | Total End-to-End Dist ($m$) | Total End-to-End Time ($s$) |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **D0 (Fresh)** | **R** | Reactive Only | Path A | 0 | 4.8 | 21.2 | 4.8 | 21.2 |
| **D0 (Fresh)** | **O** | Spatial Obs Cache | Path A | 0 | 4.8 | 21.2 | 4.8 | 21.2 |
| **D0 (Fresh)** | **F** | FailMem Memory | Path A | 0 | 4.8 | 21.2 | 4.8 | 21.2 |
| **D0 (Fresh)** | **M1**| Persistent Suppression| Path A | 0 | 4.8 | 21.2 | 4.8 | 21.2 |
| **D1 (Blocked)** | **R** | Reactive Only | Path A $\to$ Path B | **1** | **13.0** | **58.0** | **18.2** | **85.8** |
| **D1 (Blocked)** | **O** | Spatial Obs Cache | Path B | **0** | **7.8** | **33.2** | **13.0** | **61.0** |
| **D1 (Blocked)** | **F** | FailMem Memory | Path B | **0** | **7.8** | **33.2** | **13.0** | **61.0** |
| **D1 (Blocked)** | **M1**| Persistent Suppression| Path B | **0** | **7.8** | **33.2** | **13.0** | **61.0** |
| **D2 (Cleared)** | **R** | Reactive Only | Path A | 0 | 4.8 | 21.2 | 15.2 | 74.8 |
| **D2 (Cleared)** | **O** | Spatial Obs Cache | Path A | 0 | 4.8 | 21.2 | 15.2 | 74.8 |
| **D2 (Cleared)** | **F** | FailMem Memory | Path A | 0 | 4.8 | 21.2 | 15.2 | 74.8 |
| **D2 (Cleared)** | **M1**| Persistent Suppression| Path B (Detour) | 0 | **7.8** (+3.0m) | **33.2** (+12.0s) | **18.2** | **86.8** |

---

## 4. Discussion & Scientific Decision on Failure Memory vs. Observation Cache

### 4.1 Why O and F are Equivalent in Pure Spatial Routing
In single-robot static spatial navigation:
1. An execution failure at a doorway is causally reducible to spatial occupancy (`doorway_state == OCCUPIED`).
2. A spatial observation cache O recording `(region, state, timestamp)` provides the exact same high-level routing signal as a failure memory entry F recording `(goal, failure_precondition, state)`.
3. As long as O does not artificially discard valid observations (no aggressive TTL decay), O achieves identical Pareto optimality as F.

### 4.2 Where Failure Memory Retains Unique Scientific Value
Explicit failure memory provides unique advantages beyond spatial observation caching under three specific conditions:
1. **Non-Spatial / Dynamic Action Failures**: Failures caused by actuator torque limits, robot payload weight, kinetic friction on slopes, or dynamic planning timeouts where the environment is geometrically free (`doorway_state == FREE`) but the specific robot/action cannot execute the trajectory.
2. **Action-Precondition Causal Binding**: Scenarios where a failure requires a specific causal prerequisite action (e.g. flipping a switch, opening a door latch, clearing an interlock) rather than passive environmental disappearance.
3. **Multi-Agent / Role-Specific Failure Attribution**: Where an obstacle blocks a large robot (Waffle) but is passable by a small robot (Burger), requiring failure memory to bind agent capabilities to execution history.
