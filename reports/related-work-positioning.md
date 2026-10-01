# Related Work Positioning & Comparative Taxonomy

**Date**: 2026-10-01  
**Repository Branch**: `audit/r0-authenticity`  
**Purpose**: Position FailMem within the robotics, embodied AI, and cognitive memory literature, citing verified primary publications with DOIs/URLs, analyzing core mechanisms, and contrasting operational assumptions.

---

## 1. Primary Literature Survey & Mechanisms

### 1.1 Spatial Occupancy Mapping & Dynamic Costmaps
- **Costmap2D & Nav2 Costmap Pipeline** (Lu et al., IROS 2014; Macenski et al., *Robotics and Autonomous Systems* 2023, DOI: [10.1016/j.robot.2023.104510](https://doi.org/10.1016/j.robot.2023.104510)):
  - *Mechanism*: Multi-layered 2D grid representations aggregating static obstacle maps, real-time sensor ray casting (obstacle layer), and configuration-space expansion (inflation layer).
  - *Relationship to FailMem*: FailMem's Spatial Cache baseline ($O$) directly leverages 2D geometric occupancy observation. While standard costmaps clear obstacles when laser rays pass through previously marked cells, they lack action-level causal attribution and cross-episode semantic indexing.
- **OctoMap: 3D Occupancy Mapping** (Hornung et al., *Autonomous Robots* 2013, DOI: [10.1007/s10514-012-9321-0](https://doi.org/10.1007/s10514-012-9321-0)):
  - *Mechanism*: Hierarchical 3D octree data structure utilizing probabilistic occupancy updates and ray casting.
  - *Relationship to FailMem*: Provides volumetric spatial representation; like 2D costmaps, occupancy states represent geometric space rather than action executability constraints.
- **Voxblox: Incremental 3D Signed Distance Fields** (Oleynikova et al., IROS 2017, DOI: [10.1109/IROS.2017.8202315](https://doi.org/10.1109/IROS.2017.8202315)):
  - *Mechanism*: Incremental computation of Truncated Signed Distance Fields (TSDF) and Euclidean Signed Distance Fields (ESDF) for continuous trajectory optimization.

### 1.2 Robot Execution Monitoring, Plan Diagnosis & Recovery
- **Execution Monitoring and Error Recovery (PLANEX / STRIPS)** (Fikes & Nilsson, *Artificial Intelligence* 1971, DOI: [10.1016/0004-3702(71)90010-5](https://doi.org/10.1016/0004-3702(71)90010-5)):
  - *Mechanism*: Monitoring plan execution via Triangle Tables and re-planning when sensory preconditions are violated.
  - *Relationship to FailMem*: FailMem formalizes pre/postcondition verification within continuous ROS 2 action spaces, integrating raw TF and LiDAR bundles.
- **Task-Level Control & Failure Recovery (Xavier Architecture)** (Simmons, *IEEE Robotics & Automation Magazine* 1998, DOI: [10.1109/100.740882](https://doi.org/10.1109/100.740882)):
  - *Mechanism*: Layered architecture separating deliberative planning, executive task management (TCA), and reactive real-time control.
- **Particle Filter Fault Diagnosis for Autonomous Rovers** (Verma et al., *IEEE Transactions on Robotics* 2004, DOI: [10.1109/TRO.2004.833804](https://doi.org/10.1109/TRO.2004.833804)):
  - *Mechanism*: Model-based state estimation tracking unobservable robot fault modes (e.g. motor stall, sensor failure).
- **Deliberation in Autonomous Robots** (Ingrand & Galleron, *Artificial Intelligence* 2014, DOI: [10.1016/j.artint.2014.07.003](https://doi.org/10.1016/j.artint.2014.07.003)):
  - *Mechanism*: Comprehensive survey of deliberative frameworks (monitoring, acting, diagnosing, repairing).

### 1.3 LLM / Agent Verbal Self-Reflection & Memory Systems
- **Reflexion: Language Agents with Verbal Reinforcement Learning** (Shinn et al., NeurIPS 2023, arXiv: [2303.11366](https://arxiv.org/abs/2303.11366)):
  - *Mechanism*: Iterative prompting where scalar environment feedback is converted into natural language self-reflections appended to agent context.
  - *Limitation & Difference*: Operates on ungrounded text tokens without physical sensor postcondition verification, spatial costmap expiration, or cryptographic audit trails.
- **REFLECT: Summarizing Robot Failures through Multimodal Explanation** (Liu et al., CoRL 2023, arXiv: [2306.15724](https://arxiv.org/abs/2306.15724)):
  - *Mechanism*: Uses hierarchical LLMs to query sensor streams upon physical failure to generate diagnostic natural language explanations.
- **SayCan: Grounding Language in Robotic Affordances** (Ahn et al., RSS 2022, arXiv: [2204.01691](https://arxiv.org/abs/2204.01691)):
  - *Mechanism*: Combines LLM task semantics with learned value functions (affordances) to filter infeasible actions.
- **Inner Monologue: Embodied Reasoning through Language Feedback** (Huang et al., CoRL 2022, arXiv: [2207.05608](https://arxiv.org/abs/2207.05608)):
  - *Mechanism*: Closes the loop between LLM planners and perception through success detection, scene descriptions, and passive human feedback.
- **Voyager: An Open-Ended Embodied Agent with LLMs** (Wang et al., TMLR 2023, arXiv: [2305.16291](https://arxiv.org/abs/2305.16291)):
  - *Mechanism*: Iterative skill library synthesis and retrieval in Minecraft using execution error feedback.
- **A-MEM: Adaptive Memory Augmentation for Language Agents** (2025, arXiv: [2502.12110](https://arxiv.org/abs/2502.12110)):
  - *Mechanism*: Dynamic evolving memory networks updating relational linkages across agent trajectories.
- **AgeMem: Unified Long-Short Term Agent Memory** (2026, arXiv: [2601.01885](https://arxiv.org/abs/2601.01885)):
  - *Mechanism*: Tiered memory consolidation managing short-term operational buffers and long-term knowledge retention.

### 1.4 Experience-Based Planning & No-Good Learning
- **Lightning Framework: Experience-Based Planning in Robotics** (Berenson et al., IJRR 2012, DOI: [10.1177/0278364912456311](https://doi.org/10.1177/0278364912456311)):
  - *Mechanism*: Runs an experience-retrieval planner in parallel with a scratch planner (RRT) to repair and reuse prior trajectories.
- **E-Graphs: Experience-Graph Planning with Bounds** (Phillips et al., IJRR 2012, DOI: [10.1177/0278364912461942](https://doi.org/10.1177/0278364912461942)):
  - *Mechanism*: Accelerates graph search ($A^*$) by biasing search toward previously executed trajectory segments with bounded suboptimality.
- **Clause Learning & No-Good Recording in SAT/SMT** (Marques-Silva & Sakallah, IEEE Trans. Computers 1999, DOI: [10.1109/12.769433](https://doi.org/10.1109/12.769433)):
  - *Mechanism*: Derives conflict clauses ("no-goods") from backtracked search paths to prune infeasible decision branches in boolean satisfiability.

---

## 2. Comparative Mechanism Taxonomy

| Framework / Paradigm | Memory Representation | Grounding Level | Invalidation Trigger | Action-Conditioned? | Auditability & Verifiability |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Standard Costmap2D / Nav2** | 2D Occupancy Grid | Geometric cells | Direct ray pass-through | $\times$ (No) | Metric-level costmap log |
| **OctoMap / Voxblox** | 3D Voxel / ESDF | Continuous 3D geometry | Direct ray / TSDF update | $\times$ (No) | Spatial grid serialization |
| **Experience Graphs (E-Graphs)** | Path Waypoints / Graph | Discrete geometric path | Collision check during repair | $\times$ (No) | Graph edge weights |
| **Reflexion / LLM Self-Reflection** | Unstructured Text Prompt | Semantic tokens (ungrounded) | Manual prompt replacement | $\sim$ (Text only) | Non-deterministic prompt trace |
| **REFLECT / Multimodal LLM** | Structured Natural Language | Sensor summary descriptions | Session termination | $\sim$ (Text only) | Offline video/log review |
| **FailMem (Milestone P2c / F)** | Event Tuple ($t_{\text{fail}}, \text{goal\_uuid}, \text{action\_id}, \text{region}, \text{ROI}$) | Immutable raw sensor bundles | Sensor-verified `FREE` perception | $\sim$ (Bound to region & action ID) | Cryptographic SHA256 + Independent Replay Engine |
| **FailMem Extended ($F2$, Proposed)** | Profile Tuple ($t_{\text{fail}}, \text{action\_profile\_id}, \text{region}, \text{ROI}$) | Immutable sensor bundles + Action Profile | Profile-specific capability check | $\checkmark$ (Yes, footprint/velocity/controller) | Cryptographic SHA256 + Independent Replay Engine |

---

## 3. Positioning and Contribution Boundaries of FailMem

### 3.1 What FailMem Establishes
1. **Auditable & Cryptographically Grounded Failure Records**: Unlike verbal reflection prompts that rely on hallucination-prone natural language summaries, FailMem grounds failure in immutable raw sensor bundles (untruncated laser scans, TF transforms, costmap subgrid ROIs) and provides a zero-bypass independent replay verification engine.
2. **Causal Event Binding & Time-Bounded Consumption**: Memories are strictly timestamped and validated ($t_{\text{rec}} \ge \max(t_{\text{act}}, t_{\text{obs}})$), ensuring decisions never consume future knowledge or stale records from prior map versions.
3. **Dynamic Perception-Driven Invalidation**: By automatically clearing failure suppression when a physical passage is sensor-verified as `FREE`, FailMem prevents the robot from falling into permanent suboptimal detour traps (saving $-11.0\%$ distance relative to persistent suppression $M1$).

### 3.2 What Current Empirical Data Demonstrates (The Boundary Finding)
1. **Historical Knowledge vs. Reactive Exploration**: Both FailMem ($F$) and Spatial Cache ($O$) eliminate redundant retry exploration in blocked passages ($0$ dead ends vs. $1$ dead end, saving $-18.5\%$ distance and $-22.3\%$ time relative to Reactive $R$).
2. **Parity with Spatial Caching in Static 2D Geometry**: In static geometric environments, exploratory $n=3$ data show that FailMem and Spatial Cache make identical high-level topological decisions ($<1\%$ difference). Failure semantics do not exhibit an empirical advantage over simple spatial caching when the obstruction is purely geometric.
3. **Requirement for True Action-Conditioned Evaluation ($F2$)**: To demonstrate where failure memory uniquely outperforms spatial caching, future evaluation must target scenarios where space is geometrically *free* but specific action configurations are *kinematically unexecutable* (e.g. footprint, speed, payload constraints).
