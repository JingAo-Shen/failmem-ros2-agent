# 结论纠错与证据驱动的研究机会筛查报告

**文档性质**：结论纠错、离线数值复核与基于既有实验代码/日志的工程瓶颈筛查报告  
**基准成果版本**：`73b0b83a836a128b09aa1137137cf97757183e8d`（代码、数据与论文完全冻结）  
**关联分支**：`research/core-method-design`  
**执行边界**：0 新增机器人算法、0 Gazebo 场景、0 模型训练、0 真实 LLM 调用；纯离线数值核查与现有代码日志审计。

---

## 一、限定 No-Go 的适用范围

本轮根据严格的学术标准与事实依据，将去留判定结论明确界定为：

> **“当前离散联合信念 + 单步 VoI 方案尚未建立独立的方法创新，因此停止以 SCOPE-VERIFY 新算法推进。”**

```
DECISION: No-Go (当前离散联合信念 + 单步 VoI 方案未建立独立方法创新，停止以 SCOPE-VERIFY 新算法推进)
```

### 严禁过度外推的四项边界承诺

为保持科学判断的审慎与客观，本判定**坚决不得扩展**为以下论调：
1. **不得扩展为“所有失败约束研究都已经被解决”**：移动机器人在非平稳物理环境中长周期运行、经历隐蔽退化（摩擦变化、地面打滑、载荷过载）时的约束学习与安全自愈，在机器人学界依然是前沿开放课题；
2. **不得扩展为“使用已有概率框架必然没有创新”**：贝叶斯滤波、POMDP 与信念空间规划属于基础数理工具，其与连续动力学表征、非线性物理先验或触觉感知的有机结合依然能产生高水平学术贡献；
3. **不得扩展为“该项目必然不能发表”**；
4. **不得扩展为“更换为系统论文或基准论文定位即可发表”**：任何期刊或会议的录用均取决于论文在对应文种规范下的证据扎实度与工程见解，不可给出任何无依据的录用承诺。
5. **彻底删除无依据绝对化辞令**：全面剔除“必然被一票否决”、“百分之百覆盖”、“终局判定”等非学术情绪化措辞。

---

## 二、文献论证彻底核验与纠正

### 2.1 *Active Learning of Abstract Plan Feasibility* 真实元数据与设置纠正

前期调研中对该论文的作者与内容存在错配，现经原始文献核实彻底更正：
- **真实作者**：Michael Noseworthy, Isaiah Brand, Caris Moses, Sebastian Castro, Leslie Pack Kaelbling, Tomás Lozano-Pérez, Nicholas Roy
- **发表年份与出处**：Robotics: Science and Systems XVII (RSS 2021), DOI: [10.15607/RSS.2021.XVII.043](https://doi.org/10.15607/RSS.2021.XVII.043), 官方页面: [http://www.roboticsproceedings.org/rss17/p043.html](http://www.roboticsproceedings.org/rss17/p043.html).
- **核心机制与实验设置**：
  - 针对任务与运动规划（TAMP）中高层抽象规划的连续执行可行性判定，提出基于**好奇心驱动的主动探索（Curiosity-driven exploration）**框架主动采样训练数据；
  - 该工作不仅在 PyBullet 仿真环境中进行了测试，还在**真实的 Franka Emika Panda 7自由度机械臂硬件**上完成了抓取和放置非均匀质量分布积木的物理实验；
  - *局限与边界*：其主动采样的目标是优化计算机内部可行性预测器分类边界，未在移动机器人实时导航的时变代价流中调度物理探针。

### 2.2 Glen Chou 代表作真实贡献与适用范围客观界定

精读 Glen Chou, Dmitry Berenson, Necmiye Ozay 的代表作：
- **文献元数据**：Glen Chou, Dmitry Berenson, Necmiye Ozay, *"Uncertainty-Aware Constraint Learning for Adaptive Safe Motion Planning from Demonstrations"*, in *Proc. CoRL 2020*, PMLR vol. 155, pp. 1612–1639, 2021.
- **证实的事实**：
  - 提出了对示教不确定约束维护置信分布（Belief over constraints）；
  - 完整建立了**在闭环执行期利用在线传感器观测（触觉、接近觉、自由空间）持续更新约束信念并在线重规划**的机制（Section 6）；
  - 并在 7 自由度臂仿真与 12 自由度四旋翼上完成了高达 30 维约束的学习与避障验证。
- **客观适用范围（不夸大其已完全解决所有问题）**：
  - Chou 等人主要针对**静态环境中的连续几何障碍约束**；
  - 该工作**并未建模物理环境潜变量的离散非平稳跳变（如地面干湿、摩擦突变），亦未涉及针对特定操作上下文调度带成本的主动诊断探针**。
  - 因此：Chou 确立了“执行期更新约束信念”已有成熟基石，推翻了“现有约束学习缺失执行中不确定更新”的前提；但并不代表其已覆盖所有动态非平稳失败约束场景。

---

## 三、小型离线数值核查结果总结

针对前期方案中的模型与算例，本轮实现了独立的离线数值核查脚本 [`research/core_design/verify_toy_model.py`](file:///code/failmem-ros2-agent/research/core_design/verify_toy_model.py)，运行日志完整保存在 [`research/core_design/toy_model_verification.log`](file:///code/failmem-ros2-agent/research/core_design/toy_model_verification.log)。核心核查结论如下：

### 3.1 初始先验下的单步期望成本核算与叙事纠正

参数体系：$C_{\text{nom}} = 10.0\,\text{s}$，$C_{\text{detour}} = 35.0\,\text{s}$，$C_{\text{fail}} = 100.0\,\text{s}$，$\tilde{c}(v) = 3.5\,\text{s}$，误差 $\epsilon = 0.05$。  
在初始先验 $b_0 = [0.45, 0.45, 0.05, 0.05]$ 下，若面临首个重载工况 $x_H$：
- **直接执行期望成本**：$\mathbb{E}[\text{Direct}] = 0.90 \times 10 + 0.10 \times 100 = \mathbf{19.00\,\text{s}}$；
- **直接绕行期望成本**：$\mathbb{E}[\text{Detour}] = \mathbf{35.00\,\text{s}}$；
- **探针核验期望成本**：
  - $P(o_{\text{dry}}) = 0.860$，测得干燥后直行期望耗时 $10.523\,\text{s}$；
  - $P(o_{\text{wet}}) = 0.140$，测得潮湿后理性绕行耗时 $35.00\,\text{s}$；
  - $\mathbb{E}[\text{Probe}] = 3.5 + 0.860 \times 10.523 + 0.140 \times 35.00 = \mathbf{17.45\,\text{s}}$。
- **叙事错配纠偏**：
  因 $\mathbb{E}[\text{Probe}] = 17.45\,\text{s} < \mathbb{E}[\text{Direct}] = 19.00\,\text{s} < \mathbb{E}[\text{Detour}] = 35.00\,\text{s}$，智能体在第 1 步的理性决策是**调用探针（Probe）**并安全绕行，**绝不会盲目直行导致 100s 碰撞**！
  原案中“智能体先盲目直行碰撞失败”的叙事被纠正为：**首发失败是外生的公共历史事件（$\mathcal{H}_0 = \{(x_0=x_H, y_0=\text{fail})\}$），作为所有方案评测的统一初始条件，而非当前策略的内生产物**。

### 3.2 转移矩阵乘法方向纠偏

转移矩阵定义为列随机矩阵（列和为 1）：
$$\mathbf{T}_z = \begin{bmatrix} 1 - \lambda_{\text{wet}} & \lambda_{\text{dry}} \\ \lambda_{\text{wet}} & 1 - \lambda_{\text{dry}} \end{bmatrix} = \begin{bmatrix} 0.95 & 0.20 \\ 0.05 & 0.80 \end{bmatrix}$$
在标准列向量约定下，时间预测转移为：
$$p_t = \mathbf{T}_z p_{t-1}, \quad b_{\text{pred}} = \mathbf{T}_z @ b_{\text{mat}}$$
纠正了此前误用转置矩阵 `T_z.T` 破坏列和概率守恒的问题。数值核查确认 `T_z.sum(axis=0)` 严格恒等于 1.0。

### 3.3 物理真值统一与成本严格拆分

在场景 1 中，物理真值设定为 $(z^* = z_{\text{wet}}, \theta^* = \theta_{\text{narrow}})$：
- **物理真值一致性**：在 $\theta_{\text{narrow}}$ 下，工况 $x_L$ 物理上是可行的（耗时 $10\,\text{s}$）。任何策略只要在物理世界执行 $x_L$，结果必定是成功，不可在不同方案下赋予相反的物理执行真值；
- **事前期望成本 vs 事后实现成本严格区分**：
  - *工况条件缓存（Condition Cache）*：仅记录了 $(e, x_H)$ 失败，遇到 $x_L$ 放行直行。在物理世界中侥幸通行成功，事后实现成本为 **$10.0\,\text{s}$**；
  - *单步联合贝叶斯（Myopic Bayes）*：事前失效率估计为 $50\% > 27.8\%$，直接执行期望成本为 $55.0\,\text{s} > 35.0\,\text{s}$，理性选择避险绕行，事后实现成本为 **$35.0\,\text{s}$**。
  - *结论*：不能因为条件缓存撞上 narrow 真值获得 10s，就将单步贝叶斯的理性避险判定为“劣势”，更不能捏造条件缓存在物理世界发生 100s 碰撞。

### 3.4 单步近视 VoI 与 3 步有限时域 POMDP 最优策略的分歧

通过枚举法对 3 步全树 POMDP 进行了精确求解：
- 在任务序列 `['x_L', 'x_L', 'x_L']`、初始信念为 $b_1$（对 $\theta$ 50/50 最大熵）下：
  - **单步贪心 VoI（第 0 步）**：$\mathbb{E}[\text{Direct}] = 55.0\,\text{s} > \mathbb{E}[\text{Detour}] = 35.0\,\text{s}$，**选择 DETOUR**（单步视角畏惧 55s 风险）；
  - **3 步 POMDP 最优（第 0 步）**：
    - 若选 DETOUR，3 步总期望成本为 $99.20\,\text{s}$；
    - 若选 DIRECT，以 50% 概率失败（总计 170s），以 50% 概率成功（总计 37.3s），3 步全期望成本为 **$98.65\,\text{s}$**；
    - **多步最优选择 DIRECT！**
- **机制机理**：物理执行本身具有**对偶控制（Dual Control）与主动信息获取价值**——直接执行 $x_L$ 虽有单步风险，但能够一劳永逸解除 $\theta$ 的不确定性，在后续步骤中释放巨大的通行收益。单步贪心 VoI 存在结构性近视，完全忽略了跨期信息价值。

---

## 四、真实、可测量的工程困难筛查

基于现有的 ROS 2 代码实现（[`src/failure_memory.py`](file:///code/failmem-ros2-agent/src/failure_memory.py)、[`src/doorway_evaluator.py`](file:///code/failmem-ros2-agent/src/doorway_evaluator.py)）以及已冻结的实验数据（P2c 30 次运行评测日志、H1 4 次可行性实机测试），在**输入相同时**排查实际存在的不可忽视性能瓶颈：

### 候选困难 1：动作条件失败假设在标准 Nav2 局部规划器中未产生可执行性分歧（H1 场景未建立）
- **现象描述**：
  设计意图是构建两个动作配置：对齐中心通行的 $a_{\text{aligned}}$ (`[1.50, 1.20, 0.0]`) 与贴近门框膨胀层边缘的斜向通行 $a_{\text{oblique}}$ (`[0.50, 0.88, 0.0]`)，以期在无物理障碍物的门框处构造由于膨胀代价导致 $a_{\text{oblique}}$ 失败、而 $a_{\text{aligned}}$ 成功的分歧。
- **实测日志证据**：
  - 文档：[`reports/P2d-h1-feasibility-check.md`](file:///code/failmem-ros2-agent/reports/P2d-h1-feasibility-check.md)
  - 数据：[`reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json`](file:///code/failmem-ros2-agent/reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json)
  - 4 次测试中，Nav2 Action Server 全部返回 `SUCCEEDED`（4/4，100%），`act_oblique` 未触发任何控制器中止（ABORTED）或超时取消。
- **状态与评估**：
  该候选困难在现有测试中**尚未建立实证支持**（"本次候选场景未建立预期的动作可执行性差异"），属于假设未被激发的探索性场景，因此不予推荐作为核心攻坚瓶颈。

---

### 候选困难 2（明确推荐）：情景式失败符号记忆（Condition F）与 Nav2 分层代价地图光线清除机制（Condition O）在几何障碍上的功能高度重叠与零增益冗余

#### 1. 核心矛盾陈述
在 P2c 的 30 次 Gazebo 真实导航评测中，项目构建了显式维护 `FailureMemoryEntry` 符号记忆条目、三值状态机演化和在线核验器的 FailMem 方案（Condition F）。然而，与其作为基线的 Condition O（仅使用 ROS 2 Nav2 原生代价地图自带的局部障碍物与光线清除缓存 Spatial Costmap Obstacle Cache）相比，**在相同任务与感知输入下，两者的导航路径决策与总体耗时完全重叠，FailMem 展现出 0.0% 的可测量性能增益**。

#### 2. 定量数据与日志证据
查阅已冻结的基准成果数据：
- 汇总表格：[`paper/submission_source/tables/tab2_condition_summary.tex`](file:///code/failmem-ros2-agent/paper/submission_source/tables/tab2_condition_summary.tex)
- 原始日志目录：[`reports/evidence/p2c_pilot/`](file:///code/failmem-ros2-agent/reports/evidence/p2c_pilot/) (30 运行，每条件 $n=3$)

| 评测场景 | 方法条件 | 实际路线 | 死胡同率 (Dead-Ends) | 决策距离 (m) | 决策时间 (s) | 总路程 (m) | 总耗时 (s) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0 (名义无障碍)** | Condition O (代价地图缓存) | Path_A | $0.0 \pm 0.0$ | $6.20 \pm 0.01$ | $50.0 \pm 0.8$ | $6.20 \pm 0.01$ | $50.0 \pm 0.8$ |
| | **Condition F (FailMem 记忆)** | Path_A | $0.0 \pm 0.0$ | $6.20 \pm 0.03$ | $49.9 \pm 0.5$ | $6.20 \pm 0.03$ | $49.9 \pm 0.5$ |
| **D1 (静态障碍阻塞)** | Condition O (代价地图缓存) | Path_B | $0.0 \pm 0.0$ | $7.55 \pm 0.05$ | $50.0 \pm 2.0$ | $13.95 \pm 0.07$ | $108.7 \pm 2.7$ |
| | **Condition F (FailMem 记忆)** | Path_B | $0.0 \pm 0.0$ | $7.54 \pm 0.00$ | $48.2 \pm 1.0$ | $14.03 \pm 0.25$ | $109.5 \pm 1.6$ |
| **D2 (障碍移除自愈)** | Condition O (代价地图缓存) | Path_A | $0.0 \pm 0.0$ | $5.94 \pm 0.07$ | $52.0 \pm 1.7$ | $16.40 \pm 0.24$ | $149.8 \pm 0.6$ |
| | **Condition F (FailMem 记忆)** | Path_A | $0.0 \pm 0.0$ | $5.89 \pm 0.02$ | $51.1 \pm 1.0$ | $16.25 \pm 0.10$ | $151.1 \pm 7.8$ |
| | Condition M1 (永久静态记忆) | Path_B | $0.0 \pm 0.0$ | $7.89 \pm 0.02$ | $51.3 \pm 2.0$ | $18.25 \pm 0.09$ | $148.8 \pm 2.4$ |

**数据解读**：
- 在 D0 中，O 与 F 耗时完全相同（$50.0\,\text{s}$ vs $49.9\,\text{s}$）；
- 在 D1 中，O 与 F 均避开死胡同走 Path_B，总耗时相差仅 $0.8\,\text{s}$（$108.7\,\text{s}$ vs $109.5\,\text{s}$）；
- 在 D2 中，O 与 F 均通过感知确认自愈并安全通行 Path_A，总耗时相差仅 $1.3\,\text{s}$（$149.8\,\text{s}$ vs $151.1\,\text{s}$）；
- 相对增益比：$\Delta \text{Cost} = (J_O - J_F) / J_O$ 分别为 $-0.7\%$ 与 $-0.8\%$，完全处于仿真随机扰动范围内。Condition F 未能带来任何超越 Condition O 的性能增益。

#### 3. 对应代码定位与深层根因分析
通过走查源代码，定位该冗余的根本机制：
- **记忆触发条件**（[`src/failure_memory.py:41-57`](file:///code/failmem-ros2-agent/src/failure_memory.py#L41-L57)）：
  ```python
  def is_failure_eligible_for_doorway_memory(failure_reason, perception_evidence):
      if not perception_evidence or not isinstance(perception_evidence, dict):
          return False
      doorway_state = perception_evidence.get("doorway_state")
      if doorway_state != "OCCUPIED":
          return False
      return True
  ```
- **感知状态判定**（[`src/doorway_evaluator.py:306-312`](file:///code/failmem-ros2-agent/src/doorway_evaluator.py#L306-L312) 与 [`src/doorway_evaluator.py:397-400`](file:///code/failmem-ros2-agent/src/doorway_evaluator.py#L397-L400)）：
  `doorway_state` 被判定为 `OCCUPIED` 的充分必要条件，是激光雷达光线打在门口区域内的几何障碍物上（`hits_inside >= min_obstacle_hits`）或代价地图局部网格被标记为致死（`opening_lethal_cnt > 0`）。
- **调度阻断逻辑**（[`src/failure_memory.py:165-181`](file:///code/failmem-ros2-agent/src/failure_memory.py#L165-L181)）：
  当记忆处于 `ACTIVE` 时，抑制对目标区域的派发。
- **深层机制重叠**：
  1. 激光雷达扫描到几何障碍物时，Nav2 的 Costmap 障碍层（Obstacle Layer）已经将该网格标记为占据，代价地图膨胀层（Inflation Layer）已在该处形成不可通行的高代价屏障。Nav2 的全局规划器（NavFnPlanner）在这一瞬间就已经能够自主规划出绕行路线 Path_B（这正是 Condition O 能够达到的效果）；
  2. 障碍物被移除后，激光雷达的光线穿透门框射向远端，`doorway_evaluator.py` 判定 `doorway_state == 'FREE'` 并将记忆置为 `INVALIDATED`；与此完全同步的是，Nav2 的射线追踪清除机制（Raytrace clearing）在接收到同一帧激光雷达后，也瞬间将代价地图网格的障碍标记抹除，允许全局规划器再次规划 Path_A；
  3. **结论**：**在现有的 2D 激光雷达几何障碍物体系下，FailMem 所维护的符号状态机与 ROS 2 原生代价地图在物理生命周期上是 100% 同步且重叠的**。额外维护符号字典没有产生任何独立的物理决策能力。

#### 4. 困难的度量指标、复现条件与停止条件
- **度量指标**：
  1. *决策分歧率（Decision Divergence Rate, DDR）*：在相同环境与感知输入下，FailMem 决策输出与 Costmap 全局规划路线的分歧比率。目前为 $0.0\%$；
  2. *相对任务耗时增益（Relative Task Efficiency Gain, RTEG）*：$\Delta J = (J_O - J_F) / J_O$。目前在所有测试场景中均 $< 1.0\%$。
- **复现条件**：
  加载已冻结的仿真环境 `configs/p2c_dualpath_world.model` 与测试协议 `configs/p2c_pilot_protocol.yaml`，分别在 Condition O 与 Condition F 下运行评测流水线。
- **停止条件**：
  **若在所有仅包含纯 2D 激光雷达几何可测障碍的场景中，FailMem 相比 ROS 2 原生 Costmap 无法测出超过 $5.0\%$ 的统计显著正向增益，则永久停止在纯几何障碍层面上研发符号式失败记忆。**

---

## 五、三重边界的严格区分

为确保科研结论的严谨性，必须在逻辑上严格割席以下三个不同层面的命题：

```
[命题 1: 算法机制层面]
"当前离散联合信念 + 单步 VoI 方案没有新机制"
  - 核心依据: 该方案形式化后完全落入经典离散 POMDP 与 Bayes VoI 范畴, 是已有决策论的领域实例化,
    缺乏独立的数学或算法方法论创新。
  - 判定操作: 坚决停止以 SCOPE-VERIFY 新算法为题推进。

[命题 2: 既有数据支撑层面]
"现有实验数据不足以支撑新方向"
  - 核心依据: 既有 30 次 P2c 与 4 次 H1 数据完全局限于 2D 激光雷达可直接观测的几何障碍;
    在几何障碍上, Costmap 原生光线清除机制已经做到最优, 符号记忆与代价地图 100% 重叠;
    现有数据根本没有包含地面打滑、载荷过载、电机温升等非几何/部分可观测故障数据,
    无法支撑验证任何超越代价地图的容错学习。

[命题 3: 领域研究机会层面]
"整个长周期机器人容错约束领域并非没有研究机会"
  - 核心依据: 当故障是由不可见物理潜变量(摩擦系数、倾覆力矩、路面黏度)与特定工况(高速、重载)
    耦合引起时, 2D 激光代价地图完全失灵; 此时如何通过极具成本约束的主动核验从偶发失败中
    提取适用范围与时变寿命, 依然具备极高的科学研究价值。
  - 启示: 后续研究若要成立, 必须彻底脱离 2D 几何障碍玩具场景, 切入真机非几何物理退化与动力学约束。
```

---

## 六、交付物清单核验

1. **数值核查脚本及其运行输出**：
   - 脚本：[`research/core_design/verify_toy_model.py`](file:///code/failmem-ros2-agent/research/core_design/verify_toy_model.py)（单步期望成本、列和守恒、3步 POMDP 枚举、统一真值与事后实现成本）
   - 日志：[`research/core_design/toy_model_verification.log`](file:///code/failmem-ros2-agent/research/core_design/toy_model_verification.log)
2. **修正后的核心设计文档**：
   - 文档：[`research/core_design/core_research_design.md`](file:///code/failmem-ros2-agent/research/core_design/core_research_design.md)（限定 No-Go 范围、修正 Noseworthy 与 Chou 引用、纠正算例与叙事）
3. **证据驱动的筛选报告**：
   - 文档：[`research/core_design/research_opportunity_screening.md`](file:///code/failmem-ros2-agent/research/core_design/research_opportunity_screening.md)（本报告）
