# 自然候选记忆修订版独立核验总账与研究去留报告

**核验时间**: 2026-10-12 09:17:24 UTC  
**算力消耗**: **新增 GPU 调用 = 0，新增模型 Token = 0，纯 Linux OS CPU 隔离核验**  
**总样本量**: 冻结的历史 24 次调用 (Method A: 12 条, Method B: 12 条)  

---

## 一、不可靠结论正式撤回与修正声明

在此正式撤回并降级前序轮次中未经严格检验的不实结论：
1. **撤回‘12条全部正确、0条反例’的结论**：
   - *事实*：前序核验器使用了 `app_test_v1.json`、`app_v4.json` 等合成路径，根本未在模型指定的真实路径上执行测试，且忽略了前置条件的因果有效性；
   - *修正*：经本轮在模型指定路径上的严格执行核验，**正式确认至少存在 1 条因前置条件语义倒置导致的真实执行反例（第 10 次输出），以及 2 条因缺失执行身份上下文导致在属主环境下反例成立的规则（第 4、24 次输出）**；
2. **撤回‘模型表现出主动拒答能力’的表述**：
   - *事实*：在 12 次结构化提取调用中，大模型的主动拒答数 (`NO_RULE`) **实际为 0 次 (0/12)**；0 次拒答不能被粉饰为‘具备证据审慎性’或‘能主动拒答不确定故障’；
3. **撤回‘极少数反例集中于签名粒度’的断言**：
   - *事实*：此前报告并未提供任何实际的反例测试日志，属于无证据的主观推测；
4. **撤回‘S1/S2 已解决自然候选中的全部错误’的泛化主张**：
   - *事实*：前序 S1/S2 实验使用的是人工构造的错误规则（Case 5），**绝不能将人工规则下的表现直接等价为解决了自然候选中的所有缺陷**；
5. **基线实现客观定性**：
   - S1 在代码实现中直接复用了 `ConstraintLifecycleManager` 的执行结果记录与有效性跃迁，**属于同一规则管理器基础上的门禁放行简化策略，而非独立从零构建的基线**；
   - S2 探针验证调用已正式计入 `tool_calls`，且缓存已绑定具体资源上下文与 30.0s TTL 有效期。

---

## 二、三个优先科学问题核验结论

### 1. 第 10 次输出核验：配置启动与谓词倒置反例
- **候选声明**：`ACTION: start_service(/home/.../nonexistent_cfg_999.json)`, `PRECONDITION: config_file:exists == True`, `FAILURE: 1 ('Config file not found')`；
- **源经历检查**：源故障是因为文件不存在 (`config_file_exists == False`) 导致启动失败。源经历**根本不满足候选声明的 premise (`exists == True`)**，判定为 **`SOURCE_PREMISE_MISMATCH`**；
- **真实反例执行核验**：在模型指定的同一路径 `/home/agentuser/service_conf/nonexistent_cfg_999.json` 上创建有效配置，绑定空闲端口 18082。此时前置条件 `config_file:exists == True` 成立 (`TRUE`)。执行相同动作 `start_service(...)`：
  - **实际执行结果**：`exit_code: 0, success: True, stderr: ''`；
  - **核验判定**：**`COUNTEREXAMPLE`**！模型提取的规则声称‘当文件存在时启动失败报配置不存在’，而真实 OS 执行证明当文件存在时启动完全成功！反例确凿成立。

### 2. 第 4、24 次输出核验：目录 mode=0755 与属主/用户上下文缺失
- **候选声明**：`ACTION: write_config(/etc/service_demo/app_sys.json)`, `PRECONDITION: dir:/etc/service_demo:permissions == 0755`, `FAILURE: 1 ('Permission denied')`；
- **因果充分性检验**：目录 `mode=0755` **完全不足以推出写入失败**！在 Linux 系统中，0755 赋予了属主完整的读写执行权限 (`rwxr-xr-x`)；
- **执行上下文测试**：
  - 在保持 `mode=0755` 不变的情况下，若写入由目录属主执行（例如 `agentuser` 写入属主为自身的 0755 目录，或将 `/etc/service_demo` 属主变更为 `agentuser`）：写入**顺利成功 (`exit_code: 0`)**；
  - **核验判定**：该规则存在严重的**上下文范围缺失 (`SCOPE_DEFICIENT`)**，遗漏了关键的 `owner_uid != user_uid` 条件；在属主环境下构成了因果反例 (`COUNTEREXAMPLE`)。

### 3. 所有绑定 config_path 的启动规则：路径替换与参数脆弱性
- 真实 OS 测试表明，大模型倾向于将文件名硬编码到动作签名中（如 `start_service:config_path=/home/.../app_t1.json`）；
- 当相同端口冲突在另一配置文件名（如 `app_t1_alternate.json`）上发生时，规则因签名过度特异而无法匹配 (`action_matches_scope == False`)；
- **结论**：自然提取规则不存在跨资源的过度泛化，反而普遍存在**参数特异性过强与迁移能力不足（Undergeneralization / Parameter Brittleness）**。

---

## 三、Method A 与 Method B 分项核算统计总表

### 1. 分项提取与核验总览 (总调用数 = 24，分母始终为 12)

| 提取方式 | 格式解析成功 | 语义可解释率 | 主动拒答数 | 确认执行反例数 | 范围缺失数 | 提取成功率定义 |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Method A (自然语言总结)** | 12/12 (100%) | 12/12 (100%) | 0/12 (0%) | 0 | 0 | 文本生成成功，但无法直接作为确定性门禁执行 |
| **Method B (结构化规则)** | 12/12 (100%) | 11/12 (91.7%) | 0/12 (0%) | **1 (倒置反例)** | **2 (上下文缺失)** | 仅 9/12 (75%) 在特定上下文中有效，未见拒答能力 |

### 2. Method B 12 条结构化候选规则修订版逐项核验明细

| 调用编号 | 目标工具 | 提取动作签名 | 声明前置条件 | 预期失败 | V1 原场景复现 | V2 前提解除/反例测试 | V3 无关属性变更 | V4 上下文与范围测试 | 最终修订判定 |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| #2 | `start_service` | `start_service:config_path=/h...` | `port:18080:occupied True` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | ACTION_SIGNATURE_OVERLY_SPECIFIC | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #4 | `write_config` | `write_config:config_path=/et...` | `dir:/etc/service_demo:permissions 0755` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | COUNTEREXAMPLE | **SCOPE_DEFICIENT (True Counterexample under Owner Context)** |
| #6 | `start_service` | `start_service:config_path=/h...` | `port:18081:occupied True` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | ACTION_SIGNATURE_OVERLY_SPECIFIC | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #8 | `write_config` | `write_config:config_path=/ro...` | `dir:/root:writable False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #10 | `start_service` | `start_service:config_path=/h...` | `config_file:exists True` | Code | SOURCE_PREMISE_MISMATCH | **COUNTEREXAMPLE** | SUPPORTED_IN_TESTED_CONTEXT | ACTION_SIGNATURE_OVERLY_SPECIFIC | **COUNTEREXAMPLE (Inverted Predicate Proven Infeasible)** |
| #12 | `start_service` | `start_service:config_path=/h...` | `config_path:/home/agentuser/service_conf/malformed.json:valid_json False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | ACTION_SIGNATURE_OVERLY_SPECIFIC | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #14 | `check_health` | `check_health:port=18085...` | `port:18085:listening False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #16 | `start_service` | `start_service:config_path=/h...` | `port:18080:occupied True` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | ACTION_SIGNATURE_OVERLY_SPECIFIC | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #18 | `write_config` | `write_config:config_path=/tm...` | `dir:/tmp/nonexistent_subfolder_xyz:exists False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #20 | `write_config` | `write_config:config_path=/ho...` | `file:/home/agentuser/service_conf/readonly_app.json:mode "0444"` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #22 | `check_health` | `check_health:port=18081...` | `port:18081:listening False` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | SUPPORTED_IN_TESTED_CONTEXT | **SUPPORTED_IN_TESTED_CONTEXT (Narrow Path Constraint)** |
| #24 | `write_config` | `write_config:config_path=/et...` | `dir:/etc/service_demo:permissions 0755` | Code | SUPPORTED_IN_TESTED_CONTEXT | **NOT_APPLICABLE** | SUPPORTED_IN_TESTED_CONTEXT | COUNTEREXAMPLE | **SCOPE_DEFICIENT (True Counterexample under Owner Context)** |

---

## 四、自然候选规则上的 CPU 机制对照实测

> **方法论说明**：本实验属于纯 CPU 确定性机制测试，用以核验门禁策略对自然提取规则的反应边界，不代表自主 LLM 在全开放任务中的端到端收益实验。

| 策略分支 | 面对倒置规则 (Call #10) 的动作执行 | 门禁是否误阻断 | 假阳性阻断 (FP) | 计费工具调用数 | 机制应对表现 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **B0 / B2 (无门禁)** | 正常执行 (`exit_code: 0`) | 否 | 0 | 1 | 凭借环境真实响应直接完成任务 |
| **B2-G (通用谓词门禁)** | 若规则加载入库则可能触发门禁求值 | 视谓词而定 | 0~1 | 1 | 缺乏对错误规则的甄别手段 |
| **S1 (经验告警仅提示)** | 正常执行 (`exit_code: 0`) | **否** | **0** | 1 | **表现稳健**：候选仅提示，不施加硬门禁，0 误阻断 |
| **S2 (受控探针并缓存)** | 探针核验文件存在且可读后放行 | **否** | **0** | 2 | **表现最优**：单次轻量 probe 确认可行性并放行 |
| **Method M (生命周期试探)** | 候选放行试探，成功后证伪规则 | **否** | **0** | 1 | 规则跃迁为 `CONTRADICTED`，依赖执行试探消除假说 |

---

## 五、一页最终研究决策 (Final Go/No-Go Decision)

### 决策边界对照：
- [x] **情况一：存在自然错误，但简单策略可以处理**
  - 实测确认：大模型自然生成的规则确实存在错误（第 10 次谓词倒置，第 4、24 次上下文缺失）；
  - 但这些错误**无需复杂的动态生命周期状态机即可被更简单的工程策略有效化解**：
    - S1（提示告警不硬阻断）彻底免疫此类倒置规则对正常路径的拦截；
    - S2（受控轻量探针与 TTL 缓存）以确定性只读检查核验目标资源，无需承受破坏性试探报错；
    - 反馈驱动重规划（Feedback-Driven Replanning）赋予 Agent 自发绕过阻断的能力，彻底消除了固定回放脚本的假阳性死锁；
- [ ] **情况二：存在自然错误，且简单策略存在不可替代的结构性缺陷**（不成立，未观察到 S1/S2 无法处理的自然死锁案例）。

### 【最终裁决：正式采纳 Option A】

> **1. 定位收敛**：正式将“规则生命周期状态机”降级为**次级工程维护组件（作为离线规则清洗与一致性维护工具）**，不再宣称为面向自主 Agent 运行时的核心学术方法突破或独立理论贡献；  
> **2. 架构定型**：主干智能体执行流水线全面收敛至 **B2-G（通用谓词门禁与主动探测）** 与 **S1 / S2（经验提示注入与轻量探针缓存）**；  
> **3. 研究课题正式闭环**：停止生成新候选、停止追加 GPU 资源、停止围绕人工构造规则扩大论证，全量代码与真实审计日志完整归档。  
