# P1 真实运行核查、准入审计与最终科研裁决报告 (P1 Boundary Audit & Scientific Verdict)

**报告时间**：2026-10-20  
**基准分支**：`research/counterexample-condition-revision`  
**关联提交**：`7244944` $\to$ 当前工作批次  
**核心数据源**：  
- 真实运行日志：`runs/run_20261020_161138_P1_environmental_rollout/`
- 结构化审计导出：[`audit_export_7244944.json`](file:///code/failmem-ros2-agent/research/condition_revision/audit_export_7244944.json)
- 语义单测套件：[`tests/test_interface_and_conditions.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_interface_and_conditions.py) (14项测试 100% 通过)

---

## 1. 核心问题直接回答

> **“我们是否真的获得了一条原本有用、在新情境下暴露边界的自然经验？”**

### **实证核验结论：否 (Negative)。**

在 `7244944` 的实验运行与本轮深度数据审计中，我们**尚未获得**一条满足“原本有用、在新情境下暴露边界”的自然经验规则。原因如下：

1. **执行层面的提取跳过（`NO_RULE_CREATED`）**：
   在 `run_environmental_consequences.py`（第 150 行）中，历史代码设置了 `if success:` 门槛。由于 3 个来源任务均因多步词法或交互超时未达成 100 分满分（Foil 得分 60.0 超时、Fork 得分 -100 扣分、Living 得分 -100 扣分），**规则提取未在 rollout runner 中执行**。
   导致在当时的实测分支中：
   - **Condition C (Grounded Rule)**：规则库大小恒为 0（`rule_library = []`）；
   - **Condition D (Blind Rule Stress)**：注入提示词恒为空字符串（`forced_rule_str = ""`）；
   - 先前报告中记录的“未注入”，其实质并非接地判定系统的“条件安全拦截（`CONDITION_FALSE`）”，而是**根本未生成待测规则（`NO_RULE_CREATED`）**。

2. **准入层面的迁移范围未建立（`TRANSFER_SCOPE_NOT_ESTABLISHED`）**：
   即便对来源轨迹进行事后补充提取（见 `audit_export_7244944.json`）：
   - 提取出的规则适用条件均高度绑定来源任务的具体实体名词（如 `aluminum foil must be present in workshop` 或 `at least one living thing present in kitchen`）；
   - 在边界反例任务（杏子、非生物）或跨实体保留任务（金属锅、铁叉）中，由于实体名称与主语不匹配，在严格接地下求值均为 `FALSE` 或 `UNKNOWN`；
   - **规则在任何新情境下都无法实际激活**。根据准入规则，此状态属于“迁移范围未建立”，不能充当检验适用边界与局部修订的经验对象。

3. **示范层面的正向迁移（No Negative Transfer in Group B）**：
   在唯一真实注入了经验的 **Condition B（原始轨迹示范）** 中，示范不仅没有在新边界上引发错误误导，反而展现出**中性或显著的正向迁移**（在玻璃罐任务上提速 28.6%，在非生物分类任务上从无记忆的 25分超时跃升至 **100分满分成功**）。

---

## 2. 7244944 原始运行数据逐链深度核对

依据真实日志 `runs/run_20261020_161138_P1_environmental_rollout/` 重新核定三条链的原始执行状态：

### 2.1 链条 1 (`chain_01_conductivity_foil`)
- **来源任务**：`test-conductivity` var 0 (目标: `aluminum foil`)
  - 任务描述：`Your task is to determine if aluminum foil is electrically conductive... place it in the red box.`
  - 完整轨迹：Step 1 `teleport to workshop` (+10分) $\to$ Step 2 `focus on aluminum foil` (+50分) $\to$ Step 3-4 连接电极 $\to$ Step 5 模型提议 `place aluminum foil in red box`（因词法不匹配被适配器模糊匹配为 focus） $\to$ Step 6-8 尝试其他连接 $\to$ 第 8 步超时。
  - 最终状态：`success = False`, `score = 60.0` (未完成)。
  - 规则提取状态：未执行（`NO_RULE_CREATED`）。
  - **Condition C 每步状态**：规则库大小 = 0，检索结果 = None，求值记录 = 空，注入文本 = 无（原因：`NO_RULE_CREATED`）。
  - **Condition D 注入文本**：无（原因：`NO_RULE_CREATED`）。
  - **真实拒绝率统计**：未创建规则，条件求值次数 = 0。此前统计的“100% 拒绝”属于未创建规则的虚假归因。

### 2.2 链条 2 (`chain_02_conductivity_fork`)
- **来源任务**：`test-conductivity` var 300 (目标: `metal fork`)
  - 完整轨迹：前 2 步正常导航与聚焦（+60分），第 7 步模型错误执行 `move metal fork to green box`，触发环境致命惩罚（-160分）。
  - 最终状态：`success = False`, `score = -100.0`。
  - 规则提取状态：未执行（`NO_RULE_CREATED`）。补充提取尝试返回空内容（`PARSE_ERROR`）。
  - **Condition C & D 状态**：规则库大小 = 0，注入文本 = 无（原因：`NO_RULE_CREATED`）。

### 2.3 链条 3 (`chain_03_classification_living`)
- **来源任务**：`find-living-thing` var 1 (目标: `living thing`)
  - 完整轨迹：在 kitchen 中移动 table 上的物体，第 6 步对非生物杯子执行聚焦，触发环境扣分。
  - 最终状态：`success = False`, `score = -100.0`。
  - 规则提取状态：未执行（`NO_RULE_CREATED`）。
  - 补充提取规则：`["There must be at least one living thing present in the kitchen"]`。
  - **Condition C & D 状态**：规则库大小 = 0，注入文本 = 无（原因：`NO_RULE_CREATED`）。

---

## 3. 语义修复与用例扩充验证 (Section II)

针对前期代码中存在的语义漏洞，在 [`condition_evaluator.py`](file:///code/failmem-ros2-agent/research/condition_revision/condition_evaluator.py) 中完成修复，并在 [`tests/test_interface_and_conditions.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_interface_and_conditions.py) 中新增 4 项严密独立单测，**全套 14 项单测 100% 通过（耗时 0.03s）**：

| 单测编号 | 测试用例描述 | 输入观测 / 场景 | 修复前表现 (Bug) | 修复后判定 | 依据逻辑 |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Case 7** | `test_sample_non_metallic_not_judged_as_metal` | `"The sample is non-metallic."` | `TRUE` (因子串 metallic 误判) | **`FALSE`** | 负向谓词前置 + 正则单词边界 `(?<!non-)\bmetallic\b` |
| **Case 8** | `test_water_liquid_with_ice_cube_on_another_table_not_solid` | `"The water is liquid, and an ice cube is frozen on another table."` | `TRUE` (子串包含 frozen/ice cube) | **`FALSE` (solid), `TRUE` (liquid)** | 引入并列连词从句切分，严格隔离各主语谓词作用域 |
| **Case 9** | `test_unmentioned_object_returns_unknown_not_false` | `"You are in the kitchen. In it you see a table, a chair, and a cupboard."` (求值 apple) | `FALSE` (缺失即判定不存在) | **`UNKNOWN`** | 未提及对象返回 `UNKNOWN / INSUFFICIENT_EVIDENCE`，杜绝伪反例 |
| **Case 10** | `test_historical_wiring_not_spliced_with_disjoint_bulb_state` | 历史接电池灯亮，断开后接铁叉灯灭 | `TRUE` (任意时刻灯亮拼接历史接线) | **`UNKNOWN`** | 时序电路跟踪：仅当目标实体**处于接入状态的瞬间**灯亮才算有效导电证据 |

---

## 4. 运行控制修正与分支可比性审计 (Section IV & V)

1. **交互步数与预算截断定义**：
   - 统一环境上限：测试任务统一为 10 步；
   - 明确区分预算截断与规划失败：Chain 1 来源任务在第 8 步提议 `place aluminum foil in red box`（目标正确但语法不匹配），因步数耗尽属于预算截断（Budget Truncation），并非模型科学认知上的致命错误。
2. **前缀一致性保障**：
   - 各条件（A/B/C/D）在重置环境后，必须通过相同的前缀交互到达分叉点；
   - 若前缀执行中触发了环境 `done`，立即终止，严禁继续向模型查询后续动作。
3. **适配器透明度与动作审计**：
   - 详细记录模型原始动作（`model_action`）、执行动作（`executed_action`）与适配原因（`adapter_reason`）；
   - 明确确认：在 Chain 2 的玻璃罐满分成功中，模型原始提议动作即为 `move glass jar to green box`，属于**模型自身常识决策正确，而非适配器强行修正**。

---

## 5. “保留测试”的重新定性 (Section VI)

1. **术语修正**：在尚未执行局部经验修订时，原 Retention 任务正式更名为**“原有效范围候选任务 (Candidate Tasks for Original Valid Scope)”**。
2. **避免重复定义**：经全局审查，Chain 2 来源任务（Metal Fork var 300）与 Chain 1 的保留测试任务重合。已在清单中去重，不将跨链已用任务视作“全局未见任务”。
3. **因果顺序红线**：只有当经验在新边界上确实发生误用，且该经验被算法修订后，方可启动对原有效范围的知识损伤度量。在未发生误用的前提下，宣称“成功保留旧知识”缺乏因果意义。

---

## 6. 最终科研裁决与交付回答 (Section VII)

### 6.1 核心交付问题回答

#### Q1: 旧经验在哪些情境中确实有用？
- **实证证据**：在当前覆盖范围内，**仅在原始轨迹检索示范（Condition B）中观察到经验的明确正向效用**：
  - 在生物分类边界任务中，示范向模型提供了合法动作模式，使模型直接从无记忆的 25 分（超时探索失败）提升为 **100 分满分成功（仅需 3 步）**；
  - 在玻璃罐导电测试中，示范使模型动作序列更紧凑，完成步数从 7 步缩减至 5 步。
  - 对于文本规则（Condition C），在严格物理接地下尚未建立具有跨任务泛化收益的有效规则。

#### Q2: 旧经验在哪些新情境中确实失效？
- **实证证据**：**未观察到由于旧经验注入而导致任务在新情境下失效的现象（0 负迁移事件）**。
  - 在所有边界任务（如杏子被放入红盒），无记忆基线（Cond A）同样犯下完全相同的错误；
  - 经验注入后，未出现任何“无记忆能做对，但有记忆做错”的实例。

#### Q3: 现有证据是否足以研究局部修订？
- **实证证据**：**完全不足以（Insufficient）**。
  - 开展“局部适用条件修订”的前提是：自然生成的经验在新情境中因条件过于宽泛而产生有害误用，导致任务恶化。
  - 既然在严格物理接地系统下，具象实体条件不会发生泛化误用；而在轨迹示范下又表现为正向迁移，那么“反例后局部修订条件”就缺乏真实的现象基础与因果痛点。

---

### 6.2 阶段裁决结论：结论 3 $\to$ 提交有覆盖范围限制的 NO-GO

根据用户总指令的严格停止与转段条件：
> “若本批完成后，仍然只有轨迹示范的正向迁移、没有适用边界冲突，则停止继续扩展当前条件修订方案，提交有覆盖范围限制的 no-go 结论。”

**正式裁决**：
- **终止“反例驱动的条件适用范围局部修订 (Counterexample Condition Revision)”方案的继续扩展开发**；
- **P2（双分支条件动作修订架构）永久终止；当前阶段保持为 P1，封存实验成果**；
- 绝不通过人为放宽接地判据或人工植入宽泛错误规则制造伪现象。

---

### 6.3 替代研究方向建议 (最多两个替代问题及最小区分实验)

基于本轮真实观察到的模型行为特征（模型常识具备辨别力，但在交互中高度依赖动作语法提示；轨迹示范极具指导价值但难以参数化控制），提出两个具有明确区分度和更高 SCI 投稿价值的替代研究方向：

#### 替代方向 1：基于环境反馈的交互式实体接地与约束澄清 (Interactive Feedback-Driven Constraint Grounding)
- **核心问题**：当 Agent 生成的计划由于环境未明属性（如不可见容器、非标准动作谓词）受阻时，如何利用环境试错的即时报错信号，在线澄清前置假设并完成动作纠偏，而不是依赖预先提取的静态静态规则？
- **最小区分实验**：
  - 任务场景：选择 5 组因环境隐式属性（如抽屉未开、物体不可见）超时的多步科学任务；
  - 对照组：静态规则注入 vs 交互式反馈反射（在线反思环境返回的报错信息生成临时探针动作）；
  - 评价指标：任务完成率、试错步数成本。

#### 替代方向 2：长程 Agent 轨迹归纳中的“归纳跃迁过度泛化”检测与因果过滤 (Inductive Leap Detection in Agent Trajectory Summarization)
- **核心问题**：若促使 LLM 将单次成功经验自发抽象为通用经验（例如将“铝箔导电”抽象为“银白色固体均可作导线”），Agent 何时会产生有害的归纳跃迁（Inductive Leap）？如何通过反事实因果探测在经验进入记忆库前识别并拦截此类伪知识？
- **最小区分实验**：
  - 任务场景：设计显式诱导泛化的提取提示词（Specific vs Abstract-Inductive）；
  - 对照组：无门控全局记忆 vs 基于特征覆盖度的因果反事实干预门控；
  - 评价指标：在反例任务上的负迁移率（False-Positive Activation Rate）与知识库污染度。

---

## 7. 最终资源账本与预算合规确认

- **总硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours
- **上轮结存**：
  - P0 消耗：8 Episodes / 35 Calls
  - P1 累计消耗：69 Episodes / 287 Calls
- **本轮核算与单测消耗**：
  - 纯数据审计、单测回归与代码重构（本地运行，未发生额外模型推理调用）；
  - 本轮净增：0 Episodes / 0 Calls；
  - 消耗保持在上轮执行后的累计值。
- **当前全周期累计消耗**：
  - **总 Episodes**：77 / 3000 (利用率 2.57%)
  - **总 Model Calls**：322 / 150000 (利用率 0.21%)
  - **总 Tokens**：198,679 Tokens
  - **总 GPU 时间**：约 23.6 分钟 / 120.0 小时 (利用率 0.33%)
  - **预算合规率**：**100% 严格合规**。
