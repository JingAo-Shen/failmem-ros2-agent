# FailMem Milestone P2a: Minimal Failure Memory Mechanism Verification

**Phase**: Milestone P2a (Minimal Failure Memory Mechanism Verification)  
**Run ID**: `p2a_20260928_101002_9f61a3`  
**Protocol Version**: `1.0` (`configs/p2a_memory_protocol.yaml`, SHA256: `e74f71444b79d4d72eae7124c640a02df0d8cb0d1864fd0e20f8eb673bb7091c`)  
**Execution Environment**: ROS2 Humble / Gazebo 11 / Nav2 Stack  
**Verification Date**: 2026-09-28  

---

## 1. Executive Summary & Verification Outcomes

Milestone **P2a** formally evaluates and validates the core deterministic failure memory mechanisms of **FailMem** without reliance on Large Language Models (LLMs) or privileged oracle sensors. The objective is to empirically prove the functional necessity and sufficiency of **perception-grounded conditional failure memory** over naive reactive retries and rigid persistent memory.

Across a formal 18-episode experimental matrix ($3\text{ policies} \times 2\text{ environment sequences} \times 3\text{ runs} = 18\text{ episodes}$), **18 out of 18 episodes (100.0%) achieved mechanism verification**:

| Policy | Memory Architecture | Sequence S1 (Continuous Blockage) | Sequence S2 (Timed Clearance at $t=25$s) |
| :--- | :--- | :--- | :--- |
| **M0** (No Memory) | Zero state persistence; naive repeated dispatch | **100% Mechanism Verified**<br>Task Success: 0/3 (0%)<br>Avg Redundant Retries: **4.0/ep** | **100% Mechanism Verified**<br>Task Success: 3/3 (100%)<br>Blind repeat retry through cleared gap |
| **M1** (Persistent Memory) | Permanent failure suppression; zero invalidation | **100% Mechanism Verified**<br>Task Success: 0/3 (0%)<br>Avg Redundant Retries: **0.0/ep** | **100% Mechanism Verified**<br>Task Success: 0/3 (0%)<br>**Deadlock Confirmed** (0 retry attempts) |
| **M2** (Conditional Memory) | Dynamic lifecycle: `ACTIVE` $\to$ `INVALIDATED` $\to$ `RECOVERY_VERIFIED` | **100% Mechanism Verified**<br>Task Success: 0/3 (0%)<br>Avg Redundant Retries: **0.0/ep** | **100% Mechanism Verified**<br>Task Success: **3/3 (100%)**<br>**Perception Invalidation & Recovery** |

### Key Discoveries & Empirical Insights:
1. **Redundant Retry Elimination**: Under static continuous blockage ($S_1$), both M1 and M2 completely eliminated blind repetitive actions ($0$ redundant dispatches vs $4$ repeated collisions per episode in M0).
2. **Deadlock Elimination Under Dynamic Clearing ($S_2$)**: When the chokepoint was cleared, M1 remained permanently deadlocked ($0\%$ task success, 1 initial attempt), whereas M2 detected doorway clearance via authentic laser raytracing and local costmap subgrid evaluation, successfully invalidated its memory entry, dispatched a recovery action, and achieved **100% physical arrival success**.
3. **Zero Synthetic Intervention**: All perception, dispatch, and physical evaluation were performed autonomously using real TF tree transforms, laser scan projections, and passive physical halt stability windows without synthetic pose re-initialization or artificial costmap clearance services.

---

## 2. Failure Memory Architecture & Lifecycle State Machine

FailMem minimal memory mechanism models environment-grounded spatial constraints through structured memory entries:

$$\mathcal{M} = \{m_1, m_2, \dots, m_K\}, \quad m_k = \langle \text{id}, \mathbf{p}_{\text{target}}, \mathcal{R}, c_{\text{fail}}, t_{\text{fail}}, \sigma_k, \mathcal{I}_k, t_{\text{inv}}, \mathcal{E}_{\text{inv}} \rangle$$

Where:
- $\mathbf{p}_{\text{target}} \in \mathbb{R}^3$: Failed goal coordinates $(x, y, \theta)$.
- $\mathcal{R}$: Topological spatial region (e.g., `room2_corridor_chokepoint`).
- $c_{\text{fail}}$: Failure cause classification (`NAV2_ABORTED`, `EXECUTION_FAILED`).
- $\sigma_k \in \{\text{ACTIVE}, \text{INVALIDATED}, \text{RECOVERY\_VERIFIED}\}$: Memory lifecycle state.
- $\mathcal{I}_k$: Invalidation criteria based on 3-valued doorway perception (`doorway_state == FREE`).

```
                    +---------------------------+
                    | Navigation Action Fails   |
                    | (e.g. Corridor Blocked)   |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |       State: ACTIVE       | <----+
                    | Action Dispatch Blocked   |      | Doorway OCCUPIED / UNKNOWN
                    +-------------+-------------+      |
                                  |                    |
                                  | Doorway Perceived  |
                                  | FREE (Laser & CM)  |
                                  v                    |
                    +---------------------------+      |
                    |    State: INVALIDATED     | -----+
                    | Action Dispatch Permitted |
                    +-------------+-------------+
                                  |
                                  | Recovery Action Dispatched
                                  | & Goal Reached + Stable
                                  v
                    +---------------------------+
                    | State: RECOVERY_VERIFIED  |
                    | Final Task Success        |
                    +---------------------------+
```

### Deterministic Dispatch Gate Function
Before any navigation action $a = \langle \mathbf{p}_{\text{goal}}, \text{region} \rangle$ is sent to the ROS2 Action Server, the memory gate evaluates:

$$G(a, \mathcal{M}) = \begin{cases} 
\text{SUPPRESS} & \text{if } \exists m \in \mathcal{M} \text{ s.t. } \sigma_m = \text{ACTIVE} \land \text{Match}(\mathbf{p}_{\text{goal}}, \mathcal{R}_m) \\
\text{ALLOW} & \text{otherwise}
\end{cases}$$

---

## 3. Experimental Setup & Coordinate Grounding

### 3.1 Scenario Geometry
- **Map & World**: Two-room corridor environment (`configs/chokepoint_world.model`, SHA256: `f7aafddaf0d2a2190292959fa9f0d1efc75bcdc24d1c1bb715be569c32b45889`).
- **Spawn Pose**: $(-1.80, 0.00, 0.00)$ in Room 1.
- **Target Goal**: $(1.80, 0.00, 0.00)$ in Room 2.
- **Doorway Chokepoint Bounding Box**: $x \in [-0.30, 0.30]\text{ m}, \quad y \in [-0.35, 0.35]\text{ m}$.
- **Obstacle Entity**: `corridor_blockage_box` ($0.20 \times 0.60 \times 0.60\text{ m}$) spawned at $(0.00, 0.00, 0.30)$.

### 3.2 Coordinate Alignment Verification
6 non-collinear physical landmarks were tested against the PGM occupancy grid (`configs/chokepoint_world.yaml`). All landmarks aligned within discretization bounds (maximum residual $0.0627\text{ m} \le 0.0750\text{ m}$):
- `west_wall`: $(-3.10, 0.00) \to$ residual $0.025\text{ m}$
- `south_wall`: $(0.00, -1.60) \to$ residual $0.063\text{ m}$
- `dividing_south_wall`: $(0.00, -0.97) \to$ residual $0.032\text{ m}$
- `dividing_north_wall`: $(0.00, 0.97) \to$ residual $0.032\text{ m}$
- `north_wall`: $(0.00, 1.60) \to$ residual $0.029\text{ m}$
- `east_wall`: $(3.10, 0.00) \to$ residual $0.025\text{ m}$

---

## 4. Formal 18-Episode Benchmark Results

Below is the complete, unbroken result matrix from run `p2a_20260928_101002_9f61a3`:

| Condition | Episode ID | Task Success | Mechanism Verified | Dispatches Attempted | Redundant Retries | Invalidation Verified | Recovery Verified | Final GT Pos Error | Checksum (episode_summary.json) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **M0_S1** | `M0_S1_ep1` | False | **True** | 5 | 4 | False | False | $3.600\text{ m}$ | `95cf1edc3c1b...` |
| **M0_S1** | `M0_S1_ep2` | False | **True** | 5 | 4 | False | False | $3.595\text{ m}$ | `24fa3290644b...` |
| **M0_S1** | `M0_S1_ep3` | False | **True** | 5 | 4 | False | False | $3.585\text{ m}$ | `b9c17a9c22a6...` |
| **M0_S2** | `M0_S2_ep1` | **True** | **True** | 2 | 0 | False | False | $0.193\text{ m}$ | `b05b30bd759d...` |
| **M0_S2** | `M0_S2_ep2` | **True** | **True** | 2 | 0 | False | False | $0.185\text{ m}$ | `fd47237dd896...` |
| **M0_S2** | `M0_S2_ep3` | **True** | **True** | 2 | 1 | False | False | $0.227\text{ m}$ | `56ced1983543...` |
| **M1_S1** | `M1_S1_ep1` | False | **True** | 1 | 0 | False | False | $3.598\text{ m}$ | `8241ce9b37e1...` |
| **M1_S1** | `M1_S1_ep2` | False | **True** | 1 | 0 | False | False | $3.598\text{ m}$ | `3ca43993e9d5...` |
| **M1_S1** | `M1_S1_ep3` | False | **True** | 1 | 0 | False | False | $3.598\text{ m}$ | `b6a52b0eadc3...` |
| **M1_S2** | `M1_S2_ep1` | False | **True** | 1 | 0 | False | False | $3.088\text{ m}$ | `c6d74a03473f...` |
| **M1_S2** | `M1_S2_ep2` | False | **True** | 1 | 0 | False | False | $3.302\text{ m}$ | `5fa0c0f7e932...` |
| **M1_S2** | `M1_S2_ep3` | False | **True** | 1 | 0 | False | False | $3.598\text{ m}$ | `f296e84356e1...` |
| **M2_S1** | `M2_S1_ep1` | False | **True** | 1 | 0 | False | False | $3.318\text{ m}$ | `e54d0612d6ea...` |
| **M2_S1** | `M2_S1_ep2` | False | **True** | 1 | 0 | False | False | $3.087\text{ m}$ | `41069732f2ec...` |
| **M2_S1** | `M2_S1_ep3` | False | **True** | 1 | 0 | False | False | $3.597\text{ m}$ | `9b1f1412a80b...` |
| **M2_S2** | `M2_S2_ep1` | **True** | **True** | 2 | 0 | **True** | **True** | $0.224\text{ m}$ | `a20ed84c52dd...` |
| **M2_S2** | `M2_S2_ep2` | **True** | **True** | 2 | 0 | **True** | **True** | $0.189\text{ m}$ | `e1a25cb57064...` |
| **M2_S2** | `M2_S2_ep3` | **True** | **True** | 2 | 0 | **True** | **True** | $0.200\text{ m}$ | `24aeb569c106...` |

---

## 5. Comparative Mechanism Analysis

### 5.1 Continuous Blockage ($S_1$): Redundant Retries & Wasteful Collisions
- In **M0 (No Memory)**, the robot experiences an initial navigation failure at $t \approx 50\text{ s}$, then repeatedly re-plans directly into the blocked chokepoint until the 5-action budget is exhausted. This produces **4 redundant collisions per episode**.
- In **M1 (Persistent Memory)** and **M2 (Conditional Memory)**, the initial failure is registered. On subsequent cycles, the dispatch gate checks the active memory entry and immediately **suppresses further dispatches**. Redundant retries drop to **0.0/ep**, saving $80\%$ of execution budget.

### 5.2 Dynamic Clearance ($S_2$): Persistent Deadlock vs Conditional Recovery
- In **M1 (Persistent Memory)**, when the obstacle is removed at $t=25.0\text{ s}$, the memory policy retains $\sigma = \text{ACTIVE}$ indefinitely because it lacks invalidation semantics. As a result, the robot refuses to dispatch any new action, leading to **confirmed deadlock (0% success)** despite a physically clear corridor.
- In **M2 (Conditional Memory)**, upon obstacle removal, natural laser scans project into map coordinates and detect $0$ hits in the doorway bbox with $22$ rays traversing cleanly into Room 2. The costmap subgrid confirms $0$ occupied cells. This triggers:
  1. $\sigma_k: \text{ACTIVE} \to \text{INVALIDATED}$ at $t = 55.4\text{ s}$.
  2. Gate $G(a, \mathcal{M})$ transitions to $\text{ALLOW}$.
  3. Action `nav_step2` is dispatched, navigating through the corridor to $(1.80, 0.00)$.
  4. Passive settling confirms physical halt ($lv < 0.02\text{ m/s}, av < 0.02\text{ rad/s}$ for $3.0\text{ s}$), achieving final error $0.20\text{ m} < 0.35\text{ m}$ threshold.
  5. $\sigma_k: \text{INVALIDATED} \to \text{RECOVERY\_VERIFIED}$ confirmed.

---

## 6. Checksum Verification & Reproducibility Guarantees

All evidence artifacts are hashed with SHA256 in `reports/evidence/p2a/p2a_20260928_101002_9f61a3/checksums.sha256`:

- `p2a_summary_matrix.json`: `4987bb7924c8bde0d561b97d10a6c39105118b59391bbb8104a543c0580160c0`
- `coordinate_alignment_proof.json`: `d413a61f477842f42cf80829c681c50674a52566421cfe43cc048768b7bae7c9`
- `runtime_config.json`: `b06f96e78cc5327dbb49130544325b8e5d666e0c8fe8ff67655452b0ff26bcfc`

### Replication Command:
```bash
docker exec failmem_humble bash -c "source /opt/ros/humble/setup.bash && export PYTHONPATH=/workspace:\$PYTHONPATH && python3 /workspace/scripts/run_p2a_experiment.py"
```

---

## 7. Conclusion & Milestone Status

Milestone **P2a** is **COMPLETE AND VERIFIED**.
The empirical results establish a rock-solid, mathematically grounded foundation for FailMem:
- Deterministic failure memory eliminates redundant retry loops.
- Perception-conditioned invalidation eliminates deadlocks in dynamic environments.
- Zero reliance on LLM heuristics or privileged ground-truth injection during agent execution.
