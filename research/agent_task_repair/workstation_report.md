# FailMem Stage 3: 执行能力公平化与程序记忆贡献判别研究报告 (自动审计重建版)

**评估环境**: 真实模型推理、模拟工作站评测 (`Qwen/Qwen3-14B-AWQ Direct`, 单卡 NVIDIA GeForce RTX 2080 Ti 22GB, 显存占用 11.12 GB, $T=0.0$ 确定性解码)  
**实验定位**: 开发阶段先导实验（严格消融与机制归因，自动审计生成）  
**运行统计**: 共 44 次真实推理运行（4 次 Phase A 探索 + 40 次 Phase B 正式评测）。

---

## 1. 核心判别与归因结论 (Audited Scientific Findings)

依据 44 次真实推理记录的独立统计，回答核心研究问题：
**D 的收益究竟来自历史程序复用，还是仅来自省略逐步 LLM 调用（多步执行机制）？**

1. **全样本总调用量相同**: 在全部 8 个目标任务（含失败与超时）的全量统计中，**Group D 与 Group B2-plan 的 LLM 调用总数完全相同，均为 36 次**。
2. **共同成功子集 (6 任务) 呈现有限微弱优势**: 在双方均成功的 6 个任务子集中，Group D 消耗 **17 次 LLM 调用**（平均 2.83 次/任务），Group B2-plan 消耗 **19 次 LLM 调用**（平均 3.17 次/任务），D 仅比 B2-plan 净减少 **2 次调用**（$-10.5\% $）。
3. **多步执行机制是主要压缩来源**: 从单步规划（B2-step: 67 次调用）到多步执行（B2-plan: 36 次调用），LLM 调用减少了 **31 次（$-46.3\% $）**；而在多步基线之上引入程序记忆（D: 36 次），全量调用无进一步减少（0%）。这证明此前观察到的调用大幅下降主要源于**多步执行机制**。
4. **任务成功率未展现优势**: Group D 成功率为 **6/8 (75.0%)**，低于 B2-step (**7/8, 87.5%**) 与 B2-plan (**7/8, 87.5%**)。在 Target C2 中，因局部程序绑定与未解决的跨子系统依赖导致超时退出。
5. **因果条件守卫显著降低盲目重放报错**: 对比盲目重放（Group Replay, 12 次工具报错），Group D 仅发生 7 次工具报错，Prompt Tokens 从 5,689.0 压缩至 3,145.0。

---

## 2. Phase A 源任务与因果干预编译器真实统计

| 源任务 ID | 尝试轮次 | 结果 | 步数 | LLM 调用 | 耗时 (s) | 备注 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `src_pneumatic` | Attempt 1/2 | **SUCCESS** | 9 | 9 | 192.1 | 成功完成 |
| `src_sensor_actuator` | Attempt 1/2 | **SUCCESS** | 8 | 8 | 174.65 | 成功完成 |
| `src_dual_subsystems` | Attempt 1/2 | **FAILED** | 12 | 12 | 323.87 | 未在预算内恢复 |
| `src_dual_subsystems` | Attempt 2/2 | **FAILED** | 12 | 12 | 323.69 | 未在预算内恢复 |

**源任务成功率统计**: 3 个源任务中，`src_pneumatic` (1/1 成功) 与 `src_sensor_actuator` (1/1 成功) 完成诊断修复；`src_dual_subsystems` 经历 2 轮尝试均因预算/顺序未完成（0/2）。**真实来源任务成功率为 2/3 (66.7%)**。

---

## 3. 全量样本与子集聚合指标审计表

### 3.1 全样本统计 (Full Sample, 8 Target Tasks per Group)

| 评估组别 | 任务成功率 | 总 LLM 调用 | 总执行步数 | 总耗时 (s) | 总工具报错 | 成功任务平均 LLM | 成功任务平均耗时 (s) | 成功任务平均 Prompt Tok |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Group_B2_step** | 7/8 (87.5%) | 67 | 67 | 1391.31 | 7 | 7.71 | 155.85 | 8728.4 |
| **Group_B2_plan** | 7/8 (87.5%) | 36 | 71 | 1146.16 | 8 | 3.86 | 120.64 | 4413.7 |
| **Group_B1_plan** | 6/8 (75.0%) | 43 | 69 | 1330.03 | 15 | 4.17 | 117.17 | 9021.8 |
| **Group_Replay** | 6/8 (75.0%) | 35 | 72 | 1069.41 | 12 | 2.67 | 72.43 | 5689.0 |
| **Group_D_Procedural_Memory** | 6/8 (75.0%) | 36 | 69 | 1170.05 | 7 | 2.83 | 89.34 | 3145.0 |

### 3.2 共同成功子集统计 (Mutually Successful Subset, 6 Tasks: A1, A2, B1, C1, D1, D2)

| 评估组别 | 子集任务数 | 总 LLM 调用 | 平均 LLM 调用 | 总执行步数 | 平均执行步数 | 总耗时 (s) | 平均耗时 (s) | 平均 Prompt Tok | 工具报错数 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Group_B2_step** | 6 | 44 | 7.33 | 44 | 7.33 | 904.77 | 150.79 | 8266.5 | 3 |
| **Group_B2_plan** | 6 | 19 | 3.17 | 46 | 7.67 | 595.66 | 99.28 | 3556.8 | 4 |
| **Group_B1_plan** | 6 | 25 | 4.17 | 44 | 7.33 | 703.05 | 117.17 | 9021.8 | 5 |
| **Group_Replay** | 6 | 16 | 2.67 | 45 | 7.50 | 434.57 | 72.43 | 5689.0 | 2 |
| **Group_D_Procedural_Memory** | 6 | 17 | 2.83 | 46 | 7.67 | 536.03 | 89.34 | 3145.0 | 3 |

### 3.3 失败任务成本明细 (Failed Tasks Cost Breakdown)

| 失败任务 ID | 组别 | 结果状态 | LLM 调用 | 执行步数 | 耗时 (s) | 工具报错 | 终止原因 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `target_B2_power_and_sensor` | Group_B2_step | **FAIL** | 13 | 13 | 300.39 | 2 | `TIME_LIMIT_EXCEEDED` |
| `target_B2_power_and_sensor` | Group_B2_plan | **FAIL** | 9 | 11 | 301.65 | 2 | `TIME_LIMIT_EXCEEDED` |
| `target_B2_power_and_sensor` | Group_B1_plan | **FAIL** | 9 | 11 | 322.33 | 3 | `TIME_LIMIT_EXCEEDED` |
| `target_B2_power_and_sensor` | Group_Replay | **FAIL** | 9 | 12 | 310.56 | 3 | `TIME_LIMIT_EXCEEDED` |
| `target_B2_power_and_sensor` | Group_D_Procedural_Memory | **FAIL** | 9 | 11 | 302.79 | 2 | `TIME_LIMIT_EXCEEDED` |
| `target_C2_sensor_power_order` | Group_B1_plan | **FAIL** | 9 | 14 | 304.65 | 7 | `TIME_LIMIT_EXCEEDED` |
| `target_C2_sensor_power_order` | Group_Replay | **FAIL** | 10 | 15 | 324.28 | 7 | `TIME_LIMIT_EXCEEDED` |
| `target_C2_sensor_power_order` | Group_D_Procedural_Memory | **FAIL** | 10 | 12 | 331.23 | 2 | `TIME_LIMIT_EXCEEDED` |

---

## 4. Phase B 40 单元分任务详细审计表

| 任务 ID | 迁移类别 | Group B2_step | Group B2_plan | Group B1_plan | Group Replay | Group D |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `target_A1_pneumatic_leak` | Class_A_same_mechanism | PASS (8s/8l/174s) | PASS (11s/6l/168s) | PASS (8s/5l/136s) | PASS (8s/2l/64s) | PASS (11s/6l/177s) |
| `target_A2_gripper_misalign` | Class_A_same_mechanism | PASS (8s/8l/163s) | PASS (9s/4l/134s) | PASS (7s/3l/94s) | PASS (8s/3l/83s) | PASS (9s/4l/132s) |
| `target_B1_composed_faults` | Class_B_combination | PASS (11s/11l/237s) | PASS (10s/3l/112s) | PASS (11s/6l/172s) | PASS (12s/3l/81s) | PASS (10s/2l/71s) |
| `target_B2_power_and_sensor` | Class_B_combination | FAIL (13s/13l/300s) | FAIL (11s/9l/302s) | FAIL (11s/9l/322s) | FAIL (12s/9l/311s) | FAIL (11s/9l/303s) |
| `target_C1_gripper_with_load` | Class_C_condition_changed | PASS (10s/10l/211s) | PASS (9s/3l/99s) | PASS (11s/6l/176s) | PASS (10s/3l/81s) | PASS (9s/2l/73s) |
| `target_C2_sensor_power_order` | Class_C_condition_changed | PASS (10s/10l/186s) | PASS (14s/8l/249s) | FAIL (14s/9l/305s) | FAIL (15s/10l/324s) | FAIL (12s/10l/331s) |
| `target_D1_clean_startup` | Class_D_irrelevant | PASS (3s/3l/51s) | PASS (3s/2l/47s) | PASS (3s/2l/47s) | PASS (3s/2l/47s) | PASS (3s/2l/47s) |
| `target_D2_routine_maintenance` | Class_D_irrelevant | PASS (4s/4l/68s) | PASS (4s/1l/36s) | PASS (4s/3l/78s) | PASS (4s/3l/78s) | PASS (4s/1l/36s) |

---

## 5. 计数器与实现缺陷审计记录

1. **Replay 记忆执行计数器缺陷**: 原 runner 中 `memory_action_executed_count` 仅在 `action_source == procedural_memory` 时累加，遗漏了 `action_source == naive_replay`，导致 JSON 中 Replay 该计数为 0。已审计查明原因，并在重构中统一修正。
2. **首动作未经过统一公共校验**: 原 runner 在 LLM 生成多步计划时，将第 1 个动作直接送入 `env.step`，而将后续动作放入队列并在出队时校验。这导致首动作前置违规时无法被拦截。已在下一节执行入口重构中统一。
3. **拦截事件未反馈至 Agent Prompt**: 原 runner 中 `PRECONDITION_INTERLOCK_ABORT` 仅记录在 audit_events 中，下一次 LLM 提示词无法获知拦截原因，导致模型重复生成非法动作。

