# FailMem & 条件约束记忆修复与论文证据终审报告 (Paper Final Audit)

**审阅基准**: `dd3b507753fe384ab64449bb35d97974f2e73126`  
**算力状态**: **新增 GPU 调用 = 0，新增模型 Token = 0，本地 CPU 确定性执行**  
**测试状态**: 全量 261 项测试 100% 通过（`research/` 70 项通过，`tests/` 191 项通过、8 项预期 xfail）  
**产物状态**: 论文 `paper/paper.pdf` 与 `paper/supplementary.pdf` 编译成功，D2 闭合时间账本与自然候选修订版报告全量归档  

---

## 核心验收七问官方答复 (Answers to the 7 Mandatory Questions)

### 问题 1：S2 的 write_config 资源选择是否已修复？（给出可写和不可写目录的实际测试表现）

**答复：已彻底修复。**

1. **核心逻辑修复**：
   - 彻底移除了原代码中“只要动作参数包含 `port` 就盲目优先检查端口”的错误规则；
   - 在 `multistep_agent_runner.py::_evaluate_s2_cached_gate` 中，严格按动作语义选择待验证资源：
     * `write_config`：`port` 是写入配置文件的内容参数，不作为端口占用检查；实际核验目标文件路径及其父目录的写权限与执行身份；
     * `start_service`：核验实际配置路径存在性与 JSON 有效性，并按需从配置中提取端口核验监听冲突；
     * `check_health`：核验目标监听端口。
   - 多资源缓存键显式绑定具体资源复合键，状态变更时精确失效，不发生跨路径串扰。

2. **实测表现验证**（覆盖回归测试 13–15）：
   - **用户可写目录测试（回归测试 13）**：
     在端口 18080 已被实际占用的环境下，执行向 `/home/agentuser/service_conf/app_port_param.json` 写入配置，携带参数 `port: 18080`。S2 门禁将其正确识别为文件写入操作，未触发任何端口探针，门禁决策为 `ALLOW`，动作顺利执行并返回 `success: True`。
   - **不可写系统目录测试（回归测试 14）**：
     在端口 18099 空闲的环境下，执行向系统目录 `/etc/service_demo/app_unwritable.json` 写入配置，携带参数 `port: 18099`。S2 门禁通过 `probe_file` 探测到父目录 `/etc/service_demo` 对 `agentuser` 不可写（`writable_by_user: False`），硬拦截该操作（`GateDecision.BLOCK`），未发生盲目执行，记录 1 次真阳性阻断（TP）。
   - **资源缓存隔离测试（回归测试 15）**：
     连续执行两次写入，均携带相同的 `port: 18080` 参数：第一次写入不可写路径 `/etc/service_demo/app_block.json`，第二次写入可写路径 `/home/agentuser/service_conf/app_allow.json`。S2 正确阻断第一次写入；第二次写入时未发生缓存键碰撞，正常探测到 `/home/agentuser` 可写并放行执行（`ALLOW`）。

---

### 问题 2：失败类型不匹配是否已被阻止判定为 supported？（给出返回判定）

**答复：是，已被严格阻止判定为 supported。**

1. **判定逻辑机制**：
   - 在 `research/conditional_constraint_memory/run_candidate_execution_verification.py::adjudicate_candidate_variant` 中：
     只有在前置条件独立求值为 `TRUE`、动作工具与作用域匹配、且实际执行产生的错误类型与规则声明的预期错误类型完全匹配（`matches_failure_type == True`）时，才返回 `SUPPORTED_IN_TESTED_CONTEXT`；
   - 当实际执行出现故障但错误类型不同时（例如声明预期错误为 98 端口占用 `AddressAlreadyInUse`，实际执行却因为文件不存在报错 2 `ConfigNotFound`），函数明确返回判定：
     $$\textbf{FAILURE\_TYPE\_MISMATCH}$$
     此时 `failure_type_matched = False`，绝不判定为支持。

2. **实测表现验证**（覆盖回归测试 16）：
   - 在 `test_16_failure_type_mismatch_returns_failure_type_mismatch` 中，传入预期错误码 98 与实际错误码 2（配置文件不存在），判定函数返回 `verdict == "FAILURE_TYPE_MISMATCH"` 且 `failure_matched is False`，严格断言 `verdict != "SUPPORTED_IN_TESTED_CONTEXT"`。

---

### 问题 3：原始候选与衍生规则是否已彻底切分？（给出两组测试的账本来源）

**答复：是，原始历史候选与衍生压力规则已在代码、账本与报告中彻底切分。**

1. **输入基础账本来源与 SHA256**：
   - 基础账本路径：`/code/failmem-ros2-agent/research/conditional_constraint_memory/results/candidate_ledger_24.json`
   - 不可篡改 SHA256 哈希：`317c2766e919739e87918846583cf05438e996b3a74a45fef28edd1844c9e998`

2. **两组测试的严格划分**：
   - **历史原始候选实测对比组 (`RAW_CANDIDATE`)**：
     严格基于模型在历史真实会话中直接输出的原始规则及其真实路径进行核验，包括：
     * `Case_10_Inverted_Predicate_Raw`：Call #10 原始规则，路径 `/home/agentuser/service_conf/nonexistent_cfg_999.json`，实测确认反例（`COUNTEREXAMPLE`）；
     * `Case_4_Scope_Deficiency_Raw_Unprivileged`：Call #4 原始规则，路径 `/etc/service_demo/app_sys.json`，在未授权身份（agentuser）下复现失败；
     * `Case_4_Scope_Deficiency_Raw_OwnerContext`：Call #4 原始规则，路径 `/etc/service_demo/app_sys.json`，在目录属主环境下写入成功，证实范围缺失（`SCOPE_DEFICIENT`）；
     * `Case_2_Valid_Port_Conflict_Raw`：Call #2 原始端口 18080 冲突规则；
     * `Case_14_Valid_Closed_Port_Raw`：Call #14 原始端口 18085 未监听规则。
   - **衍生规则压力测试组 (`DERIVED_RULE_STRESS`)**：
     将历史原始候选（如 `/etc/service_demo/...` 系统目录规则）改写为用户属主目录路径（`/home/agentuser/service_conf/app_sys_0755.json`）等变体，在报告中单列小节呈现，明确声明仅用于压力测试谓词对属主身份的敏感性，绝不与历史原始候选混同。

---

### 问题 4：D2 时间账本是否闭合、残差是否为 0.000、论文中对应表述是否已改为有证据支持的观察性结论？

**答复：是，D2 时间账本已建立严格闭合模型，残差恒为 0.000，过度因果主张已全部撤回并修正为观察性分解。**

1. **时间账本闭合定义与残差验证**：
   - 状态划分：
     * $T_{\text{moving}}$: $|v| \ge 0.05\,\text{m/s}$
     * $T_{\text{turning}}$: $|v| < 0.05\,\text{m/s}$ 且 $|\omega| \ge 0.08\,\text{rad/s}$
     * $T_{\text{stopped}}$: $|v| < 0.05\,\text{m/s}$ 且 $|\omega| < 0.08\,\text{rad/s}$
     * $T_{\text{gap}}$: 动作间调度与过渡空隙 ($T_{\text{phase}} - \sum D_{\text{actions}}$)
   - 闭合恒等式：$T_{\text{total}} = T_{\text{moving}} + T_{\text{turning}} + T_{\text{stopped}} + T_{\text{gap}}$；
   - 产出脚本：`scripts/analyze_d2_trajectory_time_ledger.py`；
   - 账本归档：`reports/evidence/d2_time_ledger/`；
   - **残差核算结果：全部 12 轮 D2 实验在全轨迹与决策阶段的闭合残差恒等于 $0.000$（浮点绝对误差 $< 10^{-6}$）**。

2. **D2 条件级决策阶段实测数据（GT 物理轨迹，单位秒）**：
   - **D2_F**: $T_{\text{dec}} = 51.10 \pm 0.95$（$T_{\text{mov}} = 28.70 \pm 1.18$, $T_{\text{turn}} = 4.20 \pm 0.82$, $T_{\text{stop}} = 17.17 \pm 2.41$, $T_{\text{gap}} = 1.03 \pm 0.15$, 残差 $0.000$）
   - **D2_M1**: $T_{\text{dec}} = 51.30 \pm 2.00$（$T_{\text{mov}} = 34.30 \pm 1.76$, $T_{\text{turn}} = 3.47 \pm 0.49$, $T_{\text{stop}} = 12.83 \pm 1.41$, $T_{\text{gap}} = 0.70 \pm 0.00$, 残差 $0.000$）
   - **D2_O**: $T_{\text{dec}} = 52.03 \pm 1.75$（$T_{\text{mov}} = 29.33 \pm 2.15$, $T_{\text{turn}} = 3.83 \pm 0.49$, $T_{\text{stop}} = 17.77 \pm 0.12$, $T_{\text{gap}} = 1.10 \pm 0.20$, 残差 $0.000$）
   - **D2_R**: $T_{\text{dec}} = 49.57 \pm 1.59$（$T_{\text{mov}} = 28.27 \pm 0.45$, $T_{\text{turn}} = 4.17 \pm 0.84$, $T_{\text{stop}} = 15.97 \pm 1.56$, $T_{\text{gap}} = 1.17 \pm 0.12$, 残差 $0.000$）

3. **论文表述撤回与观察性修正**：
   - 彻底撤回了 `paper/draft.md`（Abstract 与 5.2 节）及 `paper_readiness_gap.md` 中原有的“揭示了物理机制”、“完全抵消”等未受闭合分解严格支持的绝对化因果断言；
   - 修正为严格受数据支持的观察性分解描述：明确指出短路径（Path A）将决策阶段纯移动耗时缩减了 $16.3\%$（$28.70\,\text{s}$ vs. $34.30\,\text{s}$），但狭窄门区的 3 阶段子目标导航与停定核验窗口（$17.17\,\text{s}$ vs. $12.83\,\text{s}$）以及动作切换空隙（$1.03\,\text{s}$ vs. $0.70\,\text{s}$）带来了代数层面的相互对冲，使总决策耗时相当（$51.10\,\text{s}$ vs. $51.30\,\text{s}$）。

---

### 问题 5：离线复现是否已在非覆盖模式下执行并成功？

**答复：是，已在非覆盖模式下成功执行并验证。**

1. **流水线安全防护实现**：
   - `scripts/reproduce_offline.sh` 移除了默认 `--overwrite` 参数；
   - `scripts/reproduce_offline.py` 增加了 `check_git_tracked_paths` 机制，通过 `git ls-files` 严格检测并阻止删除或篡改任何 git 追踪文件与基线目录；
   - 当目标输出目录非空且未指定 `--overwrite` 时，自动追加时间戳或要求显式指定空目录，实现完全非破坏性执行。

2. **实测执行结果**：
   - 运行命令：`./scripts/reproduce_offline.sh --output-dir reports/evidence/reproduced_clean_test`；
   - 执行时间：2.56 秒，GPU = 0；
   - SHA256 校验：271/271 个文件通过；
   - 轨迹回放与审计：30/30 个 episode 100% 通过；
   - 基线对比：`episodes.csv`、`condition_summary.csv`、`contrasts.csv` 三份文件与参考基准的数值差值均为 0（Diff = 0）；
   - H1 可行性复核：4/4 运行通过，GO/NO-GO 判定为 NO-GO（场景未建立）。

---

### 问题 6：转向 ROS2 论文收尾前，还遗留哪些必须由论文作者完成的工作？

**答复：当前工程代码、测试集、实验账本与 PDF 编译系统均已达到最高严谨度闭环。遗留的作者端工作仅限以下 3 项非工程事务：**

1. **作者信息与致谢填充**：当前 `paper/draft.md` 处于双盲匿名审阅格式（Anonymous Authors），最终投递前由作者根据投递要求补充作者姓名、单位与基金致谢；
2. **目标期刊/会议 LaTeX 模板终版排版**：目前编译流水线由 Markdown + Pandoc + WeasyPrint 生成高质量 10 页 PDF（`paper/paper.pdf`），若投递 IEEE ICRA/IROS 等特定会议，需将预生成的 Markdown / LaTeX 表格与图表载入 IEEEtran 官方模板进行双栏末尾栏平衡与行数微调；
3. **OS 候选分支归档锁定**：冻结本轮 `research/agent-task-repair-pilot` 分支作为约束记忆子课题的留档基线，不再追加新改动。

---

### 问题 7：当前 commit SHA

**答复**：当前提交 Commit SHA 为 `e80f7c04dbf55aa0b15316ef3524b0673413993c`（基于审阅基准 `dd3b507753fe384ab64449bb35d97974f2e73126`）。
