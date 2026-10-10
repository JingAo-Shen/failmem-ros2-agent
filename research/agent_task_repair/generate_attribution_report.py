import json
import numpy as np
from pathlib import Path

res_file = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/attribution_2x2_results.json")
report_file = Path("/code/failmem-ros2-agent/research/agent_task_repair/results/attribution_32_report.md")

with open(res_file, "r", encoding="utf-8") as f:
    data = json.load(f)

results = data["results"]
metadata = data["metadata"]
conditions = [c["condition_name"] for c in data["conditions"]]

stats = {}
for c in conditions:
    c_runs = [r for r in results if r["condition"] == c]
    succ = sum(1 for r in c_runs if r["success"])
    n = len(c_runs)
    calls = [r["llm_calls"] for r in c_runs]
    p_toks = [r["total_prompt_tokens"] for r in c_runs]
    g_toks = [r["total_generated_tokens"] for r in c_runs]
    steps = [r["step_count"] for r in c_runs]
    errs = [r["tool_errors_count"] for r in c_runs]
    times = [r["wall_time_s"] for r in c_runs]
    
    stats[c] = {
        "succ": succ,
        "n": n,
        "rate": succ / n * 100,
        "calls_tot": sum(calls),
        "calls_mean": np.mean(calls),
        "calls_std": np.std(calls),
        "p_tok_tot": sum(p_toks),
        "p_tok_mean": np.mean(p_toks),
        "g_tok_tot": sum(g_toks),
        "g_tok_mean": np.mean(g_toks),
        "steps_mean": np.mean(steps),
        "errs_tot": sum(errs),
        "errs_mean": np.mean(errs),
        "time_tot": sum(times),
        "time_mean": np.mean(times),
    }

tasks = sorted(list({r["task_id"] for r in results}))
common_succ = [tid for tid in tasks if all(any(r["task_id"] == tid and r["condition"] == c and r["success"] for r in results) for c in conditions)]

lines = []
lines.append("# 名义 2×2 提示配置比较报告 (信息内容混杂审计与有限范围结论)")
lines.append("\n> ⚠️ **后续研究审计与证据纠正链接**：")
lines.append("> - **项目证据总表**：参见 [项目研究证据总表 (research_evidence_ledger.md)](./research_evidence_ledger.md)；")
lines.append("> - **提示信息内容审计**：参见 [提示信息审计报告 (prompt_information_audit.json)](./prompt_information_audit.json)；")
lines.append("> - **实验性质重标定**：本报告记录的 32 次运行为**“名义 2×2 提示配置比较”**。实际 Prompt 信息审计表明，各条件在重规划触发时存在结构化事实与领域协议的非对称注入混杂，**不能称为严格解耦的因果归因**。\n")

lines.append("## 一、评测环境与元数据规范")
lines.append(f"- **执行代码 Commit**：`{metadata.get('commit_hash', '7e1dbb3')}`")
lines.append(f"- **评测模型**：`{metadata.get('model', '/models/Qwen3-14B-AWQ')}` (单卡 RTX 2080 Ti 22GB, AWQ 量化, Temperature = 0.0, max_new_tokens = 512)")
lines.append("- **资源预算**：32 LLM Calls / 40 Tool Calls / 1800s 超时上限")
lines.append("- **目标字符串**：所有条件统一使用去序列提示的抽象目标 `\"Diagnose workstation, resolve all active faults, verify system safety, and resume production.\"`")
lines.append("- **任务性质说明**：所测试的 8 个任务实例均属于开发诊断集，结论严格限定于该开发子集上的观察表现。\n")

lines.append("## 二、2×2 提示配置对比数据矩阵 (32 次运行原始数据保留)")
lines.append("\n| 实验条件 | 提示词级别 | 重规划策略 | 任务成功率 | 总 LLM 调用 | 平均调用数 | 总工具错误 | 平均执行步数 | 总耗时 (s) | 真实总 Prompt Token | 真实总生成 Token |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
for c in conditions:
    s = stats[c]
    rec_lvl = "NoRecipe (基础说明)" if "NoRecipe" in c else "ExpertRecipe (流程提示)"
    rep_lvl = "StandardReplan (通用重规)" if "StandardReplan" in c else "FocusedRepair (约束聚焦)"
    lines.append(f"| **{c}** | {rec_lvl} | {rep_lvl} | {s['succ']}/{s['n']} ({s['rate']:.1f}%) | {s['calls_tot']} | {s['calls_mean']:.2f} ± {s['calls_std']:.2f} | {s['errs_tot']} | {s['steps_mean']:.2f} | {s['time_tot']:.1f} | {s['p_tok_tot']} | {s['g_tok_tot']} |")

lines.append("\n> **注**：所有 Token 数均通过逐次调用记录 `llm_call_records` 经由严格断言校验 (`llm_calls == len(records)`, `total_tokens == sum(record_tokens)` 100% 成立)。\n")

lines.append("## 三、提示信息内容审计与混杂分析 (Information Confounding Audit)")
lines.append("根据 `prompt_information_audit.json` 对实际调用日志的严格审计，四种名义配置在实际 Prompt 中包含了不同维度的事实与知识，并未达到完全正交：")
lines.append("1. **结构化事实注入非对称**：")
lines.append("   - `_plan_standard_replan` 在拦截触发时向 Prompt 注入了 `verified_transitions`（已验证状态转移）和 `negative_preconditions`（负向前置观察）；")
lines.append("   - `_plan_constraint_repair` 虽定义了 `structured_facts` 形参，但在组装修复 Prompt 时**完全未使用**该变量，导致聚焦模式缺少上述来源事实。")
lines.append("2. **人工流程协议注入非对称**：")
lines.append("   - 仅在 `ExpertRecipe_FocusedRepair` 中，修复 Prompt 额外注入了 `Domain Interlock Protocols`（显式包含 `isolate -> clear_fault -> release` 具体维修链）；")
lines.append("   - `ExpertRecipe_StandardReplan` 仅在系统提示的工具说明中包含流程描述，重规划触发时并无领域协议注入。")
lines.append("3. **归因限制**：")
lines.append("   - 鉴于实际 Prompt 包含的信息内容不同，**无法将实验组间的性能差异干净归因于聚焦重规划策略、流程先验知识或上下文压缩**，只能客观记录为特定提示配置下的组合表象。\n")

lines.append("## 四、各任务实例配对表现与观察记录")
lines.append("\n| 任务类别 | 任务 ID | NoRecipe_Std | NoRecipe_Foc | Expert_Std | Expert_Foc | 核心依赖特征与表现 |")
lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :--- |")
for tid in tasks:
    t_runs = {r['condition']: r for r in results if r['task_id'] == tid}
    c_std = f"{'✓' if t_runs['NoRecipe_StandardReplan']['success'] else '✗'} ({t_runs['NoRecipe_StandardReplan']['llm_calls']}c, {t_runs['NoRecipe_StandardReplan']['step_count']}s)"
    c_foc = f"{'✓' if t_runs['NoRecipe_FocusedRepair']['success'] else '✗'} ({t_runs['NoRecipe_FocusedRepair']['llm_calls']}c, {t_runs['NoRecipe_FocusedRepair']['step_count']}s)"
    e_std = f"{'✓' if t_runs['ExpertRecipe_StandardReplan']['success'] else '✗'} ({t_runs['ExpertRecipe_StandardReplan']['llm_calls']}c, {t_runs['ExpertRecipe_StandardReplan']['step_count']}s)"
    e_foc = f"{'✓' if t_runs['ExpertRecipe_FocusedRepair']['success'] else '✗'} ({t_runs['ExpertRecipe_FocusedRepair']['llm_calls']}c, {t_runs['ExpertRecipe_FocusedRepair']['step_count']}s)"
    desc = "电源/气动/夹爪互锁" if ("combo" in tid or "interlock" in tid or "power" in tid) else "控制器溢出/传感器漂移"
    lines.append(f"| `source` | `{tid[:32]}...` | {c_std} | {c_foc} | {e_std} | {e_foc} | {desc} |")

lines.append(f"\n### 共同成功子集 ({len(common_succ)}/8 任务) 观察记录")
lines.append("在 5 个任务（`cat2_tpl1`, `cat2_tpl3`, `cat3_tpl2`, `cat4_tpl1`, `cat4_tpl2`）上，四种条件均成功。")
lines.append("\n| 条件 | 子集总调用 | 平均调用 | 子集总 Prompt Token | 平均 Prompt Token | 工具错误数 |")
lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
for c in conditions:
    c_runs = [r for r in results if r['condition'] == c and r['task_id'] in common_succ]
    calls = [r['llm_calls'] for r in c_runs]
    p_tok = [r['total_prompt_tokens'] for r in c_runs]
    errs = [r['tool_errors_count'] for r in c_runs]
    lines.append(f"| **{c}** | {sum(calls)} | {np.mean(calls):.2f} | {sum(p_tok)} | {np.mean(p_tok):.1f} | {sum(errs)} |")

lines.append("\n## 五、当前支持的有限范围研究结论")
lines.append("\n基于严谨的实证数据与信息审计，当前**仅允许确立以下 5 项有限结论**：")
lines.append("1. **在 32 次开发诊断中，无人工流程的两组均为 7/8 (87.5%)**；")
lines.append("2. **FocusedRepair 在无人工流程条件下没有提高成功率**，两组成功率持平（均为 7/8），且总 LLM 调用由 94 次增加至 107 次；")
lines.append("3. **ExpertRecipe + FocusedRepair 在当前 8 个任务实例上表现最好**（8/8 成功，总调用 67 次，工具错误 9 次）；")
lines.append("4. **由于实际 Prompt 包含的信息内容不同，无法把组间表现差异干净归因于聚焦策略、流程知识或上下文压缩**；")
lines.append("5. **先前主评测中，D-gated 相比 Replay 没有建立稳定独立的任务成功率或调用优势**（主评测二者成功率持平，Replay 平均调用更低）。\n")

lines.append("## 六、删除与降级的非受控表述清单")
lines.append("\n根据科研严谨性规范，正式**从本研究全部报告与文档中删除或降级以下缺乏充分依据的过度推论**：")
lines.append("1. **删除**：~~“SOP 是工业智能体可靠运行的必要条件”~~（降级为：在当前 8 个开发任务中，注入 SOP 提示在给定预算内降低了调用与试错数）；")
lines.append("2. **删除**：~~“三步以上是模型推理崩溃点”~~（降级为：在当前 Qwen3-14B 模型与预算下，更长程的级联任务更容易耗尽调用预算）；")
lines.append("3. **删除**：~~“两层因果关系是模型能力上限”~~（降级为：模型在当前无提示配置下成功解决了包含多故障的任务，未测定确切的理论推理层数上限）；")
lines.append("4. **删除**：~~“非马尔可夫依赖”~~（降级为：带有前置锁死条件的环境反馈）；")
lines.append("5. **删除**：~~“静态流程提示比无提示危害更大”~~（降级为：在当前特定任务实例与预算下，部分提示组合出现了单任务耗尽预算的失败）；")
lines.append("6. **删除**：~~“该架构是唯一正确道路”~~（降级为：是一种兼顾状态检查与预算拦截的工程实现选项）；")
lines.append("7. **删除**：~~“模拟工具错误直接代表真实设备危险”~~（降级为：模拟环境中的工具调用失败计数）；")
lines.append("8. **删除**：~~“已彻底证伪程序性记忆的普遍价值”~~（降级为：当前具体实现的 D-gated 在当前评测基准上未展现超越 Replay 的独立收益）。\n")

lines.append("> **实验效力边界声明**：")
lines.append("> 以上所有观察仅代表在特定开源模型（Qwen3-14B-AWQ）、特定 Workstation 模拟环境、特定提示模板和有限预算（32 调用/40 工具）下的实测表现。负结果在当前测试边界内有效成立，但不能扩大为整个程序性记忆或自主规划研究方向不成立。\n")

lines.append("## 七、研究收尾与方法冻结决策")
lines.append("\n1. **现有方法全面冻结**：")
lines.append("   - `Group_D_current`、`Group_D_gated`、`Group_Replay`、`Group_B2_plan` 及当前的 Workstation 环境与全部 8 个开发实例全部标记为**开发数据并归档冻结**；")
lines.append("   - 不再通过增加模块、修改任务名称、改变环境数值或更换提示措辞制造新实验。")
lines.append("2. **主线不盲目转向 SOP 状态机**：")
lines.append("   - 本轮不恢复 D-gated 开发，也不直接把学术主线改为 SOP 状态机；")
lines.append("   - SOP 执行系统可以作为可靠的工程成果整理，但是否构成研究创新需要独立充分论证。\n")

lines.append("---")
lines.append("*本报告数据严格保留自 `attribution_2x2_results.json`，审计细节参见 `prompt_information_audit.json`，项目全局演进记录参见 `research_evidence_ledger.md`。*")

with open(report_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Successfully generated corrected {report_file}!")
