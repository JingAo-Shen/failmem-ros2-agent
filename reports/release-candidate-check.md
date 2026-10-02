# FailMem Release Candidate Verification Report

- **Date**: 2026-10-02
- **Frozen Commit SHA**: `e3cce9d94469217757e249392f9e40a6f86e23ae`
- **Branch**: `audit/r0-authenticity`
- **Reproduction Evidence Directory**: `reports/evidence/p2c_pilot_reproduced_20261002_142300/`
- **Target Manuscript Artifacts**: `paper/draft.md`, `paper/paper.html`, `paper/paper.pdf`, `paper/build_report.json`

---

## 1. Executive Summary

This report documents the final release candidate consistency verification, machine-independent build audit, and offline reproduction check for the FailMem project. All code modifications, table generation pipelines, MathJax SVG pre-rendering steps, offline reproduction guardrails, and reference metadata updates are frozen at commit `e3cce9d94469217757e249392f9e40a6f86e23ae`. 

An independent end-to-end reproduction was executed into a dedicated timestamped evidence directory (`reports/evidence/p2c_pilot_reproduced_20261002_142300/`), achieving $100\%$ verification pass across all checksums, replay audits, baseline statistical tables, and $H_1$ feasibility checks. The manuscript build pipeline was refactored for complete machine independence with local Node.js MathJax dependencies, automated table row validation, raw TeX leak assertions, visual inspection of rendered pages, and a machine-readable build report.

---

## 2. Frozen Environment & Build Toolchain

| Tool / Environment | Version / Identifier | Purpose | Status |
| :--- | :--- | :--- | :--- |
| **Git Commit SHA** | `e3cce9d94469217757e249392f9e40a6f86e23ae` | Source & evidence snapshot | Frozen |
| **Operating System** | Linux 6.8.0-83-generic x86_64 (glibc 2.35) | Runtime platform | Verified |
| **Python** | Python 3.13.5 (Anaconda 64-bit) | Replay auditor & data analysis | Verified |
| **Node.js** | Node.js v24.21.0 (`mathjax-full@3.2.2` via `./package.json`) | Portable SVG vector math rendering | Verified |
| **Pandoc** | pandoc 2.12 (compiled with citeproc) | Markdown to HTML assembly | Verified |
| **WeasyPrint** | WeasyPrint version 70.0 | Academic CSS to PDF compilation | Verified |
| **Poppler** | pdftoppm version 22.02.0 | Page rasterization & visual inspection | Verified |
| **Key Python Packages** | `pandas==2.2.3`, `numpy==2.1.3`, `scipy==1.15.3`, `pytest==8.3.4`, `matplotlib==3.10.0` | Statistical testing & plotting | Verified |

---

## 3. End-to-End Cryptographic Traceability Chain

The following table documents the exact hash chain linking the frozen source code commit to the final PDF publication artifact:

```
[Frozen Commit: e3cce9d]
       │
       ▼
[Reproduction Report: reproduction_report.json]
       │
       ▼
[Generated Baseline CSVs: episodes.csv, condition_summary.csv, contrasts.csv]
       │
       ▼
[Table Markdown Files: table1.md, table2.md, table3.md]
       │
       ▼
[Build Pipeline: build_report.json]
       │
       ▼
[Compiled Paper: paper.pdf]
```

| Step in Pipeline | Artifact File Path | SHA256 Checksum | Traceability Role |
| :--- | :--- | :--- | :--- |
| **1. Frozen Code** | `git rev-parse HEAD` | `e3cce9d94469217757e249392f9e40a6f86e23ae` | Baseline code, scripts, tests |
| **2. Repro Report** | `reports/evidence/p2c_pilot_reproduced_20261002_142300/reproduction_report.json` | `cbb9d977b552b58aa1fca66efc3e00476c9bda874a3ef268fe5f83f7cd28330b` | End-to-end replay & integrity log |
| **3. Episodes CSV** | `reports/evidence/p2c_pilot_reproduced_20261002_142300/analysis/episodes.csv` | `40b0ae7a7af7dbd1fbed90655d69c14b734013100c48d7cec261972b044ae084` | 30 replayed physical runs |
| **4. Summary CSV** | `reports/evidence/p2c_pilot_reproduced_20261002_142300/analysis/condition_summary.csv` | `1fa9475d609d8e60cd7da1223c3ebff0f3e0c9a94c7188f61946cb426fe52111` | 10 condition aggregates ($ddof=1$) |
| **5. Contrasts CSV** | `reports/evidence/p2c_pilot_reproduced_20261002_142300/analysis/contrasts.csv` | `dd6a410c315d5e8b5db1390933d85146e77e655a504c4e8e3595c4bc3f4dcb95` | Pairwise condition differences |
| **6. H1 Derived** | `reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json` | `ac457f0a03e101cf8526a9bf3d7824c840cbf96bdae978767e72e9d396749580` | 4-run parsed timing & arrivals |
| **7. Table 1** | `paper/tables/table1_condition_summary.md` | `78a80da9d5a90ec9dda462577a4a6673579ea06511f45f28aecca4bf696454bb` | Condition table (10 data rows) |
| **8. Table 2** | `paper/tables/table2_pairwise_contrasts.md` | `fff3910ae7691a1950020f5dbd73b09d4887fbd90104e4f5a41e5e24a996f252` | Contrasts table (10 data rows) |
| **9. Table 3** | `paper/tables/table3_h1_feasibility.md` | `852d8e35bf1680cae74628dd6eedb52061ca113e1f2d8eb403af62f35827ec3c` | Feasibility table (4 data rows) |
| **10. Trajectory Map** | `paper/figures/trajectories_map.png` | `270a2634aee922c385da79ad2eea2eb4df404d87ac5f57c64551197a47014745` | High-res vector trajectory map |
| **11. Manuscript Draft** | `paper/draft.md` | `ca8b59094e1e25209f05b4a44121d661e35a83bbee7719aeea1bd3e33d26bf55` | Source text with citations |
| **12. Build Report** | `paper/build_report.json` | `6930b0d1730cf6a8435ec748d7fa3ef168c8c041fe80719bb782e67b7f8d9d3f` | Machine-readable build record |
| **13. Compiled PDF** | `paper/paper.pdf` | `ca15670a4f86c8f824e2b38606b928546a22ca0b880d2e0d8eee3f2a7a7a6116` | Final compiled PDF publication |

---

## 4. Verification Item Categorization & Results

Every claim, test, table, and figure has been classified into four explicit verification categories:

### 4.1 [AUTOMATED PASSED] (严格自动化检验通过)

1. **Path Safety Guardrails (Step 0)**:
   - Output directory collision, root escape, and ancestor overwrites prevented via strict `is_relative_to` checks in `reproduce_offline.py`.
2. **Raw Evidence Anti-Tamper Checksum Verification (Step 1)**:
   - Scanned `checksums.sha256` across 271 source raw files in `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/`.
   - Result: 271/271 matched ($100\%$), 0 mismatched, 0 missing.
3. **Automated Dataset Staging (Step 2)**:
   - Staged 30 episode directories and runtime configuration without copying stale analysis summaries.
4. **Independent Replay & Objective Scoring (Step 3)**:
   - Replayed all 30 episodes via `replay_and_score_p2c.py` under strict temporal causality and physical halt criteria ($|v_{\text{lin}}| \le 0.05\,\text{m/s}, |v_{\text{ang}}| \le 0.08\,\text{rad/s}$).
   - Episodes replayed: 30/30. Validity: 30/30. Replay audit pass rate: 30/30 ($100\%$).
5. **Statistical Aggregation & Integrity Reporting (Step 4)**:
   - Generated `episodes.csv` (30 rows), `condition_summary.csv` (10 rows), `contrasts.csv` (35 rows).
   - Integrity report: `integrity_check_passed: True` (30 expected, 30 found, 30 complete, 0 identity mismatches, 0 duplicate episodes, 0 conflicts).
6. **Mandatory Baseline CSV Verification (Step 5)**:
   - Comparison against frozen baseline CSVs:
     - `episodes.csv`: Match = True (0 shape, column, boolean, or numeric differences).
     - `condition_summary.csv`: Match = True (0 shape, column, boolean, or numeric differences).
     - `contrasts.csv`: Match = True (0 shape, column, boolean, or numeric differences).
7. **Hypothesis $H_1$ Evidence & Decision Verification (Step 6)**:
   - Verified 25 raw files in `reports/evidence/p2d_h1_feasibility/` against its SHA256 manifest (25/25 matched).
   - Verified presence and schema validity of 4 runs (`H1_aligned_run1`, `H1_aligned_run2`, `H1_oblique_run1`, `H1_oblique_run2`).
   - Recomputed timing and Go/No-Go decision: Nav2 SUCCEEDED: 4/4; strict physical arrival: 3/4 (`H1_aligned_run1` excess angular velocity $0.1068 > 0.08\,\text{rad/s}$); Decision: `NO-GO (Scenario Not Established)`.
8. **Table 1 Interface & Schema Fixes**:
   - Switched audit column from `audit_pass` to `replay_audit_pass`.
   - Strict boolean validation: rejected non-boolean strings (e.g. `"False"`) or `NaN` from counting as passed.
   - Strict `actual_route` enforcement: raises `KeyError`/`ValueError` on missing column or empty data (no fallback to `requested_routes`).
   - Unit tests pass: `tests/test_paper_table_generation.py` strictly asserts $10/10$ conditions report `3/3 (100\%)`.
9. **Table 2 Pairwise Contrasts Interface**:
   - Dynamically calculates $O - R$ contrast for D1 ($-3.273\,\text{m} / -19.0\%$, $-32.300\,\text{s} / -22.9\%$).
   - Validates presence of all 10 expected pairwise contrast rows.
10. **Table 3 $H_1$ Feasibility Interface**:
    - Removed all hardcoded mock arrays and fixed textual defaults.
    - Dynamically parses real halt failure reason (`excess av: 0.1068 > 0.08`) from serialized evidence.
11. **Machine-Independent MathJax & PDF Build**:
    - Removed hardcoded NVM paths; resolved `mathjax-full` locally via project-level `package.json`.
    - Automated table count validator verifies 3 tables (Table 1: 10 rows, Table 2: 10 rows, Table 3: 4 rows).
    - Raw TeX leak check: 0 unrendered TeX markers in compiled PDF.
12. **Pytest Regression Suite**:
    - 191 passed, 8 xfailed (historical synthetic mock fixtures), 0 failed across entire repository.

---

### 4.2 [HUMAN VISUAL PASSED] (人工视觉核对通过)

All 9 pages of `paper/paper.pdf` were rasterized at $150\,\text{dpi}$ to PNG (`paper/figures/pdf_pages/page-[1-9].png`) and inspected:

1. **Title & Header Layout (`page-1.png`)**: Single clean paper title header with `Anonymous Authors` metadata block; proper IEEE-style section numbering; no redundant title repetition.
2. **Typography & Formulas (`page-1.png` to `page-6.png`)**: Inline formulas ($n=3$, $ddof=1$, $t_{\text{rec}} \ge t_{\text{event}} + \Delta t_{\text{stab}}$, $|v_{\text{ang}}| \le 0.08\,\text{rad/s}$) and equations rendered as sharp, properly aligned SVG vectors without clipping or font substitutions.
3. **Table 1: Condition Summary (`page-6.png`)**:
   - Proper headers: Scenario, Condition, $n$, Actual Route, Dead-End Traversals, Decision Dist (m), Decision Time (s), Total Dist (m), Total Time (s), Replay Audit Pass.
   - All 10 conditions cleanly typeset with explicit `3/3 (100%)` Replay Audit Pass.
   - Accurate route representations (`Path_A`, `Path_A_then_Path_B`, `Path_B`).
4. **Table 2 & Trajectory Figure (`page-7.png`)**:
   - Table 2 cleanly formatted with all 10 contrast rows and negative signs.
   - **Figure 1 Subplot Titles**: Subtitles wrapped across lines to eliminate text collisions between left and right columns:
     - D1 F: "Avoids dead end;\ndirects via South Path B ($13.84\,\text{m}$)"
     - D1 R: "Uninformed retry to gate;\nretreats, takes Path B ($17.50\,\text{m}$)"
     - D2 F: "Dynamic invalidation on FREE;\ndirects via North Path A ($16.23\,\text{m}$)"
     - D2 M1: "Permanent suppression;\ndetour via South Path B ($18.34\,\text{m}$)"
     - Confirmed zero overlap between subplot titles.
5. **Table 3 & Limitations (`page-8.png`)**:
   - Table 3 formatted across 10 columns with accurate estimated Nav2 navigation times, assumed settling times, stability windows, and physical arrival verdicts (`False (excess av: 0.1068 > 0.08)` for `H1_aligned_run1`, `True` for others).
   - Findings & Decision text clearly demarcated.
6. **References & Citations (`page-9.png`)**:
   - Verified 12 primary references with clean DOI hyperlinks and consistent journal/conference formatting.
   - Conclusion block sits nicely on top of page 9 without page overrun.

---

### 4.3 [NOT EXECUTED] (未执行/研究范围边界)

The following items were explicitly scoped out and NOT executed in this release candidate:
1. **20-Run Formal Comparative Experiment**: Terminated under pre-registered protocol because candidate $H_1$ feasibility runs showed no executability divergence (Nav2 succeeded in both aligned and oblique runs).
2. **Physical Hardware Deployment**: Experiments conducted in Gazebo 11 simulation with TurtleBot3 Waffle; hardware deployment on physical robots remains future work.
3. **Phase F2 Algorithmic Implementation**: Action-profiled failure memory architecture ($F2$) and backoff spatial caching ($O+$) are documented as formal conceptual specifications, but not implemented in code.
4. **Alternative Controller Comparison**: Original $H_1$ design planned fast vs. slow controller profiles; actual feasibility check evaluated aligned vs. oblique doorway target goals under default DWB controller.

---

### 4.4 [UNVERIFIED / BOUNDS] (未经泛化验证/固有边界)

1. **Exploratory Sample Size ($n=3$ per condition)**: The 30-run benchmark demonstrates mechanism feasibility, auditability, and directional trends; it does not constitute large-sample asymptotic hypothesis testing.
2. **Statistical Equivalence of $F$ vs. $O$**: In static 2D geometry, FailMem ($F$) and spatial caching ($O$) choose identical high-level paths ($<1\%$ difference in reported distance/time). This demonstrates lack of measured benefit of $F$ over $O$ in this scenario, but does not prove statistical equivalence across general domains.
3. **Generalization Beyond 2D Static Geometry**: Invalidation logic was tested under static obstacles cleared across phases. Performance in 3D clutter or dynamic obstacle environments has not been verified.

---

## 5. Related Work & Text Calibration Checklist

| Verification Item | Prior Status / Defect | Release Candidate Resolution | Category |
| :--- | :--- | :--- | :--- |
| **REFLECT Description** | Characterized as "rule-based failure summarization" with unsupported performance overhead claims | Corrected in Abstract and Section 2.3: described as "hierarchical multi-modal experience summarization with LLMs to generate structured failure explanations and plan corrections"; removed unproven overhead assertions | **[AUTOMATED & VISUAL PASSED]** |
| **Reflexion Citation** | NeurIPS official paper URL hash mismatch | Updated in `reference-verification.csv` to official NeurIPS hash `1b44b878bb782e6954cd888628510e90` | **[AUTOMATED PASSED]** |
| **Macenski ROS 2 Paper** | add6975 DOI mismatch | Verified primary publisher entry for Science Robotics 7(66): eabm6074 | **[AUTOMATED PASSED]** |
| **Deliberation Survey** | Authors / DOI error | Verified authors Félix Ingrand & Malik Ghallab, Artificial Intelligence 247: 10–44 (2017), DOI: 10.1016/j.artint.2014.11.003 | **[AUTOMATED PASSED]** |
| **Bounded Metric Differences** | Overbroad $<1\%$ claims | Restricted strictly to reported total distance and total duration in static 2D geometry ($14.03\,\text{m}$ vs. $13.95\,\text{m}$ in D1; $16.25\,\text{m}$ vs. $16.40\,\text{m}$ in D2) | **[AUTOMATED & VISUAL PASSED]** |
| **$H_1$ Feasibility Conclusion** | Stated as general failure memory refutation | Unified text: *"本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。"* | **[AUTOMATED & VISUAL PASSED]** |

---

## 6. Remaining Issues & Open Items Checklist

- [x] Table 1 interface reads `replay_audit_pass` and reports $3/3 (100\%)$ for all 10 conditions.
- [x] Table 1 raises `KeyError`/`ValueError` on missing `actual_route` or `replay_audit_pass`.
- [x] Machine-independent build resolves `mathjax-full` locally without hardcoded user paths.
- [x] Project root contains `package.json` and `package-lock.json` with pinned `mathjax-full@3.2.2`.
- [x] Build pipeline verifies HTML table row counts (Table 1: 10, Table 2: 10, Table 3: 4).
- [x] Zero raw TeX leaks verified and enforced via automated assertion in `build_paper_pdf.py`.
- [x] Figure 1 trajectory map subtitle overlap resolved and verified visually.
- [x] End-to-end offline reproduction executed into fresh timestamped directory with 0 diffs.
- [x] Full test suite (191 tests) passes cleanly.
- [x] Documentation synchronized in `README.md` and `docs/reproduce-p2c.md`.
- [x] Remote push: Push frozen commit and verification report to `origin/audit/r0-authenticity`.

---

## 7. Release Candidate Verdict

> **RELEASE CANDIDATE STATUS: VERIFIED, AUDITED, AND FROZEN**
> 
> All delivery consistency checks, table generation interfaces, machine-independent build requirements, offline reproduction verifications, reference primary sources, and PDF vector typesetting are fully validated and reproducible from commit `e3cce9d94469217757e249392f9e40a6f86e23ae`.
