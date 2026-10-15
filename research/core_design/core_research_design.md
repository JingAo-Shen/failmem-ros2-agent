# 核心研究设计修订与去留判定：基于带成本核验解耦失败范围过度推广与环境过时的闭合分析

**文档性质**：学术方法论严密核验、最小模型推演与最终去留裁决（非代码开发、非实验扩容、非投稿准备）  
**基准成果版本**：`73b0b83a836a128b09aa1137137cf97757183e8d`（已有实现、数据与文本完全冻结）  
**设计迭代版本**：基于 `03b3abb` 的彻底纠偏与收缩审定  
**设计分支**：`research/core-method-design`  
**执行边界**：0 新增 Gazebo 场景、0 机器人算法代码、0 模型训练、0 真实 LLM 调用。纯手工推演、数学闭环与文献原文逐项核实。

---

## 目录

- [一页结论与去留判定](#一页结论与去留判定)
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

## 一页结论与去留判定

经过对文献原文的逐字复核、数学模型的严格闭环构建以及离线数值推演，本轮对“在部分可观测下通过带成本核验解耦失败经验过度推广与环境过时”这一具体方案得出审定结论：

> **“当前离散联合信念 + 单步 VoI 方案尚未建立独立的方法创新，因此停止以 SCOPE-VERIFY 新算法推进。”**

### 核心论据与范围界定

1. **文献事实的真实边界**：
   - 纠正了前期调研中关于 `arXiv:1804.03215` 的错配引用；
   - 精读 **Glen Chou, Dmitry Berenson, Necmiye Ozay (CoRL 2020 / PMLR 2021)** 的代表作后确认：该工作提出了“对不确定约束维护置信度（Belief over constraints）”以及“在闭环执行中利用观测数据进行信念更新（Belief updates during execution）”。但这并不意味着 Chou 等人已完全解决所有动态失败约束问题（Chou 侧重于静态环境中的连续几何约束，未显式处理非平稳离散环境跳变及主动诊断探针）；
   - 然而，Chou 的工作无可辩驳地表明，“在执行中维护和更新约束信念”已有坚实文献基础，不能把“约束可以在线更新”本身作为本方案的原创发明。

2. **当前方案的核心机制落入已有理论范畴**：
   - 当把研究目标收缩至“区分失败是来自（A）范围过度推广还是（B）环境潜在状态变化”时，所构建的包含可见上下文 $x$、潜在环境状态 $z$、约束范围参数 $\theta$ 的离散联合概率模型，本质上是标准联合贝叶斯滤波 $b_t(z_t, \theta) = P(z_t, \theta \mid \mathcal{H}_t)$ 配合单步信息价值（VoI）决策；
   - 该离散方案在形式化后，属于标准 POMDP 主动感知 / 贝叶斯决策理论在一个具体移动机器人故障场景下的直接应用（Domain Instantiation），尚未提炼出具有独立方法学价值的新机制或新算子。

3. **方法差异定位**：
   - 按照规范陈述：
     > “相对于最接近的现有方法，我们增加了在离散状态空间中将环境时变转移与离散范围参数置于同一联合贝叶斯信念中，并使用单步 VoI 调度探针；它针对将局部时变故障误当全局永久阻断（A/B 混淆）困难；预期通过在离散算例中优于忽略时变的静态约束学习器证据验证。”
   - 这一改动本质上是已有概率推断与决策理论的领域落地，不足以支撑命名为全新独立算法（如 SCOPE-VERIFY）并以理论创新为核心诉求推进。

4. **数值核验揭示的客观表现**：
   - 经离线数值程序核验，该方案的决策行为完全遵从标准联合贝叶斯推断；
   - 该方案在特定场景下相比“简单无状态缓存”的收益，来自于系统引入了马尔可夫转移先验与主动探针动作，而非全新的算法结构；
   - 此外，单步近视 VoI 与多步有限时域 POMDP 最优策略存在结构性分歧（在特定序列下单步 VoI 会因近视而错失通过物理执行消除参数不确定性的长远收益）。

5. **严格限定的去留判定**：
   - 本判定严格限定为：**当前离散联合信念 + 单步 VoI 方案尚未建立独立的方法创新，停止以新算法推进**；
   - 本判定**不得扩展**为：所有失败约束研究都已经被解决；使用已有概率框架必然没有创新；该项目必然不能发表；更换为系统论文或基准论文定位即可发表。

---

## 一、文献论证彻底核验与纠偏表

### 1.1 关键引用逐项核实与错配纠正

在前期设计文档中，存在一处严重的引用标识错配，本轮通过原始数据库进行了逐项核实与纠正：

1. **`arXiv:1804.03215` 错配纠正**：
   - *错误记录*：原稿将其标注为 Zi Wang, C. R. Garrett, L. P. Kaelbling, T. Lozano-Pérez 的《Learning Generalized Geometric Preconditions for Robot Task and Motion Planning》预印本。
   - *核验真相*：经检索 arXiv 官方数据库，`arXiv:1804.03215` 的真实论文为凝聚态物理领域的实验论文：
     > S. L. Chen et al., *"Pressure effects on the structural and superconducting transitions in $\text{La}_3\text{Co}_4\text{Sn}_{13}$"*, arXiv:1804.03215 [cond-mat.supr-con], 2018.
     该链接与机器人学毫无关系，系前期调研中的严重抓取/拼接错误，现予彻底纠正与剔除。
    - *真实对应文献确认*：
      - **IROS 2018**: Z. Wang, C. R. Garrett, L. P. Kaelbling, T. Lozano-Pérez, *"Active Model Learning and Diverse Action Sampling for Task and Motion Planning"*, in *IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)*, 2018, pp. 4107–4114. DOI: [10.1109/IROS.2018.8594027](https://doi.org/10.1109/IROS.2018.8594027).
      - **RSS 2021**: M. Noseworthy, I. Brand, C. Moses, S. Castro, L. P. Kaelbling, T. Lozano-Pérez, N. Roy, *"Active Learning of Abstract Plan Feasibility"*, in *Robotics: Science and Systems (RSS XVII)*, 2021. DOI: [10.15607/RSS.2021.XVII.043](https://doi.org/10.15607/RSS.2021.XVII.043).

### 1.2 纳入文献深度精读：Chou et al. (CoRL 2020 / PMLR 2021)

根据审定要求，系统精读了 Glen Chou, Dmitry Berenson, Necmiye Ozay 的代表作：
- **文献元数据**：Glen Chou, Dmitry Berenson, Necmiye Ozay, *"Uncertainty-Aware Constraint Learning for Adaptive Safe Motion Planning from Demonstrations"*, in *Proceedings of the 4th Conference on Robot Learning (CoRL 2020)*, PMLR vol. 155, pp. 1612–1639, 2021. 官方页面：[https://proceedings.mlr.press/v155/chou21a.html](https://proceedings.mlr.press/v155/chou21a.html).
- **精读原文核心机制**：
  1. *约束不确定性信念构建*（Section 3.1 & 4）：针对示教轨迹一致的潜在约束集合，利用鲁棒优化获得一个连续/参数化的约束置信分布（Belief over constraints），而非单一硬判定；
  2. *权衡性能与安全规划*（Section 5）：在置信空间中规划轨迹，使轨迹在最小化运动代价的同时，满足特定置信水平下的安全裕度；
  3. *执行期在线信念更新（Closed-loop Replanning with Belief Updates）*（Section 6）：在实际控制机器人执行轨迹时，持续采集在线传感数据（如触觉、接近觉或发生微接触/自由运动），将新观测代入贝叶斯/区间更新器修正约束信念，并自适应触发在线重规划；
  4. *实验验证*：在 7 自由度机械臂仿真与 12 维四旋翼上成功学习高维（达 30 维）不确定约束。
- **真实贡献与适用范围客观界定**：
  - *证实的事实*：该论文确凿地证明，**“对不确定约束维护概率信念”与“在执行过程中根据在线观测反馈动态更新约束信念并在线重规划”，在 2020 年已有严谨的方法与软硬件验证**。因此，“约束学习必然是静态确定性的、无法在执行中在线更新”这一前提被彻底推翻。
  - *未覆盖的范围（不夸大其已完全解决所有问题）*：Chou 等人的方法面向**静态环境中的连续几何障碍约束**，其在线更新依赖于机器人沿规划轨迹运动时被动收集的自由空间与接触观测；它**并未建模环境物理潜变量的非平稳时变跳变（如地面干湿、摩擦突变），亦未涉及针对特定操作上下文调度带成本的主动诊断探针**。

### 1.3 三大支柱领域最接近代表作精读

#### 类别 1：不确定约束学习与执行中信念更新
- **Chou et al. (CoRL 2020 / PMLR 2021)**（见 1.2 节）：基于示教与执行期反馈更新不确定几何约束。
- **Chou et al. (RSS 2020 / IJRR 2021)**：G. Chou, N. Ozay, D. Berenson, *"Learning Constraints from Demonstrations with Predictable Generalization"*, IJRR, vol. 40, no. 8, pp. 1023–1044, 2021. 利用凸包与 SVDD 给出泛化误差界，但环境假设为静态。

#### 类别 2：带成本的主动核验、主动学习与信息价值决策
- **Noseworthy et al. (RSS 2021)**：M. Noseworthy, I. Brand, C. Moses, S. Castro, L. P. Kaelbling, T. Lozano-Pérez, N. Roy, *"Active Learning of Abstract Plan Feasibility"*, RSS 2021. 该工作研究任务与运动规划中抽象规划可行性分类器的主动学习。机制上采用好奇心驱动的主动探索（Curiosity-driven exploration）指导采样；不仅在 PyBullet 仿真环境中进行了系统评估，还在**真实的 Franka Emika Panda 7自由度机械臂**上针对非均匀质量分布物体的抓取与放置任务进行了硬件物理验证。其主动查询在规划可行性不确定区域采样，但其核心考量的是可行性预测模型的主动收敛，未在移动机器人导航的实时时变成本流中调度物理探针。
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
| **主动可行性核验**<br>Noseworthy et al. (RSS 2021) | 好奇心驱动主动探索，并在 Franka Panda 真机上学习抽象动作可行性 | **主动采样的目标是离线/规划前快速收敛可行性分类器边界，未建模运行中带硬件耗时风险的在线即时诊断探针** | 核验动作为带有硬件执行耗时与轻微物理风险的在线即时探针动作（如力矩脉冲试探） | **场景差异，非方法差异**：VoI 的计算逻辑与目标函数在数学形式上同属决策论框架，仅成本物理含义与应用场景不同。 |
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
        # self.T_z 为列和为 1 的列随机转移矩阵，按标准列向量乘法进行前向预测: p_t = T_z @ p_{t-1}
        b_mat = self.b.reshape((2, 2))  # 行: z (0=dry, 1=wet), 列: theta (0=broad, 1=narrow)
        b_pred = self.T_z @ b_mat
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

为了完全消除仿真实验中物理引擎随机性与超参数调优带来的干扰，本节构建**所有量均可被数值脚本与手算精确复核的最小算例（Minimal Hand-checkable Walkthrough）**。对应独立数值验证脚本见 [`research/core_design/verify_toy_model.py`](file:///code/failmem-ros2-agent/research/core_design/verify_toy_model.py) 与日志 [`research/core_design/toy_model_verification.log`](file:///code/failmem-ros2-agent/research/core_design/toy_model_verification.log)。

### 5.1 最小算例环境与参数定义

- **代价体系**：$C_{\text{nom}} = 10\,\text{s}$，$\quad C_{\text{detour}} = 35\,\text{s}$，$\quad C_{\text{fail}} = 100\,\text{s}$，$\quad \tilde{c}(v) = 3.5\,\text{s}$。
  - *阈值临界点*：令直接执行与直接绕行期望成本相等的临界失效率 $P^*$：
    $$(1 - P^*) \times 10 + P^* \times 100 = 35 \implies 90 P^* = 25 \implies P^* = \frac{25}{90} \approx 0.278$$
    即：**当失效率估计 $P_{\text{fail}} > 0.278$ 时，无核验下的理性决策必定选择绕行；反之直接执行。**
- **探针似然参数**：探针具有高精度但不绝对完美（观测混淆误差 $\epsilon = 0.05$）：
  $$P(o_{\text{dry}} \mid z_{\text{dry}}) = 0.95, \quad P(o_{\text{wet}} \mid z_{\text{dry}}) = 0.05$$
  $$P(o_{\text{wet}} \mid z_{\text{wet}}) = 0.95, \quad P(o_{\text{dry}} \mid z_{\text{wet}}) = 0.05$$
- **环境时变转移参数**：列随机马尔可夫转移矩阵（满足列和守恒 $\sum_{i} T_{ij} = 1$）：
  $$\mathbf{T}_z = \begin{bmatrix} 1 - \lambda_{\text{wet}} & \lambda_{\text{dry}} \\ \lambda_{\text{wet}} & 1 - \lambda_{\text{dry}} \end{bmatrix} = \begin{bmatrix} 0.95 & 0.20 \\ 0.05 & 0.80 \end{bmatrix}$$
  其中 $\lambda_{\text{dry}} = 0.20$（积水每步有 $20\%$ 概率风干），$\lambda_{\text{wet}} = 0.05$（干燥路面每步有 $5\%$ 概率被打湿）。列向量时变转移满足 $p_t = \mathbf{T}_z p_{t-1}$。
- **初始先验信念**：
  假设任务开始前，环境以 $90\%$ 概率干燥，对范围参数完全未知：
  $$b_0 = [P(z_{\text{dry}}, \theta_{\text{broad}})=0.45, \; P(z_{\text{dry}}, \theta_{\text{narrow}})=0.45, \; P(z_{\text{wet}}, \theta_{\text{broad}})=0.05, \; P(z_{\text{wet}}, \theta_{\text{narrow}})=0.05]$$

#### 初始先验下的单步期望成本核算与叙事纠正

在初始先验 $b_0$ 下，若面临首个重载高速任务 $x_H$：
- 直接执行失效率：$P_{\text{fail}}(x_H) = 0.05 + 0.05 = 0.10$；
- 直接执行期望成本：$\mathbb{E}[\text{Cost} \mid \text{Direct}] = 0.90 \times 10 + 0.10 \times 100 = 19.00\,\text{s}$；
- 直接绕行期望成本：$\mathbb{E}[\text{Cost} \mid \text{Detour}] = 35.00\,\text{s}$；
- 探针核验期望成本（经离线程序与手算严格枚举）：
  - 探针边际概率：$P(o_{\text{dry}}) = 0.90 \times 0.95 + 0.10 \times 0.05 = 0.860$；$P(o_{\text{wet}}) = 0.140$；
  - 测得 $o_{\text{dry}}$ 后的后验失效率降至 $0.0058$，后验直行期望成本为 $10.523\,\text{s}$；
  - 测得 $o_{\text{wet}}$ 后的后验失效率升至 $0.6786 > 0.278$，后验最优动作为绕行（$35.00\,\text{s}$）；
  - 探针总期望成本：$\mathbb{E}[\text{Cost} \mid \text{Probe}] = 3.5 + 0.860 \times 10.523 + 0.140 \times 35.00 = 17.45\,\text{s}$。
- **叙事错配纠正**：
  由于 $\mathbb{E}[\text{Probe}] = 17.45\,\text{s} < \mathbb{E}[\text{Direct}] = 19.00\,\text{s} < \mathbb{E}[\text{Detour}] = 35.00\,\text{s}$，智能体在第 1 步若自主决策，**必定选择主动核验（Probe）**，进而探出潮湿并安全绕行，**绝不会盲目直行导致 100s 碰撞**！
  因此，后文推演中的“首发失败”**不能叙述为当前策略的内生决策产物，而必须被设定为外生的、所有对比方案共同的历史前提**（例如：系统在接入该策略前由人工或无感知策略在 $x_H$ 下遭遇了一次外生打滑失败并记录在案）。

---

### 5.2 场景 1：环境稳定，范围过度推广（验证防误阻断与真值一致性）

- **外生初始历史**：系统在 $x_0 = x_H$ 下发生外生打滑失败，贝叶斯后验排除 $z_{\text{dry}}$，得到公共初始信念：
  $$b_1(z_{\text{wet}}, \theta_{\text{broad}}) = 0.50, \quad b_1(z_{\text{wet}}, \theta_{\text{narrow}}) = 0.50, \quad b_1(z_{\text{dry}}, \cdot) = 0.00$$
- **物理真值设定**：环境保持潮湿 $z^* = z_{\text{wet}}$，真实物理约束仅对重载高速生效 $\theta^* = \theta_{\text{narrow}}$。
  - **重要物理真值一致性**：在 $(z_{\text{wet}}, \theta_{\text{narrow}})$ 下，**工况 $x_L$ 物理上完全可行，执行耗时为标称 $10\,\text{s}$！** 任何策略若在物理世界尝试执行 $x_L$，其物理结果必定是成功（耗时 $10\,\text{s}$），绝不能在不同方案下人为赋予相反的物理真值。

#### Step 1：第二轮任务到来，工况切换为轻载慢速 $x_1 = x_L$
- **事前期望成本评估（Ex-ante Expected Costs）**：
  - 联合贝叶斯模型失效率估计：$P_{\text{fail}}(x_L) = b_1(z_{\text{wet}}, \theta_{\text{broad}}) = 0.50 > 0.278$；
  - 直接执行期望成本：$0.50 \times 10 + 0.50 \times 100 = 55.0\,\text{s}$；
  - 直接绕行期望成本：$35.0\,\text{s}$；
  - 探针成本：因已确知 $z = z_{\text{wet}}$，探针仅能测干湿，无法测量 $\theta$，探针无决策改变价值，$\mathbb{E}[\text{Cost} \mid \text{Probe}] = 3.5 + 35 = 38.5\,\text{s}$；
  - 单步近视 VoI 决策：**选择绕行（Detour），事前期望成本 $35.0\,\text{s}$**。
- **事后实现成本与各基线客观对比（Ex-post Realized Costs）**：
  - *空间障碍物缓存（Condition O）*：将走廊视为被障碍物阻断，强制绕行，事后实现成本 **$35.0\,\text{s}$**；
  - *工况条件缓存（Condition C）*：由于历史失败记录键为 $(e, x_H)$，当前工况 $x_L$ 键不匹配，放行直行。由于物理真值为 $\theta_{\text{narrow}}$，**物理执行成功，事后实现成本仅为 $10.0\,\text{s}$**！
  - *单步联合贝叶斯（Myopic Bayes）*：由于事前失效率为 $50\%$，出于理性避险选择绕行，事后实现成本 **$35.0\,\text{s}$**；
  - *Oracle 理论上界*：获知物理真值，直接通行，实现成本 **$10.0\,\text{s}$**。
- **深刻的反思与区分**：
  - 条件缓存（Condition Cache）在这一步的事后实现成本（$10.0\,\text{s}$）优于单步贝叶斯（$35.0\,\text{s}$），是因为它恰好撞上了真值为 narrow 的好运气；但若真值为 broad，条件缓存将承受 $100\,\text{s}$ 灾难性硬破坏。
  - 单步贝叶斯在此步选择绕行，属于事前理性的风险规避（以 $35\,\text{s}$ 规避 $55\,\text{s}$ 的期望风险）。
  - **核心局限**：这也暴露了状态探针的致命短板——**纯环境状态探针无法区分参数 $\theta$ 的范围边界**，单步近视策略在此处同样无法立刻解除误阻断。

---

### 5.3 场景 2：上下文固定，环境状态变化（验证防陈旧绕行）

- **物理真值设定**：任务工况固定为重载高速 $x = x_H$。环境发生非平稳物理风干，$z^*$ 跃迁为 $z_{\text{dry}}$。

#### Step 2.1：第 3 轮任务到来，工况为 $x_3 = x_H$（刚经历 1 步时变转移）
- **时间演化预测**：
  $$\bar{b}_3(z_{\text{dry}}) = 0.20, \quad \bar{b}_3(z_{\text{wet}}) = 0.80$$
- **期望成本核算**：
  - 直接执行期望成本：$0.20 \times 10 + 0.80 \times 100 = 82.0\,\text{s}$；
  - 直接绕行期望成本：$35.0\,\text{s}$；
  - 探针总期望成本：$3.5 + 0.23 \times 25.66 + 0.77 \times 35.0 = 36.35\,\text{s}$；
  - 决策：$36.35 > 35.0 \implies$ **探针收益不足以补偿代价，系统继续选择绕行（实现成本 $35.0\,\text{s}$）**。

#### Step 2.2：时间继续流逝，经历连续转移（风干先验置信度上升）
- 经过连续预测演化后，风干先验上升至 $\bar{P}(z_{\text{dry}}) = 0.55$，$\bar{P}(z_{\text{wet}}) = 0.45$；
- **期望成本逆转**：
  - 无核验基准：直接执行期望成本 $50.5\,\text{s} > 35\,\text{s} \implies$ 绕行（$35.0\,\text{s}$）；
  - 探针边际概率：$P(o_{\text{dry}}) = 0.545$，$P(o_{\text{wet}}) = 0.455$；
  - 探针总期望成本：
    $$\mathbb{E}[\text{Cost} \mid \text{Probe}] = 3.5 + 0.545 \times 13.72 + 0.455 \times 35.0 = 26.91\,\text{s} < 35.0\,\text{s}$$
  - **决策：触发调用探针！** 探针测得 $o_{\text{dry}}$，后验失效率降至 $4.13\%$，放行直行。
  - **事后实现成本**：探针耗时 $3.5\,\text{s} +$ 直行耗时 $10.0\,\text{s} = \mathbf{13.5\,\text{s}}$（相比盲目绕行净节省 $21.5\,\text{s}$）。

---

### 5.4 场景 3：单步贪心 VoI 与多步有限时域 POMDP 最优策略的结构性分歧

为核实单步近视（Myopic）VoI 的理论健全性，离线脚本使用穷举法对 3 步有限时域 POMDP（任务序列上下文已知，全树评估）进行了最优求解。

在工况序列固定为轻载慢速 `['x_L', 'x_L', 'x_L']`、初始信念为 $b_1$（对 $\theta$ 处于 50/50 最大熵状态）的条件下：
- **单步贪心 VoI 评估（第 0 步）**：
  - $\mathbb{E}[\text{Direct}] = 55.0\,\text{s}$
  - $\mathbb{E}[\text{Detour}] = 35.0\,\text{s}$
  - $\mathbb{E}[\text{Probe}] = 38.5\,\text{s}$
  - **单步贪心决策：选择 DETOUR**（单步视角下畏惧 55s 的即时失败期望风险）。
- **3 步有限时域 POMDP 全局最优评估（第 0 步）**：
  - 若第 0 步选择 DETOUR：3 步全期望累计成本为 **$99.20\,\text{s}$**；
  - 若第 0 步选择 PROBE：3 步全期望累计成本为 **$102.15\,\text{s}$**；
  - 若第 0 步选择 DIRECT：
    - 以 $50\%$ 概率遭遇失败（$\theta_{\text{broad}}$）：当前耗时 $100\,\text{s}$，但失败确定性揭示了 $\theta = \theta_{\text{broad}}$，后续 2 步确定性绕行（$35 \times 2 = 70\,\text{s}$），总计 $170\,\text{s}$；
    - 以 $50\%$ 概率通行成功（$\theta_{\text{narrow}}$）：当前耗时 $10\,\text{s}$，且成功确定性排除了 $\theta_{\text{broad}}$（确立 $\theta = \theta_{\text{narrow}}$），永久解锁后续 $x_L$ 通行权，后续 2 步安全直行（期望总计 $27.3\,\text{s}$），总计 $37.3\,\text{s}$；
    - 3 步全期望累计成本：$0.5 \times 170 + 0.5 \times 37.3 = \mathbf{98.65\,\text{s}}$！
  - **多步全局决策：选择 DIRECT！**
- **重要理论发现**：
  - **单步 VoI 与多步 POMDP 最优解在此处发生直接分歧！**
  - **原因剖析**：物理执行本身具有**对偶控制（Dual Control）与主动信息探索价值**——直接尝试执行 $x_L$ 虽有单步失败风险，但它能够彻底消除范围参数 $\theta$ 的不确定性，从而为后续步骤带来巨大的长远收益。
  - **单步近视 VoI 在数学结构上无法感知这种多步跨期信息增益，表现出系统性的过度保守与短视**。

---

### 5.5 各基线全过程对比矩阵（统一真值与事后实现成本）

对三步典型序列 `[任务1: x_L (wet, narrow), 任务2: x_H (wet, narrow), 任务3: x_H (dry, narrow)]`，统一物理真值下的事后实现成本对比如下：

| 方法 / 基线 | Step 1: $x_L$ ($z_{\text{wet}}, \theta_{\text{narrow}}$) | Step 2: $x_H$ ($z_{\text{wet}}, \theta_{\text{narrow}}$) | Step 3: $x_H$ ($z_{\text{dry}}, \theta_{\text{narrow}}$) | 3步事后累计耗时 | 是否发生重复失败？ | 是否产生陈旧阻断？ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline 1: 空间障碍物缓存 (O)** | 绕行 (35.0s) | 绕行 (35.0s) | 绕行 (35.0s) | **105.0 s** | 0 次 | 是 (地面干后仍绕行) |
| **Baseline 2: 简单工况缓存 (C)** | 直行成功 (10.0s) | 绕行 (35.0s) | 绕行 (35.0s) | **80.0 s** | 0 次 | 是 (地面干后仍绕行) |
| **Baseline 3: 单步联合贝叶斯 (Myopic)** | 避险绕行 (35.0s) | 绕行 (35.0s) | 探针自愈 (13.5s) | **83.5 s** | **0 次** | **自适应消除** |
| **Baseline 4: 3步有限时域 POMDP 最优** | 探索直行 (10.0s) | 绕行 (35.0s) | 探针自愈 (13.5s) | **58.5 s** | 0 次 | 自适应消除 |
| **Oracle 参考上界 (上帝真值视界)** | 直行 (10.0s) | 绕行 (35.0s) | 直行 (10.0s) | **55.0 s** | 0 次 | 0 次 |

### 5.6 算例证明了什么，没有证明什么

- **算例客观证明了**：
  1. 贝叶斯后验演化与 VoI 在离散算例中能够自抑探针滥用，并在环境状态自愈时自适应消除陈旧阻断；
  2. 统一物理真值后，简单缓存的短期优势来自偶然的真实参数匹配（侥幸未踩中 broad 失败），而非长效风险控制能力；
  3. 单步 VoI 会因为近视效应而低估物理执行本身的探索价值（与 3 步 POMDP 产生分歧）。
- **算例未证明（且反驳了方法论创新）**：
  1. **未证明新方法机制**：所用公式全部为经典联合贝叶斯推断与 VoI，与已有理论完全重合；
  2. **未证明探针能解决范围混淆**：状态探针只能测环境状态 $z$，根本测不出范围参数 $\theta$；范围混淆的根本解决只能依赖高阶多步规划的主动试探，单步 VoI 对此无能为力；
  3. **未证明向真实物理世界的泛化性**：现实中的动力学与摩擦非平稳无法被 2 状态玩具模型概括。

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

### 7.1 判定结论与适用范围严格限定

依据审定规范，本轮做出明确的审定结论：

> **“当前离散联合信念 + 单步 VoI 方案尚未建立独立的方法创新，因此停止以 SCOPE-VERIFY 新算法推进。”**

```
DECISION: No-Go (当前离散联合信念 + 单步 VoI 方案未建立独立方法创新，停止以 SCOPE-VERIFY 新算法推进)
```

#### 明确的边界限定（不得过度外推）

为防止结论泛化失真，特对本判定做如下四项严格边界限定：
1. **不得扩展为“所有失败约束研究都已经被解决”**：移动机器人在非平稳、部分可观测物理环境中的长周期约束学习、故障诊断与安全恢复，依然是机器人学领域重要的开放课题；
2. **不得扩展为“使用已有概率框架必然没有创新”**：概率推断、POMDP 与信念空间规划是成熟且严密的数学工具，其与现代连续表征、触觉动力学或几何先验的高效融合依然能产生高水平贡献；
3. **不得扩展为“该项目必然不能发表”**；
4. **不得扩展为“更换为系统论文或基准论文定位即可发表”**：刊物的录用取决于论文在对应文种标准下的证据完整性与贡献度，不可断言换个文种即可轻松发表。

---

### 7.2 判定为 No-Go 的具体依据

1. **当前离散机制落入已有理论范畴（Domain Instantiation of Classical Theory）**：
   在第 2 节与第 3 节的形式化推导中证明，一旦把问题收缩为一个可以形式化求解的离散闭环模型，该方案的结构直接落入离散 POMDP / 贝叶斯主动假设检验范畴：
   - 状态转移为离散马尔可夫链；
   - 信念更新为离散贝叶斯公式；
   - 探针调度为 Howard (1966) 单步信息价值（VoI）；
   - 整个流程未提出新的数学算子、损失函数或优化结构。若将其包装为全新学习算法，其方法机制实质上是已有理论的直接应用，难以支撑独立的方法论创新。

2. **前沿代表作已有坚实覆盖**：
   - Chou et al. (CoRL 2020) 提出了不确定约束的闭环执行期信念更新；
   - Noseworthy et al. (RSS 2021) 建立了好奇心驱动的规划可行性主动学习并在真机上验证；
   - Krajnik et al. (IEEE TRO 2017) 建立了非平稳时变环境建模。
   将离散马尔可夫转移、离散约束参数与单步 VoI 结合，属于已有技术的领域实例化组合，缺乏独立的方法学增量。

3. **离线推演暴露的机制局限**：
   在第 5 节离线推演中确认：
   - 状态探针只能观测即时环境状态 $z$，无法直接探测约束范围参数 $\theta$，单步 VoI 无法在当前步解除范围混淆；
   - 方案在特定场景下相比简单缓存的收益，主要来自马尔可夫转移先验与主动探针动作的引入；
   - 单步贪心 VoI 存在近视缺陷，与 3 步有限时域 POMDP 最优策略在跨期探索价值上存在分歧。

4. **拒绝以虚假承诺换取 Conditional Go**：
   若以“后续扩展至高维连续非线性求解”为由给予 Conditional Go，在没有突破性理论工具的前提下，极易滑向依赖人工特调超参数与削弱对比基线的无效试错。

---

### 7.3 明确的止步清单与后续建议

基于上述裁决，下达清晰的执行边界：

1. **明确止步事项（What to Stop）**：
   - 停止以“自愈记忆”、“约束适用范围学习”、“SCOPE-VERIFY 算法”为题撰写理论方法创新类的学术论文；
   - 停止开发试图在连续空间拟合脆弱启发式超平面的无理论保障脚本；
   - 停止在 ROS 2 / Gazebo 中为此具体离散概率模型搭建专门的仿真对比环境；
   - 关闭 `research/core-method-design` 针对该算法的推进通道。

2. **工程与后续方向建议**：
   - `73b0b83` 基准成果中的实验与代码（[`paper/submission_source/`](file:///code/failmem-ros2-agent/paper/submission_source/)）真实记录了 ROS 2 下的执行与恢复表现，应保持该成果的客观性与真实性；
   - 若后续开展研究，应从真实的工程瓶颈出发，避免脱离物理实际凭空构造算法创新诉求。
