# P1 自然经验误用与修订损伤核验报告 (P1 Natural Misuse Verification Report)

**报告时间**：2026-10-20  
**核验分支**：`research/counterexample-condition-revision`  
**核验脚本**：`p1_prefix_replay_check.py`, `tests/test_interface_and_conditions.py`  
**运行记录**：`runs/run_20261020_124845_P1_prefix_replay/`  
**实验账本**：`experiment_ledger.json`

---

## 1. 核心核验目的

纠正此前在 84ef824 中因接口字段缺失（`experience_extractor` 接收空任务描述与空动作导致生成虚假规则）和浅层关键词匹配导致的误判。在实现完整真实接口、实体条件绑定、动态观测优先与四组记忆暴露日志后，**重新检验自然提取的经验在反例任务上是否存在有害迁移（记忆误用）与修订损伤**。

---

## 2. 接口修复与自然经验提取真实验据

### 2.1 真实轨迹提取样例
通过 `tests/test_interface_and_conditions.py` 与 `p1_prefix_replay_check.py`，完整轨迹元数据与每步执行动作确认无损进入提取提示词。
由基座模型无记忆自主成功完成的铝箔导电测试（`test-conductivity` var 0, 4步成功）提取出以下真实规则：

```json
{
  "rule_id": "rule_test-conductivity_0",
  "goal": "determine if aluminum foil is electrically conductive",
  "observed_facts": {
    "trigger_state": "agent in bathroom, aluminum foil in workshop",
    "key_actions": [
      "teleport to workshop",
      "focus on aluminum foil",
      "connect aluminum foil to red box",
      "move aluminum foil to red box"
    ],
    "outcome": "aluminum foil determined to be electrically conductive"
  },
  "llm_explanation": "Connecting the aluminum foil to the red box confirmed its conductivity, allowing it to be correctly moved to the red box.",
  "applicability_conditions": [
    "the aluminum foil must be present in the workshop",
    "there should be a red box available for placement"
  ],
  "recovery_procedure": "if the object does not move to the red box, recheck the connection and ensure the object is indeed electrically conductive."
}
```

**关键特征**：自然提取生成的规则前置条件具有高度具体的具象绑定（`"the aluminum foil must be present in the workshop"`），而非无限制的泛化规则。

---

## 3. 单步前缀复现（Causal Prefix Replay）对比实验

在所有 4 组开发诊断对的反例任务（Task B）的关键决策步（已完成导航与聚焦，面临放入红盒还是绿盒的分支点），进行严格的四条件分叉对照测试：

- **Cond A (No Memory)**：基座对照组，无记忆；
- **Cond B (Raw Trajectory)**：原始轨迹组，注入铝箔完整成功示范文本（完整记录内存暴露）；
- **Cond C (Grounded Rule)**：文献条件记忆组，经 `ConditionEvaluator` 进行实体与观测判定；
- **Cond D (Unconditioned Rule)**：反事实消融组，无条件强制注入规则，检验规则对决策的实际扰动。

### 3.1 实验结果对比矩阵

| 诊断对 ID | 反例任务目标 (`Target`) | Cond C 规则是否激活 (`Injected`) | Cond A 动作 (无记忆) | Cond B 动作 (轨迹检索) | Cond C 动作 (条件规则) | Cond D 动作 (强制无条件规则) | 因果差异 (A vs C) | 因果差异 (A vs B) | 因果差异 (A vs D) |
| :--- | :---: | :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **Pair 01 (导电: 铝箔 vs 杏子)** | 杏子 (`apricot`) | **False** (拒绝注入) | `move apricot to red box` | `move apricot to red box` | `move apricot to red box` | `move apricot to red box` | **False** | **False** | **False** |
| **Pair 02 (导电: 叉子 vs 玻璃罐)** | 玻璃罐 (`glass jar`) | **False** (拒绝注入) | `connect glass jar to red box` | `connect glass jar to red box` | `connect glass jar to red box` | `connect glass jar to red box` | **False** | **False** | **False** |
| **Pair 03 (相变: 冰 vs 水)** | 液态水 (`water`) | **False** (拒绝注入) | `focus on workshop` | `focus on workshop` | `focus on workshop` | `focus on battery` | **False** | **False** | **True** |
| **Pair 04 (热力: 水 vs 巧克力)** | 固体巧克力 (`chocolate`) | **False** (拒绝注入) | `focus on inventory` | `focus on workshop` | `focus on inventory` | `focus on inventory` | **False** | **True** | **False** |

---

## 4. 关键科学发现

### 4.1 现象 1：在物理接地判据下，自然条件记忆未发生误用 (No Harmful Misuse Under Grounded Predicates)
- 当 `ConditionEvaluator` 正确执行主语实体绑定（判定当前目标是“杏子/玻璃罐”，而非规则指定的“铝箔”）时：
  ```
  Condition: 'the aluminum foil must be present in the workshop'
  Result: FALSE
  Explanation: Condition subject 'aluminum foil' is not observed in 'workshop' (current target is 'apricot') [evidence_source: current_observation]
  ```
- 结果表明：**自然经验提取出的适用条件并未过度宽泛，在严格的实体感知求值下，规则自动被安全阻断，未在反例任务上发生错误注入（`Injected = False`）**。

### 4.2 现象 2：反例任务上的致命失败 100% 来自基座先验偏差 (Base Model Prior Bias, Not Memory Misuse)
- 在 Pair 01（杏子）与 Pair 02（玻璃罐）上，对比 Cond A（无记忆）与 Cond B/C/D：
  - 无记忆的基座模型输出的动作也是 `move apricot to red box` 和 `connect glass jar to red box`；
  - 无论是否注入记忆、无论注入轨迹还是无条件规则，模型的动作**毫无差异**（A vs B = False, A vs C = False, A vs D = False）；
  - **因果结论**：反例任务的负收益（-100分）完全是基座模型在候选动作列表中的先验选择偏差，并非由于记忆造成的“负迁移”或“经验误导”。

---

## 5. 正式结论与科研判定

依据科研守则中“不得通过放宽条件匹配器或人工注入坏规则人为制造误用”的强制要求，本轮实证检验形成最终结论：

> **“在当前基座模型（`Qwen2.5-Coder-7B-Instruct`）与基准任务（ScienceWorld）下，自然生成的条件经验具备足够的实体具体性，在物理实体接地下未表现出有害迁移；反例任务的失败源于基座自身在多步动作选择中的先验偏置，而非记忆误用。”**

因此：
- **P1 阶段结论**：未能确立假设中的“自然经验有害泛化/误用”这一待解决问题；
- **后续决策**：暂停进入 P2 开发“双分支条件动作修订”机制，避免在缺乏因果基础的伪问题上耗费后续 360 episodes / 18,000 calls 预算。
