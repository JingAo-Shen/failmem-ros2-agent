# FailMem 项目研究证据总表 (Research Evidence Ledger)

> **文档定位与科研诚信声明**：
> 本表系统梳理 FailMem 项目全生命周期（Stages 1–11）中各阶段的研究假设、代码核验程度、数据凭据、实际发现、实现缺陷与混杂因素。
> 明确划分**已验证的工程闭环成果**、**有限范围的研究观察**与**尚未验证的研究假设**，坚决杜绝过度推论与概念泛化，为后续研究决策提供唯一事实底座。

---

## 一、三层成果与认识边界划分

```
┌────────────────────────────────────────────────────────────────────────┐
│ A. 已验证的工程闭环成果 (Engineering Accomplishments)                  │
│ - 通用局部计划执行器 (CommonLocalPlanExecutor, 统一队列与分块游标)      │
│ - 约束生命周期跟踪器 (ConstraintTracker, 严格基于观测解除)             │
│ - 统一预算与防护网 (32 LLM / 40 Tool / 1800s 超时 / 重复拦截截断)      │
│ - 逐次调用完整审计日志 (llm_call_records 与严格 Token 逐项累加断言)    │
│ - 状态差异哈希与死循环自旋检测                                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 支撑
┌───────────────────────────────────▼────────────────────────────────────┐
│ B. 有限范围内的研究观察 (Bounded Empirical Observations)               │
│ - 多步批处理执行相比逐步单步调用，降低了交互延迟与通信开销             │
│ - 在部分任务上，复用历史验证片段能够减少 LLM 调用次数                  │
│ - 32 次开发诊断中，无人工流程的两组均为 7/8                            │
│ - FocusedRepair 没有提高该条件下的成功率，总调用由 94 增至 107         │
│ - ExpertRecipe + FocusedRepair 在这 8 个开发任务上表现最好             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 边界
┌───────────────────────────────────▼────────────────────────────────────┐
│ C. 尚未验证的研究假设 (Unverified / Unsupported Hypotheses)            │
│ - 程序性记忆相比通用规划或纯回放具备稳定的跨任务泛化优势 (未建立)       │
│ - 条件暂缓与状态重估机制的普遍必要性 (未建立独立收益)                  │
│ - 跨不同工具域、不同模型与真实物理环境的自主恢复能力 (完全未测试)       │
│ - SOP 是智能体可靠运行的普遍必要条件 (过度推论，已废弃)                │
│ - 大模型长程多步推理存在固有“崩溃点” (过度推论，已废弃)                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 二、项目阶段全景证据审计账本

| 阶段 | 核心研究问题 | 代码版本与可核验程度 | 核心数据文件与规模 | 对照组设置 | 实际实验发现 | 实现缺陷或实验混杂 | 可保留结论 | 不支持的结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage 1–4**<br>(先导探索与环境因果编译) | 复合故障环境下，能否从先验执行轨迹中编译因果事实并实现任务恢复？ | Commit `567e8fb` / `a03f895`<br>早期工作区历史提交已核验存在。 | `results/pilot_75_results.json` (75 runs)<br>`results/recompiled_structured_facts.json`<br>`results/recompiled_procedural_memories.json` | 探索性基线、单步规划、事实注入 | 编译器提取出 22 个转移与 13 个带 ID 的负向事实；注入结构化事实后多步规划有所改善。 | 编译器依赖先验人工模板；部分事实与评测任务场景重叠；环境错误反馈较直接。 | 结构化事实库能对工件状态与动作前后置条件提供格式化约束依据。 | ❌ 不能声称智能体自主无监督发现因果律；不能声称形成了通用因果世界模型。 |
| **Stage 5–8**<br>(程序性记忆门禁与消融评测) | D-gated 程序性记忆能否在跨任务泛化中减少负迁移并超越回放？ | Commit `d2b12d8`<br>归档于 `results/archive_stages_5_8/`，数据文件完整可复核。 | `results/dev_32_diagnosis_results.json` (32 runs)<br>`results/heldout_96_diagnosis_results.json` (96 runs)<br>`results/ablation_32_diagnosis_results.json` (32 runs) | Group_B2_plan<br>Group_B1_plan<br>Group_Replay<br>Group_D_gated<br>Group_D_no_filter<br>Group_D_no_reeval | 主评测中四组成功率持平 (16/24, 66.7%)；D-gated 产生 0 次记忆失效，但平均 LLM 调用 (13.21) 高于 Replay (12.54)。 | Goal 字符串保留了部分序列提示；记忆条目来源于同源场景；Replay 暴力回放反而调用更少。 | 前置条件门禁能拦截不适用动作，消除执行器内部记忆失效计数；多步规划优于单步。 | ❌ 当前实验未建立该实现相对强基线的稳定独立优势；不支持“程序性记忆赋予了本质规划跃迁”。 |
| **Stage 9**<br>(统计分析与先导诊断报告) | 程序性记忆收益源自何处？失败任务的根因是什么？ | Commit `fba196f`<br>诊断报告与原始数据存档。 | `workstation_report.md`<br>`results/failure_taxonomy.json` | 配对胜平负统计、置信区间分析 | 共同成功任务上，记忆复用主要收益是节省 LLM 调用通信开销；失败主要集中于电源继电器死锁。 | 分析中忽视了电源 `reset` 工具语义与物理状态的背离；过早假定门禁具有通用泛化性。 | 程序性记忆的核心学术价值在于推理性卸载 (Reasoning Offloading)，而非符号发现。 | ❌ 不支持“跨任务零样本自适应成功”的宣称。 |
| **Stage 10**<br>(重复拦截诊断与修复规划消融) | 约束修复规划与决策拦截能否解除死锁？D-gated 表现如何？ | Commit `a3f4d1f`<br>提交已核验存在；工作区快照标记为“实际运行代码快照无法完整核验”。 | `results/batch1_diagnostic_results.json` (24 runs)<br>`results/batch2_ablation_results.json` (24 runs)<br>`results/diagnostic_48_report.md` | Batch 1 (修复规划开启) vs Batch 2 (修复规划关闭)；涵盖 B2_plan, Replay, D_gated | Batch 1 三组全员 8/8 (100%)；Batch 2 成功率跌落至 50.0%~62.5%；D-gated 相比 Replay 仍无优势。 | **重大混杂**：Batch 1 公共工具说明与修复规划均人工注入了复合维修序列（两处注入），8/8 不能归因于自主修复。 | 三阶重复拦截门禁（第 3 次重复终止）在死锁消融任务中于 5~9 次调用处提前截断（见 `calculate_loop_interception_savings.py` 与 `loop_interception_audit.json`，相较 32 次预算上限减少了 71.88%~84.38% 的空转调用），属于稳健工程闭环。 | ❌ 不能把 8/8 归因于自主约束修复；当前实验未建立该实现相对强基线的稳定独立优势。 |
| **Stage 11**<br>(名义 2×2 提示配置比较) | 去除人工流程后，自主约束修复能否独立恢复任务？各自贡献多少？ | Commit `64f2844` / `7e1dbb3`<br>17 项离线门禁全部可重复验证，数据完整。 | `results/attribution_2x2_results.json` (32 runs)<br>`results/attribution_32_report.md`<br>`results/prompt_information_audit.json` (375 条调用全量审计) | 纯规划组 B2-plan，4 种条件：<br>1. NoRecipe_Std<br>2. NoRecipe_Foc<br>3. ExpertRecipe_Std<br>4. ExpertRecipe_Foc | 无流程两组均为 7/8；FocusedRepair 未提升该条件下成功率 (调用由 94 增至 107)；Expert+Focused 表现最好 (8/8, 67c)。 | **重大混杂 (Audit 证实)**：_plan_standard_replan 注入了事实转移与负向事实，_plan_constraint_repair 未使用事实但注入了目标协议，信息内容混杂。 | 在无人工流程下，模型凭借基础语义与动态谓词反馈具备一定局部试错恢复能力 (7/8)。 | ❌ 不能称为严格因果归因；不支持“SOP 是唯一道路”；当前实验未建立该实现相对强基线的稳定独立优势。 |

---

## 三、关键历史报告纠正与追溯索引

为维护科研证据链路完整性，历史报告原始数据全文保留，但必须阅读对应的后续纠正与审计：

1. **`diagnostic_48_report.md` (Stage 10)**:
   - [跳转该报告](./diagnostic_48_report.md)
   - **核心纠正**：已在报告顶部增加显式警示。Batch 1 属于“带人工流程提示的开发诊断”，严禁将 8/8 归因于自主修复；Token 数据已按 `llm_call_records` 重新校验修复；重复拦截在 10 次死锁中于 5~9 次调用处提前截断，避免空转至 32 次上限（详见 `calculate_loop_interception_savings.py`）。
2. **`attribution_32_report.md` (Stage 11)**:
   - [跳转该报告](./attribution_32_report.md)
   - **核心纠正**：性质重标定为“名义 2×2 提示配置比较，存在信息内容混杂”。删除了所有如“崩溃点”、“唯一道路”等非受控夸大推论，统一标定为“当前实验未建立该实现相对强基线的稳定独立优势”，结论严格收敛于当前 5 项受控结论。
3. **`prompt_information_audit.json` (Stage 11 全量审计产物)**:
   - [跳转审计报告](./prompt_information_audit.json)
   - **核心事实**：遍历全部 32 次运行共 375 次 LLM 调用记录（包含 `run_id`, `task_id`, `call_index`），证实了重规划触发时的非对称事实与协议注入。

---

## 四、历史实验与方法版本全面冻结确认

- **冻结对象清单**：
  - `Group_D_current`、`Group_D_gated` (条件门控程序记忆及其变体)；
  - `Group_Replay` (基于历史分段的动作序列回放)；
  - `FocusedRepair` (现有的局部约束修复规划器)；
  - 当前 5 子系统 Workstation 模拟环境及其全部评测任务。
- **任务数据性质重声明**：
  - **所有已查看的 Workstation 任务实例**（包括 Stage 5 的 8 个开发任务、Stage 7 的 24 个 Heldout 任务及 Stage 8 的 16 个消融任务），在历次诊断与代码调试中均已被研究人员直接或间接检查分析，**全部定性为“开发/探索数据”**，严禁作为学术结论的无偏泛化测试集。
- **边界底线与冻结范围明确**：
  - 冻结的是旧实验阶段（Stages 1–11）、旧方法版本及旧 Workstation 模拟环境；
  - 停止在旧 Workstation 代码库上通过微调数值或改写 Prompt 制造新实验；
  - 不恢复 D-gated 开发，不将主线包装为 SOP 状态机；
  - **本冻结不禁止在代码仓库中增加全新的独立研究目录以开展正规的机制探索**。
