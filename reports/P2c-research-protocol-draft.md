# FailMem Milestone P2c Research Protocol (Draft): Non-Line-of-Sight & Multi-Route Failure Memory Evaluation

**Protocol Version**: 4.0-draft  
**Target Milestone**: P2c  
**Date**: 2026-09-30  
**Research Focus**: Non-Line-of-Sight (NLOS) Information Gaps, Multi-Route Decision Bounding, and Causal Failure Memory

---

## 1. Core Scientific Question & Theoretical Formulation

### 1.1 The Fundamental Question
> **"Under what information conditions does execution failure history provide causal utility that cannot be substituted by instantaneous local perception?"**

### 1.2 Mathematical Formulation of the Information Gap

Let the environment state at time $t$ be $s_t \in \mathcal{S}$, and let the robot be positioned at a decision junction $s_{\text{junc}}$.  
The environment contains a set of potential routes $\mathcal{R} = \{R_A, R_B\}$ to a target goal $g \in \mathcal{G}$. Route $R_A$ passes through a chokepoint $C_A$.

1. **Local Observation Operator $\mathcal{O}(s_t)$**:
   - In Line-of-Sight (LOS) conditions (Milestone P2b), the distance $d(s_t, C_A) \le r_{\text{sensor}}$ and the line of sight is unoccluded:
     $$I(C_A = \text{BLOCKED}; \mathcal{O}(s_t)) > 0$$
     Instantaneous perception can fully determine the chokepoint state prior to navigation dispatch.
   - In Non-Line-of-Sight (NLOS) / Occluded conditions (Milestone P2c), $C_A$ is occluded by geometry (walls, turns) or beyond sensor range:
     $$I(C_A = \text{BLOCKED}; \mathcal{O}(s_{\text{junc}})) = 0 \iff \mathcal{O}(s_{\text{junc}}) = \text{UNKNOWN}$$

2. **Execution History $\mathcal{H}_t = \{(a_1, o_1, r_1), \dots, (a_t, o_t, r_t)\}$**:
   - If an action $a \in \mathcal{A}$ traversing route $R_A$ failed at time $\tau < t$ with failure reason $\phi_A$, the execution history retains mutual information:
     $$I(C_A = \text{BLOCKED}; \mathcal{H}_t) > 0$$
   - Therefore, at the decision point $s_{\text{junc}}$, the information gap is strictly positive:
     $$\Delta I = I(C_A = \text{BLOCKED}; \mathcal{H}_t) - I(C_A = \text{BLOCKED}; \mathcal{O}(s_{\text{junc}})) > 0$$

Failure memory is causally necessary if and only if $\Delta I > 0$ and the cost of physically reducing $\Delta I$ via exploration exceeds the routing overhead of alternative paths.

---

## 2. Paired Experimental Environment Design

### 2.1 Bifurcation World Topology ("Fork-Corridor Arena")

The benchmark arena features two topologically distinct paths connecting Room 1 (Spawn: $x=-2.0, y=0.0$) and Room 2 (Goal: $x=+2.0, y=0.0$):

```
                        [ Path A: Nominal Short Path (4.0m) ]
                        +------------- [ Chokepoint A ] ------------+
                        |                 (Occluded Box)            |
                        | (90 deg turn)              (90 deg turn)  |
   [ Spawn: (-2.0, 0.0) ]                                           [ Goal: (+2.0, 0.0) ]
   [ Junction J0        ]                                           [ Room 2            ]
                        |                                           |
                        | (Bypass corridor)                         |
                        +-------------------------------------------+
                        [ Path B: Alternative Bypass Path (7.5m)    ]
```

- **Junction $J_0$**: Robot start pose $(-2.0, 0.0)$. From $J_0$, both Path A and Path B enter separate corridors.
- **Path A (Nominal Short Path)**: Length $4.0\,\text{m}$. Contains an occluding $90^\circ$ turn before Chokepoint A ($x=0.0, y=+1.0$).
  - At $J_0$, Chokepoint A is completely occluded by the interior wall ($\mathcal{O}(J_0) = \text{UNKNOWN}$).
- **Path B (Detour / Bypass Path)**: Length $7.5\,\text{m}$. Completely clear of obstacles.

### 2.2 Paired Evaluation Conditions

To rigorously test whether failure memory is non-substitutable, we evaluate paired conditions with **identical instantaneous observations $\mathcal{O}(J_0) = \text{UNKNOWN}$** but different execution histories $\mathcal{H}_t$:

1. **Condition C1 (Fresh / Untried)**: Path A has not been attempted. Both paths are unobserved from $J_0$.
2. **Condition C2 (Prior Failure Un-cleared)**: Path A was attempted and failed due to blockage at Chokepoint A. The robot has returned / retreated to $J_0$. Current local perception at $J_0$ is $\mathcal{O}(J_0) = \text{UNKNOWN}$.
3. **Condition C3 (Prior Failure Cleared & Witnessed)**: Path A failed earlier; subsequent observation at Chokepoint A verified clearance (`doorway_state == FREE`). Robot is at $J_0$.

---

## 3. Strict, Uniform Unknown & Exploration Rules

To prevent synthetic handicapping of any baseline, all policies operate under identical exploration rules for $\text{UNKNOWN}$ states:

1. **Nominal Preference**: When all viable routes have status $\text{UNKNOWN}$ and are un-suppressed, the default planner dispatches the shortest nominal route (Path A).
2. **Suppression Routing**: When a route is suppressed (by failure memory), the planner automatically dispatches the next shortest un-suppressed route (Path B).
3. **Observation Cadence**: Observations are evaluated at $0.5\,\text{Hz}$ ($2.0\,\text{s}$ sim time) across all policies.

---

## 4. Evaluated Policy Architectures

| Policy ID | Architecture | Policy Mechanism | Expected Behavior in Condition C2 ($\mathcal{O}(J_0) = \text{UNKNOWN}$, Prior Failure on Path A) |
| :--- | :--- | :--- | :--- |
| **M0** | No Memory Baseline | Naive re-attempt of nominal route | Traverses into Path A, hits blockage, retreats/fails repeatedly (High dead-end cost). |
| **M1** | Persistent Memory | Permanent suppression of Path A upon failure | Routes to Path B immediately (0 dead-end traversals, but fails if Path A clears in S2). |
| **M2** | FailMem Conditional Memory | Precondition-guarded suppression + invalidation | Routes to Path B in C2; invalidates and re-enables Path A upon verified clearance. |
| **M3** | Instantaneous Reactive Perception | Pure reactive dispatch gating ($\text{FREE} \to \text{allow}$, $\text{OCCUPIED} \to \text{suppress}$, $\text{UNKNOWN} \to \text{explore}$) | Sees $\text{UNKNOWN}$ at $J_0 \to$ cannot differentiate C1 from C2 $\to$ must re-traverse Path A to inspect. |
| **M4** | Observation Cache / Sliding Window ($\tau$) | Short-term spatial observation buffer with timeout $\tau$ | Evaluates if short-term sensory cache is sufficient or if semantic failure memory is required. |

---

## 5. Quantitative Evaluation Metrics & Falsification Criteria

### 5.1 Primary Orthogonal Metrics

1. **Dead-End Traversal Count ($N_{\text{dead}}$)**: Number of times the robot enters the blocked corridor (Path A) when Chokepoint A is blocked.
2. **Total Traversed Distance ($D_{\text{total}}$ in meters)**: Integrated odometry distance from episode start to goal arrival.
3. **Mission Completion Sim Time ($T_{\text{mission}}$ in seconds)**.
4. **Redundant Dispatch Count ($N_{\text{redundant}}$)**.
5. **False Negative Permanent Suppression Rate ($R_{\text{false\_neg}}$)**: Fraction of episodes where clearance occurred but policy permanently failed to reach goal.

### 5.2 Falsification Criteria (Scientific Hypotheses)

- **Falsification Criterion 1 (Hypothesis of Memory Utility)**:
  - If in Condition C2, M3 (instantaneous perception) or M4 (sliding window cache) achieves dead-end traversal count $N_{\text{dead}} = 0$ without execution history, **the utility of failure memory is falsified**.
  - Conversely, if M2 achieves $N_{\text{dead}} = 0$ while M3 incurs $N_{\text{dead}} \ge 1$ (statistically significant $p < 0.01$), **the non-substitutable necessity of failure memory under NLOS is confirmed**.

- **Falsification Criterion 2 (Conditional Invalidation vs. Persistent Memory)**:
  - If in Sequence S2 (clearance after failure), M1 achieves task success rate equal to M2 ($100\%$), **conditional invalidation is falsified as redundant**.
  - Conversely, if M1 exhibits $0\%$ success (permanent suppression) while M2 achieves $100\%$ recovery, **conditional invalidation is confirmed necessary**.
