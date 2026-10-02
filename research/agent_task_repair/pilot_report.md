# FailMem Stage 2: 机制修复与先导有效性评估报告

**研究主题**: 面向长程机器人任务的条件化失败记忆与计划修复 (*Condition-Aware Failure Memory for Long-Horizon Robotic Task Repair*)  
**当前状态**: **机制修复与小规模开发验证完成；暂停扩大实验，先修复有效性**  
**分支**: `research/agent-task-repair-pilot`  
**基线提交**: `7a64c50d92354f6605e73f0eba4be8eb68ec0f80`  
**评测设备**: 本地 GPU NVIDIA GeForce RTX 2080 Ti (22.5 GB VRAM), Qwen2.5-Coder-7B-Instruct  

---

## 1. 历史探索性运行缺陷审计 (Historical Exploratory Run Audit)

此前提交包含 75 单元先导运行数据（`research/agent_task_repair/results/pilot_raw_results.json`）。经严格审计，该批次存在以下**设计缺陷**，**不能作为支持研究假设的证据，亦不能据此进入 Gazebo 阶段**：

1. **信息泄漏 (Information Leakage)**: 
   - 任务提示中包含未通过工具获取的隐藏状态说明（例如在 Cat 2 提示中写有 *"Obstacle has been removed"*，在 Cat 3 中写有 *"(blocked by missing badge)"*）。公开任务要求与环境状态未严格隔离。
2. **伪独立样本 (Pseudo-Independent Duplicates)**: 
   - 各类别的 5 条序列实质为同一任务配置的简单 ID 复制，去除 ID 后配置完全重复，缺乏真实环境多样性。
3. **启发式猜测与宽松解析 (Heuristic Guessing in Planner)**: 
   - 在 JSON 解析失败时，Planner 内部包含提取文本猜测动作（`"navigate"` 猜走 `"Corridor_South"`、`"pickup"` 猜 `"pkg_docs"`）的兜底逻辑，掩盖了模型真实的格式遵循失败。
4. **基线对照不公平 (Unfair Baseline Advantage in Method F)**: 
   - 方法 F 的失败记录中硬编码了专属修复动作（如 `"走南侧"`、`"去 Office_A 取证件"`），而其他基线未获得对等的结构化重规划支持。
5. **TTL 口径与序列长度不匹配 (TTL Calibration Discrepancy)**: 
   - 协议记载 TTL=2，代码实际使用 TTL=1。但在只有 2 个任务的序列中，`age <= 1` 使得 Task 2 永远不会触发过期，未有效检验遗忘机制。
6. **评分统计与报告夸大 (Reporting & Scoring Flaws)**: 
   - 错误回避指标曾依赖 `decision_summary` 中的 `"avoid"`、`"blocked"` 关键词匹配，而非基于物理动作和可行路径。
   - 报告中存在写死的 `Supported`、`PASS` 和未经实测支持的叙述（如非代码实体的 `Package_Hazard` 等）。
   - `scorer.py` 曾存在布尔统计错误，导致 `eval_success_rate` 误报为 100%。

> **历史数据保留说明**: 历史 75 单元原始结果保留在 `pilot_raw_results.json`，标记为 **“有设计缺陷的探索性运行 (Exploratory run with design defects)”**，供可追溯审计。

---

## 2. 机制修复与架构标准化清单

本轮全面完成了以下 8 项核心有效性修复：

| 修复模块 | 原始缺陷 | 修复后机制 | 验证状态 |
| :--- | :--- | :--- | :---: |
| **任务指令与可见性** | 提示包含隐藏状态提示 ("Obstacle has been removed") | 严格清洗提示，仅提供公开目标；环境状态必须通过 `observe`/`query_status` 获取 | $\checkmark$ 已修复 |
| **Agent 解析与容错** | 解析失败后自动猜测导航目标与包裹 | 严格 Tool Schema 校验，提供单次带错重试机会；若仍失败记为 `PARSE_ERROR` 动作并扣除预算 | $\checkmark$ 已修复 |
| **决策依据记录** | 要求长篇思维链 | 统一采用可核查的简短 `decision_summary` 与结构化参数 | $\checkmark$ 已修复 |
| **记忆检索与匹配** | 仅用当前位置查询；条件匹配二值化 | 多属性查询上下文；实现 `MATCH` / `MISMATCH` / `UNKNOWN` 三值逻辑，`UNKNOWN` 明确标记待验证 | $\checkmark$ 已修复 |
| **基线公平性** | 方法 F 专属硬编码绕行建议 | 移除所有专属硬编码建议，各组共享统一工具 Schema 与状态摘要 | $\checkmark$ 已修复 |
| **事件追溯与修复验证**| 缺乏跨任务事件追踪 | 引入全局唯一 `event_id` (如 `evt_t0_s02_navigate`)；修复链必须包含失败、修复与成功完整证据 | $\checkmark$ 已修复 |
| **TTL 机制与序列设计** | 2 任务序列无法使 TTL=1 过期 | 重新设计 3 任务开发序列，Task 3 中 $T=1$ 确定触发过期 ($2 > 1$) | $\checkmark$ 已修复 |
| **指标与电量核算** | 错误回避基于字符串，电量用 100-final | 回避基于物理路径与门禁真值判定；电量按动作累计核算；报告 LLM 调用次数与分类违规 | $\checkmark$ 已修复 |

---

## 3. 开发集机制验证结果 (15 单元开发实验)

针对 3 组重新设计的 3 任务开发序列（`dev_cat1_valid`, `dev_cat2_stale`, `dev_cat3_inapplicable`，共 45 个任务），使用本地 GPU 加载的 `Qwen2.5-Coder-7B-Instruct` 进行了 15 个方法-序列单元（共 45 个任务）的机制运行验证。

### 3.1 从逐任务记录严格重算指标（保留分子分母）
- **B0 (无记忆)**: 任务成功率 **4/9 (44.4%)**，后续评估任务成功率 **4/6 (66.7%)**，硬违规率 1/9 (11.1%)
- **B1 (纯文本记忆)**: 任务成功率 **0/9 (0.0%)**，后续评估任务成功率 **0/6 (0.0%)**，硬违规率 1/9 (11.1%)
- **B2 (静态条件记忆)**: 任务成功率 **1/9 (11.1%)**，后续评估任务成功率 **1/6 (16.7%)**，硬违规率 1/9 (11.1%)
- **B3 (衰减记忆)**: 任务成功率 **2/9 (22.2%)**，后续评估任务成功率 **2/6 (33.3%)**，硬违规率 3/9 (33.3%)
- **F (条件感知主动失效)**: 任务成功率 **0/9 (0.0%)**，后续评估任务成功率 **0/6 (0.0%)**，硬违规率 1/9 (11.1%)

### 3.2 开发单元全局指标汇总表
| 方法 | 任务成功率 ($SR_{\text{task}}$) | 完整序列成功率 ($SR_{\text{seq}}$) | 后续评估成功率 ($SR_{\text{eval}}$) | 硬违规率 ($VR$) | 重复失败 ($N_{\text{rep}}$) | 不必要绕路 ($N_{\text{detour}}$) | 解析错误 ($N_{\text{parse}}$) | 平均电量消耗 | 总 LLM 调用 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **B0** | 4/9 (44.4%) | 0/3 (0.0%) | 4/6 (66.7%) | 1/9 (11.1%) | 28 | 9 | 0 | 179.0 | 128 |
| **B1** | 0/9 (0.0%) | 0/3 (0.0%) | 0/6 (0.0%) | 1/9 (11.1%) | 26 | 2 | 3 | 105.0 | 91 |
| **B2** | 1/9 (11.1%) | 0/3 (0.0%) | 1/6 (16.7%) | 1/9 (11.1%) | 27 | 8 | 4 | 155.3 | 130 |
| **B3** | 2/9 (22.2%) | 0/3 (0.0%) | 2/6 (33.3%) | 3/9 (33.3%) | 22 | 10 | 0 | 174.7 | 120 |
| **F** | 0/9 (0.0%) | 0/3 (0.0%) | 0/6 (0.0%) | 1/9 (11.1%) | 28 | 8 | 4 | 164.3 | 139 |

---

## 4. 真实执行案例与根因诊断 (Grounded Trace Diagnosis)

从真实执行日志分析，基础模型在去除提示泄漏与硬编码作弊后，暴露出以下基础执行薄弱点：

1. **未取件先出发 (Premature Departure without Pickup)**:
   - 案例引用: `dev_cat3_inapplicable / F / dev_c3_t2` (Step 1–4)
   - 行为: 机器人从 `Lobby` 出发直奔 `Corridor_North`，未在 `Lobby` 执行 `pickup`。到达后呼叫 `pickup` 获得 `WRONG_LOCATION`，到达 `Office_A` 呼叫 `deliver` 获得 `NOT_HOLDING_PACKAGE`。
2. **多步拓扑迷航 (Topological Navigation Failure)**:
   - 案例引用: `dev_cat3_inapplicable / F / dev_c3_t3` (Step 18–20)
   - 行为: 机器人在 `Lobby` 试图直接 `navigate(target_zone='Office_B')`（非直连邻居），触发非法动作拒绝。
3. **死循环与重复失败 (Consecutive Failure Dead-Loop Abort)**:
   - 案例引用: `dev_cat3_inapplicable / F / dev_c3_t1` (Step 15–17)
   - 行为: 机器人在 `Corridor_North` 连续 3 次调用 `acquire_credential('security_badge')`（证件实际在 `Office_A`），触发执行器死循环保护强制终止。

---

## 5. 阶段准入判定与 Go/No-Go 评估

| 准入维度 | 判定准则 | 当前实测状态 | 判定结论 |
| :--- | :--- | :--- | :---: |
| **提示与信息隔离** | 任务指令无隐藏状态泄漏，公开目标与环境观测完全分离 | 3 组开发序列通过无泄漏检查 | $\checkmark$ 达标 |
| **解析与接口健壮性** | 无启发式硬编码猜测，严格 Schema 校验与单次重试 | 15 单元中解析错误均规范归类并记录 | $\checkmark$ 达标 |
| **三值逻辑条件匹配** | 条件评估严格输出 `MATCH`, `MISMATCH`, `UNKNOWN` | 单元测试通过，待验证不误判为确定适用 | $\checkmark$ 达标 |
| **主动失效与 TTL 触发** | 观测正确失效旧记忆，TTL 在多任务序列中确定生效 | 开发实验与测试均触发对应事件 | $\checkmark$ 达标 |
| **研究假设验证** | 在独立未见的大规模评测集上建立显著优势 | **尚未在新独立评测集上运行正式评测** | **未验证 (Unverified)** |
| **Gazebo / 阶段三准入** | 先导有效性确立且方法优势具备统计依据 | **暂未满足正式结论准入条件** | **未达标 (NOT READY)** |

### **当前官方决策**: **暂停扩大实验，先修复有效性 (PAUSE EXPANSION / REPAIRING AGENT EXECUTION CAPABILITY)**
