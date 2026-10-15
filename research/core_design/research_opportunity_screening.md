# 结论纠错与证据驱动的研究机会筛查报告

**文档性质**：事实纠错、数值程序复核与既有工程证据筛查报告  
**基准成果版本**：`73b0b83a836a128b09aa1137137cf97757183e8d`（代码、数据与论文完全冻结）  
**关联分支**：`research/core-method-design`  
**执行边界**：0 新增机器人算法、0 Gazebo 场景、0 模型训练、0 真实 LLM 调用；纯离线数值核查与现有代码日志审计。

---

## 一、限定 No-Go 的适用范围

本轮将去留判定结论明确界定为：

> **“当前离散联合信念 + 单步 VoI 方案尚未建立独立的方法创新，因此停止以 SCOPE-VERIFY 新算法推进。”**

```
DECISION: No-Go (当前离散联合信念 + 单步 VoI 方案未建立独立方法创新，停止以 SCOPE-VERIFY 新算法推进)
```

### 严禁过度外推的四项边界承诺

为保持科学判断的客观性，本判定**坚决不得扩展**为以下论调：
1. **不得扩展为“所有失败约束研究都已经被解决”**：移动机器人在非平稳物理环境中的长周期约束学习、故障诊断与安全自愈依然是前沿课题；
2. **不得扩展为“使用已有概率框架必然没有创新”**：概率推断、POMDP 与高维物理先验或触觉动力学结合依然能产出高水平学术贡献；
3. **不得扩展为“该项目必然不能发表”**；
4. **不得扩展为“更换为系统论文或基准论文定位即可发表”**：任何论文发表均取决于其在对应文种标准下的证据扎实度与独立贡献，不可给出任何发表保证；
5. **彻底删除无依据绝对化辞令**：全面剔除“必然被一票否决”、“百分之百覆盖”、“终局判定”等非学术情绪化措辞。

---

## 二、文献论证彻底核验与纠正

### 2.1 *Active Learning of Abstract Plan Feasibility* 真实作者与设置纠正

- **真实作者**：Michael Noseworthy, Isaiah Brand, Caris Moses, Sebastian Castro, Leslie Pack Kaelbling, Tomás Lozano-Pérez, Nicholas Roy
- **发表年份与出处**：Robotics: Science and Systems XVII (RSS 2021), DOI: [10.15607/RSS.2021.XVII.043](https://doi.org/10.15607/RSS.2021.XVII.043), 官方页面: [http://www.roboticsproceedings.org/rss17/p043.html](http://www.roboticsproceedings.org/rss17/p043.html).
- **核心机制与实验设置**：针对任务与运动规划中抽象规划可行性判定，提出基于**好奇心驱动的主动探索（Curiosity-driven exploration）**框架主动采样；不仅在 PyBullet 仿真环境中评估，还在**真实的 Franka Emika Panda 7自由度机械臂**上完成了抓取和放置非均匀质量分布积木的物理实验。其主动采样的目标是优化分类器边界，未在移动机器人导航时变代价流中调度物理探针。

### 2.2 Glen Chou 代表作真实贡献与适用范围客观界定

- **文献元数据**：Glen Chou, Dmitry Berenson, Necmiye Ozay, *"Uncertainty-Aware Constraint Learning for Adaptive Safe Motion Planning from Demonstrations"*, in *Proc. CoRL 2020*, PMLR vol. 155, pp. 1612–1639, 2021.
- **证实的事实**：提出了对示教不确定约束维护置信分布（Belief over constraints），并完整建立了**在闭环执行期利用在线传感器观测（触觉、接近觉、自由空间）持续更新约束信念并在线重规划**的机制（Section 6），推翻了“现有约束学习缺失执行中不确定更新”的前提。
- **客观适用范围（不夸大其已完全解决所有问题）**：Chou 等人主要面向**静态环境中的连续几何障碍约束**，并未建模物理潜变量的离散非平稳时变跳变（如地面干湿、摩擦突变），亦未涉及针对特定操作上下文调度带成本的主动诊断探针。

---

## 三、小型离线数值核查结果总结

使用独立数值核验脚本 [`research/core_design/verify_toy_model.py`](file:///code/failmem-ros2-agent/research/core_design/verify_toy_model.py) 与日志 [`research/core_design/toy_model_verification.log`](file:///code/failmem-ros2-agent/research/core_design/toy_model_verification.log) 完成核查：

### 3.1 初始期望成本核算与探针风险纠偏

参数体系：$C_{\text{nom}} = 10.0\,\text{s}$，$C_{\text{detour}} = 35.0\,\text{s}$，$C_{\text{fail}} = 100.0\,\text{s}$，$\tilde{c}(v) = 3.5\,\text{s}$（包含 $0.5\,\text{s}$ 风险惩罚期望），探针误判误差 $\epsilon = 0.05$。  
在初始先验 $b_0 = [0.45, 0.45, 0.05, 0.05]$ 下，若面临首个重载工况 $x_H$：
- $\mathbb{E}[\text{Direct}] = 19.00\,\text{s}$，$\mathbb{E}[\text{Detour}] = 35.00\,\text{s}$，$\mathbb{E}[\text{Probe}] = 17.45\,\text{s}$；
- **探针风险核对**：虽然 $\mathbb{E}[\text{Probe}] = 17.45\,\text{s}$ 最优，但探针具有 $\epsilon = 0.05$ 的非零误判率（$P(o_{\text{dry}} \mid z_{\text{wet}}) = 0.05$）。在地面真实潮湿时仍有 $5\%$ 概率误判为干燥并放行，进而导致物理失败。**删除“绝不会发生失败”“此前失败不可能由此策略产生”等绝对化断言**。
- **首发失败设定**：为构建确定、公平的对比基准，首发失败被设定为**外生的公共历史前提（$\mathcal{H}_0 = \{(x_0=x_H, y_0=\text{fail})\}$）**，作为后续自愈对比的统一初始条件。

### 3.2 转移矩阵乘法方向

转移矩阵 $\mathbf{T}_z$ 定义为列随机矩阵（列和为 1，`T_z.sum(axis=0) == 1.0`），按标准列向量乘法进行前向时变预测：$p_t = \mathbf{T}_z p_{t-1}$，代码中纠正为 `b_pred = T_z @ b_mat`。

### 3.3 物理真值统一与广义成本辨析

- **物理真值一致性**：在物理真值 $(z^* = z_{\text{wet}}, \theta^* = \theta_{\text{narrow}})$ 下，工况 $x_L$ 物理上完全可行，执行耗时为标称 $10.0\,\text{s}$。
- **成本拆分**：
  - 条件缓存（Condition Cache）因工况键不匹配直接放行 $x_L$，在 narrow 物理真值下侥幸成功，事后实现成本为 **$10.0\,\text{s}$**；
  - 单步贝叶斯（Myopic Bayes）因事前失效率估计为 $50\% > 27.8\%$，理性避险绕行，事后实现成本为 **$35.0\,\text{s}$**（事前规避 55s 风险）。
  - 探针成本中的 $3.5\,\text{s}$ 为包含 $1\%$ 停机风险期望惩罚（$3.0 + 0.01 \times 50 = 3.5\,\text{s}$）的**广义成本**；在未显式采样风险事件的单条正常轨迹中，名义实测物理耗时为 $3.0 + 10.0 = \mathbf{13.0\,\text{s}}$，若计入广义成本则为 $\mathbf{13.5\,\text{s}}$。

### 3.4 有限时域 POMDP 求解与分支数值纠偏

通过穷举法求解有限时域 POMDP：
1. **序列 `['x_L', 'x_L', 'x_L']` 分支纠正**：
   - 首次 DIRECT 后：
     - **失败分支（概率 0.50）**：第 0 步耗时 $100.0\,\text{s}$，后验确定 $\theta_{\text{broad}}$，后续 2 步条件期望累计成本为 $67.3\,\text{s}$，**失败分支条件期望累计成本为 $167.3\,\text{s}$**；
     - **成功分支（概率 0.50）**：第 0 步耗时 $10.0\,\text{s}$，后验确定 $\theta_{\text{narrow}}$，后续 2 步通行确定成功（每步 10.0s），**成功分支条件期望累计成本为 $30.0\,\text{s}$**；
     - **总期望累计成本**：$0.50 \times 167.3 + 0.50 \times 30.0 = \mathbf{98.65\,\text{s}}$。
   - **纠偏**：彻底撤回不符合程序的 $170$ 与 $37.3$ 分支解释，严格采用程序输出的 $167.3$ 与 $30.0$。
2. **评测序列 `['x_L', 'x_H', 'x_H']` 决策纠正**：
   - 调用 POMDP 求解器，首步各动作 3 步期望值为：DIRECT 为 $122.3\,\text{s}$，DETOUR 为 $102.3\,\text{s}$，PROBE 为 $105.8\,\text{s}$；
   - **当前程序在 `['x_L', 'x_H', 'x_H']` 序列下首步选择 DETOUR，而非 DIRECT**；
   - **纠偏**：原稿中出现的“Baseline 4 累计耗时 $58.5\,\text{s}$”系将 `['x_L', 'x_L', 'x_L']` 序列的首步决策错误套用所致，现予彻底撤回。在 `['x_L', 'x_H', 'x_H']` 序列下，3 步 POMDP 最优策略的动作序列与 Myopic Bayes 完全相同（DETOUR, DETOUR, PROBE），事后实现成本全同为 $83.5\,\text{s}$（广义成本）/ $83.0\,\text{s}$（名义耗时）。

---

## 四、纠正 Condition O 的真实身份与客观结论收缩

### 4.1 Condition O 的代码与协议真实身份

走查项目源码与评测配置文件：
- [`src/p2c_pipeline.py:281-308`](file:///code/failmem-ros2-agent/src/p2c_pipeline.py#L281-L308)：
  `Condition O` 是项目自行实现的 **`SpatialObservationCache`** 类，用于保存区域级别的 `OCCUPIED` / `FREE` 物理观测历史；
- [`src/p2c_pipeline.py:346-354`](file:///code/failmem-ros2-agent/src/p2c_pipeline.py#L346-L354) 与 [`scripts/run_p2c_experiment.py:334`](file:///code/failmem-ros2-agent/scripts/run_p2c_experiment.py#L334)：
  在决策节点 $J_0$ 处，高层策略查询 `cache.get_latest_state(region_id)`，若为 `OCCUPIED` 则高层策略主动切换派发 Path_B；
- [`configs/p2c_pilot_protocol.yaml:81-83`](file:///code/failmem-ros2-agent/configs/p2c_pilot_protocol.yaml#L81-L83)：
  明确定义 `O` 为 `"spatial_observation_cache"`。

**事实确认**：
**现有 O 与 F 的对比，是项目实现的“区域级空间观测缓存”与“带前置条件和生命周期的失败记忆”之间的策略对比，绝不是“额外失败记忆对比未经扩展的 Nav2 原生代价地图”的实验！**

### 4.2 错误推论的彻底删除与结论严格收缩

基于对 Condition O 真实身份的核实，**彻底删除**此前由误读推导出的以下无依据断言：
- ❌ 删除“原生 Costmap 已经最优”；
- ❌ 删除“二者生命周期 100% 同步”；
- ❌ 删除“所有几何障碍场景都没有失败记忆研究价值”。

同时，对已有 P2c 实验（[`paper/submission_source/tables/tab2_condition_summary.tex`](file:///code/failmem-ros2-agent/paper/submission_source/tables/tab2_condition_summary.tex)）中的数据表现，**将“零增益”“完全等效”“差异完全来自随机扰动”等表述统一收缩为审慎的客观陈述**：

> **“在现有单一测试地图、每条件 $n=3$ 的探索性运行结果中，FailMem（Condition F）未显示出相对于 SpatialObservationCache（Condition O）的额外性能收益；该探索性数据尚未建立两者的统计等效性，亦不能作为一般性结论外推。”**

---

## 五、撤回对“候选困难 2”的推荐与研究机会客观裁定

### 5.1 撤回理由

在上一版讨论中，曾试图将“FailMem 相对 Condition O 路线相同且未见收益”包装为推荐候选困难。现予**正式撤回**：
- “现有 F 与 O 路线相同、未见额外收益”只是**已有评测结果的边界记录**，反映了在当前单一走廊场景下 F 相比 O 没有测出优势的事实；
- 这种“未显示额外收益”本身并不是一个具备待验证方法机制、能够开展反驳验证的核心科学问题。

### 5.2 筛查结论：本轮未筛出满足条件的新候选

按照严谨的立项标准，一个值得投入的候选科学问题必须同时满足以下四项硬性条件：
1. **有具体代码或数据依据**；
2. **强基线存在可验证的不足**；
3. **有明确的待验证方法机制**；
4. **当前资源能够开展公平的最小验证**。

**筛查裁决**：
- 候选 1（H1 动作条件分歧）：实测 4/4 成功，差异未建立（“尚无实证支持”）；
- 候选 2（F vs O 冗余）：属于已有探索性测试的边界，缺乏强基线的可验证缺陷与新机制假设；
- **客观结论：本轮筛查未找到同时满足上述四项条件的新候选。**

### 5.3 严禁脱离证据跳跃至未验证新选题

**坚决不为了延续研究设计而强行虚构新名称**。
同时，**明确禁止直接跳跃至湿滑路面、重载过载、电机温升或高维真机动力学等选题**。这些方向属于完全未经当前软硬件平台与数据检验的全新命题，若要立项，必须从头单独论证传感器配置、物理可观测性、实验可行性以及与文献已有工作的差异，不能作为当前失败记忆项目的包装性延续。

---

## 六、本轮交付物核对

1. **数值核查脚本及运行日志**：
   - 脚本：[`research/core_design/verify_toy_model.py`](file:///code/failmem-ros2-agent/research/core_design/verify_toy_model.py)
   - 运行日志：[`research/core_design/toy_model_verification.log`](file:///code/failmem-ros2-agent/research/core_design/toy_model_verification.log)
2. **修正后的核心设计文档**：
   - 文档：[`research/core_design/core_research_design.md`](file:///code/failmem-ros2-agent/research/core_design/core_research_design.md)
3. **纠错与筛查报告**：
   - 文档：[`research/core_design/research_opportunity_screening.md`](file:///code/failmem-ros2-agent/research/core_design/research_opportunity_screening.md)（本报告）
4. **一页收尾说明**：
   - 文档：[`research/core_design/research_closure_statement.md`](file:///code/failmem-ros2-agent/research/core_design/research_closure_statement.md)（见第四部分）
