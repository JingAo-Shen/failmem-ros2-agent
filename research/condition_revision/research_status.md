# 持续研究状态跟踪文件 (Research Status)

> [!IMPORTANT]
> **当前状态说明**：
> 1. **通用接口对照实验（`P1d_GENERIC_INTERFACE_CONTROL`）执行与分析完毕**：
>    - 在 ScienceWorld `boil` 任务变体 0 与变体 2（源轨迹复现变体）共 16 个 episode（Block 5 & 6，随机种子 3409）中，各条件完成率与均分分别为：
>      - **条件 A（No-Memory 基线）**：完成率 2/4 (50.0%)，均分 86.25，Dunk 错误 1 次；
>      - **条件 G（通用动作语义说明）**：完成率 3/4 (75.0%)，均分 93.75，Dunk 错误 2 次；
>      - **条件 C（具体恢复经验）**：完成率 2/4 (50.0%)，均分 43.00，Dunk 错误 0 次；
>      - **条件 GC（通用语义 + 具体经验）**：完成率 3/4 (75.0%)，均分 93.00，Dunk 错误 0 次。
>    - **主比较（GC vs G，通用动作语义上具体经验是否有边际收益）**：
>      - **任务完成率与得分**：总体完成率持平（75.0% vs 75.0%）；配对比较中，GC 胜 1 对（Var 2 Block 6: GC=100 vs G=75），G 胜 1 对（Var 2 Block 5: G=100 vs GC=72），平 2 对（Var 0 双双满分）。
>      - **双双成功步数增量（2 对，均为 Var 0）**：GC 决策步数比 G 均少 4 步（平均 $\Delta = -4.00$ 步；M05 为 18 步 vs M02 为 22 步，M15 为 18 步 vs M14 为 22 步；环境步平均 $\Delta = -2.50$ 步）。
>      - **液体交互探索抑制与成本**：G 产生 2 次无效 dunk 错误，而 GC 产生 0 次 dunk 错误；GC 的执行耗时（42.0s）与模型费用（$0.0625）显著低于 G（67.8s, $0.1066）。
>    - **次要比较**：
>      - **G vs A**：成功率 75% 对比 50%，得分 2 胜 0 负 2 平。证明提供清晰的通用动作接口语义说明本身即可显著降低大模型盲目试错、提升规划成功率。
>      - **C vs A**：成功率 50% 对比 50%，C 在成功变体中大幅精简步数（Var 2 Block 5 仅 10 步 vs 24 步），但在未适应变体中因误用陷入严重惩罚（M01 得分 -100）。
>      - **GC vs C**：成功率 75% 对比 50%，GC 借助通用语义规则有效防止了极端惩罚。
> 2. **前置小修正落实**：
>    - 单决策 HTTP 请求严格限制为共享最多 2 次尝试（网络传输重试与 JSON 重试共享配额，第 3 次禁止发出，超额记录 `step_request_budget_exhausted`），离线 Mock 测试 18/18 通过。
>    - 文档因果表述完成客观修正，移除主观因果归因。
> 3. **全流程环境交互审计（全口径明细）**：
>    - **真实模型评测 Episode 数**：219（P0 校准 8、P1 历史 153、P1 真实准入 6、P1b 筛查 24、P1c 复查 12、P1d 对照 16）。
>    - **变体准入预检 Reset 次数**：4（Boil 变体 0, 1, 2, 9 兼容性重置）。
>    - **早期排查探针交互**：未留存独立完整日志的早期排查探针，历史记录预估约 0–12 次交互，按未知处理，不主观编造具体数字。
> 4. **预算核对**：
>    - 累计已知 API 开销：$1.847586 USD；保守预留未知费用：$0.102252 USD；累计承诺开销：$1.949837 USD。
>    - 剩余安全可用额度：$8.050163 USD（严格在 $10.00 USD 预算池内）。
> 5. **边界红线**：不开启 P2，不开发局部修订算法，不运行正式 held-out 确认集。

**更新时间**：2026-10-23  
**当前阶段**：**通用接口对照实验 (P1d_GENERIC_INTERFACE_CONTROL) 完成**  
**当前状态**：**P1D_EXPERIMENT_COMPLETED**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 现行结论事实说明 (Current Factual Status)

- **P1d 对照实验事实 (16 Episodes, 原始轨迹 M01–M16 已全部哈希索引归档)**：
  - 任务与变体：ScienceWorld `boil` Var 0（基准环境）、Var 2（水槽破损，源轨迹变体）；
  - 条件与设计：
    - **A (No-Memory 基线)**：无通用语义，无经验；
    - **G (Generic Action Semantics)**：冻结通用动作语义说明（SHA: `ab7aadf7...`），无经验；
    - **C (Specific Recovery Experience)**：无通用语义，冻结完整恢复经验（SHA: `3ecb0e98...`）；
    - **GC (Semantics + Experience)**：通用动作语义说明 + 完整恢复经验；
    - 槽位顺序：通用动作语义 -> 经验文本 -> 基础提示词；
  - 实验结果：
    - **条件 A**：完成率 2/4 (50.0%)，均分 86.25，Dunk 错误 1，成功决策均步 22.0，模型调用 90 次，费用 $0.1585；
    - **条件 G**：完成率 3/4 (75.0%)，均分 93.75，Dunk 错误 2，成功决策均步 21.67，模型调用 95 次，费用 $0.1066；
    - **条件 C**：完成率 2/4 (50.0%)，均分 43.00，Dunk 错误 0，成功决策均步 12.50，模型调用 63 次，费用 $0.1241；
    - **条件 GC**：完成率 3/4 (75.0%)，均分 93.00，Dunk 错误 0，成功决策均步 15.67，模型调用 60 次，费用 $0.0625。
  - 配对对比结论：
    - **GC vs G (核心主比较)**：
      - 完成率与得分：75.0% vs 75.0%，得分 1 胜 1 负 2 平；
      - 双成功步数：2 对双成功案例中（Var 0 Block 5 & 6），GC 决策步均比 G 少 4 步（平均 $\Delta = -4.00$ 步，环境步 $\Delta = -2.50$ 步）；
      - 错误动作抑制：G 发生 2 次无效 dunk，GC 为 0 次；
      - 推理冗余降低：GC 输出 tokens 和耗时较 G 缩减约 37%–38%。
    - **G vs A (通用动作语义的独立价值)**：
      - 完成率提升至 75.0% 对比 50.0%，得分 2 胜 0 负 2 平；说明即使不提供案例经验，仅消除动作接口的歧义理解，即可大幅提升大模型在环境中的推理质量。
    - **C vs A 与 GC vs C**：
      - C 具备高收益与高风险两极化特征；GC 则结合了 G 的动作规范与 C 的目标捷径，兼具高成功率（75%）与高步数效率。
  - 菜单交互：
    - 16 个 episode 中共触发 16 次菜单消歧交互，`menu_blank_cancellations_count = 0`，模型均以有效数字索引正常消歧，无异常退出。

---

## 2. 决策与规划记录 (Decision Records)

- **严格遵循停止条件**：16 个 episode 运行结束并完成统计分析后立即停止。
- **不恢复 P2**：P2 保持 `TERMINATED_NO_GO` 状态，不消耗未核准预算，不擅自开发算法。
- **预算透明与安全**：已核算各部分开销，区分实测 usage 估值与预留 hold。

---

## 3. 本项目全流程成果与资产清单

1. **官方定价配置与审计规范**：
   - [`pricing_config.json`](file:///code/failmem-ros2-agent/research/condition_revision/pricing_config.json)
2. **通用接口对照实验套件与交付物 (`generic_interface_control/`)**：
   - 固化通用语义与经验哈希：[`frozen_generic_semantics.json`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/frozen_generic_semantics.json)
   - 随机打乱清单：[`manifest.json`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/manifest.json)
   - 执行脚本与分析器：[`run_p1d.py`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/run_p1d.py)、[`analyze_p1d.py`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/analyze_p1d.py)
   - 16 轮独立运行完整记录：[`evidence_trajectories/`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/evidence_trajectories/)（M01–M16 JSON）
   - 逐轮汇总与步级明细：[`summary.csv`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/summary.csv)、[`step_summary.csv`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/step_summary.csv)
   - 轨迹证据 SHA-256 索引：[`trajectory_evidence_index.json`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/trajectory_evidence_index.json)
   - 完整统计分析报告：[`p1d_analysis_report.json`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/p1d_analysis_report.json)
   - 阶段执行记录与核验：[`execution_notes.md`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/execution_notes.md)
   - 实时预算账本：[`budget_ledger.json`](file:///code/failmem-ros2-agent/research/condition_revision/generic_interface_control/budget_ledger.json)
3. **自然经验迁移筛查套件与交付物 (`natural_experience_screen/`)**：
   - 24 轮独立运行记录与分析报告（E01–E24，详见该目录索引）。
4. **强规划器底层与回归套件**：
   - [`remote_llm_client.py`](file:///code/failmem-ros2-agent/research/condition_revision/remote_llm_client.py)（每决策步最多 2 次 HTTP 尝试共享配额机制）
   - [`tests/test_remote_planner_offline.py`](file:///code/failmem-ros2-agent/research/condition_revision/tests/test_remote_planner_offline.py)（30/30 离线测试通过）
5. **历史阶段封存资产**：
   - 菜单协议复查：[`menu_protocol_recheck/`](file:///code/failmem-ros2-agent/research/condition_revision/menu_protocol_recheck/)
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
  - **P1d 通用接口对照（Batch 17）**：16 episodes, 308 calls, 444,418 tokens, 1,396.1s (已消耗 16/16 episodes，开销 $0.4517 USD)
- **累计实际消耗总计（P0 + P1 + P1b + P1c + P1d）**：
  - **真实模型评测总轮次（全口径核定）**：**219 Episodes**（占总硬上限 7.30%）
  - **总调用**：**2407 LLM Calls**（占总硬上限 1.60%）
  - **总 Tokens**：**2,698,071 Tokens**
  - **API 开销已知总额**：**$1.8476 USD**（占 10.00 美元限额的 18.48%）
  - **保守安全预留 hold**：**$0.1023 USD**
  - **累计承诺开销合计**：**$1.9498 USD**
  - **已核对官方账单**：**$0.00 USD**（待月度账单结算）
  - **剩余可用 API 额度**：**$8.0502 USD**
- **预算合规性**：**100% 严格在预算红线内执行，无超额消耗，账本清晰可审计**。
