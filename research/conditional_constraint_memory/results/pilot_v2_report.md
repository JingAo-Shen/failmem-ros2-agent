# Controlled Pilot Experiment Report (Version 2.0)

**Execution Date**: 2026-10-11 12:18:28 UTC  
**Environment**: Multi-Step Service Deployment Environment (Real Socket + Non-Root User Permissions)  
**Model**: Qwen3-14B-AWQ (RTX 2080 Ti, temp=0.0, AWQ 4-bit, enable_thinking=False)  
**Budget Adherence**: Exactly 36 model episodes executed (2 Smoke + 2 Source + 32 Target).  

---

## 1. Executive Summary & Audit Observations

### Key Empirical Observations:
- **Success Rates**: B0: 100.0%, B2: 100.0%, B2-G: 100.0%, M: 100.0%.
- **Executed Errors**: B0: 0, B2: 0, B2-G: 0, M: 0.
- **Gate Triggers**: Total TP Blocks across all groups: 0, Total FP Blocks: 0, Active UNKNOWN Probes: 0.
- **Gate Efficacy Assessment**: Because gate triggers did not occur in practice (0 blocks recorded), no claim of gate protection or false-positive reduction can be established from this pilot.

### Memory Treatment & Lifecycle Audit Metrics:

| Audit Metric | Value | Audit Meaning / Operational Definition |
| :--- | :---: | :--- |
| **source_failure_count** | 0 | Genuine failure traces produced during source task runs |
| **extracted_rule_count** | 0 | Constraint rules successfully extracted via deterministic parser |
| **target_initial_memory_count** | 0 | Non-empty memory items injected into target evaluation suite |
| **matched_rule_count** | 0 | Target action proposals matching active memory constraint signatures |
| **gate_opportunities** | 0 | Instances where preconditions were evaluated against proposed actions |
| **lifecycle_transition_count** | 0 | Transitions across CANDIDATE, SUPPORTED, CONTRADICTED, RETIRED |

> [!IMPORTANT]
> **空记忆审计特别声明**：`target_initial_memory_count = 0`。
> 因为源任务中 Agent 自发采取主动探测策略未产生自然执行失败，进入目标评测的记忆库保持为空。
> **实验处理未实际生效，不能评价记忆的独立贡献**。
> 当前实验结果属于空记忆条件下的多步部署基线验证，不能作为证伪或证实记忆机制独立价值的有效证据。

---

## 2. Comparative Metrics Table

| Metric | B0 (No Memory) | B2 (Dynamic Facts) | B2-G (Predicate Gate) | M (Lifecycle Gate) |
| :--- | :---: | :---: | :---: | :---: |
| **Success Rate (8 instances)** | 8/8 (100.0%) | 8/8 (100.0%) | 8/8 (100.0%) | 8/8 (100.0%) |
| **Proposed Error Actions** | 0 | 0 | 0 | 0 |
| **Executed Error Actions** | 0 | 0 | 0 | 0 |
| **TP Blocks / FP Blocks** | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| **Active Probes Triggered** | 0 | 0 | 0 | 0 |
| **Candidate Trials** | - | - | - | 0 |
| **Avg LLM Calls / Ep** | 7.50 | 7.50 | 7.50 | 7.50 |
| **Avg Tool Calls / Ep** | 7.50 | 7.50 | 7.50 | 7.50 |
| **Avg Prompt Tokens** | 6738.1 | 6741.9 | 6742.1 | 6787.8 |
| **Avg Generated Tokens** | 447.2 | 446.8 | 447.9 | 452.1 |
| **Avg Total Tokens** | 7185.4 | 7188.6 | 7190.0 | 7239.9 |
| **Avg Model Inference Time (s)** | 164.13s | 163.94s | 164.31s | 165.86s |
| **Avg End-to-End Latency (s)** | 164.51s | 164.32s | 164.69s | 166.24s |

---

## 3. Instance-by-Instance Breakdown

| Instance ID | B0 Success (Steps) | B2 Success (Steps) | B2-G Success (Steps) | M Success (Steps) |
| :--- | :---: | :---: | :---: | :---: |
| `inst1_port_conflict_persistent` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst2_blockage_cleared` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst3_permission_fallback` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst4_irrelevant_change` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst5_stale_observation` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst6_counterexample_feasibility` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst7_midepisode_port_clash` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst8_permission_and_port_composition` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |

---

## 4. Formal Research Conclusion

- **科学定性**: **空记忆条件下的多步部署基线验证；记忆方法效果证据不足**
- **客观事实与归因**: 全量实测数据表明：四组均8/8成功、零执行错误、平均7.50次调用。但因源任务未产生执行报错，目标记忆库为空，实验处理未实际生效，不能评价记忆的独立贡献。当前数据证明了多步任务部署基线的可运行性与规划稳健性，但尚未构成对约束记忆机制有效性或冗余性的充分检验证据。
