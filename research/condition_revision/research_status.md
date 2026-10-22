# 持续研究状态跟踪文件 (Research Status)

> [!IMPORTANT]
> **当前状态说明**：
> 1. **自然经验迁移筛查（`P1b_NATURAL_EXPERIENCE_SCREEN`）审计与核实完毕**：
>    - 在 ScienceWorld 任务 `boil` 的 4 项自然变体及 2 个独立伪随机重复块（共 24 个 episode）中，各条件端到端完成率分别为：**条件 A（No-Memory 基线）5/8（62.5%）**，**条件 B（Failure-Only 经验）2/8（25.0%）**，**条件 C（Success-With-Failure 完整经验）8/8（100.0%）**。
>    - **空动作提前终止核查**：在条件 B 的 6 次未完成中，有 **3 次（E13, E19, E21，占 37.5%）** 发生在环境弹出歧义取消菜单（`Ambiguous request: ... (or blank to cancel)`）时，模型输出有效 JSON 空动作（`"action": ""`）意图取消，但旧 native 适配器将空字符串判定为异常提前终止了 episode。条件 A 与条件 C 空动作终止率均为 0/8（0.0%）。该现象属于特定协议下的样本表现，不构成否定失败经验迁移的一般性理论证明。
>    - **成对胜负平与步数差异**：B 对比 A 为 2 胜 4 负 2 平（双双成功仅 1 对，B 多用 3 步）；C 对比 A 为 3 胜 0 负 5 平（零负场，双双成功 5 对，C 平均少用 5.8 步）。
> 2. **接口协议复查（`P1c_MENU_PROTOCOL_RECHECK`）执行中/完成**：
>    - 实现了统一通用协议：歧义取消菜单下模型输出空动作统一放行至 `env.step("")`；离线测试 30/30 通过。
>    - 针对变体 0 与变体 2（源轨迹复现变体）执行 12 轮独立复查（Blocks 3 & 4，种子 3408），单步调用严格限制 <= 2 次。
> 3. **预算与交互硬核对**：
>    - 累计 API 费用处于 $10.00 USD 授权总池内（当前已知开销约 $1.2 USD，剩余可用 > $8.7 USD）。
>    - 环境交互账目全口径审计：P1 历史核定 159 轮（包含 141 轮 7B、12 轮 Qwen3 预检及 6 轮 DeepSeek 真实准入预检 D1–D6）、P1b 筛查 24 轮、P1c 复查 12 轮，加上 P0 校准 8 轮，全流程累计环境交互 203 轮，无隐式少计。
> 4. **边界红线**：不开启 P2，不开发局部修订算法，不进入正式 held-out 确认集。

**更新时间**：2026-10-22  
**当前阶段**：**通用菜单协议复查 (P1c_MENU_PROTOCOL_RECHECK)**  
**当前状态**：**P1C_RECHECK_ACTIVE**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 现行结论事实说明 (Current Factual Status)

- **P1b 筛查实验事实 (24 Episodes, 原始轨迹已全部哈希索引归档)**：
  - 任务与变体：ScienceWorld `boil` Var 0（双正常）、Var 1（灶台破损）、Var 2（水槽破损，源轨迹变体）、Var 3（双破损）；
  - 条件与经验：条件 A（无经验）；条件 B（D6 步 1–3 失败前缀，SHA: `b4276884...`）；条件 C（D6 步 1–17 完整探索恢复，SHA: `3ecb0e98...`）；
  - 指标与表现：
    - **条件 A（No-Memory）**：完成率 5/8 (62.5%)，空动作终止 0/8 (0%)，均分 89.25，均步 24.38（成功均步 21.40）；
    - **条件 B（Failure-Only）**：完成率 2/8 (25.0%)，空动作终止 3/8 (37.5%)，均分 78.38，均步 21.50（成功均步 23.00）；
    - **条件 C（Success-With-Failure）**：完成率 8/8 (100.0%)，空动作终止 0/8 (0%)，均分 100.00，均步 18.12（成功均步 18.12）。
  - 配对对比（客观样本描述）：
    - **B vs A**：B 胜 2 对、A 胜 4 对、平 2 对；双双成功配对 1 对（B 比 A 多 3 步）；在当前适配器下 B 样本表现出较低完成率，且 3 次未完成直接受空动作判定所致；
    - **C vs A**：C 胜 3 对、A 胜 0 对、平 5 对；双双成功配对 5 对（C 平均少用 5.8 步）；完整成功经验在本样本中稳定达成满分并减少决策步数。
- **阶段隔离与账目事实**：
  - P1 历史准入预检（D1–D6，5/6 成功，消耗 159/160 episodes）结果保持原样，不篡改；
  - 环境交互全口径严格统计，无少计漏计。

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
  - **P1 归因与准入预检（Batches 2–14）**：159 episodes（含 141 轮 7B、12 轮 Qwen3 预检及 6 轮 DeepSeek 真实准入预检 D1–D6）, 1305 calls, 1,099,019 tokens, 10,529.2s (已消耗 159/160 episodes，开销 $0.1268 USD)
  - **P1b 自然经验迁移筛查（Batch 15）**：24 episodes, 517 calls, 774,373 tokens, 2,022.3s (已消耗 24/24 episodes，开销 $0.8651 USD)
  - **P1c 菜单协议复查（Batch 16）**：12 episodes, 242 calls, 358,126 tokens, 1,071.2s (已消耗 12/12 episodes，开销 $0.3874 USD)
- **累计实际消耗总计（P0 + P1 + P1b + P1c）**：
  - **环境交互总轮次（全口径核定）**：**203 Episodes**（占总硬上限 6.77%）
  - **总调用**：**2099 LLM Calls**（占总硬上限 1.40%）
  - **总 Tokens**：**2,253,653 Tokens**
  - **API 开销已知总额**：**$1.3793 USD**（占 10.00 美元限额的 13.79%）
  - **保守安全预留 hold**：**$0.0810 USD**
  - **累计承诺开销合计**：**$1.4603 USD**
  - **已核对官方账单**：**$0.00 USD**（待月度账单结算）
  - **剩余可用 API 额度**：**$8.5397 USD**
- **预算合规性**：**100% 严格在预算红线内执行，无超额消耗，账本清晰可审计**。
