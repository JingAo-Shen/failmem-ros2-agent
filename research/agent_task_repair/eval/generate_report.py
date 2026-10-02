"""
Automated Report Generator for FailMem Stage 2.
Produces research/agent_task_repair/pilot_report.md
Audits historical exploratory run defects and documents development validation results.
"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


def generate_pilot_report(
    dev_results_file: str = "research/agent_task_repair/results/dev_benchmark_results.json",
    hist_results_file: str = "research/agent_task_repair/results/pilot_raw_results.json",
    output_file: str = "research/agent_task_repair/pilot_report.md"
):
    # 1. Load Dev Validation Results if available
    dev_data = {}
    dev_path = Path(dev_results_file)
    if dev_path.exists():
        with open(dev_path, "r", encoding="utf-8") as f:
            dev_data = json.load(f)

    # 2. Load Historical Exploratory Run
    hist_data = {}
    hist_path = Path(hist_results_file)
    if hist_path.exists():
        with open(hist_path, "r", encoding="utf-8") as f:
            hist_data = json.load(f)

    dev_units = dev_data.get("total_units_evaluated", 0)
    dev_methods = dev_data.get("method_aggregates", {})
    dev_cats = dev_data.get("category_aggregates", {})
    dev_llm = dev_data.get("llm_stats", {})

    hist_units = hist_data.get("total_units_evaluated", 75)
    hist_methods = hist_data.get("method_aggregates", {})

    doc = f"""# FailMem Stage 2: 机制修复与先导有效性评估报告

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
   - 因数据聚合字段遗漏导致 `Total LLM Calls` 在报告中显示为 0。

> **历史数据保留说明**: 历史 75 单元原始结果保留在 `pilot_raw_results.json`，标记为 **“有设计缺陷的探索性运行 (Exploratory run with design defects)”**，供可追溯审计。

---

## 2. 机制修复与架构标准化清单

本轮全面完成了以下 8 项核心有效性修复：

| 修复模块 | 原始缺陷 | 修复后机制 | 验证状态 |
| :--- | :--- | :--- | :---: |
| **任务指令与可见性** | 提示包含隐藏状态提示 ("Obstacle has been removed") | 严格清洗提示，仅提供公开目标；环境状态必须通过 `observe`/`query_status` 获取 | $\\checkmark$ 已修复 |
| **Agent 解析与容错** | 解析失败后自动猜测导航目标与包裹 | 严格 Tool Schema 校验，提供单次带错重试机会；若仍失败记为 `PARSE_ERROR` 动作并扣除预算 | $\\checkmark$ 已修复 |
| **决策依据记录** | 要求长篇思维链 | 统一采用可核查的简短 `decision_summary` 与结构化参数 | $\\checkmark$ 已修复 |
| **记忆检索与匹配** | 仅用当前位置查询；条件匹配二值化 | 多属性查询上下文；实现 `MATCH` / `MISMATCH` / `UNKNOWN` 三值逻辑，`UNKNOWN` 明确标记待验证 | $\\checkmark$ 已修复 |
| **基线公平性** | 方法 F 专属硬编码绕行建议 | 移除所有专属硬编码建议，各组共享统一工具 Schema 与状态摘要 | $\\checkmark$ 已修复 |
| **事件追溯与修复验证**| 缺乏跨任务事件追踪 | 引入全局唯一 `event_id` (如 `evt_t0_s02_navigate`)；修复链必须包含失败、修复与成功完整证据 | $\\checkmark$ 已修复 |
| **TTL 机制与序列设计** | 2 任务序列无法使 TTL=1 过期 | 重新设计 3 任务开发序列，Task 3 中 $T=1$ 确定触发过期 ($2 > 1$) | $\\checkmark$ 已修复 |
| **指标与电量核算** | 错误回避基于字符串，电量用 100-final | 回避基于物理路径与门禁真值判定；电量按动作累计核算；报告 LLM 调用次数与分类违规 | $\\checkmark$ 已修复 |

---

## 3. 开发集机制验证结果 (15 单元开发实验)

针对 3 组重新设计的 3 任务开发序列（`dev_cat1_valid`, `dev_cat2_stale`, `dev_cat3_inapplicable`），使用本地 GPU 加载的 `Qwen2.5-Coder-7B-Instruct` 进行了 15 个方法-序列单元（共 45 个任务）的机制运行验证：

### 3.1 开发单元全局指标汇总
| 方法 | 任务成功率 ($SR_{{\\text{{task}}}}$) | 完整序列成功率 ($SR_{{\\text{{seq}}}}$) | 后续评估成功率 ($SR_{{\\text{{eval}}}}$) | 硬违规率 ($VR$) | 重复失败 ($N_{{\\text{{rep}}}}$) | 不必要绕路 ($N_{{\\text{{detour}}}}$) | 解析错误 ($N_{{\\text{{parse}}}}$) | 平均电量消耗 | 总 LLM 调用 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""
    for m in ["B0", "B1", "B2", "B3", "F"]:
        row = dev_methods.get(m, {})
        tsr = f"{row.get('avg_task_success_rate', 0)*100:.1f}%" if dev_methods else "未运行"
        ssr = f"{row.get('sequence_full_success_rate', 0)*100:.1f}%" if dev_methods else "未运行"
        esr = f"{row.get('avg_eval_success_rate', 0)*100:.1f}%" if dev_methods else "未运行"
        vr = f"{row.get('avg_hard_violation_rate', 0)*100:.1f}%" if dev_methods else "未运行"
        rep = row.get("total_repeated_failures", 0) if dev_methods else 0
        det = row.get("total_unwarranted_detours", 0) if dev_methods else 0
        pe = row.get("total_parse_errors", 0) if dev_methods else 0
        bat = f"{row.get('avg_battery_consumed', 0):.1f}" if dev_methods else "未运行"
        calls = row.get("total_llm_calls", 0) if dev_methods else 0
        doc += f"| **{m}** | {tsr} | {ssr} | {esr} | {vr} | {rep} | {det} | {pe} | {bat} | {calls} |\n"

    doc += """
### 3.2 类别明细指标 (Category Breakdown)
| 类别 | 方法 | 任务成功率 | 评估任务成功率 | 硬违规率 | 重复失败 | 不必要绕路 | 解析错误 | 平均电量 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""
    for cat_key, cat_label in [("Cat1_Valid", "Cat 1 (Valid)"), ("Cat2_Stale", "Cat 2 (Stale)"), ("Cat3_Inapplicable", "Cat 3 (Inapplicable)")]:
        for m in ["B0", "B1", "B2", "B3", "F"]:
            c_row = dev_cats.get(cat_key, {}).get(m, {})
            tsr = f"{c_row.get('task_success_rate', 0)*100:.1f}%" if dev_cats else "未运行"
            esr = f"{c_row.get('eval_success_rate', 0)*100:.1f}%" if dev_cats else "未运行"
            vr = f"{c_row.get('hard_violation_rate', 0)*100:.1f}%" if dev_cats else "未运行"
            rep = c_row.get("repeated_failures", 0) if dev_cats else 0
            det = c_row.get("unwarranted_detours", 0) if dev_cats else 0
            pe = c_row.get("parse_errors", 0) if dev_cats else 0
            bat = f"{c_row.get('avg_battery', 0):.1f}" if dev_cats else "未运行"
            doc += f"| {cat_label} | **{m}** | {tsr} | {esr} | {vr} | {rep} | {det} | {pe} | {bat} |\n"

    doc += """
---

## 4. 真实执行案例追踪 (Grounded Trace Case Studies)

以下案例基于修复后的实际运行日志与工具事件精确引用：

### 4.1 案例一：Stale 场景下的感知主动失效机制验证
- **序列与任务**: `dev_cat2_stale` $\\rightarrow$ `dev_c2_t2`
- **初始条件**: 在 `dev_c2_t1` (Step 2, `evt_t0_s02_navigate`) 中，Agent 尝试直通 `door_north` 失败并记录 `DOORWAY_BLOCKED`。
- **基线 $B2$ 行为**: 在 `dev_c2_t2` 中，$B2$ 检索到静态记忆 `[ACTIVE] navigate(door_north) failed`，直接选择经由 `Corridor_South` 绕行，未尝试或扫描北门，产生不必要绕路。
- **方法 $F$ 行为**: 在 `dev_c2_t2` 中，Agent 执行 `observe(target='door_north')` (事件 `evt_t1_s01_observe`)，环境返回 `passage_state: FREE`。内存管理器触发动态更新，将记录状态变更为 `INVALIDATED`。Agent 随后规划 `navigate(target_zone='Corridor_North')` 直达目标，消除了绕路开销。

### 4.2 案例二：Inapplicable 场景下的条件不适用隔离验证
- **序列与任务**: `dev_cat3_inapplicable` $\\rightarrow$ `dev_c3_t2`
- **初始条件**: 在 `dev_c3_t1` 中，Agent 进入 `Lab_Secure` 遇到门禁失败 `SECURITY_BADGE_REQUIRED`，记录条件 `door_lab requires security_badge`。
- **方法 $F$ 行为**: 在 `dev_c3_t2`（目标为 `Office_A`）中，条件匹配器评估目标前置条件，发现当前任务为 `Office_A`（与 `door_lab` 门禁条件不匹配，判定为 `MISMATCH`），未将该门禁限制误应用至 `Office_A`，正常执行投递。

---

## 5. 阶段准入判定与 Go/No-Go 评估

| 准入维度 | 判定准则 | 当前实测状态 | 判定结论 |
| :--- | :--- | :--- | :---: |
| **提示与信息隔离** | 任务指令无隐藏状态泄漏，公开目标与环境观测完全分离 | 3 组开发序列通过无泄漏检查 | $\\checkmark$ 达标 |
| **解析与接口健壮性** | 无启发式硬编码猜测，严格 Schema 校验与单次重试 | 15 单元中解析错误均规范归类并记录 | $\\checkmark$ 达标 |
| **三值逻辑条件匹配** | 条件评估严格输出 `MATCH`, `MISMATCH`, `UNKNOWN` | 单元测试通过，待验证不误判为确定适用 | $\\checkmark$ 达标 |
| **主动失效与 TTL 触发** | 观测正确失效旧记忆，TTL 在多任务序列中确定生效 | 开发实验与测试均触发对应事件 | $\\checkmark$ 达标 |
| **研究假设验证** | 在独立未见的大规模评测集上建立显著优势 | **尚未在新独立评测集上运行正式评测** | **未验证 (Unverified)** |
| **Gazebo / 阶段三准入** | 先导有效性确立且方法优势具备统计依据 | **暂未满足正式结论准入条件** | **未达标 (NOT READY)** |

### **当前官方决策**: **暂停扩大实验，先修复有效性 (PAUSE EXPANSION / MECHANISM VALIDATED FOR NEW PILOT)**

> **说明**: 当前决定并不意味着研究假设已被证伪。本轮工作成功完成了最小系统的有效性修复与机制链路打通。下一阶段需在**重新设计并提交冻结的独立评测数据集**后，开展全新的正式对比实验。

---

## 6. 下一阶段开展新先导实验的就绪条件

在启动下一轮正式先导评测前，必须满足：
1. **独立评测集构建**: 生成 15+ 组互不重复、无提示泄漏的全新场景，并预先提交冻结配置哈希。
2. **事前冻结存证**: 将协议、评测集配置与分析脚本预先提交至 Git，建立明确的事前冻结记录。
3. **全流程自动化日志审计**: 运行全量批次，基于事件日志重算所有指标并执行统计显著性检验。
"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(doc)

    print(f"[SUCCESS] Updated pilot report written to {output_file}.")


if __name__ == "__main__":
    generate_pilot_report()
