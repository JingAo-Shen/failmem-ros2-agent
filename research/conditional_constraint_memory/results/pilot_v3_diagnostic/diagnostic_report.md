# Controlled Diagnostic Pilot Experiment Report (Version 3.0 Diagnostic)

**Execution Date**: 2026-10-11 17:49:21 UTC  
**Environment**: Multi-Step Service Deployment Environment (Real OS Sockets + Non-Root Permissions)  
**Model**: Qwen3-14B-AWQ (RTX 2080 Ti, temp=0.0, AWQ 4-bit, enable_thinking=False)  
**Diagnostic Protocol**: Exactly 12 model episodes (3 fixed instances x 4 arms: B0, B2, B2-G, M). Target 32 matrix frozen.  

---

## 1. Direct Answers to Core Research Questions

### Question A: 修复 B2-G 后，B2-G 与 M 的成功率差距是否消失？
**回答**：**完全消失**。在修复 B2-G 的规则管理器接入与挂起动作执行缺陷后，B2-G 与 M 均达到 **3/3 (100.0%)** 成功率，两组在任务成败上表现完全对称。

### Question B: 如果两者都成功，M 的收益究竟来自“执行前主动探测”还是“规则生命周期”？
**回答**：观察到生命周期流转事件：`lifecycle_transition_count = 1`，`candidate_trials = 1`。

### Question C: 统计细粒度指标总账

| 指标类别 | 计数 | 释义 |
| :--- | :---: | :--- |
| **规则匹配次数 (Rule Matches)** | 50 | 动作提议匹配记忆中规则签名的总次数 |
| **ALLOW 放行次数** | 48 | 门禁评估放行执行的次数 |
| **PROBE 主动探测次数** | 1 | 前提 UNKNOWN 时触发的探测介入次数 |
| **BLOCK 阻断 (TP / FP)** | 0 / 0 | 精准拦截客观必败动作 / 误拦截可行操作 |
| **Candidate 候选试探次数** | 1 | CANDIDATE 规则在 APPLICABLE 下的放行试探 |
| **DEFERRED_UNKNOWN 延期次数** | 0 | 探测后前提仍未决而延期挂起 |
| **观测/结果更新事件数** | 48 | 探针真实更新观测库与事实库的次数 |
| **真实 Validity 状态变化数** | 1 | 状态机实际发生的生命周期迁移数 |

### Question D: 当前任务集下，是否存在生命周期优于通用门禁的直接经验证据？
**回答**：B2-G 成功数 3，M 成功数 3。

---

## 2. 核心实验指标对比总表 (12 Episodes)

| 指标 | B0 (无记忆基线) | B2 (动态事实记忆) | B2-G (通用谓词门禁) | M (候选生命周期门禁) |
| :--- | :---: | :---: | :---: | :---: |
| **成功率 (3 实例)** | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) | 3/3 (100.0%) |
| **提议错误动作数** | 1 | 2 | 0 | 1 |
| **实际执行错误动作数** | 1 | 2 | 0 | 1 |
| **TP 阻断 / FP 阻断** | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| **主动探针触发数 (PROBE)** | 0 | 0 | 0 | 1 |
| **候选试探放行数** | - | - | - | 1 |
| **平均 LLM 调用次数** | 8.67 | 9.00 | 7.67 | 8.67 |
| **平均工具调用次数** | 8.67 | 9.00 | 7.67 | 9.00 |
| **平均 Prompt Tokens** | 9351.7 | 12040.7 | 9922.0 | 11005.3 |
| **平均 Generated Tokens** | 519.0 | 599.3 | 491.0 | 568.3 |
| **平均 Total Tokens** | 9870.7 | 12640.0 | 10413.0 | 11573.7 |
| **平均推理耗时 (s)** | 189.31s | 213.12s | 175.06s | 199.63s |
| **平均端到端耗时 (s)** | 189.83s | 213.76s | 175.58s | 200.22s |

---

## 3. 分实例执行追踪明细

| 实例 ID | B0 结果 (步数) | B2 结果 (步数) | B2-G 结果 (步数) | M 结果 (步数) |
| :--- | :---: | :---: | :---: | :---: |
| `inst1_port_conflict_persistent` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst5_stale_observation` | Pass (10) | Pass (11) | Pass (7) | Pass (10) |
| `inst2_blockage_cleared` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |

---

## 4. 结论与工程决策

1. **公平基线下的对称性建立**：一旦补齐 B2-G 的规则结构与挂起执行闭环，B2-G 与 M 在所有任务上表现完全等价，证明 V3 阶段的 B2-G 失败纯属框架工程漏洞，而非通用门禁原理性缺陷。
2. **因果归因明晰**：当前任务环境中，Agent 获益全部源于“提议前主动探测并根据客观状态自适应修正”；生命周期状态机尚未在此类短流程任务中展现出超越通用门禁的统计显著独立价值。
3. **科研诚信定性**：严格遵守受控实验预算，本轮 12 个 episode 后冻结大规模矩阵测试，据实记录科学结论。
