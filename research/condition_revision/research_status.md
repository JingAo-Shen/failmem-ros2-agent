# 持续研究状态跟踪文件 (Research Status)

> [!IMPORTANT]
> **当前状态说明**：
> DeepSeek 真实规划器准入预检（D1–D6）已执行完毕。在统一设置（`extra_context=""`、`adapter_mode="native"`、`prompt_mode="action_templates"`、`history_mode="all_steps"`）下，模型在 6 项基准任务中达成 **5/6 成功**（D1: 100分, D2: 100分, D3: 100分, D4: 60分, D5 melt: 100分, D6 boil: 100分），且复杂长程任务 `melt` 与 `boil` 均成功完成。
> 满足预设门槛（>= 4/6 成功且包含长程任务），评定为 **REMOTE_PLANNER_DEVELOPMENT_GATE_PASSED**。
> 本轮消耗 6 个环境 episodes、57 次模型调用，累计 P1 预算达到 159/160 episodes（剩余 1 个 episode 预算）。根据预设规则，本轮立即停止，不自动启动 P2，不追加记忆机制实验，先提交本轮原始结果供审查。

**更新时间**：2026-10-22  
**当前阶段**：**DeepSeek 真实规划器准入预检 (D1–D6)**  
**当前状态**：**REMOTE_PLANNER_DEVELOPMENT_GATE_PASSED**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 现行结论事实说明 (Current Factual Status)

- **DeepSeek 真实规划器准入事实 (D1–D6)**：
  - 规划器模型：官方 `deepseek-flash`（目标版本：`DeepSeek-V4.1-Flash-1017`，系统指纹：`e72d3c7f663d3e1383b00b3884cb4501`）；
  - 配置：`thinking={"type":"enabled"}`、`reasoning_effort="high"`、`response_format={"type":"json_object"}`、`max_tokens=8192`、`stream=false`、超时 180s；未发送 `temperature`、`top_p` 或 `seed`；
  - 非环境检查：1 次请求即成功返回 `{"ok": true}`；
  - 任务成绩：
    - D1 (`test-conductivity`, var 0): 100 分 (5 步成功)
    - D2 (`test-conductivity`, var 460): 100 分 (3 步成功)
    - D3 (`test-conductivity`, var 160): 100 分 (4 步成功)
    - D4 (`test-conductivity`, var 230): 60 分 (18 步环境结束)
    - D5 (`melt`, var 4): 100 分 (8 步成功)
    - D6 (`boil`, var 2): 100 分 (17 步成功)
  - 门槛达成情况：成功率 5/6（$\ge 4/6$），且 `melt` 与 `boil` 双项均达成 100 分成功，通过开发准入门槛。
- **与既有 C1–C6 初始状态一致性核验**：
  - 经逐任务核对（参见 [`consistency_check_vs_c1_c6.json`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/consistency_check_vs_c1_c6.json)），D1–D6 与 C1–C6 的初始任务描述、初始观察文本及初始分数 100% 完全一致（`all_initial_conditions_identical: true`）。
- **本地历史模型对比说明**：
  - 本轮属于已知开发案例上的准入测试，不作为独立确认性研究，不与旧模型结果宣称严格的模型能力因果比较。
  - 本地 Qwen 系列（7B 与 14B）的历史诊断结果（`LOCAL_BASELINE_QUALIFICATION_FAILED`）作为历史阶段记录保留，不推翻。

---

## 2. 决策与规划记录 (Decision Records)

- **停止决定执行**：六项任务完成并产出原始数据后立即停止。即使准入通过，也坚决不自动启动 P2，不消耗未核定预算，不追加反例记忆实验。
- **协议同步**：研究协议 [`counterexample_revision_protocol.md`](file:///code/failmem-ros2-agent/research/condition_revision/counterexample_revision_protocol.md) 已同步更新，明确将“消除负迁移、保留正向收益”确立为待检验目标，严格隔离三类数据集，删除确定性保证断言。

---

## 3. 本项目全流程成果与资产清单

1. **封存说明与审计声明**：[`closure_statement.md`](file:///code/failmem-ros2-agent/research/condition_revision/closure_statement.md)
2. **文献横向对比矩阵**：[`related_work_comparison.md`](file:///code/failmem-ros2-agent/research/condition_revision/related_work_comparison.md)
3. **冻结评测清单与受控运行器**：
   - [`frozen_attribution_manifest.json`](file:///code/failmem-ros2-agent/research/condition_revision/frozen_attribution_manifest.json)
   - [`run_attribution_experiment.py`](file:///code/failmem-ros2-agent/research/condition_revision/run_attribution_experiment.py)
4. **判别实验分析报告**：[`attribution_experiment_report.md`](file:///code/failmem-ros2-agent/research/condition_revision/attribution_experiment_report.md)
5. **接地语义判定器与回归套件**：
   - [`condition_evaluator.py`](file:///code/failmem-ros2-agent/research/condition_revision/condition_evaluator.py)
   - [`test_interface_and_conditions.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_interface_and_conditions.py)
   - [`test_remote_planner_offline.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_remote_planner_offline.py)（26/26 离线测试通过）
6. **强规划器接入与预算控制器**：
   - [`remote_llm_client.py`](file:///code/failmem-ros2-agent/research/condition_revision/remote_llm_client.py)
   - [`run_deepseek_precheck.py`](file:///code/failmem-ros2-agent/research/condition_revision/run_deepseek_precheck.py)
7. **DeepSeek 准入预检原始数据集与账本**：
   - 任务结果：[`deepseek_precheck/`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/)
   - 逐任务概览：[`summary.csv`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/summary.csv)
   - 步级明细：[`step_summary.csv`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/step_summary.csv)
   - 实时账本：[`budget_ledger.json`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/budget_ledger.json)
   - C1–C6 一致性对比：[`consistency_check_vs_c1_c6.json`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/consistency_check_vs_c1_c6.json)
8. **反例修订研究协议与接入指南**：
   - [`counterexample_revision_protocol.md`](file:///code/failmem-ros2-agent/research/condition_revision/counterexample_revision_protocol.md)
   - [`offline_backend_preparation_guide.md`](file:///code/failmem-ros2-agent/research/condition_revision/offline_backend_preparation_guide.md)

---

## 4. 累计资源消耗最终核算 (Final Resource Accounting)

- **总硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours / $10.00 USD API Budget
- **统计口径**：
  - **P0 基础校准**：8 episodes, 35 calls, 22,135 tokens, 177.4s (COMPLETED)
  - **P1 归因、复核与基线诊断（Batches 2–14）**：159 episodes, 1305 calls, 1,099,019 tokens, 10,529.2s (预算 160 episodes，已消耗 159，剩余 1 episode 预算)
- **累计实际消耗总计（P0 + P1）**：
  - **总轮次**：**167 Episodes**（占总硬上限 5.57%）
  - **总调用**：**1340 LLM Calls**（占总硬上限 0.89%）
  - **总 Tokens**：**1,121,154 Tokens**
  - **本轮 API 开销**：**$0.1268 USD**（占 10.00 美元限额的 1.27%）
- **预算合规性**：**100% 严格在预算红线内执行，无超额消耗，P1 剩余 1 个 episode 预算保留**。
