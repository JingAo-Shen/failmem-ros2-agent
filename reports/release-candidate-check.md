# FailMem Release Candidate Verification Report

- **Date**: 2026-10-01
- **Frozen Commit SHA**: `29a21107ddfeb0972a6d4b100b854f80fdddf79d`
- **Branch**: `audit/r0-authenticity`
- **Reproduction Evidence Directory**: `reports/evidence/p2c_pilot_reproduced_20261001_233651/`
- **Target Manuscript**: `paper/draft.md`, `paper/paper.pdf`, `paper/paper.html`

---

## 1. Executive Summary

This report documents the final release candidate consistency verification and offline reproduction check for the FailMem project. All code modifications, table generation pipelines, MathJax SVG pre-rendering steps, offline reproduction guardrails, and reference metadata updates were frozen at commit `29a2110`. An independent end-to-end reproduction from the frozen commit was executed into a dedicated timestamped evidence directory (`reports/evidence/p2c_pilot_reproduced_20261001_233651/`), achieving $100\%$ verification pass across all checksums, replay audits, baseline statistical tables, and $H_1$ feasibility checks.

---

## 2. Frozen Environment & Metadata

| Field | Value |
| :--- | :--- |
| **Git Commit SHA** | `29a21107ddfeb0972a6d4b100b854f80fdddf79d` |
| **Git Status** | Clean (0 uncommitted modifications) |
| **Operating System** | Linux 6.8.0-83-generic x86_64 (glibc 2.35) |
| **Python Version** | Python 3.13.5 (Anaconda 64-bit) |
| **Key Package Versions** | `pandas==2.2.3`, `numpy==2.1.3`, `scipy==1.15.3`, `pytest==8.3.4`, `weasyprint==70.0` |
| **Node.js Math Pre-renderer** | MathJax-full v3.2.2 on Node.js v24.21.0 |

---

## 3. Offline Reproduction & Audit Verification Results

The automated reproduction suite was executed via `./scripts/reproduce_offline.sh --output-dir reports/evidence/p2c_pilot_reproduced_20261001_233651`.

### 3.1 Step-by-Step Execution Summary

1. **Path Safety & Collision Validation (Step 0)**:
   - Verified that `output_dir` is not identical to, nested within, or an ancestor of `REPO_ROOT`, `source_dir`, `baseline_dir`, `h1_dir`, or system root paths.
   - Verified that `output_dir` was newly created and clean.
   - Status: **PASSED**

2. **SHA256 Anti-Tamper Checksum Verification (Step 1)**:
   - Scanned `checksums.sha256` across 271 source raw files.
   - Result: 271/271 matched, 0 mismatched, 0 missing.
   - Status: **PASSED**

3. **Automated Dataset Staging (Step 2)**:
   - Staged 30 episode directories and runtime configuration without copying stale analysis summaries.
   - Status: **PASSED**

4. **Independent Replay & Scoring (Step 3)**:
   - Replayed all 30 episodes (`replay_and_score_p2c`).
   - Episodes replayed: 30/30.
   - Validity: 30/30 valid.
   - Replay audit pass rate: 30/30 ($100\%$).
   - Status: **PASSED**

5. **Statistical Aggregation & Integrity Reporting (Step 4)**:
   - Generated `episodes.csv` (30 rows), `condition_summary.csv` (10 rows), `contrasts.csv` (35 rows).
   - Integrity report: `integrity_check_passed: True` (30 expected, 30 found, 30 complete, 0 identity mismatches, 0 duplicate episodes, 0 conflicts).
   - Single-location retention: stored exclusively in `output_dir/analysis/`.
   - Status: **PASSED**

6. **Baseline CSV Verification (Step 5)**:
   - Mandatory comparison against baseline CSVs in `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/`.
   - `episodes.csv`: Match = True (0 shape, column, boolean, or numeric differences).
   - `condition_summary.csv`: Match = True (0 shape, column, boolean, or numeric differences).
   - `contrasts.csv`: Match = True (0 shape, column, boolean, or numeric differences).
   - Status: **PASSED**

7. **Hypothesis $H_1$ Raw & Derived Evidence Verification (Step 6)**:
   - Verified 25 raw files in `reports/evidence/p2d_h1_feasibility/` against its SHA256 tree (25/25 matched).
   - Verified presence and schema validity of 4 runs (`H1_aligned_run1`, `H1_aligned_run2`, `H1_oblique_run1`, `H1_oblique_run2`).
   - Derived timing breakdowns and Go/No-Go evaluation:
     - Nav2 `SUCCEEDED` (code 4): 4/4 runs.
     - Strict physical arrival verified: 3/4 runs (`H1_aligned_run1` excess angular velocity $0.1068 > 0.08\,\text{rad/s}$).
     - Go condition: False (`NO-GO (Scenario Not Established)`).
     - Unified conclusion preserved: *"本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。"*
   - Status: **PASSED**

---

## 4. Paper Table Generation & Embedding Verification

The paper table generation script (`paper/scripts/generate_paper_tables.py`) and PDF compilation pipeline (`paper/scripts/build_paper_pdf.py`) were validated:

### 4.1 Table 1: Condition Summary (`paper/tables/table1_condition_summary.md` / `.tex`)
- **Route Aggregation**: Replaced static requested route with aggregated `actual_route` directly from `episodes.csv` (`Path_A`, `Path_B`, `Path_A_then_Path_B`).
- **Audit Pass Rate**: Replaced hardcoded string with dynamic calculation from `episodes.csv` `audit_pass` column ($3/3, 100\%$).
- Verification: **PASSED**

### 4.2 Table 2: Pairwise Contrasts (`paper/tables/table2_pairwise_contrasts.md` / `.tex`)
- **$O - R$ Contrast Calculation**: Explicitly calculated spatial cache vs. reactive contrast in D1 ($-3.273\,\text{m} / -19.0\%$, $-32.300\,\text{s} / -22.9\%$).
- **Row Completeness**: Checked that all 10 expected pairwise contrast entries (5 comparisons $\times$ 2 metrics) are present and formatted correctly.
- Verification: **PASSED**

### 4.3 Table 3: $H_1$ Feasibility (`paper/tables/table3_h1_feasibility.md` / `.tex`)
- **No Mock Fallback**: Removed all hardcoded fallback arrays; missing input raises explicit `FileNotFoundError`.
- **Dynamic Halt Failure Reason**: Dynamically parses actual halt failure reason (`excess av: 0.1068 > 0.08`) for `H1_aligned_run1` from serialized evidence.
- Verification: **PASSED**

### 4.4 Dynamic Markdown & HTML Assembly
- `build_paper_pdf.py` replaces `<!-- TABLE:... -->` blocks with freshly generated table contents.
- Post-assembly validator verifies that all 3 tables are non-empty and embedded in `paper.html`.
- Verification: **PASSED**

---

## 5. PDF Visual & Math Typesetting Inspection

- **Pipeline**: Pandoc Markdown $\to$ MathJax Vector SVG Pre-Rendering $\to$ WeasyPrint Academic CSS Compilation.
- **Compiled File**: `paper/paper.pdf` ($816.2\,\text{KB}$, 9 pages).
- **Math Vector Quality**: All inline formulas (e.g., $n=3$, $ddof=1$, $t_{\text{rec}} \ge \dots$) and display equations converted to native SVG vector elements.
- **Automated Text & Layout Inspection**:
  - Raw TeX Leaks: **0 leaks detected** (`math_clean: True`).
  - First-page Title Header: Single title block with title and `Anonymous Authors` metadata (duplicate title bug resolved).
  - Wide Tables: Properly styled with border-collapse and proportional padding fitting within page boundaries.
  - Figures: High-resolution trajectory plot (`trajectories_map.png`) embedded and scaled appropriately.

---

## 6. References & Text Calibration Checklist

| Item | Source / Requirement | Calibration Status |
| :--- | :--- | :--- |
| **Reflexion URL** | NeurIPS official paper page URL | Updated in `reference-verification.csv` to official hash `1b44b878bb782e6954cd888628510e90-Abstract-Conference.html`. |
| **Reflection Framework Distinction** | Differentiate generative reflection (Reflexion) from rule-based reflection (REFLECT) | Updated in Abstract and Introduction: *"Unlike embodied agent architectures relying on LLM/VLM generative reflection (e.g., Reflexion) or specific rule-based failure summarization (e.g., REFLECT), FailMem operates directly at the low-level ROS action and costmap interface..."* |
| **Bounded Metric Differences** | Restrict $<1\%$ claim to reported total distance and total duration | Updated in Abstract, Introduction, and Results: *"with $<1\%$ differences in reported total travel distance and total execution duration ($14.03\,\text{m}$ vs. $13.95\,\text{m}$ in D1; $16.25\,\text{m}$ vs. $16.40\,\text{m}$ in D2)"*. |
| **Primary Reference Sources** | All 15 BibTeX entries verified against primary publisher entries | Recorded with access dates in `paper/reference-verification.csv`. |

---

## 7. Full Test Suite Execution

Executed full test suite via `pytest tests/`:
- Total Collected Tests: 198
- Passed: 190
- XFailed: 8 (historical synthetic mock state machine tests)
- Failed: 0
- Execution Time: $2.43\,\text{s}$

```text
================== 190 passed, 8 xfailed, 1 warning in 2.43s ===================
```

---

## 8. Release Candidate Verdict

> **RELEASE CANDIDATE STATUS: ACCEPTED & FROZEN**
> 
> All delivery consistency checks, table generation pipelines, offline reproduction protections, reference verifications, and PDF vector math renderings are complete, tested, and reproducible from commit `29a2110`.
