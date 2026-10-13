# FailMem: Supplementary Materials & Verification Audit Details

**Title**: Auditable Failure Memory for ROS 2 Navigation: Supplementary Materials  
**Document Status**: Accompanying Material for Review & Reproduction  
**Associated Commit**: `e3cce9d`  

---

## S1. Precondition Integrity & Doorway Clearance Details

The passage state evaluation in `src/doorway_evaluator.py` enforces strict sensor-TF alignment rules prior to emitting a clearance classification:

### S1.1 Precondition Rules
1. **Finite Transforms**: TF translation vector $\mathbf{t} = [x, y, z]^T$ and yaw angle $\psi$ must be finite real numbers ($-\infty < x, y, z, \psi < \infty$).
2. **Temporal Alignment**: Scan and TF timestamps must satisfy $|t_{\text{tf}} - t_{\text{scan}}| \le 0.80\,\text{s}$.
3. **Data Freshness**: Current simulation clock $t_{\text{sim}}$ must satisfy $t_{\text{sim}} - t_{\text{tf}} \le 1.0\,\text{s}$ and $t_{\text{sim}} - t_{\text{scan}} \le 1.5\,\text{s}$.
4. **Ray Projections**:
   - Number of finite laser scan ranges $N_{\text{valid}} > 0$.
   - Number of projected rays intersecting the doorway bounding volume $N_{\text{intersect}} > 0$.
5. **Costmap Availability**: When costmap subgrids are provided, total cells in the Region of Interest (ROI) $N_{\text{total\_cells}} > 0$.

If any precondition fails, the evaluator emits $\text{State}(B) = \text{UNKNOWN}$ and does not alter memory state.

### S1.2 Bounding Volume & Threshold Parameters
- Doorway center: $x = 0.0\,\text{m}, y = 1.20\,\text{m}$.
- ROI bounding box: $x \in [-0.15, 0.15]\,\text{m}, y \in [0.95, 1.45]\,\text{m}$.
- Minimum pass-through rays for `FREE`: $N_{\text{pass\_through}} \ge 8$.
- Maximum hits inside for `FREE`: $N_{\text{hits\_inside}} = 0$.
- Hits threshold for `OCCUPIED`: $N_{\text{hits\_inside}} \ge 5$ or $N_{\text{costmap\_occupied\_cells}} > 0$.

---

## S2. Cryptographic Replay Audit Engine

To avoid reliance on self-reported runtime metrics, the independent replay auditor (`scripts/replay_and_score_p2c.py`) re-scores every physical simulation run offline:

### S2.1 Replay Integrity Verification Steps
1. **Manifest Audit**: Verifies every serialized file against `checksums.sha256` to detect modifications relative to the recorded manifest (detecting file changes relative to the manifest, rather than asserting intrinsic authenticity of the original underlying sensor data).
2. **Trajectory Distance**: Computes traversed distance by summing Euclidean distances between consecutive odometry sample positions $\langle x_k, y_k \rangle_{k=1}^K$:
   $$d = \sum_{k=2}^K \sqrt{(x_k - x_{k-1})^2 + (y_k - y_{k-1})^2}$$
3. **Halt Stability Verification**: Verifies that upon goal completion, the robot remains stationary over a minimum nominal window of $2.0\,\text{s}$:
   $$\max_{t \in [t_{\text{goal}}, t_{\text{goal}} + \Delta t_{\text{stab}}]} |v_{\text{lin}}(t)| \le 0.05\,\text{m/s}, \quad \max_{t \in [t_{\text{goal}}, t_{\text{goal}} + \Delta t_{\text{stab}}]} |v_{\text{ang}}(t)| \le 0.08\,\text{rad/s}$$
4. **Chronological Causality**:
   $$t_{\text{rec}} \ge \max(t_{\text{action\_end}}, t_{\text{obs\_eval}}) - 0.05\,\text{s}$$
   $$t_{\text{inv}} \ge \max(t_{\text{failure}}, t_{\text{free\_eval}}) - 0.05\,\text{s}$$

---

## S3. Machine-Independent PDF Build Pipeline

The manuscript build pipeline (`paper/scripts/build_paper_pdf.py`):
1. **Dynamic Table Injection**: Substitutes `<!-- TABLE:... -->` markers with freshly generated LaTeX and Markdown tables.
2. **MathJax Vector SVG Pre-Rendering**: Converts LaTeX formulas into inline SVG vector paths via Node.js `mathjax-full@3.2.2` resolved from project root `package.json`.
3. **Table Row Validation**: Verifies generated HTML table structure prior to PDF compilation:
   - Table 1 (Condition Summary): Exactly 10 data rows.
   - Table 2 (Pairwise Contrasts): Exactly 10 data rows.
   - Table 3 ($H_1$ Feasibility): Exactly 4 data rows.
4. **Zero Raw TeX Leak Assertion**: Renders compiled PDF pages to PNG at $150\,\text{dpi}$ (`pdftoppm`) and extracts text (`pdftotext`); raises `RuntimeError` on unrendered TeX control sequences.
5. **Structured Build Record**: Emits `paper/build_report.json` documenting tool versions, pre-build git status, post-build workspace changes, and cryptographic input/output digests.

---

## S4. Detailed Parameter & Source Code Traceability

For exact code symbol and line-number mappings for all mathematical formulations and protocol parameters, refer to [`paper/method-code-map.csv`](method-code-map.csv) (33 parameter mappings). For the complete literature primary verification ledger, refer to [`paper/reference-verification.csv`](reference-verification.csv) (15 primary-source verified references).

---

## S5. D2 Trajectory Time Ledger: Observational Decomposition & Threshold Sensitivity

### S5.1 Observational Trajectory Time Ledger & Algebraic Closure
To analyze timing differences between FailMem ($F$) and persistent suppression ($M1$) in Scenario D2 without relying on unverified stationary assumptions, we perform an observational trajectory decomposition across Full Episode, History Phase, and Decision Phase.

> **Notice on Algebraic Residuals**: The zero residual ($\text{residual} = 0.000\,\text{s}$) across all phases arises strictly by algebraic construction (absorbing unobserved active intervals and outside-action time as remainder components), and does not serve as independent validation of velocity classification accuracy or physical mechanism validity.

#### Decision Phase Ledger ($t \ge T_{\text{history}}$)
| Condition | $n$ | Distance (m) | Duration $T_{\text{dec}}$ (s) | Moving $T_{\text{mov}}$ (s) | Turning $T_{\text{turn}}$ (s) | Stopped $T_{\text{stop}}$ (s) | [Settling Window] (s) | Unobserved $T_{\text{unobs}}$ (s) | Outside Actions (s) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D2_F** | 3 | 5.89 ± 0.02 | 51.10 ± 0.95 | 28.70 ± 1.18 | 4.20 ± 0.82 | 15.83 ± 2.42 | [6.97] | 1.33 ± 0.06 | 1.03 ± 0.15 |
| **D2_M1** | 3 | 7.89 ± 0.02 | 51.30 ± 2.00 | 34.30 ± 1.76 | 3.47 ± 0.49 | 12.13 ± 1.41 | [4.60] | 0.70 ± 0.00 | 0.70 ± 0.00 |
| **D2_O** | 3 | 5.94 ± 0.07 | 52.03 ± 1.75 | 29.33 ± 2.15 | 3.83 ± 0.49 | 16.47 ± 0.06 | [6.93] | 1.30 ± 0.10 | 1.10 ± 0.20 |
| **D2_R** | 3 | 5.92 ± 0.04 | 49.57 ± 1.59 | 28.27 ± 0.45 | 4.17 ± 0.84 | 14.70 ± 1.55 | [5.37] | 1.27 ± 0.06 | 1.17 ± 0.12 |

#### History Phase Ledger ($t < T_{\text{history}}$)
| Condition | $n$ | Distance (m) | Duration $T_{\text{hist}}$ (s) | Moving $T_{\text{mov}}$ (s) | Turning $T_{\text{turn}}$ (s) | Stopped $T_{\text{stop}}$ (s) | [Settling Window] (s) | Unobserved $T_{\text{unobs}}$ (s) | Outside Actions (s) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D2_F** | 3 | 10.36 ± 0.08 | 100.00 ± 7.72 | 52.37 ± 3.66 | 9.93 ± 0.75 | 30.13 ± 4.31 | [11.00] | 3.17 ± 0.15 | 4.40 ± 0.30 |
| **D2_M1** | 3 | 10.35 ± 0.11 | 97.53 ± 2.12 | 49.23 ± 1.58 | 10.10 ± 0.76 | 30.63 ± 0.91 | [11.77] | 3.20 ± 0.10 | 4.37 ± 0.31 |
| **D2_O** | 3 | 10.46 ± 0.22 | 97.73 ± 1.21 | 49.80 ± 1.14 | 9.83 ± 0.50 | 30.70 ± 0.78 | [11.87] | 3.23 ± 0.06 | 4.17 ± 0.42 |
| **D2_R** | 3 | 10.43 ± 0.05 | 98.60 ± 2.38 | 50.90 ± 1.32 | 9.40 ± 0.46 | 30.53 ± 1.80 | [11.77] | 3.07 ± 0.06 | 4.70 ± 0.27 |

#### Full Episode Ledger
| Condition | $n$ | Distance (m) | Duration $T_{\text{total}}$ (s) | Moving $T_{\text{mov}}$ (s) | Turning $T_{\text{turn}}$ (s) | Stopped $T_{\text{stop}}$ (s) | [Settling Window] (s) | Unobserved $T_{\text{unobs}}$ (s) | Outside Actions (s) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D2_F** | 3 | 16.25 ± 0.10 | 151.10 ± 7.76 | 81.07 ± 4.48 | 14.13 ± 1.29 | 45.97 ± 2.57 | [17.97] | 4.50 ± 0.17 | 5.43 ± 0.45 |
| **D2_M1** | 3 | 18.25 ± 0.09 | 148.83 ± 2.40 | 83.53 ± 3.01 | 13.57 ± 0.51 | 42.77 ± 1.61 | [16.37] | 3.90 ± 0.10 | 5.07 ± 0.31 |
| **D2_O** | 3 | 16.40 ± 0.24 | 149.77 ± 0.55 | 79.13 ± 1.03 | 13.67 ± 0.15 | 47.17 ± 0.76 | [18.80] | 4.53 ± 0.12 | 5.27 ± 0.50 |
| **D2_R** | 3 | 16.34 ± 0.03 | 148.17 ± 3.16 | 79.17 ± 0.90 | 13.57 ± 1.21 | 45.23 ± 1.16 | [17.13] | 4.33 ± 0.06 | 5.87 ± 0.38 |

*Note*: Settling window duration (`sim_duration_covered`) is reported strictly as an independent event-level observation metric and is not algebraically subtracted from stopped time.

### S5.2 Discretization Threshold Sensitivity Analysis
To evaluate sensitivity to kinematic classification parameters, Decision Phase moving and stopped durations were evaluated across linear velocity thresholds $v_{\text{lin}} \in \{0.03, 0.05, 0.08\}\,\text{m/s}$, angular velocity thresholds $\omega_{\text{ang}} \in \{0.05, 0.08, 0.12\}\,\text{rad/s}$, and gap thresholds $\tau_{\text{gap}} \in \{0.25, 0.50, 1.00\}\,\text{s}$.

| $v_{\text{lin}}$ (m/s) | $\omega_{\text{ang}}$ (rad/s) | $\tau_{\text{gap}}$ (s) | $F$ Moving (s) | $M1$ Moving (s) | Diff (s) | $F$ Stopped (s) | $M1$ Stopped (s) | Diff (s) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0.03 | 0.05 | 0.25 | 31.30 | 36.40 | -5.10 | 13.80 | 10.70 | +3.10 |
| 0.03 | 0.08 | 0.50 | 31.30 | 36.40 | -5.10 | 13.80 | 10.70 | +3.10 |
| 0.03 | 0.12 | 1.00 | 31.30 | 36.40 | -5.10 | 13.80 | 10.70 | +3.10 |
| 0.05 | 0.05 | 0.25 | 28.70 | 34.30 | -5.60 | 15.77 | 12.07 | +3.70 |
| 0.05 | 0.08 | 0.50 | 28.70 | 34.30 | -5.60 | 15.83 | 12.13 | +3.70 |
| 0.05 | 0.12 | 1.00 | 28.70 | 34.30 | -5.60 | 15.90 | 12.13 | +3.77 |
| 0.08 | 0.05 | 0.25 | 25.80 | 32.60 | -6.80 | 18.33 | 13.13 | +5.20 |
| 0.08 | 0.08 | 0.50 | 25.80 | 32.60 | -6.80 | 18.47 | 13.27 | +5.20 |
| 0.08 | 0.12 | 1.00 | 25.80 | 32.60 | -6.80 | 18.53 | 13.30 | +5.23 |

*Sensitivity Summary*: Across thresholds, sample mean moving differences range from $-5.10\,\text{s}$ to $-6.80\,\text{s}$, and stopped differences range from $+3.10\,\text{s}$ to $+5.23\,\text{s}$. Because individual components depend on discretization thresholds, we report them as observational latencies without asserting exact physical compensation.


