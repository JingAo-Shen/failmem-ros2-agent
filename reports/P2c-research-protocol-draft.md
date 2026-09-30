# FailMem Milestone P2c Research Protocol: Non-Line-of-Sight & Multi-Route Failure Memory Evaluation

**Protocol Version**: 4.1 (Revised)  
**Target Milestone**: Milestone P2c  
**Date**: 2026-09-30  
**Research Focus**: Empirical Evaluation of Failure Memory vs. Spatial Observation Caching under Non-Line-of-Sight Multi-Route Conditions  

---

## 1. Core Scientific Questions & Hypotheses

Milestone P2c investigates the concrete empirical utility of execution failure memory in robotic navigation when chokepoints are non-line-of-sight (NLOS) and alternative routes are available.

Rather than asserting theoretical necessity formulas or predetermining victory conditions, this protocol formulates three testable empirical questions:

- **H1 (Utility of Historical Information)**:  
  *Does retaining past environmental state information reduce repeated exploratory traversal costs compared to purely reactive execution?*
- **H2 (Independent Value of Failure Memory vs. Observation Caching)**:  
  *Does an explicit execution failure record (associating action goals, failure preconditions, and recovery bindings) provide measurable decision advantages over a general spatial observation cache with identical evidence access?*
- **H3 (Value of Conditional Invalidation)**:  
  *Does verified invalidation of failure memory reduce unnecessary bypass detour costs when a previously blocked path is restored to a passable state?*

---

## 2. Benchmark Methods & Controlled Comparisons

To ensure strict scientific fairness, we evaluate three primary architectural paradigms (plus a non-decaying cache baseline) operating with **identical sensors, actuators, maps, exploration policies, and execution budgets**:

1. **Method R (Reactive Only / No Memory)**:
   - Evaluates only instantaneous sensor observations at the current robot pose.
   - When the state of a chokepoint is `UNKNOWN` from the current vantage point, R follows the standard uniform exploration rule (attempting the nominal shortest route).

2. **Method O (Spatial Observation Cache)**:
   - Maintains a spatial cache of verified environmental observations (`OCCUPIED` / `FREE`, spatial coordinates/region, timestamp, validity).
   - Operates without artificial short TTL decay within the episode.
   - When choosing routes at a decision junction, queries the spatial cache:
     * If Chokepoint A is cached as `OCCUPIED` (and not superseded by a newer `FREE` observation), routes via Path B.
     * If Chokepoint A is cached as `FREE`, routes via Path A.
     * If Chokepoint A is unobserved (`UNKNOWN`), follows the standard exploration rule (Path A).

3. **Method F (FailMem Failure Memory)**:
   - In addition to holding the spatial observations in O, explicitly records the **action execution failure**, the causal attribution link, and the recovery binding contract.
   - Suppresses dispatch to goals/regions guarded by active failure preconditions.
   - When verified clearance occurs (`FREE`), transitions the failure memory to `INVALIDATED` and binds subsequent dispatches to a recovery lifecycle.

4. **Method M1 (Persistent Suppression Baseline - for H3 Detour Comparison)**:
   - Records failure upon initial blockage and permanently suppresses Path A.
   - When Path A is subsequently cleared in Sequence S2, M1 continues taking the detour (Path B).
   - **Important Protocol Rule**: M1 is NOT treated as a task failure when Path B is open. Its performance is evaluated purely by the **additional trajectory distance, execution time, and route selection overhead** relative to M2/F.

### Uniform Control Principles:
- All methods share the exact same underlying Nav2 stack, costmap configurations, controller parameters, and robot kinematics.
- Condition updates and evidence freshness requirements (e.g. valid scan coverage, laser ray intersection) are identical across O and F.
- If Method F exhibits identical routing decisions and execution costs as Method O across all conditions, we will accept the empirical finding that **general historical observation caching is sufficient for this task domain**, without inventing ad-hoc rules to artificially favor F.

---

## 3. Dual-Path Arena Design & Information Properties

### 3.1 Topology & Geometry

The arena connects Room 1 (Spawn / Decision Junction $J_0: x=-2.0, y=0.0$) to Room 2 (Goal: $x=+2.0, y=0.0$) via two distinct routes:

```
                        [ Path A: Nominal Short Route (Length: ~4.5m) ]
                        +------------- [ Chokepoint A ] ---------------+
                        |                (Occluded Doorway)            |
                        | (90 deg wall)                  (90 deg wall) |
   [ Decision Junction  ]                                              [ Goal Target        ]
   [ J0: (-2.0, 0.0)    ]                                              [ Room 2: (2.0, 0.0) ]
                        |                                              |
                        | (Open Bypass Corridor)                       |
                        +----------------------------------------------+
                        [ Path B: Alternative Detour Route (Length: ~8.0m) ]
```

1. **Path A (Nominal Short Route)**:
   - Shorter nominal traversal distance ($\approx 4.5\,\text{m}$).
   - Passes through Chokepoint A at $(0.0, +1.2)$, which is occluded from Junction $J_0$ by an interior wall and a $90^\circ$ turn.
   - At $J_0$, the LiDAR cannot penetrate the wall to observe Chokepoint A $\implies \mathcal{O}(J_0) = \text{UNKNOWN}$.
2. **Path B (Detour Route)**:
   - Longer nominal traversal distance ($\approx 8.0\,\text{m}$).
   - Completely free of obstacles and always passable.

### 3.2 Nav2 Global Costmap Integrity & Shared Memory Verification
- A critical audit requirement is verifying whether the Nav2 global costmap retains previously detected obstacle markers after the robot returns to $J_0$.
- If the global costmap retains historical obstacle cells, it represents a shared source of spatial memory. The costmap state must be explicitly tracked and documented as an input to all policies, avoiding false claims that "all inputs are identical" if one policy has costmap retention while another does not.
- Global costmap settings will be identical across all methods (R, O, F).

---

## 4. Paired Historical Diagnostic Sequences (D0, D1, D2)

To evaluate H1, H2, and H3 without robot teleportation or artificial history injection, we define three physical diagnostic scenarios starting and deciding at Junction $J_0$:

- **Diagnostic D0 (Untried Baseline / Fresh State)**:
  * Robot is at Junction $J_0$ with no prior traversal history.
  * Chokepoint A state is `UNKNOWN` to local sensors.
  * *Test*: Does the policy dispatch Path A under nominal exploration?

- **Diagnostic D1 (Prior Failure Confirmed Blocked)**:
  * Robot physically traverses Path A from $J_0$, detects blockage at Chokepoint A (action aborts/fails and records `OCCUPIED` scan), and physically retreats back to $J_0$.
  * At $J_0$, local sensors currently observe `UNKNOWN` for Chokepoint A, but the event history contains the blockage.
  * *Test*: Does the policy dispatch Path B immediately (O / F), or does it re-traverse into Path A (R)?

- **Diagnostic D2 (Prior Failure Followed by Verified Clearance)**:
  * Following D1, the obstacle at Chokepoint A is cleared. The robot physically probes/observes Chokepoint A `FREE`, and returns to $J_0$.
  * At $J_0$, local sensors observe `UNKNOWN`.
  * *Test*: Does the policy revert to the shorter Path A (O / F), or does it persist on the detour Path B (M1)?

---

## 5. Quantitative Metrics

For all trials, we report separate metrics for the **History Acquisition Phase** (if applicable), the **Subsequent Decision Phase**, and the **End-to-End Total**:

1. **Dead-End Traversal Count ($N_{\text{dead}}$)**: Number of times the robot enters the blocked corridor of Path A while Chokepoint A is blocked.
2. **Post-Decision Trajectory Distance ($D_{\text{decision}}$ in meters)**: Integrated distance from decision at $J_0$ to final arrival.
3. **Post-Decision Sim Time ($T_{\text{decision}}$ in seconds)**: Sim time from decision at $J_0$ to final arrival.
4. **End-to-End Total Trajectory Distance ($D_{\text{total}}$)** and **Total Sim Time ($T_{\text{total}}$)**.
5. **Route Selection**: Path A vs. Path B.
6. **Navigation Action Dispatches & Suppressions**.
