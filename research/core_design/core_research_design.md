# 核心研究设计：部分可观测下失败约束适用范围的主动核验与学习机制

**文档定位**：学术方法论论证与可证伪 SCI 研究方案设计（非代码实现、非实验扩容、非投稿准备）  
**基准成果版本**：`73b0b83a836a128b09aa1137137cf97757183e8d`（已有实现、数据与文本完全冻结）  
**设计分支**：`research/core-method-design`  
**执行边界**：0 新增算法工程代码、0 仿真/物理机器人实验、0 模型训练、0 真实 LLM 调用。仅包含原始文献精读、数学形式化推导、示意性推演案例与评测证伪设计。

---

## 目录

- [一页中文摘要（核心五问答辩）](#一页中文摘要核心五问答辩)
- [一、候选核心问题与方法目标](#一候选核心问题与方法目标)
  - [1.1 核心研究问题界定](#11-核心研究问题界定)
  - [1.2 候选方法目标与本质聚焦](#12-候选方法目标与本质聚焦)
  - [1.3 核心边界与否定触发预警](#13-核心边界与否定触发预警)
- [二、最接近已有方法精读与文献差异表](#二最接近已有方法精读与文献差异表)
  - [2.1 四大领域最接近文献精读与定位](#21-四大领域最接近文献精读与定位)
  - [2.2 关键质疑专项剖析](#22-关键质疑专项剖析)
  - [2.3 最接近方法比较表](#23-最接近方法比较表)
  - [2.4 新颖性边界判定](#24-新颖性边界判定)
- [三、问题形式化](#三问题形式化)
  - [3.1 决策对象与动作空间](#31-决策对象与动作空间)
  - [3.2 可见信息、条件与观测空间](#32-可见信息条件与观测空间)
  - [3.3 隐藏潜变量与环境不完全可观测性](#33-隐藏潜变量与环境不完全可观测性)
  - [3.4 候选约束与其适用范围表示](#34-候选约束与其适用范围表示)
  - [3.5 核验动作库、信息增益与代价模型](#35-核验动作库信息增益与代价模型)
  - [3.6 任务全生命周期累计成本目标函数](#36-任务全生命周期累计成本目标函数)
  - [3.7 理论假设、公理与极限情况深入讨论](#37-理论假设公理与极限情况深入讨论)
- [四、具体候选方法设计（SCOPE-VERIFY 最小模型）](#四具体候选方法设计scope-verify-最小模型)
  - [4.1 失败触发与多重候选解释溯因生成](#41-失败触发与多重候选解释溯因生成)
  - [4.2 贝叶斯后验与范围边界联合更新](#42-贝叶斯后验与范围边界联合更新)
  - [4.3 任务导向的主动核验决策策略](#43-任务导向的主动核验决策策略)
  - [4.4 约束生命周期管理：复用、暂缓、收缩与撤销](#44-约束生命周期管理复用暂缓收缩与撤销)
  - [4.5 未见条件组合下的泛化与外推机制](#45-未见条件组合下的泛化与外推机制)
  - [4.6 算法伪代码与计算复杂度分析](#46-算法伪代码与计算复杂度分析)
  - [4.7 相比基线方法的核心步骤差异与增益机理](#47-相比基线方法的核心步骤差异与增益机理)
- [五、能够否定方法的评测方案](#五能够否定方法的评测方案)
  - [5.1 贯穿全文的 ROS 2/Gazebo 真实物理任务场景](#51-贯穿全文的-ros-2gazebo-真实物理任务场景)
  - [5.2 对照组设计（5 类强基线）](#52-对照组设计5-类强基线)
  - [5.3 公平性控制矩阵（先验 vs 习得知识）](#53-公平性控制矩阵先验-vs-习得知识)
  - [5.4 泛化性与非平稳动态测试协议](#54-泛化性与非平稳动态测试协议)
  - [5.5 评价指标体系（预先锚定主指标）](#55-评价指标体系预先锚定主指标)
  - [5.6 消融实验矩阵](#56-消融实验矩阵)
  - [5.7 证伪与强制停止条件（Stop Conditions）](#57-证伪与强制停止条件stop-conditions)
- [六、研究决策论证（Go / Conditional Go / No-Go）](#六研究决策论证go--conditional-go--no-go)
  - [6.1 决策判定：Conditional Go](#61-决策判定conditional-go)
  - [6.2 必须解决的最小核心技术缺口清单](#62-必须解决的最小核心技术缺口清单)
  - [6.3 严格停止边界与非包装承诺](#63-严格停止边界与非包装承诺)

---

## 一页中文摘要（核心五问答辩）

本研究设计旨在客观回答：在完全冻结原有工程实现与无对照实验的前提下，能否提炼出一个具有实质学术贡献、可证伪且值得进入 SCI 严谨审稿流程的方法论课题。

### 1. 现有方法缺什么？
现有自主机器人应对执行失败主要依赖三类范式，但这三类范式在“部分可观测复杂物理环境”下均存在根本结构性缺陷：
- **经验规划与几何通行性（如 E-Graphs, Lightning, BADGR）**：仅在构型空间 $\mathcal{C}$ 或低维图像特征中记录成功/失败轨迹，缺乏对隐藏物理参数（如表面附着系数、载荷偏心、隐蔽门禁逻辑）的解耦能力；遭遇单次局部失败时，往往将失败直接投影在空间坐标或粗粒度动作上，导致严重的**错误泛化与陈旧阻断（Stale Blocking）**，即使换用不同速度、轻质载荷或环境恢复后仍盲目绕行。
- **符号/几何约束学习（如 TAMP 前置条件学习、反事实推断）**：普遍假设环境状态完全可观测或失败因果链确定，通过静态反例拟合可行域边界；缺乏对“不可观测潜变量”的主动识别手段，无法在多重竞争解释中实施带成本的物理探针交互。
- **大模型反思与定性诊断（如 REFLECT, Reflexion）**：依赖事后文本总结生成单次修复步骤（Single-episode Correction），不构建显式、可复用、带置信边界的几何/参数化约束模型，更缺乏对约束“何时适用、何时失效、何时跨任务迁移”的严谨维护机制。

**核心缺失**：现有体系缺失一套能够在**潜变量不完全可观测**、**探测动作存在时间/能耗/风险成本**的双重约束下，**自主通过最经济的探针主动判明失败根因，并将“失败经验”提炼为具有明确适用参数范围、动态自愈生命周期的可复用决策约束**的严密数学机制。

### 2. 我们提出什么？
我们提出 **SCOPE-VERIFY（基于有限代价主动核验的失败约束适用范围学习与自愈机制）**。该方法不以“给记忆数据库堆砌字段/状态机”为目标，而是建立一个在决策前评估“直接执行风险、绕行代价、探针核验收益”的**元决策控制闭环**：
- 将失败约束形式化为三元组 $\langle a, \Omega_x, \mathcal{B}_z \rangle$：在动作 $a$、可见环境与任务上下文 $x \in \Omega_x$、以及隐藏物理状态信念 $\mathcal{B}_z$ 的联合空间中界定不可行域；
- 维护约束的**适用范围边界（Applicability Scope Boundary）**，将环境潜变量的未知性显式纳入规划；
- 在再次面临潜在冲突任务时，不盲目规避也不盲目重试，而是按“单位成本信息增益（Cost-normalized VoI）”计算是否值得调用局部低成本物理探针（如微幅力矩试探、主动声光/深度感知），以最小化全生命周期的任务累计总成本。

### 3. 方法的新步骤在哪里？
不同于传统“失败 $\rightarrow$ 标记阻断 $\rightarrow$ 静态绕行”或“盲目全量感知”的机制，SCOPE-VERIFY 引入了三个具有明确数学定义的创新步骤：
1. **多重溯因假设生成与等价类归并（Abductive Hypotheses Generation with Equivalence Partitioning）**：单次物理失败发生时，基于物理守恒与运动学模型分解出可见上下文相关的潜在假说集 $\mathcal{H} = \{h_1, \dots, h_K\}$，并自动根据机器人当前可用传感器/探针的可识别矩阵，将无法区分的假说归并为最小可测等价类，杜绝伪因果虚假推断。
2. **代价约束下的最优探针序列规划（Budgeted Information-Theoretic Probing）**：将后续核验决策构建为非近视（Non-myopic）的期望任务代价极小化问题，权衡 $\text{Cost}(v)$、潜在碰撞惩罚 $C_{\text{fail}}$ 与绕行惩罚 $C_{\text{detour}}$，仅在“探针收益大于其执行成本”时触发主动核验。
3. **基于正反例支撑向量与时间衰减的双轨范围自愈（Dual-track Scope Shrinking & Revocation）**：当核验或变参数成功穿越发生时，通过支持向量机（SVM）的 $\alpha$-边界自适应收缩 $\Omega_x$；同时利用非齐次泊松过程追踪环境潜在跳变，在置信度退化到先验时自动解除陈旧阻断。

### 4. 预计解决什么实际问题？
解决移动操作/复杂移动机器人在非结构化、部分可观测环境中长期自主运行时普遍存在的两大痛点：
- **陈旧过度保守（Over-conservative Stale Detouring）**：一处路面由于临时积水打滑一次后，传统系统永久禁止所有机器人在此通行，造成持续巨大的无谓绕行开销。SCOPE-VERIFY 能精确识别出“仅当载荷 $> 5\,\text{kg}$ 且速度 $> 0.4\,\text{m/s}$ 时才打滑”，并能在环境风干后通过单次低成本摩擦探针自愈恢复全速通行。
- **同类隐蔽陷阱重复掉入（Blind Failure Recurrence）**：在遇到视觉外观相似但隐蔽摩擦力骤降、或隐蔽高度限幅的未知区域时，单纯条件缓存因外观微小变异无法匹配而重复撞击。SCOPE-VERIFY 能通过参数范围外推预测潜在风险，主动降速微探，消灭重复硬性破坏。

### 5. 什么结果会否定它？
本设计预先设定了**不可动摇的证伪标准（Falsification Criteria）**。在后续评测中，出现下列任意情况即宣告该方法理论价值不成立，坚决执行终止（No-Go）：
1. **基线等效否定**：在涵盖多载荷、动态路面与隐蔽门禁的标准化基准测试中，一个简单的“上下文条件缓存 + 指数退避 TTL + 贪心被动降速”策略在全序列累计任务成本上与 SCOPE-VERIFY 统计无显著差异（$p > 0.05$）；
2. **核验净损耗否定**：在复杂长序列任务中，主动探针引入的时间与动作成本累计值，超过了其所挽回的失败损失与绕行节省总和（探针收益为负）；
3. **不可识别性崩塌**：在真实物理噪声干扰下，探针观测似然矩阵条件数过高，导致范围边界收缩震荡，误阻断率（False Positive Blockage）高于 25%；
4. **人工先验依赖**：该方法必须依赖人工预设的精细物理方程才能工作，一旦切换至未见物理属性（如粘弹性地面、软体接触），算法退化为随机盲测。

---

## 一、候选核心问题与方法目标

### 1.1 核心研究问题界定

在经典机器人体系中，环境的物理属性（如摩擦力、接触阻抗、电磁干扰、动态机构锁闭、瞬态热漂移）通常无法直接通过前向视觉或 2D 激光雷达全局观测。当机器人在执行高级动作（如高速重载导航、窄道穿越、机构按压）遭受失败时，底层控制栈（如 Nav2、MoveIt）通常返回通用的超时（Timeout）或控制器中止（Aborted）。

由此产生核心研究问题：
> **“在失败原因与适用范围不完全可观测的情况下，机器人如何通过有限、带成本的核验，从失败经历中学习可复用的决策约束，并避免错误泛化、重复失败与陈旧阻断？”**

这里的科学核心是：**“失败约束的适用范围（Applicability Scope）究竟如何由证据驱动归纳并维持自愈，而不是事后给记忆库打标签或人工预定义规则”。**

### 1.2 候选方法目标与本质聚焦

- **拒绝伪创新**：系统既不把“多建几个 SQLite/JSON 字段”称为创新，也不把“给大模型写一段 Prompt 让其诊断”称为创新，更不把“状态机流转与 SHA256 哈希审计”作为算法新颖性。
- **方法本质目标**：构建一个数学严密的**元决策闭环**，形式化为：
  $$\pi^*_{\text{meta}}: \mathcal{H}_{\text{history}} \times x \to \{\text{Execute}(a), \text{Detour}(a'), \text{Probe}(v_k)\}$$
  通过主动调度具有物理边际成本的核验探针 $v_k \in \mathcal{V}$，以最小的信息获取成本，最大限度收敛隐藏故障原因的后验分布，进而精确刻画不可行域在参数化上下文中的边界 $\partial \Omega_x$。

### 1.3 核心边界与否定触发预警

本研究必须直面以下严峻事实：
1. 若文献调研表明“约束范围学习 + 主动核验”在本质上只是已有 TAMP 或 POMDP 在特定 ROS 场景下的朴素拼凑，无任何理论增量，必须立即收缩或否定；
2. 若现实物理环境中绝大多数失败因传感器分辨率限制完全不可区分（Identifiability Failure），则主动核验的数学根基失效，必须直接宣告该方向不可行；
3. 本文坚持客观独立评估，绝不以“维护既往工作意义”为目标。

---

## 二、最接近已有方法精读与文献差异表

为杜绝“闭门造车”与“文献稻草人”，本节精读四大相关领域的开创性与最新原始论文，明确其具体章节、核心公式与已知边界。

### 2.1 四大领域最接近文献精读与定位

#### 领域 1：动作条件化通行性与经验规划（Action-conditioned Traversability & Experience Navigation）
1. **BADGR (Kahn et al., IEEE RA-L 2021)**
   - *文献定位*：G. Kahn, P. Abbeel, S. Levine, "BADGR: An Autonomous Self-Supervised Learning-Based Navigation System", IEEE Robotics and Automation Letters (RA-L), vol. 6, no. 2, pp. 1312–1319, 2021. ([arXiv:2002.05700](https://arxiv.org/abs/2002.05700))
   - *精读重点*：Section III-D（Predictive Model）与 Section III-E（Planning）。模型为 $f_\theta(\mathbf{o}_t, \mathbf{a}_{t:t+H}) \to \hat{\mathbf{e}}^{0:K}_{t:t+H}$，利用循环神经网络在自监督无标注交互中预测未来事件（碰撞、颠簸度、位置）。
   - *能力边界*：BADGR 采用端到端连续策略优化（Zeroth-order stochastic optimizer）。其通行性完全是**黑盒图像特征与速度的统计相关性**，不具备显式因果假说，无法执行离散物理探针核验；更致命的是，当遇到外观未见但物理属性相同的场景时，泛化缺乏边界保障；且无显式“约束撤销/自愈”机制，环境非平稳变化时必须收集数小时数据并全量微调。
2. **E-Graphs (Phillips et al., IJRR 2012) & Lightning (Berenson et al., IJRR 2012)**
   - *文献定位*：
     - M. Phillips et al., "E-Graphs: Bootstrapping Planning with Experience Graphs", International Journal of Robotics Research (IJRR), vol. 31, no. 10, pp. 1159–1175, 2012.
     - D. Berenson et al., "A Robot Path Planning Framework for Adaptive Experience Reuse", IJRR, vol. 31, no. 10, pp. 1237–1254, 2012.
   - *精读重点*：E-Graphs 中通过边权重修改（Edge Weight Penalization）隔离失效路段；Lightning 在模块 Repair Path 中直接删除发生碰撞的离散路径点。
   - *能力边界*：其经验库仅存在于几何构型空间 $\mathcal{C}$ 中。失效仅与特定空间坐标 $(x, y, \theta)$ 绑定，**完全不感知上下文条件**（如载荷、当前转弯角速度、底盘偏航惯量）。一旦环境轻微变异，几何图失效；且无主动核验环节，必须直接尝试整条路径，发生硬碰撞后才被动修复。

#### 领域 2：失败诊断、约束学习与负经验复用（Failure Diagnosis, Constraint Learning & Negative Reuse）
1. **REFLECT (Liu et al., CoRL 2023)**
   - *文献定位*：Z. Liu, A. Bahety, S. Song, "REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction", Conference on Robot Learning (CoRL), PMLR 229:3468–3484, 2023. ([arXiv:2306.15724](https://arxiv.org/abs/2306.15724))
   - *精读重点*：Section 3.1（Hierarchical Robot Summary）与 Section 3.2（Progressive Failure Explanation）。基于多模态传感器（视/听/接触）生成场景图 $G_t = \{N, E\}$，并用 LLM 生成“为什么失败”的自然语言总结。
   - *能力边界*：REFLECT 是**单次任务的事后定性解释器（Post-hoc Episodic Debugger）**。其输出是指导当前任务重试的文本（如 "toggle_off burner-2"），**不提炼跨任务的可复用决策约束**；不维护数学化的不可行参数流形，不评估未来新任务中的误阻断风险，也不包含主动探针的信息价值决策。
2. **广义几何前置条件学习 (Wang et al., ICRA 2018)**
   - *文献定位*：Z. Wang, C. R. Garrett, L. P. Kaelbling, T. Lozano-Pérez, "Learning Generalized Geometric Preconditions for Robot Task and Motion Planning", IEEE ICRA, 2018. ([arXiv:1804.03215](https://arxiv.org/abs/1804.03215))
   - *精读重点*：Section IV。针对 TAMP 动作原语，通过分类器（高斯过程/SVM）学习连续几何构型到可行性的映射 $P(\text{feasible} \mid s, a)$。
   - *能力边界*：**假设环境 3D 几何完全可观测**。输入特征依赖完美的物体 Mesh 与 6D 位姿；失败机理被假设为确定性几何干涉；完全没有涉及由摩擦力、隐藏阻尼、时变外力导致的**部分可观测潜变量故障**，不具备带成本主动试探的能力。
3. **基于示教的约束学习 (Chou et al., RSS 2020 / IJRR 2021)**
   - *文献定位*：G. Chou, N. Ozay, D. Berenson, "Learning Constraints from Demonstrations with Predictable Generalization", Robotics: Science and Systems (RSS), 2020.
   - *精读重点*：利用凸包与 SVDD 拟合安全可行域 $C(x) \le 0$，给出 PAC 风格的泛化误差上界 $\epsilon, \delta$。
   - *能力边界*：假设所有轨迹为可行正样本；主要处理安全避障边界；不适用于系统发生运行崩溃后的反事实因果诊断与自发主动探针交互。

#### 领域 3：主动学习、信息价值（VoI）与带成本核验（Active Learning, VoI & Costly Probing）
1. **经典信息价值理论 (Howard 1966) 与非近视信息采集 (Krause & Guestrin 2005)**
   - *公式核心*：
     $$\text{VoI}(e) = \mathbb{E}_y \left[ \max_{a \in \mathcal{A}} \mathbb{E}_{s}[U(a, s) \mid y] \right] - \max_{a \in \mathcal{A}} \mathbb{E}_{s}[U(a, s)]$$
   - *能力边界*：经典 VoI 假设**状态空间、动作效用函数及传感器似然模型 $P(y \mid s)$ 完全已知**。机器人仅计算静态决策树的边际增益。但在真实非结构化任务中，**失败的假设空间本身是开放且非平稳的**，先验分布未知，单纯套用静态 VoI 无法解决“假设从未见场景中动态生成”的问题。
2. **信念空间任务与动作规划 (Kaelbling & Lozano-Pérez, IJRR 2013)**
   - *文献定位*：L. P. Kaelbling, T. Lozano-Pérez, "Integrated Task and Motion Planning in Belief Space", IJRR, vol. 32, no. 9–10, pp. 1194–1227, 2013.
   - *精读重点*：将未知状态维护为概率分布（Belief State），并将感知动作显式建模为产生观测的分支转移。
   - *能力边界*：必须预先由专家手写完整的 POMDP 观测算子（Observation Operators）；当出现未曾建模的物理机制失效时，信念转移矩阵无法更新；计算复杂度随信念维度呈指数爆炸，难以支撑长序列自适应演化。

#### 领域 4：动态环境中的记忆失效与变化检测（Dynamic Invalidation & Change Detection）
1. **动态地图维护 (Biber & Duckett, RSS 2005 / RAS 2009)**
   - *核心机制*：多时标样本衰减，通过空间样本的存活时间淘汰移动障碍物。
2. **频域时变增强地图 Fremen (Krajnik et al., IEEE TRO 2017)**
   - *核心公式*：将空间网格占用概率 $p(x, t)$ 进行离散傅里叶展开，提取周期性状态变迁。
   - *能力边界*：仅建模“空间点 $(x, y)$ 在时刻 $t$ 是否被占据”。它们无法表达**与机器人自身状态耦合的条件性约束**（例如：“此门对空载慢速车辆可行，但对装载重液体的快速车辆不可行”）；将纯粹的物理条件差异误判为纯时间非平稳性。

---

### 2.2 关键质疑专项剖析

为了彻底打消学术包装嫌疑，必须直接回答以下三个尖锐问题：

#### 质疑 1：约束适用范围学习是否已有？
- **结论：已有方法解决了“全观测连续几何特征下的通行分类”，但缺失了“部分可观测潜变量与多任务上下文耦合下的范围学习”。**
- **严密对比**：Wang et al. (ICRA 2018) 学习的是 $P(\text{success} \mid \text{mesh\_pose}, a)$，依赖几何全观测；Chou et al. 学习的是状态空间的凸约束。然而在现实机器人应用中，失败往往由**跨模态参数耦合**引发（如：载荷质量 $M$ + 速度 $v$ + 表面摩擦系数 $\mu$ + 转向曲率 $\kappa$）。现有方法要么将其当作黑盒深度神经网络拟合（样本需求量极大且无边界），要么只能处理全观测欧氏空间障碍物。

#### 质疑 2：主动核验是否只是标准信息价值（VoI）策略？
- **结论：如果只在固定贝叶斯网络上计算一次探针选择，100% 就是标准 VoI，毫无新颖性。**
- **实质突破点必须落在**：
  1. **假设空间自适应构建**：标准 VoI 假设状态与假说预设，本方案从非结构化失败执行日志中反向溯因出最小竞争假说集 $\mathcal{H}_z$；
  2. **等价类与不可识别性坍缩**：当多个物理假说在当前探针空间不可辨识时，算法必须给出决策等价类；
  3. **非齐次成本结构**：探针动作不仅消耗时间 $c(v)$，还具有侵入性物理风险 $r(v)$（如低速推门可能导致门锁机械损坏或机器人轻微失衡），必须建立风险敏感的元决策机制。

#### 质疑 3：跨任务收益是否已有经验规划方法完全覆盖？
- **结论：经验规划（E-Graphs/Lightning）覆盖了“几何路径的复用”，但无法覆盖“参数化负约束的抽象复用”。**
- **严密对比**：E-Graphs 复用的是一条由 Waypoints 构成的折线。如果环境中某个走廊在特定载荷下打滑，E-Graphs 只能通过在整网格中反复搜索被阻断的边来更新图结构，无法将“遇此材质降速 50% 即可通行”的规则抽象外推至完全不相交的另一个走廊中。

---

### 2.3 最接近方法比较表

| 维度 / 方法 | 代表作 | 重合部分 | 关键缺陷 / 候选差异 | 待严格验证事项（Falsification Check） |
| :--- | :--- | :--- | :--- | :--- |
| **动作条件化通行性** | BADGR (RA-L 2021) | 考虑动作与传感器观测的映射 | **黑盒连续拟合，无显式因果假说，无主动探针机制，无法自愈撤销陈旧阻断** | 验证结构化约束在样本效率与未见工况外推上是否显著优于端到端模型 |
| **几何经验规划** | E-Graphs (IJRR 2012), Lightning (IJRR 2012) | 记录历史失败路段并避免再次发生碰撞 | **仅限构型空间 $\mathcal{C}$ 坐标，不感知任务上下文（载荷/速度），导致严重错误泛化阻断** | 验证引入上下文范围（$\Omega_x$）后，是否能消除不必要的几何大绕行 |
| **大模型反思** | REFLECT (CoRL 2023), Reflexion (NeurIPS 2023) | 利用多模态信息解释失败原因 | **仅做单步文本修复（Episodic Repair），不生成参数化数学约束，不跨任务维护** | 验证参数化约束在跨任务复用时的零样本阻断收益是否显著高于每次重新调用 LLM |
| **TAMP 前置条件学习** | Wang et al. (ICRA 2018), Garrett et al. (2021) | 学习动作可行域的分类器边界 | **假设 3D 几何完全可观测，无法处理摩擦力/隐蔽门禁等潜变量，无带成本主动探针** | 验证引入隐藏潜变量 $\mathcal{B}_z$ 与主动探针后，在部分可观测物理场景中的成功率优势 |
| **主动感知 / VoI** | Howard (1966), Kaelbling (IJRR 2013) | 带代价的信息获取与效用折现 | **假设固定先验分布与静态因果图，无法自发从失败中归纳假设与生命周期自愈** | 验证在动态开放假说下，基于失败溯因的核验调度是否优于无上下文被动感知 |
| **时变动态地图** | Fremen (TRO 2017), Biber (RSS 2005) | 随时间衰减或周期性建模障碍物 | **仅建模点位几何占用 $P(O)$，无法区分是“时间流逝”还是“任务物理工况变化”** | 验证能否严格解耦“时间漂移”与“工况变异”，杜绝震荡误判 |

### 2.4 新颖性边界判定

基于上述对比，我们做出严谨判定：
> **判定结论**：若且仅若本研究将重点严格锁定在**“不可观测物理潜变量下的最小假说溯因”、“基于上下文与风险成本的探针元决策”以及“参数化约束适用范围的自愈维护”**这一完整闭环上，其学术新颖性成立。
> 
> 反之，若退化为“调用 LLM 生成一段故障文本存入向量库”，或者“预先给定完全已知的贝叶斯网络直接算 VoI”，**则判定新颖性不成立，属于既有工作的无意义重包装**。

---

## 三、问题形式化

为使后续算法可计算、可推导、可证伪，本节建立严格的数学定义。

```mermaid
flowchart TD
    subgraph Reality [真实物理世界（部分可观测）]
        S[真实状态 s = (x, z)]
        X[可见上下文 x: 载荷质量 M, 期望航速 v, 门宽 W, 几何点云]
        Z[隐藏潜变量 z: 地面附着系数 μ, 机构闭锁 D, 底部隐蔽凸起 h]
    end
    
    subgraph Execution [执行与失败触发]
        A[机器人动作 a: 导航航路 e, 期望速度档位]
        Exec[物理交互转移]
        Y{执行结果 y}
        Succ[成功: y = success]
        Fail[失败: y = failure 报错/滑移/超时]
    end
    
    subgraph Reasoning [SCOPE-VERIFY 元决策核心]
        Abduct[逆向溯因: 生成最小假说集 H = {h_1, ..., h_K}]
        Equiv[不可识别性等价类归并]
        VoI[代价敏感主动核验决策]
        Probe[执行核验探针 v_k: 微力矩滑移探测 / 局部主动感知]
        Update[更新后验 B_z 与范围边界 ∂Ω_x]
    end

    S --> X
    S --> Z
    X --> Exec
    Z --> Exec
    A --> Exec
    Exec --> Y
    Y -- 失败 --> Abduct
    Abduct --> Equiv
    Equiv --> VoI
    VoI --> Probe
    Probe --> Update
    Update -->|生成约束 C| A
```

### 3.1 决策对象与动作空间

考虑一个在连续时间、离散阶段执行任务的自主机器人。在任务规划阶段 $t$，机器人的**决策对象**为元组：
$$a_t = \langle \text{Path}_t, \mathbf{u}_t \rangle \in \mathcal{A}$$
- $\text{Path}_t \in \mathcal{P}$：拓扑拓扑导航走廊、路径通道或末端抓取轨迹；
- $\mathbf{u}_t \in \mathcal{U}$：受控执行参数，包含名义航速 $v_{\text{cmd}} \in [v_{\min}, v_{\max}]$、加速度限制 $a_{\max}$、接触阻抗/抓握力阈值 $F_{\text{limit}}$。

### 3.2 可见信息、条件与观测空间

在执行决策前，机器人可直接读取的**可见信息上下文（Visible Context）**记为 $x_t \in \mathcal{X} \subset \mathbb{R}^{d_x}$：
$$x_t = \big( \mathbf{p}_{\text{start}}, \mathbf{p}_{\text{goal}}, M_{\text{load}}, \mathbf{r}_{\text{com}}, W_{\text{geom}}, T_{\text{visual}}, \tau_{\text{tod}} \big)$$
- $\mathbf{p}_{\text{start}}, \mathbf{p}_{\text{goal}}$：起止点与当前空间拓扑节点；
- $M_{\text{load}} \in \mathbb{R}^+$：当前搬运物体的质量（由机械臂腕部六维力/力矩传感器或调度清单直接读取）；
- $\mathbf{r}_{\text{com}} \in \mathbb{R}^3$：载荷标称质心偏移量；
- $W_{\text{geom}}$：车载 2D 激光雷达测得的名义几何走廊有效净宽；
- $T_{\text{visual}} \in \{\text{paved}, \text{tile}, \text{metal}, \text{rubber}\}$：表面视觉纹理分类标签；
- $\tau_{\text{tod}}$：当前任务执行时刻的时间戳（用于评估时变衰减）。

历史执行日志记为 $\mathcal{D}_{1:t-1} = \{(x_\tau, a_\tau, y_\tau)\}_{\tau=1}^{t-1}$，其中 $y_\tau \in \{\text{success}, \text{failure}\}$。

### 3.3 隐藏潜变量与环境不完全可观测性

真实环境的完整物理状态为 $s_t = (x_t, z_t) \in \mathcal{S}$，其中 $z_t \in \mathcal{Z} \subset \mathbb{R}^{d_z}$ 为**隐藏潜变量（Hidden Latent Factor）**，无法通过常规名义传感器直接全局感知：
$$z_t = \big( \mu_{\text{friction}}, D_{\text{latch}}, h_{\text{bump}}, H_{\text{clearance}}^{\text{neg}} \big)$$
- $\mu_{\text{friction}} \in [0.05, 0.9]$：接触面真实等效摩擦系数（例如地面隐蔽油污、积水、清洁剂打蜡，视觉上具有高混淆度）；
- $D_{\text{latch}} \in \{0, 1\}$：防火门/推拉门的机械闭锁状态（锁止 vs 未锁，无法从 2D 点云直接推断）；
- $h_{\text{bump}} \in [0, 5\,\text{cm}]$：路面软胶减速带下方隐藏的刚性台阶高度；
- $H_{\text{clearance}}^{\text{neg}} \in \mathbb{R}^+$：2D 激光雷达盲区处的悬空障碍物垂直净空。

**真实物理可行性映射**由隐藏物理定律决定：
$$f^*: \mathcal{X} \times \mathcal{Z} \times \mathcal{A} \to \{0, 1\}$$
当 $f^*(x, z, a) = 0$ 时，底层控制栈（如 Nav2 Controller / Recovery）必将触发硬故障中断 $y = \text{failure}$，并引发巨大时间惩罚与重置代价。

### 3.4 候选约束与其适用范围表示

机器人从失败中归纳并维护的知识单元称为**候选失败约束（Candidate Failure Constraint）** $\mathcal{C}_k$，形式化为三元组：
$$\mathcal{C}_k = \langle a^{(k)}, \Omega_x^{(k)}, \mathcal{B}_z^{(k)} \rangle$$
1. **关联动作模式 $a^{(k)}$**：该约束管辖的特定执行动作（如“高速通过走廊 3”）；
2. **可见适用范围流形 $\Omega_x^{(k)} \subseteq \mathcal{X}$**：约束在可见特征空间中的适用范围几何体。我们采用支持向量紧凑包络（Support Vector Data Description, SVDD）或超矩形带间隔边界（Interval Bound with Slack）：
   $$\Omega_x^{(k)} = \left\{ x \in \mathcal{X} \;\middle|\; \Phi_k(x) \ge 0 \right\} = \left\{ x \;\middle|\; \mathbf{w}_k^T \psi(x) + b_k \ge 0 \right\}$$
   例如：$\Omega_x = \{ (M, v) \mid M \ge 4.5\,\text{kg} \wedge v \ge 0.35\,\text{m/s} \}$；
3. **隐藏因果假说后验信念 $\mathcal{B}_z^{(k)}$**：对引起该失败的潜变量解释的概率分布：
   $$\mathcal{B}_z^{(k)} = P(z \mid \mathcal{D}_{\text{evidence}}^{(k)}) = \sum_{j=1}^{m} w_j \mathcal{N}(\bar{z}_j, \Sigma_j) \quad \text{或离散假说分布} \quad P(h_j \mid \mathcal{D})$$

- **约束判决规则**：
  若当前任务上下文 $x \in \Omega_x^{(k)}$，且后验失效概率 $\mathbb{P}_{\mathcal{B}_z}[f^*(x, z, a)=0] > \theta_{\text{risk}}$，则约束被激活（Active）。机器人不得直接放行动作 $a$。

### 3.5 核验动作库、信息增益与代价模型

机器人在遇到激活约束时，并非只能非黑即白地选择“盲目冒险”或“大范围绕行”，而是拥有一组**局部带成本主动核验探针（Verification Probes）** $\mathcal{V} = \{v_1, v_2, \dots, v_m\}$。

每个探针 $v \in \mathcal{V}$ 具有严格的物理与信息属性：
1. **执行成本 $c(v) > 0$**：执行探针所需的时间、算力或电池能耗（秒/焦耳）；
2. **物理风险 $r(v) \in [0, 1)$**：探针造成环境扰动或微碰撞的先验风险概率；
3. **观测通道与似然模型 $P(o_v \mid z)$**：探针返回的离散或连续观测值 $o_v \in \mathcal{O}_v$。

| 探针编号 $v$ | 物理操作动作 | 目标排除解释 | 时间成本 $c(v)$ | 物理扰动风险 $r(v)$ | 观测似然模型 $P(o_v \mid z)$ |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **$v_{\text{traction}}$** | 原地施加 $0.05\,\text{s}$ 微小力矩脉冲，对比轮速计与 IMU 积分 | 区分表面湿滑 $\mu < 0.25$ 与驱动器虚脱 | $1.5\,\text{s}$ | 0.00 | 高斯白噪测量 $\hat{\mu} \sim \mathcal{N}(\mu, \sigma_\mu^2)$ |
| **$v_{\text{push}}$** | 以 $0.03\,\text{m/s}$ 极低速并设力矩上限推顶门缝 | 区分机械门锁死 ($D=0$) 与通行阻力 | $4.5\,\text{s}$ | 0.03（可能轻擦门板） | 接触力反馈 $F > F_{\text{th}} \implies D=0$ |
| **$v_{\text{tilt3D}}$** | 俯仰驱动 RGB-D 相机扫描上方盲区 | 区分垂直净空受限与地面障碍 | $2.5\,\text{s}$ | 0.00 | 点云障碍物存在性概率 |
| **$v_{\text{iot\_query}}$** | 查询楼宇物业保洁与维护系统 API | 获取该区域地面打蜡/施工的先验概率 | $0.4\,\text{s}$ | 0.00 | 存在网络丢包与滞后时间差 |

### 3.6 任务全生命周期累计成本目标函数

评价一个方法优劣，绝不能只看“后续执行成功率”，也不能只看“探针调用次数”。必须建立**全生命周期序列累计任务成本函数（Cumulative Task Cost, CTC）**。

在连续 $T$ 个任务序列中，机器人的累计总损失定义为：
$$J_{\text{total}} = \sum_{t=1}^T \Big( C_{\text{nominal}}(a_t) + \sum_{v \in \mathcal{V}_t} c(v) + \mathbb{I}(a_t \text{ detours}) \cdot C_{\text{detour}} + \mathbb{I}(y_t = \text{failure}) \cdot C_{\text{fail}} + C_{\text{meta}}(t) \Big)$$
- $C_{\text{nominal}}(a)$：标称无故障通行时间（通常为基准值，如 $15\,\text{s}$）；
- $c(v)$：所有调用探针的直接耗时；
- $C_{\text{detour}}$：被迫绕行备用路线产生的额外耗时（如 $+45\,\text{s}$）；
- $C_{\text{fail}}$：执行失败的灾难性惩罚（包含 Nav2 多次重试、超时等待、陷入死区以及人工介入复位，通常巨大，如 $120\,\text{s}$）；
- $C_{\text{meta}}(t)$：算法自身的计算与求解开销（要求在百毫秒以内）。

**优化目标**：学习最优元策略 $\pi^*_{\text{meta}}$，使期望累计总成本最小化：
$$\pi^*_{\text{meta}} = \arg\min_\pi \mathbb{E}_{\{x_t, z_t\}} [J_{\text{total}}]$$

### 3.7 理论假设、公理与极限情况深入讨论

为保证科学严谨性，必须直面以下四个根本理论命题：

#### 命题 1：不可识别解释的等价类归并（Observational Equivalence & Identification）
- **问题**：如果两种失败解释 $h_1$（如“地面附着力过低导致轮子打滑”）与 $h_2$（如“电机驱动器过热发生降额限流”），在机器人当前携带的所有探针与车载传感器观测下，具有完全相同的联合分布：
  $$\forall v \in \mathcal{V}, \quad P(o_v \mid h_1, x) \equiv P(o_v \mid h_2, x)$$
- **定理（不可识别等价性原理）**：机器人系统**严禁在没有统计证据支持的前提下，擅自向用户或规划器输出单一物理归因**。
- **形式化解法**：算法将所有在当前探针子空间 $\mathcal{V}$ 下全等可观测的因果假说，自动合并为一个**决策等价类（Decision Equivalence Class）** $[h]_v = \{h_1, h_2\}$。决策器仅针对等价类制定防御约束，禁止使用幻觉因果进行细粒度拆分。

#### 命题 2：证据不足时的学习/不学习决策边界（Principle of Cautious Learning）
- **问题**：仅遭遇 1 次孤立失败，能否立刻学出参数边界 $\Omega_x$？
- **论证**：高维空间单点不可插值。在样本数 $N=1$ 时，若直接通过连续分类器拟合边界，极易发生灾难性过拟合（Overfitting），导致将全局不相干的特征（如“发生失败时环境照度为 300 Lux”）误判为约束条件。
- **形式化解法**：采用**双层证据累积机制**。
  - $N=1$ 时，仅在局部生成一个以该数据点为中心的**保守近邻信任球（Local Confidence Ball）** $B_\epsilon(x_1)$，并将假说后验置于不确定性最大熵状态；
  - 只有当后续探针或不同参数的探索样本达到支持向量最小统计显著性阈值（$N \ge K_{\text{min}}$）时，才触发超矩形/超多面体流形解算。

#### 命题 3：时间变化（Non-stationarity）与条件变化（Condition Shift）的解耦机制
- **问题**：走廊 3 上午因保洁打蜡打滑导致失败，下午恢复正常。如果简单设置时间 TTL（Time-To-Live），在打蜡未干时提前放行会导致重复摔倒；若永久保留约束，又会导致陈旧阻断。
- **数学解耦模型**：我们将隐藏状态 $z_t$ 的演化建模为**跳跃马尔可夫驱动过程（Jump-Markov Process）**：
  $$z_t = \begin{cases} z_{t-1}, & \text{with prob } 1 - \lambda \Delta t \\ z' \sim P_{\text{prior}}(z), & \text{with prob } \lambda \Delta t \end{cases}$$
  约束的有效性不是简单依绝对时间清零，而是其后验置信度随着时间流逝向先验分布 $P_{\text{prior}}(z)$ 发生**信息熵扩散（Entropy Diffusion）**：
  $$P(z_t \mid \mathcal{D}_{\tau}) = (1 - e^{-\lambda (t - \tau)}) P_{\text{prior}}(z) + e^{-\lambda (t - \tau)} P(z_\tau \mid \mathcal{D}_\tau)$$
  当扩散导致失效率期望低于容忍阈值时，自动触发一次极低成本的**“自愈探针（Revocation Probe）”**或允许低速受控试探，而非硬性阻断。

#### 命题 4：相关性与因果约束的识别条件（Causality vs Correlation）
- **问题**：机器人运送蓝色箱子时在门前失败，运送红色箱子时成功。能否判定“箱子颜色是失败约束条件”？
- **因果干预公理**：纯粹观察到的联合概率 $P(y = \text{fail} \mid X_{\text{color}} = \text{blue})$ 包含混杂偏差（Confounding Bias）。要确立 $X_i$ 为因果约束维度，必须满足 Pearl 因果后门准则，或通过**主动物理干预（Intervention $\text{do}(a)$）**。
- **规则**：本方法的特征空间必须经过**物理语义正交解耦**。只将能够直接进入动力学、运动学或几何干涉方程的物理物理量（质量、尺寸、速度、抓握力、表面法向量）列入候选约束边界学习维度，一切无直接物理耦合机制的环境表象特征（颜色、日期等）默认禁止作为约束超平面的划分轴，从根源掐死虚假因果。

---

## 四、具体候选方法设计（SCOPE-VERIFY 最小模型）

本节给出候选方法 **SCOPE-VERIFY** 的最小化闭环设计。坚决不堆叠无关模块，所有步骤均有可推导的数学公式支撑。

### 4.1 失败触发与多重候选解释溯因生成

当底层执行发生异常终止时（Nav2 返回 `ABORTED` 或跟踪误差超标），算法触发溯因解释器（Abductive Reasoner）：

1. **失败上下文快照捕获**：提取瞬态特征向量 $x_{\text{fail}} = (M, v, W, T)$ 与底层物理遥测数据（电机电流 $I(t)$、轮速滑移率 $s(t)$、激光测距残差 $\delta r(t)$）。
2. **基于运动学/动力学不变量的假设空间投影**：
   通过预置的一组极其通用的基础物理不变量规则（Physical Invariants），将底层遥测映射到高层因果候选集 $\mathcal{H}_z$：
   - 若 $\max s(t) > s_{\text{slip\_th}} \implies h_{\text{slip}}$: 地面附着力不足（$\mu < \mu_{\text{crit}}(M, v)$）；
   - 若 $\max I(t) > I_{\text{stall\_th}} \wedge s(t) \approx 0 \implies h_{\text{block}}$: 物理机构机械卡滞或隐蔽台阶过高；
   - 若激光测距显示局部动态簇但全局地图未标注 $\implies h_{\text{dynamic}}$: 临时走动人员堵塞；
   - 若均不满足 $\implies h_{\text{unknown}}$: 未建模环境异常。
3. **初始化离散先验分布**：
   $$P(h_j \mid x_{\text{fail}}) = \frac{\exp(-\text{Loss}_{\text{physics}}(h_j))}{\sum_k \exp(-\text{Loss}_{\text{physics}}(h_k))}$$

### 4.2 贝叶斯后验与范围边界联合更新

假设施加了探针或受控试探并获得了观测 $o_v$，假说后验依标准贝叶斯法则更新：
$$P(h_j \mid o_v) = \frac{P(o_v \mid h_j) P(h_j)}{\sum_{k} P(o_v \mid h_k) P(h_k)}$$

在可见参数空间 $\mathcal{X}$ 中，适用范围边界 $\Omega_x$ 的更新采用**自适应带松弛支持向量数据描述（SVDD with Margin Slack）**：
- 设历史在相同物理机制下引发失败的样本集合为 $\mathcal{D}_{\text{fail}} = \{x_1^-, \dots, x_{N_-}^-\}$；
- 成功穿越或轻载慢速穿越的成功样本集合为 $\mathcal{D}_{\text{succ}} = \{x_1^+, \dots, x_{N_+}^+\}$；
- 求解二次规划（QP）界定不可行凸包：
  $$\min_{\mathbf{w}, b, \xi} \frac{1}{2} \|\mathbf{w}\|^2 + C_1 \sum_{i \in \mathcal{D}_{\text{fail}}} \xi_i + C_2 \sum_{j \in \mathcal{D}_{\text{succ}}} \zeta_j$$
  $$\text{s.t.} \quad \mathbf{w}^T \psi(x_i^-) + b \ge 1 - \xi_i, \quad \mathbf{w}^T \psi(x_j^+) + b \le -1 + \zeta_j, \quad \xi_i, \zeta_j \ge 0$$
由此得到的不可行超平面 $\mathbf{w}^T \psi(x) + b = 0$ 构成了显式约束适用范围边界 $\partial \Omega_x$。

### 4.3 任务导向的主动核验决策策略

当新任务到来，具有可见上下文 $x_{\text{new}}$ 时，机器人面临三难抉择：
1. **直接执行（Direct Action）**：风险为潜在失败成本；
2. **保守绕行（Detour）**：必定付出恒定绕行开销 $C_{\text{detour}}$；
3. **主动探针（Invoke Probe $v$）**：付出 $c(v)$ 换取后验熵减，随后做出更有依据的决策。

**期望效用计算**：
- 若直接执行动作 $a$：
  $$\mathbb{E}[\text{Cost} \mid \text{Direct}] = P(\text{fail} \mid x_{\text{new}}, \mathcal{B}_z) \cdot C_{\text{fail}} + (1 - P(\text{fail} \mid x_{\text{new}}, \mathcal{B}_z)) \cdot C_{\text{nominal}}$$
- 若直接绕行：
  $$\mathbb{E}[\text{Cost} \mid \text{Detour}] = C_{\text{nominal}} + C_{\text{detour}}$$
- 若调用探针 $v \in \mathcal{V}$，预计后验观测为 $o_v$：
  $$\mathbb{E}[\text{Cost} \mid \text{Probe } v] = c(v) + \sum_{o \in \mathcal{O}_v} P(o \mid x_{\text{new}}) \min \Big( \mathbb{E}[\text{Cost} \mid \text{Direct}, o], \; \mathbb{E}[\text{Cost} \mid \text{Detour}] \Big)$$

**元决策选择规则**：
$$v^* = \arg\min_{v \in \mathcal{V}} \mathbb{E}[\text{Cost} \mid \text{Probe } v]$$
$$\text{Action}^* = \begin{cases} 
\text{Probe } v^*, & \text{if } \mathbb{E}[\text{Cost} \mid \text{Probe } v^*] < \min(\mathbb{E}[\text{Cost} \mid \text{Direct}], \mathbb{E}[\text{Cost} \mid \text{Detour}]) \\ 
\text{Direct } a, & \text{if } \mathbb{E}[\text{Cost} \mid \text{Direct}] \le \min(\mathbb{E}[\text{Cost} \mid \text{Probe } v^*], \mathbb{E}[\text{Cost} \mid \text{Detour}]) \\ 
\text{Detour}, & \text{otherwise} 
\end{cases}$$

此公式完美体现了**信息价值与执行代价的动态权衡**：仅当探针提供的信息期望挽回的失败/绕行损失大于探针自身开销 $c(v)$ 时，机器人方才执行探测！

### 4.4 约束生命周期管理：复用、暂缓、收缩与撤销

约束具有完整的生命周期状态机：
1. **复用（Reuse）**：当 $x_{\text{new}}$ 深入 $\Omega_x$ 内部且置信度极高时，直接阻断并采纳绕行；
2. **暂缓（Defer）**：当 $x_{\text{new}}$ 靠近边界 $\partial \Omega_x$ 或时效衰减时，触发中等精度探针重新校准；
3. **收缩（Shrink）**：当机器人在变工况下（如低速 $v_{\text{low}}$）成功穿越该区域，该成功点作为正反例加入训练集，QP 求解器重新计算超平面，$\Omega_x$ 沿速度轴向内退缩；
4. **撤销（Revoke）**：环境熵扩散至置信度低于先验阈值 $\theta_{\text{revoke}}$，或者自愈探针证实隐蔽物理障碍已被完全清除，约束移入非活跃历史池。

### 4.5 未见条件组合下的泛化与外推机制

如果遇到此前从未见过的全新工况组合（例如从未遇到过的载荷 $M = 8\,\text{kg}$ 与速度 $v = 0.5\,\text{m/s}$ 组合）：
- 简单缓存策略因 Hash 不匹配将直接当作全新未见场景，盲目放行导致重复失败；
- SCOPE-VERIFY 通过参数流形核函数 $\psi(x)$ 的连续单调性假设（质量越大、速度越高，动能 $E_k = \frac{1}{2} M v^2$ 越高，附着力裕度越低）：
  $$\frac{\partial P(\text{fail})}{\partial M} \ge 0, \quad \frac{\partial P(\text{fail})}{\partial v} \ge 0$$
  算法在未见区域自动外推**保序半空间约束（Monotone Half-space Generalization）**，预先将高能量区标记为危险域，并提前规划降速试探。

### 4.6 算法伪代码与计算复杂度分析

```python
def scope_verify_planner(task_context x_new, candidate_action a, 
                         constraint_pool Pool, probe_library V):
    """
    SCOPE-VERIFY 元决策控制主循环
    """
    active_constraints = []
    for C in Pool:
        # 1. 检查时效性衰减
        C.decay_entropy(current_time)
        # 2. 判断当前上下文是否在约束适用范围内部或边缘
        if C.is_in_scope_or_margin(x_new):
            active_constraints.append(C)
            
    if not active_constraints:
        # 无任何历史冲突约束，直接按标称规划放行
        return PlanDecision(action=a, mode="EXECUTE")

    # 3. 计算直接执行与直接绕行的期望成本
    p_fail_max = max([C.eval_failure_prob(x_new) for C in active_constraints])
    cost_direct = p_fail_max * C_FAIL + (1.0 - p_fail_max) * C_NOMINAL
    cost_detour = C_NOMINAL + C_DETOUR

    # 4. 评估核验探针库中的所有可选核验
    best_probe = None
    min_probe_cost = float('inf')
    
    for v in V:
        expected_cost_v = v.exec_cost
        # 对探针可能返回的各种观测值求期望
        for o_val, p_o in v.simulate_outcomes(active_constraints, x_new):
            # 模拟贝叶斯更新
            hypo_posterior = v.mock_bayes_update(active_constraints, o_val)
            p_fail_post = eval_posterior_fail(hypo_posterior, x_new)
            post_direct = p_fail_post * C_FAIL + (1.0 - p_fail_post) * C_NOMINAL
            expected_cost_v += p_o * min(post_direct, cost_detour)
            
        if expected_cost_v < min_probe_cost:
            min_probe_cost = expected_cost_v
            best_probe = v

    # 5. 元决策裁决
    if min_probe_cost < min(cost_direct, cost_detour):
        # 探针期望总成本最低，采纳主动核验
        observation = execute_probe(best_probe)
        # 依据真实物理探针反馈更新约束
        update_constraints(active_constraints, best_probe, observation, x_new)
        # 递归或单步决策
        return scope_verify_planner(x_new, a, Pool, V)
    elif cost_direct <= cost_detour:
        return PlanDecision(action=a, mode="EXECUTE")
    else:
        return PlanDecision(action=find_detour_path(x_new), mode="DETOUR")
```

- **时间复杂度分析**：
  - 范围判定：单约束判断为一次核向量内积运算，耗时 $\mathcal{O}(|\mathcal{D}_{\text{SV}}| \cdot d_x)$；
  - 探针评价：遍历探针集合 $|\mathcal{V}|$，对离散观测空间 $|\mathcal{O}|$ 求和，复杂度为 $\mathcal{O}(|\mathcal{V}| \cdot |\mathcal{O}| \cdot |\mathcal{H}_z|)$；
  - 在实际场景中，$|\mathcal{V}| \le 5$，$|\mathcal{O}| \le 3$，$|\mathcal{H}_z| \le 4$，单次元决策耗时 $< 2\,\text{ms}$，完全满足 10–50 Hz 的实时机器人控制环路。
- **空间复杂度分析**：
  - 存储 $|\mathcal{C}|$ 个约束，每个仅保留支持向量点位与 $d_z \times d_z$ 协方差矩阵，占用内存极小（数十 KB），相比占用数百 MB 的经验网格图具有数量级优势。

### 4.7 相比基线方法的核心步骤差异与增益机理

1. **对比简单条件缓存（Condition Cache）**：缓存是离散黑盒匹配，遇到任何浮点微小差异（如 $M = 4.0\,\text{kg}$ vs $M = 4.1\,\text{kg}$）便失效；SCOPE-VERIFY 是**连续支撑流形**，具有紧致边界。
2. **对比标准 VoI（Standard VoI）**：标准 VoI 在静态先验上死算；SCOPE-VERIFY 的假说是**从失败遥测中动态物理溯因构建**，且具备自愈撤销算子。
3. **对比几何前置条件学习（Wang et al.）**：Wang et al. 无法处理摩擦系数等不可观测变量，遇到打滑只能将整个走廊几何阻断；SCOPE-VERIFY 通过引入潜变量信念 $\mathcal{B}_z$ 与探针动作，保全了轻载通行通道。

---

## 五、能够否定方法的评测方案

本设计必须遵循严格的证伪主义科学准则。评测设计必须具备**足以彻底推翻 SCOPE-VERIFY 理论假设的判定能力**。

### 5.1 贯穿全文的 ROS 2/Gazebo 真实物理任务场景

为确保评估完全符合真实物理与 ROS 2/Gazebo 仿真栈实际能力，构建一个**室内仓储/物流转运长周期巡检场景**：

```
       [仓库货架区 A]
             |
       [通道 1: 宽平走廊] -------- (备用超长绕行路线: +45s)
             |                                    |
      [节点 C: 关键门禁]                           |
             |                                    |
    +--------+--------+                           |
    |                 |                           |
[门径 2: 湿滑环氧地] [门径 3: 限位防火门]           |
    |                 |                           |
    +--------+--------+                           |
             |                                    |
       [车间装配区 B] <----------------------------+
```

- **移动底盘**：TurtleBot3 / Clearpath Jackal 差速驱动底盘，搭载 ROS 2 Humble 与标准 Nav2 导航栈。
- **任务定义**：机器人执行连续 50 轮搬运任务，从 A 点取件运往 B 点。任务上下文随机变化：
  - 载荷质量 $M \in [1.0, 8.0]\,\text{kg}$（改变底盘质心与最大附着极限）；
  - 目标导航速度档位 $v \in [0.2, 0.8]\,\text{m/s}$；
  - 地面状态在第 15–30 轮发生突变（清洁工在地砖表面洒水并打蜡，$\mu$ 从 0.7 降至 0.18；第 31 轮后风干，$\mu$ 恢复 0.7）；
  - 门径 3 发生随机机械闭锁（门锁在特定班次被插销卡住）。
- **物理现象响应**：
  - 若以高速 $v \ge 0.5\,\text{m/s}$ 且重载 $M \ge 4.0\,\text{kg}$ 强行通过湿滑地砖，Nav2 DWB 控制器发生严重侧滑超调，触发安全避障急停并报死（$C_{\text{fail}} = 120\,\text{s}$）；
  - 若以低速 $v \le 0.3\,\text{m/s}$ 通过，驱动轮在防抱死控制下成功低速通过（$C_{\text{nominal}} = 15\,\text{s}$）。

### 5.2 对照组设计（5 类强基线）

严禁使用“无记忆、无重试、故意劣化”的稻草人作为主基线。设置以下 5 组严谨对照：

1. **Baseline 1: 简单上下文缓存 (Condition Cache)**
   - 精确记录 $(x, a, \text{fail})$ 离散哈希；再次遇到完全一致的上下文时无条件绕行；否则盲目重试。
2. **Baseline 2: 固定 TTL / 周期复核策略 (Fixed TTL & Periodic Reset)**
   - 传统动态环境标准做法。遭遇失败后全盘阻断该动作，并赋予固定的生存时间（如 $TTL = 300\,\text{s}$）；时间一到强行清空阻断。
3. **Baseline 3: 共享预算的标准非上下文主动探针 (Standard VoI Baseline)**
   - 具有与候选方法相同的探针库 $\mathcal{V}$ 与时间预算；但不维护上下文适用范围边界 $\Omega_x$，每次面临该区域时均以静态常数先验计算标准 VoI 并调用探针。
4. **Baseline 4: 最接近的已有约束学习器 (Adapted Continuous Constraint Learner)**
   - 适配自 Chou et al. (RSS 2020) 与 Wang et al. (ICRA 2018) 的连续分类器；利用多项式 SVM 拟合失败边界，但**完全没有主动探针动作与潜变量推理**，只能在被动失败或被动成功中更新边界。
5. **Baseline 5: 真实物理上帝视角的参考上界 (Oracle / Upper Bound)**
   - 拥有对环境潜变量 $z$（当前真实 $\mu$、真实门禁锁状态）的完全真值访问权限；永远做出理论最优决策（绝不多花 1 秒探针，绝不多绕行 1 米，绝不发生一次碰撞）。此基线仅作为理论极限参考，严格标注。

### 5.3 公平性控制矩阵（先验 vs 习得知识）

| 维度 | Baseline 1 (Cache) | Baseline 2 (TTL) | Baseline 3 (Std VoI) | Baseline 4 (Learner) | **候选方法 (SCOPE-VERIFY)** | Baseline 5 (Oracle) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **预先给定先验知识** | 标称地图与代价 | 标称地图与 TTL | 标称地图 + 探针似然 | 标称地图 + 连续核函数 | **标称地图 + 探针库属性** | 完整地图 + 潜变量实时真值 |
| **运行时可见特征** | $x = (M, v, W)$ | $x = (M, v, W)$ | $x = (M, v, W)$ | $x = (M, v, W)$ | **$x = (M, v, W)$** | $x + z$ (全要素) |
| **主动核验能力** | 无 | 无 | 有 (静态先验) | 无 | **有 (条件敏感自适应)** | 无需核验 |
| **失败后重试恢复预算** | 同等统一限制 | 同等统一限制 | 同等统一限制 | 同等统一限制 | **同等统一限制** | 理论无重试 |
| **底盘控制与驱动参数** | 统一 Nav2 配置 | 统一 Nav2 配置 | 统一 Nav2 配置 | 统一 Nav2 配置 | **统一 Nav2 配置** | 统一 Nav2 配置 |

### 5.4 泛化性与非平稳动态测试协议

测试必须严格划分为三阶段，禁止使用相同参数反复刷分：
- **Phase I（训练诱发阶段，Episodes 1–10）**：在有限载荷工况下诱发首次失败；
- **Phase II（未见工况泛化阶段，Episodes 11–25）**：测试集中**绝不出现训练集用过的载荷数值**（如训练集为 2kg 与 6kg，测试集为 4.5kg 与 7.5kg）；考察范围边界插值与外推准确性；
- **Phase III（时变非平稳自愈阶段，Episodes 26–50）**：注入环境物理突变（地面风干、门禁解锁）；考察系统能否从阻断中自愈恢复，对比各基线的陈旧绕行损失。

### 5.5 评价指标体系（预先锚定主指标）

为防止事后挑选有利指标，本设计**预先锚定主指标（Primary Metric）**：
- **主指标：全序列累计归一化任务成本（Normalized Cumulative Task Cost, NCTC）**
  $$\text{NCTC} = \frac{J_{\text{total}}}{J_{\text{oracle}}}$$
  比值越接近 1.0，代表系统越逼近理论最优。

- **细分次级诊断指标（Diagnostic Metrics）**：
  1. **误阻断率（False Positive Blockage Rate, FPBR）**：物理原本可行的轻载慢速动作被错误禁止绕行的比例；
  2. **误放行率（False Negative Pass Rate, FNPR）**：物理必然失败的工况被错误放行导致硬崩溃的比例；
  3. **适用范围边界误差（Scope Boundary Jaccard Error）**：习得的 $\Omega_x$ 与物理真值不可行域 $\Omega_x^*$ 的对称差集交并比；
  4. **核验开销占比（Verification Overhead Ratio, VOR）**：探针消耗总耗时占系统总时间的比例 $\frac{\sum c(v)}{J_{\text{total}}}$；
  5. **自愈滞后轮次（Self-healing Latency Episodes）**：环境物理恢复后，系统经过几轮任务才彻底解除陈旧阻断。

### 5.6 消融实验矩阵

必须逐项剥离核心组件，验证理论增益的真实归因：
- **Ablation 1 (w/o Scope Boundary)**：保留探针与潜变量推理，但将范围判定退化为全区域点位阻断（验证参数范围学习的必要性）；
- **Ablation 2 (w/o Active Probing)**：保留范围学习，但禁止调用探针，仅依赖成功/失败硬碰撞反馈更新边界（验证带成本核验的主动价值）；
- **Ablation 3 (w/o Entropy Diffusion)**：关闭基于非平稳跳跃过程的置信度时间扩散机制，使用无限期永久置信（验证自愈解耦模块在动态环境中的作用）；
- **Ablation 4 (w/o Monotone Prior)**：关闭物理单调性保序先验，在未见高能量工况下退化为无偏随机采样（验证物理不变量外推的有效性）。

### 5.7 证伪与强制停止条件（Stop Conditions）

若评测中出现下列任意现象，直接判定本方案理论证伪，研究终止：
1. **基线优势反转（Baseline Dominance）**：在完整 50 轮评估中，Baseline 4（无探针的纯连续分类器）或 Baseline 1（简单缓存）的 NCTC 与本方法无统计显著性优势（双侧 t 检验 $p > 0.05$）；
2. **核验负收益（Negative Value of Probing）**：在全部测试集中，探针的总执行耗时大于其所避免的碰撞与绕行损失总和（$\text{VOR} > 35\%$ 且 NCTC 未见改善）；
3. **高维边界退化（Boundary Degeneration）**：当上下文特征维度超过 4 维时，由于样本极度稀疏，边界收缩导致误阻断率 $\text{FPBR} > 30\%$；
4. **人工工程过拟合（Engineering Overfitting）**：算法优势必须依赖人工精心调节的力矩/滑移阈值，更换一个 Gazebo 物理引擎（如 ODE 切换至 Bullet）后性能断崖式下跌超过 40%。

---

## 六、研究决策论证（Go / Conditional Go / No-Go）

### 6.1 决策判定：Conditional Go

经过上述极其严苛的文献核查、数学形式化推演与评测反思，针对“能否形成一个具有明确方法贡献、可证伪且值得投入的 SCI 研究方案”，我们给出客观审慎的最终裁决：

$$\mathbf{DECISION: \quad Conditional \ Go \quad (有条件推进)}$$

#### 为什么不是“No-Go”？
- **真实痛点确实存在且未被彻底解决**：文献调研（第 2 节）证实，无论是端到端经验导航（BADGR），还是大模型事后反思（REFLECT），亦或是几何前置条件（Wang et al.），在**“不可观测物理潜变量下避免陈旧阻断与参数范围自愈”**这一细分问题上，确实留有明显的空白。现有方法在真实机器人面临轻微环境变异时，普遍陷入“永久大绕行”或“盲目重复撞击”的两难困境。
- **理论模型能够闭环且具备严谨数学形式**：第 3 节与第 4 节证明，该问题可以被严格形式化为代价敏感的元决策控制与带约束 SVDD 流形更新，不再停留在“写提示词让 LLM 聊天”的松散工程层面。
- **评测设计具备不可逆的证伪能力**：第 5 节预设了清晰的指标、5 大强基线和 4 大强制停止红线，研究方案具备高度的学术诚信度与可反驳性。

#### 为什么坚决不能直接给“Go”？
- **存在两大尚未闭环的核心技术阻碍（见 6.2 节）**；
- 若未经原型推导贸然投入大规模 ROS 2/Gazebo 编码或论文写作，极易在“物理探针似然建模”与“高维稀疏样本边界震荡”上遭遇理论死胡同，造成巨大科研资源浪费。

---

### 6.2 必须解决的最小核心技术缺口清单

在进入正式代码实现与系统构建前，必须在纯数学推导与最小脚本验证层面攻克以下三大技术缺口：

1. **缺口 1：探针观测似然函数的自适应标定问题（Likelihood Calibration Gap）**
   - *问题描述*：公式中 $P(o_v \mid z)$ 目前被假设为标准高斯分布。然而在真实机器人上，地面湿滑时的微幅力矩脉冲响应与轮子磨损、底盘自重波动高度非线性耦合。
   - *最小解法*：必须先在一个独立的离线数值仿真脚本中，验证该似然模型在带有 $\pm 20\%$ 未建模模型误差扰动时，贝叶斯后验收敛是否仍具有鲁棒性。
2. **缺口 2：小样本下的超平面边界震荡（Small-Sample Boundary Oscillation）**
   - *问题描述*：在任务前 5 轮，失败样本极度稀疏（可能仅有 1–2 个样本）。此时 SVDD 或 SVM 的解空间极度不稳定，任何微小噪声都可能导致 $\Omega_x$ 发生剧烈膨胀或坍缩。
   - *最小解法*：引入基于物理不变量的**先验约束正则化项（Physics-Informed Regularization）**，约束法向量 $\mathbf{w}$ 必须保持在符合能量耗散单调性的锥体内（Monotonicity Cone Constraint）。
3. **缺口 3：ROS 2 标准消息与探针动作的原生兼容性（ROS 2 Action Architecture Alignment）**
   - *问题描述*：标准 Nav2 导航栈只接受目标位姿，缺乏原生支持“在行进前先执行力矩微探针”的标准接口层。
   - *最小解法*：明确其在 ROS 2 体系下的架构定位——作为 Nav2 BT（Behavior Tree）之上的**元决策规划节点（Meta-Planner Action Server）**，通过标准的 Behavior Tree Plugin 调度探针动作与导航子树，杜绝侵入式篡改 Nav2 底层源码。

---

### 6.3 严格停止边界与非包装承诺

为捍卫科研真实性，在此做出公开学术承诺：
1. **停止阈值**：如果后续在离线数学验证中发现，在满足动力学鲁棒性条件下，主动核验带来的期望收益根本无法抵消其 $c(v)$ 探针耗时（即 $\mathbb{E}[\text{VoI}] < c(v)$ 恒成立），**将立即将状态转为 No-Go，直接终止该课题，不强行包装发文**；
2. **零造假承诺**：所有对照实验基线必须采用其官方推荐参数调至最优状态，绝不通过刻意劣化基线算法制造本方案的虚假优势；
3. **代码与数据解耦**：本设计严格保持对已有 `failmem-ros2-agent` 成果的冻结，所有新推演与未来工作均在独立分支演进。

---

## 参考文献

1. S. Macenski et al., "Robot Operating System 2: Design, architecture, and uses in the wild," *Science Robotics*, vol. 7, no. 66, p. eabm6074, 2022.
2. G. Kahn, P. Abbeel, and S. Levine, "BADGR: An Autonomous Self-Supervised Learning-Based Navigation System," *IEEE Robotics and Automation Letters (RA-L)*, vol. 6, no. 2, pp. 1312–1319, 2021.
3. M. Phillips, B. J. Cohen, S. Chitta, and M. Likhachev, "E-Graphs: Bootstrapping Planning with Experience Graphs," *The International Journal of Robotics Research (IJRR)*, vol. 31, no. 10, pp. 1159–1175, 2012.
4. D. Berenson, S. S. Srinivasa, and J. Kuffner, "A Robot Path Planning Framework for Adaptive Experience Reuse," *The International Journal of Robotics Research (IJRR)*, vol. 31, no. 10, pp. 1237–1254, 2012.
5. Z. Liu, A. Bahety, and S. Song, "REFLECT: Summarizing Robot Experiences for Failure Explanation and Correction," in *Conference on Robot Learning (CoRL)*, PMLR 229, 2023, pp. 3468–3484.
6. Z. Wang, C. R. Garrett, L. P. Kaelbling, and T. Lozano-Pérez, "Learning Generalized Geometric Preconditions for Robot Task and Motion Planning," in *IEEE International Conference on Robotics and Automation (ICRA)*, 2018, pp. 1–8.
7. G. Chou, N. Ozay, and D. Berenson, "Learning Constraints from Demonstrations with Predictable Generalization," in *Robotics: Science and Systems (RSS)*, 2020.
8. S. Srivastava, E. Fang, L. Riano, R. Chitnis, S. Russell, and P. Abbeel, "Combined Task and Motion Planning Through an Extensible Planner-Independent Interface Layer," in *AAAI Conference on Artificial Intelligence*, 2014, pp. 639–646.
9. R. A. Howard, "Information Value Theory," *IEEE Transactions on Systems Science and Cybernetics*, vol. 2, no. 1, pp. 22–26, 1966.
10. A. Krause and C. Guestrin, "Near-optimal Nonmyopic Value of Information in Graphical Models," in *Conference on Uncertainty in Artificial Intelligence (UAI)*, 2005.
11. L. P. Kaelbling and T. Lozano-Pérez, "Integrated Task and Motion Planning in Belief Space," *The International Journal of Robotics Research (IJRR)*, vol. 32, no. 9–10, pp. 1194–1227, 2013.
12. T. Krajnik, J. P. Fentanes, J. M. Santos, and T. Duckett, "Fremen: Frequency Map Enhancement for Long-Term Mobile Robot Autonomy," *IEEE Transactions on Robotics (TRO)*, vol. 33, no. 4, pp. 964–977, 2017.
13. P. Biber and T. Duckett, "Dynamic Maps for Long-Term Operation of Mobile Service Robots," in *Robotics: Science and Systems (RSS)*, 2005.
14. D. V. Lu, D. Hershberger, and W. D. Smart, "Layered Costmaps for Context-Sensitive Navigation," in *IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*, 2014, pp. 709–715.
