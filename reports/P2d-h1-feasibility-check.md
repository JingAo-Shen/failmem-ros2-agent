# H1 Scenario Feasibility Check Protocol & Pre-Execution Plan

**Date**: 2026-10-01  
**Scope**: Limited Feasibility Check (Max 4 Physical Runs)  
**Objective**: Empirically test whether two distinct action configurations exhibit reproducible executability differences in the same unobstructed geometric passage under genuine Nav2 execution.

---

## 1. Experimental Configuration & Environment

- **World Model**: `configs/p2c_dualpath_world.model` (frozen SHA256: `7b5d5638...`)
- **Obstacle State**: **Absent** (Doorway is geometrically unobstructed, LiDAR ray pass-through verified, raw cell occupancy in center = 0).
- **Robot Spawn Pose**: `[-2.50, 0.00, 0.0, frame_id="map"]` (Decision Junction $J_0$).
- **Starting Corridor Waypoint**: `[-1.50, 1.20, 0.0]` (Corridor entrance).
- **Navigation Stack**: ROS 2 Humble Nav2 with `DWBLocalPlanner` and `NavFnPlanner`.

---

## 2. Action Profile Definitions

| Profile ID | Profile Name | Goal Target ($x, y, \text{yaw}$) | Timeout ($s$) | Target Description & Expected Physical Rationale |
| :--- | :--- | :--- | :---: | :--- |
| `act_aligned` | **Longitudinal Aligned Traversal ($a_{\text{aligned}}$)** | `[1.50, 1.20, 0.0]` | $15.0$ | Goal is aligned with the corridor central axis ($y=1.20$). Clears the $0.80\,\text{m}$ doorway with $\approx 0.21\,\text{m}$ lateral margin on both sides. Expected to succeed (`SUCCEEDED`). |
| `act_oblique` | **Boundary-Biased Oblique Entry ($a_{\text{oblique}}$)** | `[0.50, 0.88, 0.0]` | $15.0$ | Goal is placed in the narrow doorpost inflation boundary ($y=0.88$, wall edge at $y=0.80$). Robot footprint ($0.38\,\text{m}$) incurs inflation cost conflict with wall, triggering recovery oscillations. |

---

## 3. Pre-Defined Execution Sequence & Budget (Fixed 4 Runs)

1. **Run 1**: `H1_aligned_run1` ($a_{\text{aligned}}$, Attempt 1)
2. **Run 2**: `H1_aligned_run2` ($a_{\text{aligned}}$, Attempt 2)
3. **Run 3**: `H1_oblique_run1` ($a_{\text{oblique}}$, Attempt 1)
4. **Run 4**: `H1_oblique_run2` ($a_{\text{oblique}}$, Attempt 2)

**Hard Constraint**: Exactly 4 runs total. Zero parameter retries or tuning during execution. All 4 runs are logged and retained in evidence directory `reports/evidence/p2d_h1_feasibility/`.

---

## 4. Termination & Status Classification Rules

1. **`SUCCEEDED`**: Nav2 action server returns `SUCCEEDED` (status code 4), and physical pose at termination is within tolerance ($\Delta d \le 0.30\,\text{m}$, $\Delta \theta \le 0.35\,\text{rad}$) with verified passive halt.
2. **`ABORTED`**: Nav2 action server autonomously returns `ABORTED` (status code 6) due to recovery failure or local planner path exhaustion.
3. **`CANCELED` / `BUDGET_DEADLINE_EXCEEDED`**: Action does not complete within nominal $15.0\,\text{s}$ timeout; watchdog dispatches cancel request.
*Strict Requirement*: Must distinguish between Nav2 autonomous `ABORTED` and experiment watchdog `CANCELED`.

---

## 5. Decision & Go / No-Go Criteria

- **Go (Scenario Preliminary Usable)**:
  - Both runs of $a_{\text{aligned}}$ succeed (`SUCCEEDED`, 2/2).
  - Both runs of $a_{\text{oblique}}$ consistently fail (Nav2 `ABORTED` or timeout `CANCELED`, 2/2) in the same unobstructed doorway.
  - *Note*: Even if Go is reached, this only demonstrates that the physical scenario exhibits action-conditioned executability differences. It does **not** constitute a comparative method evaluation.
- **No-Go (Scenario Not Established - "本场景未建立")**:
  - If $a_{\text{oblique}}$ succeeds, OR if $a_{\text{aligned}}$ fails, the executability difference is not established. Exploration of $H_1$ will immediately terminate.

---

## 6. Physical Execution Results & Final Decision

### 6.1 Execution Summary Table

Evidence directory: `reports/evidence/p2d_h1_feasibility/` (Checksums verified in `checksums.sha256`).

| Run Name | Action Profile | Target Goal ($x, y, \theta$) | Perceived Doorway State | Nav2 Terminal Status | Execution Outcome | Duration ($s$) | Physical Arrival Verified |
| :--- | :--- | :--- | :---: | :---: | :--- | :---: | :---: |
| `H1_aligned_run1` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` | `SUCCEEDED` | `BUDGET_SUCCESS` | $18.8$ | False (Angular velocity halt check) |
| `H1_aligned_run2` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` | `SUCCEEDED` | `BUDGET_SUCCESS` | $18.8$ | True |
| `H1_oblique_run1` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` | `SUCCEEDED` | `BUDGET_SUCCESS` | $16.4$ | True |
| `H1_oblique_run2` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` | `SUCCEEDED` | `BUDGET_SUCCESS` | $16.3$ | True |

### 6.2 Analysis & Behavioral Findings

1. **Lack of Executability Divergence**: Both runs of `act_oblique` successfully traversed through the doorway and reached `[0.50, 0.88, 0.0]` in $\approx 16.3-16.4\,\text{s}$ without triggering Nav2 action aborts or timeout cancellations.
2. **Perception-Action Consistency**: Perception correctly verified `doorway_state == "FREE"` ($0$ laser hits in bounding box, $22-23$ rays traversing to Room 2). Nav2 local planner safely adjusted the path around the doorpost inflation radius, achieving successful traversal.
3. **Hypothesis Disconfirmation in Current Setup**: The assumption that geometric clearance (`FREE`) could reliably coexist with physical action failure (`ABORTED`) under the candidate parameterization is disconfirmed in this physical setup.

### 6.3 Final Verdict

**结论：本场景未建立 (Scenario Not Established - No-Go)**

In accordance with pre-registered protocol rules:
- No parameter tuning, retry hunting, or goal displacement was performed.
- All 4 physical attempts are fully logged and archived.
- The 20-run comparative experiment matrix for Hypothesis H1 is **strictly aborted**. No further physical experiments will be conducted for this hypothesis.

