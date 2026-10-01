# Paper Draft v2 Revision Notes & Scientific Boundaries

**Date**: 2026-10-01  
**Target Paper**: `paper/draft.md` (Draft v2)  
**Associated BibTeX**: `paper/references.bib`  
**Reference Verification Table**: `paper/reference-verification.csv`  

---

## 1. Summary of Draft v2 Revisions

### 1.1 Reference Audit and Substantive Error Corrections
1. **`macenski2022ros2` & `macenski2020marathon2`**:
   - Replaced previous erroneous DOI `10.1016/j.robot.2023.104510` (which corresponded to a Riemannian manifold paper) with verified primary citations:
     - `macenski2022ros2`: *Science Robotics*, Vol. 7, No. 66, eabm6074, 2022, DOI: `10.1126/scirobotics.abm6074`.
     - `macenski2020marathon2`: *IEEE/RSJ IROS 2020*, pp. 2718–2725, DOI: `10.1109/IROS45743.2020.9341207` (arXiv: `2003.00368`).
2. **`liu2023reflect`**:
   - Corrected formal title to *"REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction"*, published in *CoRL 2023 (PMLR 229:3468–3484)*.
3. **`ingrand2017deliberation`**:
   - Corrected authors to *Félix Ingrand, Malik Ghallab*, publication volume *Artificial Intelligence (247:10–44, 2017)*, and DOI to `10.1016/j.artint.2014.11.003`.
4. **All References Verified**: Every citation in `paper/references.bib` was verified against primary publisher records and cataloged in `paper/reference-verification.csv`.

### 1.2 Mathematical Formulation & Code Consistency
1. **Hierarchical Doorway State Formulation**:
   - Replaced simplified $N_{\text{hits}} > 0$ rule with exact hierarchical logic from `src/doorway_evaluator.py`:
     - Explicit precondition validation: TF finite numbers, timestamp alignment $|t_{\text{tf}} - t_{\text{scan}}| \le 0.80\,\text{s}$, TF staleness $\le 1.0\,\text{s}$, scan staleness $\le 1.5\,\text{s}$, valid projected rays $N_{\text{valid}} > 0$, rays intersecting doorway bounding box $N_{\text{intersect}} > 0$.
     - `OCCUPIED`: $N_{\text{hits\_inside}} \ge 5$ or $N_{\text{costmap\_occupied\_cells}} > 0$.
     - `FREE`: $N_{\text{hits\_inside}} = 0$, $N_{\text{pass\_through}} \ge 8$, and costmap cleared ($N_{\text{unknown}} = 0 \land N_{\text{occupied}} = 0$).
     - `UNKNOWN`: Default fallback when preconditions or clearance criteria are not satisfied.
2. **Timing Tolerance Specification**:
   - Explicitly stated the $0.05\,\text{s}$ tolerance window applied during replay causality verification ($t_{\text{rec}} \ge \max(t_{\text{act}}, t_{\text{obs}}) - 0.05\,\text{s}$).
3. **Distance Metrics Disambiguation**:
   - Clearly separated:
     - Nominal map geometric path length: Path A ($6.12\,\text{m}$), Path B ($9.11\,\text{m}$);
     - Decision-phase traversed distance: D1 Path B ($\approx 7.54\,\text{m}$), D2 Path A ($\approx 5.89\,\text{m}$);
     - Total episode distance (including history leg): D1 $F/O$ ($\approx 14.03\,\text{m}$), D1 $R$ ($\approx 17.22\,\text{m}$).
4. **Scope of Memory Persistence**:
   - Clarified that memory transfer is implemented across sequential phases within an experimental runner session, and has not yet been evaluated as a multi-process persistent database.
5. **Reactive Baseline ($R$) Modeling**:
   - Described $R$'s structured entrance check at waypoint `[-1.50, 1.20]` and fallback retreat to $J_0$, noting that all methods share identical Nav2 costmap configurations.

### 1.3 Scientific Tone & Claim Calibration
1. **Elimination of Unsubstantiated Claims**:
   - Removed all uses of "pre-registered", "zero-bypass", "tamper-proof", "proving no independent advantage", "complete reproducibility", and "exact requirements".
   - SHA256 hashes are described as checking file integrity against the committed manifest.
2. **Unified $F$ vs. $O$ Phrasing**:
   - Adopted standard formulation: *"本次探索性数据中路线选择相同，未显示 F 的额外收益；尚未进行统计等效或一般化验证。"*
3. **Accurate Representation of Related Work**:
   - Clearly distinguished 3D occupancy voxels (OctoMap) from continuous signed distance fields (Voxblox).
   - Accurately described REFLECT, Inner Monologue, and Reflexion per their published papers, contrasting their language-level reasoning with FailMem's sensory grounding and deterministic invalidation rules.
4. **H1 Feasibility Finding**:
   - Retained exact empirical findings: 4/4 Nav2 `SUCCEEDED`, 3/4 verified strict physical arrival (`H1_aligned_run1` failed angular velocity halt threshold).
   - Maintained unified conclusion: *"本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。"*

---

## 2. Evidence Boundaries & Methodology

1. **Exploratory Pilot Scale ($n=3$)**:
   - Results represent mechanism functioning under fixed-seed simulation in Gazebo 11.
   - All standard deviations represent sample standard deviation ($ddof=1$).
2. **Single-Agent Static Dual-Path Geometry**:
   - The primary benchmark evaluates a single TurtleBot3 in a static dual-path corridor layout without dynamic obstacles or adversarial sensor noise.
3. **Single Canonical Directory**:
   - `paper/` is established as the sole canonical source of truth for the paper manuscript and references. `papers/README.md` redirects all readers to `paper/`.

---

## 3. Open Questions & Future Research Agenda

1. **Action-Conditioned Failure Differentiation ($F2$)**:
   - Designing benchmark environments where geometric space is verified `FREE` but specific action profiles (e.g. high-speed approach, large robot footprint, constrained steering angles) consistently trigger local controller abortion.
2. **Adaptive Invalidation under Dynamic Noise**:
   - Evaluating memory invalidation when sensors experience intermittent dropouts, occlusions, or false clearance reflections.
3. **Multi-Agent / Cross-Capability Transfer**:
   - Investigating transfer of failure records across heterogeneous robots with distinct kinematics and footprint envelopes.
4. **Persistent Cross-Session Storage**:
   - Scaling from in-memory runner contexts to multi-session persistent databases surviving robot restarts.
