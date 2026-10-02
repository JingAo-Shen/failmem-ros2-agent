# Publication Venue Shortlist & Assessment: FailMem

**Document Type**: Target Venue Screening & Policy Audit  
**Date**: 2026-10-02  
**Target Positioning**: Empirical Boundary Analysis & Verifiable Robotics System (Positioning B / A)  
**Policy Compliance**: All policies verified against official publisher author guides. No submissions, fees, or editorial contact executed in this stage.

---

## 1. Candidate Comparison Matrix

| Venue | Venue Type / Archival | Supported Article Types | Submission Deadline | Review Model & Page Limits | Data & Code Policy | Officially Disclosed Fees | Indexing Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. IEEE Robotics and Automation Letters (RA-L)** | Formal Archival Journal (IEEE RAS) | Letters, Systems & Empirical Evaluations, Lessons Learned | Continuous / Rolling (No fixed deadline for standalone journal submission) | Single-blind; 6 pages baseline (max 8 pages with overlength charge) | Strongly encourages open code & benchmark datasets | Free under subscription; Pages 7–8: ~$175–$220/page; Optional OA APC: ~$2,490 | SCIE, EI Compendex, Scopus (Verified) |
| **2. SoftwareX (Elsevier)** | Formal Archival Journal (Elsevier) | Original Software Publications (OSP), Research Tools | Continuous / Rolling (No fixed deadline) | Single-blind; Short structured format (~4–6 pages) | Mandatory open source repository (OSI license, GitHub/GitLab, test suite) | Gold Open Access; Mandatory APC: ~$1,100 (excluding tax) | SCIE, Scopus (Verified) |
| **3. IEEE Access (Robotics Track)** | Formal Archival Journal (IEEE) | Research Articles, Empirical Studies, System Reports | Continuous / Rolling (No fixed deadline) | Single-blind; Typically 8–12 pages (flexible) | Encouraged open data / code | Gold Open Access; Mandatory APC: $1,950 | SCIE, EI Compendex, Scopus (Verified) |

---

## 2. Detailed Venue Profiles & Reviewer Risk Analysis

### Candidate 1: IEEE Robotics and Automation Letters (RA-L)
- **Official Source**: IEEE Robotics & Automation Society Author Instructions (https://www.ieee-ras.org/publications/ra-l)
- **Topic Alignment & Scope**: Premier venue for rapid, concise peer-reviewed robotics research. Welcomes system architectures, empirical evaluations, reproducible benchmarks, and letters reporting critical empirical findings.
- **Deadlines & Schedule**: Standalone journal track accepts submissions continuously on a rolling basis. (Note: Submissions linked to ICRA/IROS conferences follow annual conference schedules; standalone RA-L does not have fixed cutoffs).
- **Format Requirements**: IEEE standard 2-column format (`IEEEtran.cls`). Length: 6 pages included in base publication; maximum 8 pages total. Single-blind review (authors and institutions disclosed).
- **Data & Code Requirements**: IEEE RAS strongly encourages reproducibility materials, links to open-source repositories, and multimedia video attachments.
- **Financial Obligations**: No mandatory page charge for papers up to 6 pages under the traditional subscription model. Pages 7 and 8 incur mandatory overlength charges. Open Access publication is completely optional.
- **Top 2 Reviewer Concerns / Likely Criticisms**:
  1. *Simulation-Only & Exploratory Sample Size*: Benchmarking was performed exclusively in Gazebo 11 simulation with $n=3$ runs per condition; lacks real-world physical TurtleBot3 hardware validation.
  2. *Lack of Demonstrated Algorithmic Superiority in 2D Static Geometry*: In the primary benchmark, FailMem ($F$) and spatial caching ($O$) chose identical routes ($<1\%$ difference in distance/time), which reviewers may criticize if framed as a novel memory algorithm rather than an empirical boundary study.

---

### Candidate 2: SoftwareX (Elsevier)
- **Official Source**: Elsevier SoftwareX Guide for Authors (https://www.elsevier.com/journals/softwarex/2352-7110/guide-for-authors)
- **Topic Alignment & Scope**: Dedicated archival journal for peer-reviewed research software across all scientific domains. Focuses on software architecture, reproducibility, code quality, and verifiable execution contracts.
- **Deadlines & Schedule**: Continuous rolling submission.
- **Format Requirements**: Structured software paper template (Software Description, Illustrative Examples, Impact). Typically 3–6 pages. Single-blind review.
- **Data & Code Requirements**: Mandatory publicly accessible repository (GitHub/GitLab) with an OSI-approved open-source license, clear installation instructions, automated testing suite, and versioned release tags.
- **Financial Obligations**: SoftwareX is a pure Gold Open Access journal. Authors must pay an Article Processing Charge (APC) of approximately $1,100 upon acceptance.
- **Top 2 Reviewer Concerns / Likely Criticisms**:
  1. *Ecosystem Generality & Packaging*: Reviewers will examine whether FailMem is packaged as a general ROS 2 navigation utility for arbitrary robots or remains coupled to the specific dual-path benchmark workspace.
  2. *Scientific Insight vs. Code Utility*: SoftwareX evaluates the software engineering contribution and usability; it gives limited weight to robotics theoretical insights or empirical negative findings.

---

### Candidate 3: IEEE Access (Robotics Track)
- **Official Source**: IEEE Access Author Information Center (https://ieeeaccess.ieee.org/)
- **Topic Alignment & Scope**: Multidisciplinary, rapid-review Open Access journal. Regularly publishes robotics systems, empirical evaluation studies, and negative/boundary results in engineering.
- **Deadlines & Schedule**: Continuous rolling submission year-round; rapid peer-review cycle (~4–6 weeks).
- **Format Requirements**: IEEE Access standard template; flexible page length (typically 8–12 pages). Single-blind review.
- **Data & Code Requirements**: Authors are encouraged to archive datasets and code.
- **Financial Obligations**: Mandatory Open Access APC of $1,950 upon acceptance.
- **Top 2 Reviewer Concerns / Likely Criticisms**:
  1. *Simulation Fidelity & Generalization Scope*: Evaluated on a single dual-path topological layout in Gazebo; lack of complex multi-room environments or hardware testing.
  2. *Cost-Effectiveness*: Requires a substantial mandatory APC ($1,950) for an exploratory study that does not present headline performance gains.

---

## 3. Recommendation & Action Plan

### Primary Recommendation: IEEE Robotics and Automation Letters (RA-L)
- **Rationale**: RA-L is the highest-impact and most respected outlet for robotics letters. Under Positioning B (Empirical Boundary Analysis), a 6-page letter accurately reporting the exact boundary conditions where episodic memory does vs. does not provide value over spatial costmaps directly addresses the ROS 2 / mobile robot community. Furthermore, publishing up to 6 pages is **free of mandatory page charges or APCs**.
- **Action Required**: Compress the current 9-page draft into a strict 6-page manuscript, moving internal audit logs, historical bug retrospectives, and extended verification checklists into an online supplementary material document.

### Secondary Backup: SoftwareX (Elsevier)
- **Rationale**: If reviewers in the robotics conference/journal ecosystem demand extensive hardware trials before considering negative findings, FailMem should be submitted to SoftwareX as an open-source, re-auditable ROS 2 failure-memory framework with cryptographic replay auditing.

*Note: Per project instructions, no submissions, fee payments, or editorial inquiries have been initiated.*
