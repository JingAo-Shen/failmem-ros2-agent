---
title: "Auditable Failure Memory for ROS 2 Navigation: An Exploratory Comparison with Spatial Caching"
author: "Anonymous Authors"
---

## Abstract

**Problem**: Autonomous mobile robots navigating structured indoor environments frequently encounter physical chokepoint blockages. Standard navigation architectures (e.g., ROS 2 Nav2) employ reactive intra-action recovery routines but discard execution outcomes upon goal termination, leading to repetitive, unguided traversals into known dead ends across subsequent tasks.  
**Implementation**: We present **FailMem**, an event-driven failure memory architecture integrated with ROS 2 Nav2. FailMem binds navigation aborts to immutable observation bundles (raw LiDAR scans, TF transforms, and 2D costmap regions of interest) and introduces perception-driven dynamic invalidation that unsuppresses routes upon sensor-verified clearance.  
**Experiment**: In physical Gazebo 11 simulations with a TurtleBot3 robot, we evaluate FailMem across 30 runs ($n=3$ per condition under sequential fixed-seed execution) against reactive ($R$), spatial observation caching ($O$), and persistent suppression ($M1$) baselines in an asymmetric dual-path environment, alongside an exploratory 4-run feasibility check on action-conditioned navigation ($H_1$).  
**Key Results**: In obstructed environments (Scenario D1), historical information eliminates redundant dead-end exploration ($0.0$ vs. $1.0$ traversals), saving $-18.5\%$ travel distance ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) and $-22.3\%$ execution time ($109.5\,\text{s}$ vs. $141.0\,\text{s}$) relative to reactive retry ($R$). Upon blockage removal (Scenario D2), dynamic invalidation saves $-11.0\%$ distance relative to permanent suppression ($M1$) ($16.25\,\text{m}$ vs. $18.25\,\text{m}$), though total execution times remain comparable ($151.1\,\text{s}$ vs. $148.8\,\text{s}$) due to clearance observation maneuvers. Under static 2D geometry, FailMem and spatial caching ($O$) chose identical topological routes with $<1\%$ differences in reported distance and time ($14.03\,\text{m}$ vs. $13.95\,\text{m}$ in D1; $16.25\,\text{m}$ vs. $16.40\,\text{m}$ in D2).  
**Limitations**: In this exploratory benchmark, route choices were identical and showed no additional benefit of explicit failure memory over spatial caching; statistical equivalence across general domains has not been proven. Furthermore, candidate action configurations in $H_1$ did not establish executability divergence (4/4 Nav2 success), demonstrating the boundaries of controller robustness and informing future action-profiled memory designs.

---

## 1. Introduction

Autonomous mobile robots operating in structured indoor facilities—such as warehouses, hospitals, and office corridors—must repeatedly navigate shared corridors and doorways. In dynamic environments, unmapped physical blockages (such as parked delivery carts or closed safety doors) frequently obstruct the nominal shortest path. Standard navigation systems, including the ROS 2 Navigation Stack (Nav2) \cite{macenski2020marathon2, macenski2022ros2}, utilize layered 2D costmaps \cite{lu2014layered} and local recovery behaviors (e.g., in-place rotations, backup maneuvers, costmap clearing). While these recovery routines assist during active trajectory tracking, their diagnostic state is discarded upon goal termination. Consequently, when a new navigation task is dispatched from a distant junction, the robot lacks structured cross-phase memory of recent failures, leading to unguided retry traversals into known dead ends before on-board sensors re-acquire line-of-sight.

To mitigate unguided re-exploration, two primary approaches exist:
1. **Spatial Costmap Caching ($O$)**: Maintaining geometric occupancy in persistent global grids (e.g., Costmap2D \cite{lu2014layered}, OctoMap \cite{hornung2013octomap}, Voxblox \cite{oleynikova2017voxblox}) as sensory observations accumulate.
2. **Episodic Failure Memory ($F$)**: Recording explicit execution aborts, error causes, or symbolic constraints to suppress infeasible route options in high-level dispatching.

While embodied AI frameworks explore language-based reflection (e.g., Reflexion \cite{shinn2023reflexion}, REFLECT \cite{liu2023reflect}), they operate primarily in semantic prompt spaces and lack physical costmap expiration semantics. Conversely, robotics systems rarely formalize verifiable contracts for when episodic failure records should be dynamically invalidated by physical perception. This raises an essential empirical question: *Under what conditions does an autonomous mobile robot genuinely require explicit episodic failure memory over standard spatial costmap caching?*

In this work, we present **FailMem**, an event-driven failure memory architecture for ROS 2 Nav2, and conduct an exploratory empirical study to delineate its operational boundaries. Specifically, we provide:
1. **Event-Driven Failure Memory Architecture**: A ROS 2 Nav2 action-client implementation that binds execution aborts to immutable observation bundles (raw LiDAR scans, TF transforms, costmap ROIs) and provides sensor-driven dynamic invalidation upon verified clearance.
2. **Reproducible Evaluation Benchmark**: An exploratory 30-run benchmark ($n=3$ per condition under sequential fixed seeds) in Gazebo 11 comparing FailMem ($F$) against reactive ($R$), spatial caching ($O$), and persistent suppression ($M1$) baselines across clean (D0), blocked (D1), and restored (D2) scenarios.
3. **Empirical Boundary Analysis**: We demonstrate that while failure memory eliminates dead ends ($-18.5\%$ distance vs. $R$) and dynamic invalidation prevents permanent detour traps ($-11.0\%$ distance vs. $M1$), FailMem and spatial caching ($O$) chose identical topological routes with $<1\%$ cost differences in static 2D geometry. Furthermore, an exploratory 4-run feasibility trial on action-conditioned navigation ($H_1$) reveals that standard local controllers negotiated narrow doorpost inflation margins without abortion, establishing empirical stopping criteria for future action-profiled memory research.

---

## 2. Related Work & Mechanism Taxonomy

### 2.1 Spatial Occupancy Mapping & Distance Fields
Layered 2D costmaps \cite{lu2014layered, macenski2020marathon2} maintain geometric obstacles by ray-casting sensor ranges into grid cells and propagating configuration-space inflation. 3D volumetric frameworks, such as OctoMap \cite{hornung2013octomap}, employ hierarchical octrees with discrete probabilistic voxel occupancy updates. Distance-field frameworks such as Voxblox \cite{oleynikova2017voxblox} incrementally construct continuous Euclidean Signed Distance Fields (ESDF) for smooth trajectory optimization. While spatial mapping accurately maintains geometric free and occupied space, it treats unobserved areas identically and does not capture action-specific execution failures.

### 2.2 Execution Monitoring & Plan Diagnosis
Deliberative robotics frameworks \cite{fikes1971strips, simmons1998xavier, ingrand2017deliberation} formalize plan execution monitoring and diagnostic repair. Modern navigation stacks \cite{macenski2020marathon2} execute recovery behaviors when local planners fail. However, standard recovery states are discarded upon goal termination, requiring explicit cross-phase or cross-task episodic memory stores to guide high-level routing.

### 2.3 LLM Self-Reflection & Agent Memory
Recent embodied AI systems investigate large language models for planning and error correction. Reflexion \cite{shinn2023reflexion} prompts LLMs with scalar task feedback to generate natural language self-reflections. Inner Monologue \cite{huang2023inner} integrates success detectors and scene descriptions into closed-loop prompt chains. REFLECT \cite{liu2023reflect} uses hierarchical multi-modal experience summarization with LLMs to generate structured failure explanations and plan corrections. While these methods demonstrate prompt-level flexibility, they focus on higher-level task reflection. FailMem complements these approaches by investigating event-driven failure recording, perception-driven invalidation, and offline replay auditing directly within the low-level ROS 2 action and costmap stack.

### 2.4 Experience-Based Planning & No-Good Learning
In motion planning, the Lightning framework \cite{berenson2012lightning} and Experience Graphs (E-Graphs) \cite{phillips2012egraphs} reuse libraries of prior successful paths to accelerate search. In discrete optimization, conflict-driven clause learning (e.g., GRASP \cite{marquessilva1999grasp}) records "no-goods" from search dead ends to prune infeasible branches. FailMem adapts the principle of negative constraint recording to mobile robot navigation with explicit sensor-verified invalidation.

```
+---------------------------------------------------------------------------------------------------+
|                                 Comparative Mechanism Taxonomy                                    |
+---------------------------------------------------------------------------------------------------+
| Paradigm               | Representation         | Grounding Level   | Invalidation Trigger        |
+------------------------+------------------------+-------------------+-----------------------------+
| Costmap2D / Nav2       | 2D Occupancy Grid      | Geometric cells   | Direct laser ray traversal  |
| OctoMap                | 3D Voxel Octree        | Discrete 3D voxels| Direct laser ray traversal  |
| Voxblox                | Continuous ESDF / TSDF | 3D Distance Field | Dynamic voxel integration   |
| Experience Graphs      | Path Waypoints / Graph | Discrete Path     | Collision check on repair   |
| Reflexion              | Natural Language Text  | Semantic tokens   | Manual context reset        |
| REFLECT                | Natural Language Text  | Multi-modal logs  | Session termination         |
| FailMem (Implemented)  | Event Tuple            | Raw sensor bundle | Sensor-verified FREE state  |
| FailMem F2 (Proposed)  | Profile Tuple          | Bundle + Profile  | Profile capability check    |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. The FailMem Architecture

![FailMem Architecture and Verification Pipeline](figures/architecture.svg)

Figure 1 illustrates the overall system architecture, encompassing the execution runtime, immutable observation bundles, and memory lifecycle.

### 3.1 Immutable Observation Bundles
Prior to evaluating passage clearance, FailMem constructs an immutable observation bundle $B$:
$$B = \langle \text{obs\_id}, \mathbf{z}_{\text{scan}}, \mathbf{T}_{\text{map}\to\text{base}}, \mathbf{M}_{\text{costmap\_ROI}}, t_{\text{msg}}, t_{\text{capture}}, t_{\text{eval}} \rangle$$
where $\mathbf{z}_{\text{scan}}$ is the raw range array, $\mathbf{T}_{\text{map}\to\text{base}}$ is the TF transformation, and $\mathbf{M}_{\text{costmap\_ROI}}$ is the extracted 2D subgrid matrix.

### 3.2 Clearance Classification Rules
The passage state is evaluated according to strict geometric criteria implemented in `src/doorway_evaluator.py`:
$$\text{State}(B) = \begin{cases} 
\text{OCCUPIED}, & \text{if } N_{\text{hits\_inside}} \ge 5 \text{ or } N_{\text{costmap\_occupied\_cells}} > 0 \\ 
\text{FREE}, & \text{if } N_{\text{hits\_inside}} = 0 \text{ and } N_{\text{pass\_through}} \ge 8 \text{ and } \text{CostmapCleared}(B) \\ 
\text{UNKNOWN}, & \text{otherwise} 
\end{cases}$$
where $\text{CostmapCleared}(B) \iff (N_{\text{unknown\_cells}} = 0 \land N_{\text{occupied\_cells}} = 0)$ within the doorway ROI $[-0.15, 0.15, 0.95, 1.45]$. (See Supplementary Material S1 for detailed transform alignment and ray projection preconditions).

### 3.3 Memory Lifecycle & Invalidation Mechanics
- **Failure Registration**: When navigation fails within an occupied passage, an active failure record is created:
  $$M = \langle \text{mem\_id}, t_{\text{fail}}, \text{goal\_uuid}, \text{action\_id}, \text{region\_id}, \mathbf{M}_{\text{costmap\_ROI}} \rangle$$
  Active failure records suppress the associated route at Decision Junction $J_0$.
- **Dynamic Invalidation**: When subsequent sensor perception yields $\text{State}(B) = \text{FREE}$ with evidence timestamp $t_{\text{free}} > t_{\text{fail}}$, the memory entry is marked $\text{INVALIDATED}$, unsuppressing the route.
- **Evaluation Pipeline**: An independent cryptographic replay auditor verifies all serialized logs against SHA256 checksum manifests and physical halt stability criteria ($|v_{\text{lin}}| \le 0.05\,\text{m/s}, |v_{\text{ang}}| \le 0.08\,\text{rad/s}$) without reliance on runtime assertions (detailed in Supplementary Material S2).

---

## 4. Experimental Setup & Benchmarking Protocol

### 4.1 Physical Simulation Environment & Geometry
Simulations are conducted in ROS 2 Humble with Gazebo 11 simulating a TurtleBot3 Waffle robot in an asymmetric dual-path environment (`configs/p2c_dualpath_world.model`).
- **Path A (North Short Path)**: Waypoint polyline length is $6.124\,\text{m}$ from Decision Junction $J_0 [-2.50, 0.00]$ to Goal $[2.50, 0.00]$ through a $0.80\,\text{m}$ doorway chokepoint at $y=1.20$.
- **Path B (South Bypass Detour)**: Waypoint polyline length is $9.105\,\text{m}$ from $J_0$ to Goal via open corridor at $y=-2.40$.

### 4.2 Distance Metric Definitions
To evaluate performance across different phases, we define:
1. **Decision Distance ($d_{\text{dec}}$)**: Physical odometry distance traversed during Phase 2 after goal dispatch from Decision Junction $J_0$ (Path B direct: $\approx 7.54\,\text{m}$; Path A direct: $\approx 5.89\,\text{m}$).
2. **Total Distance ($d_{\text{tot}}$)**: Cumulative odometry distance spanning both Phase 1 (historical observation/attempt) and Phase 2 (dispatch to goal).

### 4.3 Evaluated Scenarios & Baseline Methods
- **Scenario D0 (Unobstructed)**: Doorway is clear; robot navigates Path A without prior history.
- **Scenario D1 (Blocked)**: Doorway is blocked by an obstacle. Phase 1 approaches gate waypoint $[-1.50, 1.20]$, detects blockage, and retreats to $J_0$. Phase 2 evaluates routing from $J_0$.
- **Scenario D2 (Cleared)**: Following D1, the obstacle is removed. Phase 1 observes `FREE` doorway clearance from vantage waypoint $[-1.50, 1.20]$ and retreats to $J_0$. Phase 2 evaluates routing from $J_0$.

**Evaluated Methods**:
1. **Reactive Baseline ($R$)**: No cross-phase memory. In D1, enters Path A approach leg, detects blockage at $[-1.50, 1.20]$, and retreats to $J_0$ before taking Path B.
2. **Spatial Observation Cache ($O$)**: Caches 2D geometric occupancy observed from vantage point $[-1.50, 1.20]$ during Phase 1. Evaluated at $J_0$ during Phase 2.
3. **FailMem ($F$)**: Event-driven failure memory with dynamic perception-driven invalidation.
4. **Persistent Suppression ($M1$)**: Static failure memory permanently suppressing Path A without dynamic invalidation.

All runs use $n=3$ per condition under sequential fixed seeds with an episode budget of $180.0\,\text{s}$.

---

## 5. Empirical Results & Boundary Analysis

### 5.1 Condition-Level Performance
Table 1 presents condition-level performance across 30 physical simulation runs ($n=3$ per condition, reporting mean $\pm$ sample standard deviation with Bessel correction $ddof=1$). All 10 conditions achieved a $100\%$ replay audit pass rate ($3/3$), confirming physical halt stability and data completeness across all runs.

<!-- TABLE:table1_condition_summary -->

### 5.2 Pairwise Contrasts & Trajectory Analysis
Table 2 reports pairwise contrast comparisons across evaluated methods, and Figure 2 illustrates representative physical trajectories.

<!-- TABLE:table2_pairwise_contrasts -->

![Representative Physical Trajectories Across Evaluated Conditions](figures/trajectories_map.png)

1. **Elimination of Redundant Dead-End Exploration ($F$ vs. $R$)**: In Scenario D1, FailMem ($F$) eliminates redundant entry into the blocked corridor ($0.0$ vs. $1.0$ dead ends), reducing total distance by $-18.5\%$ ($14.03\,\text{m}$ vs. $17.22\,\text{m}$) and execution time by $-22.3\%$ ($109.5\,\text{s}$ vs. $141.0\,\text{s}$) relative to Reactive $R$ (Table 2, Figure 2). Reactive $R$'s dead-end traversal represents an unguided retry to the entrance waypoint, not physical collision.
2. **Prevention of Detour Overhead ($F$ vs. $M1$)**: In Scenario D2, dynamic invalidation upon observing `FREE` unsuppresses Path A, saving $2.00\,\text{m}$ ($-11.0\%$) total distance relative to persistent suppression ($M1$) ($16.25\,\text{m}$ vs. $18.25\,\text{m}$). However, total execution time is comparable ($151.1\,\text{s}$ vs. $148.8\,\text{s}$, $+1.5\%$), as the physical vantage observation leg in Phase 1 consumes wall-clock simulation time.
3. **Comparison with Spatial Caching in Static 2D Geometry ($F$ vs. $O$)**: In both D1 and D2, FailMem ($F$) and Spatial Cache ($O$) selected identical topological routes. Total distance differences ($+0.6\%$ in D1, $-0.9\%$ in D2) and total duration differences ($+0.7\%$ in D1, $+0.9\%$ in D2) remained under $1\%$. *In this exploratory dataset, route choices were identical and showed no additional benefit of $F$ over $O$; general scenarios and statistical equivalence have not been verified.*

### 5.3 Feasibility Check for Action-Conditioned Navigation ($H_1$)
To investigate whether action configurations (aligned $a_{\text{aligned}}$ vs. doorpost boundary-biased oblique $a_{\text{oblique}}$) create executability differences in an unobstructed doorway, a fixed 4-run feasibility check was conducted (`reports/evidence/p2d_h1_feasibility/`).

<!-- TABLE:table3_h1_feasibility -->

Table 3 summarizes the feasibility trial outcomes. Nav2 returned `SUCCEEDED` (status code 4) in all 4/4 runs, and strict physical arrival was verified in 3/4 runs (`H1_aligned_run1` exceeded the angular velocity halt threshold during the stability window: $0.1068 > 0.08\,\text{rad/s}$). Crucially, Nav2's `DWBLocalPlanner` successfully negotiated the doorpost inflation boundary without planner abortion in both oblique runs.  
**Decision & Conclusion**: *本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。*

---

## 6. Threats to Validity & Limitations

1. **Exploratory Sample Size**: The 30-run comparative pilot ($n=3$ per condition) serves as an exploratory demonstration of mechanism functioning and auditability; it does not constitute large-sample asymptotic hypothesis testing.
2. **Simulation Fidelity**: Evaluated in Gazebo 11 simulation with nominal sensor models. Hardware deployments with real-world sensor dropout, dynamic obstacles, and adversarial conditions are subject to future research.
3. **Conceptual Extensions ($F2, O+$)**: Action-profiled failure memory ($F2$) and backoff spatial caching ($O+$) are formalized as conceptual models in project documentation but have not yet been evaluated in simulation.

---

## 7. Conclusion

This paper presented FailMem, an event-driven failure memory architecture for autonomous mobile robots. By binding execution failures to immutable observation bundles and providing an independent replay audit pipeline, FailMem establishes rigorous standards for reproducible robotics evaluation. Our empirical findings demonstrate that failure memory eliminates redundant dead-end exploration relative to reactive baselines and prevents permanent detour traps upon environmental recovery, while exhibiting identical route selection with spatial caching under the tested static 2D geometry. These findings define concrete experimental benchmarks and provide a solid foundation for future research in action-conditioned and multi-agent failure memory systems.

---

## References

\bibliographystyle{IEEEtran}
\bibliography{references}

