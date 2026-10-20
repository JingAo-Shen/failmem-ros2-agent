# 基座模型能力与步数预算标定简报 (Base Planner Capability Calibration Brief)

**标定对象**：`Qwen2.5-Coder-7B-Instruct` (bfloat16, RTX 2080 Ti 单卡, `temperature=0.0`)  
**标定环境**：`ScienceWorld v1.2.3` (Java 11, 原生配置 `simplificationStr="teleportAction,openDoors"`)  
**实验类型**：无记忆基准对照实验（No-Memory Control, Group A）  
**关联文件**：`calibrate_base_planner.py`, `runs/base_planner_calibration_results.json`

---

## 1. 标定目标

在引入记忆与条件修订机制前，通过确定性基线实验明确基座规划器的基础能力特征与边界，回答以下三个关键科学问题：
1. **步数上限敏感性**：15 步的交互上限是否过紧，从而导致由于步数截断引起的“伪失败”？
2. **基础动作执行力**：在给定候选动作空间时，模型能否在无记忆辅助下自主完成标准具身任务？
3. **反例任务失败归因**：在反例任务（Task B，如杏子、玻璃罐、液态水）上的失败，究竟是模型“完全不会做 / 先验偏差”，还是“被记忆误导而做错”？

---

## 2. 标定实验数据与记录

共测试 6 个典型任务配置（覆盖导电测试、相变熔化、沸腾加热）：

| 序号 | 任务名称 (`task_name`) | 变体 (`var`) | 目标实体 (`target`) | 步数上限 (`limit`) | 实际步数 | 最终得分 (`score`) | 终止原因 (`term_reason`) | 最终执行动作与关键观测 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **C1** | `test-conductivity` | 0 | 铝箔 (`aluminum foil`) | 10 | 4 | **100.0** | `success` | `move aluminum foil to red box` (成功断开电路放入红盒，完成导电判定) |
| **C2** | `test-conductivity` | 80 | 杏子 (`apricot`) | 10 | 3 | **-100.0** | `fatal_penalty` | `move apricot to red box` (未检测导电性，直接误放入红盒触发致命惩罚) |
| **C3** | `melt` | 4 | 冰 (`ice`) | 10 | 2 | **-100.0** | `fatal_penalty` | `focus on kitchen` (对房间进行非法 focus 动作，触发致命惩罚) |
| **C4** | `melt` | 4 | 冰 (`ice`) | 15 | 2 | **-100.0** | `fatal_penalty` | `focus on kitchen` (同上，第 2 步即终止) |
| **C5** | `melt` | 4 | 冰 (`ice`) | 20 | 2 | **-100.0** | `fatal_penalty` | `focus on kitchen` (同上，第 2 步即终止) |
| **C6** | `boil` | 2 | 水 (`water`) | 15 | 3 | **-100.0** | `fatal_penalty` | `focus on stove` (对炉灶进行非法 focus 动作，触发致命惩罚) |

---

## 3. 核心发现与归因分析

### 3.1 排除“步数上限过紧导致伪失败”假说
- 在 `melt` 任务上，对比 10 步、15 步与 20 步上限：
  - 3 次运行均在 **第 2 步** 触发非法的环境约束罚分（`focus on kitchen`），程序立即终止；
- 在 `test-conductivity` 成功案例（C1）中，模型仅需 **4 步** 即完成全流程；
- **结论**：当前任务的失败与 15 步交互上限完全无关，不存在由于交互预算不足导致的步数截断伪失败。

### 3.2 基座模型的基础执行能力边界
- **具备的能力**：在目标清晰且流程线性的简单任务（如铝箔导电测试）中，模型具备完美的导航、聚焦、电路连接与容器放置能力，4 步达成 100 分。
- **存在的硬伤**：
  1. **实体与环境聚焦混淆**：在复杂场景下，模型倾向于将导航目标当成聚焦目标（如在需要去厨房时执行 `focus on kitchen`，或在需要用炉灶时执行 `focus on stove`），而 ScienceWorld 要求必须聚焦在特定任务物体上（如 `focus on ice`），非法聚焦直接引发致命终止。
  2. **候选动作排序先验偏差**：当环境提供多个等价候选项时（如 `move apricot to red box` 与 `move apricot to green box`），由于提示词中 `red box` 排序靠前或语义常见度更高，基座在不具备实体物理性质确切先验时，**100% 盲目选择第一个候选项**。

### 3.3 反例任务失败的真实归因（区分“先验错误”与“记忆误导”）
- **关键事实**：在 C2 实验中，Agent 处于 **绝对无记忆（Zero-Memory, Control Group A）** 状态，没有任何旧规则或历史轨迹输入。
- **观察到的行为**：基座模型在第 3 步自主输出了：
  > *Thought: "The apricot is located around the workshop. I need to move it to either the red or green box based on its electrical conductivity."*  
  > *Action: "move apricot to red box"*
- **决定性归因结论**：
  在既往探索性实验中，反例物体（如杏子、玻璃罐）被放入红盒子，**完全由基座模型自身的先验偏置导致，与跨任务记忆的注入毫无因果关系**。任何将该错误归咎于“失败经验未有效修订”的推论均属于归因混淆。
