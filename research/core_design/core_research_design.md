# 核心研究设计修订与去留判定：基于带成本核验解耦失败范围过度推广与环境过时的闭合分析

**文档性质**：学术方法论严密核验、最小模型推演与最终去留裁决（非代码开发、非实验扩容、非投稿准备）  
**基准成果版本**：`73b0b83a836a128b09aa1137137cf97757183e8d`（已有实现、数据与文本完全冻结）  
**设计迭代版本**：基于 `03b3abb` 的彻底纠偏与收缩审定  
**设计分支**：`research/core-method-design`  
**执行边界**：0 新增 Gazebo 场景、0 机器人算法代码、0 模型训练、0 真实 LLM 调用。纯手工推演、数学闭环与文献原文逐项核实。

---

## 目录

- [一页终局结论与核心答辩](#一页终局结论与核心答辩)
- [一、文献论证彻底核验与纠偏表](#一文献论证彻底核验与纠偏表)
  - [1.1 关键引用逐项核实与错配纠正](#11-关键引用逐项核实与错配纠正)
  - [1.2 纳入文献深度精读：Chou et al. (CoRL 2020 / PMLR 2021)](#12-纳入文献深度精读chou-et-al-corl-2020--pmlr-2021)
  - [1.3 三大支柱领域最接近代表作精读](#13-三大支柱领域最接近代表作精读)
  - [1.4 “研究缺口—原文依据—本研究差异”严格对照表](#14-研究缺口原文依据本研究差异严格对照表)
  - [1.5 既往不实断言撤回与边界确认](#15-既往不实断言撤回与边界确认)
- [二、候选核心问题收缩：单一关键混淆（A/B 混淆）](#二候选核心问题收缩单一关键混淆ab-混淆)
  - [2.1 关键混淆界定：范围推广过度 vs 环境状态过时](#21-关键混淆界定范围推广过度-vs-环境状态过时)
  - [2.2 现有联合信念更新与主动学习能否自然处理？](#22-现有联合信念更新与主动学习能否自然处理)
  - [2.3 明确的边界排除承诺](#23-明确的边界排除承诺)
- [三、闭合的最小联合概率模型](#三闭合的最小联合概率模型)
  - [3.1 五类变量的严格划分](#31-五类变量的严格划分)
  - [3.2 联合概率预测与贝叶斯更新闭环](#32-联合概率预测与贝叶斯更新闭环)
  - [3.3 有限假设模型界定](#33-有限假设模型界定)
  - [3.4 统一成本体系（含失败定义与探针物理转移）](#34-统一成本体系含失败定义与探针物理转移)
  - [3.5 单步信息价值（Myopic VoI）决策模型](#35-单步信息价值myopic-voi决策模型)
- [四、唯一的方法差异定位](#四唯一的方法差异定位)
  - [4.1 核心差异标准陈述句](#41-核心差异标准陈述句)
  - [4.2 决策与更新算法伪代码](#42-决策与更新算法伪代码)
  - [4.3 坦诚学术定位：已有理论的实例化 vs 原创新算法](#43-坦诚学术定位已有理论的实例化-vs-原创新算法)
- [五、公平的手工可复核最小推演](#五公平的手工可复核最小推演)
  - [5.1 最小算例环境与参数定义](#51-最小算例环境与参数定义)
  - [5.2 场景 1：环境稳定，范围过度推广（验证防误阻断）](#52-场景-1环境稳定范围过度推广验证防误阻断)
  - [5.3 场景 2：上下文固定，环境状态变化（验证防陈旧绕行）](#53-场景-2上下文固定环境状态变化验证防陈旧绕行)
  - [5.4 场景 3：核验成本过高或无信息，理性不核验（验证抗滥用）](#54-场景-3核验成本过高或无信息理性不核验验证抗滥用)
  - [5.5 各基线全过程对比矩阵](#55-各基线全过程对比矩阵)
  - [5.6 算例证明了什么，没有证明什么](#56-算例证明了什么没有证明什么)
- [六、修正后的未来评测方案（只设计，不执行）](#六修正后的未来评测方案只设计不执行)
  - [6.1 正交隔离的测试协议](#61-正交隔离的测试协议)
  - [6.2 统计分析单元与实际效应量阈值](#62-统计分析单元与实际效应量阈值)
  - [6.3 物理假设标记与虚假承诺撤回](#63-物理假设标记与虚假承诺撤回)
- [七、研究决策判定：No-Go](#七研究决策判定no-go)
  - [7.1 判定结论与核心依据](#71-判定结论与核心依据)
  - [7.2 为什么必须判定为 No-Go（拒绝 Conditional Go 拖延）](#72-为什么必须判定为-no-go拒绝-conditional-go-拖延)
  - [7.3 明确的止步清单与后续建议](#73-明确的止步清单与后续建议)

---

## 一页终局结论与核心答辩

经过对文献原文的逐字复核、数学模型的严格闭环构建以及手算最小例子的公正推演，本轮对“在部分可观测下通过带成本核验解耦失败经验过度推广与环境过时”这一课题得出**终局判定：No-Go（坚决停止作为独立方法论 SCI 论文推进）**。

### 核心答辩要点

1. **修正后的文献事实彻底推翻了“现有约束学习缺失执行中不确定更新”的前提**：
   - 原设计将 `arXiv:1804.03215` 错配为超导体凝聚态物理论文，本轮已纠正并核实真正的相关论文；
   - 尤为关键的是，精读 **Glen Chou, Dmitry Berenson, Necmiye Ozay (CoRL 2020 / PMLR 2021)** 的代表作后确认：该工作**已经完整提出了“对不确定约束维护置信度（Belief over constraints）”、“在闭环执行中利用观测数据进行信念更新（Belief updates using data gathered during execution）”以及“权衡任务性能与满足潜在约束的轨迹规划”**。
   - 所谓“已有约束学习都是确定性的、无法在执行中更新”是完全违背文献事实的“稻草人断言”。

2. **核心问题在形式化闭环后，已被经典理论完全覆盖**：
   - 当把研究目标严格收缩至“区分失败是来自（A）范围过度推广还是（B）环境潜在状态变化”时，我们构建了包含可见上下文 $x$、潜在环境状态 $z$、约束范围参数 $\theta$ 的联合概率模型；
   - 结果表明：**标准联合贝叶斯滤波 $b_t(z_t, \theta) = P(z_t, \theta \mid \mathcal{H}_t)$ 配合单步信息价值（VoI）决策，在数学上已经完全且自然地解决了该混淆**；
   - 本方案没有任何新的机器学习公式、没有新的先验理论、没有新的信息测度，**纯粹是标准 POMDP 主动感知 / 贝叶斯决策理论在一个具体机器人故障场景下的直接应用（Instantiation）**。

3. **方法差异无法支撑独立的 SCI 方法创新**：
   - 按照规范填空：
     > “相对于最接近的现有方法，我们增加或改变了**在离散状态空间中将环境时变转移与离散范围参数置于同一联合贝叶斯信念中并使用单步 VoI 调度探针**；它针对**将局部时变故障误当全局永久阻断（A/B 混淆）**困难；预期通过**在离散算例中优于忽略时变的静态约束学习器**证据验证。”
   - 这一改动本质上是“使用教科书已有工具解决一个特定应用问题”。一旦以“提出全新学习算法”向一流国际期刊投稿，必将被熟知 POMDP、主动学习和约束学习的审稿人一票否决。

4. **手算推演揭示的客观真相**：
   - 在第 5 节严格对等的手算算例中，本方案的决策完全与**标准联合贝叶斯最优参考解（Exact Bayes Reference）完全重合**；
   - 本方案之所以能在特定场景下战胜“简单缓存”或“无时变分类器”，**100% 来源于给系统引入了马尔可夫转移先验与额外的主动探针动作库**，而非源于某种超越基线的算法机制；
   - 一旦探针成本过高，算法自动退化为被动绕行或直接执行。

5. **决断：拒绝“Conditional Go”包装，诚实停止**：
   - 不再承诺“未来解决连续高维、非近视长序列、开放世界诊断”等宏大口号来换取虚假的“有条件通过”；
   - 承认该构想作为“独立算法创新”是不成立的，建议团队停止将其作为 SCI 学术论文投入，避免浪费科研资源。

---

## 一、文献论证彻底核验与纠偏表

### 1.1 关键引用逐项核实与错配纠正

在前期设计文档中，存在一处严重的引用标识错配，本轮通过原始数据库进行了逐项核实与纠正：

1. **`arXiv:1804.03215` 错配纠正**：
   - *错误记录*：原稿将其标注为 Zi Wang, C. R. Garrett, L. P. Kaelbling, T. Lozano-Pérez 的《Learning Generalized Geometric Preconditions for Robot Task and Motion Planning》预印本。
   - *核验真相*：经检索 arXiv 官方数据库，`arXiv:1804.03215` 的真实论文为凝聚态物理领域的实验论文：
     > S. L. Chen et al., *"Pressure effects on the structural and superconducting transitions in $\text{La}_3\text{Co}_4\text{Sn}_{13}$"*, arXiv:1804.03215 [cond-mat.supr-con], 2018.
     该链接与机器人学毫无关系，系前期调研中的严重抓取/拼接错误，现予彻底纠正与剔除。
   - *真实对应文献确认*：Zi Wang, Caelan Reed Garrett, Leslie Pack Kaelbling, Tomás Lozano-Pérez 在该阶段的真正核心论文为：
     - **IROS 2018**: Z. Wang, C. R. Garrett, L. P. Kaelbling, T. Lozano-Pérez, *"Active Model Learning and Diverse Action Sampling for Task and Motion Planning"*, in *IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*, 2018, pp. 4107–4114. DOI: [10.1109/IROS.2018.8594027](https://doi.org/10.1109/IROS.2018.8594027).
     - **RSS 2021**: Z. Wang, C. R. Garrett, L. P. Kaelbling, T. Lozano-Pérez, *"Active Learning of Abstract Plan Feasibility"*, in *Robotics: Science and Systems (RSS)*, 2021. DOI: [10.15607/RSS.2021.XVII.043](https://doi.org/10.15607/RSS.2021.XVII.043).

### 1.2 纳入文献深度精读：Chou et al. (CoRL 2020 / PMLR 2021)

根据审定要求，系统精读了 Glen Chou, Dmitry Berenson, Necmiye Ozay 的代表作：
- **文献元数据**：Glen Chou, Dmitry Berenson, Necmiye Ozay, *"Uncertainty-Aware Constraint Learning for Adaptive Safe Motion Planning from Demonstrations"*, in *Proceedings of the 4th Conference on Robot Learning (CoRL 2020)*, PMLR vol. 155, pp. 1612–1639, 2021. 官方页面：[https://proceedings.mlr.press/v155/chou21a.html](https://proceedings.mlr.press/v155/chou21a.html).
- **精读原文核心机制**：
  1. *约束不确定性信念构建*（Section 3.1 & 4）：针对示教轨迹一致的潜在约束集合，利用鲁棒优化获得一个连续/参数化的约束置信分布（Belief over constraints），而非单一硬判定；
  2. *权衡性能与安全规划*（Section 5）：在置信空间中规划轨迹，使轨迹在最小化运动代价的同时，满足特定置信水平下的安全裕度；
  3. *执行期在线信念更新（Closed-loop Replanning with Belief Updates）*（Section 6）：在实际控制机器人执行轨迹时，持续采集在线传感数据（如触觉、接近觉或发生微接触/自由运动），将新观测代入贝叶斯/区间更新器修正约束信念，并自适应触发在线重规划；
  4. *实验验证*：在 7 自由度机械臂与 12 维四旋翼上成功学习高维（达 30 维）不确定约束。
- **对本研究的直接冲击**：
  该论文无可辩驳地证明，**“不确定约束的概率表示”与“在机器人执行中根据反馈动态更新约束信念并重新规划”，早在 2020 年就已被 Glen Chou 等人完整提出并在多自由度硬件上验证**。任何声称“传统约束学习缺乏不确定性表达、无法在执行中在线更新”的说法，都是站不住脚的。

### 1.3 三大支柱领域最接近代表作精读

#### 类别 1：不确定约束学习与执行中信念更新
- **Chou et al. (CoRL 2020 / PMLR 2021)**（见 1.2 节）：基于示教与执行期反馈更新不确定几何约束。
- **Chou et al. (RSS 2020 / IJRR 2021)**：G. Chou, N. Ozay, D. Berenson, *"Learning Constraints from Demonstrations with Predictable Generalization"*, IJRR, vol. 40, no. 8, pp. 1023–1044, 2021. 利用凸包与 SVDD 给出泛化误差界，但环境假设为静态。

#### 类别 2：带成本的主动核验、主动学习与信息价值决策
- **Wang et al. (RSS 2021)**：Z. Wang et al., *"Active Learning of Abstract Plan Feasibility"*, RSS 2021. 利用分类器不确定性指导主动采样，优先计算高信息增益的几何连续运动规划。局限在于：其“成本”是算法计算时间，而非物理机器人的硬件风险与时间。
- **Kaelbling & Lozano-Pérez (IJRR 2013)**：L. P. Kaelbling, T. Lozano-Pérez, *"Integrated Task and Motion Planning in Belief Space"*, IJRR, vol. 32, no. 9–10, pp. 1194–1227, 2013. 建立了完整的信念空间规划，动作显式包含感知动作（Sensing Actions），并用离散/连续观测更新分布。
- **Howard (1966)**：R. A. Howard, *"Information Value Theory"*, IEEE Trans. Syst. Sci. Cybern., 1966. 奠定了单步/多步 VoI 的数学基石：仅当信息获取后的期望效用提升大于获取成本时，核验才具有经济合理性。

#### 类别 3：非平稳环境中的变化检测与知识更新
- **Krajnik et al. (IEEE TRO 2017)**：T. Krajnik et al., *"Fremen: Frequency Map Enhancement for Long-Term Mobile Robot Autonomy"*, IEEE TRO, vol. 33, no. 4, pp. 964–977, 2017. 用频域谐波追踪环境栅格占用的非平稳时变过程。局限在于：仅建模空间几何点位占用，不建模与机器人载荷、速度耦合的物理约束。
- **Biber & Duckett (RSS 2005 / RAS 2009)**：基于多时标样本衰减剔除陈旧障碍物。

---

### 1.4 “研究缺口—原文依据—本研究差异”严格对照表

| 领域 / 代表作 | 原文已解决的核心能力与依据 | 原文未覆盖/真实局限（文献依据） | 本研究候选差异（严格限定） | 差异成立性严谨评估 |
| :--- | :--- | :--- | :--- | :--- |
| **不确定约束更新**<br>Chou et al. (CoRL 2020) | 在执行期利用轨迹在线数据更新几何约束置信度并重规划（Sec. 6） | **仅针对静态障碍物几何边界；未建模潜在物理状态突变（如地面变湿/变干）的时变马尔可夫跳变** | 将离散非平稳状态转移与约束参数置于同一联合信念，并使用专门物理探针而非仅沿轨迹被动观测 | **部分成立，但属于应用级组合**：Chou 关注高维几何，未显式处理时变环境跳变；但数学上均属贝叶斯后验。 |
| **主动可行性核验**<br>Wang et al. (RSS 2021) | 主动选择最有信息量的样本以判定高层规划动作的可行性 | **主动核验的对象是计算机内的运动规划器计算（Simulation/Planning Cost），不是物理探针与硬件损耗** | 核验动作为带有硬件执行耗时与轻微物理碰撞风险的真实探针动作（如力矩脉冲试探） | **场景差异，非方法差异**：VoI 的计算逻辑与目标函数在数学形式上全同，仅成本物理含义不同。 |
| **时变动态地图**<br>Krajnik et al. (TRO 2017) | 建立长周期时变非平稳概率地图，周期性自愈自适应 | **只建模空间坐标 $(x,y)$ 几何占用 $P(O)$，完全不包含机器人自身任务上下文（质量、速度、动力学）** | 区分是“环境状态变了”还是“机器人换用了轻载慢速工况”（解耦 A 与 B） | **问题定位明确，但解法被标准 POMDP 覆盖**：解耦 A/B 确有工程意义，但标准联合滤波即可直接完成。 |
| **信念空间规划**<br>Kaelbling (IJRR 2013) | 将感知动作与物理动作统一放入 POMDP 求解，最小化期望成本 | **POMDP 经典求解在高维连续空间极度困难，通常依赖人工设计的离散感知原语** | 针对 failure-recovery 场景限定一个最小离散模型进行即时单步 VoI 解析求解 | **无方法学增量**：实质上就是 Kaelbling 理论在 2 状态、2 参数下的手算特例。 |

### 1.5 既往不实断言撤回与边界确认

为保证科研诚信，正式撤回前期报告中的以下不当概括：
1. **撤回“已有约束学习都是确定性的”**：Chou et al. (CoRL 2020) 明确提出了针对不确定约束的信念维护与概率安全保证；
2. **撤回“标准 VoI 必然固定先验”**：信息价值理论中先验始终随着贝叶斯滤波动态更新，不存在“必须固定常数先验”的理论缺陷；
3. **撤回“组合多个模块即可宣布新颖性”**：将 Chou 的约束不确定性、Krajnik 的时变衰减与 Howard 的 VoI 拼装，在学术规范中属于已知技术的系统集成，不能直接声称方法学创新。

---

## 二、候选核心问题收缩：单一关键混淆（A/B 混淆）

### 2.1 关键混淆界定：范围推广过度 vs 环境状态过时

我们将研究对象严格收缩为移动机器人长周期运行中面临的**唯一关键混淆**：

> 机器人在走廊 $e$ 遭遇一次物理执行失败（如重载高速通行打滑急停），随后面临新的决策时，该失败可能归因于两种截然不同的物理机制：
> - **机制 A：原有失败经验的适用范围被过度推广（Scope Over-generalization）**  
>   环境潜在物理状态 $z$ 未变（地面依然较湿滑，$\mu = 0.2$），但该物理失败仅发生在极端工况（重载 $M_{\text{high}}$ 且高速 $v_{\text{high}}$）。若当前任务是轻载慢速（$M_{\text{low}}, v_{\text{low}}$），动作在当前物理状态下完全可行。若机器人简单记住“该走廊不可行”，便引发**错误阻断（False Blockage）**。
> - **机制 B：环境潜在状态发生变化，原有经验已经过时（State Stale / Obsolete）**  
>   失败经验当时确实成立，但环境潜变量 $z$ 随时间发生了非平稳恢复（保洁积水已彻底风干，$\mu$ 恢复至 0.7）。当前即便是重载高速，动作也已恢复可行。若机器人永久保留此约束，同样引发**陈旧阻断（Stale Blocking）**；反之若机械性定时清零，又会在积水未干时发生**重复失败（Repeated Failure）**。

**候选研究问题**：  
机器人能否通过有限、带成本的局部物理核验（Probing），在不确定联合信念中以最低累计代价区分 A 与 B，从而兼顾消除错误阻断与杜绝重复失败？

### 2.2 现有联合信念更新与主动学习能否自然处理？

必须正面回答用户的核心质问：
> **“现有联合信念更新和主动学习方法是否已经能够自然处理它？若能够，剩余困难具体是什么？”**

**客观回答：在数学理论层面，现有标准理论已经能够完全、自然地处理它！**

- **理论依据**：
  在统计决策理论与 POMDP 框架中，定义联合状态向量包含潜在状态与未知参数 $S_t = (z_t, \theta)$。
  - $z_t$ 按马尔可夫转移概率 $P(z_t \mid z_{t-1})$ 演化（表达机制 B 的时变性）；
  - $\theta$ 表示不可行域的临界参数边界（表达机制 A 的范围边界）；
  - 机器人的历史交互与核验观测序列记为 $\mathcal{H}_t$。
  - 联合信念分布 $b_t(z_t, \theta) = P(z_t, \theta \mid \mathcal{H}_t)$ 根据标准贝叶斯法则进行递归滤波预测与更新：
    $$b_t(z_t, \theta) \propto P(o_t \mid z_t, \theta) \sum_{z_{t-1}} P(z_t \mid z_{t-1}) b_{t-1}(z_{t-1}, \theta)$$
  - 在该联合分布上，直接套用单步信息价值（VoI）评估候选探针 $v$，当且仅当 $\text{VoI}(v) > c(v)$ 时调用探针。
- **数学结论**：**这套标准的联合贝叶斯滤波框架，在定义上天然耦合了时变跳变与参数不确定性，不存在任何理论上的“脱节”或“无法处理”。**

#### 那么，剩余困难究竟是什么？
现有文献在机器人落地时的真实剩余困难，**不在于公式原理缺失，而在于工程与计算扩展性**：
1. **连续高维积分不可解**：若 $x$ 是高维连续向量，$\theta$ 是非线性流形参数，联合信念 $b(z_t, \theta)$ 的精确后验没有共轭闭式解，粒子滤波（Particle Filter）极易在小样本离散失败事件中发生粒子耗散（Particle Depletion）；
2. **探针信息非对称性**：机器人携带的物理探针（如微力矩滑移探测）通常只能直接观测即时环境状态 $z_t$（测出表面摩擦力），**几乎不可能有任何直接探测“临界速度阈值 $\theta$”的探针**。$\theta$ 的收敛只能依赖于机器人冒着失败风险进行真实的执行试探。这种状态直接可测、参数只能间接试探的非对称性，导致信息价值评估在近视（Myopic）假设下往往低估探索价值。

### 2.3 明确的边界排除承诺

为了确保研究设计的可证伪性与闭环性，本轮坚决剔除一切无法严格求解的宏大口号：
- **排除开放世界假设生成**：不采用任何未定义假设空间的 LLM 幻觉归因，假说严格受限于预置的离散集合；
- **排除高维连续边界学习**：不在高维连续流形上拟合不稳定的 SVDD/SVM 边界，退回到离散区间参数；
- **排除多步非近视探针规划**：明确声明本方法采用**单步近视信息价值（Myopic VoI）**，不保留任何“全局非近视序列”的虚假陈述；
- **排除复杂物理因果诊断**：不建立端到端流体动力学方程，探针观测直接由离散混淆矩阵/高斯似然生成。

---

## 三、闭合的最小联合概率模型

本节构建一个完全闭合、变量无遗漏、概率无断层的最小离散数学模型。

```mermaid
flowchart TD
    subgraph StateSpace [联合隐状态与参数]
        Z[时变潜在环境状态: z_t in {dry, wet}]
        Theta[静态范围参数: theta in {broad, narrow}]
        JointBelief["联合信念分布: b_t(z_t, theta) = P(z_t, theta | H_t)"]
        Z --> JointBelief
        Theta --> JointBelief
    end

    subgraph ContextAndAction [当前任务输入]
        X[可见任务上下文: x_t in {x_L, x_H}]
        Act[候选决策: Direct / Detour / Probe]
    end

    subgraph JointModel [统一预测与成本评估]
        FailProb["联合失效率: P(fail | x_t, z_t, theta)"]
        VoIEval["单步信息价值评估: VoI(v) vs c(v)"]
        JointBelief --> FailProb
        X --> FailProb
        FailProb --> VoIEval
        Act --> VoIEval
    end

    subgraph Outcome [观测反馈与信念演化]
        ObsY[执行成败: y in {succ, fail}]
        ObsO[探针反馈: o in {o_dry, o_wet}]
        Markov[马尔可夫时变转移: P(z_t | z_t-1)]
        Markov --> JointBelief
        ObsY --> JointBelief
        ObsO --> JointBelief
    end
```

### 3.1 五类变量的严格划分

在每个离散任务决策时刻 $t = 1, 2, \dots$：
1. **可见上下文 $x_t \in \mathcal{X} = \{x_L, x_H\}$**：
   - $x_L$：轻载低速工况（如载荷 $M = 2\,\text{kg}$，航速 $v = 0.2\,\text{m/s}$）；
   - $x_H$：重载高速工况（如载荷 $M = 7\,\text{kg}$，航速 $v = 0.6\,\text{m/s}$）。
   任务发生时由外部调度下发，机器人 100% 完全可见。
2. **不可直接观察的环境潜在状态 $z_t \in \mathcal{Z} = \{z_{\text{dry}}, z_{\text{wet}}\}$**：
   - $z_{\text{dry}}$：地面正常干燥（标称状态）；
   - $z_{\text{wet}}$：地面存在隐蔽积水/清洁剂打蜡（低附着状态）。
   该变量不对机器人名义导航传感器直接可见。
3. **尚不确定的失败范围参数 $\theta \in \Theta = \{\theta_{\text{broad}}, \theta_{\text{narrow}}\}$**：
   - $\theta_{\text{broad}}$（宽泛失效）：在 $z_{\text{wet}}$ 状态下，底盘动力学极限被严重破坏，**$x_L$ 与 $x_H$ 均必然失败**；
   - $\theta_{\text{narrow}}$（狭窄失效）：在 $z_{\text{wet}}$ 状态下，仅重载高速的 **$x_H$ 失败**，轻载慢速的 **$x_L$ 依然能够安全通行**。
   - （在 $z_{\text{dry}}$ 状态下，无论 $\theta$ 取何值，$x_L$ 与 $x_H$ 均必然成功）。
4. **执行与核验收到的即时观测**：
   - 动作执行结果：$y_t \in \mathcal{Y} = \{\text{succ}, \text{fail}\}$；
   - 探针核验结果：$o_t \in \mathcal{O}_v = \{o_{\text{dry}}, o_{\text{wet}}\}$。
5. **已知量、需学量与 Oracle 真值划分**：
   - *先验已知量*：马尔可夫转移参数 $\lambda_{\text{dry}}, \lambda_{\text{wet}}$、探针观测混淆矩阵 $P(o \mid z)$、成本常数 $C_{\text{nom}}, C_{\text{detour}}, C_{\text{fail}}, c(v)$；
   - *需学习维护量*：4 维离散联合后验向量 $b_t(z_t, \theta) = [b_{11}, b_{12}, b_{21}, b_{22}]^T$；
   - *仅供评测评估的 Oracle 量*：真实物理环境状态 $z_t^*$ 与物理规律真实阈值 $\theta^*$（用于计算最优决策理论上界，对算法严格隐蔽）。

### 3.2 联合概率预测与贝叶斯更新闭环

统一失败概率预测方程（消除了原有 SVDD 凸包与贝叶斯后验的断层）：
$$P(\text{fail} \mid x, z, \theta) = \begin{cases}
0, & \text{if } z = z_{\text{dry}} \\
1, & \text{if } z = z_{\text{wet}} \wedge x = x_H \\
1, & \text{if } z = z_{\text{wet}} \wedge x = x_L \wedge \theta = \theta_{\text{broad}} \\
0, & \text{if } z = z_{\text{wet}} \wedge x = x_L \wedge \theta = \theta_{\text{narrow}}
\end{cases}$$

#### 状态转移模型（机制 B 驱动）
环境潜在状态服从平稳二值马尔可夫链（以时间步或固定时间间隔演化）：
$$\mathbf{T}_z = \begin{bmatrix} P(z_t = z_{\text{dry}} \mid z_{t-1} = z_{\text{dry}}) & P(z_t = z_{\text{dry}} \mid z_{t-1} = z_{\text{wet}}) \\ P(z_t = z_{\text{wet}} \mid z_{t-1} = z_{\text{dry}}) & P(z_t = z_{\text{wet}} \mid z_{t-1} = z_{\text{wet}}) \end{bmatrix} = \begin{bmatrix} 1 - \lambda_{\text{wet}} & \lambda_{\text{dry}} \\ \lambda_{\text{wet}} & 1 - \lambda_{\text{dry}} \end{bmatrix}$$
范围参数 $\theta$ 为系统内在固有物理参数，服从恒等转移：$P(\theta_t \mid \theta_{t-1}) = \mathbb{I}(\theta_t = \theta_{t-1})$。

#### 预测步（Time Update / Entropy Diffusion）
在收到任务 $t$ 之前，信念经历时间转移：
$$\bar{b}_t(z_t, \theta) = \sum_{z_{t-1} \in \mathcal{Z}} P(z_t \mid z_{t-1}) b_{t-1}(z_{t-1}, \theta)$$

#### 更新步（Measurement Update）
若执行了动作或探针，收到观测 $m \in \{y_t, o_t\}$：
$$b_t(z_t, \theta) = \frac{P(m \mid x_t, z_t, \theta) \bar{b}_t(z_t, \theta)}{\sum_{z' \in \mathcal{Z}} \sum_{\theta' \in \Theta} P(m \mid x_t, z', \theta') \bar{b}_t(z', \theta')}$$

### 3.3 有限假设模型界定

本模型只有有限的 2 种环境状态与 2 种范围参数，联合假设空间大小为 $|\mathcal{Z} \times \Theta| = 4$。本设计郑重将其命名为**“离散四假设信念闭环模型”**，不再使用任何诸如“连续自适应流形”或“开放世界归因”的非受控修辞。

### 3.4 统一成本体系（含失败定义与探针物理转移）

所有代价量纲均严格统一为**等效执行时间成本（秒）**：
1. **标称直行成本 $C_{\text{nom}} = 10\,\text{s}$**：在通道正常通行且成功到达的目标耗时；
2. **保守绕行成本 $C_{\text{detour}} = 35\,\text{s}$**：放弃当前通道、经由外围安全大通道通行的时间（必定成功，但确定性多耗费 $25\,\text{s}$）；
3. **硬失败惩罚 $C_{\text{fail}} = 100\,\text{s}$**：
   - **严格包含关系确认**：$C_{\text{fail}}$ **已经完整包含**了机器人进入通道前行到滑移点的时间（约 $5\,\text{s}$）、Nav2 控制器多次打滑重试超时时间（$30\,\text{s}$）、原地自转恢复失败（$25\,\text{s}$）以及人工介入或自动复位重定位至起点的时间（$40\,\text{s}$）。一旦发生失败，该任务总消耗时间即计为 $100\,\text{s}$；
4. **主动探针直接成本 $c(v) = 3\,\text{s}$**：执行原地微幅力矩脉冲并读取滑移差耗时；
5. **探针物理转移与风险界定**：
   - 设探针具有极微小的硬件扰动风险 $r(v) = 0.01$（有 $1\%$ 概率导致驱动轮局部划伤或底盘轻微偏航而触发保护停机，停机惩罚为 $C_{\text{risk}} = 50\,\text{s}$）；
   - 则探针的综合广义执行成本修正为：
     $$\tilde{c}(v) = c(v) + r(v) \cdot C_{\text{risk}} = 3.0 + 0.01 \times 50 = 3.5\,\text{s}$$
   - 探针动作自身不改变地面的干湿状态：$P(z' \mid z, v) = \mathbb{I}(z' = z)$。

### 3.5 单步信息价值（Myopic VoI）决策模型

在当前上下文 $x_t$ 与先验信念 $\bar{b}_t$ 下：
1. **直接执行的期望成本**：
   $$P_{\text{fail}}(x_t, \bar{b}_t) = \sum_{z \in \mathcal{Z}} \sum_{\theta \in \Theta} P(\text{fail} \mid x_t, z, \theta) \bar{b}_t(z, \theta)$$
   $$\mathbb{E}[\text{Cost} \mid \text{Direct}] = (1 - P_{\text{fail}}(x_t, \bar{b}_t)) \cdot C_{\text{nom}} + P_{\text{fail}}(x_t, \bar{b}_t) \cdot C_{\text{fail}}$$
2. **直接绕行的确定成本**：
   $$\mathbb{E}[\text{Cost} \mid \text{Detour}] = C_{\text{detour}} = 35$$
3. **无核验基准最优期望成本**：
   $$V_{\text{no\_probe}}(x_t, \bar{b}_t) = \min \Big( \mathbb{E}[\text{Cost} \mid \text{Direct}], \; \mathbb{E}[\text{Cost} \mid \text{Detour}] \Big)$$
4. **调用探针后的期望成本（单步 VoI）**：
   探针返回观测 $o \in \{o_{\text{dry}}, o_{\text{wet}}\}$，边际预测概率为 $P(o \mid \bar{b}_t) = \sum_z P(o \mid z) \bar{b}_t(z)$。
   更新后的后验记为 $b_t^o$。
   $$\mathbb{E}[\text{Cost} \mid \text{Probe}] = \tilde{c}(v) + \sum_{o \in \mathcal{O}_v} P(o \mid \bar{b}_t) \min \Big( \mathbb{E}[\text{Cost} \mid \text{Direct}, b_t^o], \; C_{\text{detour}} \Big)$$
5. **决策裁决**：
   $$\text{Decision}^* = \begin{cases}
   \text{Probe } v, & \text{if } \mathbb{E}[\text{Cost} \mid \text{Probe}] < V_{\text{no\_probe}}(x_t, \bar{b}_t) \\
   \text{Direct } a, & \text{if } \mathbb{E}[\text{Cost} \mid \text{Direct}] \le \min(\mathbb{E}[\text{Cost} \mid \text{Probe}], C_{\text{detour}}) \\
   \text{Detour}, & \text{otherwise}
   \end{cases}$$

---

## 四、唯一的方法差异定位

### 4.1 核心差异标准陈述句

按照审阅要求，严格用一句话界定本方案的方法定位：

> **“相对于最接近的现有方法（Chou et al. 2020 的不确定约束学习与 Biber/Krajnik 的时变地图），我们增加或改变了：在任务决策前显式维护‘环境潜变量时变马尔可夫转移’与‘任务上下文约束范围参数’的 4 维联合离散后验信念，并基于单步信息价值（VoI）权衡探针代价动态调度核验动作；它针对：将局部瞬态失效错误泛化为全局永久阻断、以及因环境自愈滞后导致无谓绕行（A/B 混淆）困难；预期通过：在包含环境跳变与多工况上下文的序列测试中，取得显著低于静态约束学习与无核验衰减基线的全序列累计任务成本证据验证。”**

### 4.2 决策与更新算法伪代码

```python
class JointBeliefActivePlanner:
    def __init__(self, T_z, P_obs_given_z, costs):
        # 4维联合信念向量: [ (dry, broad), (dry, narrow), (wet, broad), (wet, narrow) ]
        self.b = np.array([0.45, 0.45, 0.05, 0.05])
        self.T_z = T_z  # 2x2 马尔可夫转移矩阵
        self.P_obs_z = P_obs_given_z  # 探针似然混淆矩阵
        self.costs = costs  # {nom: 10, detour: 35, fail: 100, probe: 3.5}

    def predict_time_step(self):
        # 仅对 z 轴做马尔可夫扩散，theta 轴保持不变
        b_mat = self.b.reshape((2, 2))  # 行: z (0=dry, 1=wet), 列: theta (0=broad, 1=narrow)
        b_pred = self.T_z.T @ b_mat
        self.b = b_pred.flatten()

    def select_action(self, x_t):
        # 1. 计算直接执行的失效率与期望代价
        p_fail = self.eval_fail_prob(self.b, x_t)
        cost_direct = (1 - p_fail) * self.costs['nom'] + p_fail * self.costs['fail']
        cost_detour = self.costs['detour']
        val_no_probe = min(cost_direct, cost_detour)

        # 2. 计算调用单步探针的期望代价 (Myopic VoI)
        cost_probe = self.costs['probe']
        for o_idx, o_name in enumerate(['dry', 'wet']):
            p_o = sum(self.P_obs_z[o_idx, z_idx] * self.b[z_idx*2 + th_idx] 
                      for z_idx in [0,1] for th_idx in [0,1])
            if p_o < 1e-6:
                continue
            # 假设观测为 o 时的虚拟贝叶斯更新
            b_post = self.bayes_update_probe(self.b, o_idx)
            p_fail_post = self.eval_fail_prob(b_post, x_t)
            post_direct = (1 - p_fail_post) * self.costs['nom'] + p_fail_post * self.costs['fail']
            cost_probe += p_o * min(post_direct, cost_detour)

        # 3. 动作决策
        if cost_probe < val_no_probe:
            return "PROBE"
        elif cost_direct <= cost_detour:
            return "DIRECT"
        else:
            return "DETOUR"

    def update_execution(self, x_t, y_t):
        # 根据真实执行结果 y in {succ, fail} 更新联合信念
        likelihood = np.zeros(4)
        for i, (z, th) in enumerate([(0,0), (0,1), (1,0), (1,1)]):
            p_f = 1.0 if (z == 1 and (x_t == 'x_H' or th == 0)) else 0.0
            likelihood[i] = p_f if y_t == 'fail' else (1.0 - p_f)
        self.b = (likelihood * self.b) / np.sum(likelihood * self.b)

    def update_probe(self, o_t):
        # 根据探针观测 o in {dry, wet} 更新联合信念
        o_idx = 0 if o_t == 'dry' else 1
        self.b = self.bayes_update_probe(self.b, o_idx)

    def bayes_update_probe(self, b_prior, o_idx):
        lik = np.array([self.P_obs_z[o_idx, 0], self.P_obs_z[o_idx, 0],
                        self.P_obs_z[o_idx, 1], self.P_obs_z[o_idx, 1]])
        post = lik * b_prior
        return post / np.sum(post)

    def eval_fail_prob(self, b, x_t):
        # 计算在上下文 x_t 下的失效率: p_fail = sum b(z, theta) * I(fail)
        p_fail = 0.0
        for i, (z, th) in enumerate([(0,0), (0,1), (1,0), (1,1)]):
            if z == 1: # wet
                if x_t == 'x_H' or th == 0: # heavy-fast 或 broad 必然失败
                    p_fail += b[i]
        return p_fail
```

### 4.3 坦诚学术定位：已有理论的实例化 vs 原创新算法

面对上述代码与公式，进行最彻底的学术反省：
- **到底有没有发明新的数学运算？没有。**
  更新公式是标准 Bayes Rule；状态预测是标准 Markov Chain Chapman-Kolmogorov 方程；动作决策是标准 Howard (1966) 单步 VoI；
- **到底改变了什么？**
  仅仅改变了**状态变量的组织形式**（将以往分开考虑的环境变量与约束阈值合并成一个 4 元状态向量），并将其绑定到了移动机器人 Nav2 导航的任务输入接口上；
- **定位结论**：**本方案在本质上是一项标准的“贝叶斯决策理论在移动机器人导航容错中的领域实例化（Domain Application / Systems Instantiation）”，完全不具备提出全新机器学习方法论的创新高度。**

---

## 五、公平的手工可复核最小推演

为了完全消除仿真实验中物理引擎随机性与超参数调优带来的干扰，本节构建**所有量均可被审稿人手算复核的最小算例（Minimal Hand-checkable Walkthrough）**。

### 5.1 最小算例环境与参数定义

- **代价体系**：$C_{\text{nom}} = 10$，$\quad C_{\text{detour}} = 35$，$\quad C_{\text{fail}} = 100$，$\quad \tilde{c}(v) = 3.5$。
  - *阈值临界点*：令直接执行与直接绕行期望成本相等的临界失效率 $P^*$：
    $$(1 - P^*) \times 10 + P^* \times 100 = 35 \implies 90 P^* = 25 \implies P^* = \frac{25}{90} \approx 0.278$$
    即：**当失效率估计 $P_{\text{fail}} > 0.278$ 时，无核验下的理性决策必定选择绕行；反之直接执行。**
- **探针似然参数**：探针具有高精度但不绝对完美（观测混淆误差 $\epsilon = 0.05$）：
  $$P(o_{\text{dry}} \mid z_{\text{dry}}) = 0.95, \quad P(o_{\text{wet}} \mid z_{\text{dry}}) = 0.05$$
  $$P(o_{\text{wet}} \mid z_{\text{wet}}) = 0.95, \quad P(o_{\text{dry}} \mid z_{\text{wet}}) = 0.05$$
- **环境时变转移参数**：
  $$\lambda_{\text{dry}} = 0.20 \quad (\text{积水在每个时步有 } 20\% \text{ 概率彻底风干})$$
  $$\lambda_{\text{wet}} = 0.05 \quad (\text{干燥路面在每个时步有 } 5\% \text{ 概率被重新洒水打湿})$$
- **初始先验信念**：
  假设任务开始前，环境为常态干燥，对范围参数完全未知：
  $$b_0 = [P(z_{\text{dry}}, \theta_{\text{broad}})=0.45, \; P(z_{\text{dry}}, \theta_{\text{narrow}})=0.45, \; P(z_{\text{wet}}, \theta_{\text{broad}})=0.05, \; P(z_{\text{wet}}, \theta_{\text{narrow}})=0.05]$$

---

### 5.2 场景 1：环境稳定，范围过度推广（验证防误阻断）

- **物理真值设定**：环境保持潮湿 $z^* = z_{\text{wet}}$，物理约束仅对重载高速生效 $\theta^* = \theta_{\text{narrow}}$（即物理上 $x_L$ 完全可行，$x_H$ 必然打滑）。

#### Step 1.1：首轮任务到来，工况为重载高速 $x_1 = x_H$
- 预测步：先验失效率极低 $P_{\text{fail}} = 0.05 + 0.05 = 0.10 < 0.278$；
- 决策：直接执行；
- **物理结果：发生滑移硬碰撞！** 耗时 $100\,\text{s}$；
- **贝叶斯更新**：$x_H$ 失败提供强似然 $\implies$ 排除 $z_{\text{dry}}$（在干燥地面 $x_H$ 不可能失败）：
  $$b_1(z_{\text{wet}}, \theta_{\text{broad}}) = 0.50, \quad b_1(z_{\text{wet}}, \theta_{\text{narrow}}) = 0.50, \quad b_1(z_{\text{dry}}, \cdot) = 0.00$$
  *注意*：此时系统完全确定地面是湿的，但对 $\theta$（究竟是 $x_L$ 也会失败，还是仅 $x_H$ 失败）处于最大熵状态（各 $50\%$）。

#### Step 1.2：第二轮任务立即到来，工况为轻载慢速 $x_2 = x_L$（环境未变，仍为 $z_{\text{wet}}$）
- 此时在 $x_L$ 下，若 $\theta = \theta_{\text{broad}}$ 则失败，若 $\theta = \theta_{\text{narrow}}$ 则成功。
- 失效率估计：$P_{\text{fail}}(x_L) = b_1(z_{\text{wet}}, \theta_{\text{broad}}) = 0.50 > 0.278$；
- **无核验基准决策**：若无核验，系统由于 $P_{\text{fail}} = 0.50 > 0.278$，必定恐惧失败而**选择绕行**（成本 $35\,\text{s}$）。
- **探针价值计算**：由于此时机器人已知 $z = z_{\text{wet}}$，而探针仅测量 $z$ 的干湿，无法测量 $\theta$！
  $$P(o_{\text{wet}} \mid b_1) = 0.95, \quad P(o_{\text{dry}} \mid b_1) = 0.05$$
  - 若探测出 $o_{\text{wet}}$，后验仍是 $z_{\text{wet}}$，后验失效率仍为 $0.50$，后验动作依然只能绕行（成本 $35$）；
  - 探针不仅不能改变决策，白白多花 $3.5\,\text{s}$ 探针费！
  - $\mathbb{E}[\text{Cost} \mid \text{Probe}] = 3.5 + 35 = 38.5 > 35$。
  - **理性贝叶斯裁决：不核验，直接绕行（成本 35）！**
- **各基线表现对比**：
  - *简单粗暴经验规划（E-Graphs/全局黑名单）*：永久绕行该走廊，成本 $35\,\text{s}$；
  - *本方案（联合贝叶斯）*：由于无法直接测 $\theta$，在当前步同样理性选择绕行，成本 $35\,\text{s}$；
  - *Oracle 理论上限*：Oracle 知道 $\theta = \theta_{\text{narrow}}$，直接走 $x_L$ 畅通无阻，成本 $10\,\text{s}$。
- **阶段性深刻结论**：
  **当探针只能观测环境状态 $z$ 而不能直接观测约束阈值 $\theta$ 时，仅凭状态探针根本无法瞬间解决“范围过度推广”问题！** 必须等待系统在后续低风险或不可避免的情况下主动尝试一次 $x_L$ 成功，才能打破僵局。所谓“主动核验瞬间消除范围误阻断”在物理模型下被证伪。

---

### 5.3 场景 2：上下文固定，环境状态变化（验证防陈旧绕行）

- **物理真值设定**：沿用 Step 1.1 后的状态，任务工况固定为 $x = x_H$。但在两个任务之间，环境经历了保洁风干，$z^*$ 真实跃迁为 $z_{\text{dry}}$。

#### Step 2.1：第 3 轮任务到来，工况依然为重载高速 $x_3 = x_H$
- **时间演化步（Markov 预测）**：
  $$P(z_3 = z_{\text{dry}} \mid z_2 = z_{\text{wet}}) = \lambda_{\text{dry}} = 0.20$$
  $$P(z_3 = z_{\text{wet}} \mid z_2 = z_{\text{wet}}) = 1 - \lambda_{\text{dry}} = 0.80$$
  预测后验分布：
  $$\bar{b}_3(z_{\text{dry}}, \cdot) = 0.20, \quad \bar{b}_3(z_{\text{wet}}, \cdot) = 0.80$$
- **不核验选项评估**：
  - 在 $x_H$ 下，只要 $z = z_{\text{wet}}$ 就必失败，因此 $P_{\text{fail}} = 0.80$；
  - 直接执行成本：$0.20 \times 10 + 0.80 \times 100 = 82\,\text{s}$；
  - 直接绕行成本：$35\,\text{s}$；
  - 无核验基准：$\min(82, 35) = 35\,\text{s}$（直接绕行）。
- **核验选项（VoI）严格计算**：
  - 探针预测概率：
    $$P(o_{\text{dry}}) = 0.20 \times 0.95 + 0.80 \times 0.05 = 0.19 + 0.04 = 0.23$$
    $$P(o_{\text{wet}}) = 0.20 \times 0.05 + 0.80 \times 0.95 = 0.01 + 0.76 = 0.77$$
  - *分支 1：探针返回 $o_{\text{dry}}$（概率 0.23）*：
    后验概率 $P(z_{\text{wet}} \mid o_{\text{dry}}) = \frac{0.04}{0.23} \approx 0.174$。
    此时失效率降至 $0.174 < 0.278$！
    后验最优动作为**直接放行执行**！
    该分支期望成本：$(1 - 0.174) \times 10 + 0.174 \times 100 = 8.26 + 17.4 = 25.66\,\text{s}$；
  - *分支 2：探针返回 $o_{\text{wet}}$（概率 0.77）*：
    后验概率 $P(z_{\text{wet}} \mid o_{\text{wet}}) = \frac{0.76}{0.77} \approx 0.987$。
    此时失效率极高，后验最优动作为**绕行**，耗时 $35\,\text{s}$；
  - **探针总期望成本**：
    $$\mathbb{E}[\text{Cost} \mid \text{Probe}] = \tilde{c}(v) + 0.23 \times 25.66 + 0.77 \times 35 = 3.5 + 5.90 + 26.95 = 36.35\,\text{s}$$
  - *判定*：$36.35 > 35$。此时风干概率仅 20%，探针收益不足以抵消其 $3.5\,\text{s}$ 代价，**系统依然选择绕行！**

#### Step 2.2：时间继续流逝，再过 3 个时步（风干累计置信度提升）
- 经过连续转移后，积水风干先验上升至 $\bar{P}(z_{\text{dry}}) = 0.55$，$\bar{P}(z_{\text{wet}}) = 0.45$；
- **重新计算探针价值**：
  - 无核验基准：直接执行期望成本 $0.55 \times 10 + 0.45 \times 100 = 50.5 > 35 \implies$ 绕行（$35\,\text{s}$）；
  - 探针观测边际概率：
    $$P(o_{\text{dry}}) = 0.55 \times 0.95 + 0.45 \times 0.05 = 0.5225 + 0.0225 = 0.545$$
    $$P(o_{\text{wet}}) = 0.455$$
  - 若 $o_{\text{dry}}$，后验 $P(z_{\text{wet}} \mid o_{\text{dry}}) = \frac{0.0225}{0.545} \approx 0.0413$；
    直接执行成本：$0.9587 \times 10 + 0.0413 \times 100 = 9.587 + 4.13 = 13.72\,\text{s}$；
  - 若 $o_{\text{wet}}$，后验绕行成本：$35\,\text{s}$；
  - **探针总期望成本**：
    $$\mathbb{E}[\text{Cost} \mid \text{Probe}] = 3.5 + 0.545 \times 13.72 + 0.455 \times 35 = 3.5 + 7.48 + 15.93 = 26.91\,\text{s}$$
  - **历史性逆转**：$26.91 < 35$！**此时探针期望成本显著低于直接绕行（净节省 8.09 秒）！**
  - **执行动作：调用探针** $\implies$ 探针测得 $o_{\text{dry}}$ $\implies$ 机器人安全直行，实际耗时 $3.5 + 10 = 13.5\,\text{s}$。
- **基线对比**：
  - *无衰减静态记忆（永久黑名单）*：继续盲目绕行，耗时 $35\,\text{s}$（净亏损 $21.5\,\text{s}$）；
  - *机械 TTL（定时清零重试）*：若恰好清零且地面已干，耗时 $10\,\text{s}$；但若清零时地面未干，则遭遇 $100\,\text{s}$ 灾难性硬破坏；
  - *本方案（联合贝叶斯 VoI）*：在置信度成熟时以 $3.5\,\text{s}$ 的极小探针代价，安全平稳自愈，耗时 $13.5\,\text{s}$。

---

### 5.4 场景 3：核验成本过高或无信息，理性不核验（验证抗滥用）

- **参数修改**：假设使用昂贵或高风险的物理探针（例如需要停机展开机械臂轻触门框，或探针能耗过大），使其综合代价升为 $\tilde{c}(v) = 15\,\text{s}$。
- 在 Step 2.2 的相同置信状态下（风干先验 55%）：
  - 探针后验期望耗时为 $23.41\,\text{s}$；
  - 加上探针自身成本 $15\,\text{s}$：
    $$\mathbb{E}[\text{Cost} \mid \text{Probe}] = 15 + 23.41 = 38.41\,\text{s} > 35\,\text{s}$$
- **裁决**：算法自动放弃探针，直接采纳绕行（$35\,\text{s}$）。
- **推演结论**：数学闭环模型具有严格的自抑能力，绝不会出现“为了核验而核验”的探针滥用。

---

### 5.5 各基线全过程对比矩阵

在上述 3 轮推演全过程中，各基线表现如下表：

| 方法 / 基线 | Step 1.1 (首发 $x_H$ 失败) | Step 1.2 ($x_L$ 遭遇范围混淆) | Step 2.2 (环境风干过时自愈) | 3步累计总成本 | 是否发生重复失败？ | 是否产生陈旧阻断？ |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline 1: 简单离散缓存** | 盲目重试失败 (100s) | 误当全新场景盲试失败 (100s) | 遇 $x_H$ 永久死锁绕行 (35s) | **235 s** | 严重重复 (2次) | 是 |
| **Baseline 2: 固定 TTL 重置** | 失败 (100s) | TTL期内盲目绕行 (35s) | TTL到期盲试 (若干则10s,未干100s) | **145~235 s** | 高风险 | 周期性震荡 |
| **Baseline 3: 静态连续分类器** | 失败 (100s) | 拟合点位全局阻断 (35s) | 永久记录几何不可行绕行 (35s) | **170 s** | 无 | 永久陈旧阻断 |
| **Baseline 4: 独立更新启发式 (03b3abb 原稿)** | 失败 (100s) | SVDD与后验各算各的，震荡决策 (35s) | 启发式衰减，强行探针 (13.5~38s) | **150~175 s** | 偶发 | 偶发 |
| **标准联合贝叶斯参考解 (Exact Bayes)** | 失败 (100s) | 理性避险绕行 (35s) | 适时调用低成本探针安全自愈 (13.5s) | **148.5 s** | **0 次** | **自适应消除** |
| **Oracle 参考上界 (上帝真值视界)** | 避开失败绕行 (35s) | 获知 $\theta_{\text{narrow}}$ 直行 (10s) | 获知地面已干全速直行 (10s) | **55.0 s** | 0 次 | 0 次 |

### 5.6 算例证明了什么，没有证明什么

- **算例确实证明了**：
  1. 将时变跳变 $z_t$ 与范围参数 $\theta$ 纳入同一个联合贝叶斯滤波框架，在逻辑与数学上能够自洽解耦“时效过时”与“范围混淆”；
  2. 引入单步 VoI 机制，确实能够阻止盲目探针消耗，并在环境恢复时以低成本自愈解除陈旧阻断。
- **算例坚决没有证明（必须清醒承认）**：
  1. **没有证明方法创新**：因为上述全过程演算所用的公式，无一例外全是经典教科书贝叶斯滤波与 VoI 的手算展开，**本方案在数学上与 Standard Exact Bayes 完全等价，属于同一理论实体**；
  2. **没有证明高维可扩展性**：算例只有可怜的 2 个状态、2 个参数。现实中如果参数连续（如摩擦系数取 $[0.05, 0.9]$ 的实数区间，载荷取 $[0, 10]$ 的连续实数），贝叶斯更新退化为连续非线性积分，目前并无任何可闭环的有效算法支撑；
  3. **没有证明真实物理有效性**：现实机器人探针存在未建模动力学扰动与接触漂移，手算假设的完美高斯混淆矩阵在 Gazebo 或实物中极易失效。

---

## 六、修正后的未来评测方案（只设计，不执行）

若后续研究者需要验证上述解耦机制，必须推翻原稿中“把所有变化混在一起”的混乱设计，严格执行**正交隔离评测协议**。

### 6.1 正交隔离的测试协议

必须建立两个完全独立的实验流（Streams），严禁混合：

```
[独立实验流 1: 纯范围泛化流] ------------------------> 统计指标: 误阻断率 (FPBR)
- 环境潜变量恒定锁定 (z* 恒等于 wet, 绝不风干)
- 仅让任务上下文 x 随机交替变化 (x_L, x_H, 中间工况)
- 纯粹检验算法能否精准识别边界, 杜绝将 x_H 的失败错误推广至 x_L

[独立实验流 2: 纯时变自愈流] ------------------------> 统计指标: 陈旧自愈延迟 (L_heal)
- 任务上下文恒定锁定 (x* 恒等于 x_H, 绝不换轻载)
- 仅让环境状态按马尔可夫链发生物理跃迁 (wet -> dry -> wet)
- 纯粹检验算法能否在工况不变时, 依靠时效扩散与探针打破陈旧死锁
```

### 6.2 统计分析单元与实际效应量阈值

1. **统计单元定义**：
   - 严禁将单次 50 步任务序列中的“每一步”当作独立同分布（IID）样本；
   - **统计检验的唯一合法单位是独立的完整任务序列（Full Episode / Run）**。每次评测至少运行 30 个具有不同随机种子的独立完整序列（每序列 30 步）；
2. **实际效应量阈值（Practical Significance Threshold）**：
   - 彻底删除“$p > 0.05$ 判定等效”的学术不规范陈述；
   - 预先规定具备实际工程与科学意义的**最小效应量（Minimum Effect Size）**：
     $$\Delta \text{Cost} = \frac{J_{\text{baseline}} - J_{\text{proposed}}}{J_{\text{baseline}}} \ge 10.0\%$$
   - 只有当 30 次独立序列的配对 Wilcoxon 符号秩检验在显著性水平 $\alpha = 0.01$ 下显著，且成本降低的点估计与 $95\%$ 置信区间下界均严格大于 $10.0\%$ 时，方可认为存在实质性增益。若改进幅度在 $0\% \sim 5\%$ 之间，一律判定为“统计显著但无实际工程意义的边际扰动”。

### 6.3 物理假设标记与虚假承诺撤回

1. **撤回未测性能承诺**：
   - 撤回原稿中宣称的“单次元决策耗时 $< 2\,\text{ms}$”、“内存占用数十 KB”等未经真机 Profile 测量的数字；
2. **所有物理量标记为“待验假设”**：
   - 地面临界摩擦系数 $\mu = 0.25$、探针耗时 $3.0\,\text{s}$、滑移检出率 $95\%$ 等，均明确定义为**人工构造的仿真待验假设（Simulation Hypotheses）**，绝不宣称为真实物理事实。

---

## 七、研究决策判定：No-Go

### 7.1 判定结论与核心依据

依据任务规范设定的判定规则：
- *Go*：找到具体、证据支持的未解决困难；方法差异已明确；可以开展小规模实现来验证。
- *Conditional Go*：问题有价值，但仍有一个明确的关键不确定性；列出能解决它的最小验证及停止条件。
- *No-Go*：优势依赖削弱基线、额外先验或人为场景设定，或当前方法实质上已被已有方法覆盖。

我们做出极其严肃、冷静且不容妥协的最终裁决：

$$\mathbf{FINAL \ DECISION: \quad No-Go \quad (终止独立方法论研究)}$$

---

### 7.2 为什么必须判定为 No-Go（拒绝 Conditional Go 拖延）

1. **理论新颖性彻底瓦解（Already Covered by Classical Theory）**：
   在第 2 节与第 3 节的严密推导中已经证明，一旦把问题收缩为一个可以形式化求解的数学闭环，该模型**百分之百等价于经典的离散状态 POMDP / 贝叶斯主动假设检验（Bayesian Active Hypothesis Testing）**。
   - 状态转移用的是经典的马尔可夫链；
   - 信念更新用的是教科书上的贝叶斯定理；
   - 探针调度用的是 Howard 在 1966 年提出的单步信息价值（VoI）；
   - 没有任何一个新的算子、没有新的损失函数、没有新的优化算法。如果将这样的工作包装为“提出了全新的 SCOPE-VERIFY 约束学习理论”投稿 SCI，必然被国际同行一眼看穿本质是已有理论的习题级演练。

2. **前沿基石已被顶会顶刊严密覆盖（Literature Grounding Collapsed）**：
   - Chou et al. (CoRL 2020) 已经做了不确定约束的闭环执行信念更新；
   - Wang et al. (RSS 2021) 已经做了 TAMP 中的主动可行性核验；
   - Krajnik et al. (IEEE TRO 2017) 已经做了非平稳时变环境建模。
   将三者在离散层面拼在一起，属于**典型的工程系统集成应用**。用户提示词第一条明确指出：“不得以组合多个模块为由直接宣布新颖性成立。”

3. **优势完全建立在“对基线的信息剥夺”上（Baseline Asymmetry）**：
   在第 5 节手算推演中暴露无遗：本方案之所以能比 Baseline 1（缓存）和 Baseline 3（静态分类器）省时间，**根本不是因为本方案算法高明，而是因为我们给本方案额外配备了一个“探针工具”以及“马尔可夫转移矩阵”先验知识**！一旦允许基线拥有同样的探针与先验，基线就直接变成了“标准联合贝叶斯解”，本方案与其没有任何算法差别。

4. **拒绝用 Conditional Go 作为逃避决断的缓冲**：
   若给“Conditional Go”，借口只能是“虽然离散被覆盖了，但连续高维也许能做”。然而：
   - 连续高维下的非线性非凸求解极其困难，远非几个月内拼凑简单启发式可以解决；
   - 强行推进只会诱导团队继续编写充满人工特调阈值（力矩、速度、滑移率）的脆弱仿真脚本，并在测试中通过刻意劣化基线参数来制造虚假胜利，彻底滑向学术伪劣研究。

---

### 7.3 明确的止步清单与后续建议

基于 No-Go 裁决，下达明确的止步清单：

1. **立即停止事项（What to Stop）**：
   - 停止以“自愈记忆”、“约束适用范围学习”、“主动核验算法”为题撰写任何具有方法学创新诉求的学术论文草稿；
   - 停止开发任何试图在连续空间拟合脆弱 SVDD 超平面的中间件脚本；
   - 停止在 ROS 2 / Gazebo 中为此虚构方法搭建专门的评测场景；
   - 彻底关闭 `research/core-method-design` 的算法演进通道。

2. **已有工作的合理归宿建议（Constructive Path Forward）**：
   - 原有 `73b0b83` 基准成果中的 LaTeX 主稿（[`paper/submission_source/`](file:///code/failmem-ros2-agent/paper/submission_source/)）依然是一个中规中矩、诚实记录了 ROS 2 真实探针恢复实验与离线复现证据的工程技术成果；
   - 建议作者团队**彻底放弃将“理论方法创新”作为卖点，转向真实的“系统经验与工程基准（System Paper / Benchmark / Lessons Learned）”**，如 IEEE Robotics & Automation Magazine (RAM) 的应用栏目，或者 ROSCon 等系统级开源社区，真实报告在 ROS 2 机器人部署中面对执行失败时的工程处理经验；
   - 不包装、不神化、不造词，回归学术研究本真的诚实与质朴。
