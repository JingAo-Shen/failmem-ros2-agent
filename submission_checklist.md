# FailMem 投稿评议材料清单与决策备查包 (Submission Checklist & Review Package)

**文档定位**: 供作者团队在最终投稿前进行独立审阅与决策的完整材料包。  
**源码冻结基准**: `de05246f251263fb60a98ca3995fb8d65f38905c` (`de05246`)  
**手稿终审基准**: `5e6ed1ff3e36e19195b0fe637ce02047ee2d7fc7` (`5e6ed1f`)  
**整理时间**: 2026-10-14  

---

## 一、手稿核心元数据 (Neutral Manuscript Metadata)

### 1.1 英文中立标题 (Neutral English Title)
> **Auditable Failure Memory for ROS 2 Navigation: An Exploratory Comparison with Spatial Caching**

### 1.2 精炼学术摘要 (Refined Abstract)
> Multi-stage autonomous mobile robot navigation frequently encounters dead-end paths that cannot be resolved solely through immediate line-of-sight sensing. While spatial costmap caching can preserve geometric occupancy, explicit failure memory offers a perception-grounded mechanism for recording traversal aborts and driving dynamic invalidation. This paper presents an open-source, auditable implementation of episodic failure memory integrated into the ROS 2 Nav2 stack. In a controlled physical simulation featuring an asymmetric dual-path hallway ($0.80\,\text{m}$ doorway), we conduct an exploratory benchmark ($n=3$ fixed seeds per condition) across nominal, blocked, and cleared scenarios. In blocked configurations (D1), retaining historical failure records eliminates dead-end traversals, reducing travel distance by $18.5\%$ and simulated duration by $22.3\%$ compared to reactive retries ($R$). When a blocked passage is cleared (D2), perception-driven invalidation autonomously re-enables the primary route, shortening distance by $11.0\%$ relative to permanent detour baselines ($M1$), though overall duration is dominated by pre-dispatch history. However, in this static 2D rigid geometry, FailMem ($F$) selects topological paths identical to standard spatial caching ($O$), yielding distance and duration differences below $1\%$; no incremental routing advantage of explicit failure events over spatial caching is observed. A pilot exploration of action-conditioned navigation ($H_1$) was objectively terminated when all commanded orientation actions traversed the passage without differentiation. All simulation artifacts, deterministic trajectory ledgers, and build workflows are published under an end-to-end reproducible pipeline.

### 1.3 三项限定贡献 (Three Limited Contributions)
1. **感知证据绑定的事件记录与动态失效实现 (Perception-Grounded Event Memory & Invalidation Implementation)**:  
   设计并实现了一套适用于 ROS 2 Nav2 的轻量级架构，将导航任务中止事件与不可变传感器数据（原始激光雷达点云、TF 坐标变换、局部代价图感兴趣区域快照）直接绑定，并在感知核验通道通畅时触发动态失效。
2. **可复算的探索性导航比较 (Auditable Exploratory Navigation Comparison)**:  
   在 Gazebo 物理仿真中建立了包含 30 轮仿真实验的对比基准（$n=3$ 固定种子），覆盖通畅（D0）、阻塞（D1）与恢复（D2）三种场景，配套全量数据哈希清单、离线重放评分流水线与严格物理停定审计准则。
3. **当前布局中未观察到 FailMem 优于 Spatial Cache 的边界结果 (Boundary Results on $F$ vs. $O$)**:  
   通过客观实测界定了显式失败记忆与空间缓存的能力边界：在当前评测的静态 2D 刚体几何不对称长廊环境中，FailMem 未能提供超出空间缓存的增量路由收益；在一项 4 轮动作条件化导航可行性探索（$H_1$）中未观察到可执行性分化，依据预设科学规程客观中止了该分支探索。

### 1.4 客观已知局限声明 (Acknowledged Limitations)
1. **单一环境布局**: 实验限定于长廊不对称双路径几何环境（北侧门区 $0.80\,\text{m}$，南侧开阔通道）；尚未覆盖多岔路迷宫或多房间复杂建筑。
2. **小样本探索性试验**: 主线对比实验为每条件 $n=3$ 轮固定随机种子执行（总计 30 轮物理运行），属于机理验证性的小样本基准，不构成大样本渐近统计假设检验；严禁将小样本均值接近表述为“统计等效”。
3. **物理仿真环境限制**: 评测限定于 Gazebo 11 物理仿真与标称传感器模型下完成，未在带有传感器噪声丢包、动态人流或光照变化的实体机器人硬件上进行长周期测试。
4. **静态几何下无增量路由收益**: 在静态 2D 刚体障碍场景下，FailMem ($F$) 与 Spatial Cache ($O$) 选择完全相同的拓扑路径，距离与耗时差异 $<1\%$；显式失败事件在此类场景未展现超越空间代价图缓存的增量路由收益。

---

## 二、研究分支边界说明 (Scope & OS Branch Boundary)

- **主线投稿内容界定**:  
  主线投稿稿件严格聚焦于 **ROS 2 Nav2 架构下的 FailMem 与 Spatial Cache 的可复算实证对比**。
- **OS 探索分支地位 (Archival-Only Status)**:  
  前期进行的 OS 场景探索分支（包含操作系统工具链调用、环境交互探针等）**仅作为仓库历史归档保留，严格不作为主线论文的投稿内容，亦不作为核心证据链**。主线成果完全独立自足。

---

## 三、完整投稿材料清单 (Submission Package Checklist)

| 材料类别 | 文件/资源定位 | 状态与说明 | 审核确认 |
| :--- | :--- | :--- | :---: |
| **主文 PDF** | [`paper/paper.pdf`](paper/paper.pdf) | SHA-256: `77707d90162e3c10b9749a81ea7da00320ff5b0cbb55af81186ae98f423872e8` (10 页，692KB) | `human_verified=false` |
| **补充材料 PDF** | [`paper/supplementary.pdf`](paper/supplementary.pdf) | SHA-256: `b86bdb0b14ce528091cbe6d589c0760c71948eebec8fd3409490e7f743e09055` (4 页，191KB) | `human_verified=false` |
| **中文单页简报** | [`paper_summary_zh.md`](paper_summary_zh.md) | 针对研究问题、三项贡献、核心数据与局限的中文说明文档 | 已就绪 |
| **投稿去向调研** | [`submission_options.md`](submission_options.md) | 涵盖 IEEE RA-L、ICRA/IROS Workshop 与 Elsevier RAS 的官方规范比对 | 已就绪 |
| **独立验收归档** | [`reports/acceptance/INDEX.md`](reports/acceptance/INDEX.md) | 归档完整 SHA-256 索引表、区分 Phase A 与 Phase B 执行记录 | 已就绪 |
| **代码与数据仓库** | GitHub 仓库主干/发布分支 | 公开代码库与数据归档包，分支 `research/agent-task-repair-pilot` | 已冻结 |
| **一键复现脚本** | [`scripts/reproduce_offline.sh`](scripts/reproduce_offline.sh) | 零外部网络依赖的离线复现流水线（271/271 SHA 吻合，Replay 30/30 通过） | 已验证 |
| **自动化构建脚本** | [`paper/scripts/build_paper_pdf.sh`](paper/scripts/build_paper_pdf.sh) | 基于锁文件依赖的本地 PDF 编译流水线（含 TeX 公式泄露检测与表格行列校验） | 已验证 |
| **作者信息占位** | 见本文第四节 | 提供单盲（Single-Blind）与双盲（Double-Blind）占位模板 | 待作者填入 |
| **致谢与基金占位** | 见本文第四节 | 提供标准致谢与基金资助编号占位模板 | 待作者填入 |
| **硬件实验缺失说明** | 见本文第五节 | 明确披露缺乏实体机器人实验的风险并给出作者决策预案 | 待作者决策 |

---

## 四、作者信息与致谢占位模板 (Placeholders)

### 4.1 匿名评审版本 (Double-Blind / Anonymous Placeholder)
若目标渠道采用双盲评审（例如部分 ICRA/IROS Workshop 或特殊审稿专栏）：
```latex
\author{Anonymous Authors}
\affiliation{Paper under double-blind review}
```
正文及致谢中一律隐去作者姓名、依托单位及直接指向个人身份的 GitHub 私有账户。

### 4.2 实名评审版本 (Single-Blind / Non-blind Placeholder)
若目标渠道采用单盲评审（例如 IEEE RA-L 或 Elsevier RAS）：
```latex
\author{Author One$^{1}$, Author Two$^{2}$, and Author Three$^{1}$%
\thanks{$^{1}$Author One and Author Three are with the Department of Robotics Engineering, University Name, City, Country. {\tt\small author1@university.edu}}%
\thanks{$^{2}$Author Two is with the Autonomous Systems Laboratory, Research Institute, City, Country. {\tt\small author2@institute.org}}%
}
```

### 4.3 基金资助与致谢模板 (Funding & Acknowledgments Placeholder)
```latex
\section*{Acknowledgment}
This work was supported in part by the [Funding Agency Name] under Grant [Grant Number 12345678], and in part by the [Project/Laboratory Name]. The authors would like to thank [Colleague Names / Lab Members] for their insightful feedback during system integration and benchmarking discussions.
```

---

## 五、实体真机实验缺失说明与决策预案 (Hardware Gap Disclosure)

### 5.1 事实披露
- **现状确认**: 本研究的所有评测数据均在 **Gazebo 11 物理仿真环境与标称传感器模型** 下采集完成（共计 30 轮物理仿真运行）；
- **当前缺失**: **完全未进行实体机器人（Real Robot Hardware）实物实验**；未对真实激光雷达多径反射、轮速打滑、无线网络时延及动态人流场景进行硬件验证。

### 5.2 针对各投稿渠道的作者决策指南
1. **若投稿至 选项一 (IEEE RA-L)**:
   - **风险提示**: RA-L 审稿人极其严苛地将“实体机器人硬件验证”作为评估论文工程成熟度的重要依据。纯仿真论文被拒稿率极高。
   - **作者决策选择**:
     - *方案 A (推荐)*: 不急于提交 RA-L，优先转向更重视科学中性发现与软件透明度的 **选项二 (ICRA/IROS Workshop)** 或 **选项三 (Elsevier RAS)**；
     - *方案 B*: 若必须提交 RA-L，作者团队需调配物理轮式移动机器人（如 TurtleBot 3、Jackal 等），在真实办公楼或实验室搭建 $0.80\,\text{m}$ 门洞场景，录制物理机器人在 D0/D1/D2 下的验证视频作为多媒体附件，并在正文中补充实物测试对比数据。
2. **若投稿至 选项二 (ICRA/IROS Workshop)** 或 **选项三 (Elsevier RAS - Short Communication)**:
   - **风险提示**: 此类渠道认可高置信度物理仿真评测与可复算基准（Reproducible Benchmark）；
   - **作者决策选择**: 维持当前 100% 仿真成果，在正文局限性章节中如实披露硬件缺失，重点突出代码完全开源与离线审计机制，即可直接发起投稿。
