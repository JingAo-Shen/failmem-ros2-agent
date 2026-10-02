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
| **Compiled Main PDF** | [`paper/paper.pdf`](paper.pdf) | Compiled 9-page PDF with inline vector SVG MathJax math and academic CSS styling. |
| **Supplementary Materials (Markdown)** | [`paper/supplementary.md`](supplementary.md) | Precondition rules, replay auditor algorithms, build pipeline, and parameter trace. |
| **Compiled Supplementary PDF** | [`paper/supplementary.pdf`](supplementary.pdf) | Compiled PDF of supplementary materials with vector SVG math and academic styling. |
| **Paper Positioning Brief** | [`paper/positioning.md`](positioning.md) | Strategic scope definition (Positioning B: Auditable Exploratory Comparison). |
| **Venue Shortlist Assessment** | [`paper/venue-shortlist.md`](venue-shortlist.md) | Fact-checked policy audit of 3 candidate journals (RA-L, SoftwareX, IEEE Access) and tech report path. |
| **Build Report** | [`paper/build_report.json`](build_report.json) | Tool versions, pre-build git status, post-build changes, and file SHA256 digests. |
| **Doorway Evaluator** | [`src/doorway_evaluator.py`](../src/doorway_evaluator.py) | Precondition checks and 3-valued clearance evaluation logic. |
| **Failure Memory Store** | [`src/failure_memory.py`](../src/failure_memory.py) | Event-driven failure recording and dynamic sensor invalidation. |
| **Cryptographic Replay Auditor** | [`scripts/replay_and_score_p2c.py`](../scripts/replay_and_score_p2c.py) | Independent offline replay and physical halt stability scoring. |
| **Statistical Analysis Engine** | [`scripts/analyze_p2c_results.py`](../scripts/analyze_p2c_results.py) | Aggregation script generating `episodes.csv`, `condition_summary.csv`, and `contrasts.csv`. |
| **One-Step Reproduction** | [`scripts/reproduce_offline.sh`](../scripts/reproduce_offline.sh) | End-to-end checksum verification, replay scoring, and baseline comparison. |
| **PDF Compilation Pipeline** | [`paper/scripts/build_paper_pdf.sh`](scripts/build_paper_pdf.sh) | Table injection, MathJax SVG pre-rendering, and WeasyPrint PDF compilation. |

---

## 2. Evidence Datasets & Code Versioning

To ensure scientific integrity and provenance traceability, the codebase and documentation versions are strictly distinguished across experimental and manuscript stages:

1. **Original Physical Simulation Execution Phase**:
   - **Main Comparative Benchmark (P2c, 30 runs)**: Executed under protocol v4.2 freeze in the original simulation environment (`reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/`, 271 raw files verified against `checksums.sha256`).
   - **Action-Conditioned Feasibility Trial ($H_1$, 4 runs)**: Executed under the $H_1$ exploratory protocol (`reports/evidence/p2d_h1_feasibility/`, 25 raw files across 4 physical runs).
2. **Independent Offline Reproduction Version**:
   - Executed offline on commit `e3cce9d` / `351c2de` (`reports/evidence/p2c_pilot_reproduced_20261002_142300/`), independently rescoring all trajectories and achieving exact 0 numeric diffs against baseline CSVs without running Gazebo.
3. **Current Manuscript & Policy Review Version**:
   - Tracks the 9-page internal review manuscript, supplementary material, verified venue policies, and compiled PDF deliverables.
4. **Environment & Regression Baselines**:
   - **Project Node Dependencies**: `./package.json` (`mathjax-full@3.2.2`).
   - **Python Test Suite**: `pytest tests/` (191 passed, 8 historical regression fixtures xfailed).

---

## 3. Pending Pre-Submission Items (真实待填项清单)

The following items are deferred pending internal review and target venue selection. **No information has been invented**:

1. **Official Template Adaptation**:
   - The manuscript is currently compiled as a 9-page neutral internal review draft.
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

**当前建议先完成技术报告的内部审阅；是否公开发布、选择期刊或扩展研究，由作者决定。**

### Justification:
1. **Scientific Integrity**: The manuscript strictly adheres to Positioning B (Exploratory Boundary Analysis & Negative Findings). It does not overclaim algorithmic superiority over spatial caching in static 2D geometry, acknowledges the exploratory sample size ($n=3$), reports comparable duration in D2 without speculative speed claims, and transparently documents the No-Go outcome of candidate action profiles ($H_1$).
2. **Reviewer Readability**: The abstract follows the structured "Problem–Implementation–Experiment–Results–Limitations" format. Methodological implementation details and mathematical definitions are preserved in [`paper/supplementary.md`](supplementary.md), leaving the main text concise and accessible.
3. **Technical Reproducibility**: Every number reported in the numerical result tables (Tables 2–4) is directly tied to serialized physical evidence through the cryptographic hash chain (Table 1 is a qualitative mechanism taxonomy table). The build pipeline runs deterministically with project-local dependencies.

---

## 6. 决策摘要（作者团队审阅参考）

### 1. 当前已证实的事实（Firmly Confirmed）
- **死胡同消除（D1）**：在通道受阻场景（D1）中，FailMem ($F$) 消除了无指导的重复死胡同试探（$0.0$ 次 vs $1.0$ 次），相对反应式重试基线（$R$）减少了约 $18.5\%$ 的行进距离（$14.03\,\text{m}$ vs $17.22\,\text{m}$）与 $22.3\%$ 的仿真耗时（$109.5\,\text{s}$ vs $141.0\,\text{s}$）。空间缓存基线（$O$）在 D1 中同样避免了死胡同试探（总距离 $13.95\,\text{m}$，总耗时 $108.7\,\text{s}$）。
- **动态失效避免永久绕路（D2）**：障碍移除后，基于传感器感知的动态失效使得 $F$ 恢复选择主通道，相对永久抑制基线（$M1$）减少了约 $11.0\%$ 的物理行进距离（$16.25\,\text{m}$ vs $18.25\,\text{m}$）；但平均总仿真耗时增加了约 $1.5\%$（$151.1\,\text{s}$ vs $148.8\,\text{s}$），本实验未观察到耗时收益，具体原因未经验证。
- **实验数据与审计指标分别核验情况**：
  - *文件哈希完整性*：主实验目录 271 个文件与 $H_1$ 目录 25 个文件均 $100\%$ 通过 `checksums.sha256` 完整性校验，无篡改或丢失。
  - *主实验离线回放评分（P2c，30 次运行）*：全部 10 种条件（每种 3 次运行）的离线轨迹回放均满足物理停机与稳定性判据（$|v_{\text{lin}}| \le 0.05\,\text{m/s}, |v_{\text{ang}}| \le 0.08\,\text{rad/s}$），回放审计通过率为 $30/30$（$100\%$）。
  - *动作条件可行性检查（$H_1$，4 次运行）Nav2 状态*：Nav2 局部规划器在全部 4 次运行中均返回 `SUCCEEDED`（状态码 4，通过率 4/4）。
  - *动作条件可行性检查（$H_1$，4 次运行）严格物理到达与稳定性*：严格物理到达与稳定检查通过率为 3/4；其中 `H1_aligned_run1` 运行在停机窗口内的最大角速度为 $0.1068\,\text{rad/s}$，超过了 $0.08\,\text{rad/s}$ 的静止阈值，未计入严格物理到达成功。

### 2. 当前未证实/已主动排除的事实（Unconfirmed / Disclaimed）
- **未证实 F 相对 O 的额外收益**：在当前二维静态几何布局与样本中，$F$ 与空间代价地图缓存（$O$）选择了完全相同的拓扑路径，距离与耗时差异 $<1\%$。不能据此断言普遍无效，亦未证明统计等价。
- **D2 时间差异原因未证实**：关于通过窄门与走长廊之间的速度、加减速差异，当前未采集速度轨迹分析，不作定论。
- **动作条件记忆优势未证实（H1）**：在 4 次可行性检查中，Nav2 局部规划器以 4/4 `SUCCEEDED` 通过门框膨胀层，候选场景未建立可执行性差异，已依规则停止本轮探索。
- **动态失效非 F 独占**：空间缓存基线（$O$）在观测到空闲空间后同样会更新代价地图并解除阻塞。

### 3. 现有可供审阅的交付物
- 主文手稿及 PDF：[`paper/draft.md`](draft.md) 与 [`paper/paper.pdf`](paper.pdf)（9 页中性格式内部审阅稿，尚未适配投稿模板，含 Tables 2–4 与矢量公式）。
- 附录材料及 PDF：[`paper/supplementary.md`](supplementary.md) 与 [`paper/supplementary.pdf`](supplementary.pdf)（2 页排版，含预条件、回放算法与参数映射）。
- 投稿渠道政策核验表：[`paper/venue-shortlist.md`](venue-shortlist.md)（含 RA-L、SoftwareX、IEEE Access 政策与决策对比表）。
- 完整可复现实验证据库与代码套件（191 个单元测试全部通过）。

### 4. 需作者团队决定的后续路线（保持待选）
- **路线 A（开源技术报告 / arXiv 预印本）**：以当前可审计实证基准发布，完整公开负结果与边界，无强制版面费用。
- **路线 B（Elsevier SoftwareX 软件期刊）**：需团队批准专用工程解耦工作（将算法独立打包为通用 ROS 2 软件包），并在核实官方现行政策后评估 APC 预算。
- **路线 C（IEEE RA-L 机器人期刊）**：需团队立项开展实质性实验扩展（补充真实物理机器人实验或多场景/动作故障分化基准），以应对常规同行评审中的质疑风险。
- **当前建议**：先在团队内部完成本套技术报告包的审阅；是否公开发布、选择期刊或扩展研究，由作者团队决定。
