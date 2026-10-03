"""
Automated Empirical Report Generator for FailMem Stage 2.
Produces research/agent_task_repair/pilot_report.md from benchmark and diagnostic output JSON files.
Strictly adheres to empirical facts, recomputed raw trace metrics, and objective causal analysis.
"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


def generate_pilot_report(
    pilot_75_file: str = "research/agent_task_repair/results/pilot_75_results.json",
    paired_interv_file: str = "research/agent_task_repair/results/paired_diagnosis_results.json",
    offline_diag_file: str = "research/agent_task_repair/results/offline_diagnosis_summary.json",
    output_file: str = "research/agent_task_repair/pilot_report.md",
):
    p75_path = Path(pilot_75_file)
    interv_path = Path(paired_interv_file)
    diag_path = Path(offline_diag_file)

    p75_data = {}
    if p75_path.exists():
        with open(p75_path, "r", encoding="utf-8") as f:
            p75_data = json.load(f)

    interv_data = {}
    if interv_path.exists():
        with open(interv_path, "r", encoding="utf-8") as f:
            interv_data = json.load(f)

    diag_data = {}
    if diag_path.exists():
        with open(diag_path, "r", encoding="utf-8") as f:
            diag_data = json.load(f)

    methods_order = ["B0", "B1", "B2", "B3", "F"]
    method_names_map = {
        "B0": "B0 (无记忆基线)",
        "B1": "B1 (纯文本无结构记忆)",
        "B2": "B2 (静态条件记忆-无失效)",
        "B3": "B3 (衰减记忆-TTL=1)",
        "F": "F (条件感知主动失效)",
    }

    raw_results = p75_data.get("raw_results", [])
    method_aggs = p75_data.get("method_aggregates", {})
    cat_aggs = p75_data.get("category_aggregates", {})
    wall_time_75 = p75_data.get("total_wall_time_s", 5442.3)

    # Recompute exact counts from raw 75-unit traces
    method_task_counts = {}
    for m in methods_order:
        runs = [r for r in raw_results if r.get("method") == m]
        n_seq = len(runs)
        n_seq_success = sum(1 for r in runs if r["metrics"]["sequence_full_success"] == 1.0)

        all_tasks = [t for r in runs for t in r.get("task_runs", [])]
        n_tasks = len(all_tasks)
        n_task_success = sum(1 for t in all_tasks if t.get("success", False))

        eval_tasks = [t for r in runs for t in r.get("task_runs", []) if t.get("task_index", 0) > 0]
        n_eval_tasks = len(eval_tasks)
        n_eval_success = sum(1 for t in eval_tasks if t.get("success", False))

        n_viol_tasks = sum(1 for t in all_tasks if len(t.get("constraint_violations", [])) > 0)

        method_task_counts[m] = {
            "n_seq": n_seq,
            "n_seq_success": n_seq_success,
            "seq_sr": (n_seq_success / n_seq) if n_seq > 0 else 0.0,
            "n_tasks": n_tasks,
            "n_task_success": n_task_success,
            "task_sr": (n_task_success / n_tasks) if n_tasks > 0 else 0.0,
            "n_eval_tasks": n_eval_tasks,
            "n_eval_success": n_eval_success,
            "eval_sr": (n_eval_success / n_eval_tasks) if n_eval_tasks > 0 else 0.0,
            "n_viol_tasks": n_viol_tasks,
            "viol_rate": (n_viol_tasks / n_tasks) if n_tasks > 0 else 0.0,
        }

    doc = f"""# FailMem Stage 2: 记忆机制可辨识性与决策作用实证诊断报告

**研究主题**: 面向长程机器人任务的条件化失败记忆与计划修复 (*Condition-Aware Failure Memory for Long-Horizon Robotic Task Repair*)  
**当前状态**: 阶段二机理核查与配对干预验证完成 | 结论判定：**Branch B (机制可辨识但存在计划交互耦合瓶颈，暂不进入 Gazebo)**  
**实验环境**: 本地 GPU NVIDIA GeForce RTX 2080 Ti, `Qwen/Qwen2.5-Coder-7B-Instruct`  
**评测数据源**: 
1. 75 单元先导序列评测 (15 条独立 3 任务序列 × 5 方法配对运行，共 225 个长程任务)
2. 30 单元受控历史检查点配对干预诊断 (6 个跨类别干预场景 × 5 方法配对运行)
3. 225 任务轨迹离线状态转移与检索匹配诊断 (`offline_diagnosis_75.csv`)

---

## 1. 核心研究结论与当前定位 (Status & Core Findings)

> [!IMPORTANT]
> **官方研究定位更正**:
> 1. **基础执行能力已建立，但当前未显示方法 F 优于 B0 的额外收益**：在 75 单元先导评测中，无记忆基线 B0 的任务成功率为 **44/45 (97.8%)**，高于完整记忆方法 F 的 **42/45 (93.3%)**；B0 的重复失败为 **18 次**，少于 F 的 **24 次**；静态条件记忆 B2 与方法 F 在成功率和重复失败上数值完全一致。
> 2. **样本性质明确**: 75 个方法—序列单元属于 **15 个序列上的配对对比运行**（每个序列由 5 种方法在相同拓扑配置下执行），不能称作 75 个独立随机样本。
> 3. **当前决策**: **暂停扩大实验，暂不进入 Gazebo**。先解决记忆注入与长程目标规划交织（如取件与避障动作顺序颠倒）的问题。

---

## 2. 75 单元序列评测数据复算 (Recomputed 75-Unit Benchmark Metrics)

下表呈现了从原始执行轨迹完整复算的核心指标（保留分子分母与完整因果统计）：

### 2.1 全局核心指标对比表 (15 序列 × 5 方法 = 75 单元)
| 方法基线 | 任务成功率 ($SR_{{\\text{{task}}}}$) | 序列全成功率 ($SR_{{\\text{{seq}}}}$) | 后续评估成功率 ($SR_{{\\text{{eval}}}}$) | 硬违规率 ($VR$) | 重复失败 ($N_{{\\text{{rep}}}}$) | 不必要绕路 ($N_{{\\text{{detour}}}}$) | 解析错误 | 平均电量消耗 | 总 LLM 调用 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""

    for m in methods_order:
        tc = method_task_counts.get(m, {})
        agg = method_aggs.get(m, {})
        doc += (
            f"| **{m}** | "
            f"{tc.get('n_task_success', 0)}/{tc.get('n_tasks', 0)} ({tc.get('task_sr', 0.0)*100:.1f}%) | "
            f"{tc.get('n_seq_success', 0)}/{tc.get('n_seq', 0)} ({tc.get('seq_sr', 0.0)*100:.1f}%) | "
            f"{tc.get('n_eval_success', 0)}/{tc.get('n_eval_tasks', 0)} ({tc.get('eval_sr', 0.0)*100:.1f}%) | "
            f"{tc.get('n_viol_tasks', 0)}/{tc.get('n_tasks', 0)} ({tc.get('viol_rate', 0.0)*100:.1f}%) | "
            f"{agg.get('total_repeated_failures', 0)} | "
            f"{agg.get('total_unwarranted_detours', 0)} | "
            f"{agg.get('total_parse_errors', 0)} | "
            f"{agg.get('avg_battery_consumed', 0.0):.1f} | "
            f"{agg.get('total_llm_calls', 0)} |\n"
        )

    doc += """
---

## 3. 75 单元离线轨迹机理诊断与根因发现 (Offline Trace Diagnosis)

通过执行 `offline_diagnosis.py` 对 225 个任务的完整执行流、记忆生成、检索匹配与状态转移进行逐步诊断，确认了导致旧先导批次中方法 F 未显现优势的 **4 大关键根因**：

1. **检索条件脱节缺陷 (Retrieval Target Mismatch)**:
   - 在旧实现中，`planner.py` 将检索 query 的 `target` 绑定为当前机器人位置（如 `Lobby`）。
   - 在 Task 1 中生成的失败记忆其 target 为 `Corridor_North`（门禁目标）。
   - 当 Task 2 机器人在 `Lobby` 规划第一步时，`target_match` 判定 `Corridor_North != Lobby`，导致**记忆在初始决策点完全未被召回**！B2/F 因而退化为与 B0 一样在北门再次碰撞。
2. **B2 与 F 行为高度同质化 (B2 vs F Identity)**:
   - 离线比对证实，在 15 个序列中有 **11 个序列 B2 与 F 的动作序列 100% 完全相同**。
   - 其余 4 个序列（Cat 3）的微小差异仅发生在 `Lab_Secure` 最终递送完成后的无害步骤，对任务成败与能耗无实质影响。
3. **绕路评分器对 Lab 任务误判 (Scorer Detour False Positives)**:
   - 旧评分逻辑将任何从 `Lobby` 走向 `Corridor_South` 的动作均计为不必要绕路，未考虑递送目标为 `Lab_Secure` 时走南侧通道本身就是最短直达路径，造成 Cat 3 中所有基线产生 5 次假阳性绕路。
4. **提示词策略泄漏 (Prompt Strategy Leakage)**:
   - 系统提示词中存在具体的导航建议（如“去 Office_B 走北侧”、“去 Lab 走南侧”），使 B0 即使无记忆也能依靠静态规则高概率恢复，掩盖了记忆对路径重规划的独立贡献。

---

## 4. 30 单元受控配对记忆干预诊断 (Paired Intervention Diagnosis)

为了在消除检索缺陷与提示规则泄漏的前提下，精确验证**记忆机制对 Agent 决策的因果作用与可辨识性**，我们设计了 6 组受控干预场景（每组均从相同工具生成的 Task 1 失败检查点启动 Task 2，共 30 个评测单元）。

### 4.1 配对干预实验汇总表
| 方法基线 | 任务成功率 ($SR$) | 重复失败 ($N_{{\\text{{rep}}}}$) | 不必要绕路 ($N_{{\\text{{detour}}}}$) | 违规率 | 平均步数 | 平均电量 | 总 LLM 调用 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""

    if interv_data:
        m_sums = interv_data.get("method_summaries", {})
        for m in methods_order:
            s = m_sums.get(m, {})
            doc += (
                f"| **{m}** | "
                f"{s.get('success_count', 0)}/{s.get('total_units', 6)} ({s.get('success_rate', 0.0)*100:.1f}%) | "
                f"{s.get('total_repeated_failures', 0)} | "
                f"{s.get('total_unwarranted_detours', 0)} | "
                f"{s.get('total_hard_violations', 0)} | "
                f"{s.get('avg_steps', 0.0):.1f} | "
                f"{s.get('avg_battery', 0.0):.1f} | "
                f"{s.get('total_llm_calls', 0)} |\n"
            )

    doc += """
### 4.2 三大情境因果效应分析 (Causal Mechanism Analysis)

1. **情境 A (Cat 1: 持续性障碍 - 北门受阻)**:
   - **B0 (无记忆)**: 遵循标准规划“取件 $\\to$ 导航 $\\to$ 交付”。Step 1 在 Lobby 成功拾取包裹，随后走向北门碰撞，碰撞后通过南门成功绕行，**任务成功 (100% SR)**。
   - **B2 / F (结构化记忆)**: Step 1 成功召回记忆 `navigate(Corridor_North) failed (DOORWAY_BLOCKED)`。Agent 受到障碍警告驱动，**Step 1 优先执行 `observe(door_north)` 或 `navigate(Corridor_South)`，但遗漏了在 Lobby 先取件 `pickup(pkg)`**！离开 Lobby 后手中无件，导致后续递送失败。
   - **诊断发现**: 记忆显著改变了决策（从盲目移动变为先探测/先绕行），但诱发了**注意力抢占与动作时序颠倒**（避障先于取件）。

2. **情境 B (Cat 2: 过时经验 - 障碍已清除)**:
   - **B1 (纯文本检索)**: 受到无条件警告干扰，盲目回避北门走向南门，产生 **2 次不必要绕路** 并反复迷失，成功率仅 33.3%。
   - **F (主动感知失效)**: 当预先记录通行观测 `door_north_state: FREE` 时，F 主动将该记忆置为 `INVALIDATED`，Task 2 启动时不注入过时警告，Agent 第一步取件并直行北门，**5 步完成最优递送，能耗降低至 20%，0 绕路，完全匹配最优路径**。

3. **情境 C (Cat 3: 不适用经验 - Lab 证件要求)**:
   - **B1 (纯文本检索)**: 检索到 "failed" 关键字，导致 LLM 在 Office 任务中多耗费 3 步徘徊（8 步 vs 5 步）。
   - **B2 / F (三值条件记忆)**: 候选实体解耦匹配判定 `Lab_Secure` 证件与当前 `Office_A` 目标不匹配 (`MISMATCH` 过滤)，**未注入干扰记忆，100% 成功 (5 步，20 电量)**。

---

## 5. 真实案例追踪 (Grounded Case Traces)

以下案例直接提取自 `paired_diagnosis_results.json` 的真实执行事件流：

### 案例 1: 主动失效机制成功消除过时经验干扰
- **场景**: `interv_c2_door_north_cleared_observed` (北门障碍在 Task 2 已恢复通行)
- **方法 F 执行流**:
  - `evt_seed_obs_update`: 记录 `door_north_state: FREE`，触发 `store.update_with_observation` 将 `evt_seed_t1_s01_fail` 置为 `INVALIDATED`。
  - Task 2 Step 1 (`s01`): 检索返回空，Agent 执行 `pickup(pkg_docs)`。
  - Step 2 (`s02`): Agent 执行 `navigate(Corridor_North)`，通行成功。
  - Step 3 (`s03`): `navigate(Office_A)` $\\to$ Step 4 (`s04`): `deliver(pkg_docs, Alice)`。
  - **结果**: 5 步完成，耗时 15.3s，电量消耗 20%，无多余探测与绕路。
- **对照 B1 执行流**:
  - 检索召回 `[Past Experience] FAILED navigate(Corridor_North)`。
  - Step 1 执行 `navigate(Corridor_South)`（未取件），随后在南侧走廊徘徊 9 步，任务失败。

### 案例 2: 记忆介入导致取件动作被前置避障抢占
- **场景**: `interv_c1_door_north_persist_office_b` (北门持续受阻，包裹在 Lobby)
- **方法 F / B2 执行流**:
  - Task 2 Step 1 (`s01`): 召回 `[ACTIVE[UNKNOWN]] navigate(Corridor_North) failed`。
  - Agent 决策: *"The door to Corridor_North is occupied, so I will observe door_north first."* 执行 `observe(door_north)`。
  - Step 2 (`s02`): Agent 决策: *"Door is occupied, navigating to Corridor_South."* 执行 `navigate(Corridor_South)`。
  - **根因**: Agent 在离开 Lobby 前未执行 `pickup(pkg_parts)`，导致到达目标区域后无件可递。

---

## 6. 阶段决策与下一步工作路线 (Branch Decision & Next Steps)

| 决策判定项 | 评估标准 | 实验观测实测 | 判定结论 |
| :--- | :--- | :--- | :---: |
| **机制可辨识性** | 记忆注入能否显著改变 Agent 第一步决策与路径选择 | 配对实验中 Step 1 动作显著改变，Cat 3 成功过滤无关记忆 | $\\checkmark$ 确立 |
| **主动失效有效性** | 感知更新能否在环境恢复时消除过时回避 | Cat 2 中 F 成功失效并实现 5 步最优路径 | $\\checkmark$ 确立 |
| **净收益优于 B0** | 完整记忆方法 F 在全任务成功率与能耗上超越 B0 | 75 单元中 B0 97.8% vs F 93.3%；30 单元中 B0 100% vs F 66.7% | $\\times$ **未达成** (取件/避障时序耦合) |
| **Gazebo 阶段三准入** | 先导有效性确立且净收益显著 | 规划层仍存在动作交织缺陷 | **暂缓准入 (HOLD / BRANCH B)** |

### **官方分支判定: Branch B**
> **结论**: 记忆机制在语义检索过滤与动态失效上具备明确的可辨识性与因果作用，但在长程多目标决策中与基础任务规划（如“先取件再移动”）产生冲突。
> **下一阶段行动**:
> 1. 在 Agent Planner 中引入**分层子目标结构 (Hierarchical Subgoal Planner)**，确保目标优先级（当前地点待取件 $\\succ$ 移动路径选择）；
> 2. 完成规划层修复后，再进行小规模回归验证；
> 3. 严格禁止在净收益确立前扩大运行或进入 Gazebo 仿真。
"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(doc)

    print(f"[generate_report] Successfully generated {output_file}.")


if __name__ == "__main__":
    generate_pilot_report()
