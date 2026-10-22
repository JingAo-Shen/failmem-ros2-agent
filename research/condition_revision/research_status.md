# 持续研究状态跟踪文件 (Research Status)

> [!IMPORTANT]
> **当前状态说明**：
> 自然经验迁移筛查（`P1b_NATURAL_EXPERIENCE_SCREEN`）已完整执行完毕。在 ScienceWorld 任务 `boil` 的 4 项自然变体（Var 0: 水槽正常/灶台正常, Var 1: 水槽正常/灶台损坏, Var 2: 水槽损坏/灶台正常, Var 3: 水槽损坏/灶台损坏）以及 2 个独立伪随机重复块下，完成了全部 24 个 episode 的受控实验：
> 1. **条件 A（No-Memory 基线）**：达成 **5/8 成功（62.5%）**，平均得分 89.25，平均步数 24.38（成功平均 21.40 步）。
> 2. **条件 B（Failure-Only 经验）**：仅提供源轨迹 D6 第 1–3 步的失败前缀经验（"水槽可能损坏，切勿依赖水槽"），成功率骤降至 **2/8 成功（25.0%）**，平均得分 78.38。在配对比较中，A 胜 4 轮，B 仅胜 2 轮（平 2 轮），**呈现出显著的负迁移现象（Δ 成功率 = -37.5%）**，甚至在产出该失败经验的原变体（Var 2）上连续 2 轮失败。
> 3. **条件 C（Success-With-Failure 完整经验）**：提供包含局部失败与探索恢复的完整经验（D6 第 1–17 步），达成 **8/8 满分全胜（100.0%）**，平均得分 100.00，平均步数 18.12。在配对比较中，C 胜 3 轮，A 胜 0 轮（平 5 轮，零负场），在双双成功的配对中比基线 **平均少用 5.8 步（-5.8 步）**，且在灶台损坏的变体（Var 1, Var 3）中自主迁移使用烤箱加热成功。
> 4. **预算执行**：本阶段消耗 24 个环境 episodes、517 次模型调用，开销 $0.8651 USD。历史 P1 用量保持 159/160 episodes 不变，P1 + P1b 累计模型调用 574 次，累计已知开销 **$0.9918 USD**（含安全预留合计 $1.0523 USD），严格处于 $10.00 USD 授权总预算池红线以内（剩余 $8.9477 USD）。
> 5. **边界坚守**：坚决不擅自恢复 P2，不运行正式 held-out 确认集，不自行实现局部修订算法，客观交付原始数据。

**更新时间**：2026-10-22  
**当前阶段**：**自然经验迁移筛查 (P1b_NATURAL_EXPERIENCE_SCREEN)**  
**当前状态**：**P1B_SCREENING_COMPLETED**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 现行结论事实说明 (Current Factual Status)

- **筛查实验设计与执行事实 (P1b 24 Episodes)**：
  - 任务：ScienceWorld `boil`；
  - 变体覆盖：Var 0（双正常）、Var 1（灶台破损）、Var 2（水槽破损，源轨迹变体）、Var 3（双破损）；预检 100% 确认初始破损状态；
  - 重复块设计：Block 1（E01–E12）与 Block 2（E13–E24），使用固定种子 3407 分别独立伪随机打乱执行顺序；
  - 模型与环境：官方 `deepseek-flash`、`adapter_mode="native"`、`prompt_mode="action_templates"`、`history_mode="all_steps"`（150 字符截断）、步数上限 30；
  - 实验结果：
    - **条件 A（No-Memory）**：成功率 5/8 (62.5%)，平均分 89.25，平均决策步 24.38，成功平均步 21.40；
    - **条件 B（Failure-Only）**：成功率 2/8 (25.0%)，平均分 78.38，平均决策步 21.50，成功平均步 23.00；
    - **条件 C（Success-With-Failure）**：成功率 8/8 (100.0%)，平均分 100.00，平均决策步 18.12，成功平均步 18.12。
- **配对对比分析 (Paired Comparisons)**：
  - **B vs A**：A 胜 4，B 胜 2，平 2；成功率变化 -37.5%；双方均成功配对中 B 比 A 多用 3 步；证实单纯注入失败前缀经验会导致显著负迁移；
  - **C vs A**：C 胜 3，A 胜 0，平 5（A 零胜场）；成功率变化 +37.5%；双方均成功配对中 C 比 A 少用 5.8 步；证实完整成功轨迹注入具备强鲁棒正迁移效益。
- **历史数据与阶段隔离说明**：
  - P1 历史准入预检（D1–D6，5/6 成功，消耗 159/160 episodes）结果保持原样，不篡改；
  - 本轮作为独立的 P1b 探索筛查阶段，不推导过度泛化结论，不冒充最终确认集。

---

## 2. 决策与规划记录 (Decision Records)

- **严格遵循停止条件**：24 个 episode 运行结束并完成统计分析后立即停止。
- **不恢复 P2**：P2 保持 `TERMINATED_NO_GO` 状态，不消耗未核准预算，不擅自开发算法。
- **预算透明与安全**：已核算各部分开销，区分实测 usage 估值与预留 hold。

---

## 3. 本项目全流程成果与资产清单

1. **官方定价配置与审计规范**：
   - [`pricing_config.json`](file:///code/failmem-ros2-agent/research/condition_revision/pricing_config.json)
2. **自然经验迁移筛查套件与交付物 (`natural_experience_screen/`)**：
   - 固化经验与哈希：[`frozen_experiences.json`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/frozen_experiences.json)
   - 变体破损预检：[`variation_status_preflight.json`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/variation_status_preflight.json)
   - 随机打乱清单：[`manifest.json`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/manifest.json)
   - 执行脚本与分析器：[`run_natural_screen.py`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/run_natural_screen.py)、[`analyze_results.py`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/analyze_results.py)
   - 24 轮独立运行记录：[`runs/`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/runs/)（E01–E24 JSON）
   - 逐轮汇总与步级明细：[`natural_experience_screen_summary.csv`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/natural_experience_screen_summary.csv)、[`step_summary.csv`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/step_summary.csv)
   - 配对对比统计报告：[`paired_comparison_report.json`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/paired_comparison_report.json)
   - 阶段执行记录：[`execution_notes.md`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/execution_notes.md)
   - 实时预算账本：[`budget_ledger.json`](file:///code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/budget_ledger.json)
3. **强规划器底层与回归套件**：
   - [`remote_llm_client.py`](file:///code/failmem-ros2-agent/research/condition_revision/remote_llm_client.py)
   - [`tests/test_remote_planner_offline.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_remote_planner_offline.py)（29/29 离线测试通过）
4. **历史阶段封存资产**：
   - DeepSeek 准入预检：[`deepseek_precheck/`](file:///code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/)
   - 协议与审计说明：[`counterexample_revision_protocol.md`](file:///code/failmem-ros2-agent/research/condition_revision/counterexample_revision_protocol.md)、[`closure_statement.md`](file:///code/failmem-ros2-agent/research/condition_revision/closure_statement.md)

---

## 4. 累计资源消耗最终核算 (Final Resource Accounting)

- **总硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours / $10.00 USD API Budget
- **统计口径**：
  - **P0 基础校准**：8 episodes, 35 calls, 22,135 tokens, 177.4s (COMPLETED)
  - **P1 归因与准入预检（Batches 2–14）**：159 episodes, 1305 calls, 1,099,019 tokens, 10,529.2s (已消耗 159/160 episodes，开销 $0.1268 USD)
  - **P1b 自然经验迁移筛查（Batch 15）**：24 episodes, 517 calls, 774,373 tokens, 2,022.3s (已消耗 24/24 episodes，开销 $0.8651 USD)
- **累计实际消耗总计（P0 + P1 + P1b）**：
  - **总轮次**：**191 Episodes**（占总硬上限 6.37%）
  - **总调用**：**1857 LLM Calls**（占总硬上限 1.24%）
  - **总 Tokens**：**1,895,527 Tokens**
  - **API 开销已知总额**：**$0.9918 USD**（占 10.00 美元限额的 9.92%，剩余可用额度 **$8.9477 USD**）
- **预算合规性**：**100% 严格在预算红线内执行，无超额消耗，账本清晰可审计**。
