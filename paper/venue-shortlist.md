# Publication Venue Shortlist & Assessment: FailMem

**Document Type**: Target Venue Screening & Policy Audit  
**Verification Date**: 2026-10-02  
**Target Positioning**: Auditable Exploratory Comparison & Verifiable Robotics Framework (Positioning B / A)  
**Policy Compliance**: All policies verified against official publisher author guides as of October 2026. No submissions, fees, or editorial inquiries have been initiated.

---

## 1. Candidate Comparison Matrix

| Venue | Publisher / Archival Status | Article Format & Review Model | Submission Deadline | Page Limits & Length Rules | Mandatory vs. Optional Fees | Data & Code Policy | Official Author Guide Source |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. IEEE Robotics and Automation Letters (RA-L)** | Formal Archival Journal (IEEE RAS) | Standard Letter; **Double-anonymous (Double-blind)** review mandatory | Continuous / Rolling (No fixed cutoff for standalone journal submissions) | 6 pages base included in publication; Maximum 8 pages total | **Subscription model: $0 mandatory fee** (≤6 pages). Overlength pages 7–8: **$175/page (mandatory)**. Optional Gold Open Access APC: **$2,490 USD + tax** | Strongly encourages open code, benchmark datasets, and multimedia video attachments | [IEEE RAS RA-L Author Guide](https://www.ieee-ras.org/publications/ra-l) (Verified 2026-10-02) |
| **2. SoftwareX (Elsevier)** | Formal Archival Journal (Elsevier) | Original Software Publication (OSP); **Single-blind** review | Continuous / Rolling | Structured 4–6 page format (Motivation, Architecture, Examples, Impact) | **Mandatory Gold OA APC: $1,100 USD** (excluding local tax upon acceptance) | **Mandatory open-source repository** (OSI-approved license, GitHub/GitLab, test suite, release tag) | [Elsevier SoftwareX Guide](https://www.elsevier.com/journals/softwarex/2352-7110/guide-for-authors) (Verified 2026-10-02) |
| **3. IEEE Access (Robotics Track)** | Formal Archival Journal (IEEE) | Regular Research Article; **Single-blind** review | Continuous / Rolling | Flexible length (typically 8–12 pages, no strict overlength fee) | **Mandatory Gold OA APC: $2,160 USD** (+ local tax upon acceptance) | Encourages Open Data and Code statements | [IEEE Access Author Center](https://ieeeaccess.ieee.org/) (Verified 2026-10-02) |
| **4. Archival Technical Report / Workshop (e.g. arXiv / ROSCon / ICRA Workshop)** | Archival Preprint / Peer-reviewed Workshop | Extended Abstract / Short Paper (2–4 pages) or Full Technical Report; Single- or Double-blind depending on call | Rolling (arXiv) / Annual Workshop cycles | Flexible (2–8 pages) | **$0 (Free)** | Fully compatible with public Git repository and cryptographic replay bundle | [arXiv Computer Science](https://arxiv.org/archive/cs) / ROSCon / IEEE RAS Workshop Calls (Verified 2026-10-02) |

---

## 2. Fact-Checked Venue Profiles & Policy Clauses

### Candidate 1: IEEE Robotics and Automation Letters (RA-L)
- **Official Policy URL**: `https://www.ieee-ras.org/publications/ra-l/information-for-authors-ra-l` (Accessed 2026-10-02)
- **Review Policy**: **Strict Double-Anonymous (Double-Blind)**. RA-L policy explicitly requires that author names, institutions, acknowledgments, and direct links to non-anonymized public repositories (e.g., personal GitHub usernames) must be removed from the initial submission PDF. Failure to anonymize triggers immediate administrative rejection.
- **Track Scope**: RA-L accepts standard Letters presenting concise, original, and significant contributions in robotics and automation. *Note*: RA-L does **not** host a dedicated "Lessons Learned" track or a specialized "Negative Results" category. Letters are evaluated against general peer-review standards of novelty, technical depth, and experimental rigor.
- **Financial Structure**:
  - Traditional subscription publishing model: **$0 mandatory fees** for manuscripts up to 6 published pages.
  - Overlength charges: Pages 7 and 8 incur a mandatory fee of **$175 per page**.
  - Gold Open Access: Authors may optionally elect Gold OA at an APC of **$2,490 USD** (plus local taxes).
- **Core Reviewer Vulnerabilities**:
  1. *Lack of Algorithmic Superiority*: FailMem ($F$) produces identical topological route choices to spatial caching ($O$) with $<1\%$ metric variation ($14.03\,\text{m}$ vs $13.95\,\text{m}$ in D1; $16.25\,\text{m}$ vs $16.40\,\text{m}$ in D2). Reviewers expecting a novel navigation algorithm outperforming standard spatial representations will assess technical novelty as insufficient.
  2. *Single-Layout Simulation Benchmark*: Experiments are conducted strictly in Gazebo 11 on a single dual-path topological layout with $n=3$ fixed-seed runs per condition, lacking multi-environment diversity or physical hardware trials.

---

### Candidate 2: SoftwareX (Elsevier)
- **Official Policy URL**: `https://www.elsevier.com/journals/softwarex/2352-7110/guide-for-authors` (Accessed 2026-10-02)
- **Review Policy**: **Single-Blind**. Author identities and affiliations are visible to reviewers.
- **Article Structure & Scope**: Publishes "Original Software Publications" (OSPs). Manuscripts must follow Elsevier’s structured software paper template:
  1. Motivation and significance
  2. Software description (architecture, software functionalities)
  3. Illustrative examples
  4. Impact and conclusions
- **Repository Requirements**: SoftwareX requires an active, publicly accessible repository (GitHub, GitLab, or Bitbucket) with:
  - An OSI-approved open-source license (e.g., Apache 2.0, MIT).
  - Versioned release tag matching the paper submission.
  - Comprehensive documentation and installation guides.
  - Executable automated test suite (e.g., CI workflow, pytest suite).
- **Financial Structure**:
  - SoftwareX is a pure Gold Open Access journal.
  - Mandatory Article Publishing Charge (APC): **$1,100 USD** (excluding local sales tax) upon acceptance.
- **Core Reviewer Vulnerabilities**:
  1. *Software Generality vs. Benchmark Coupling*: The current codebase is organized around a dual-path Gazebo evaluation runner. Reviewers will evaluate whether the failure memory module is packaged as an installable, decoupled ROS 2 library reusable across general navigation stacks, or remains tightly coupled to the benchmark harness.
  2. *Audience Fit*: SoftwareX prioritizes software utility and general reusability; empirical findings regarding costmap vs. memory boundaries are secondary to software engineering quality.

---

### Candidate 3: IEEE Access (Robotics Section)
- **Official Policy URL**: `https://ieeeaccess.ieee.org/` (Accessed 2026-10-02)
- **Review Policy**: **Single-Blind**.
- **Scope & Deadlines**: Multidisciplinary Gold Open Access journal with rolling submissions and rapid peer-review cycles (typically 4–6 weeks). Welcomes comprehensive engineering implementations and empirical system evaluations. *Note*: IEEE Access does not feature a dedicated negative results track; articles must demonstrate sound engineering methodology and practical value.
- **Financial Structure**:
  - Mandatory Gold Open Access Article Processing Charge (APC): **$2,160 USD** (plus local taxes, verified October 2026).
- **Core Reviewer Vulnerabilities**:
  1. *High Cost-to-Impact Ratio*: A mandatory charge of $2,160 USD is required for an exploratory, simulation-only study that does not establish headline performance gains.
  2. *Experimental Scale*: Reviewers frequently request multi-scenario generalization or physical robot deployments when evaluating standard journal-length engineering papers.

---

## 3. Venue Suitability Decision Table

The following decision analysis evaluates each candidate against actual project evidence, identifying structural gaps and realistic publication prospects.

| Evaluation Dimension | Candidate 1: IEEE RA-L | Candidate 2: SoftwareX | Candidate 3: IEEE Access | Recommended Path: Tech Report / Workshop |
| :--- | :--- | :--- | :--- | :--- |
| **Target Positioning Fit** | Low–Medium (Expects positive algorithmic novelty or physical robotics breakthrough) | High (Evaluates reproducible research software and verifiable tools) | Medium (Accepts broad engineering studies, but expects broader empirical scale) | **High** (Ideal for auditable exploratory comparisons, benchmarks, and negative findings) |
| **Requirements Satisfied by Current Deliverables** | 6-page draft available; strict replay auditability; empirical stopping criteria clearly documented | Comprehensive pytest suite (191 passed); complete repository; cryptographic checksums; clear architecture | Extensive tabular data; detailed methodological documentation; full reproducibility scripts | Complete offline verification bundle; transparent negative finding; zero financial overhead |
| **Fatal Review Risks / Critical Vulnerabilities** | **Very High Risk**: <br>1. Zero routing advantage of $F$ over $O$ in 2D geometry.<br>2. Single-layout simulation ($n=3$), no physical robot validation.<br>3. No dedicated negative results track in RA-L. | **Moderate Risk**: <br>Current code is structured as an experimental evaluation workspace rather than a plug-and-play ROS 2 navigation package. | **High Risk / Poor ROI**: <br>1. High mandatory APC ($2,160 USD).<br>2. Limited scientific return for a single-environment negative result. | **Low Risk**: <br>Directly meets reader expectations for exploratory studies, negative result disclosure, and benchmark methodology. |
| **Gaps Resolvable via Writing Alone** | • Anonymize manuscript for double-blind review.<br>• Reframe as empirical boundary analysis.<br>• Trim to exact 6-page limit. | • Reformat paper into SoftwareX structured 4-section OSP template. | • Expand literature review and contextual discussion. | • Package report into standard tech report or workshop short paper format. |
| **Gaps Requiring New Substantive Research / Engineering** | • Multi-environment benchmark layout suite.<br>• Physical robot hardware trials.<br>• Extension to high-dimensional 3D/action spaces where $F$ demonstrably outperforms $O$. | • Decouple `src/failure_memory.py` into a standalone, pip/colcon-installable ROS 2 package with generic action hooks. | • Substantial experimental scale expansion across varied floorplans or robots. | **None** (Current codebase, data, and draft fully support this deliverable). |
| **Financial Commitment** | **$0** (if kept within 6 pages under subscription model) | **$1,100 USD** (mandatory OA APC) | **$2,160 USD** (mandatory OA APC) | **$0** (Free open dissemination) |
| **Final Feasibility Assessment** | **High Desk / Review Rejection Probability**. Not recommended as primary submission in current form. | **Conditionally Viable**, provided 1–2 weeks of software packaging refactoring is performed. | **Not Cost-Effective**. Unfavorable cost-benefit profile. | **Primary Recommended Route**. Preserves scientific integrity and establishes open provenance immediately. |

---

## 4. Strategic Submission Decision & Roadmap

### Primary Recommendation: Archival Technical Report & Robotics Workshop Short Paper
- **Core Rationale**:
  The empirical evidence in FailMem establishes two key truths:
  1. In static 2D indoor environments, explicit episodic failure memory does **not** provide routing advantages over spatial costmap observation caching ($<1\%$ difference).
  2. Action-conditioned failure semantics ($H_1$) did not exhibit divergence in candidate narrow-aperture tests because the underlying local planner successfully cleared the margin.
  
  These are valuable negative and exploratory findings that prevent researchers from designing redundant memory architectures. However, top-tier robotics journals like IEEE RA-L evaluate submissions on technical superiority, generalizable algorithmic theorems, or extensive physical fleet evaluations. Attempting to force an exploratory $n=3$ simulation study into RA-L carries an extremely high likelihood of rejection.
  
  Disseminating this work immediately as an **archival technical report (e.g., arXiv / institutional repository)** alongside submission to a focused venue (such as **ROSCon** or an **ICRA/IROS Workshop on Failure Recovery and Benchmarking**) guarantees rapid, peer-recognized attribution with zero financial cost and complete scientific honesty.

### Secondary Journal Route: SoftwareX (Elsevier)
- **Prerequisite Engineering Work**:
  If a formal SCIE journal publication is strictly required by institutional stakeholders, **SoftwareX** represents the most plausible avenue. Rather than claiming theoretical routing superiority, the contribution is framed as an *open-source, causally bound failure memory and cryptographic replay audit framework for ROS 2 navigation*.
- **Required Tasks Before Submission**:
  1. Decouple `src/failure_memory.py` and `src/doorway_evaluator.py` from the dual-path benchmark runner into an independent ROS 2 package (`failmem_ros2`).
  2. Provide a standard `setup.py` / `CMakeLists.txt` enabling straightforward installation in arbitrary ROS 2 Humble/Iron/Jazzy workspaces.
  3. Reformat `paper/draft.md` into the SoftwareX OSP structured format (Motivation, Architecture, Examples, Impact).
  4. Allocate the mandatory $1,100 USD APC budget.
