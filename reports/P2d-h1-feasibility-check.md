# H1 Scenario Feasibility Check Protocol & Results Report

**Date**: 2026-10-01  
**Scope**: Limited Feasibility Check (Max 4 Physical Runs)  
**Objective**: Empirically test whether two distinct action configurations exhibit reproducible executability differences in the same unobstructed geometric passage under genuine Nav2 execution.

> [!NOTE]
> **Implementation Scope Note**: The actual physical check evaluates two distinct target goals (`act_aligned` at `[1.50, 1.20, 0.0]` vs. `act_oblique` at `[0.50, 0.88, 0.0]`) to probe geometric inflation boundary effects. It did not implement dynamic controller-level parameter swaps (such as fast vs. slow speed limits).

---

## 1. Experimental Configuration & Environment

- **World Model**: `configs/p2c_dualpath_world.model` (SHA256: `7b5d5638bbe4ecc17a18cec3c7cb38750c6bb513ce6be296a3ee4634129486f4`)
- **Protocol Configuration**: `configs/p2c_pilot_protocol.yaml` (SHA256: `fdbe35c90e53b0e80fa106cdee06d942033491cb212a616df815efc7c0b37a5f`)
- **Obstacle State**: **Absent** (Doorway is geometrically unobstructed, LiDAR ray pass-through verified with 22–23 rays, raw cell occupancy in center = 0).
- **Robot Spawn Pose**: `[-2.50, 0.00, 0.0, frame_id="map"]` (Decision Junction $J_0$).
- **Starting Corridor Waypoint**: `[-1.50, 1.20, 0.0]` (Corridor entrance).
- **Navigation Stack**: ROS 2 Humble Nav2 with `DWBLocalPlanner` and `NavFnPlanner`.

---

## 2. Action Profile Definitions

| Profile ID | Profile Name | Goal Target ($x, y, \text{yaw}$) | Timeout ($s$) | Target Description & Expected Physical Rationale |
| :--- | :--- | :--- | :---: | :--- |
| `act_aligned` | **Longitudinal Aligned Traversal ($a_{\text{aligned}}$)** | `[1.50, 1.20, 0.0]` | $15.0$ | Goal is aligned with the corridor central axis ($y=1.20$). Clears the $0.80\,\text{m}$ doorway with $\approx 0.21\,\text{m}$ lateral margin on both sides. Expected to succeed (`SUCCEEDED`). |
| `act_oblique` | **Boundary-Biased Oblique Entry ($a_{\text{oblique}}$)** | `[0.50, 0.88, 0.0]` | $15.0$ | Goal is placed in the narrow doorpost inflation boundary ($y=0.88$, wall edge at $y=0.80$). Probes whether local inflation cost triggers controller abortion. |

---

## 3. Fixed Execution Sequence & Budget (4 Runs)

1. **Run 1**: `H1_aligned_run1` ($a_{\text{aligned}}$, Attempt 1)
2. **Run 2**: `H1_aligned_run2` ($a_{\text{aligned}}$, Attempt 2)
3. **Run 3**: `H1_oblique_run1` ($a_{\text{oblique}}$, Attempt 1)
4. **Run 4**: `H1_oblique_run2` ($a_{\text{oblique}}$, Attempt 2)

**Hard Constraint**: Exactly 4 runs total. Zero parameter retries or goal shifting during execution. All 4 runs are logged and retained in raw evidence directory `reports/evidence/p2d_h1_feasibility/`.

---

## 4. Termination & Status Classification Rules

1. **`SUCCEEDED`**: Nav2 action server returns `SUCCEEDED` (status code 4), and physical pose at termination is within tolerance ($\Delta d \le 0.30\,\text{m}$, $\Delta \theta \le 0.35\,\text{rad}$) with verified passive halt.
2. **`ABORTED`**: Nav2 action server autonomously returns `ABORTED` (status code 6) due to recovery failure or local planner path exhaustion.
3. **`CANCELED` / `BUDGET_DEADLINE_EXCEEDED`**: Action does not complete within nominal $15.0\,\text{s}$ timeout; watchdog dispatches cancel request.
*Strict Requirement*: Must distinguish between Nav2 autonomous `ABORTED` and experiment watchdog `CANCELED`.

---

## 5. Decision & Go / No-Go Criteria

- **Go (Scenario Preliminary Usable)**:
  - Both runs of $a_{\text{aligned}}$ succeed (Nav2 `SUCCEEDED`, status code 4, and strict physical arrival 2/2).
  - Both runs of $a_{\text{oblique}}$ consistently fail (Nav2 `ABORTED` or timeout `CANCELED`, 2/2) in the same unobstructed doorway.
- **No-Go (Scenario Not Established - "本场景未建立")**:
  - If $a_{\text{oblique}}$ succeeds, OR if $a_{\text{aligned}}$ fails, the executability difference is not established. Exploration of $H_1$ terminates immediately.

---

## 6. Physical Execution Results & Final Decision

### 6.1 Execution Results & Timing Breakdown

- Raw evidence directory: `reports/evidence/p2d_h1_feasibility/` (Preserved intact with `checksums.sha256`)
- Parsed derived data: `reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json`

| Run Name | Action Profile | Target Goal ($x, y, \theta$) | Doorway Perception | Nav2 Status (Code) | Nav2 Nav Time ($s$) | Passive Settling ($s$) | Stability Window ($s$) | Total Sim Duration ($s$) | Physical Arrival Verified |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `H1_aligned_run1` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` ($23$ rays) | `SUCCEEDED` (4) | $13.4$ | $3.0$ | $2.4$ | $18.8$ | **False** (excess av: $0.1068 > 0.08$) |
| `H1_aligned_run2` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` ($22$ rays) | `SUCCEEDED` (4) | $13.4$ | $3.0$ | $2.4$ | $18.8$ | **True** |
| `H1_oblique_run1` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` ($23$ rays) | `SUCCEEDED` (4) | $11.1$ | $3.0$ | $2.3$ | $16.4$ | **True** |
| `H1_oblique_run2` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` ($22$ rays) | `SUCCEEDED` (4) | $11.0$ | $3.0$ | $2.3$ | $16.3$ | **True** |

### 6.2 Timing Calibration Note
The `test_action_duration_sec` ($16.3-18.8\,\text{s}$) recorded at the step level includes:
1. Active Nav2 navigation ($11.0-13.4\,\text{s}$, which completed within the $15.0\,\text{s}$ timeout);
2. Post-arrival passive halt settling wait ($3.0\,\text{s}$);
3. Post-halt trajectory stability recording window ($2.3-2.4\,\text{s}$).

### 6.3 Separate Performance Summary
- **Nav2 Action Server `SUCCEEDED`**: **4 / 4 (100%)**
- **Strict Physical Arrival & Stability Verified**: **3 / 4 (75%)**
  *(Note: `H1_aligned_run1` failed the angular velocity halt check during the stability window and is strictly not counted as an arrival success).*

### 6.4 Behavioral Analysis & Findings
1. **Lack of Executability Divergence**: Both runs of `act_oblique` traversed the doorway cleanly and reached `[0.50, 0.88, 0.0]` without planner abortion or timeout cancellation.
2. **Perception-Action Consistency**: Perception correctly verified `FREE` ($0$ laser hits, $22-23$ pass-through rays). The local planner safely accommodated the doorpost inflation gradient.
3. **No Parameter Hunting**: No parameter adjustments, retry attempts, or goal modifications were made.

### 6.5 Final Verdict

**结论：本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。**

The 20-run comparative experiment matrix for Hypothesis H1 is **strictly aborted**. Research conclusions are finalized on the existing boundary results.


