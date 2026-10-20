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

## 3. 同状态单步记忆干预探测（Same-State Single-Step Memory Intervention Probe）

在 4 组开发诊断对的反例任务（Task B）的关键决策步（已完成导航与聚焦，面临放入红盒还是绿盒的分支点），进行四条件分叉干预探测：

- **Condition A (No Memory)**：无记忆基线对照；
- **Condition B (Raw Trajectory Demo)**：完整原始轨迹检索示范基线；
- **Condition C (Condition-Gated Rule)**：经过条件门控的接地经验规则（最接近已有条件化记忆方法）；
- **Condition D (Unconditioned Blind Rule)**：无条件注入经验规则的**诊断对照（压力测试）**，**绝非局部修订方法**。

> **边界说明**：本探测仅测试在固定前缀状态下单步动作输出的敏感性，未推进后续完整环境交互分支，不代表任务最终环境结果层面的因果核验，亦未涉及修订损伤测试。

### 3.1 探测结果对比矩阵

| 诊断对 ID | 反例任务目标 (`Target`) | Cond C 规则是否激活 (`Injected`) | Cond A 动作 (无记忆) | Cond B 动作 (轨迹检索) | Cond C 动作 (条件规则) | Cond D 动作 (强制无条件规则) | 单步动作差异 (A vs C) | 单步动作差异 (A vs B) | 单步动作差异 (A vs D) |
| :--- | :---: | :---: | :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| **Pair 01 (导电: 铝箔 vs 杏子)** | 杏子 (`apricot`) | **False** (拒绝注入) | `move apricot to red box` | `move apricot to red box` | `move apricot to red box` | `move apricot to red box` | **False** | **False** | **False** |
| **Pair 02 (导电: 叉子 vs 玻璃罐)** | 玻璃罐 (`glass jar`) | **False** (拒绝注入) | `connect glass jar to red box` | `connect glass jar to red box` | `connect glass jar to red box` | `connect glass jar to red box` | **False** | **False** | **False** |
| **Pair 03 (相变: 冰 vs 水)** | 液态水 (`water`) | **False** (拒绝注入) | `focus on workshop` | `focus on workshop` | `focus on workshop` | `focus on battery` | **False** | **False** | **True** |
| **Pair 04 (热力: 水 vs 巧克力)** | 固体巧克力 (`chocolate`) | **False** (拒绝注入) | `focus on inventory` | `focus on workshop` | `focus on inventory` | `focus on inventory` | **False** | **True** | **False** |

---

## 4. 关键科学发现与断言修正

### 4.1 现象 1：在物理接地判据下，自然条件记忆未发生误用 (No Harmful Misuse Under Grounded Predicates)
- 当 `ConditionEvaluator` 正确执行主语实体绑定（判定当前目标是“杏子/玻璃罐”，而非规则指定的“铝箔”）时：
  ```
  Condition: 'the aluminum foil must be present in the workshop'
  Result: FALSE
  Explanation: Condition subject 'aluminum foil' is not observed in 'workshop' (current target is 'apricot') [evidence_source: current_observation]
  ```
- 结果表明：**自然经验提取出的适用条件并未过度宽泛，在严格的实体感知求值下，规则自动被安全阻断，未在反例任务上发生错误注入（`Injected = False`）**。

### 4.2 断言修正与因果边界澄清
- **撤回“失败 100% 来自基座先验”的笼统断言**：在单步探测中，虽然 Pair 01 和 Pair 02 的单步动作相同，但这仅反映特定局部状态下的动作倾向，不能推论为所有多步交互失败均完全由基座先验主导。
- **撤回“候选项顺序导致 100% 选择第一项”的推断**：该推论此前缺乏控制候选顺序反转的严格消融实验支持，且在完善候选动作过滤后，基座在多个任务中表现出对有效实体的定向选择能力。
- **明确 Condition D 的诊断性质**：Condition D 强制注入不满足前置条件的规则，目的是检验模型抗干扰性与语义鲁棒性，不得将其作为局部修订方法进行效能评估。

---

## 5. 阶段性结论与向环境后果推进

依据科研守则中“不得通过放宽条件匹配器或人工注入坏规则人为制造误用”的强制要求：
- 在单步探测阶段，未观察到自然提取的接地经验在反例上发生有害误用；
- 为验证长程多步环境后果，必须进一步推进到完整轨迹的分支 rollout（详见 `environmental_consequences_report.md`）。

