# Related Work Positioning & Comparative Taxonomy

**Date**: 2026-10-01  
**Repository Branch**: `audit/r0-authenticity`  
**Purpose**: Position FailMem within the mobile robotics, embodied AI, and cognitive memory literature using verified primary publications, analyzing core mechanisms, and contrasting operational assumptions.

---

## 1. Primary Literature Survey & Mechanics

### 1.1 Spatial Occupancy Mapping & Dynamic Distance Fields
- **Costmap2D & Nav2 Layered Costmap Pipeline** (Lu et al., IROS 2014, DOI: [10.1109/IROS.2014.6942636](https://doi.org/10.1109/IROS.2014.6942636); Macenski et al., IROS 2020, DOI: [10.1109/IROS45743.2020.9341207](https://doi.org/10.1109/IROS45743.2020.9341207); Macenski et al., *Science Robotics* 2022, DOI: [10.1126/scirobotics.add6975](https://doi.org/10.1126/scirobotics.add6975)):
  - *Mechanism*: Multi-layered 2D grid representations aggregating static obstacle maps, real-time sensor ray casting (obstacle layer), and configuration-space expansion (inflation layer).
  - *Relationship to FailMem*: FailMem's Spatial Cache baseline ($O$) directly leverages 2D geometric occupancy observation. While standard costmaps clear obstacles when laser rays pass through previously marked cells, they lack action-level causal attribution and cross-episode semantic indexing.
- **OctoMap: 3D Occupancy Mapping** (Hornung et al., *Autonomous Robots* 2013, DOI: [10.1007/s10514-012-9321-0](https://doi.org/10.1007/s10514-012-9321-0)):
  - *Mechanism*: Hierarchical 3D octree data structure utilizing discrete probabilistic voxel occupancy updates via ray casting.
  - *Relationship to FailMem*: Provides volumetric spatial representation of geometric occupancy.
- **Voxblox: Incremental 3D Signed Distance Fields** (Oleynikova et al., IROS 2017, DOI: [10.1109/IROS.2017.8202315](https://doi.org/10.1109/IROS.2017.8202315)):
  - *Mechanism*: Incremental computation of Truncated Signed Distance Fields (TSDF) and continuous Euclidean Signed Distance Fields (ESDF) for continuous trajectory optimization, distinct from discrete voxel occupancy grids.

### 1.2 Robot Execution Monitoring, Plan Diagnosis & Recovery
- **Execution Monitoring and Error Recovery (PLANEX / STRIPS)** (Fikes & Nilsson, *Artificial Intelligence* 1971, DOI: [10.1016/0004-3702(71)90010-5](https://doi.org/10.1016/0004-3702(71)90010-5)):
  - *Mechanism*: Monitoring plan execution via Triangle Tables and re-planning when sensory preconditions are violated.
  - *Relationship to FailMem*: FailMem formalizes pre/postcondition verification within continuous ROS 2 action spaces, integrating raw TF and LiDAR bundles.
- **Task-Level Control & Failure Recovery (Xavier Architecture)** (Simmons et al., *IEEE Robotics & Automation Magazine* 1998, DOI: [10.1109/100.740882](https://doi.org/10.1109/100.740882)):
  - *Mechanism*: Layered architecture separating deliberative planning, executive task management (TCA), and reactive real-time control.
- **Deliberation in Autonomous Robots** (Ingrand & Ghallab, *Artificial Intelligence* 2017, DOI: [10.1016/j.artint.2014.11.003](https://doi.org/10.1016/j.artint.2014.11.003)):
  - *Mechanism*: Comprehensive survey of deliberative frameworks (monitoring, acting, diagnosing, repairing).

### 1.3 LLM / Agent Verbal Self-Reflection & Memory Systems
- **Reflexion: Language Agents with Verbal Reinforcement Learning** (Shinn et al., NeurIPS 2023, arXiv: [2303.11366](https://arxiv.org/abs/2303.11366)):
  - *Mechanism*: Iterative prompting where scalar environment feedback is converted into natural language self-reflections appended to agent context.
  - *Relationship & Difference*: Operates on ungrounded text tokens in prompt contexts without physical sensor postcondition verification, spatial costmap expiration, or cryptographic audit trails.
- **REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction** (Liu, Bahety, & Song, CoRL 2023, PMLR 229:3468–3484, [proceedings.mlr.press/v229/liu23g.html](https://proceedings.mlr.press/v229/liu23g.html)):
  - *Mechanism*: Generates failure explanations and plan corrections by querying multi-sensory video and audio streams using hierarchical LLMs.
  - *Relationship & Difference*: REFLECT focuses on diagnostic summarization and corrective prompting across human-robot interaction sessions, whereas FailMem focuses on lightweight, causally bound execution records with deterministic sensor-driven invalidation rules.
- **SayCan: Grounding Language in Robotic Affordances** (Ahn et al., RSS 2022, DOI: [10.15607/RSS.2022.XVIII.021](https://doi.org/10.15607/RSS.2022.XVIII.021)):
  - *Mechanism*: Combines LLM task semantics with learned value functions (affordances) to filter infeasible actions.
- **Inner Monologue: Embodied Reasoning through Planning with Language Models** (Huang et al., CoRL 2022, PMLR 205:1769–1782, [proceedings.mlr.press/v205/huang23c.html](https://proceedings.mlr.press/v205/huang23c.html)):
  - *Mechanism*: Closes the loop between LLM planners and environment feedback through success detection, scene descriptions, and passive human feedback.

### 1.4 Experience-Based Planning & No-Good Learning
- **Lightning Framework: Experience-Based Planning in Robotics** (Berenson, Srinivasa, & Kuffner, IJRR 2012, DOI: [10.1177/0278364912456311](https://doi.org/10.1177/0278364912456311)):
  - *Mechanism*: Runs an experience-retrieval planner in parallel with a scratch planner (RRT) to repair and reuse prior trajectories.
- **E-Graphs: Experience-Graph Planning with Bounds** (Phillips et al., IJRR 2012, DOI: [10.1177/0278364912461942](https://doi.org/10.1177/0278364912461942)):
  - *Mechanism*: Accelerates graph search ($A^*$) by biasing search toward previously executed trajectory segments with bounded suboptimality.
- **Clause Learning & No-Good Recording in SAT/SMT** (Marques-Silva & Sakallah, IEEE Trans. Computers 1999, DOI: [10.1109/12.769433](https://doi.org/10.1109/12.769433)):
  - *Mechanism*: Derives conflict clauses ("no-goods") from backtracked search paths to prune infeasible decision branches in boolean satisfiability.

---

## 2. Comparative Mechanism Taxonomy

| Framework / Paradigm | Memory Representation | Grounding Level | Invalidation Trigger | Action-Conditioned? | Verification Mechanism |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Standard Costmap2D / Nav2** | 2D Occupancy Grid | Geometric cells | Direct ray pass-through | $\times$ (No) | Metric-level costmap log |
| **OctoMap** | 3D Voxel Octree | Discrete 3D voxel occupancy | Direct ray pass-through | $\times$ (No) | Spatial grid serialization |
| **Voxblox** | Continuous ESDF / TSDF | Continuous 3D distance field | Dynamic voxel integration | $\times$ (No) | Distance field evaluation |
| **Experience Graphs (E-Graphs)** | Path Waypoints / Graph | Discrete geometric path | Collision check during repair | $\times$ (No) | Graph edge weights |
| **Reflexion** | Natural Language Text | Ungrounded semantic tokens | Manual context reset | $\sim$ (Text prompt) | Prompt trace review |
| **REFLECT** | Structured Natural Language | Multi-modal sensor streams (video/audio) | Session termination | $\sim$ (Text prompt) | Multi-modal diagnostic log |
| **FailMem (Current Implementation)** | Event Tuple ($t_{\text{fail}}, \text{goal\_uuid}, \text{action\_id}, \text{region}, \text{ROI}$) | Immutable raw sensor bundles (scan/TF/ROI) | Sensor-verified `FREE` perception | $\sim$ (Bound to region & action ID) | SHA256 Manifest + Replay Audit |
| **FailMem Extended ($F2$, Proposed)** | Profile Tuple ($t_{\text{fail}}, \text{action\_profile\_id}, \text{region}, \text{ROI}$) | Immutable sensor bundles + Action Profile | Profile-specific capability verification | $\checkmark$ (Yes, footprint/speed/controller) | SHA256 Manifest + Replay Audit |

---

## 3. Verified Positioning of FailMem

### 3.1 Implemented Capabilities
1. **Grounded Failure Records**: Binds execution failure to immutable raw sensor observation bundles (untruncated laser scans, TF transforms, costmap subgrid ROIs).
2. **Causal Event Binding**: Memories are timestamped and validated ($t_{\text{rec}} \ge \max(t_{\text{act}}, t_{\text{obs}}) - 0.05\,\text{s}$), ensuring decisions consume only chronologically valid records from matching map versions.
3. **Dynamic Perception-Driven Invalidation**: Automatically clears failure suppression upon observing verified `FREE` passage, preventing permanent detour traps ($-11.0\%$ distance relative to persistent suppression $M1$).

### 3.2 Empirical Boundaries
1. **Comparison with Reactive Exploration ($R$)**: Historical knowledge (both $F$ and $O$) eliminates redundant retry exploration into blocked passages ($0.0$ vs. $1.0$ dead ends, reducing distance by $-18.5\%$ and time by $-22.3\%$ relative to Reactive $R$).
2. **Comparison with Spatial Cache ($O$) in Static Geometry**: In static geometric environments, exploratory $n=3$ data show that FailMem and Spatial Cache make identical high-level topological decisions ($<1\%$ difference). *本次探索性数据中路线选择相同，未显示 F 的额外收益；尚未进行统计等效或一般化验证。*
3. **Requirement for Action-Conditioned Evaluation ($F2$)**: Differentiating failure memory from spatial caching requires evaluating scenarios where space is geometrically open (`FREE`) but specific action profiles are kinematically infeasible.
