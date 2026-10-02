# FailMem Submission Readiness Checklist & Deliverable Index

**Document Type**: Pre-Submission Audit & Delivery Manifest  
**Date**: 2026-10-02  
**Current Milestone**: Paper Positioning & Submission Preparation  
**Overall Readiness Verdict**: **READY FOR INTERNAL REVIEW (达到“可供内部审阅”状态)**  

---

## 1. Primary Deliverable & Code Entry Points

| Item | Path / Location | Description |
| :--- | :--- | :--- |
| **Reviewer Draft (Markdown)** | [`paper/draft.md`](draft.md) | Streamlined, reviewer-facing manuscript (Problem–Implementation–Experiment–Results–Limitations). |
| **Compiled PDF Paper** | [`paper/paper.pdf`](paper.pdf) | Compiled 9-page PDF with inline vector SVG MathJax math and academic CSS styling. |
| **Supplementary Materials** | [`paper/supplementary.md`](supplementary.md) | Precondition rules, replay auditor algorithms, build pipeline, and parameter trace. |
| **Paper Positioning Brief** | [`paper/positioning.md`](positioning.md) | 2-page strategic scope definition comparing Options A, B, and C. |
| **Venue Shortlist Assessment** | [`paper/venue-shortlist.md`](venue-shortlist.md) | Comparison matrix of 3 real venues (RA-L, SoftwareX, IEEE Access). |
| **Build Report** | [`paper/build_report.json`](build_report.json) | Tool versions, pre-build git status, post-build changes, and file SHA256 digests. |
| **Doorway Evaluator** | [`src/doorway_evaluator.py`](../src/doorway_evaluator.py) | Precondition checks and 3-valued clearance evaluation logic. |
| **Failure Memory Store** | [`src/failure_memory.py`](../src/failure_memory.py) | Event-driven failure recording and dynamic sensor invalidation. |
| **Cryptographic Replay Auditor** | [`scripts/replay_and_score_p2c.py`](../scripts/replay_and_score_p2c.py) | Independent offline replay and physical halt stability scoring. |
| **Statistical Analysis Engine** | [`scripts/analyze_p2c_results.py`](../scripts/analyze_p2c_results.py) | Aggregation script generating `episodes.csv`, `condition_summary.csv`, and `contrasts.csv`. |
| **One-Step Reproduction** | [`scripts/reproduce_offline.sh`](../scripts/reproduce_offline.sh) | End-to-end checksum verification, replay scoring, and baseline comparison. |
| **PDF Compilation Pipeline** | [`paper/scripts/build_paper_pdf.sh`](scripts/build_paper_pdf.sh) | Table injection, MathJax SVG pre-rendering, and WeasyPrint PDF compilation. |

---

## 2. Evidence Datasets & Code Versioning

- **Git Branch**: `audit/r0-authenticity`
- **Frozen Source Commit SHA**: `e3cce9d94469217757e249392f9e40a6f86e23ae`
- **Baseline Raw Evidence**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/` (271 raw files verified against `checksums.sha256`).
- **Independent Reproduction Evidence**: `reports/evidence/p2c_pilot_reproduced_20261002_142300/` (reproduced 30 runs with exact 0 numeric diffs against baseline CSVs).
- **H1 Feasibility Evidence**: `reports/evidence/p2d_h1_feasibility/` (25 raw files across 4 physical runs).
- **Project Node Dependencies**: `./package.json` (`mathjax-full@3.2.2`).
- **Python Test Suite**: `pytest tests/` (191 passed, 8 historical regression fixtures xfailed).

---

## 3. Pending Pre-Submission Items (待补项清单)

The following items are deferred pending internal review and target venue selection. **No information has been invented**:

1. **Official Template Adaptation**:
   - The manuscript is currently compiled in a neutral, highly readable Markdown/HTML/PDF format.
   - Once a venue is formally selected (e.g., IEEE RA-L `IEEEtran.cls` or Elsevier `SoftwareX`), final column formatting, bibstyle, and author blocks will be styled according to that publisher's official LaTeX template.
2. **Author Names & Order**:
   - Currently formatted as `Anonymous Authors`.
   - Real author identities, contributions, and ordering must be provided by the human project leads.
3. **Institutional Affiliations**:
   - Department, laboratory, university/company names, and email addresses to be provided.
4. **Funding & Grant Acknowledgments**:
   - Grant numbers, funding agencies, and project sponsorships to be provided by the research team.
5. **Conflict of Interest / Competing Interests Statement**:
   - Formal disclosure to be signed off by authors upon journal submission.
6. **Public Open Science Repository / DOI**:
   - Code is currently tracked in the project Git repository. A public or double-blind anonymized Zenodo/Figshare archive link will be generated prior to formal submission.

---

## 4. Citation & Reference Verification Status

- **Verification Matrix**: [`paper/reference-verification.csv`](reference-verification.csv)
- **Primary Publisher Verification**: All 15 cited references have been verified against primary publisher entries (IEEE Xplore, PMLR, Science Robotics, ScienceDirect, NeurIPS) with explicit DOI/URL links and retrieval dates.
- **Unverified Entries**: **0 unverified entries**. All active references have documented primary sources.

---

## 5. Readiness Assessment & Recommendation

### Status: READY FOR INTERNAL REVIEW (可供内部审阅)

### Justification:
1. **Scientific Integrity**: The manuscript strictly adheres to Positioning B (Exploratory Boundary Analysis & Negative Findings). It does not overclaim algorithmic superiority over spatial caching in static 2D geometry, acknowledges the exploratory sample size ($n=3$), and transparently documents the No-Go outcome of candidate action profiles ($H_1$).
2. **Reviewer Readability**: The abstract follows the structured "Problem–Implementation–Experiment–Results–Limitations" format. Heavy internal audit narratives and historical regression details have been separated into [`paper/supplementary.md`](supplementary.md), leaving the main text concise and accessible.
3. **Technical Reproducibility**: Every number reported in Tables 1, 2, and 3 is directly tied to serialized physical evidence through the cryptographic hash chain. The build pipeline runs deterministically with project-local dependencies.
4. **Next Steps**: Await internal review feedback to select the final venue (Recommended: IEEE RA-L) and supply author/funding metadata before executing venue-specific template adaptation.
