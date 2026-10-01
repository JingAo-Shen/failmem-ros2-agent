# Verified Failure Memory for Cross-Episode Robot Navigation: An Auditable Evaluation and Exploratory Boundary Study

**Anonymous Authors**

---

## Abstract

Autonomous mobile robots navigating dynamic indoor environments frequently encounter execution failures at physical chokepoints, narrow passages, and transient blockages. While standard navigation architectures (e.g., ROS 2 Nav2) employ reactive intra-episode recovery behaviors, they lack structured cross-episode memory, leading to repetitive dead-end retries across subsequent tasks. Conversely, verbal self-reflection frameworks in embodied AI store unstructured text logs that lack physical sensor postcondition grounding and spatial expiration semantics. In this work, we present **FailMem**, an event-driven, causally-bound failure memory architecture for autonomous mobile robots. FailMem records immutable observation bundles comprising raw LiDAR ranges, TF transforms, and raw 2D costmap regions-of-interest (ROIs), binding navigation failures to specific execution regions and action identities while dynamically invalidating suppression upon verified sensory clearance. To ensure complete scientific reproducibility and eliminate unverified synthetic abstractions, we implement an independent cryptographic replay audit pipeline that recomputes sensory metrics directly from raw physical observations. Evaluated across 30 physical simulation runs in Gazebo 11 with ROS 2 Nav2 ($n=3$ per condition), FailMem ($F$) eliminates redundant dead-end traversals relative to a memory-less reactive baseline ($R$), reducing total travel distance by $-18.5\%$ ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) and total execution time by $-22.3\%$ ($109.5\,\text{s}$ vs. $141.0\,\text{s}$). Furthermore, dynamic memory invalidation saves $-11.0\%$ total distance relative to permanent suppression ($M1$) upon environmental recovery. Crucially, our exploratory findings reveal that under static 2D geometric blockages, FailMem and a spatial observation caching baseline ($O$) achieve functional routing parity with $<1\%$ difference ($14.03\,\text{m}$ vs. $13.95\,\text{m}$), demonstrating that failure semantics do not exhibit an empirical advantage over spatial caching in static 2D geometry. Finally, a pre-registered limited feasibility trial ($n=4$) for candidate action-conditioned execution ($H_1$) confirmed that local planners negotiated narrow inflation margins without controller abortion, establishing clear operational boundaries and motivating future action-profiled memory architectures.

---

## 1. Introduction

Autonomous mobile robots deployed in complex indoor facilities (e.g., warehouses, hospitals, offices) must repeatedly navigate through shared corridors and doorways. In such environments, unmapped physical blockages—such as temporary cargo staging or closed passage doors—prevent robots from traversing nominal shortest paths. Standard navigation systems, such as the ROS 2 Navigation Stack (Nav2) \cite{macenski2023robot}, rely on layered 2D costmaps \cite{lu2014layered} and reactive recovery behaviors (e.g., in-place spinning, backing up, costmap clearing). While effective for local collision avoidance, these mechanisms operate strictly within the lifetime of an active navigation goal. When a new task is dispatched from a distant starting location, the robot has no structured record of prior execution failures in non-line-of-sight (NLOS) corridors, resulting in repeated traversal attempts into known dead ends before local sensors can re-detect the obstruction.

To avoid redundant exploration, two primary paradigms have emerged:
1. **Spatial Occupancy Caching**: Updating global geometric occupancy grids (e.g., Costmap2D \cite{lu2014layered}, OctoMap \cite{hornung2013octomap}, Voxblox \cite{oleynikova2017voxblox}) whenever sensor observations indicate occupied space.
2. **Episodic Failure Memory & Verbal Reflection**: Storing execution logs, error traces, or natural language self-reflections (e.g., Reflexion \cite{shinn2023reflexion}, REFLECT \cite{liu2023reflect}) to guide high-level task planners.

However, existing memory implementations suffer from critical scientific and operational shortcomings. Verbal reflection mechanisms typically store ungrounded natural language strings in prompt contexts, lacking physical sensor postcondition verification and spatial invalidation rules when the environment changes. Furthermore, historical benchmarks in embodied AI frequently rely on synthetic mock state machines with simplified coordinate approximations, obscuring actual controller dynamics, timing delays, and sensor noise.

To address these challenges, we make the following contributions:
1. **Auditable Event-Driven Architecture**: We formalize FailMem, integrating genuine ROS 2 Humble Nav2 action clients with immutable observation bundles that preserve raw LiDAR point clouds, TF transforms, and raw 2D costmap ROI subgrids before evaluation.
2. **Cryptographic Independent Replay Engine**: We construct an independent replay verification suite that reconstructs memory lifecycles and physical trajectories directly from raw serialized sensor records against SHA256 checksums, enforcing strict chronological causality and rejecting placeholder records.
3. **Rigorous Empirical Evaluation & Boundary Analysis**: Across 30 physical simulation runs in Gazebo 11 across three distinct scenarios (unobstructed, blocked, and recovered), we demonstrate that FailMem eliminates redundant dead-end exploration ($-18.5\%$ distance vs. Reactive $R$) and prevents permanent detour traps ($-11.0\%$ distance vs. Persistent $M1$).
4. **Transparent Negative Results & Operational Boundaries**: We show that in static 2D geometric blockages, FailMem and spatial caching ($O$) exhibit identical routing decisions ($<1\%$ difference), proving that failure semantics provide no independent advantage over spatial caching under static geometry. We also report a pre-registered 4-run feasibility study on action-conditioned navigation ($H_1$), defining the exact requirements for future action-profiled memory systems ($F2$).

---

## 2. Related Work

### 2.1 Spatial Occupancy Mapping & Costmaps
Layered 2D grid costmaps \cite{lu2014layered, macenski2023robot} represent obstacles by updating cell costs via sensor ray casting. 3D volumetric representations such as OctoMap \cite{hornung2013octomap} and Voxblox \cite{oleynikova2017voxblox} provide continuous signed distance fields for trajectory optimization. While spatial mapping accurately reflects geometric obstacles, it treats all unobserved space identically and does not capture action-specific execution failures (e.g., kinematic infeasibility in narrow passages).

### 2.2 Execution Monitoring & Robot Recovery
Deliberative robotics architectures \cite{fikes1971strips, simmons1998xavier, ingrand2014deliberation} have long emphasized execution monitoring and plan repair. In modern navigation stacks \cite{macenski2023robot}, recovery behaviors are triggered reactively when local planners fail. However, these recoveries discard diagnostic state upon episode completion, necessitating explicit cross-episode memory frameworks.

### 2.3 LLM Reflection & Agent Memory
Recent embodied AI systems leverage large language models for planning and verbal self-reflection \cite{shinn2023reflexion, ahn2022can, huang2022inner, liu2023reflect}. While verbal memory improves high-level sequencing across trials, it operates on unstructured text tokens without physical sensor grounding or geometric expiration guarantees.

---

## 3. The FailMem Architecture & Verification Pipeline

```
+-----------------------------------------------------------------------------+
|                          Action Dispatcher & Planner                        |
+-----------------------------------------------------------------------------+
         |                                                 ^
         | [1] Dispatch Goal UUID                          | [5] Invalidate
         v                                                 |     on FREE
+-----------------------+     [3] Raw TF / LiDAR / ROI    +-------------------+
|      ROS 2 Nav2       |-------------------------------->| Immutable Sensor  |
| NavigateToPose Action |                                 |    Observation    |
+-----------------------+                                 +-------------------+
         |                                                         |
         | [2] ABORTED / TIMEOUT Code                              | [4] Causality Check
         v                                                         v
+-----------------------------------------------------------------------------+
|                     Event-Driven Failure Memory Store                       |
|     Record: (t_fail, goal_uuid, action_id, region_id, costmap_roi)          |
+-----------------------------------------------------------------------------+
```

### 3.1 Immutable Observation Bundles
Before evaluating passage clearance, FailMem constructs an immutable observation bundle $B$:
$$B = \langle \text{obs\_id}, \mathbf{z}_{\text{scan}}, \mathbf{T}_{\text{map}\to\text{base}}, \mathbf{M}_{\text{costmap\_ROI}}, t_{\text{msg}}, t_{\text{capture}}, t_{\text{eval}} \rangle$$
Doorway clearance is classified into a 3-valued perception state:
$$\text{State}(B) = \begin{cases} \text{OCCUPIED}, & \text{if } N_{\text{hits}} > 0 \text{ or } \text{mean}(\mathbf{M}_{\text{costmap\_ROI}}) \ge \tau_{\text{occ}} \\ \text{FREE}, & \text{if } N_{\text{hits}} = 0 \text{ and } N_{\text{pass\_through}} \ge 8 \\ \text{UNKNOWN}, & \text{otherwise} \end{cases}$$

### 3.2 Memory Lifecycle & Dynamic Invalidation
- **Failure Commitment**: When an action fails in an occupied region, a memory record $M$ is committed:
  $$M = \langle \text{mem\_id}, t_{\text{fail}}, \text{goal\_uuid}, \text{action\_id}, \text{region\_id}, \mathbf{M}_{\text{costmap\_ROI}} \rangle$$
- **Dynamic Invalidation**: When the robot subsequently observes the passage as $\text{State}(B) = \text{FREE}$ at time $t_{\text{free}} \ge t_{\text{fail}}$, the memory is transitioned to $\text{INVALIDATED}$, unsuppressing the route.

### 3.3 Independent Replay & Audit Pipeline
To prevent reliance on unverified runtime summaries, an independent offline replayer (`scripts/replay_and_score_p2c.py`) reads raw serialized sensor arrays, validates SHA256 checksums, re-computes subgrid cell statistics, integrates continuous odometry trajectories, and validates chronological causality ($t_{\text{rec}} \ge \max(t_{\text{act}}, t_{\text{obs}})$).

---

## 4. Experimental Setup & Benchmarking Protocol

### 4.1 Physical Simulation Environment
Experiments are executed in ROS 2 Humble with Gazebo 11 simulating a TurtleBot3 Waffle robot in a dual-path indoor environment (`configs/p2c_dualpath_world.model`). The environment features a primary corridor (Path A, nominal length $6.2\,\text{m}$) with a $0.80\,\text{m}$ doorway chokepoint, and an alternate unobstructed corridor (Path B, nominal length $13.9\,\text{m}$).

### 4.2 Evaluated Scenarios
- **Scenario D0 (Baseline Clear)**: Primary doorway is unobstructed. Robot navigates directly along Path A.
- **Scenario D1 (Blocked Chokepoint)**: Primary doorway is blocked by a physical box obstacle. Path A is impassable; robot must route via Path B.
- **Scenario D2 (Recovered Environment)**: Obstacle is removed after prior failure. Robot starts with prior memory of blockage and can observe clearance at Decision Junction $J_0$.

### 4.3 Evaluated Methods
1. **Reactive Baseline ($R$)**: No cross-episode memory; attempts Path A until local sensors detect blockage, then executes recovery/reroute.
2. **Spatial Observation Cache ($O$)**: Caches 2D geometric occupancy observed at $J_0$.
3. **FailMem ($F$)**: Event-driven failure memory with dynamic perception-driven invalidation.
4. **Persistent Suppression ($M1$)**: Static failure memory that suppresses Path A permanently without dynamic invalidation.

---

## 5. Empirical Results & Boundary Analysis

### 5.1 30-Run Comparative Benchmark Results

Table 1 summarizes performance across 30 physical simulation runs ($n=3$ per condition, reporting mean $\pm$ sample standard deviation with Bessel correction $\text{ddof}=1$).

| Scenario | Method | $n$ | Actual Route | Dead-End Traversals | Decision Dist (m) | Decision Time (s) | Total Dist (m) | Total Time (s) | Replay Audit Pass |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0** | $R$ | 3 | Path_A | $0.0 \pm 0.0$ | $6.160 \pm 0.040$ | $51.533 \pm 1.662$ | $6.160 \pm 0.040$ | $51.533 \pm 1.662$ | 3/3 (100%) |
| **D0** | $O$ | 3 | Path_A | $0.0 \pm 0.0$ | $6.203 \pm 0.012$ | $49.967 \pm 0.850$ | $6.203 \pm 0.012$ | $49.967 \pm 0.850$ | 3/3 (100%) |
| **D0** | $F$ | 3 | Path_A | $0.0 \pm 0.0$ | $6.196 \pm 0.031$ | $49.900 \pm 0.458$ | $6.196 \pm 0.031$ | $49.900 \pm 0.458$ | 3/3 (100%) |
| **D1** | $R$ | 3 | Path_A $\to$ Path_B | $1.0 \pm 0.0$ | $10.816 \pm 0.067$ | $82.067 \pm 4.388$ | $17.220 \pm 0.243$ | $141.000 \pm 5.912$ | 3/3 (100%) |
| **D1** | $O$ | 3 | Path_B | $0.0 \pm 0.0$ | $7.550 \pm 0.053$ | $50.033 \pm 1.986$ | $13.947 \pm 0.071$ | $108.700 \pm 2.718$ | 3/3 (100%) |
| **D1** | $F$ | 3 | Path_B | $0.0 \pm 0.0$ | $7.536 \pm 0.005$ | $48.200 \pm 0.954$ | $14.027 \pm 0.252$ | $109.500 \pm 1.572$ | 3/3 (100%) |
| **D2** | $R$ | 3 | Path_A | $0.0 \pm 0.0$ | $5.915 \pm 0.038$ | $49.567 \pm 1.595$ | $16.344 \pm 0.031$ | $148.167 \pm 3.156$ | 3/3 (100%) |
| **D2** | $O$ | 3 | Path_A | $0.0 \pm 0.0$ | $5.939 \pm 0.070$ | $52.033 \pm 1.747$ | $16.396 \pm 0.237$ | $149.767 \pm 0.551$ | 3/3 (100%) |
| **D2** | $F$ | 3 | Path_A | $0.0 \pm 0.0$ | $5.886 \pm 0.021$ | $51.100 \pm 0.954$ | $16.247 \pm 0.103$ | $151.100 \pm 7.763$ | 3/3 (100%) |
| **D2** | $M1$ | 3 | Path_B | $0.0 \pm 0.0$ | $7.895 \pm 0.023$ | $51.300 \pm 2.000$ | $18.248 \pm 0.089$ | $148.833 \pm 2.401$ | 3/3 (100%) |

### 5.2 Key Contrasts & Analysis

Table 2 presents pairwise contrast comparisons across methods.

| Scenario | Comparison | Metric | Method A Mean | Method B Mean | Abs Diff ($A - B$) | Rel Diff (%) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **D1** | $F$ vs. $R$ | Total Distance (m) | $14.027$ | $17.220$ | $-3.193$ | **$-18.5\%$** |
| **D1** | $F$ vs. $R$ | Total Time (s) | $109.500$ | $141.000$ | $-31.500$ | **$-22.3\%$** |
| **D1** | $O$ vs. $R$ | Total Distance (m) | $13.947$ | $17.220$ | $-3.273$ | **$-19.0\%$** |
| **D1** | $O$ vs. $R$ | Total Time (s) | $108.700$ | $141.000$ | $-32.300$ | **$-22.9\%$** |
| **D1** | $F$ vs. $O$ | Total Distance (m) | $14.027$ | $13.947$ | $+0.080$ | **$+0.6\%$** |
| **D1** | $F$ vs. $O$ | Total Time (s) | $109.500$ | $108.700$ | $+0.800$ | **$+0.7\%$** |
| **D2** | $F$ vs. $M1$ | Total Distance (m) | $16.247$ | $18.248$ | $-2.001$ | **$-11.0\%$** |
| **D2** | $F$ vs. $M1$ | Total Time (s) | $151.100$ | $148.833$ | $+2.267$ | **$+1.5\%$** |
| **D2** | $F$ vs. $O$ | Total Distance (m) | $16.247$ | $16.396$ | $-0.149$ | **$-0.9\%$** |
| **D2** | $F$ vs. $O$ | Total Time (s) | $151.100$ | $149.767$ | $+1.333$ | **$+0.9\%$** |

1. **Elimination of Dead-End Retries**: In D1, FailMem ($F$) eliminates redundant entry into the blocked corridor ($0.0$ vs. $1.0$ dead ends), reducing total distance by $-18.5\%$ and time by $-22.3\%$ relative to Reactive $R$.
2. **Prevention of Detour Overhead**: In D2, dynamic invalidation upon observing `FREE` unsuppresses Path A, saving $-11.0\%$ distance relative to persistent suppression memory ($M1$).
3. **Exploratory Parity Boundary**: In both D1 and D2, FailMem ($F$) and Spatial Cache ($O$) yield identical topological routes with $<1\%$ difference. The empirical data does not demonstrate an advantage of failure semantics over spatial caching under static 2D geometry.

### 5.3 Hypothesis H1 Feasibility Check ($n=4$)
To test whether action configurations (aligned $a_{\text{aligned}}$ vs. boundary-biased oblique $a_{\text{oblique}}$) create executability differences in an unobstructed doorway, a fixed 4-run feasibility check was executed.
All 4 runs received `SUCCEEDED` from Nav2 (status code 4), with 3/4 verifying strict physical arrival ($H1\_aligned\_run1$ failed angular velocity halt threshold). Because Nav2 successfully negotiated the doorway inflation boundary without planner abortion in both oblique runs, the expected executability divergence failed to manifest. As pre-registered, further comparative trials on $H_1$ were halted.

---

## 6. Threats to Validity & Limitations

1. **Exploratory Sample Size**: The primary benchmark is an exploratory repetition pilot ($n=3$ per condition) and does not constitute full large-sample hypothesis validation.
2. **Simulation Fidelity**: Evaluated in Gazebo 11 simulation with nominal sensor models. Physical hardware validation in noisy or dynamically changing real-world environments is planned for future work.
3. **Conceptual Action-Conditioned Extensions**: Architectural designs for action-profiled failure memory ($F2$) and backoff spatial baselines ($O+$) are formalized as conceptual models but remain unexecuted in simulation.

---

## 7. Conclusion

This paper presents FailMem, an auditable, event-driven failure memory architecture for autonomous mobile robot navigation. By grounding failures in immutable raw observation bundles and providing an independent cryptographic replay verification pipeline, FailMem establishes rigorous standards for reproducible robotics evaluation. Our empirical findings delineate clear operational boundaries: failure memory eliminates redundant dead-end exploration relative to reactive baselines and prevents permanent detour traps upon environmental recovery, but achieves functional parity with spatial caching in static 2D geometry. These results provide an empirically grounded baseline for future research in action-conditioned and multi-agent failure memory systems.

---

## References

\bibliographystyle{IEEEtran}
\bibliography{references}
