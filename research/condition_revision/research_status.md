# 持续研究状态跟踪文件 (Research Status)

> [!IMPORTANT]
> **当前状态说明**：
> 本地 Qwen3-14B-AWQ 诊断维持 **LOCAL_BASELINE_QUALIFICATION_FAILED** 结论（有候选 2/6，无候选 0/6 未达准入门槛），暂停本地小模型调参与任务扩展，不恢复 P2。
> 现已完成强规划器接入的离线准备，标记为 **OFFLINE_BACKEND_PREPARATION_COMPLETE**。离线准备阶段消耗 0 环境 Episodes、0 次真实模型调用，剩余 7 个 P1 Episodes 预算严格保留，仅用于未来强规划器的准入预检。

**更新时间**：2026-10-22  
**当前阶段**：**强规划器接入离线准备 (Strong Planner Offline Backend Preparation)**  
**当前状态**：**OFFLINE_BACKEND_PREPARATION_COMPLETE**（本地基准判定：`LOCAL_BASELINE_QUALIFICATION_FAILED`）  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 现行结论事实说明 (Current Factual Status)

- **本地模型基线评定事实**：
  - 在有候选列表的 C1–C6 预检中，达成 2/6 任务成功（C1 导电var0: 100分，C2 导电var460: 100分；其余 C3: 60分, C4: 60分, C5: -100分, C6: -100分）；
  - 在无候选列表（`prompt_mode="no_candidates"`）的 N1–N6 诊断中，达成 0/6 任务成功（N1: 60分, N2: 55分, N3: 60分, N4: 60分, N5: 3分, N6: -100分）；
  - 确认本地配置未通过预设准入门槛，停止决定与 `LOCAL_BASELINE_QUALIFICATION_FAILED` 评定永久保留，不推翻不篡改。
- **强规划器离线准备就绪事实**：
  - 完成 OpenAI 兼容协议客户端 [`remote_llm_client.py`](file:///code/failmem-ros2-agent/research/condition_revision/remote_llm_client.py)，默认使用 Mock 传输层硬拦截外部网络，支持自动 JSON 单次重试与 Token 记账（无统计时置 `"unknown"`，杜绝假 0）；
  - 接入层具备快错机制（Fail-fast）：缺少必要参数或 API 密钥环境变量时直接退出，**绝不回退至本地模型**；
  - 在 [`BaseAgent`](file:///code/failmem-ros2-agent/research/condition_revision/agents/base_agent.py) 中新增 `prompt_mode="action_templates"`，完整注入 ScienceWorld 27 个原生动作模板与固定声明，保持原生直通模式（`adapter_mode="native"`）；
  - 离线自测套件 [`test_remote_planner_offline.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_remote_planner_offline.py) 覆盖全量 8 项测试并通过（全套件 25/25 测试通过）；
  - 冻结研究方案 [`counterexample_revision_protocol.md`](file:///code/failmem-ros2-agent/research/condition_revision/counterexample_revision_protocol.md) 与接入指南 [`offline_backend_preparation_guide.md`](file:///code/failmem-ros2-agent/research/condition_revision/offline_backend_preparation_guide.md) 已提交生效。
- **历史解释撤回说明**：此前早期报告中关于“完全证实长度/缓冲效应”、“全面否定失败轨迹价值”等解释性推论，已被正式标记为**已撤回的历史解释 (Withdrawn Historical Interpretations)**，仅作为早期实验记录留存，不再作为当前结论。

---

## 2. 决策与规划记录 (Decision Records)

- **停止决定与预算保留**：保留本地基线未准入判定，不启动 P2。P1 预算（160 episodes）已消耗 153，保留剩余 7 个 episodes 专门用于未来强规划器的准入预检。
- **协议冻结约束**：一旦启用远程强规划器，模型与超参数全流程冻结（temperature=0.0），严禁按任务微调或更换模型。


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
   - [`test_interface_and_conditions.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_interface_and_conditions.py)
6. **强规划器离线接入层与离线自测套件**：
   - [`remote_llm_client.py`](file:///code/failmem-ros2-agent/research/condition_revision/remote_llm_client.py)
   - [`remote_planner_config.example.json`](file:///code/failmem-ros2-agent/research/condition_revision/remote_planner_config.example.json)
   - [`test_remote_planner_offline.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_remote_planner_offline.py)（全套件 25/25 测试通过）
7. **反例修订研究协议与接入操作指南**：
   - [`counterexample_revision_protocol.md`](file:///code/failmem-ros2-agent/research/condition_revision/counterexample_revision_protocol.md)
   - [`offline_backend_preparation_guide.md`](file:///code/failmem-ros2-agent/research/condition_revision/offline_backend_preparation_guide.md)

---

## 4. 累计资源消耗最终核算 (Final Resource Accounting)

- **总硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours
- **统计口径**：
  - **P0 基础校准**：8 episodes, 35 calls, 22,135 tokens, 177.4s (COMPLETED)
  - **P1 归因、复核与基线诊断（Batches 2–12）**：153 episodes, 1248 calls, 1,007,907 tokens, 10,229.2s (预算 160 episodes，已消耗 153，剩余 7 episodes)
- **累计实际消耗总计（P0 + P1）**：
  - **总轮次**：**161 Episodes**（占总硬上限 5.37%）
  - **总调用**：**1283 LLM Calls**（占总硬上限 0.86%）
  - **总 Tokens**：**1,030,042 Tokens**
  - **总耗时**：**10,406.6s (~173.4 分钟，约 2.89 GPU 小时，占 GPU 预算 2.41%)**
- **预算合规性**：**100% 严格在预算红线内执行，无超额消耗，剩余 7 个 P1 episodes 预算保留**。

