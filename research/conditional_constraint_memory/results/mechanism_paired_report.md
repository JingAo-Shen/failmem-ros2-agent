# CPU Paired Mechanism Experiments Report (B2-G vs M)

**Execution Date**: 2026-10-12 00:51:54 UTC  
**Environment**: Production MultiStepDeploymentEnv (Real Linux Sockets, Non-Root agentuser Permissions)  
**Runner**: Production MultiStepAgentRunner with ScriptedPolicyBackend  
**Evaluation Methodology**: Identical initial rules, observations, action sequences, and budgets for B2-G and M.  

---

## 1. 机制案例测试汇总对比表

| 案例编号与名称 | 类型 | B2-G 阻断 (TP/FP) | B2-G 执行错误 | M 试探放行 | M 执行错误 | M 状态迁移 | 最终结果 (B2-G / M) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **case_1**: Valid Candidate Rule, Blockage Persists | 常规机制 | 1 TP / 0 FP | 0 | 1 | 1 | 1 次 | Pass / Pass |
| **case_2**: Valid Rule, Premise Cleared | 常规机制 | 0 TP / 0 FP | 0 | 0 | 0 | 0 次 | Pass / Pass |
| **case_3**: Valid Rule, Irrelevant Attribute Changed | 常规机制 | 1 TP / 0 FP | 0 | 0 | 0 | 0 次 | Fail / Fail |
| **case_4**: Observation Expired, Premise Blocked After Refresh | 常规机制 | 1 TP / 0 FP | 0 | 0 | 0 | 0 次 | Fail / Fail |
| **case_5**: Overgeneralized Candidate Rule, Feasible Action (True Counter-Example) | 压力测试 (人工构造) | 0 TP / 1 FP | 0 | 1 | 0 | 1 次 | Fail / Fail |
| **case_6**: Conflicting or Poorly-Supported Candidate Rules | 压力测试 (人工构造) | 0 TP / 0 FP | 0 | 0 | 0 | 0 次 | Pass / Pass |

---

## 2. 逐案例详细机制剖析

### CASE_1: Valid Candidate Rule, Blockage Persists
- **测试目标与场景**: Port 18080 occupied. Candidate rule matches. B2-G blocks immediately (0 error); M allows candidate trial (1 OS error), then upgrades to SUPPORTED.
- **B2-G 表现**: TP阻断=1, FP阻断=0, 探针=0, 实际执行错误=0
- **Method M 表现**: 候选试探=1, TP阻断=0, 实际执行错误=1, 真实有效性跃迁=1
- **规则最终状态 (M)**: {"r_c1_port": {"validity_state": "SUPPORTED", "support_count": 2, "contradict_count": 0}}

### CASE_2: Valid Rule, Premise Cleared
- **测试目标与场景**: Port 18080 is free. Rule declared condition is False. Both B2-G and M evaluate NOT_APPLICABLE, allow execution, and succeed.
- **B2-G 表现**: TP阻断=0, FP阻断=0, 探针=0, 实际执行错误=0
- **Method M 表现**: 候选试探=0, TP阻断=0, 实际执行错误=0, 真实有效性跃迁=0
- **规则最终状态 (M)**: {"r_c2_port": {"validity_state": "SUPPORTED", "support_count": 3, "contradict_count": 0}}

### CASE_3: Valid Rule, Irrelevant Attribute Changed
- **测试目标与场景**: Config filename arbitrarily changed, but target port is still 18080. Normalized action signature matches rule; both B2-G and M block.
- **B2-G 表现**: TP阻断=1, FP阻断=0, 探针=0, 实际执行错误=0
- **Method M 表现**: 候选试探=0, TP阻断=1, 实际执行错误=0, 真实有效性跃迁=0
- **规则最终状态 (M)**: {"r_c3_port": {"validity_state": "SUPPORTED", "support_count": 3, "contradict_count": 0}}

### CASE_4: Observation Expired, Premise Blocked After Refresh
- **测试目标与场景**: Port 18080 observation is 60s old (TTL=30s -> UNKNOWN). start_service triggers PROBE, probe discovers port occupied, re-evaluation BLOCKS in both B2-G and M.
- **B2-G 表现**: TP阻断=1, FP阻断=0, 探针=1, 实际执行错误=0
- **Method M 表现**: 候选试探=0, TP阻断=1, 实际执行错误=0, 真实有效性跃迁=0
- **规则最终状态 (M)**: {"r_c4_port": {"validity_state": "SUPPORTED", "support_count": 3, "contradict_count": 0}}

### CASE_5: Overgeneralized Candidate Rule, Feasible Action (True Counter-Example)
- **测试目标与场景**: [STRESS TEST SYNTHETIC] Rule claims /etc unwritable -> writing /home/agentuser fails. Premise holds True in OS. B2-G FP blocks feasible action; M allows candidate trial, OS write succeeds, M downgrades rule to CONTRADICTED.
- **B2-G 表现**: TP阻断=0, FP阻断=1, 探针=0, 实际执行错误=0
- **Method M 表现**: 候选试探=1, TP阻断=0, 实际执行错误=0, 真实有效性跃迁=1
- **规则最终状态 (M)**: {"stress_overgeneralized_write": {"validity_state": "CONTRADICTED", "support_count": 1, "contradict_count": 1}}

### CASE_6: Conflicting or Poorly-Supported Candidate Rules
- **测试目标与场景**: [STRESS TEST SYNTHETIC] Rule A valid on 18080; Rule B spurious on 18081. Port 18081 probed free. Both B2-G and M evaluate Rule B as NOT_APPLICABLE and execute successfully.
- **B2-G 表现**: TP阻断=0, FP阻断=0, 探针=0, 实际执行错误=0
- **Method M 表现**: 候选试探=0, TP阻断=0, 实际执行错误=0, 真实有效性跃迁=0
- **规则最终状态 (M)**: {"r_c6_valid": {"validity_state": "SUPPORTED", "support_count": 3, "contradict_count": 0}, "stress_c6_spurious": {"validity_state": "CANDIDATE", "support_count": 1, "contradict_count": 0}}

---

## 3. 核心机制发现与对冲分析

1. **方法论边界说明**：
   - 本实验中的人工错误规则属于受控合成压力测试，**只能说明候选放行机制在特定构造案例中能避免错误阻断，不能证明自然 Agent 在开放任务中的独立收益、唯一性或不可替代性**；
   - 本实验全部基于 CPU 脚本策略测试桩运行，所有 token 字段均为模拟占位值 (`simulated`)；真实大模型调用与真实 token 开销均为 0；
2. **Case 1 暴露的 M 固有缺陷**：
   - 当候选规则是**正确且阻碍持续存在**的物理 OS 约束时，B2-G 凭借通用谓词直接精准拦截（0 次执行错误）；
   - 现有 M 的候选试探机制允许真实执行，**付出 1 次实际 OS 失败（Errno 98）的代价**；
3. **Case 5 表现与任务状态澄清（必须区分局部动作可行性与最终任务完成）**：
   - 当规则为人工构造的**过度泛化假规则**时（声明前提成立，但当前动作实际可行），B2-G 发生误阻断（FP Block = 1）；
   - M 凭借候选放行试探成功执行了写配置动作，并在 real OS 成功后**因果判定为反例，将假规则证伪降级为 CONTRADICTED**；
   - **必须明确区分局部动作可行性与任务完成**：Case 5 脚本仅包含目录探测与写配置动作，未包含启动服务与健康检查，因此 B2-G 与 M 最终的任务完成状态均为 Fail。M 实现了局部动作的可行性恢复与反例证伪，但并未在此脚本中完成端到端部署任务；
4. **反例判定的严谨性**：
   - Case 5 是真正的反例（前提确立为 True，动作真实在 OS 成功）；而 Case 2（前提解除后的成功）被正确识别为 NOT_APPLICABLE 正常放行，未被误判为反例。
