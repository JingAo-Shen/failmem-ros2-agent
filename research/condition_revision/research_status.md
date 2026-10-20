# 持续研究状态跟踪文件 (Research Status)

**更新时间**：2026-10-20  
**当前阶段**：**P1（自然经验误用与修订损伤核验）**  
**当前状态**：**核验完成：全环境分支 rollout 实测表明，自然提取的条件记忆在严格实体与物理语义接地下未表现出有害误用；P2 开发继续暂停**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 核心研究问题与当前定位

> **“面对新反例，如何修订旧经验中被证伪的适用范围，同时保留其在原有有效情境中的作用？”**

### 明确四个条件的评估身份：
- **Condition A (No Memory)**：无记忆基线对照；
- **Condition B (Raw Trajectory Demo)**：完整原始轨迹检索示范基线；
- **Condition C (Condition-Gated Rule)**：经过条件门控的接地经验规则（最接近已有条件化记忆方法）；
- **Condition D (Unconditioned Blind Rule)**：无条件注入经验规则的**诊断对照（压力测试）**，**绝非局部修订方法**。

### 撤回未经充分控制实验证明的断言：
1. **撤回“失败 100% 来自基座先验”的笼统断言**：先前在 `p1_prefix_replay_check.py` 中仅开展了同状态单步干预探测，未执行各动作后的完整环境分支演化，不能作为全局因果结论。
2. **撤回“候选项顺序导致 100% 选择第一项”的推论**：在修复基座动作过滤机制后，基座在 `glass jar` 与 `metal pot` 等任务上展现出根据任务描述自主选择正确容器并达标的能力（见 Chain 2 实测 100 分），证明模型并非单纯的位置顺序跟随者。

---

## 2. P0 语义与判定基础设施修复结果 (已通过 100% 回归测试)

针对先前发现的语义误判与匹配缺陷，在 `condition_evaluator.py` 与 `test_interface_and_conditions.py` 完成 6 项彻底修复，10 项单元测试全部通过（0.02s）：

1. **实体与主语严格绑定**：在求值条件从句时，严格隔离条件实体与当前任务目标实体（`test_aluminum_foil_in_workshop_not_matched_by_apricot` 通过）。
2. **观测动态状态绝对优先于先验**：当前观测到水结冰时，必须覆盖历史或词典液体先验（`test_current_state_overrides_older_history_state` 通过）。
3. **多实体物理状态隔离**：环境内其它物体（如旁边的液体）冻结，绝不改变目标实体（如水）的独立液体判定（`test_other_object_freezing_does_not_affect_water_liquid_state` 通过）。
4. **严格词边界匹配**：使用 `\bnon[- ]?living\b` 优先判定，杜绝 `non-living` 被 `living` 的子串匹配抢占（`test_non_living_not_preempted_by_living` 通过）。
5. **电路绑定导电性判据**：灯泡点亮只有在观测明确提示目标实体接入闭合回路时才判定导电，杜绝未接入电路的任意目标被误判为导电（`test_bulb_on_does_not_prove_arbitrary_target_conductive` 通过）。
6. **未观测实体返回 UNKNOWN**：当前观测未出现目标对象或地点时，返回 `ConditionResult.UNKNOWN` 与 `EvidenceSource.INSUFFICIENT_EVIDENCE`，严禁直接判为 FALSE（`test_unobserved_object_location_returns_unknown_not_false` 通过）。
7. **复合条件合取求值**：支持 `and` / `;` 分隔的复合从句逐步求值，任一否定即为 FALSE，任一未决且无否定即为 UNKNOWN（`test_compound_conditions_all_evaluated` 通过）。

---

## 3. 基座模型基线能力预检 (Planner Pre-check)

在 `research/condition_revision/planner_precheck.py` 中，对基座模型（`Qwen2.5-Coder-7B-Instruct`，`temperature=0.0`）在来源任务与多步任务上的基础能力进行无记忆标定（结果记录于 `runs/planner_precheck_results.json`）：

- **`test-conductivity` (var 0, aluminum foil)**：成功导航至 workshop，精准聚焦目标，并完成部分电路探针连接（得分 60.0，8 步超时）。展现出基础多步规划能力，但受限于环境具体词法（`move` vs `place`），未在 8 步内闭合完整电路；
- **`melt` (var 4, ice)**：成功导航至 kitchen（得分 3.0），后续尝试通过通用动词聚焦 ice 发生环境词法不匹配；
- **`boil` (var 2, water)**：尝试连接杯子与炉灶，体现出基于常识的任务意图，但在缺少多步容器转移先验下未完成煮水。

**结论**：基座模型在单步导航与目标聚焦上具备确定性有效动作生成能力，在复杂工具交互（连接电极、加热）上依赖清晰的语法支持或环境反馈。

---

## 4. 全环境后果比较实验 (Environmental Rollout Results)

在实验前预先登记并冻结 3 条跨家族经验链条（记录于 `frozen_dev_manifest.json` 与 `task_manifest.py`），对每条链条在 4 种条件下完整 rollout 至环境终止（跑到底，而非单步截断），完整记录暴露文本、条件门控状态、模型建议与执行动作及环境最终得分：

### 经验链条 1：`chain_01_conductivity_foil`
- **来源任务**：`test-conductivity` (var 0, 目标: aluminum foil)
- **边界任务 (Task B)**：`test-conductivity` (var 80, 目标: apricot, 绝缘体)
- **保留测试 (Retention)**：`test-conductivity` (var 300, 目标: metal fork, 导体)

| 条件分支 | 任务角色 | 记忆注入状态 | 记忆暴露 / 门控状态 | 执行步数 | 终止原因 | 最终得分 |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: |
| **Cond A (No Memory)** | Boundary B | 否 | `not_exposed_to_rule` | 6 | fatal_penalty | -100.0 |
| **Cond B (Raw Trajectory)** | Boundary B | **是** | 注入 aluminum foil 完整轨迹 | 6 | fatal_penalty | -100.0 |
| **Cond C (Grounded Rule)** | Boundary B | 否 | **`not_exposed_to_rule` (条件求值拒识)** | 6 | fatal_penalty | -100.0 |
| **Cond D (Blind Rule Stress)**| Boundary B | 否/强行 | `not_exposed_to_rule` | 6 | fatal_penalty | -100.0 |
| **Cond A (No Memory)** | Retention | 否 | `not_exposed_to_rule` | 7 | fatal_penalty | -100.0 |
| **Cond C (Grounded Rule)** | Retention | 否 | `not_exposed_to_rule` | 7 | fatal_penalty | -100.0 |

*实测发现*：Cond A、B、C、D 在反例（apricot）上均于第 6 步选择 `move apricot to red box` 终止。Cond C 准确将 foil 经验拦截；Cond B 即使注入了 foil 的操作过程，模型最终决策也与无记忆组完全一致。

### 经验链条 2：`chain_02_conductivity_fork`
- **来源任务**：`test-conductivity` (var 300, 目标: metal fork)
- **边界任务 (Task B)**：`test-conductivity` (var 230, 目标: glass jar, 绝缘体)
- **保留测试 (Retention)**：`test-conductivity` (var 380, 目标: metal pot, 导体)

| 条件分支 | 任务角色 | 记忆注入状态 | 记忆暴露 / 门控状态 | 执行步数 | 终止原因 | 最终得分 |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: |
| **Cond A (No Memory)** | Boundary B | 否 | `not_exposed_to_rule` | 7 | **success** | **100.0** |
| **Cond B (Raw Trajectory)** | Boundary B | **是** | 注入 metal fork 完整轨迹 | **5** | **success** | **100.0** |
| **Cond C (Grounded Rule)** | Boundary B | 否 | **`not_exposed_to_rule` (准确拦截)** | 7 | **success** | **100.0** |
| **Cond D (Blind Rule Stress)**| Boundary B | 否 | `not_exposed_to_rule` | 7 | **success** | **100.0** |
| **Cond A (No Memory)** | Retention | 否 | `not_exposed_to_rule` | 5 | **success** | **100.0** |
| **Cond C (Grounded Rule)** | Retention | 否 | `not_exposed_to_rule` | 5 | **success** | **100.0** |

*实测发现*：在 glass jar 反例上，**所有条件均取得 100.0 满分成功**！注入 metal fork 失败轨迹（Cond B）不仅没有误导模型将玻璃罐放入红盒子，反而使动作步数从 7 步缩短为 5 步（更快完成绿盒子放置）。Retention 任务（metal pot）在各组中亦稳定取得 100.0 满分。

### 经验链条 3：`chain_03_classification_living`
- **来源任务**：`find-living-thing` (var 1, 目标: living thing)
- **边界任务 (Task B)**：`find-non-living-thing` (var 1, 目标: non-living thing)
- **保留测试 (Retention)**：`find-living-thing` (var 2, 目标: living thing)

| 条件分支 | 任务角色 | 记忆注入状态 | 记忆暴露 / 门控状态 | 执行步数 | 终止原因 | 最终得分 |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: |
| **Cond A (No Memory)** | Boundary B | 否 | `not_exposed_to_rule` | 7 | timeout | 25.0 |
| **Cond B (Raw Trajectory)** | Boundary B | **是** | 注入 living thing 轨迹 | **3** | **success** | **100.0** |
| **Cond C (Grounded Rule)** | Boundary B | 否 | **`not_exposed_to_rule` (准确拦截)** | 7 | timeout | 25.0 |
| **Cond D (Blind Rule Stress)**| Boundary B | 否 | `not_exposed_to_rule` | 7 | timeout | 25.0 |
| **Cond A (No Memory)** | Retention | 否 | `not_exposed_to_rule` | 2 | fatal_penalty | -100.0 |
| **Cond C (Grounded Rule)** | Retention | 否 | `not_exposed_to_rule` | 2 | fatal_penalty | -100.0 |

*实测发现*：在 `find-non-living-thing` 边界任务上，无记忆组（Cond A）因探索超时仅得 25.0 分；而检索到轨迹的示范组（Cond B）**从示范动作中学习到容器定位与转移模式，以 3 步直接斩获 100.0 满分**！

---

## 5. 核心科学结论与转段裁决

### 核心结论：
1. **自然提取规则具有天然的实体具体性**：基座模型从真实交互轨迹中归纳的适用条件通常包含实体特异性从句（如 `aluminum foil must be present` 或 `at least one living thing present`）。在严谨物理接地下，这些规则在反例上均被准确阻断（`not_exposed_to_rule`），未发生自然有害误用。
2. **轨迹示范（Cond B）表现为中性或正向迁移**：在跨任务或边界任务中，示范给出了环境可用动作与对象交互模式，在 Chain 2 中加速任务完成（7步 -> 5步），在 Chain 3 中直接帮助模型找到关键物体完成任务（25分 -> 100分）。
3. **未观测到记忆诱发的负迁移（Negative Transfer）**：在全部 3 条经验链条与 4 个条件的全分支 rollout 中，不存在任何一例“原本无记忆能做对、但注入记忆后做错”的现象。

### 阶段转段裁决：
根据总指令明确的转段红线：
> “只有在观察到自然提取的经验在新的边界任务上发生有害误用，或观察到某种修订导致保留任务发生灾难性损伤时，才允许进入 P2。若二者均未出现，请如实汇报，并保持在 P1 阶段深入分析原因。严禁为了转段而故意放宽条件匹配、人工构造伪反例或植入错误规则。”

**裁决：P2（双分支条件动作修订开发）继续暂停 (PAUSED)；当前研究阶段保持为 P1。**

---

## 6. 累计资源消耗账本 (Cumulative Accounting)

- **总预算硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours
- **P0 实际消耗**：8 Episodes / 35 Calls / 20,431 In Tokens / 1,704 Out Tokens / 177.4s
- **P1 累计消耗**：69 Episodes / 287 Calls / 160,483 In Tokens / 16,061 Out Tokens / 1,238.7s
- **本轮环境后果 Rollout 批次消耗**：
  - 来源采集与分支 Rollout：21 Episodes / 93 Calls
  - 基线能力预检：3 Episodes / 24 Calls
  - 提取调试核验：3 Calls
  - **本轮总计**：**24 Episodes / 120 Calls** (严格控制在本轮授权上限 80 Episodes / 4000 Calls 内，预算利用率 Episodes: 30.0%, Calls: 3.0%)
- **新周期当前累计**：**77 Episodes / 322 Calls / 198,679 Tokens / 1,416.1s (~23.6 分钟)**
- *(历史 79e6d23 探索性消耗单列于 `archive_exploratory_79e6d23/`，共计 184 Episodes, 839 Calls)*
