# FailMem 论文投稿去向调研与决策备忘录 (Candidate Submission Options)

**文档定位**: 依据手稿当前真实定位（单一几何环境、Gazebo 11 仿真、每条件 $n=3$ 小样本、与 Spatial Cache $O$ 中性对比、无实体真机实验、100% 离线复现流水线）筛选的最多 3 个精准匹配去向，涵盖顶级 Letters、专题研讨会与自主系统期刊。  
**冻结源码与手稿基准**: 源码冻结 `de05246`，手稿终审 `5e6ed1f`  
**整理时间**: 2026-10-14  

---

## 核心去向横向对比总表

| 评估维度 | 选项一：IEEE RA-L (Letters) | 选项二：IEEE ICRA/IROS Workshop (负面/中性结果专题) | 选项三：Elsevier RAS (Short Communication) |
| :--- | :--- | :--- | :--- |
| **全称** | IEEE Robotics and Automation Letters | IEEE ICRA/IROS Workshop on Benchmarking & Negative/Neutral Results | Robotics and Autonomous Systems (Elsevier) |
| **出版类型** | 顶级混合期刊 (Rapid Letters) | 国际顶级会议专题研讨会短文 (Workshop Paper) | 知名机器人学术期刊 (Short Communication) |
| **官方收录依据** | SCIE (JCR Q1/Q2), EI, Scopus, IEEE Xplore | IEEE Xplore / EI (若含正式论文集) 或 arXiv/DBLP | SCIE (JCR Q2), EI Compendex, Scopus, DBLP |
| **征稿状态/周期** | 常年开放投稿 (Year-round rolling) | 周期性 (ICRA: 1-3月截稿; IROS: 6-8月截稿) | 常年开放投稿 (Year-round rolling) |
| **基础篇幅限制** | 6 页 IEEE 双栏 (含正文、图表与文献) | 4–6 页 IEEE 双栏 (短文 / 扩展摘要) | ~6,000 词或 8–10 期刊页 |
| **超页与补充规则** | 最多超 2 页 (上限 8 页, $175/页); **严禁文本附录** | 参考文献通常不计入或灵活; 附录可挂链接 | 允许在 ScienceDirect 官方挂载多页 Supplementary PDF |
| **版面费 / APC** | 1–6页免费; 超页 $175/页; OA 可选 (~$2,495) | **$0 APC** (仅需注册会议/研讨会) | **$0 APC** (传统订阅免费); OA 可选 (~$3,200) |
| **对中性/负面结论包容度** | 低 (审稿人强烈偏好增量显著优势与真机) | **极高** (专题研讨会核心宗旨即为负向/探索性边界) | 中等 (接受系统实践、边界剖析与基准对比) |
| **真机实验硬性要求** | 极高 (审稿人常因无真机直接拒稿) | 无 (明确接受纯物理仿真与架构评测) | 中等 (仿真基准可被接受，但需详述环境机理) |
| **录用风险评级** | **极高风险 (High Risk)** | **极低风险 (Low Risk)** | **中等风险 (Moderate Risk)** |

---

## 选项一：IEEE Robotics and Automation Letters (RA-L)

### 1. 官方要求与指标
- **征稿范围 (Scope)**: 快速发表机器人与自动化领域具有创新思想和应用价值的同行评审短文（Letters）。涵盖理论突破、系统设计与工程应用案例。
- **当前状态**: 常年开放投稿（Year-round continuous submission），无固定截止日期；投稿至终审周期通常为 6 个月。
- **篇幅限制 (Page Limit)**:
  - 基础篇幅为 **6 页**（IEEE 双栏格式，包含正文、所有图表和参考文献）。
  - 最多允许 **2 页超页**（总页数不得超过 **8 页**），超页部分需缴纳强制超页费（$175 美元/页）。
- **补充材料规则 (Supplementary Material)**:
  - **重要约束**: 官方明确规定 **“严禁将文本附录或补充图表伪装为多媒体文件上传以规避 8 页限制，违者将直接 Desk Reject”**。
  - 仅允许上传多媒体附件（如演示视频，MP4 格式）或在正文中提供代码/数据仓库的只读链接。
- **格式模板**: 标准 `IEEEtran.cls`（双栏，Letters/Journal 格式）或 PaperPlaza 格式。
- **版面费 / APC**:
  - 1–6 页完全免费；
  - 7–8 页收取超页费 $175/页（若 8 页则需 $350 美元）；
  - 混合期刊（Hybrid），若作者自愿选择开源（Gold Open Access），需支付约 $2,495 美元 APC。
- **官方收录依据**: SCIE、EI Compendex、Scopus、IEEE Xplore、DBLP。

### 2. 匹配理由与学术价值
- 国际机器人领域公认的高水平学术期刊，同行关注度高；
- 紧密贴合 ROS 2 机器人软件生态与导航架构。

### 3. 贡献点风险分析 (Critical Risks)
- **真机实验缺失**: RA-L 审稿群体通常对纯仿真（Gazebo-only）持有审慎态度，常以“缺乏 Sim-to-Real 实体机器人部署”为由给出负面意见；
- **样本量与泛化性局限**: 本文仅在单一长廊布局下完成每条件 $n=3$ 的探索性小样本测试，极易受到关于“统计显著性不足”或“场景过于简单”的质疑；
- **中性结论的发表阻力**: 在静态几何下 FailMem 未能显著优于 Spatial Cache（$F$ vs. $O$ 路由差异 $<1\%$），尽管科学事实诚实，但在传统期刊追求“超越 SOTA”的评审文化中难以获得高分；
- **版面强制压缩**: 当前手稿为 10 页正文 + 4 页附录，若投 RA-L 必须将 14 页内容强力压缩至 6–8 页，且无法保留独立出版的附录。

### 4. 所需补充材料与应对准备
- 需由人类作者团队决策是否补充实体轮式机器人长廊部署视频；
- 若按当前仿真成果提交，需在 Cover Letter 中明确强调“探索性可复现基准研究（Exploratory Benchmarking Study）”；
- 需精简正文排版，将补充材料（S1–S5）转移至 GitHub/Zenodo 外部链接。

---

## 选项二：IEEE ICRA / IROS 专题研讨会 (Workshop on Benchmarking, Reproducibility & Negative Results)

*(例如：ICRA/IROS Workshop on Benchmarking and Reproducibility in Robotics / Workshop on Negative Results in Embodied AI)*

### 1. 官方要求与指标
- **征稿范围 (Scope)**: 专门征集机器人系统实践中的负向/中性结果（Negative & Neutral Results）、失败案例剖析、可复现基准测试工具链以及针对现有范式边界的挑战性实证。
- **当前状态**: 周期性征稿（Annual cycles）。
  - **ICRA Workshop**: 每年 1–3 月投稿截止，5 月随大会举办；
  - **IROS Workshop**: 每年 6–8 月投稿截止，10 月随大会举办。
- **篇幅限制 (Page Limit)**:
  - 通常要求 **4 至 6 页**（IEEE 双栏 Conference 格式），部分研讨会允许参考文献不占页数。
- **补充材料规则**: 鼓励提供完整的复现脚本、Docker 镜像与数据链接，附录可作为补充文件或在线材料一并提交。
- **格式模板**: 标准 IEEE Conference LaTeX 模板 (`\documentclass[conference]{IEEEtran}`)。
- **版面费 / APC**: **$0 美元**（研讨会本身不收取论文出版处理费，只需一位作者注册会议/研讨会门票）。
- **官方收录依据**:
  - 若为 IEEE 官方联合出版的 Workshop 论文集，收录于 IEEE Xplore、EI Compendex、Scopus；
  - 若为交流性质的 Non-archival Workshop，论文存档于 arXiv / OpenReview / 研讨会官方网站，被 Google Scholar 和 DBLP 检索。

### 2. 匹配理由与学术价值
- **最高契合度 (Best Match)**: 研讨会的核心宗旨与 FailMem 当前的学术定位完全一致——诚实报告中性边界（在静态几何下事件记忆不优于空间缓存）、公开 100% 离线复现流水线、剖析 D2 轨迹时间账本；
- **同行评审友好**: 研讨会审稿人高度重视研究的可审计性与实证透明度，不会因为“没有跑赢基线”或“缺乏真机”而拒稿，反而会赞赏细致的停定判定准则与代数闭合分析；
- **交流与后续拓展契机**: 能在国际顶级会议现场与机器人自主导航和基准测试学者直接交流，为后续多房间布局与动作画像研究奠定学术声誉。

### 3. 贡献点风险分析
- **学术成果认定风险**: 研讨会短文（Workshop Paper）在部分学术考核体系中的评价权重低于常规期刊长文；作者团队需根据考核需求进行权衡。

### 4. 所需补充材料
- 将 10 页手稿聚焦并浓缩为 4–6 页的精炼版本（重点突出中性实测发现、账本分解与开源复现流水线）；
- 附上 Zenodo DOI 归档与 GitHub 代码库链接。

---

## 选项三：Elsevier *Robotics and Autonomous Systems* (RAS)

### 1. 官方要求与指标
- **征稿范围 (Scope)**: 涵盖自主机器人系统、软件体系结构、移动机器人导航、环境表征与空间记忆、高置信度物理仿真评测等。官方设有 **Short Communications** 专栏，欢迎针对现有机器人算法与系统的实证比较与探索性实验报告。
- **当前状态**: 常年开放投稿（Year-round continuous submission via Editorial Manager），无固定截稿日。
- **篇幅限制 (Page Limit)**:
  - **Short Communications**: 推荐字数约 5,000–6,000 词以内（相当于期刊排版后约 8–10 页）；
  - **Regular Articles**: 篇幅无严格上限（通常 12–18 页）；
- **补充材料规则**:
  - **支持官方挂载**: Elsevier ScienceDirect 平台完全支持作者上传多页 Supplementary Material（PDF、数据 CSV、多媒体视频），将与正文同享正式 DOI 并在文章主页供读者下载。本研究现有的 4 页附录（S1–S5）无需删减，可直接作为官方 Supplementary PDF 提交。
- **格式模板**: Elsevier LaTeX 模板（`cas-dc.tex` 双栏或单栏稿件格式）。
- **版面费 / APC**:
  - **$0 美元**：期刊为混合出版模式（Hybrid），作者选择传统订阅出版（Subscription Model）**免收任何版面费**；
  - 若自选 Gold Open Access，APC 费用约为 $3,200 美元。
- **官方收录依据**: SCIE（JCR Q2，中科院计算机与机器人大类）、EI Compendex、Scopus、INSPEC、DBLP。

### 2. 匹配理由与学术价值
- 机器人领域传统知名刊物，对机器人软件架构（Software Architecture）与导航算法实现非常包容；
- 官方支持挂载详尽的补充材料，能完整容纳本文严格的数学推导、离散化敏感度网格与物理停定规则；
- 免版面费（$0 APC），对科研预算友好。

### 3. 贡献点风险分析
- **审稿周期相对较长**: Elsevier 期刊一审周期通常在 2–4 个月左右；
- **对机理分析要求高**: 审稿人可能要求更加深入地解释“为什么在静态刚体几何下 FailMem 无法胜过 Spatial Cache”（本文第 5 节的路径重合分析已部分回答此问题，但审稿人可能会要求补充更多几何参数分析）。

### 4. 所需补充材料
- 转换为 Elsevier 投稿模板，排版为正文 + 官方 Supplementary Material；
- 撰写针对性的 Cover Letter，阐明本文作为 Short Communication 的系统性价值。

---

## 建议行动决策路线 (Recommended Strategy)

1. **若追求成果的权威收录与无版面费支出**:
   - **推荐首选 选项三 (Elsevier RAS - Short Communication)**：完整保留 10 页正文 + 4 页附录（作为 Supplementary），如实阐述中性边界，享受正规 SCIE/EI 检索且 $0 支出。
2. **若追求研究理念的快速传播与同行认可**:
   - **推荐首选 选项二 (IEEE ICRA/IROS Workshop)**：将手稿浓缩为 4–6 页，以可审计性与中性发现为核心卖点，在顶级国际会议展示并与领域专家交流。
3. **若团队有强烈的 Letters 考核指标并能补充真机实验**:
   - 考虑 **选项一 (IEEE RA-L)**，但必须提前做好在有限时间内补充真机实体实验与大幅删减正文的准备。
