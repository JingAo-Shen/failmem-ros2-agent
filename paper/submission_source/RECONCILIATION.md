# Markdown-to-LaTeX Reconciliation Record

**Date**: 2026-10-14  
**Source Baseline**: Frozen Markdown manuscript (`paper/draft.md`, `paper/supplementary.md`) at commit `893946d`  
**Target Architecture**: Venue-neutral standalone LaTeX submission source (`paper/submission_source/`)  

---

## 1. Structural Mapping Matrix

| Source Markdown Element | Target LaTeX Source File | Compiled Entity in PDF |
| :--- | :--- | :--- |
| `paper/draft.md` Frontmatter & Abstract | `main.tex` | Title, Abstract, Author/Affiliation Placeholders |
| `paper/draft.md` Section 1 | `sections/01_introduction.tex` | Section 1: Introduction |
| `paper/draft.md` Section 2 | `sections/02_related_work.tex` | Section 2: Related Work & Mechanism Taxonomy |
| `paper/draft.md` Table 1 | `tables/tab1_classification.tex` | Table 1: Classification & Taxonomy |
| `paper/draft.md` Section 3 & Figure 1 | `sections/03_architecture.tex`, `figures/architecture.pdf` | Section 3: The FailMem Architecture, Figure 1 |
| `paper/draft.md` Section 4 | `sections/04_experimental_setup.tex` | Section 4: Experimental Setup & Benchmarking Protocol |
| `paper/draft.md` Section 5.1 & Table 2 | `sections/05_results.tex`, `tables/tab2_condition_summary.tex` | Section 5.1, Table 2: Condition Summary |
| `paper/draft.md` Section 5.2, Table 3 & Figure 2 | `sections/05_results.tex`, `tables/tab3_pairwise_contrasts.tex`, `figures/trajectories_map.pdf` | Section 5.2, Table 3: Contrasts, Figure 2 |
| `paper/draft.md` Section 5.3 & Table 4 | `sections/05_results.tex`, `tables/tab4_h1_feasibility.tex` | Section 5.3, Table 4: H1 Feasibility |
| `paper/draft.md` Section 6 | `sections/06_threats_to_validity.tex` | Section 6: Threats to Validity & Limitations |
| `paper/draft.md` Section 7 | `sections/07_conclusion.tex` | Section 7: Conclusion |
| `paper/references.bib` | `references.bib`, `ieeetr.bst` | References (15 primary-source citations) |
| `paper/supplementary.md` Sections S1–S5 | `supplementary.tex` | Supplementary Document (4 pages standalone PDF) |

---

## 2. Text Harmonization & Precision Adjustments

During migration from Markdown to LaTeX, the following precision adjustments were executed across all source files (`paper/draft.md`, `paper/supplementary.md`, `paper_summary_zh.md`, and `paper/submission_source/`):

1. **Standardized $H_1$ Feasibility Phrasing**:
   - *Previous informal phrasing*: Stated that all commanded orientation actions traversed the passage without differentiation.
   - *Standardized phrasing*: Strict adherence to:  
     `Nav2 returned success in 4/4 runs, with strict physical arrival verified in 3/4 runs; the candidate scenario did not establish the expected executability divergence.`
   - *Chinese counterpart*: `“Nav2返回成功4/4，严格物理到达验证3/4；该候选场景未建立预期可执行性差异。”`
2. **Explicit Gazebo Simulation Nomenclature**:
   - Replaced all ambiguous mentions of "30 physical runs" with "30 Gazebo simulation runs" (`30 轮 Gazebo 仿真运行`) across the title abstract, Section 4, Section 5, and supplementary documents. This prevents any misinterpretation of simulation data as physical hardware experiments.
3. **Rigorous $F$ vs. $O$ Capability Boundary Scope**:
   - Added explicit qualification:  
     `"Within the evaluated static 2D hallway layout, specific implementation, and run sample (n=3), no additional routing benefit of FailMem over spatial caching was observed; this does not imply general lack of benefit across arbitrary domains or statistical equivalence."`
4. **D2 Trajectory Duration & Distance Ledger**:
   - Explicitly highlighted that while travel distance was reduced by $\approx 11.0\%$ ($-2.00\,\text{m}$ relative to $M1$), full-episode duration showed no observed improvement ($+2.27\,\text{s}$ sample mean difference), which was predominantly accrued during pre-dispatch history exploration ($+2.47\,\text{s}$). Kinematic decomposition is documented strictly as observational latencies without asserting invariant physical mechanisms.
5. **Literature Citations in Mechanism Taxonomy**:
   - Added direct literature citations for every row in Table 1 (Costmap2D \cite{lu2014layered}, OctoMap \cite{hornung2013octomap}, Voxblox \cite{oleynikova2017voxblox}, E-Graphs \cite{phillips2012egraphs}, Reflexion \cite{shinn2023reflexion}, REFLECT \cite{liu2023reflect}). Invalidation triggers specify exact literature mechanisms without unsupported baseline-weakening claims.
6. **Venue-Neutral Metadata & Funding Placeholders**:
   - Generic placeholders are provided for authors, affiliations, and grant numbers in `main.tex` and `supplementary.tex`, ready for author completion upon target venue selection.

---

## 3. Build & Compilation Verification

- **Build Script**: `paper/submission_source/build.sh`
- **Compiler**: `pdfTeX 3.141592653-2.6-1.40.22 (TeX Live 2022/dev/Debian)` + `BibTeX 0.99d`
- **Verification Results**:
  - `main.pdf`: 8 pages, 321 KB, 0 undefined citations or references (`?`), clean vector graphics.
  - `supplementary.pdf`: 4 pages, 211 KB, 0 undefined citations or references (`?`), all ledger tables rendered.
