# FailMem 论文投稿去向调研与决策备忘录 (Submission Options & Venue Verification)

**文档定位**: 依据手稿当前冻结状态（单一长廊布局、Gazebo 11 物理仿真、每条件 $n=3$ 小样本、与空间缓存基线呈中性对比、无实体真机实验、100% 离线复现流水线）开展的严格事实核查与投稿去向调研。  
**源码冻结基准**: `de05246f251263fb60a98ca3995fb8d65f38905c` (`de05246`)  
**手稿终审基准**: `5e6ed1ff3e36e19195b0fe637ce02047ee2d7fc7` (`5e6ed1f`)  
**核查日期**: 2026-10-14  

---

## 一、官方来源核查总表 (Official Source Verification Table)

为确保所有分析均有据可循，下表汇总了本轮对各候选去向官方指南与费用标准的逐项核验结果。找不到官方证据的条款一律标为**“未核实”**，严禁填入估计值。

| 目标渠道 | 官方信息来源 (URL) | 核查日期 | 核查栏目 / 章节 | 已核实官方规则摘要 | 未核实 / 未知事项 |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **IEEE RA-L** (Letters) | `https://www.ieee-ras.org/publications/ra-l/information-for-authors-ra-l` | 2026-10-14 | `Scope`, `Peer Review Model`, `Initial Submission`, `Final Submission`, `Types of Submission` | • 采用**双匿名评审 (Double-anonymous)**；<br>• 初投须使用 `ieeeconf.cls` 会议模板，录用后转 IEEE Journal 模板；<br>• 基础篇幅 6 页，上限 8 页；超页费 $175 USD/页；<br>• **严禁**将文本附录作为多媒体提交以规避 8 页上限；<br>• 官方未规定真机为硬性拒稿条款；<br>• 常年征稿，自接收至终审约 5–6 个月。 | • 会议联合投稿（RA-L with Conference Option）当前开放的具体关联会议截稿窗口（需在投稿系统实时查询）。 |
| **IEEE OA 费率** (适用于 RA-L) | `https://open.ieee.org/for-authors/article-processing-charges/` | 2026-10-14 | `Article Processing Charges` 列表 | • 混合期刊 (Hybrid journals) 自选开源 APC 为 **$2,800 USD** (2026 年执行费率，不含当地税费/VAT)；<br>• 传统订阅模式出版版面费为 **$0 USD**（1–6 页内）。 | • 特殊发展中国家减免政策在具体机构下的折扣比例（视作者所属单位而定）。 |
| **Elsevier RAS** (Journal) | `https://www.elsevier.com/journals/robotics-and-autonomous-systems/0921-8890/guide-for-authors` | 2026-10-14 | `Peer review`, `Writing and formatting`, `File format`, `LaTeX`, `Supplementary material`, `Open access` | • 采用**单匿名评审 (Single-anonymized)**；<br>• 模板要求可编辑 Word 或 LaTeX CAS 模板 (`els-cas-templates.zip`)；<br>• 允许挂载 Supplementary material（原样上线 ScienceDirect）；<br>• 混合出版：订阅模式 **$0 USD**；自选 Gold OA APC 为 **$2,940 USD** (官方页面标价，不含税)；<br>• SCIE 收录 (2025/2026 影响因子 6.0)。 | • **Short Communication 当前是否存在及字数限制未在指南中提及 (未核实)**；<br>• 常规论文的硬性页数上限未在指南中明确规定。 |
| **ICRA/IROS Workshop** | 对应大会主页及各专题研讨会 CFP 页面 | 2026-10-14 | 各专题征稿通知栏 | • **当前未找到已核实的可投 Workshop**（IROS 2026 截稿已过，ICRA 2027 Workshop 专题名单尚未公布）；<br>• 研讨会论文集是否正式收录进 IEEE Xplore 需视具体 Workshop 申请资质而定，不得自动套用主会 EI 检索。 | • 2027 年各专题的具体设立名称、截稿日、页数限制与匿名规则（均待 2027 年初官方公布）。 |
| **JOSS** (软件期刊) | `https://joss.theoj.org/about#submission_requirements` | 2026-10-14 | `Scope & submission requirements` | • 开源软件期刊，Diamond OA ($0 APC)；<br>• **硬性要求**：在投稿前必须有至少 6 个月的公开开源开发历史与发布记录。 | • 针对由私有仓库近期转公开项目的豁免审核流程（指南明确暂不支持）。 |
| **IEEE Access** | `https://ieeeaccess.ieee.org/guide-for-authors/` | 2026-10-14 | 官网访问测试 | • 官网 `guide-for-authors` 链接请求超时 (EOF)，无法访问；<br>• APC 由 `open.ieee.org` 核实为 **$2,160 USD** (Gold OA, 不含税)。 | • 具体排版规范、审稿周期与最新模板要求标为**未核实**（因官网无法连接）。 |

---

## 二、候选渠道详细核对与差距分析

### 候选一：IEEE Robotics and Automation Letters (RA-L) [对照选项]

> **定位说明**: 本选项作为传统顶级 Letters 渠道的**对照基准**进行保留，不预设为首选去向。

#### 1. 官方要求与指标核查
- **官方来源**: `https://www.ieee-ras.org/publications/ra-l/information-for-authors-ra-l` 与 `https://open.ieee.org/for-authors/article-processing-charges/`
- **核查日期**: 2026-10-14
- **出版类型与收录**: 快速发表期刊短文 (Rapid Letters)。官方收录依据：SCIE (JCR Q1/Q2)、EI Compendex、Scopus、IEEE Xplore、DBLP。
- **同行评审机制**: **双匿名评审 (Double-anonymous)**。手稿正文、图表、引用与致谢中严禁泄露作者及机构信息。
- **篇幅限制与附录规定**:
  - 基础篇幅为 **6 页**（包含所有正文、图表、表格与参考文献）；
  - 最多允许 **2 页超页**（总页数封顶 **8 页**），第 7、8 页每页收取超页费；
  - **重要限制**: 官方明确声明 **“严禁将文本附录或补充图表伪装为多媒体文件上传以规避 8 页限制，违者将直接未经评审予以形式拒稿 (Desk Reject)”**。
- **稿件格式与模板**:
  - **初投稿模板**: 必须使用 IEEE Conference 格式模板 `ieeeconf.cls`（US Letter，双栏排版，严格遵守 PaperPlaza 边距检测）；
  - **录用后终稿模板**: 录用后转换为 IEEE Journal 格式模板 (`IEEEtran.cls`) 排版。
- **出版费用**:
  - **传统订阅出版模式**: 1–6 页为 **$0 USD**；超页（第 7、8 页）每页收取 **$175 USD**（若 8 页则需缴纳 $350 USD 超页费，不含当地税费）；
  - **开放获取 (Gold Open Access)**: 若作者自愿选择开源出版，2026 年 IEEE 混合期刊 APC 统一定价为 **$2,800 USD**（不含税费，超页费另计）。
- **投稿周期**: 常年开放投稿（Year-round continuous submission），自初投至终审（Accept/Reject）通常在 5–6 个月内完成。
- **真机实验官方规则事实**: RA-L 官方作者指南中**未将实体机器人硬件实验列为硬性退稿条款**。

#### 2. 本文匹配判断与差距分析
- **格式与篇幅差距**: 本文目前终审排版为 10 页正文 + 4 页附录（共 14 页）。若投 RA-L，必须进行深度删减，将正文压减至 $\le 8$ 页以内，且现有的 4 页补充材料（S1–S5 时间账本与敏感性分析）无法作为官方出版物附录提交，只能移至第三方代码仓库。
- **评审文化与贡献风险**:
  - 尽管官方未硬性要求真机，但在审稿实务中，审稿人普遍对纯仿真（Gazebo-only）持有严格的有效性拷问，缺乏 Sim-to-Real 实物部署存在明显的同行评议阻力；
  - 本文评估基于单一长廊布局与每条件 $n=3$ 小样本，且在静态几何下 FailMem 未能超越空间缓存基线（$F$ vs. $O$ 路由差异 $<1\%$），面对追求显著正向性能提升的期刊审稿群体，存在较高的被拒风险。

#### 3. 未知与待确认事项
- 会议联合评审通道（RA-L with Conference Option）若要绑定特定大会（如 ICRA/IROS），具体截稿截止时间窗口需根据 IEEE RAS 官方当年日历单独核实。

---

### 候选二：Elsevier *Robotics and Autonomous Systems* (RAS) [常规期刊论文]

> **定位说明**: 自主机器人与系统工程领域的经典 SCIE 期刊。**在此正式撤回上轮报告中未经充分核实的“免费短文首选”结论**；经查证，该刊当前指南未声明短文规则，需按常规研究论文（Regular Paper）审视。

#### 1. 官方要求与指标核查
- **官方来源**: `https://www.elsevier.com/journals/robotics-and-autonomous-systems/0921-8890/guide-for-authors`
- **核查日期**: 2026-10-14
- **出版类型与收录**: 学术期刊论文。官方收录依据：SCIE (JCR Q2, 2025/2026 影响因子 6.0)、EI Compendex、Scopus、INSPEC、DBLP。
- **同行评审机制**: **单匿名评审 (Single-anonymized)**。审稿人匿名，作者需在首页明确提供完整的作者姓名、所属机构及通讯作者邮箱。
- **文章类型核查状态**:
  - 官方 Guide for Authors 页面**未包含 Short Communication 文章类型的具体字数上限或栏目规范**（标为**未核实**）；
  - 当前官方明确支持的标准类型为 Regular Full-Length Article（常规研究论文）及特刊征文（VSI）。
- **稿件格式与模板**:
  - 支持可编辑的 Word（单栏排版）或 LaTeX 源文件；
  - LaTeX 推荐使用 Elsevier CAS 模板套件 (`els-cas-templates.zip`)，允许双栏排版；投稿须提供完整可编译源文件。
- **补充材料规则**:
  - 官方支持上传 Supplementary Material（支持 PDF、数据文件、视频等）；
  - 补充材料将直接按原貌发布在 ScienceDirect 数据库文章主页，不经二次排版。
- **出版费用**:
  - **传统订阅出版模式**: **$0 USD**（免收任何版面费与审稿费）；
  - **金色开放获取 (Gold Open Access)**: 若作者自选开源，官方页面公示标价 APC 为 **$2,940 USD**（2025/2026 标价，不含税费）。
- **投稿周期**: 常年开放投稿（Year-round submission via Editorial Manager），无固定截稿日。

#### 2. 本文匹配判断与差距分析
- **格式与篇幅差距**: 本文当前的 10 页正文结构与章节划分（引言、相关工作、架构、协议、实测、局限、结论）与 Elsevier 常规论文规范高度契合；现有的 4 页附录（S1–S5）可直接作为官方 Supplementary PDF 随稿提交，无需删减数学证明与时间账本。
- **贡献与方法学风险**:
  - 由于未核实到短文通道，若按常规研究长文（Regular Paper）提交，审稿人通常期望具有更广泛的实验广度（例如多个不同拓扑场景、更大样本量统计、或更丰富的动态扰动分析）；
  - 本文严格限定在单一长廊布局与 $n=3$ 小样本，作为长文提交可能面临“实验规模偏小、结论偏探索性”的质询。

#### 3. 未知与待确认事项
- 编辑部当前是否仍在后台系统接受短篇通讯（Short Communication），需通过投审稿系统（Editorial Manager）实际新建稿件下拉菜单核查；
- 常规研究论文的建议字数与图表数量上限未在公开指南中硬性限定。

---

### 候选三：专题研讨会 (ICRA/IROS Workshop) 核查结果

> **定位说明**: 依据规程，严格核实具体开放状态，杜绝以泛称占据正式候选名额。

#### 1. 官方核查事实
- **核查日期**: 2026-10-14
- **核查结论**: **当前未找到已核实的可投 Workshop**。
- **具体核查事实与周期分析**:
  1. **IROS 2026**: 会议已于 2026 年秋季举办，所有研讨会征稿早于 2026 年夏季截止并已结会；
  2. **ICRA 2027**: 主会目前处于前期组织阶段，专题研讨会（Workshop Proposals）审批与入选名单尚未完成公示；各具体专题的独立征稿通知（CFP）、截稿日期、具体页数（4页或6页）及评审规则通常在 **2027 年 1 月至 2 月** 才会陆续开通；
  3. **检索与收录事实判定**: 研讨会论文（Workshop Papers）通常分为正式纳入 IEEE Xplore 论文集出版与非正式交流（Non-archival / arXiv / OpenReview）两种情况。**严禁将 IEEE ICRA/IROS 主会的 EI 检索直接套用到所有附属 Workshop**。研讨会短文能否被单位或学校认可为正式学术成果，存在制度差异。

#### 2. 应对建议
- 暂不以虚构的 Workshop 名称作为正式投稿候选；
- 建议作者团队在 **2027 年 1 月** 关注 ICRA 2027 官方发布的研讨会列表（重点关注机器人基准测试 Benchmarking、可复现性 Reproducibility 或负面结果专题），届时依据具体的官方 CFP 规则决定是否投送。

---

### 其他探索性与软件渠道核查说明 (JOSS / IEEE Access)

为响应“寻找适合探索性比较、系统实践或边界结果渠道”的要求，对以下两个渠道进行了针对性核实：

1. **JOSS (Journal of Open Source Software)**:
   - **官方规则**: 免费开源软件期刊（$0 APC），Scopus/Crossref 收录；
   - **不匹配事实**: 官方明确要求项目在投稿前需有**至少 6 个月的公开开源开发历史（public history）**；本项目此前处于开发演进与冻结期，不满足 6 个月公开历史的硬性门槛，目前无法投稿。
2. **IEEE Access**:
   - **官方规则**: SCIE Q2 开放获取期刊，征稿范围涵盖系统与仿真工程实践；由 `open.ieee.org` 确认为 Gold OA，APC 为 **$2,160 USD**（不含税）；
   - **核查受阻说明**: 本轮尝试访问其官方投稿指南页面（`https://ieeeaccess.ieee.org/guide-for-authors/`）遭遇网络连接超时 (EOF)，具体排版与审稿规范无法从原始页面核验，故**依规不作为正式候选列入**。

---

## 三、一页决策表：正式发表 vs. 同行交流 (Decision Matrix)

本决策表旨在清晰区分两种不同导向的发表路径，供作者团队结合考核需求、成果认定标准及预算进行权衡决策：

| 决策考量维度 | 路径 A：正式期刊学术发表 (Formal Journal Publication)<br>*[对应候选：Elsevier RAS 或 IEEE RA-L]* | 路径 B：同行交流与预印本首发 (Peer Exchange / Workshop)<br>*[对应方向：待 2027 年初公布的 ICRA Workshop 或 arXiv]* |
| :--- | :--- | :--- |
| **出版属性与正式性** | **正式出版物 (Formal Archival Journal)**，具有正式卷期、页码与期刊 DOI。 | **非正式交流或会议研讨会 (Workshop / Non-archival)**，部分仅在官网或 arXiv 存档。 |
| **官方学术检索认定** | 确保进入 **SCIE、EI Compendex、Scopus** 核心库检索。能满足大部分高校与科研机构的毕业/职称量化考核。 | **不保证 EI / SCI 检索**。通常仅被 Google Scholar 或 DBLP 收录；需作者提前确认所在机构对 Workshop 的认定政策。 |
| **时间可行性与周期** | **常年可投**。但初审通常需 2–5 个月，修改复审约 1–3 个月，见刊周期相对较长。 | **受固定会议日历约束**。需等待 2027 年 1–2 月 ICRA 2027 Workshop CFP 公布，评审周期通常较短（约 3–4 周）。 |
| **手稿篇幅与格式差距** | • **Elsevier RAS**: 格式差距小，10 页正文 + 4 页附录可完整作为正文与官方 Supplementary 保留；<br>• **IEEE RA-L**: 格式差距大，必须由 14 页大幅删减压缩至 $\le 8$ 页，附录须转移至外链。 | • 篇幅差距较大：通常要求 4–6 页双栏短文，必须高度精炼，删减大部分实现细节，只保留核心中性对比图表。 |
| **学术主张与贡献风险** | **存在一定审查风险**：审稿人可能对单一布局、小样本（$n=3$）及中性结论提出质疑，或要求补充实物硬件对比。 | **审查风险相对较低**：研讨会审稿人普遍对阴性/中性结果、系统可复现性与工程账本持开放讨论态度。 |
| **费用支出 (APC / 注册费)** | • 若选传统订阅模式：**$0 USD**（免费出版）；<br>• 若选 Gold OA：需支付 $2,800–$2,940 USD APC。 | 出版费通常为 **$0 USD**，但通常要求至少一位作者注册线下或线上会议（注册费依大会定价）。 |
| **推荐适用场景** | 适用于**必须产出具备正规 SCIE/EI 检索记录的期刊成果**，且愿意承受长周期同行评审的学术场景。 | 适用于**优先追求研究理念传播、同行交流探讨、且不急于计入毕业或考核指标**的学术场景。 |

---

## 四、建议后续行动路线

1. **第一步（作者团队决策目标类型）**:
   - 作者团队审议上述一页决策表，确认是否需要正式 SCIE 期刊检索，还是倾向于等待 2027 年初的专业 Workshop。
2. **第二步（模板适配与格式转换）**:
   - 若作者选定 **Elsevier RAS**：将当前 Markdown/HTML 手稿排版适配转换为 Elsevier CAS LaTeX 模板，将 4 页附录整理为独立的 Supplementary Material PDF；
   - 若作者选定 **IEEE RA-L**：启动精简压缩，将正文压缩至 6–8 页双栏，附录转为仓库链接，并评估是否需要筹备实物演示视频；
   - 若作者决定等待 **ICRA 2027 Workshop**：保持手稿冻结，设置提醒于 2027 年 1 月中旬检索 ICRA 2027 获批 Workshop 名单。
