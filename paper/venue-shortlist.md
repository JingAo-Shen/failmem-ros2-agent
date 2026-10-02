# Publication Venue Shortlist & Assessment: FailMem

**Document Type**: Target Venue Screening & Policy Audit  
**Verification Date**: 2026-10-02  
**Target Positioning**: Auditable Exploratory Comparison (Positioning B)  
**Policy Audit Status**: Documented policies are cross-referenced with official publisher author guidelines as of October 2026; unverified details are explicitly marked "待核实". No formal submissions, fee payments, or editorial inquiries have been initiated.

---

## 1. Formal Candidate Comparison Matrix

The candidate list for formal submission is strictly limited to three journals:

| Venue | Publisher / Archival Status | Article Format & Review Model | Submission Deadline | Page Limits & Length Rules | Mandatory vs. Optional Fees | Data & Code Policy | Official Author Guide Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. IEEE Robotics and Automation Letters (RA-L)** | Formal Archival Journal (IEEE RAS) | Standard Letter; **Double-anonymous (Double-blind)** review mandatory | Continuous / Rolling (No fixed cutoff for standalone journal submissions) | 6 pages base included in publication; Maximum 8 pages total | **Subscription model: $0 mandatory fee** (≤6 pages). Overlength pages 7–8: **$175/page (mandatory)**. Optional Gold Open Access APC: **$2,490 USD + tax** | Strongly encourages open code, benchmark datasets, and multimedia video attachments | [IEEE RAS RA-L Author Guide](https://www.ieee-ras.org/publications/ra-l/information-for-authors-ra-l) |
| **2. SoftwareX (Elsevier)** *(备选：需另行批准工程扩展)* | Formal Archival Journal (Elsevier) | Original Software Publication (OSP); **Single-blind** review | Continuous / Rolling | Structured 4–6 page format (Motivation, Architecture, Examples, Impact) | **Mandatory Gold OA APC: $1,100 USD** (excluding local tax upon acceptance) | **Mandatory open-source repository** (OSI-approved license, GitHub/GitLab, test suite, release tag) | [Elsevier SoftwareX Guide](https://www.elsevier.com/journals/softwarex/2352-7110/guide-for-authors) |
| **3. IEEE Access (Robotics Track)** | Formal Archival Journal (IEEE) | Regular Research Article; **Single-blind** review | Continuous / Rolling | Flexible length (typically 8–12 pages, no strict overlength fee) | **Mandatory Gold OA APC: $2,160 USD** (+ local tax upon acceptance) | Encourages Open Data and Code statements | [IEEE Access Author Center](https://ieeeaccess.ieee.org/) |

---

## 2. Fact-Checked Venue Profiles & Policy Clauses

### Candidate 1: IEEE Robotics and Automation Letters (RA-L)
- **Official Policy URL**: [`https://www.ieee-ras.org/publications/ra-l/information-for-authors-ra-l`](https://www.ieee-ras.org/publications/ra-l/information-for-authors-ra-l)
- **Review Policy**: **Strict Double-Anonymous (Double-Blind)**. RA-L guidelines require that author names, institutions, acknowledgments, and non-anonymized repository links be omitted from the initial submission PDF.
- **Track Scope**: Accepts standard Letters presenting concise, original contributions in robotics and automation. RA-L does **not** host a dedicated "Lessons Learned" track or a "Negative Results" category.
- **Financial Structure**:
  - Traditional subscription publishing model: **$0 mandatory fees** for manuscripts up to 6 published pages.
  - Overlength charges: Pages 7 and 8 incur a mandatory fee of **$175 per page**.
  - Gold Open Access: Optional APC of **$2,490 USD** (plus local taxes).
- **Distinction Between Official Requirements and Project Fit**:
  - *Official Requirements*: RA-L author guidelines do **not** formally mandate physical hardware trials or algorithmic superiority proofs as submission prerequisites.
  - *Project Suitability Assessment*: In standard peer review, reviewers evaluate technical contribution and experimental validation. In our study, FailMem ($F$) achieved identical topological route selection to spatial caching ($O$) in static 2D geometry ($<1\%$ metric difference), evaluated in simulation on a single dual-path layout with $n=3$. Without hardware trials or demonstrated routing superiority, there is substantial risk that reviewers may evaluate the empirical findings as insufficient for an RA-L Letter.

---

### Candidate 2: SoftwareX (Elsevier) — 备选（需另行批准工程扩展）
- **Official Policy URL**: [`https://www.elsevier.com/journals/softwarex/2352-7110/guide-for-authors`](https://www.elsevier.com/journals/softwarex/2352-7110/guide-for-authors)
- **Review Policy**: **Single-Blind**. Author identities and affiliations are visible to reviewers.
- **Article Structure & Scope**: Publishes "Original Software Publications" (OSPs) using a structured template: Motivation and significance, Software description, Illustrative examples, Impact.
- **Repository Requirements**: Requires an active, publicly accessible repository with an OSI-approved license, automated test suite, documentation, and a versioned release tag.
- **Financial Structure**: Mandatory Gold Open Access APC of **$1,100 USD** (excluding tax) upon acceptance.
- **Scope & Project Fit**:
  - Evaluates software engineering quality, reproducibility, and general reusability across the research community.
  - *Current Status*: Retained strictly as a conditional backup requiring separate project authorization. The current codebase was implemented and tested on ROS 2 Humble as a dual-path evaluation benchmark. Decoupling into an independent, general-purpose ROS 2 package and verifying compatibility across other distributions is not part of the current milestone and would require dedicated engineering approval.

---

### Candidate 3: IEEE Access (Robotics Track)
- **Official Policy URL**: [`https://ieeeaccess.ieee.org/`](https://ieeeaccess.ieee.org/)
- **Review Policy**: **Single-Blind**.
- **Scope & Deadlines**: Broad multidisciplinary Open Access journal with rolling submissions and rapid review cycles. Does not have a dedicated negative results track.
- **Financial Structure**: Mandatory Gold Open Access APC of **$2,160 USD** (plus local taxes, verified October 2026).
- **Project Fit Assessment**:
  - The mandatory APC ($2,160 USD) represents a substantial financial commitment. Given that the current study is an exploratory simulation benchmark showing comparable routing between $F$ and $O$, the cost-benefit ratio of this route is considered unfavorable.

---

## 3. Non-Journal Archival & Dissemination Paths

### Path A: Internal Review & Open Technical Report / Preprint (e.g., arXiv / Institutional Repository)
- **Characteristics**: Archival dissemination without peer-review overhead.
- **Cost**: **$0 (Free)**.
- **Fit**: Completely transparent venue for establishing provenance of exploratory benchmark results, negative findings, and cryptographic replay datasets without requiring novel algorithmic superiority or physical fleet experiments.

### Path B: Peer-Reviewed Workshops & Conferences (e.g., ROSCon / ICRA/IROS Workshops)
- **Current Status**: **未列入即时投稿目标**。
- **Rationale**: Specific upcoming workshop editions or conference tracks with published, active Calls for Papers (CFPs) matching this work have not been identified or verified in the current workspace. If a suitable CFP specifically targeting robotic failure recovery, reproducibility, or benchmarking is identified in the future, it can be evaluated as an independent target.

---

## 4. Venue Suitability Decision Table

| Evaluation Dimension | Candidate 1: IEEE RA-L | Candidate 2: SoftwareX (备选) | Candidate 3: IEEE Access | Dissemination Path: Tech Report / Preprint |
| :--- | :--- | :--- | :--- | :--- |
| **Official Scope** | Concise, significant letters in robotics and automation | Peer-reviewed original research software and tools | Broad multidisciplinary engineering research | Archival technical reports and preprints |
| **Requirements Satisfied by Current Deliverables** | 6-page draft available; strict replay auditability; empirical stopping criteria clearly documented | Comprehensive pytest suite (191 passed); complete repository; cryptographic checksums | Extensive tabular data; detailed methodological documentation; full reproducibility scripts | Complete offline verification bundle; transparent negative finding; zero financial overhead |
| **Project Review Vulnerabilities** | Evaluated on single-layout simulation ($n=3$); route selection identical to spatial cache ($O$); no hardware trials | Current code is organized as a benchmark harness rather than a decoupled generic ROS 2 package | High mandatory APC ($2,160 USD) for an exploratory single-scenario simulation finding | Non-peer-reviewed (does not count as formal journal publication) |
| **Gaps Resolvable via Writing Alone** | • Anonymize manuscript for double-blind review.<br>• Reframe as empirical boundary analysis.<br>• Trim to exact 6-page limit. | • Reformat paper into SoftwareX structured 4-section OSP template. | • Expand literature review and contextual discussion. | • Package manuscript into technical report format. |
| **Gaps Requiring Substantive Engineering / Research** | • Multi-environment benchmark layout suite.<br>• Physical robot hardware trials.<br>• Higher-dimensional action spaces demonstrating divergence. | • Decouple `src/failure_memory.py` into a standalone, general ROS 2 package.<br>• Package testing and documentation. | • Substantial experimental expansion across varied floorplans or robots. | **None** (Current codebase, data, and draft fully support this deliverable). |
| **Mandatory Financial Commitment** | **$0** (if kept within 6 pages under subscription model) | **$1,100 USD** (mandatory OA APC) | **$2,160 USD** (mandatory OA APC) | **$0** (Free open dissemination) |
| **Feasibility & Recommendation Status** | **Review Risk High**. Not recommended for immediate submission without experimental expansion. | **Conditionally Viable**, requiring separate authorization for package decoupling. | **Not Cost-Effective**. Unfavorable cost-benefit profile. | **Recommended Immediate Step**. Serves as the baseline for internal review. |

---

## 5. Strategic Summary

1. **Immediate Step**: Complete internal review of the technical report / manuscript bundle.
2. **Subsequent Dissemination Choice**:
   - If the goal is rapid, zero-cost dissemination of reproducible negative/exploratory findings, an **archival technical report / preprint** is the most direct path.
   - If a peer-reviewed publication is required:
     - **SoftwareX** is the primary journal candidate, provided that project leadership approves a dedicated engineering phase to decouple and package the software.
     - Formal submission to **IEEE RA-L** should only be pursued if the team decides to expand the experimental scope (e.g., physical robot trials or multi-environment layouts).
     - Workshops/ROSCon remain conditional on identifying an active, officially verified CFP.
