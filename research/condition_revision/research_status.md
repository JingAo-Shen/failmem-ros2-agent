# 持续研究状态跟踪文件 (Research Status)

**更新时间**：2026-10-21  
**当前阶段**：**失败轨迹迁移收益来源判别完成；正式执行决策 1（终止与转向）**  
**当前状态**：**已终结：实证证实失败轨迹迁移收益源于示范长度缓冲与高层目标提示，而非领域交互知识；原始失败轨迹产生严重归纳负迁移；正式停止基于失败轨迹迁移的方法开发**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 核心研究问题最终科学解答

> **“自然失败轨迹是否包含超出通用动作接口说明的、能够跨任务迁移的交互知识？”**

### **结论：否 (Negative)。**

本轮通过在 8 个预先冻结的目标任务上，对 6 个严格受控条件（A: 无记忆, B: 失败轨迹, C: 语法手册, D: 无关轨迹, E: 仅描述, F: 有效子序列）进行了 48 轮独立环境交互评测（总耗时 1555.9s，333 次交互调用），获得了坚实清晰的因果证据：

1. **收益来源非领域交互知识（H3 & H2 成立）**：
   - 在分类任务中，Condition B 表现出的“避免盲目聚焦”效应，被完全无关的**融化冰失败轨迹（Condition D）以完全一致的步数和得分（25.0分与17.0分）复现**，并在 T7 任务上仅用 3 步达成 100 分满分（超越 B 的 75 分）。这证明多步示范的增益主要来自**长上下文对贪婪短视决策的缓冲抑制效应（Demonstrative Buffering Effect）**；
   - 仅提供来源任务一句话目标描述的 **Condition E 取得了全场最高的任务成功率（37.5%，3/8 任务满分）**，超越了提供完整动作轨迹的 Condition B（25.0%），证明高层语义目标提示远比底层试错轨迹更高效安全。

2. **原始失败轨迹具有严重的归纳毒化（H4 负迁移）**：
   - 在基线 A、语法 C、无关 D、描述 E、片段 F 均能以 100 分满分成功的导电测试任务（T1 曲别针）中，**唯独注入了同领域失败轨迹的 Condition B 得分暴跌至 -100.0 分**；
   - 追踪显示，模型受铝箔失败轨迹中混乱尝试电路连线的强烈诱导，在目标任务上盲目连线 8 步，最终将导体放入绝缘箱，造成灾难性误导。

3. **通用语法手册（Condition C）在定义清晰任务上表现极致高效**：
   - 在 T1 任务中，Condition C 仅需 2 步即达成 100 分满分，耗时仅 9.0 秒，验证了结构化语法示范在操作规范性上的决定性优势。

---

## 2. 科学决策与研究转向 (Research Decision)

根据预设的客观裁决准则，正式宣布：

> ### **【决策 1（终止与转向 / Termination & Pivot）】**
> **全面停止基于自然失败轨迹迁移的方法开发与架构扩展。**

### 明确停止理由：
- 自然失败轨迹中并不包含无法被通用语法与目标提示替代的专属交互知识；
- 原始轨迹中混杂的大量无效探索动作会对智能体产生严重的因果先验污染（负迁移）；
- 任何试图直接从未经成功续写的失败轨迹中反思规则并迁移至新任务的框架，在理论与实证上均缺乏稳固的因果支撑。

---

## 3. 本项目全流程成果与资产清单

虽然停止了旧方案的方法扩展，但本项目沉淀了高质量的严谨研究资产与实证工具链：

1. **封存说明与审计声明**：[`closure_statement.md`](file:///code/failmem-ros2-agent/research/condition_revision/closure_statement.md)
   - 确立了 `NO_RULE_CREATED`、`RULE_GENERATED_NO_TRANSFER` 与 `TRANSFER_WITHOUT_NEGATIVE_EFFECT` 的三层严格定性区分。
2. **文献横向对比矩阵**：[`related_work_comparison.md`](file:///code/failmem-ros2-agent/research/condition_revision/related_work_comparison.md)
   - 系统核验了 ExpeL、LearnAct、Sentry、SkillPivot 在输入形式、可用反馈、成功续写依赖与更新对象上的本质差异。
3. **冻结评测清单与受控运行器**：
   - [`frozen_attribution_manifest.json`](file:///code/failmem-ros2-agent/research/condition_revision/frozen_attribution_manifest.json)
   - [`run_attribution_experiment.py`](file:///code/failmem-ros2-agent/research/condition_revision/run_attribution_experiment.py)
   - 全量 48 轮次步级可追溯运行库：`runs/run_20261020_232315_P1_attribution_experiment/attribution_results.json`
4. **判别实验分析报告**：[`attribution_experiment_report.md`](file:///code/failmem-ros2-agent/research/condition_revision/attribution_experiment_report.md)
5. **严谨的接地语义判定器与回归套件**：
   - [`condition_evaluator.py`](file:///code/failmem-ros2-agent/research/condition_revision/condition_evaluator.py)
   - [`test_interface_and_conditions.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_interface_and_conditions.py)（14/14 测试全部通过）。

---

## 4. 累计资源消耗最终核算 (Final Resource Accounting)

- **总硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours
- **累计实际消耗总计**：
  - **总轮次**：**129 Episodes**（占硬上限 4.3%）
  - **总调用**：**675 LLM Calls**（占硬上限 0.45%）
  - **总 Tokens**：**482,996 Tokens**
  - **总耗时**：**3,090.5s (~51.5 分钟，占 GPU 预算 0.72%)**
- **预算合规性**：**100% 严格在预算红线内执行，无任何超额消耗**。
