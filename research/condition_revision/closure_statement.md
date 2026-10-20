# 条件适用范围局部修订方案正式封存与审计声明 (Closure & Archival Statement)

**封存时间**：2026-10-20  
**基准分支**：`research/counterexample-condition-revision`  
**封存依据**：P0/P1 全流程实证运行数据与严格审计结论  

---

## 1. 核心封存结论

> **“在当前模型、任务与实验实现下，未建立能够检验局部适用条件修订的有效经验对象，因此停止该实现的扩展。”**

---

## 2. 实验现象三层定性区分

必须严格区分以下三类本质不同的实验状态，现有实证事实绝不能被混淆解释：

1. **没有生成待测规则（`NO_RULE_CREATED`）**：
   - **实证事实**：在 `run_environmental_consequences.py`（第 150 行）中，由于设置了 `if success:` 逻辑，全部 3 个来源任务均因多步词法或步数截断未取得 100 分满分（Foil 得分 60.0 超时、Fork 得分 -100 扣分、Living 得分 -100 扣分），导致**规则提取器在评测中从未被执行**；
   - **后果**：Condition C 的规则库实际为空（大小为 0），Condition D 实际注入文本为空字符串；
   - **定性归类**：**现有实验实测数据主要且根本地属于“第一类：没有生成待测规则”**。在规则库为空的状态下，从未发生对实际存在规则的条件求值，因此绝不能将未注入解释为“经过逻辑判定后的安全阻断”。

2. **已生成规则但没有迁移（`RULE_GENERATED_NO_TRANSFER`）**：
   - **实证事实**：对于任何事后尝试提取的规则，LLM 均生成了绑定具体物体名称的具象条件（如 `aluminum foil must be present in workshop`）；
   - **后果**：在边界反例任务（杏子、非生物）或保留任务（金属锅、铁叉）中，因实体主语不匹配，在严谨物理接地下求值必然为 `FALSE` 或 `UNKNOWN`，**在任何测试任务中均无法实际激活**；
   - **定性归类**：此状态属于“迁移范围未建立”，不能充当评估反例后局部修订能力的经验对象。

3. **已发生迁移但没有负效应（`TRANSFER_WITHOUT_NEGATIVE_EFFECT`）**：
   - **实证事实**：在唯一真实注入了经验的 Condition B（原始失败轨迹示范）中，模型不仅未受失败轨迹误导，反而表现为中性或正向迁移（玻璃罐提速 28.6%，非生物分类任务直接从 25 分超时跃升至 100 分满分成功）；
   - **定性归类**：未观察到由于经验注入引发的任务退化或反例边界冲突（0 负迁移事件）。

> **科学结论界限**：由于实测主干处于“第一类（未生成待测规则）”，我们不能将该工程实现中的空值运行作为后两类（迁移与负效应）的充分实证依据。

---

## 3. 历史文档审计与已知限制核实

1. **关于“事后补充提取”的真实性修正**：
   - 先前报告提及的“事后补充提取”属于终端临时测试，未在正式运行目录中固化完整的请求 Payload、原始模型响应、解析日志与带时间戳的调用记录；
   - **审计判定**：正式定性为**未核实（Unverified exploratory traces）**，在后续研究中不再作为正式验证产物引用。

2. **关于代码声称能力的已知限制核实**：
   - **前缀提前终止检查（Prefix Done Check）**：历史 `execute_prefix` 代码在执行导航与聚焦动作时，虽记录了环境返回的 `done` 状态，但未在检测到 `done=True` 时立即 `break` 退出。此项属于**已知限制（Known Limitation）**，已在本次封存中如实标记；
   - **跨链任务实例重叠（Task Overlap）**：历史清单中 Chain 2 来源任务（Metal Fork var 300）与 Chain 1 保留任务实例重合。此项属于**已知限制（Known Limitation）**，正式封存，不宣传为未见任务。

---

## 4. 封存代码边界

保留已通过 14 项单元测试（覆盖严格非金属词边界、从句主语隔离、未见实体未知态、时序电路绑定）的 [`condition_evaluator.py`](file:///code/failmem-ros2-agent/research/condition_revision/condition_evaluator.py) 与 [`tests/test_interface_and_conditions.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_interface_and_conditions.py) 作为基础工具。不再为了维持旧方案的报告措辞继续进行代码重构或寻找特殊失败案例。
