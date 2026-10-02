---
title: "面向 ROS 2 导航的可审计失败记忆系统：与空间缓存的探索性对比研究"
author: "匿名作者（待团队正式补充）"
date: "2026年10月"
---

# 面向 ROS 2 导航的可审计失败记忆系统：与空间缓存的探索性对比研究

**作者**：匿名作者（待团队正式补充）  
**机构**：待补充  
**日期**：2026年10月  
**版本**：内部审阅定稿（对应英文稿 `paper/draft.md`）

---

## 摘要

**研究问题**：在多阶段室内移动机器人导航任务中，缺乏跨阶段记忆的标准反应式导航系统（在本基准中以基线方法 $R$ 为代表）在初始视线受阻的情况下，会跨连续任务反复尝试进入已被阻挡的隐蔽通道，导致严重的重复死胡同探索。  
**系统实现**：本文提出了 **FailMem**——一种面向 ROS 2 Nav2 的事件驱动型失败记忆架构。FailMem 将导航中止事件与包含原始激光雷达点云、TF 坐标变换和二维代价地图感兴趣区（ROI）的不可变观测包进行绑定，并引入了基于物理感知的动态失效机制：当机载传感器再次核验证实通道已恢复通畅时，系统会自动解除对该路径的抑制。记忆的保持与失效在单次连续运行会话（single continuous runner execution session）的跨阶段场景中进行评估。  
**实验评测**：在基于 Gazebo 11 与真实 TurtleBot3 动力学仿真的非对称双路径环境中，我们在序列固定随机种子下评测了 FailMem 的 30 次运行（每种实验条件 $n=3$），并与反应式导航（$R$）、空间观测缓存（$O$）以及永久抑制基线（$M1$）进行了系统对比；同时针对动作条件化导航开展了 4 次可行性检查（$H_1$）。  
**关键结果**：在通道受阻场景（D1）中，引入历史信息完全消除了无指导的重复死胡同试探（$0.0$ 次 vs $1.0$ 次），相对反应式重试（$R$）减少了约 $-18.5\%$ 的行进距离（$14.03\,\text{m}$ vs $17.22\,\text{m}$）与 $-22.3\%$ 的仿真耗时（$109.5\,\text{s}$ vs $141.0\,\text{s}$）。在障碍物移除场景（D2）中，动态失效机制相较于永久抑制（$M1$）减少了约 $11.0\%$ 的行进距离（$16.25\,\text{m}$ vs $18.25\,\text{m}$），但平均总仿真耗时增加了约 $1.5\%$（$151.1\,\text{s}$ vs $148.8\,\text{s}$）；本实验未观察到耗时收益，具体原因未经验证。在二维静态几何结构下，FailMem 与空间缓存（$O$）选择了完全相同的拓扑路径，两者在距离和耗时上的差异均小于 $1\%$（D1 中为 $14.03\,\text{m}$ vs $13.95\,\text{m}$；D2 中为 $16.25\,\text{m}$ vs $16.40\,\text{m}$）。  
**研究局限**：在本测试布局与当前样本中，未观察到 FailMem 相对空间缓存（$O$）的额外路由收益；该结论不意味着在任意复杂场景下均无优势，亦未证明统计等价。此外，动作条件化导航候选配置（$H_1$）在当前门洞下未能建立可执行性差异（Nav2 规划器 4/4 成功）。

---

## 1. 引言 (Introduction)

在仓库、医院及办公走廊等结构化室内环境中自主作业的移动机器人，需要频繁穿越共享通道与门禁区域。在动态环境下，未建图的临时物理障碍（如停放的推车或关闭的安全门）常导致名义上的最短路径阻断。包括 ROS 2 导航框架（Nav2）[1, 2] 在内的现代机器人导航系统广泛采用分层二维代价地图（Layered 2D Costmaps）[3] 与局部恢复行为（如原地旋转、后退倒车、清除代价地图等）。尽管此类恢复例程有助于单个目标点跟踪过程中的局部解困，但当目标因超时或规划失败而终止后，其诊断状态通常被直接丢弃。因此，在任务由远端决策路口分阶段下发的场景中，缺乏跨阶段记忆的纯反应式智能体在机载传感器重新获得对阻塞点的视线之前，会机械地反复驶入已知的死胡同。

为了缓解这种盲目的重复试探，目前主要存在两种机制范式：
1. **空间代价地图缓存 ($O$)**：随着传感器观测的积累，在全局连续或离散栅格（例如 Costmap2D [3]、OctoMap [4]、Voxblox [5]）中持久化维护几何占用状态；
2. **情景式失败记忆 ($F$)**：显式记录执行中止事件、故障成因或符号化冲突约束，并在高层任务调度中主动剪枝不可行的候选路径。

尽管当前具身智能研究探索了基于大语言模型的自反思机制（如 Reflexion [9]、REFLECT [12]），但它们主要运作于语义提示词空间，缺乏与物理代价地图生命周期严格契合的过期与失效语义。另一方面，经典机器人学系统极少针对“物理感知何时应当动态撤销某条情景失败记录”给出严格、可验证的判定契约。这就引出了一个核心的实证问题：**在何种物理几何与观测条件下，移动机器人确实需要显式的情景失败记忆，而非仅依赖标准的空间代价地图缓存？**

针对这一问题，本文提出了面向 ROS 2 Nav2 的事件驱动型失败记忆架构 **FailMem**，并通过探索事实证研究厘清其性能边界。本文的核心贡献包括：
1. **事件驱动的失败记忆系统架构**：基于 ROS 2 Nav2 Action 客户端实现，将导航失败事件与不可变观测包（原始激光雷达扫描、TF 坐标变换、局部代价地图 ROI）强绑定，并提供由传感器判定直接驱动的动态失效机制；
2. **可完全复现的基准评测体系**：在 Gazebo 11 物理仿真中建立了包含通畅（D0）、受阻（D1）与恢复（D2）三种场景的 30 次序列固定随机种子评测基准（每条件 $n=3$），对 FailMem（$F$）、反应式重试（$R$）、空间缓存（$O$）和永久抑制（$M1$）进行了系统横向对比；
3. **经验性边界分析与停止判定**：实验证明，历史记忆消除了死胡同绕行（相对 $R$ 减少 $-18.5\%$ 距离），动态失效在障碍移除后避免了永久绕路（相对 $M1$ 减少约 $11.0\%$ 距离，但仿真耗时增加约 $1.5\%$）；而在静态二维几何下，$F$ 与 $O$ 拓扑选择完全重合，性能差异 $<1\%$，未观察到 $F$ 相对 $O$ 的额外路由增量。此外，在动作条件化导航探索（$H_1$）中，候选动作配置未分化出可执行性差异（Nav2 规划器 4/4 成功），从而依据既定协议形成了本轮探索的经验终止标准。

---

## 2. 相关工作与机制分类 (Related Work & Mechanism Taxonomy)

### 2.1 空间占用建图与距离场
分层二维代价地图 [1, 3] 通过将传感器测距射线投射至栅格地图中更新几何障碍，并向外传播配置空间膨胀层。三维体积映射框架（如 OctoMap [4]）利用层次化八叉树实现离散概率体素更新。连续欧氏符号距离场（ESDF）框架（如 Voxblox [5]）则增量构建光滑距离场以供轨迹优化使用。空间建图能够精确维护几何上的自由与占用空间，但对未观测区域一视同仁，且无法表征与特定执行动作相关的故障成因。

### 2.2 执行监控与规划诊断
经典规划监控框架（如 STRIPS [6]、Xavier 移动机器人系统 [7] 及 Ingrand 与 Ghallab 的审议系统综述 [8]）形式化了任务执行监控与诊断修复。现代导航框架 [2] 在局部规划失败时触发恢复行为，但其上下文状态在目标结束后即被丢弃，需要引入显式的跨任务或跨阶段情景记忆来指导高层重路由。

### 2.3 大模型自反思与智能体记忆
近年来，具身智能领域广泛探索利用大语言模型（LLM）进行规划和容错。Reflexion [9] 通过标量奖励反馈驱动 LLM 生成自然语言自反思；Inner Monologue [11] 将环境成功检测器与场景描述注入闭环提示链中；REFLECT [12] 利用 LLM 对多模态机器人经验进行分层总结，生成结构化故障诊断与规划修正。上述方法聚焦于高级语义推理，而 FailMem 则聚焦于 ROS 2 底层 Action 通信与代价地图层级的事件记录、动态失效判定及离线回放审计。

### 2.4 基于经验的规划与冲突学习
在运动规划中，Lightning 框架 [13] 与经验图（E-Graphs）[14] 通过复用历史成功路径库来加速复杂环境中的图搜索。在离散布尔可满足性（SAT）求解中，冲突驱动子句学习（如 GRASP 算法 [15]）通过记录搜索死胡同导出的“非解”（No-goods）来高效剪枝不合理分支。FailMem 借鉴了这种负约束记录思想，并结合物理传感器的主动核验机制赋予其动态撤销能力。

表 1 总结了不同记忆表征与失效机制的对比分类：

**表 1：不同导航记忆机制与失效触发方式分类对比**

| 机制范式 | 内部状态表征 | 物理对齐层级 | 失效触发判定 |
| :--- | :--- | :--- | :--- |
| **Costmap2D / Nav2** | 二维离散占用栅格 | 几何栅格单元 | 传感器射线直接穿透清除 |
| **OctoMap** | 三维概率八叉树 | 离散 3D 体素 | 传感器射线直接穿透清除 |
| **Voxblox** | 连续 ESDF / TSDF | 三维欧氏距离场 | 动态体素积分更新 |
| **Experience Graphs** | 历史路径航点图 | 离散路径段 | 修复时的几何碰撞检测 |
| **Reflexion** | 自然语言文本提示 | 语义 Token | 人工清空或上下文重置 |
| **REFLECT** | 结构化多模态日志 | 语义解释与修正 | 会话结束或离线批处理 |
| **FailMem (本文实现)** | 事件驱动元组 | 原始物理传感器包 | 传感器验证满足 `FREE` 准则 |
| **FailMem F2 (概念扩展)**| 动作轮廓约束元组 | 传感器包 + 轮廓 | 动作几何/动力学能力检验 |

---

## 3. FailMem 系统架构 (The FailMem Architecture)

![FailMem 架构体系与验证管线](figures/architecture.svg)  
*图 1：FailMem 系统总体架构，包含执行运行时、不可变观测包构造与记忆生命周期管理。*

### 3.1 不可变观测包 (Immutable Observation Bundles)
在对通道进行净空分类前，FailMem 首先构建不可变观测包 $B$：
$$B = \langle \text{obs\_id}, \mathbf{z}_{\text{scan}}, \mathbf{T}_{\text{map}\to\text{base}}, \mathbf{M}_{\text{costmap\_ROI}}, t_{\text{msg}}, t_{\text{capture}}, t_{\text{eval}} \rangle$$
其中 $\mathbf{z}_{\text{scan}}$ 表示原始激光扫描测距数组，$\mathbf{T}_{\text{map}\to\text{base}}$ 为 TF 空间坐标变换，$\mathbf{M}_{\text{costmap\_ROI}}$ 为门洞局部感兴趣区（ROI）的二维代价栅格切片，$t$ 分别为消息产生、捕获与评估的时间戳。

### 3.2 通行状态评估准则 (Clearance Classification Rules)
门洞通道的通行状态由严格的几何规则进行三值逻辑分类（在 `src/doorway_evaluator.py` 中实现）：
$$\text{State}(B) = \begin{cases} 
\text{OCCUPIED}, & \text{若 } N_{\text{hits\_inside}} \ge 5 \text{ 或 } N_{\text{costmap\_occupied\_cells}} > 0 \\ 
\text{FREE}, & \text{若 } N_{\text{hits\_inside}} = 0 \text{ 且 } N_{\text{pass\_through}} \ge 8 \text{ 且 } \text{CostmapCleared}(B) \\ 
\text{UNKNOWN}, & \text{其它情况} 
\end{cases}$$
其中 $\text{CostmapCleared}(B) \iff (N_{\text{unknown\_cells}} = 0 \land N_{\text{occupied\_cells}} = 0)$，评估区域限定在门洞局部坐标 ROI $[-0.15, 0.15, 0.95, 1.45]$ 内。

### 3.3 记忆生命周期与动态失效机制
- **失败注册（Failure Registration）**：当机器人在被阻挡的通道内发生导航失败时，系统生成一条激活状态的失败记录：
  $$M = \langle \text{mem\_id}, t_{\text{fail}}, \text{goal\_uuid}, \text{action\_id}, \text{region\_id}, \mathbf{M}_{\text{costmap\_ROI}} \rangle$$
  该激活记录会在决策路口 $J_0$ 强制抑制对应的候选路径。
- **动态失效（Dynamic Invalidation）**：当后续传感器观测得出 $\text{State}(B) = \text{FREE}$ 且证据时间戳 $t_{\text{free}} > t_{\text{fail}}$ 时，该记忆记录状态被置为 $\text{INVALIDATED}$，系统解除对主路径的抑制。
- **跨阶段适用范围说明**：在当前实验实现中，历史观测采集、失败记忆生成、调度分发以及记忆重置均在单次连续运行会话（single continuous runner execution session）中完成。这验证了单次运行内跨阶段的记忆传递，尚未作为跨操作系统守护进程的长效持久化数据库进行评测。
- **独立回放审计管线**：独立的密码学回放审计器根据 SHA256 校验和清单对所有运行日志进行逐一校验，并根据严格物理静止判据（$|v_{\text{lin}}| \le 0.05\,\text{m/s}, |v_{\text{ang}}| \le 0.08\,\text{rad/s}$）评估最终停机稳定性。

---

## 4. 实验设置与评测协议 (Experimental Setup & Protocol)

### 4.1 仿真环境与几何参数
实验在 ROS 2 Humble 环境下利用 Gazebo 11 仿真搭载差速底盘的 TurtleBot3 Waffle 机器人，场景采用非对称双通道布局（`configs/p2c_dualpath_world.model`）：
- **Path A（北部主干道/短路径）**：从决策路口 $J_0 [-2.50, 0.00]$ 经由 $y=1.20$ 处宽 $0.80\,\text{m}$ 的门洞窄道到达目标点 $[2.50, 0.00]$，规划折线总长 $6.124\,\text{m}$。
- **Path B（南部绕行长廊/长路径）**：从 $J_0$ 经由 $y=-2.40$ 的开阔长廊到达目标点，规划折线总长 $9.105\,\text{m}$。

### 4.2 距离指标定义
1. **决策距离 ($d_{\text{dec}}$)**：第 2 阶段机器人由决策路口 $J_0$ 接收目标调度后行驶的物理里程计距离（直达 Path B 约 $7.54\,\text{m}$；直达 Path A 约 $5.89\,\text{m}$）。
2. **总行进距离 ($d_{\text{tot}}$)**：涵盖第 1 阶段（历史试探/感知观测）与第 2 阶段（向终点导航）的累计里程计总距离。

### 4.3 评测场景与基线方法
- **场景 D0（完全通畅）**：门洞无障碍，机器人无先验历史直接沿 Path A 前往终点。
- **场景 D1（主路受阻）**：门洞被物理箱体完全阻断。第 1 阶段包含以下严格时序：
  1. *前哨观测*：机器人从 $J_0 [-2.50, 0.00]$ 移动至观测哨位 $[-1.00, 1.20, 0.0]$，采集初始观测包；
  2. *穿行尝试*：机器人向 $[0.50, 1.20, 0.0]$ 发送真实的 Nav2 Action 请求（超时限额 $15.0\,\text{s}$）；
  3. *动作中止*：Nav2 因物理阻挡报告规划失败；
  4. *记忆生成*：机器人采集确认 `OCCUPIED` 的观测包，分类故障原因，提交激活的失败记录（或更新空间缓存 $O$）；
  5. *返回决策点*：机器人返回 $J_0$。  
  随后在第 2 阶段，从 $J_0$ 调度导航。反应式基线 $R$ 因无跨阶段记忆，仍会尝试进入 Path A，行进至入口航点 $[-1.50, 1.20]$ 处方探测到障碍并倒回 $J_0$，再转向 Path B。该死胡同试探属于第 2 阶段的盲目尝试，与 $F$ 和 $O$ 在第 1 阶段的历史构建严格区分。
- **场景 D2（障碍移除）**：在 D1 之后，障碍被移除。第 1 阶段从哨位 $[-1.00, 1.20]$ 观测到 `FREE` 净空并返回 $J_0$。第 2 阶段从 $J_0$ 调度导航。

**对比基线方法**：
1. **反应式基线 ($R$)**：无跨阶段记忆；在 D1 中重复进入 Path A，探测阻挡后退回 $J_0$ 绕行 Path B。
2. **空间缓存基线 ($O$)**：第 1 阶段在全局代价地图中缓存几何占用，第 2 阶段据此在 $J_0$ 直接规划。
3. **FailMem ($F$)**：具备基于感知的动态失效能力的事件驱动失败记忆系统。
4. **永久抑制基线 ($M1$)**：静态失败记忆，永久屏蔽 Path A，无动态失效机制。

所有条件均在序列固定随机种子下执行 $n=3$ 次运行，单次仿真时间预算为 $180.0\,\text{s}$。

---

## 5. 实证结果与边界分析 (Empirical Results & Boundary Analysis)

### 5.1 条件级综合表现
表 2 列出了 30 次物理仿真运行的完整条件级指标统计（每条件 $n=3$，报告均值 $\pm$ 样本标准差，使用 Bessel 校正 $ddof=1$）。全部 10 种条件的独立回放审计通过率均为 $3/3$（$100\%$），证实了物理停机稳定性与数据的完整性。

**表 2：30 次物理仿真运行的各条件综合实验表现**

| 场景 | 条件/方法 | 运行次数 $n$ | 实际执行路径 | 死胡同进入次数 | 决策距离 (m) | 决策耗时 (s) | 总行进距离 (m) | 总仿真耗时 (s) | 回放审计通过率 |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0** | $R$ | 3 | `Path_A` | 0.0 $\pm$ 0.0 | 6.160 $\pm$ 0.037 | 51.533 $\pm$ 1.656 | 6.160 $\pm$ 0.037 | 51.533 $\pm$ 1.656 | 3/3 (100%) |
| **D0** | $O$ | 3 | `Path_A` | 0.0 $\pm$ 0.0 | 6.203 $\pm$ 0.007 | 49.967 $\pm$ 0.850 | 6.203 $\pm$ 0.007 | 49.967 $\pm$ 0.850 | 3/3 (100%) |
| **D0** | $F$ | 3 | `Path_A` | 0.0 $\pm$ 0.0 | 6.196 $\pm$ 0.031 | 49.900 $\pm$ 0.458 | 6.196 $\pm$ 0.031 | 49.900 $\pm$ 0.458 | 3/3 (100%) |
| **D1** | $R$ | 3 | `Path_A_then_Path_B` | 1.0 $\pm$ 0.0 | 10.816 $\pm$ 0.072 | 82.067 $\pm$ 4.394 | 17.220 $\pm$ 0.242 | 141.000 $\pm$ 5.910 | 3/3 (100%) |
| **D1** | $O$ | 3 | `Path_B` | 0.0 $\pm$ 0.0 | 7.550 $\pm$ 0.052 | 50.033 $\pm$ 1.986 | 13.947 $\pm$ 0.070 | 108.700 $\pm$ 2.718 | 3/3 (100%) |
| **D1** | $F$ | 3 | `Path_B` | 0.0 $\pm$ 0.0 | 7.536 $\pm$ 0.003 | 48.200 $\pm$ 0.954 | 14.027 $\pm$ 0.252 | 109.500 $\pm$ 1.572 | 3/3 (100%) |
| **D2** | $R$ | 3 | `Path_A` | 0.0 $\pm$ 0.0 | 5.915 $\pm$ 0.044 | 49.567 $\pm$ 1.595 | 16.344 $\pm$ 0.032 | 148.167 $\pm$ 3.164 | 3/3 (100%) |
| **D2** | $O$ | 3 | `Path_A` | 0.0 $\pm$ 0.0 | 5.939 $\pm$ 0.066 | 52.033 $\pm$ 1.747 | 16.396 $\pm$ 0.240 | 149.767 $\pm$ 0.551 | 3/3 (100%) |
| **D2** | $F$ | 3 | `Path_A` | 0.0 $\pm$ 0.0 | 5.886 $\pm$ 0.022 | 51.100 $\pm$ 0.954 | 16.247 $\pm$ 0.098 | 151.100 $\pm$ 7.762 | 3/3 (100%) |
| **D2** | $M1$ | 3 | `Path_B` | 0.0 $\pm$ 0.0 | 7.895 $\pm$ 0.023 | 51.300 $\pm$ 1.997 | 18.248 $\pm$ 0.094 | 148.833 $\pm$ 2.397 | 3/3 (100%) |

---

### 5.2 成对对比与轨迹分析
表 3 汇总了各方法间的成对对比结果，图 2 展示了代表性的物理运动轨迹。

**表 3：评估方法间的成对差异对比统计**

| 场景 | 对比组合 ($A$ vs. $B$) | 评估指标 | 方法 A 均值 | 方法 B 均值 | 绝对差异 ($A - B$) | 相对差异 (%) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **D1** | $F$ vs. $R$ | 总行进距离 (m) | 14.027 | 17.220 | -3.193 | **-18.5%** |
| **D1** | $F$ vs. $R$ | 总仿真耗时 (s) | 109.500 | 141.000 | -31.500 | **-22.3%** |
| **D1** | $O$ vs. $R$ | 总行进距离 (m) | 13.947 | 17.220 | -3.273 | **-19.0%** |
| **D1** | $O$ vs. $R$ | 总仿真耗时 (s) | 108.700 | 141.000 | -32.300 | **-22.9%** |
| **D1** | $F$ vs. $O$ | 总行进距离 (m) | 14.027 | 13.947 | +0.080 | +0.6% |
| **D1** | $F$ vs. $O$ | 总仿真耗时 (s) | 109.500 | 108.700 | +0.800 | +0.7% |
| **D2** | $F$ vs. $M1$ | 总行进距离 (m) | 16.247 | 18.248 | -2.000 | **-11.0%** |
| **D2** | $F$ vs. $M1$ | 总仿真耗时 (s) | 151.100 | 148.833 | +2.267 | +1.5% |
| **D2** | $F$ vs. $O$ | 总行进距离 (m) | 16.247 | 16.396 | -0.149 | -0.9% |
| **D2** | $F$ vs. $O$ | 总仿真耗时 (s) | 151.100 | 149.767 | +1.333 | +0.9% |

![各评测条件下的代表性物理运动轨迹](figures/trajectories_map.png)  
*图 2：各评测条件下的代表性物理运动轨迹。*

1. **消除无指导的死胡同试探（$F$ vs. $R$）**：在场景 D1 中，FailMem ($F$) 完全避免了向受阻通道内的重复行进（$0.0$ 次 vs $1.0$ 次），相对反应式基线 $R$ 减少了 $-18.5\%$ 的总距离（$14.03\,\text{m}$ vs $17.22\,\text{m}$）和 $-22.3\%$ 的总耗时（$109.5\,\text{s}$ vs $141.0\,\text{s}$）。需要指出，$R$ 的死胡同试探体现为向入口航点的无指导折返尝试，未发生物理碰撞。
2. **避免永久绕路开销（$F$ vs. $M1$）**：在场景 D2 中，动态失效机制在观测到 `FREE` 状态后解除对 Path A 的抑制，相对永久抑制基线 $M1$ 节省了约 $11.0\%$ 的总距离（$2.00\,\text{m}$，$16.25\,\text{m}$ vs $18.25\,\text{m}$）。然而，平均总仿真耗时增加了约 $1.5\%$（$151.1\,\text{s}$ vs $148.8\,\text{s}$）；在缺乏高分辨率速度曲线采集的前提下，这一耗时微增的具体成因尚未经验证，本实验未观察到耗时收益。
3. **二维静态几何下与空间缓存的对比（$F$ vs. $O$）**：在 D1 与 D2 两个场景中，FailMem ($F$) 与空间缓存 ($O$) 均选择了完全一致的拓扑路径。两者的总距离差异（D1 中 $+0.6\%$，D2 中 $-0.9\%$）与总耗时差异（D1 中 $+0.7\%$，D2 中 $+0.9\%$）均处于 $1\%$ 以内。**在当前测试布局与运行样本下，未观察到显式失败记忆相对空间代价地图缓存的额外路由收益；这不意味着在任意领域均无优势，亦未证明统计等价。** 此外，障碍移除后的动态恢复能力并非 FailMem 独占，空间缓存（$O$）在接收到新的开阔区域点云后同样会更新代价地图并恢复对主路的规划。

---

### 5.3 动作条件化导航可行性检查 ($H_1$)
为了探索动作配置（如正对对齐进入 $a_{\text{aligned}}$ 与偏向门框边界的斜向进入 $a_{\text{oblique}}$）是否会在通畅门洞中产生执行层面的成功率分化，我们开展了包含 4 次物理仿真的探索性可行性检查（`reports/evidence/p2d_h1_feasibility/`）。

**表 4：动作条件化导航 ($H_1$) 4 次可行性检查明细**

| 运行标识 | 动作配置轮廓 | 目标航点坐标 | 门洞感知状态 | Nav2 状态码 (名称) | 预估 Nav2 耗时 (s) | 设定静止期 (s) | 稳定性窗口 (s) | 总仿真耗时 (s) | 严格物理到达核验 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `H1_aligned_run1` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` (23 束) | `SUCCEEDED` (4) | 13.4 | 3.0 | 2.4 | 18.8 | **False** (角速度超标: $0.1068 > 0.08$) |
| `H1_aligned_run2` | `act_aligned` | `[1.50, 1.20, 0.0]` | `FREE` (22 束) | `SUCCEEDED` (4) | 13.4 | 3.0 | 2.4 | 18.8 | **True** |
| `H1_oblique_run1` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` (23 束) | `SUCCEEDED` (4) | 11.1 | 3.0 | 2.3 | 16.4 | **True** |
| `H1_oblique_run2` | `act_oblique` | `[0.50, 0.88, 0.0]` | `FREE` (22 束) | `SUCCEEDED` (4) | 11.0 | 3.0 | 2.3 | 16.3 | **True** |

表 4 汇总了可行性检查的实测数据。Nav2 规划器在全部 4/4 次运行中均返回 `SUCCEEDED`（状态码 4），且在 3/4 次运行中通过了严格物理到达核验（其中 `H1_aligned_run1` 在停机窗口内的最大角速度为 $0.1068\,\text{rad/s}$，超出 $0.08\,\text{rad/s}$ 阈值）。Nav2 的 `DWBLocalPlanner` 在所有测试中均顺利完成门洞穿越，未触发底层规划中止。  
**判定与决策**：**候选动作配置未能建立预期中的可执行性分化；因此依预定协议终止了针对该假设的后续实验，这并不构成对更广泛动作条件失败记忆假设的否定。**

---

## 6. 有效性威胁与研究局限 (Threats to Validity & Limitations)

1. **探索性样本规模**：本研究的 30 次主对比实验（每条件 $n=3$）旨在验证机制的可行性与可审计性，不构成大样本渐近统计假设检验。
2. **仿真保真度**：实验基于 Gazebo 11 与标称传感器噪声模型。在包含传感器丢包、高度动态人流及恶劣光照的真实物理硬件部署仍属后续研究范畴。
3. **概念扩展阶段（$F2, O+$）**：动作轮廓化失败记忆（$F2$）与带退避衰减的空间缓存（$O+$）目前仅作为概念模型写入设计文档，尚未开展仿真实现与评测。
4. **单会话阶段内评估**：记忆的有效性验证严格局限于单次持续运行会话内的连续跨阶段场景，尚未验证跨操作系统重启、长期数据库持久化索引或多日连续运行。

---

## 7. 结论 (Conclusion)

本文提出了面向自主移动机器人的事件驱动型失败记忆架构 FailMem。通过将导航执行中止与不可变观测包强绑定，并结合独立的离线密码学回放审计，FailMem 为机器人系统的可复现性评测建立了严格的标准体系。实证数据表明，相较于纯反应式重试，历史记忆能彻底消除盲目的死胡同试探；而基于感知的动态状态更新（在 FailMem 与空间缓存中均具备）可有效防止环境恢复通畅后的永久绕路陷阱。在当前评测的静态几何布局与样本中，显式失败记忆未展现出超越空间代价地图缓存的额外路由收益。这一探索性基准与经验终止判据，为未来高维动作空间及多智能体协作记忆系统的深入研究提供了真实可靠的实证参考。

---

## 参考文献 (References)

[1] S. Macenski, T. Foote, B. Gerkey, C. Lalancette, and W. Woodall, "Robot Operating System 2: Design, architecture, and uses in the wild," *Science Robotics*, vol. 7, no. 66, p. eabm6074, 2022. DOI: [10.1126/scirobotics.abm6074](https://doi.org/10.1126/scirobotics.abm6074).  
[2] S. Macenski, F. Martín, R. White, and J. Ginés Clavero, "The Marathon 2: A Navigation System," in *IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*, 2020, pp. 2718–2725. DOI: [10.1109/IROS45743.2020.9341207](https://doi.org/10.1109/IROS45743.2020.9341207).  
[3] D. V. Lu, D. Hershberger, and W. D. Smart, "Layered Costmaps for Context-Sensitive Navigation," in *IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*, 2014, pp. 709–715. DOI: [10.1109/IROS.2014.6942636](https://doi.org/10.1109/IROS.2014.6942636).  
[4] A. Hornung, K. M. Wurm, M. Bennewitz, C. Stachniss, and W. Burgard, "OctoMap: An Efficient Probabilistic 3D Mapping Framework Based on Octrees," *Autonomous Robots*, vol. 34, no. 3, pp. 189–206, 2013. DOI: [10.1007/s10514-012-9321-0](https://doi.org/10.1007/s10514-012-9321-0).  
[5] H. Oleynikova, Z. Taylor, M. Fehr, R. Siegwart, and J. Nieto, "Voxblox: Incremental 3D Euclidean Signed Distance Fields for On-Robot Exploration," in *IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*, 2017, pp. 1366–1373. DOI: [10.1109/IROS.2017.8202315](https://doi.org/10.1109/IROS.2017.8202315).  
[6] R. E. Fikes and N. J. Nilsson, "STRIPS: A New Approach to the Application of Theorem Proving to Problem Solving," *Artificial Intelligence*, vol. 2, no. 3-4, pp. 189–208, 1971. DOI: [10.1016/0004-3702(71)90010-5](https://doi.org/10.1016/0004-3702(71)90010-5).  
[7] R. Simmons, R. Goodwin, K. Z. Haigh, S. Koenig, and J. O'Sullivan, "The Xavier Mobile Robot: Autonomous Navigation in Human Environments," *IEEE Robotics & Automation Magazine*, vol. 5, no. 1, pp. 34–42, 1998. DOI: [10.1109/100.740882](https://doi.org/10.1109/100.740882).  
[8] F. Ingrand and M. Ghallab, "Deliberation for Autonomous Robots: A Survey," *Artificial Intelligence*, vol. 247, pp. 10–44, 2017. DOI: [10.1016/j.artint.2014.11.003](https://doi.org/10.1016/j.artint.2014.11.003).  
[9] N. Shinn, F. Cassano, A. Gopinath, K. Narasimhan, and S. Yao, "Reflexion: Language Agents with Verbal Reinforcement Learning," in *Advances in Neural Information Processing Systems (NeurIPS)*, vol. 36, 2023, pp. 8634–8652. URL: [https://proceedings.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954a37003d400e932-Abstract-Conference.html](https://proceedings.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954a37003d400e932-Abstract-Conference.html).  
[10] M. Ahn et al., "Do As I Can, Not As I Say: Grounding Language in Robotic Affordances," in *Robotics: Science and Systems (RSS)*, 2022. DOI: [10.15607/RSS.2022.XVIII.021](https://doi.org/10.15607/RSS.2022.XVIII.021).  
[11] W. Huang et al., "Inner Monologue: Embodied Reasoning through Planning with Language Models," in *Conference on Robot Learning (CoRL)*, ser. Proceedings of Machine Learning Research, vol. 205, 2023, pp. 1769–1782. URL: [https://proceedings.mlr.press/v205/huang23c.html](https://proceedings.mlr.press/v205/huang23c.html).  
[12] Z. Liu, A. Bahety, and S. Song, "REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction," in *Conference on Robot Learning (CoRL)*, ser. Proceedings of Machine Learning Research, vol. 229, 2023, pp. 3468–3484. URL: [https://proceedings.mlr.press/v229/liu23g.html](https://proceedings.mlr.press/v229/liu23g.html).  
[13] D. Berenson, S. S. Srinivasa, and J. Kuffner, "A Robot Path Planning Framework for Adaptive Experience Reuse," *The International Journal of Robotics Research*, vol. 31, no. 10, pp. 1237–1254, 2012. DOI: [10.1177/0278364912456311](https://doi.org/10.1177/0278364912456311).  
[14] M. Phillips, B. J. Cohen, S. Chitta, and M. Likhachev, "E-Graphs: Bootstrapping Planning with Experience Graphs," *The International Journal of Robotics Research*, vol. 31, no. 10, pp. 1159–1175, 2012. DOI: [10.1177/0278364912461942](https://doi.org/10.1177/0278364912461942).  
[15] J. P. Marques-Silva and K. A. Sakallah, "GRASP: A Search Algorithm for Propositional Satisfiability," *IEEE Transactions on Computers*, vol. 48, no. 5, pp. 506–521, 1999. DOI: [10.1109/12.769433](https://doi.org/10.1109/12.769433).  
