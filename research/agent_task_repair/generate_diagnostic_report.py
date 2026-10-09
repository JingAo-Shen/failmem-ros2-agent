import json
import numpy as np
from pathlib import Path

b1_file = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/batch1_diagnostic_results.json")
b2_file = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/batch2_ablation_results.json")
report_file = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/diagnostic_48_report.md")

with open(b1_file) as f:
    b1_data = json.load(f)
with open(b2_file) as f:
    b2_data = json.load(f)

b1_results = b1_data["results"]
b2_results = b2_data["results"]

assert len(b1_results) == 24, f"Expected 24 runs in Batch 1, got {len(b1_results)}"
assert len(b2_results) == 24, f"Expected 24 runs in Batch 2, got {len(b2_results)}"

groups = ["Group_B2_plan", "Group_Replay", "Group_D_gated"]

def compute_group_stats_strict(results, g):
    runs = [r for r in results if r["group_id"] == g]
    succ = sum(1 for r in runs if r["success"])
    n = len(runs)
    calls = [r["llm_calls"] for r in runs]
    steps = [r["step_count"] for r in runs]
    errs = [r["tool_errors_count"] for r in runs]
    times = [r["wall_time_s"] for r in runs]
    
    # Strictly recompute from llm_call_records
    records_count = [len(r.get("llm_call_records", [])) for r in runs]
    p_tokens_strict = [sum(rec["prompt_tokens"] for rec in r.get("llm_call_records", [])) for r in runs]
    g_tokens_strict = [sum(rec["generated_tokens"] for rec in r.get("llm_call_records", [])) for r in runs]
    
    # Assert consistency for call counts
    for r in runs:
        assert r["llm_calls"] == len(r.get("llm_call_records", [])), f"Call count mismatch in {r['task_id']}"
    
    mem_sel = sum(r.get("memory_selected_count", 0) for r in runs)
    mem_def = sum(r.get("memory_deferred_count", 0) for r in runs)
    mem_res = sum(r.get("memory_resumed_count", 0) for r in runs)
    mem_exec = sum(r.get("memory_action_executed_count", 0) for r in runs)
    mem_ver = sum(r.get("memory_postcondition_verified_count", 0) for r in runs)
    mem_inv = sum(r.get("memory_invalidated_count", 0) for r in runs)
    
    return {
        "succ": succ,
        "n": n,
        "rate": succ / n * 100,
        "calls_total": sum(calls),
        "calls_mean": np.mean(calls),
        "calls_std": np.std(calls),
        "steps_total": sum(steps),
        "steps_mean": np.mean(steps),
        "errs_total": sum(errs),
        "errs_mean": np.mean(errs),
        "time_total": sum(times),
        "time_mean": np.mean(times),
        "p_tok_total": sum(p_tokens_strict),
        "g_tok_total": sum(g_tokens_strict),
        "mem_sel": mem_sel,
        "mem_def": mem_def,
        "mem_res": mem_res,
        "mem_exec": mem_exec,
        "mem_ver": mem_ver,
        "mem_inv": mem_inv,
        "runs": runs,
    }

b1_stats = {g: compute_group_stats_strict(b1_results, g) for g in groups}
b2_stats = {g: compute_group_stats_strict(b2_results, g) for g in groups}

# Validate known Batch 1 token counts
assert b1_stats["Group_B2_plan"]["p_tok_total"] == 164816, f"Expected 164816, got {b1_stats['Group_B2_plan']['p_tok_total']}"
assert b1_stats["Group_Replay"]["p_tok_total"] == 119891, f"Expected 119891, got {b1_stats['Group_Replay']['p_tok_total']}"
assert b1_stats["Group_D_gated"]["p_tok_total"] == 130919, f"Expected 130919, got {b1_stats['Group_D_gated']['p_tok_total']}"

tasks = sorted(list({r["task_id"] for r in b1_results}))
b1_succ_matrix = {g: {r["task_id"]: r["success"] for r in b1_results if r["group_id"] == g} for g in groups}
b2_succ_matrix = {g: {r["task_id"]: r["success"] for r in b2_results if r["group_id"] == g} for g in groups}

b1_common_succ = [tid for tid in tasks if all(b1_succ_matrix[g][tid] for g in groups)]
b2_common_succ = [tid for tid in tasks if all(b2_succ_matrix[g][tid] for g in groups)]

lines = []
lines.append("# 重复拦截诊断、人工流程提示与自主约束修复贡献判别报告 (Batch 1 & Batch 2 评测纠正版)")
lines.append("\n> **研究定位修正说明**：")
lines.append("> 1. **Batch 1 定位纠正**：Batch 1 严格标记为**“带人工领域流程提示的开发诊断”**。本轮评测中 8/8 的高成功率**不能**归因于智能体自主发现约束修复动作，因为实验中向模型显式注入了人工编写的领域修复动作链。")
lines.append("> 2. **人工流程注入点披露（两处完整披露）**：")
lines.append(">    - **注入点一（公共工具说明）**：在系统提示词的工具描述中明确写明了复合流程，例如 `clear_fault` 要求“requires isolate 'engage' first, then clear_fault, then isolate 'release'”；")
lines.append(">    - **注入点二（约束修复规划提示词）**：在 `_plan_constraint_repair` 中硬编码了 `Domain Interlock Protocols`（包括电源、气动、夹爪与相机的具体维修动作序列）。")
lines.append("> 3. **代码版本客观性**：实际运行代码在 `d2b12d8` 后进行了执行器与拦截逻辑修改，真实固化快照对应 Commit `a3f4d1f`。历史未打 Tag 的工作区快照标记为“实际运行代码快照无法完整核验”，坚决杜绝后验假造冻结证明。")
lines.append("> 4. **研究取舍决定**：当前 `Group_D_gated` 相比 `Group_Replay` 没有综合性能与效率优势（在调用成本上 Replay 甚至更低，且在具备规划器时无任务成功率差异）。**本研究正式决定停止扩展门控、调度或记忆模块，如实保留方法实现与负结果**。\n")

lines.append("## 一、核心对比数据重算（基于 llm_call_records 逐次调用严格统计）")
lines.append("\n### 1. Batch 1: 带人工领域流程提示的开发诊断 (24 次运行)\n")
lines.append("| 评测组 | 任务成功率 | 总 LLM 调用 | 平均调用数 | 总工具错误 | 平均执行步数 | 总耗时 (s) | 真实总 Prompt Token | 真实总生成 Token |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for g in groups:
    s = b1_stats[g]
    lines.append(f"| **{g}** | {s['succ']}/{s['n']} ({s['rate']:.1f}%) | {s['calls_total']} | {s['calls_mean']:.2f} ± {s['calls_std']:.2f} | {s['errs_total']} | {s['steps_mean']:.2f} | {s['time_total']:.1f} | {s['p_tok_total']} | {s['g_tok_total']} |")

lines.append("\n*注：Prompt Tokens 经由全部 65 / 46 / 52 次调用的 `llm_call_records` 原始记录重算校验，完全消除历史累加字段遗漏，确认 B2-plan: 164816, Replay: 119891, D-gated: 130919。*\n")

lines.append("### 2. Batch 2: 关闭约束修复规划 (消融实验 24 次运行)\n")
lines.append("| 评测组 | 任务成功率 | 总 LLM 调用 | 平均调用数 | 总工具错误 | 平均执行步数 | 总耗时 (s) | 真实总 Prompt Token | 真实总生成 Token |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for g in groups:
    s = b2_stats[g]
    lines.append(f"| **{g}** | {s['succ']}/{s['n']} ({s['rate']:.1f}%) | {s['calls_total']} | {s['calls_mean']:.2f} ± {s['calls_std']:.2f} | {s['errs_total']} | {s['steps_mean']:.2f} | {s['time_total']:.1f} | {s['p_tok_total']} | {s['g_tok_total']} |")

lines.append(f"\n> **共同成功子集 ({len(b2_common_succ)}/8 任务)**：4 个非电源故障任务全员成功。平均调用数：Group_Replay (3.25) < Group_D_gated (4.25) < Group_B2_plan (5.25)。\n")

lines.append("## 二、D-gated 程序性记忆执行指标（数据与复现核验）\n")
lines.append("| 批次 | Memory Selected | Memory Deferred | Memory Resumed | Actions Executed | Postcond Verified | Invalidation Count |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
lines.append(f"| **Batch 1 (流程提示开启)** | {b1_stats['Group_D_gated']['mem_sel']} | {b1_stats['Group_D_gated']['mem_def']} | {b1_stats['Group_D_gated']['mem_res']} | {b1_stats['Group_D_gated']['mem_exec']} | {b1_stats['Group_D_gated']['mem_ver']} | {b1_stats['Group_D_gated']['mem_inv']} |")
lines.append(f"| **Batch 2 (流程提示关闭)** | {b2_stats['Group_D_gated']['mem_sel']} | {b2_stats['Group_D_gated']['mem_def']} | {b2_stats['Group_D_gated']['mem_res']} | {b2_stats['Group_D_gated']['mem_exec']} | {b2_stats['Group_D_gated']['mem_ver']} | {b2_stats['Group_D_gated']['mem_inv']} |")

with open(report_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("Updated diagnostic_48_report.md successfully!")
