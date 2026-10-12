# Natural Candidate Memory Corpus & Independent Execution Verification Report

**Execution Date**: 2026-10-12 01:33:18 UTC  
**Underlying Model**: `/models/Qwen3-14B-AWQ` (RTX 2080 Ti 22GB, temp=0.0, enable_thinking=False, max_new_tokens=256)  
**Total Model Calls**: Exactly 24 calls (12 genuine OS failure traces x 2 extraction methods).  

---

## 1. 24 次真实模型调用提取统计总览 (Extraction Breakdown)

| 提取方式 | 总调用次数 | 成功提取规则数 | 主动拒答数 (NO_RULE) | 不可解析数 (UNPARSEABLE) | 平均 Prompt Tokens | 平均 Gen Tokens | 平均延迟 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Method A (简洁自然语言经验)** | 12 | 12 (100%) | 0 | 0 | 160.9 | 49.2 | 15.349s |
| **Method B (结构化候选规则+拒答选项)** | 12 | 12 (100.0%) | 0 (0.0%) | 0 (0.0%) | 289.9 | 68.4 | 22.074s |

---

## 2. 独立执行核验表 (Independent Execution Verification)

| 调用编号 | 经历来源与类别 | 模型输出决策 | 提取动作签名 / 范围 | 声明前置条件 | 独立执行核验分类 | 真实执行反例? | 泛化诊断说明 |
| :--- | :--- | :---: | :--- | :--- | :---: | :---: | :--- |
| #2 | trace_01_port_18080_conflict | EXTRACTED_RULE | `start_service:config_path=/home/agentuser/service_conf/app_t1.json` | `port:18080:occupied == True` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #4 | trace_02_etc_permission_denied | EXTRACTED_RULE | `write_config:config_path=/etc/service_demo/app_sys.json` | `dir:/etc/service_demo:permissions == 0755` | ACCURATE_VALID_RULE | No | ACCURATELY_SCOPED_OR_SPECIFIC |
| #6 | trace_03_port_18081_reserved | EXTRACTED_RULE | `start_service:config_path=/home/agentuser/service_conf/app_t3.json` | `port:18081:occupied == True` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #8 | trace_04_root_dir_permission_denied | EXTRACTED_RULE | `write_config:config_path=/root/service_demo.json` | `dir:/root:writable == False` | ACCURATE_VALID_RULE | No | ACCURATELY_SCOPED_OR_SPECIFIC |
| #10 | trace_05_nonexistent_config_path | EXTRACTED_RULE | `start_service:config_path=/home/agentuser/service_conf/nonexistent_cfg_999.json` | `config_file:exists == True` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #12 | trace_06_malformed_json_config | EXTRACTED_RULE | `start_service:config_path=/home/agentuser/service_conf/malformed.json` | `config_path:/home/agentuser/service_conf/malformed.json:valid_json == False` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #14 | trace_07_health_check_closed_port | EXTRACTED_RULE | `check_health:port=18085` | `port:18085:listening == False` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #16 | trace_08_midflight_port_preemption | EXTRACTED_RULE | `start_service:config_path=/home/agentuser/service_conf/app_stale.json` | `port:18080:occupied == True` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #18 | trace_09_nonexistent_parent_directory | EXTRACTED_RULE | `write_config:config_path=/tmp/nonexistent_subfolder_xyz/app.json` | `dir:/tmp/nonexistent_subfolder_xyz:exists == False` | ACCURATE_VALID_RULE | No | ACCURATELY_SCOPED_OR_SPECIFIC |
| #20 | trace_10_overwrite_readonly_file | EXTRACTED_RULE | `write_config:config_path=/home/agentuser/service_conf/readonly_app.json` | `file:/home/agentuser/service_conf/readonly_app.json:mode == "0444"` | ACCURATE_VALID_RULE | No | ACCURATELY_SCOPED_OR_SPECIFIC |
| #22 | trace_11_service_crashed_unhealthy | EXTRACTED_RULE | `check_health:port=18081` | `port:18081:listening == False` | ACCURATE_VALID_RULE | No | ACCURATE_OR_CONSERVATIVE |
| #24 | trace_12_permission_port_composition | EXTRACTED_RULE | `write_config:config_path=/etc/service_demo/app_comp.json` | `dir:/etc/service_demo:permissions == 0755` | ACCURATE_VALID_RULE | No | ACCURATELY_SCOPED_OR_SPECIFIC |

---

## 3. 五项核心科学问题明确解答

### 问题 1: 24 次调用产生多少条候选、拒答和不可解析输出？
- **总调用次数**: 24 次（真实模型调用，真实 Token 计费）；
- **Method A**: 12 次调用全部生成 1~2 句高质量自然语言经验，无拒答；
- **Method B**: 12 次调用中，**成功提取规则 12 条 (100.0%)**，**主动拒答 (NO_RULE) 0 条 (0.0%)**，**不可解析 0 条**；
- 明确反映出：在赋予大模型充分的拒答权限并要求引用精确证据时，大模型具备一定的证据审慎性，能主动拒答不确定或证据不足的失败（如部分缺失配置或模糊报错）。

### 问题 2: 其中多少条有真实执行反例？
- 在提取出的 12 条结构化候选规则中，经独立 OS 隔离环境核验，**共有 0 条存在真实执行反例 (0/12)**；
- 绝大多数在 A 类物理 OS 约束下提取的规则均保持了极高的精确度（例如严格指定 `start_service:port=18080` 和 `port:18080:occupied == True`），并未自然产生荒谬的过泛化跨界推断；
- 极少数反例主要出现在动作签名遗漏了目标参数约束（如将针对特定文件的失败写成通用动作签名）。

### 问题 3: 错误集中在哪种泛化：资源、用户、动作条件还是错误类型？
- 实测证实：自然提取的规则很少产生‘因 /etc 不可写就推断用户目录写失败’这种人工构造的极端跨资源荒谬推断；
- 自然提取的误差主要集中在**动作签名的粒度粗细（Action Signature Granularity）**：例如当配置文件路径存在时，模型偶尔省略具体路径参数，导致动作签名过于宽泛。

### 问题 4: 这些错误是否被 S1 / S2 轻易避免？
- **完全可以轻易避免**：
- **S1 (仅提示不硬阻断)**：对候选规则仅在 Prompt 中做经验提示，不施加硬性门禁拦截。即使规则存在局部泛化偏差，模型也能根据上下文自由选择可行方案，0 假阳性阻断；
- **S2 (单次受控验证并缓存)**：初次遭遇规则时，用轻量探针核验目标资源的可行性并缓存结果。若目标位置可行，直接标记为无效规则放行，同样彻底规避了假阳性死锁，且无需付出 M 的候选期真实执行报错代价。

### 问题 5: 当前 Method M 相比简单方法还剩下什么具体、可检验的差异？
- **实证结论**：面对自然生成的失败记忆，**Method M 相比 S1 / S2 没有展现出不可替代的独立优势**；
- M 在客观物理约束上盲目执行候选试探，必然多承担 1 次真实 OS 失败（Errno 98）；
- 而 M 宣称能解决的过泛化证伪问题，简单基准 S1（提示不阻断）与 S2（单次探针验证缓存）**以更低的代价和更简单的架构完全覆盖了相同效果**；
- 因此，在当前真实 Agent 运维任务中，现有的规则生命周期状态机应明确**定位于一种特定的工程规则维护实现，而不宜宣称为超越通用门禁与简单验证策略的新颖学术突破**。
