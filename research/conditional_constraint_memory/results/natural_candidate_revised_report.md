# 自然候选记忆修订版独立核验总账与研究去留报告

**核验时间**: 2026-10-13 02:32:04 UTC  
**算力消耗**: **新增 GPU 调用 = 0，新增模型 Token = 0，纯 Linux OS CPU 隔离核验**  
**总样本量**: 冻结的历史 24 次调用 (Method A: 12 条, Method B: 12 条)  

---

## 一、不可靠结论正式撤回与修正声明

在此正式撤回并降级前序轮次中未经严格检验的不实结论：
1. **撤回‘12条全部正确、0条反例’的结论**：
   - *事实*：前序核验器使用了合成路径，未在模型指定的真实路径上执行测试，且忽略了前置条件的因果有效性；
   - *修正*：经在模型指定路径上的严格执行核验，**确认至少存在 1 条因前置条件语义倒置导致的真实执行反例（第 10 次输出），以及 2 条因缺失执行身份上下文导致在属主环境下反例成立的规则（第 4、24 次输出）**；
2. **撤回‘模型表现出主动拒答能力’的表述**：
   - *事实*：在 12 次结构化提取调用中，大模型的主动拒答数 (`NO_RULE`) **实际为 0 次 (0/12)**；0 次拒答不能被粉饰为‘具备证据审慎性’或‘能主动拒答不确定故障’；
3. **撤回‘极少数反例集中于签名粒度’的断言**：
   - *事实*：此前报告并未提供任何实际的反例测试日志，属于无证据的主观推测；
4. **撤回‘S1/S2 已解决自然候选中的全部错误’的泛化主张**：
   - *事实*：前序 S1/S2 实验使用的是人工构造的错误规则（Case 5），**绝不能将人工规则下的表现直接等价为解决了自然候选中的所有缺陷**；
5. **基线实现客观定性**：
   - S1 在代码实现中直接复用了 `ConstraintLifecycleManager` 的执行结果记录与有效性跃迁，**属于同一规则管理器基础上的门禁放行简化策略（消融策略），而非独立从零构建的外部基线**；
   - S2 探针验证调用已正式计入 `tool_calls`，且缓存已绑定具体资源上下文、执行身份、环境实例与单调时钟 TTL 有效期；状态变更时触发相关缓存失效。

---

## 二、三个优先科学问题核验结论

### 1. 第 10 次输出核验：配置启动与谓词倒置反例
- **候选声明**：`ACTION: start_service(/home/.../nonexistent_cfg_999.json)`, `PRECONDITION: config_file:exists == True`, `FAILURE: 1 ('Config file not found')`；
- **源经历检查**：源故障是因为文件不存在 (`config_file:exists == False`) 导致启动失败。源经历**根本不满足候选声明的 premise (`exists == True`)**，判定为 **`SOURCE_PREMISE_MISMATCH`**；
- **真实反例执行核验**：在模型指定的同一路径 `/home/agentuser/service_conf/nonexistent_cfg_999.json` 上创建有效配置，绑定空闲端口 18082。此时前置条件 `config_file:exists == True` 经独立 OS 检查成立 (`TRUE`)。执行相同动作 `start_service(...)`：
  - **实际执行结果**：`exit_code: 0, success: True, stderr: ''`；
  - **核验判定**：**`COUNTEREXAMPLE`**！模型提取的规则声称‘当文件存在时启动失败报配置不存在’，而真实 OS 执行证明当文件存在时启动完全成功！反例确凿成立。

### 2. 第 4、24 次输出核验：目录 mode=0755 与属主/用户上下文缺失
- **候选声明**：`ACTION: write_config(/etc/service_demo/app_sys.json)`, `PRECONDITION: dir:/etc/service_demo:permissions == 0755`, `FAILURE: 1 ('Permission denied')`；
- **因果充分性检验**：目录 `mode=0755` **不足以推出写入失败**！在 Linux 系统中，0755 赋予了属主完整的读写执行权限 (`rwxr-xr-x`)；
- **执行上下文测试**：
  - 在保持 `mode=0755` 不变的情况下，若写入由目录属主执行（例如 `agentuser` 写入属主为自身的 0755 目录，或将 `/etc/service_demo` 属主变更为 `agentuser`）：写入**顺利成功 (`exit_code: 0`)**；
  - **核验判定**：该规则存在**上下文范围缺失 (`SCOPE_DEFICIENT`)**，遗漏了关键的 `owner_uid != user_uid` 条件；在属主环境下构成了因果反例 (`COUNTEREXAMPLE`)。

### 3. 所有绑定 config_path 的启动规则：路径替换与参数脆弱性
- 真实 OS 测试表明，大模型倾向于将文件名硬编码到动作签名中（如 `start_service:config_path=/home/.../app_t1.json`）；
- 当相同端口冲突在另一配置文件名（如 `app_t1_alternate.json`）上发生时，规则因签名过度特异而无法匹配 (`action_matches_scope == False`)；
- **结论**：自然提取规则不存在跨资源的过度泛化，核心表现为**参数特异性过强与迁移能力不足（Undergeneralization / Parameter Brittleness）**。

---

## 三、Method A 与 Method B 分项核算统计总表

### 1. 分项提取与核验总览 (总调用数 = 24，分母始终为 12)

| 提取方式 | 格式解析成功 | 语义可解释率 | 主动拒答数 | 确认执行反例数 | 范围缺失数 | 提取成功率定义 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Method A (自然语言总结)** | 12/12 (100%) | 12/12 (100%) | 0/12 (0%) | **未评估** | **未评估** | 文本生成成功，但未进行形式化门禁执行核验 |
| **Method B (结构化规则)** | 12/12 (100%) | 11/12 (91.7%) | 0/12 (0%) | **1 (倒置反例)** | **2 (上下文缺失)** | 经测试仅 9/12 (75.0%) 在特定窄上下文中有效 |

> **统计口径定义说明**：
> - **格式解析成功率**：输出满足对应 JSON/文本结构并能被解析器读取的比例 (A: 12/12, B: 12/12)；
> - **确认执行反例数**：在独立 OS 状态确认前置条件为 TRUE 且动作成功执行以否定声明失败的规则数 (B: 1 条，Call #10)；Method A 未进行确定性门禁执行核验，严格记为‘未评估’，不写 0；
> - **范围缺失数**：因缺少关键身份/环境约束而在特定合法上下文（如属主身份）下产生反例的规则数 (B: 2 条，Call #4, #24)；
> - **有效比例 (75.0%)**：12 条 Method B 候选规则中，排除 1 条倒置反例与 2 条范围缺失规则后，剩余 9 条在原特定狭窄路径下复现失败且前提解除后动作可行的规则数 (9/12)。

### 2. Method B 12 条结构化候选规则修订版逐项核验明细

| 调用编号 | 目标工具 | 提取动作签名 | 声明前置条件 | 预期失败 | V1 原场景复现 | V2 前提探针/反例测试 | V3 无关属性变更 | V4 上下文与范围测试 | 最终修订判定 |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| #2 | `start_service` | `start_service:config_path=/h...` | `port:18080:occupied True` | Code | SUPPORTED_IN_TESTED_CONTEXT | **SOURCE_PREMISE_MISMATCH** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #4 | `write_config` | `write_config:config_path=/et...` | `dir:/etc/service_demo:permissions 0755` | Code | SUPPORTED_IN_TESTED_CONTEXT | **ACTION_SIGNATURE_OVERLY_SPECIFIC** | SUPPORTED_IN_TESTED_CONTEXT | COUNTEREXAMPLE | **SCOPE_DEFICIENT (Counterexample under Owner Context)** |
| #6 | `start_service` | `start_service:config_path=/h...` | `port:18081:occupied True` | Code | SUPPORTED_IN_TESTED_CONTEXT | **SOURCE_PREMISE_MISMATCH** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #8 | `write_config` | `write_config:config_path=/ro...` | `dir:/root:writable False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **ACTION_SIGNATURE_OVERLY_SPECIFIC** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #10 | `start_service` | `start_service:config_path=/h...` | `config_file:exists True` | Code | SOURCE_PREMISE_MISMATCH | **COUNTEREXAMPLE** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **COUNTEREXAMPLE (Inverted Predicate Proven Infeasible)** |
| #12 | `start_service` | `start_service:config_path=/h...` | `config_path:/home/agentuser/service_conf/malformed.json:valid_json False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **SOURCE_PREMISE_MISMATCH** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #14 | `check_health` | `check_health:port=18085...` | `port:18085:listening False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **ACTION_SIGNATURE_OVERLY_SPECIFIC** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #16 | `start_service` | `start_service:config_path=/h...` | `port:18080:occupied True` | Code | SUPPORTED_IN_TESTED_CONTEXT | **SOURCE_PREMISE_MISMATCH** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #18 | `write_config` | `write_config:config_path=/tm...` | `dir:/tmp/nonexistent_subfolder_xyz:exists False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **ACTION_SIGNATURE_OVERLY_SPECIFIC** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #20 | `write_config` | `write_config:config_path=/ho...` | `file:/home/agentuser/service_conf/readonly_app.json:mode "0444"` | Code | SUPPORTED_IN_TESTED_CONTEXT | **SOURCE_PREMISE_MISMATCH** | SOURCE_PREMISE_MISMATCH | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #22 | `check_health` | `check_health:port=18081...` | `port:18081:listening False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **ACTION_SIGNATURE_OVERLY_SPECIFIC** | SOURCE_PREMISE_MISMATCH | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT** |
| #24 | `write_config` | `write_config:config_path=/et...` | `dir:/etc/service_demo:permissions 0755` | Code | SUPPORTED_IN_TESTED_CONTEXT | **ACTION_SIGNATURE_OVERLY_SPECIFIC** | SUPPORTED_IN_TESTED_CONTEXT | COUNTEREXAMPLE | **SCOPE_DEFICIENT (Counterexample under Owner Context)** |

---

## 四、自然候选规则上的真实策略 CPU 对照实测

> **输入账本来源与 SHA256**: `/code/failmem-ros2-agent/research/conditional_constraint_memory/results/candidate_ledger_24.json` (SHA256: `317c2766e919739e87918846583cf05438e996b3a74a45fef28edd1844c9e998`)  
> **方法论说明**: 本实验属于纯 CPU 确定性机制测试，用以核验门禁策略对自然提取规则的反应边界，不代表自主 LLM 在全开放任务中的端到端收益实验。

### 1. 历史原始候选实测对比结果 (Raw Historical Candidates)

| 评测案例 | 类别 | 策略分支 | 门禁决策 | 动作执行 | 动作成功 | 假阳性阻断 (FP) | 计费调用数 | 跃迁数 | 耗时(s) | 机制应对评价 |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| Call #10 Raw Candidate: star... | `RAW_CANDIDATE` | **B2** | ALLOW | 已执行 | 成功 | 0 | 1 | 0 | 0.237s | 无门禁拦截，依据环境执行结果自愈 |
| Call #10 Raw Candidate: star... | `RAW_CANDIDATE` | **B2-G** | BLOCK | 未执行 | 未成功 | 1 (FP) | 1 | 0 | 0.188s | 通用谓词门禁求值；在倒置规则上未预先甄别 |
| Call #10 Raw Candidate: star... | `RAW_CANDIDATE` | **S1** | ALLOW | 已执行 | 成功 | 0 | 1 | 1 | 0.244s | 提示策略不实施硬阻断，0 误阻断（注：不代表 LLM 端到端规划能力） |
| Call #10 Raw Candidate: star... | `RAW_CANDIDATE` | **S2** | ALLOW | 已执行 | 成功 | 0 | 3 | 0 | 0.257s | 受控探针核验资源可行性并缓存，0 误阻断 |
| Call #10 Raw Candidate: star... | `RAW_CANDIDATE` | **M** | ALLOW | 已执行 | 成功 | 0 | 2 | 1 | 0.235s | 试探执行后捕获反例，产生 1 次状态跃迁 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **B2** | ALLOW | 已执行 | 未成功 | 0 | 1 | 0 | 0.123s | 无门禁拦截，依据环境执行结果自愈 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **B2-G** | BLOCK | 未执行 | 未成功 | 0 | 1 | 0 | 0.120s | 门禁拦截 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **S1** | ALLOW | 已执行 | 未成功 | 0 | 1 | 1 | 0.126s | 提示策略不实施硬阻断，0 误阻断（注：不代表 LLM 端到端规划能力） |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **S2** | BLOCK | 未执行 | 未成功 | 0 | 1 | 0 | 0.134s | 受控探针核验资源可行性并缓存，0 误阻断 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **M** | ALLOW | 已执行 | 未成功 | 0 | 2 | 1 | 0.121s | 试探执行后捕获反例，产生 1 次状态跃迁 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **B2** | ALLOW | 已执行 | 成功 | 0 | 1 | 0 | 0.134s | 无门禁拦截，依据环境执行结果自愈 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **B2-G** | BLOCK | 未执行 | 未成功 | 0 | 1 | 0 | 0.119s | 门禁拦截 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **S1** | ALLOW | 已执行 | 成功 | 0 | 1 | 1 | 0.130s | 提示策略不实施硬阻断，0 误阻断（注：不代表 LLM 端到端规划能力） |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **S2** | ALLOW | 已执行 | 成功 | 0 | 2 | 0 | 0.128s | 受控探针核验资源可行性并缓存，0 误阻断 |
| Call #4 Raw Candidate: write... | `RAW_CANDIDATE` | **M** | ALLOW | 已执行 | 成功 | 0 | 2 | 1 | 0.135s | 试探执行后捕获反例，产生 1 次状态跃迁 |
| Call #2 Raw Candidate: start... | `RAW_CANDIDATE` | **B2** | ALLOW | 已执行 | 未成功 | 0 | 1 | 0 | 0.263s | 无门禁拦截，依据环境执行结果自愈 |
| Call #2 Raw Candidate: start... | `RAW_CANDIDATE` | **B2-G** | BLOCK | 未执行 | 未成功 | 0 | 1 | 0 | 0.187s | 门禁拦截 |
| Call #2 Raw Candidate: start... | `RAW_CANDIDATE` | **S1** | ALLOW | 已执行 | 未成功 | 0 | 1 | 1 | 0.245s | 提示策略不实施硬阻断，0 误阻断（注：不代表 LLM 端到端规划能力） |
| Call #2 Raw Candidate: start... | `RAW_CANDIDATE` | **S2** | BLOCK | 未执行 | 未成功 | 0 | 2 | 0 | 0.187s | 受控探针核验资源可行性并缓存，0 误阻断 |
| Call #2 Raw Candidate: start... | `RAW_CANDIDATE` | **M** | ALLOW | 已执行 | 未成功 | 0 | 2 | 1 | 0.261s | 试探执行后捕获反例，产生 1 次状态跃迁 |
| Call #14 Raw Candidate: chec... | `RAW_CANDIDATE` | **B2** | ALLOW | 已执行 | 未成功 | 0 | 1 | 0 | 0.171s | 无门禁拦截，依据环境执行结果自愈 |
| Call #14 Raw Candidate: chec... | `RAW_CANDIDATE` | **B2-G** | BLOCK | 未执行 | 未成功 | 0 | 1 | 0 | 0.175s | 门禁拦截 |
| Call #14 Raw Candidate: chec... | `RAW_CANDIDATE` | **S1** | ALLOW | 已执行 | 未成功 | 0 | 1 | 1 | 0.175s | 提示策略不实施硬阻断，0 误阻断（注：不代表 LLM 端到端规划能力） |
| Call #14 Raw Candidate: chec... | `RAW_CANDIDATE` | **S2** | BLOCK | 未执行 | 未成功 | 0 | 1 | 0 | 0.183s | 受控探针核验资源可行性并缓存，0 误阻断 |
| Call #14 Raw Candidate: chec... | `RAW_CANDIDATE` | **M** | ALLOW | 已执行 | 未成功 | 0 | 2 | 1 | 0.177s | 试探执行后捕获反例，产生 1 次状态跃迁 |

### 2. 衍生规则压力测试 (Derived Rule Stress Tests)

> **说明**: 本小节评估将历史原始候选（如 `/etc/service_demo/...` 系统目录规则）改写为用户目录（`/home/agentuser/...`）等变体后的衍生规则，用于压力测试谓词是否在用户属主目录下因缺失执行身份约束而发生失效。不可与原始历史候选混淆。

| 衍生测试案例 | 类别 | 策略分支 | 门禁决策 | 动作执行 | 动作成功 | 假阳性阻断 (FP) | 计费调用数 | 跃迁数 | 耗时(s) | 机制应对评价 |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| Call #4 Derived Rule Stress ... | `DERIVED_RULE_STRESS` | **B2** | ALLOW | 已执行 | 成功 | 0 | 1 | 0 | 0.182s | 无门禁拦截，动作在属主目录下成功执行 |
| Call #4 Derived Rule Stress ... | `DERIVED_RULE_STRESS` | **B2-G** | BLOCK | 未执行 | 未成功 | 1 (FP) | 1 | 0 | 0.183s | 通用谓词门禁求值；mode 0755 成立导致硬拦截 (FP) |
| Call #4 Derived Rule Stress ... | `DERIVED_RULE_STRESS` | **S1** | ALLOW | 已执行 | 成功 | 0 | 1 | 1 | 0.196s | 提示告警放行，0 误阻断 |
| Call #4 Derived Rule Stress ... | `DERIVED_RULE_STRESS` | **S2** | ALLOW | 已执行 | 成功 | 0 | 2 | 0 | 0.203s | 探针探测用户目录属主可写，放行执行，0 误阻断 |
| Call #4 Derived Rule Stress ... | `DERIVED_RULE_STRESS` | **M** | ALLOW | 已执行 | 成功 | 0 | 2 | 1 | 0.199s | 试探执行成功，发现属主反例产生 1 次状态跃迁 |

---

## 五、一页研究去留决策 (Final Decision)

### 实证事实依据：
1. **大模型自然生成的候选确实存在缺陷**：确认 1 条谓词语义倒置反例（Call #10）与 2 条上下文范围缺失规则（Call #4, #24）；核心表现为参数特异性过强与未泛化，未见跨资源的过度泛化。
2. **简单策略在受控范围内的有效性**：
   - S1 提示策略不实施硬阻断，完全避免了此类错误规则导致的执行前误拦截；
   - S2 结合轻量只读探针核验与单调时钟 TTL 缓存，以受控成本确认资源状态；
   - 反馈驱动重规划（Feedback-Driven Replanning）赋予智能体在工具报错后自愈的能力，排除了固定回放脚本带来的假阳性死锁。

### 【项目工程选择：正式采纳 Option A】

> **决策声明**：  
> “在目前测试范围内，尚未证明生命周期机制相对简单策略具有额外收益，因此暂停将其作为核心方法继续投入。”  
>  
> **执行路径**：  
> 1. **主干流水线定型**：执行链路保留通用谓词门禁、主动探测与提示告警，规则生命周期状态机降级为离线维护组件；  
> 2. **边界清晰归档**：历史 24 次调用作为来源受限的案例审计保留归档，不作为自然错误分布的基准数据集；  
> 3. **算力与调用冻结**：停止追加模型调用与 GPU 实验，全套代码、测试与账本保持冻结。  
