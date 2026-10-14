# Markdown-to-LaTeX Reconciliation & Final Editorial Record

**Date**: 2026-10-14  
**Primary Submission Manuscript**: `paper/submission_source/main.tex`, `paper/submission_source/supplementary.tex`  
**Frozen Reference Baseline**: `paper/draft.md`, `paper/supplementary.md` (frozen at commit `de05246` / `5e6ed1f`)  
**Synchronization Policy**: All subsequent submission formatting, venue template migrations, and peer review revisions are conducted exclusively within `paper/submission_source/`. Root Markdown files remain strictly frozen as historical reference baselines to prevent divergent dual-track modifications.

---

## 1. Structural Mapping Matrix

| Entity in LaTeX Primary Manuscript | Source in Frozen Reference | Role & Implementation Details |
| :--- | :--- | :--- |
| `main.tex` | `paper/draft.md` frontmatter & body | Root LaTeX file (standard `article` class, 10pt, twocolumn) |
| `supplementary.tex` | `paper/supplementary.md` | Standalone supplementary material (4 pages) |
| `sections/01_introduction.tex` | `paper/draft.md` Section 1 | Introduction & 3 limited contributions |
| `sections/02_related_work.tex` | `paper/draft.md` Section 2 | Related work across 4 literature streams |
| `tables/tab1_classification.tex` | `paper/draft.md` Table 1 | Taxonomy of representations & update concepts |
| `sections/03_architecture.tex` | `paper/draft.md` Section 3 | System architecture & observation bundle formalization |
| `figures/architecture.pdf` | `paper/figures/architecture.svg` | Cropped 16:9 vector PDF diagram (720x405 pt) |
| `sections/04_experimental_setup.tex` | `paper/draft.md` Section 4 | Benchmark setup, D0–D2 scenarios, Gazebo 11 stack |
| `sections/05_results.tex` | `paper/draft.md` Section 5 | Empirical results, pairwise contrasts, H1 trial |
| `tables/tab2_condition_summary.tex` | `paper/tables/table1_condition_summary.*` | Main paper Table 2 (Condition summary across 30 runs) |
| `tables/tab3_pairwise_contrasts.tex` | `paper/tables/table2_pairwise_contrasts.*` | Main paper Table 3 (Pairwise contrasts in D1/D2) |
| `figures/trajectories_map.pdf` | `paper/figures/trajectories_map.pdf` | Physical trajectory map in Gazebo simulation runs |
| `tables/tab4_h1_feasibility.tex` | `paper/tables/table3_h1_feasibility.*` | Main paper Table 4 (H1 exploratory feasibility trial) |
| `sections/06_threats_to_validity.tex` | `paper/draft.md` Section 6 | 4 acknowledged limitations & conceptual extensions ($F2, O+$) |
| `sections/07_conclusion.tex` | `paper/draft.md` Section 7 | Conclusion & empirical stopping rationale |
| `references.bib` | `paper/references.bib` | 15 primary-source verified references with `ieeetr.bst` |
| `build.sh` & `build.log` | `paper/scripts/build_paper_pdf.sh` | Standalone compilation script & full build audit log |

---

## 2. Specific Revisions & Grounding Adjustments (Final Consistency Pass)

In this final consistency pass, the following specific technical revisions and phrasing adjustments were executed:

### 2.1 Elimination of Broad Negative Claims in Related Work
- **Spatial Mapping (Section 2.1)**:
  - *Previous*: Claimed that spatial mapping "treats unobserved areas identically and does not capture action-specific execution failures".
  - *Revised*: Rewritten neutrally to reflect actual system design: mapping representations focus on geometric occupancy and distance fields from sensor rays; because their core primitive is spatial state rather than execution history, they do not inherently index episodic action aborts or failure metadata.
- **Nav2 Execution Monitoring (Section 2.2 & Section 1)**:
  - *Previous*: Claimed that "standard recovery states are discarded upon goal termination".
  - *Revised*: Grounded with primary literature \cite{macenski2020marathon2}: Nav2's action architecture treats each dispatched navigation goal independently, and recovery routines operate within the scope of an individual goal execution.
- **LLM Reflection (Section 2.3 & Section 1)**:
  - *Previous*: Claimed that LLMs "lack physical costmap expiration semantics".
  - *Revised*: Clarified that frameworks like Reflexion \cite{shinn2023reflexion} and REFLECT \cite{liu2023reflect} target semantic task planning and verbal reflection, whereas mobile robot navigation requires grounding outcomes in metric coordinates and costmaps.
- **Table 1 Conceptual Distinction**:
  - Clarified in both text and Table 1 header that ray-clearing, graph invalidation, LLM trial reset, and perception-verified rule invalidation are distinct concepts across paradigms, rather than forcing them under a single homogeneous label.
- **Removal of Unevaluated $F2$ from Table 1**:
  - Removed `FailMem F2 (Proposed)` from Table 1 in the main text to prevent misleading side-by-side juxtaposition with implemented baselines; retained $F2$ exclusively in Section 6 as conceptual future work.

### 2.2 Text Streamlining & Numbering Clarification
- **Abstract $H_1$ Streamlining**:
  - Removed redundant duplicate clause in the Abstract; strictly retained:  
    *“Furthermore, in an exploratory 4-run feasibility trial on action-conditioned navigation ($H_1$), Nav2 returned success in 4/4 runs, with strict physical arrival verified in 3/4 runs; this candidate scenario did not establish the expected executability divergence, leading to stopping per protocol.”*
- **Supplementary Section S3 Numbering Clarification**:
  - Explicitly resolved the distinction between generated file names and main paper table numbers:
    - Generated file `table1_condition_summary` $\to$ rendered as **Table 2** in the main paper (10 condition rows);
    - Generated file `table2_pairwise_contrasts` $\to$ rendered as **Table 3** in the main paper (10 contrast rows);
    - Generated file `table3_h1_feasibility` $\to$ rendered as **Table 4** in the main paper (4 trial rows);
    - Table 1 in the main paper is the qualitative mechanism taxonomy.

### 2.3 Typography, Readability & Overfull Hbox Elimination
- **Wide Tables Typography**:
  - In `tab1_classification.tex`, `tab2_condition_summary.tex`, `tab3_pairwise_contrasts.tex`, and `tab4_h1_feasibility.tex`, replaced arbitrary `resizebox` scaling with professional `booktabs` rules, explicit column spacing (`\tabcolsep`), and multi-line stacked headers (`\shortstack`). Fonts remain at clean, readable sizes (`\small` and `\footnotesize`).
- **Equation Line Breaking**:
  - Broke long multi-variable tuples across multiple lines in Equations (1), (2), and (3) in `03_architecture.tex`, eliminating equation overflow entirely.
- **Diagram Bounding Box Optimization**:
  - Generated a tightly cropped 16:9 vector PDF (`720x405 pt`) for `architecture.pdf` from the source SVG, eliminating giant A4 white margins and enabling proportional rendering.
- **Overfull Hbox Status**:
  - **Zero overfull hboxes** across both `main.pdf` and `supplementary.pdf`.

### 2.4 Venue-Neutral Page Count & Placeholder Integrity
- **Neutral Template Page Count**:
  - The current compilation yields 7 pages for `main.pdf` and 4 pages for `supplementary.pdf`. This page count is strictly an incidental outcome of standard `article` 10pt twocolumn formatting and does not imply targeting or compliance with any specific journal/conference page limit.
- **Author & Funding Metadata**:
  - Clean placeholders (`Author One\thanks{...}`, `[Funding Grant Placeholder: #XXXX-XXXX]`) are strictly maintained without guessing real author identities or affiliations.

---

## 3. Compilation & Verification Audit Results

- **Compiler**: `pdfTeX 3.141592653-2.6-1.40.22 (TeX Live 2022/dev/Debian)` + `BibTeX 0.99d`
- **Build Script**: `paper/submission_source/build.sh`
- **Build Log**: `paper/submission_source/build.log`
- **Audit Findings**:
  - Undefined references (`?`): **0**
  - Undefined citations: **0**
  - Overfull hboxes: **0**
  - Text leakages / unrendered TeX control sequences: **0**
  - Table row counts verified:
    - Table 1 (Taxonomy): exactly 7 data rows (excluding unevaluated F2).
    - Table 2 (Condition Summary): exactly 10 data rows.
    - Table 3 (Pairwise Contrasts): exactly 10 data rows.
    - Table 4 (H1 Feasibility): exactly 4 data rows.
  - Test suite status: `pytest tests/` $\to$ **196 passed, 8 xfailed, 0 failed**.
