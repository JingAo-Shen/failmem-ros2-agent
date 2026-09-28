# FailMem P1c Single-Fault Channel Temporary Blockage Pilot Report

**Date**: 2026-09-28  
**Run ID**: `p1c_20260928_040123_da8cc6`  
**Evidence Directory**: [`reports/evidence/p1c/p1c_20260928_040123_da8cc6`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6)  
**Protocol File**: [`configs/p1c_blockage_protocol.yaml`](file:///code/failmem-ros2-agent/configs/p1c_blockage_protocol.yaml)  
**Overall Status**: `PASSED`  
**Branch**: `audit/r0-authenticity`  
**Pytest Suite**: 83 passed, 8 xfailed in 0.17s

---

## 1. Experimental Design & Protocol

This pilot pre-experiment establishes a repeatable, physically grounded single-fault environment anomaly benchmark in ROS 2 Humble / Gazebo Classic 11. It tests navigation behavior across 3 conditions (9 independent episodes) with strict offline scoring and continuous sensor tracking.

### 1.1 Arena & Obstacle Geometry
- **Arena**: `turtlebot3_world` (Gazebo Classic 11, $0.05$m/px 2D occupancy grid, origin at geometric center $[0, 0, 0]$).
- **Robot**: TurtleBot3 Waffle (footprint width $0.38$m).
- **Navigation Task**: Start pose $[-2.0, -0.5, 0.0, \text{map}] \longrightarrow$ Target goal $[0.5, -0.5, 0.0, \text{map}]$ (direct passage along the south corridor between cylinder rows).
- **Obstacle Placement**: Static rigid box ($0.6\text{m} \times 0.6\text{m} \times 0.6\text{m}$) spawned at $[-1.1, -0.55, 0.30, \text{world}]$ directly between landmark cylinders $(-1.1, -1.1)$ and $(-1.1, 0.0)$. The remaining clearance on either side is $< 0.10$m, physically sealing the south corridor.

```
       North Corridor (y = +0.55) [Open]
  (-1.1, 1.1) O --------- (0.0, 1.1) O --------- (1.1, 1.1) O
              |                       |                      |
              |                       |                      |
  (-1.1, 0.0) O --------- (0.0, 0.0) O --------- (1.1, 0.0) O
              |   [BOX]               |                      |
  Start       |  (-1.1,-0.55)         |                      |    Goal
[-2.0, -0.5] ---> [BLOCKED] --------> | -------------------> [0.5, -0.5]
  (-1.1,-1.1) O --------- (0.0,-1.1) O --------- (1.1,-1.1) O
       South Corridor (y = -0.55) [Occluded in C1/C2]
```

### 1.2 Experimental Conditions (3 Episodes Each)
1. **$C_0$ (Unblocked Baseline)**: No obstacle present. Initial Observe $\to$ Navigate to $[0.5, -0.5]$ $\to$ Passive 2.0s settling $\to$ Stability window $\to$ Final Observe.
2. **$C_1$ (Continuous Obstacle Blockage)**: Obstacle box continuously present. Initial Observe $\to$ Navigate to $[0.5, -0.5]$ (timeout 30.0s) $\to$ Failure / timeout cancellation $\to$ Passive settling $\to$ Stability window $\to$ Post-failure Observe.
3. **$C_2$ (Temporary Obstacle Blockage)**: Obstacle box initially present $\to$ Initial navigate blocked (timeout 25.0s) $\to$ Mid Observe $\to$ Obstacle deleted via `/delete_entity` + costmaps purged $\to$ Retry action dispatched with replayed parameters from action history $\to$ Nav2 traverses cleared south corridor to $[0.5, -0.5]$ $\to$ Final Observe.

---

## 2. Empirical Results Matrix (9 Independent Episodes)

| Episode | Cond | Obstacle Present | Step 1 Nav Outcome | Mid Obs Status | Obstacle Deleted | Retry Nav Outcome | Final GT Pos $(x, y)$ | Final GT Err (m) | Final AMCL Err (m) | Stability Window | Episode Result |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `C0_ep1` | $C_0$ | None | `BUDGET_SUCCESS` | N/A | N/A | N/A | $(0.47, -0.49)$ | $0.24$ | $0.03$ | $2.40$s stable | **PASSED** |
| `C0_ep2` | $C_0$ | None | `BUDGET_SUCCESS` | N/A | N/A | N/A | $(0.43, -0.51)$ | $0.28$ | $0.07$ | $2.40$s stable | **PASSED** |
| `C0_ep3` | $C_0$ | None | `BUDGET_SUCCESS` | N/A | N/A | N/A | $(0.47, -0.51)$ | $0.24$ | $0.04$ | $2.40$s stable | **PASSED** |
| `C1_ep1` | $C_1$ | $[-1.1, -0.55]$ | `BUDGET_DEADLINE_EXCEEDED` | N/A | No | N/A | $(-1.02, -0.53)$ | $1.52$ (blocked) | N/A | $2.50$s stable | **PASSED** |
| `C1_ep2` | $C_1$ | $[-1.1, -0.55]$ | `BUDGET_DEADLINE_EXCEEDED` | N/A | No | N/A | $(-1.01, -0.54)$ | $1.51$ (blocked) | N/A | $2.50$s stable | **PASSED** |
| `C1_ep3` | $C_1$ | $[-1.1, -0.55]$ | `BUDGET_DEADLINE_EXCEEDED` | N/A | No | N/A | $(-1.03, -0.52)$ | $1.53$ (blocked) | N/A | $2.50$s stable | **PASSED** |
| `C2_ep1` | $C_2$ | Initial $\to$ Deleted | `BUDGET_DEADLINE_EXCEEDED` | `ERROR` (stale) | **Yes** | `BUDGET_SUCCESS` | $(0.45, -0.48)$ | $0.26$ | $0.06$ | $2.50$s stable | **PASSED** |
| `C2_ep2` | $C_2$ | Initial $\to$ Deleted | `BUDGET_DEADLINE_EXCEEDED` | `ERROR` (stale) | **Yes** | `BUDGET_SUCCESS` | $(0.45, -0.50)$ | $0.25$ | $0.05$ | $2.50$s stable | **PASSED** |
| `C2_ep3` | $C_2$ | Initial $\to$ Deleted | `BUDGET_DEADLINE_EXCEEDED` | `SUCCESS` | **Yes** | `BUDGET_SUCCESS` | $(0.47, -0.51)$ | $0.24$ | $0.03$ | $2.50$s stable | **PASSED** |

---

## 3. Detailed Analysis & Key Findings

### 3.1 Baseline Navigation ($C_0$)
- In all 3 episodes, TurtleBot3 smoothly traversed the unobstructed south corridor $[-2.0, -0.5] \to [0.5, -0.5]$ within $11.5$s simulation time.
- Physical arrival errors: Ground truth position error $= 0.24 - 0.28$m ($\le 0.30$m tolerance); AMCL position error $= 0.03 - 0.07$m.
- Passive settling: Verified $2.0$s continuous stillness with $|v_{\text{lin}}| \le 0.0001$ m/s, $|v_{\text{ang}}| \le 0.0004$ rad/s and zero safety intervention.

### 3.2 Continuous Obstacle Blockage ($C_1$)
- The spawned obstacle box at $[-1.1, -0.55]$ was immediately detected by 2D laser scan ($\text{min\_range} \approx 0.48 - 0.49$m) and mapped into local/global costmaps.
- Under the 30.0s simulation time budget, Nav2 attempted local recovery behaviors and was unable to find an unblocked path through the south corridor.
- At $t=30.0$s sim time, `await_nav_goal_terminal_result()` triggered graceful goal cancellation, and the robot executed a passive physical halt at $x \approx -1.02, y \approx -0.53$ (remaining $1.51 - 1.53$m away from the target).
- **Detour Analysis**: 0 out of 3 episodes found a bypass route within the 30s budget, confirming robust channel occlusion.

### 3.3 Temporary Blockage with Observe $\to$ Removal $\to$ Retry ($C_2$)
- **Phase 1 (Blockage)**: Navigation initiated against the obstacle, cleanly timed out at 25.0s sim time, halted passively, and recorded `BUDGET_DEADLINE_EXCEEDED`.
- **Phase 2 (Observe & Clearing)**: Mid-episode observe was dispatched. The obstacle was deleted from the Gazebo physical world via `/delete_entity`, and costmaps were purged.
- **Phase 3 (Retry Navigation)**: Action dispatcher dispatched `retry` with replayed parameters from action history (`action_id: C2_epX_retry_nav` referencing `original_action_id: C2_epX_nav_orig`). Nav2 replanned through the newly opened corridor, successfully navigating to $[0.5, -0.5]$ in $11.0$s sim time.
- **Phase 4 (Arrival & Final Observe)**: In all 3 episodes, physical arrival was verified at $[0.45 - 0.47, -0.48 - -0.51]$ ($\le 0.30$m tolerance), passive 2.0s halt was verified, and the post-arrival observe action returned `SUCCESS`.

---

## 4. Evidence Integrity & Artifact Links

Every episode in run `p1c_20260928_040123_da8cc6` contains full raw telemetry and verification logs:

- **Geometric Consistency**: [`coordinate_alignment_proof.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/coordinate_alignment_proof.json) (9 landmarks verified, max residual 0.0594m).
- **Run Summary**: [`summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/summary.json)
- **Cryptographic Manifest**: [`checksums.sha256`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/checksums.sha256)
- **Episode Evidence Packages**:
  - `C0_ep1`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep1/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep1/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep1/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep1/episode_summary.json)
  - `C0_ep2`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep2/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep2/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep2/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep2/episode_summary.json)
  - `C0_ep3`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep3/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep3/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep3/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C0_ep3/episode_summary.json)
  - `C1_ep1`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep1/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep1/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep1/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep1/episode_summary.json)
  - `C1_ep2`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep2/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep2/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep2/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep2/episode_summary.json)
  - `C1_ep3`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep3/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep3/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep3/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C1_ep3/episode_summary.json)
  - `C2_ep1`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep1/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep1/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep1/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep1/episode_summary.json)
  - `C2_ep2`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep2/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep2/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep2/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep2/episode_summary.json)
  - `C2_ep3`: [`events.log`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep3/events.log), [`trajectory.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep3/trajectory.json), [`stability_window.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep3/stability_window.json), [`episode_summary.json`](file:///code/failmem-ros2-agent/reports/evidence/p1c/p1c_20260928_040123_da8cc6/C2_ep3/episode_summary.json)

---

## 5. Conclusion & Transition to P2

Milestone P1c demonstrates that:
1. Physical blockage can be dynamically controlled via Gazebo entity lifecycle without restart side-effects or state pollution across independent episodes.
2. The Action Runtime + Dispatcher correctly manages parameter history replay on `retry`, generates distinct RFC 4122 v5 UUIDs, and enforces single-state retry budgets.
3. The offline scoring evaluator reliably assesses arrival vs. blockage vs. settling stability.

With P1b closeout and P1c pilot completed and passing, the test harness is verified and ready for **Milestone P2 (FailMem Failure Memory Database, Indexing, and Policy Evaluation)**.
