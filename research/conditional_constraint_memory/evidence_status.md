# 核心主张证据分级与边界状态清单 (Evidence Status Matrix)

**基准提交**: `0fe4c7337c8099c87611009fedefacc3780026fa`  
**算力预算状态**: **新增 GPU 调用 = 0，新增模型 Token = 0，纯 Linux OS CPU 隔离核验**  
**证据冻结清单**: [`research/conditional_constraint_memory/results/frozen_evidence_manifest.json`](results/frozen_evidence_manifest.json)

---

## 边界与证据来源明确划分

为了保证科学结论的严谨性与学术审计的可追溯性，本清单对以下三类证据实施严格的边界隔离：
1. **历史模型调用 (Historical Model Outputs)**：包含 24 次历史调用原始输入输出（12 次 Method A + 12 次 Method B）。历史提取脚本在经历记录中使用了预置兜底字符串，且复用了合成路径，其源经历未完整保留，**标记为来源受限的历史语料，不可作为自然错误分布的基准数据集**；
2. **重新采集的干净经历 (Clean OS Failure Traces)**：在纯净 Linux OS 环境中无兜底捕获的 12 种底层故障（真实 exit_code、stderr 与系统调用），属于后续基准测试，**不得视作历史模型调用的原始输入，亦不得声称模型在干净输入上的提取准确率**；
3. **针对历史候选的执行核验 (Subsequent Execution Verification)**：在模型指定的真实路径与独立 OS 状态上对 24 条历史候选执行的因果闭环测试。

---

## 证据分级总览表

| 证据级别 | 级别定义 | 核心主张条目 |
| :--- | :--- | :--- |
| **已证实 (Proven)** | 具备完整实机/仿真/OS 执行闭环证据，有可重算的日志、测试用例与哈希支持 | 主张 1.1, 1.2, 1.3, 1.4, 1.5 |
| **受限证实 (Limited)** | 仅在特定构造场景、特定参数或特定前提下成立，严禁向开放场景外推 | 主张 2.1, 2.2, 2.3 |
| **未证实 / 暂不支持 (Unproven)** | 现有实测数据不足以支撑，或实验未观察到预期收益/差异 | 主张 3.1, 3.2, 3.3, 3.4 |
| **已证伪 / 需撤回 (Refuted / Retracted)** | 历史结论被本轮严格核验与真实 OS 执行明确推翻，必须撤回 | 主张 4.1, 4.2, 4.3, 4.4, 4.5 |

---

## 一、已证实主张 (Proven Claims)

### 主张 1.1：历史感知信息能消除 ROS 2 Gazebo 导航中的冗余死胡同探索
- **主张内容**：在双路径阻塞场景（Scenario D1）下，保留历史信息（失败记忆 $F$ 与空间缓存 $O$）相比无跨任务记忆的反应式基线（$R$）消除了死胡同的重复进入（$0.0$ vs. $1.0$ 次），节省 $-18.5\%$ 行驶距离（$14.03\,\text{m}$ vs. $17.22\,\text{m}$）与 $-22.3\%$ 仿真时间（$109.5\,\text{s}$ vs. $141.0\,\text{s}$）。
- **适用范围与失效边界**：仅在 Gazebo 11 仿真环境（TurtleBot3 Waffle 机器人、非视距不对称双路径结构）中得到证实。反应式基线 $R$ 代表无跨任务记忆的死胡同重试，非物理碰撞或控制器死机。
- **证据文件与哈希**：
  - 论文手稿：[`paper/draft.md`](../../paper/draft.md)
  - 实验报告：`reports/evidence/p2c_pilot_reproduced/`
  - 核心审计脚本：`scripts/replay_and_score_p2c.py` (30 次 Gazebo 回放 $100\%$ 通过)

### 主张 1.2：感知驱动的动态失效机制在障碍清除时能恢复近路通行能力
- **主张内容**：在障碍清除场景（Scenario D2）下，通过传感器核验 `FREE` 状态触发动态失效，机器人重新选用短路，相比永久禁用近路的记忆基线（$M1$）节省 $\approx 11.0\%$ 行驶距离（$16.25\,\text{m}$ vs. $18.25\,\text{m}$）。
- **适用范围与失效边界**：在当前仿真样本下，平均总运行时间未见改善（$151.1\,\text{s}$ vs. $148.8\,\text{s}$，微增 $+1.5\%$）。轨迹时间账本实测表明：决策阶段耗时几乎完全相等（$51.10\,\text{s}$ vs. $51.30\,\text{s}$，仅差 $-0.20\,\text{s}$），总时间差主要来自历史探索阶段（$+2.47\,\text{s}$）；粗粒度分解显示 Path A 移动时间较少，但被门区子目标协商与停顿核验抵消；具体分量受离散化阈值影响。失效机理依赖静态门区 ROI 的传感器重获，尚未在动态移动障碍物上验证。
- **证据文件与哈希**：[`paper/draft.md`](../../paper/draft.md#L140-L141)，[`reports/evidence/d2_time_ledger/`](../../reports/evidence/d2_time_ledger/)

### 主张 1.3：大模型自然提取的候选规则表现为参数脆弱性与未泛化，而非跨资源过度泛化
- **主张内容**：大模型结构化提取倾向于将特定文件路径（如 `config_path=/home/agentuser/service_conf/app_t1.json`）硬编码至动作签名中。当相同冲突发生在其他文件名时，规则无法匹配（`action_matches_scope == False`）。候选规则未展现出跨端口或跨目录的过度泛化。
- **适用范围与失效边界**：基于 Qwen2.5-Coder-32B 在 12 种系统服务故障上的历史提取输出（Calls #2, #4, #6, #8, #10, #12, #16, #18, #20, #24）。
- **证据文件与哈希**：
  - 修订总账：[`results/candidate_ledger_24.json`](results/candidate_ledger_24.json)
  - 执行报告：[`results/natural_candidate_revised_report.md`](results/natural_candidate_revised_report.md#L43-L47)

### 主张 1.4：前置条件语义倒置会导致确凿的执行反例
- **主张内容**：第 10 次模型提取将源故障“配置文件不存在导致启动失败”倒置声称为“当 `config_file:exists == True` 时启动失败报文件不存在”。在模型指定的真实路径上创建文件使前置条件成立后执行启动，OS 返回 `exit_code: 0, success: True`，反例确凿成立。
- **适用范围与失效边界**：在真实 Linux OS 环境下执行，覆盖特定路径 `/home/agentuser/service_conf/nonexistent_cfg_999.json`。
- **证据文件与哈希**：
  - 核验账本：[`results/natural_candidate_revised_verification.json`](results/natural_candidate_revised_verification.json) (Call #10)
  - 回归测试：[`test_candidate_verification_regression.py`](test_candidate_verification_regression.py) (`test_precondition_true_and_action_succeeds_identifies_valid_counterexample`)

### 主张 1.5：缺失身份/属主上下文导致规则在属主环境下反例成立
- **主张内容**：第 4、24 次模型提取声称“目录权限 `0755` 导致写配置失败”。在 Linux 权限模型下，0755 赋予了属主完整的写权限。当在属主身份（`agentuser`）下执行写入时顺利成功（`exit_code: 0`）。规则遗漏了关键的 `owner_uid != user_uid` 条件，存在范围缺失（`SCOPE_DEFICIENT`）。
- **适用范围与失效边界**：在真实 Linux OS 环境下对 `/etc/service_demo` 进行属主变更与执行核验。
- **证据文件与哈希**：
  - 核验账本：[`results/natural_candidate_revised_verification.json`](results/natural_candidate_revised_verification.json) (Calls #4, #24)
  - 回归测试：[`test_candidate_verification_regression.py`](test_candidate_verification_regression.py)

---

## 二、受限证实主张 (Limited Confirmation Claims)

### 主张 2.1：候选试探机制在人工构造的错误假说案例中能避免动作误阻断
- **主张内容**：在 Case 5 人工构造错误规则（误称写入用户配置必败）的固定动作脚本中，候选放行试探使得写入动作得以执行，并在成功后将规则置为 `CONTRADICTED`。
- **限制与边界**：**仅能在特定构造的单步动作场景下成立**。该脚本未配置后续启动服务，整体任务依然失败（Fail）；不能证明自然 Agent 在开放任务中的端到端收益，亦不能证明机制的唯一性。
- **证据文件与哈希**：[`results/natural_candidate_cpu_comparison.json`](results/natural_candidate_cpu_comparison.json)

### 主张 2.2：S1 提示告警与 S2 轻量探针在测试案例中实现 0 假阳性误阻断
- **主张内容**：在评测案例中，S1 策略不施加门禁硬拦截（0 误阻断），S2 策略通过只读探针核验资源可行性并缓存（0 误阻断，探针调用计入 `tool_calls`）。
- **限制与边界**：S1 复用了生命周期管理器的跃迁与事实记录逻辑，属于同框架下的门禁放行简化策略（消融策略）；S2 依赖只读探针的存在性（只适用于存在轻量探针的 OS/物理资源），且缓存受限于单调时钟 TTL 与上下文绑定。
- **证据文件与哈希**：
  - 核心实现：[`multistep_agent_runner.py`](multistep_agent_runner.py#L753-L865)
  - 回归测试：[`test_candidate_verification_regression.py`](test_candidate_verification_regression.py) (`test_path_or_identity_change_does_not_erroneously_reuse_cache`, `test_ttl_expiry_and_resource_changes_trigger_reverification_and_invalidation`)

### 主张 2.3：反馈驱动重规划能避免固定回放队列中的假阳性死锁
- **主张内容**：当智能体具备根据工具执行返回值自愈重规划的能力时，即使面对错误的门禁拦截或执行报错，也能自主切换替代路径完成任务，使全部对比组任务完成率均达到 100%。
- **限制与边界**：仅在具备等价备用资源（如备用空闲端口、备用可写临时目录）的多步任务环境中成立；若环境中不存在替代资源，重规划无法凭空解决物理冲突。
- **证据文件与哈希**：[`results/runner_integration_events.json`](results/runner_integration_events.json)

---

## 三、未证实 / 暂不支持主张 (Unproven / Unsupported Claims)

### 主张 3.1：显式失败记忆 ($F$) 在静态 2D 几何障碍中优于空间观测缓存 ($O$)
- **状态**：**暂不支持 (Unsupported)**。
- **实测证据**：在 30 次 Gazebo 仿真运行中，$F$ 与 $O$ 选择了完全相同的拓扑路径，距离与耗时差异均 $<1\%$（D1 距离差异 $+0.6\%$，耗时 $+0.7\%$；D2 距离差异 $-0.9\%$，耗时 $+0.9\%$）。在当前静态 2D 几何布局和样本下，未观察到 $F$ 相比 $O$ 的额外收益。

### 主张 3.2：动作条件导航假设 ($H_1$) 会在开阔门区产生可执行性分化
- **状态**：**暂不支持 (Unsupported - Stopped per Protocol)**。
- **实测证据**：在 4 次可行性检查中，不同朝向目标动作在 Nav2 下均执行成功（4/4 成功，3/4 严格物理到达），`DWBLocalPlanner` 未出现规划失败，未建立动作可执行性差异。按照研究规程终止该假设探索。

### 主张 3.3：规则生命周期状态机 ($M$) 相对简单策略具备累积超额收益
- **状态**：**未证实 (Unproven)**。
- **实测证据**：在测试用例中，候选试探机制放行动作带来了真实的系统报错（Errno 98），其试探代价在后续任务中未被收回；S1 与 S2 等更简单策略以更低代价达到了相同或更优的容错效果。

### 主张 3.4：跨会话、跨 OS 重启的长期失败记忆索引与检索
- **状态**：**未证实 (Unproven - Outside Scope)**。
- **实测证据**：当前评测局限于单次运行会话内的阶段流转，尚未构建跨守护进程生命周期的持久化数据库。

---

## 四、已证伪 / 需撤回结论 (Refuted & Retracted Claims)

### 撤回 4.1：“12 条自然候选全部正确、0 条反例”
- **原表述**：历史报告曾声称大模型自然提取的 12 条结构化规则全部正确，无执行反例。
- **证伪证据**：历史核验器未在模型指定路径上执行测试。本轮严格核验在真实 OS 上证实：第 10 次输出确凿为反例（`COUNTEREXAMPLE`），第 4、24 次输出为上下文缺失（`SCOPE_DEFICIENT`）。该结论正式撤回并修正。

### 撤回 4.2：“模型表现出主动拒答能力”
- **原表述**：历史报告声称模型展现出对不确定故障的审慎性与主动拒答能力。
- **证伪证据**：在 12 次结构化提取调用中，大模型主动拒答次数实际为 **0 次 (0/12)**。0 次拒答不能被解读为具备拒答能力。该表述正式撤回。

### 撤回 4.3：“极少数反例集中于签名粒度”
- **原表述**：声称反例仅出现在签名匹配粒度。
- **证伪证据**：历史报告未提供任何反例测试日志。本轮实测确认核心缺陷为前置条件语义倒置与属主身份缺失。该断言正式撤回。

### 撤回 4.4：“S1/S2 已解决自然候选中的全部错误”
- **原表述**：将人工规则（Case 5）实验的表现外推至自然候选语料。
- **证伪证据**：人工构造案例不能代表自然候选分布。该外推主张正式撤回。

### 撤回 4.5：夸大性修辞表述
- **撤回清单**：“唯一可靠机制”、“绝对最优”、“表现最优”、“100%自愈”、“自主死锁”、“完全化解”、“不具备学术新颖性”、“不值得研究”。
- **修正原则**：全部改为客观事实陈述与数据呈现。

---

## 五、证据链与核心文件追溯索引

| 证据项类别 | 相对文件路径 | 校验哈希 / 测试结果 |
| :--- | :--- | :--- |
| **冻结证据清单** | `research/conditional_constraint_memory/results/frozen_evidence_manifest.json` | 包含 6 个历史文件 SHA256 清单 |
| **24条候选总账** | `research/conditional_constraint_memory/results/candidate_ledger_24.json` | 24 条分解明细 (12 Method A, 12 Method B) |
| **修订版执行核验** | `research/conditional_constraint_memory/results/natural_candidate_revised_verification.json` | 12 条 Method B 严格 OS 执行结果 |
| **CPU 机制实测对比** | `research/conditional_constraint_memory/results/natural_candidate_cpu_comparison.json` | 4 案例 5 分支确定性对比 |
| **回归测试套件** | `research/conditional_constraint_memory/test_candidate_verification_regression.py` | 16/16 项核心科学不变量回归测试全部通过 |
| **全量单测套件** | `research/conditional_constraint_memory/` | 70/70 项单元与集成测试全部通过 |
| **主仓库测试套件** | `tests/` | 191 通过，8 项预期 xfailed，0 失败 |
| **D2 轨迹时间账本** | `reports/evidence/d2_time_ledger/` | 12 轮三阶段闭合核算、27 点参数敏感性网格完整生成 |
| **ROS 2 论文手稿** | `paper/draft.md` | 完整 30 次仿真 + 4 次可行性检查报告 (PDF 10 页) |
