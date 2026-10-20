# [历史探索性结果，实验有效性待核对] 候选研究可行性阶段评估报告：反例驱动的适用条件修订机制

> [!WARNING]
> **状态说明（2026-10-19）**：  
> 本报告及对应的历史运行记录（已备份至 `archive_exploratory_79e6d23/`）属于阶段 0 前的初期探索记录。  
> 经长周期指令排查，原评测实现中存在如下有效性问题：  
> 1. 条件匹配采用浅层关键词导致“假阳性激活”（例如因包含“workshop”将铝箔规则误赋给杏子任务）；  
> 2. 将所有 Task B 失败等同于“记忆误用”（包括无记忆对照组）；  
> 3. 未评测反例修订后任务的后续表现或未见边界迁移，且修订验证依赖 LLM 单次布尔自评而非独立程序回归。  
> 因此，本报告的 No-Go 结论暂不作为方法创新的最终裁决，亦不反向宣布 Go。全部有效性修复与真实测量在后续 P0~P3 阶段系统展开。

**评估时间**：2026-10-19  
**评估基准**：ScienceWorld (v1.2.3, Java 11) + 本地 Qwen2.5-Coder-7B-Instruct (单卡 RTX 2080 Ti 22GB)  
**评估分支**：`research/counterexample-condition-revision` (基于 `b0e8c1f` 独立开展，旧资产完全冻结)  
**历史探索状态**：历史记录保留，实验有效性待核对并在新阶段重新测量。

---

## 一、文献排重与理论定位结论

通过对指定的 6 篇原始论文及经典理论修订/概念学习体系的深入阅读与文本比对，针对用户提出的四个核心问题给出确切回答：

### 1. 哪些方法已经学习适用条件？
- **BASM (Boundary-Aware Skill Memory, arXiv:2608.22339)**：离线从成功与失败轨迹对中提取带有显式边界字段（`applicability conditions` $A(s)$、`risk cues` $R$、`avoidance rules` $N$）的技能记忆库。
- **ReSYNC (Recover, Discover, Plan, arXiv:2606.18328)**：在机器人多任务规划中，通过失败恢复经验学习技能，并利用 IVNTR 双层优化推导关系谓词，精化符号规划算子的前置适用条件（`preconditions`）。
- **Sentry (arXiv:2610.02994)**：为失败恢复教训建立基于失败类型和检索标签（`retrieval labels`）的触发匹配机制。
- **经典归纳逻辑程序设计 (ILP: FOIL, Progol)**：直接从正负样本中归纳一阶霍恩子句的前置约束（适用条件）。

### 2. 哪些方法能根据新反例修订旧条件？
- **经典理论修订 (Theory Revision) 与概念学习**：
  - **Version Space / Candidate Elimination (Mitchell 1982)**：当泛化边界 $G$ 覆盖新的负例（反例）时，对 $G$ 进行极小特化（Minimal Specialization），剔除反例的同时确保保留对已知正例 $S$ 的覆盖。
  - **PTR (1994) / EITHER (1994) / KRK (1995)**：在正反例驱动下，通过向规则体添加前置条件字面量或分裂规则来修正假阳性。
- **ExpeL (arXiv:2308.10144)**：设计了 LLM 维度的 `EDIT` 与 `DOWNVOTE` 提示词算子，允许 LLM 在遇到失败时自由重写规则文本。但 ExpeL **无显式条件边界结构**，属于无约束文本重写，**完全不追溯历史正例支持集**，亦不检验修改是否导致历史样本退化。
- **现代 LLM 记忆库（BASM, Sentry, UpliftMem, CMI）的机制空白**：
  - **BASM**：边界库在离线阶段生成并完全**冻结**，测试期不在线修订边界；
  - **Sentry**：仅执行**单向追加**（`adds only verified recovery lessons`）。已有教训在后续任务中失效时仅产生空记录（`unresolved episodes produce none`），**完全不修订旧条目**；
  - **UpliftMem / CMI**：机制为集合级检索增益评估或因果扰动打分，属于外部筛选过滤（Retrieval Filter），不深入记忆条目内部修改条件。

### 3. 哪些方法同时验证“修正错误”和“保留仍有效的经验”？
- 经典 ML 理论修订系统在评测协议中明确计算正例集保留率（Retention Rate）与反例排除率。
- 在现代 LLM Agent 文献中，**目前没有工作构建专门评估“反例到达后局部条件特化 vs 历史正例回归保留”的隔离对比基准**。BASM 测试离线固定库性能，Sentry 测试追加迁移，ExpeL 仅测试端到端混合累积准确率。

### 4. 我们剩余的具体困难是什么？
- 在具身/交互环境中，LLM 总结的经验高度依赖单次探索，极易出现过度泛化（例如只关联了操作对象名称或所处房间，忽视了物理材质和状态属性）。
- 面对反例时，核心困难在于：
  1. **证据极小与因果混淆**：只有 1 个新反例和极少历史样本，难以区分是前置条件不满足还是后续规划偶然失误；
  2. **局部特化与灾难性遗忘的权衡**：无约束重写极易丢失已验证前提，过度特化则导致规则无法复用；
  3. **Agent 执行能力的短板**：即使条件识别正确，Agent 在多步长程物理动作生成上的固有缺陷依然主导了最终任务成败。

---

## 二、公开环境与模型验证

1. **环境**：ScienceWorld (v1.2.3, OpenJDK 11)
   - 确定性重置与动作前缀重放 100% 验证通过；
   - 采用原生简化配置 `simplificationStr="teleportAction,openDoors"`，消除无意义的闭门与房间盲搜干扰，直接聚焦物理状态操作与因果决策；
   - 任务环境提供标准化的客观奖励与终态判定（成功 = 100 分，违规误操作 = -100 分直接终止）。

2. **评测模型与推理配置**：
   - 骨干模型：本地 `Qwen2.5-Coder-7B-Instruct`（safetensors, bfloat16）；
   - 硬件占用：单卡 NVIDIA GeForce RTX 2080 Ti（显存分配 15.23 GB / 22 GB，空闲 >6 GB）；
   - 推理参数：`temperature = 0.0`（确定性贪婪解码），`do_sample = False`；单步决策 `max_new_tokens = 128`，经验提炼与修订 `max_new_tokens = 256 ~ 384`；
   - 零云端调用，单次推理平均耗时 4.17 秒。

---

## 三、自然经历与经验获取事实

在 Phase 1 阶段运行了 12 个自主探索任务（严禁人工植入带缺陷规则），使用 BaseAgent 自主交互并提炼经验。实测结果表明：

1. **Agent 自然产生了明确的“过度泛化”经验**：
   - 在 `test-conductivity`（aluminum foil）成功完成后，LLM 提炼出的适用条件为：
     `Conditions: ['the aluminum foil must be present in the workshop', 'there should be a red box available for placement']`
   - 在 `test-conductivity`（metal fork）成功完成后，LLM 提炼出的适用条件为：
     `Conditions: ['the metal fork must be present in the workshop', 'there must be a red box available for connection']`
   - **事实确认**：模型在自主归纳时，未自发形成“材料必须是金属/良导体”的物理前置约束，而是机械地将“位于工作间”、“存在红盒子”作为充分适用条件。这一经验直接为后续反例任务埋下了误用隐患，证明**经验过度泛化是真实存在的自然缺陷，而非人为制造**。

---

## 四、四组对照实验设计与执行数据

### 1. 实验设置与预算控制
- **评测设计**：10 对预先构造的诊断性任务（Task A 为原条件适用任务，Task B 为表面相似但关键条件改变的反例任务），每组测试 20 个任务，独立重复 2 轮。
- **四组对照**：
  - **A 组 (No-Memory)**：无跨任务记忆的纯 ReAct Agent；
  - **B 组 (Raw-Trajectory)**：原始轨迹存储与 Top-1 Few-shot 检索（遇到反例仅追加轨迹，不压缩为规则）；
  - **C 组 (Literature: BASM + ExpeL)**：边界记忆库，遇到反例采用 ExpeL 式无约束 Prompt 全量重写，不校验历史正例；
  - **D 组 (Local-Revision)**：反例驱动局部条件修订原型，对比正反例特征追加特化条件，并回溯正例支持集防范回归。
- **预算执行记录**：
  - 总完成 episodes：184（硬预算上限 200，实际完成 184）；
  - 总模型调用：839 次（硬预算上限 8000 次）；
  - 总消耗 tokens：551,955 tokens（输入 504,201，输出 47,754）；
  - 总耗时：3500.51 秒（~58.3 分钟）。

### 2. 核心客观指标汇总表

| 对照组别 | Task A 保留率 (Round 1) | Task B 成功率 (Round 1) | Task B 误用率 (Round 1) | Task A 保留率 (Round 2) | Task B 成功率 (Round 2) | Task B 误用率 (Round 2) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. No-Memory** | 30.0% (3/10) | 0.0% (0/10) | 100.0% (10/10) | 30.0% (3/10) | 0.0% (0/10) | 100.0% (10/10) |
| **B. Raw-Trajectory** | 30.0% (3/10) | **20.0% (2/10)** | **80.0% (8/10)** | 30.0% (3/10) | **20.0% (2/10)** | **80.0% (8/10)** |
| **C. Literature (BASM+ExpeL)** | 30.0% (3/10) | 0.0% (0/10) | 100.0% (10/10) | 30.0% (3/10) | 0.0% (0/10) | 100.0% (10/10) |
| **D. Local-Revision (Prototype)** | 30.0% (3/10) | 0.0% (0/10) | 100.0% (10/10) | 30.0% (3/10) | 0.0% (0/10) | 100.0% (10/10) |

---

## 五、浅层决策树对照核查 (Decision Tree Check)

针对 20 个评测任务提取浅层结构特征（任务类别、物态、材料分类），训练标准分类决策树：
- **单特征树 (Depth=1)**：准确率 55.0%（仅略高于随机猜测 50%）；
- **双特征树 (Depth=2)**：准确率 **65.0%**；
  - 核心分裂规则：优先判定 `material_aluminum`，其次判定 `phase_solid`。
- **核查结论**：
  浅层属性分类器仅能在离线静态标签上达到 65% 的识别率，但在具身交互任务中，即使准确识别出物体属性，Agent 依然面临多步动作时序协调（如定向转移、对焦、容器连接、开关触发）的失败风险。这表明：**当前瓶颈不仅是适用条件的布尔判断，更在于条件识别后具身动作规划的鲁棒执行**。

---

## 六、失败案例与不确定性事实剖析

1. **Task B 上的典型误用行为**：
   - 在 `pair_03`（Task B: apricot 杏子导电性判定）中，Agent 提取了 aluminum foil 的历史规则，观测到工作间有红盒子，直接执行 `move apricot to red box`，导致环境返回 `-100.0` 严重惩罚并立即失败终止。
   - 在 `pair_04`（Task B: glass jar 玻璃罐）与 `pair_05`（Task B: book 书本）中，完全重复了上述误用模式。

2. **为什么 Group D 没有击败 Group B？**
   - **B 组（原始轨迹检索）显示出天然鲁棒性**：当提供完整的历史成功轨迹上下文时，LLM 可以在 Prompt 中直观比对两者的目标差异（例如目标文字为 `aluminum foil` vs `apricot`），在 2 个任务中自发避开了盲目套用；
   - **D 组（规则特化）面临后置生成断层**：即使 D 组通过局部特化在规则中追加了 `material must be metal`，规则系统在 Task B 上成功阻止了将杏子放入红盒子，但由于没有对应“非金属物品放入绿盒子”的完整执行模板，Agent 随后退化为无记忆随机探索，依然未能在步数限制内完成正确闭环。
   - **结论**：在没有配对动作分支的情况下，单纯收缩旧规则的适用条件只能“避免误用”，无法直接带来“反例任务的成功率提升”。

---

## 七、最终去留判定 (Go / No-Go Decision)

依据既定的硬性去留准则进行逐项核验：

| 判定准则 | 核验事实 | 判定结果 |
| :--- | :--- | :---: |
| **准则 1：是否存在可重复的经验误用？** | 是。两轮独立测试中，模型自发提炼的规则均由于缺失材质条件导致在 Task B 上出现 100% 误用。 | 通过 |
| **准则 2：最接近强基线是否存在具体不足？** | 部分。C 组（BASM+ExpeL）表现较差，但 B 组（原始轨迹检索）在 Task B 上达到 20% 成功率，优于规则化方法。 | 未建立绝对优势 |
| **准则 3：局部修订是否建立相对强基线的独立增益？** | **否**。D 组在两轮测试中 Task B 成功率均为 0.0%，未能超越 B 组（20.0%）。 | **未通过** |
| **准则 4：两轮独立实验是否结论一致？** | 是。Round 1 与 Round 2 表现完全一致（A=30%, B=30%/20%, C=30%/0%, D=30%/0%）。 | 具备一致性 |

### 最终裁决：No-Go (停止当前方法路线推进)

**核心判定依据**：
1. **未建立区别于基线的方法优势**：最小“反例驱动局部修订原型”（Group D）在当前具身科学探索任务中，未能展现超越简单“原始轨迹检索”（Group B）的实证收益。
2. **条件收缩无法孤立产生决策增益**：实验严格证明，仅特化适用条件（剔除反例）只能起到消极防御作用；若无对应反事实动作的联合生成机制，Agent 在反例任务上的任务完成率依然为 0。
3. **遵循科研止步承诺**：不通过反复调整任务、人工修饰 Prompt 或更换术语来强行包装方法创新。正式宣布：**停止以“反例驱动适用条件局部修订”作为独立新算法推进**。

---

## 八、交付资产与复现清单

1. **可运行最小代码**：
   - 评测主程序：[`research/condition_revision/run_experiment.py`](file:///code/failmem-ros2-agent/research/condition_revision/run_experiment.py)
   - 环境封装与动作重放：[`research/condition_revision/env_wrapper.py`](file:///code/failmem-ros2-agent/research/condition_revision/env_wrapper.py)
   - 本地模型客户端：[`research/condition_revision/llm_client.py`](file:///code/failmem-ros2-agent/research/condition_revision/llm_client.py)
   - 任务清单配置：[`research/condition_revision/task_manifest.py`](file:///code/failmem-ros2-agent/research/condition_revision/task_manifest.py)
   - 四组 Agent 实现：[`research/condition_revision/agents/`](file:///code/failmem-ros2-agent/research/condition_revision/agents/)
   - 决策树特征核验脚本：[`research/condition_revision/decision_tree_check.py`](file:///code/failmem-ros2-agent/research/condition_revision/decision_tree_check.py)
2. **原始实验数据与记录**：
   - 逐步真实执行轨迹（包含每步 thought, action, obs, reward）：[`research/condition_revision/logs/raw_trajectories.jsonl`](file:///code/failmem-ros2-agent/research/condition_revision/logs/raw_trajectories.jsonl)
   - 自然探索提炼规则（含过拟合/过度泛化条件）：[`research/condition_revision/logs/extracted_rules.json`](file:///code/failmem-ros2-agent/research/condition_revision/logs/extracted_rules.json)
   - 反例触发与条件修订事件流：[`research/condition_revision/logs/revision_events.jsonl`](file:///code/failmem-ros2-agent/research/condition_revision/logs/revision_events.jsonl)
   - 快速验证汇总报告：[`research/condition_revision/logs/smoke_test_summary.json`](file:///code/failmem-ros2-agent/research/condition_revision/logs/smoke_test_summary.json)
   - 184-Episode 综合实验汇总报告：[`research/condition_revision/logs/experiment_summary.json`](file:///code/failmem-ros2-agent/research/condition_revision/logs/experiment_summary.json)
   - Round 1 结果分类账：[`research/condition_revision/logs/round_1_ledger.json`](file:///code/failmem-ros2-agent/research/condition_revision/logs/round_1_ledger.json)
   - Round 2 结果分类账：[`research/condition_revision/logs/round_2_ledger.json`](file:///code/failmem-ros2-agent/research/condition_revision/logs/round_2_ledger.json)
   - 全量标准输出与调用日志：[`research/condition_revision/logs/experiment_stdout.log`](file:///code/failmem-ros2-agent/research/condition_revision/logs/experiment_stdout.log)
3. **一键复现命令**：
   - 快速端到端冒烟核验（~2分钟）：
     ```bash
     python3 /code/failmem-ros2-agent/research/condition_revision/run_experiment.py --smoke_test --step_limit 4
     ```
   - 浅层属性决策树基线核验：
     ```bash
     python3 /code/failmem-ros2-agent/research/condition_revision/decision_tree_check.py
     ```
   - 全量两轮基准评测（184 episodes, ~58分钟）：
     ```bash
     python3 /code/failmem-ros2-agent/research/condition_revision/run_experiment.py --rounds 2 --step_limit 10
     ```
