# 持续研究状态跟踪文件 (Research Status)

> [!IMPORTANT]
> **当前状态说明**：
> 当前Qwen2.5-Coder-7B-Instruct配置的开发诊断暂停。最近历史窗口对照四轮均未完成任务，尚不足以支持失败记忆机制评价。此结论仅针对当前实验配置，不推广至整个失败记忆研究方向。

**更新时间**：2026-10-21  
**当前阶段**：**配置开发诊断暂停与本机资源清点**  
**当前状态**：**开发诊断暂停 (Development Diagnosis Paused)**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 现行结论事实说明 (Current Factual Status)

- **当前开发状态**：Qwen2.5-Coder-7B-Instruct 配置的开发诊断已暂停；目前正在执行候选规划器 Qwen3-14B-AWQ 的无记忆基础能力预检。
- **事实记录**：在 Qwen2.5-Coder-7B-Instruct 的严格受控实验中，历史窗口对照（R15–R18）与多轮交互均未能在测试变体上达成稳定任务成功，当前实测数据尚不足以对失败记忆机制提供充分的判定支持。
- **历史解释撤回说明**：此前报告中关于“完全证实长度/缓冲效应”、“全面否定失败轨迹价值”等解释性推论，已被正式标记为**已撤回的历史解释 (Withdrawn Historical Interpretations)**，仅作为特定早期实验配置下的观测记录留存，不再作为当前有效的研究结论。

---

## 2. 决策与规划记录 (Decision Records)

- **阶段决策**：原基于自然失败轨迹条件修订的特定方法扩展继续封存，不自动恢复 P2 架构扩展。
- **当前方向**：在独立、无记忆、原生动作直通基线下，先完成候选规划器（Qwen3-14B-AWQ）的多任务基础环境交互预检，依据客观执行记录确定后续能力基线。

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
