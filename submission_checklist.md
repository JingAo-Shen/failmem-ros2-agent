# FailMem 投稿评议材料清单与决策备查包 (Submission Checklist & Review Package)

**文档定位**: 供作者团队在最终选定投稿渠道前进行审阅与决策的完整材料包。  
**源码冻结基准**: `de05246f251263fb60a98ca3995fb8d65f38905c` (`de05246`)  
**手稿终审基准**: `5e6ed1ff3e36e19195b0fe637ce02047ee2d7fc7` (`5e6ed1f`)  
**整理日期**: 2026-10-14  

---

## 一、手稿核心元数据 (Neutral Manuscript Metadata)

### 1.1 英文中立标题 (Neutral English Title)
> **Auditable Failure Memory for ROS 2 Navigation: An Exploratory Comparison with Spatial Caching**

### 1.2 精炼学术摘要 (Refined Abstract)
> Multi-stage autonomous mobile robot navigation frequently encounters dead-end paths that cannot be resolved solely through immediate line-of-sight sensing. While spatial costmap caching can preserve geometric occupancy, explicit failure memory offers a perception-grounded mechanism for recording traversal aborts and driving dynamic invalidation. This paper presents an open-source, auditable implementation of episodic failure memory integrated into the ROS 2 Nav2 stack. In a controlled physical simulation featuring an asymmetric dual-path hallway ($0.80\,\text{m}$ doorway), we conduct an exploratory benchmark ($n=3$ fixed seeds per condition) across nominal, blocked, and cleared scenarios. In blocked configurations (D1), retaining historical failure records eliminates dead-end traversals, reducing travel distance by $18.5\%$ and simulated duration by $22.3\%$ compared to reactive retries ($R$). When a blocked passage is cleared (D2), perception-driven invalidation autonomously re-enables the primary route, shortening distance by $11.0\%$ relative to permanent detour baselines ($M1$), though no overall duration improvement was observed as total duration is dominated by pre-dispatch history. However, in this static 2D rigid geometry, FailMem ($F$) selects topological paths identical to the spatial caching baseline implemented in this study ($O$), yielding distance and duration differences below $1\%$; no incremental routing advantage of explicit failure events over spatial caching is observed. A pilot exploration of action-conditioned navigation ($H_1$) was objectively terminated when all commanded orientation actions traversed the passage without differentiation (Nav2 returned success 4/4, strict physical arrival verification passed 3/4; failed to establish expected executability difference). All simulation artifacts, deterministic trajectory ledgers, and build workflows are published under an end-to-end reproducible pipeline.

### 1.3 三项限定贡献 (Three Limited Contributions)
本研究严格限定为以下三项贡献，与冻结正文保持严格一致，不新增未量化主张：

1. **感知证据绑定的事件记录与动态失效实现 (Perception-Grounded Event Memory & Invalidation Implementation)**:  
   设计并实现了一套适用于 ROS 2 Nav2 的架构，将导航任务中止事件与底层传感器数据（原始激光雷达点云、TF 坐标变换、局部代价图感兴趣区域快照）直接绑定，并在感知核验通道通畅时触发动态失效（Dynamic Invalidation）。
2. **可复算的探索性导航比较 (Auditable Exploratory Navigation Comparison)**:  
   在 Gazebo 物理仿真中建立了包含 30 轮物理运行的基准测试（每条件 $n=3$ 固定随机种子），在通畅（D0）、阻塞（D1）与恢复（D2）三种场景下对比了 FailMem ($F$)、反应式基线 ($R$)、本研究实现的空间缓存基线 ($O$) 与永久禁用基线 ($M1$)；配套全量数据哈希清单、离线重放评分流水线与严格物理停定审计标准。在恢复场景（D2）中，**明确记录距离缩短但未观察到总时间改善**（行驶距离缩短 $\approx 11.0\%$，总时间均值差 $+2.27\,\text{s}$，主要由派发前的历史探索阶段耗时所主导）。
3. **当前布局中未观察到 FailMem 优于空间缓存基线的边界结果 (Boundary Results on $F$ vs. $O$)**:  
   通过客观实测界定了显式失败记忆与空间缓存的能力边界：在当前评测的静态 2D 刚体几何长廊环境中，FailMem 未能提供超出本研究实现的空间缓存基线（$O$）的增量路由收益（路径拓扑一致，距离与时间差异 $<1\%$）；在一项 4 轮动作条件化导航可行性探索（$H_1$）中，**Nav2返回成功4/4，严格物理到达验证3/4；未建立预期可执行性差异**，依据预设科学规程客观中止了该分支探索。

### 1.4 客观已知局限声明 (Acknowledged Limitations)
1. **单一环境布局**: 实验限定于长廊不对称双路径几何环境（北侧门区 $0.80\,\text{m}$，南侧开阔通道）；尚未覆盖多岔路迷宫或多房间复杂建筑拓扑。
2. **探索性小样本**: 主线对比实验为每条件 $n=3$ 轮固定随机种子执行（总计 30 轮物理运行），属于机理验证性的小样本基准，不构成大样本渐近统计假设检验；严禁将小样本均值接近表述为“统计等效”。
3. **物理仿真环境限制**: 评测限定于 Gazebo 11 物理仿真与标称传感器模型下完成，未在带有传感器噪声丢包、轮速打滑、动态人流或光照变化的实体机器人硬件上进行长周期测试。
4. **静态几何下无增量路由收益**: 在静态 2D 刚体障碍场景下，FailMem ($F$) 与本研究实现的空间缓存基线 ($O$) 选择完全相同的拓扑路径，距离与耗时差异 $<1\%$；显式失败事件在此类场景未展现超越空间代价图缓存的增量路由收益。

---

## 二、研究分支边界说明 (Scope & OS Branch Boundary)

- **主线投稿内容界定**:  
  主线论文严格聚焦于 **ROS 2 Nav2 架构下的 FailMem 与空间缓存基线 ($O$) 的可复算实证对比与边界分析**。
- **OS 探索分支归档地位 (Archival-Only Status)**:  
  前期进行的 OS 场景探索分支（包含操作系统工具链调用、环境交互探针等）**仅作为仓库历史归档保留，严格不作为主线论文的投稿内容，亦不作为核心证据链**。主线成果完全独立自足。

---

## 三、完整投稿材料清单 (Submission Package Checklist)

| 材料类别 | 文件/资源定位 | 状态与说明 | 审核确认 |
| :--- | :--- | :--- | :---: |
| **主文 PDF** | [`paper/paper.pdf`](paper/paper.pdf) | SHA-256: `77707d90162e3c10b9749a81ea7da00320ff5b0cbb55af81186ae98f423872e8` (10 页，692KB) | `human_verified=false` |
| **补充材料 PDF** | [`paper/supplementary.pdf`](paper/supplementary.pdf) | SHA-256: `b86bdb0b14ce528091cbe6d589c0760c71948eebec8fd3409490e7f743e09055` (4 页，191KB) | `human_verified=false` |
| **中文单页简报** | [`paper_summary_zh.md`](paper_summary_zh.md) | 针对研究问题、三项限定贡献、核心实测数据与局限的中文说明文档 | 已就绪 |
| **投稿去向调研** | [`submission_options.md`](submission_options.md) | 涵盖 IEEE RA-L、Elsevier RAS 与 Workshop 状态的逐项官方依据核查与决策表 | 已就绪 |
| **独立验收归档** | [`reports/acceptance/INDEX.md`](reports/acceptance/INDEX.md) | 归档完整 SHA-256 索引表、区分 Phase A (worktree) 与 Phase B (主工作区) 执行记录 | 已就绪 |
| **代码与数据仓库** | GitHub 仓库主干/发布分支 | 公开代码库与数据归档包，分支 `research/agent-task-repair-pilot` | 已冻结 |
| **一键复现脚本** | [`scripts/reproduce_offline.sh`](scripts/reproduce_offline.sh) | 零外部网络依赖的离线复现流水线（271/271 SHA 吻合，Replay 30/30 通过） | 已验证 |
| **自动化构建脚本** | [`paper/scripts/build_paper_pdf.sh`](paper/scripts/build_paper_pdf.sh) | 基于锁文件依赖的本地 PDF 编译流水线（含 TeX 公式泄露检测与表格结构校验） | 已验证 |
| **作者信息占位** | 见本文第四节 | 渠道中立的作者信息与致谢信息准备清单（待作者选定目标后填入适配模板） | 待作者填入 |
| **硬件实验缺失说明** | 见本文第五节 | 明确记录缺失实体硬件实验的客观事实，提示作者团队评估同行评审风险 | 待作者决策 |

---

## 四、渠道中立的作者信息与致谢占位准备 (Venue-Neutral Placeholders)

> **原则说明**: 在作者团队未最终确定具体投稿目标渠道前，**不提前混用 IEEE 或 Elsevier 特定的 LaTeX 格式模板宏包**。作者团队只需提前核实并准备以下通用元数据字段，待选定具体渠道后再直接转换为对应期刊/会议的排版宏：

### 4.1 通用作者信息清单 (Author Information Fields)
- **论文署名顺序与姓名 (Author Names & Order)**: [例如：Author 1, Author 2, Author 3]
- **作者依托单位与院系 (Affiliations)**: [例如：Department of ..., University/Institute Name, City, Country]
- **通讯作者指定与邮箱 (Corresponding Author & Email)**: [例如：Author Name, email@domain.edu]
- **ORCID 标识符 (ORCID iDs)**: [例如：0000-000X-XXXX-XXXX]
- **评审盲审模式适配提示**:
  - 若最终选定渠道要求**双匿名评审 (Double-anonymous, 如 IEEE RA-L)**：提交稿件正文中隐去上述全部作者信息；
  - 若最终选定渠道要求**单匿名评审 (Single-anonymized, 如 Elsevier RAS)**：提交稿件首页须完整呈现上述全部信息。

### 4.2 基金资助与致谢通用信息 (Funding & Acknowledgments Fields)
- **资助基金机构全称 (Funding Agency)**: [例如：National Science Foundation / 某某科学基金委员会]
- **资助项目/课题编号 (Grant Numbers)**: [例如：Grant No. XXXXXXXX]
- **受致谢人员及贡献性质 (Acknowledged Individuals & Contributions)**: [例如：感谢某某实验室提供算力支持或参与系统联调讨论，确保无利益冲突]

---

## 五、实体真机实验缺失说明与同行评审风险提示 (Hardware Gap & Risk Assessment)

### 5.1 客观事实核查
- **实测范围确认**: 本研究的所有基准评测数据均在 **Gazebo 11 物理仿真环境与标称传感器模型** 下采集完成（共计 30 轮仿真物理运行）；
- **客观缺失**: **本研究未进行实体机器人（Real Robot Hardware）部署实验**；未在带有真实物理接触、轮式打滑、激光雷达脏污/多径反射或动态人流穿行的真实建筑物中完成长周期测试。

### 5.2 对同行评审过程的定性风险分析
1. **若投稿至 传统机器人 Letters (如 IEEE RA-L)**:
   - **风险定性**: 尽管官方指南未将真机列为强制 Desk Reject 条件，但机器人领域期刊审稿群体对纯仿真实验普遍持有较高的审慎态度，常有审稿意见质疑“仿真到真实（Sim-to-Real）的有效性”，存在明显的同行评议阻力；
   - **应对选择**: 需由作者团队决策是否需额外补充实体轮式机器人环境验证视频，或转投对仿真与系统实践更具包容性的刊物。
2. **若投稿至 机器人与自主系统期刊 (如 Elsevier RAS 常规论文)**:
   - **风险定性**: 期刊征稿范围包含仿真环境下的认知与导航算法架构；但作为常规长文（Regular Paper）审视时，单一长廊布局与小样本（$n=3$）可能被审稿人认为实验广度不足；
   - **应对选择**: 需在 Cover Letter 与引言中明确阐明本文作为“探索性机制比较与可复算基准（Exploratory Benchmarking Framework）”的系统定位，强调离线审计流水线的完整性。
3. **若等待 2027 年初公布的专业 Workshop (如 ICRA 2027 Benchmarking / Reproducibility 专题)**:
   - **风险定性**: 研讨会同行通常对纯仿真基准、中性结果与工程账本高度包容；但需注意非正式研讨会论文集可能无法满足特定学术机构的毕业或职称考核要求，需作者团队提前确认成果认定细则。
