# 持续研究状态跟踪文件 (Research Status)

**更新时间**：2026-10-20  
**当前阶段**：**P1 终结批次（真实数据核查、准入审计与有界 NO-GO 裁决）**  
**当前状态**：**已终结：未建立自然经验有害误用或反例边界冲突；经验仅在示范组体现正向迁移；终止条件修订扩展方案 (NO-GO)**  
**基准分支**：`research/counterexample-condition-revision`  

---

## 1. 核心研究问题直接回答与最终定位

> **“我们是否真的获得了一条原本有用、在新情境下暴露边界的自然经验？”**

### **结论：否 (Negative)。**

1. **未在 Rollout 中生成待测规则（`NO_RULE_CREATED`）**：
   在 `7244944` 的实验中，由于历史代码设置了来源任务 100 分门槛，未成功来源任务被跳过提取。因此 Condition C 规则库大小为 0，Condition D 提示词为空。先前记录的“安全阻断”并非物理接地的条件求值拒绝，而是**尚未生成待测规则**。
2. **迁移范围未建立（`TRANSFER_SCOPE_NOT_ESTABLISHED`）**：
   事后对真实轨迹进行补充提取后发现，LLM 生成的适用条件均高度特化于具体实体（如 `aluminum foil must be present in workshop`）。在严谨物理接地下，这些规则在反例（杏子、非生物）上均被判定为 `FALSE` 或 `UNKNOWN`，无法在任何新情境下激活。
3. **轨迹示范（Condition B）仅表现为中性或正向迁移**：
   在唯一真实注入经验的 Condition B 中，检索到的示范文本在玻璃罐任务中提速 28.6%（7步 $\to$ 5步），在非生物任务中直接从超时失败提升至 **100分满分成功（仅需 3 步）**，未出现任何灾难性负迁移。

---

## 2. 交付核心问题系统解答

### Q1: 旧经验在哪些情境中确实有用？
- **实证证据**：在当前评测范围内，**仅在原始轨迹检索示范（Condition B）中观察到确凿的效用提升**：
  - 在生物分类边界任务中，示范帮助模型习得容器转移模式，从无记忆的 25分超时跃升至 **100分满分成功**；
  - 在玻璃罐导电测试中，示范使动作序列更紧凑，完成步数从 7 步缩减至 5 步。
  - 对于规则文本（Condition C），在严格物理接地下尚未建立具有跨任务泛化收益的有效规则。

### Q2: 旧经验在哪些新情境中确实失效？
- **实证证据**：**未观察到在新情境下由于旧经验导致的失败（0 负迁移事件）**。
  - 在所有边界任务（如杏子被放入红盒），无记忆基线（Cond A）同样犯下完全相同的错误；
  - 经验注入后，未出现任何“无记忆能做对，但有记忆做错”的实例。

### Q3: 现有证据是否足以研究局部修订？
- **实证证据**：**完全不足以（Insufficient）**。
  - 局部修订算法的研究前提是“经验过度泛化导致有害误用”。
  - 既然在严格物理接地系统下，具象实体条件不会发生泛化误用；而在轨迹示范下又表现为正向迁移，那么“反例后局部修订条件”就缺乏真实的现象基础与因果痛点。

---

## 3. 语义修复与单测完全回归 (14/14 通过)

在 `condition_evaluator.py` 中彻底修复 4 项语义逻辑漏洞，并在 `test_interface_and_conditions.py` 扩充并通过对应单测：

1. **`test_sample_non_metallic_not_judged_as_metal`**：通过负向正则词边界判定，确保 `"The sample is non-metallic."` 100% 判定为 `FALSE`（杜绝 `metallic` 子串假阳性）；
2. **`test_water_liquid_with_ice_cube_on_another_table_not_solid`**：引入并列连词切分，确保 `"The water is liquid, and an ice cube is frozen on another table."` 判定水为 `liquid = TRUE`, `solid = FALSE`（杜绝冰块状态污染水）；
3. **`test_unmentioned_object_returns_unknown_not_false`**：未提及对象返回 `UNKNOWN / INSUFFICIENT_EVIDENCE`（杜绝将未在视口提及降级为否定）；
4. **`test_historical_wiring_not_spliced_with_disjoint_bulb_state`**：建立时序电路跟踪，杜绝将断开后的历史灯亮任意拼接为当前实体的导电证据。

---

## 4. 阶段裁决与科研转向建议

### 4.1 正式科研裁决
根据总指令：
> “若本批完成后，仍然只有轨迹示范的正向迁移、没有适用边界冲突，则停止继续扩展当前条件修订方案，提交有覆盖范围限制的 no-go 结论。”

**裁决**：
- **提交有覆盖范围限制的 NO-GO 结论**；
- **终止“反例驱动的条件适用范围局部修订”方案在 ScienceWorld 中的继续扩展开发**；
- **P2 开发正式关闭，封存实验成果**。

### 4.2 两个更具 SCI 价值的替代研究方向
1. **替代方向 1：基于环境反馈交互式澄清约束的在线闭环修正 (Interactive Feedback-Driven Constraint Grounding)**
   - 核心问题：当 Agent 遇到未明属性（如不可见容器、非标准动作谓词）受阻时，如何利用环境试错报错信号在线澄清约束并纠偏动作？
   - 最小区分实验：对比静态规则注入 vs 在线交互报错反思；评价指标为任务完成率与试错步数成本。
2. **替代方向 2：长程 Agent 轨迹归纳中的“归纳跃迁过度泛化”检测与因果过滤 (Inductive Leap Detection in Agent Trajectory Summarization)**
   - 核心问题：当 LLM 自发将单次交互经验抽象为通用常识时，何时会产生错误的归纳跃迁（Inductive Leap）？如何设计前置因果探针拦截伪知识？
   - 最小区分实验：对比具象规则与跨实体归纳规则在反例上的负迁移率，测试因果门控有效性。

---

## 5. 累计资源消耗账本 (Final Accounting)

- **总硬上限**：3,000 Episodes / 150,000 Model Calls / 120.0 GPU Hours
- **累计实际消耗**：
  - **P0**：8 Episodes / 35 Calls / 20,431 In / 1,704 Out Tokens
  - **P1**：69 Episodes / 287 Calls / 160,483 In / 16,061 Out Tokens
  - **总计**：**77 Episodes / 322 Calls / 198,679 Tokens / 1,416.1s (~23.6 分钟)**
  - **预算合规率**：**100% 严格合规**（Episodes 占 2.57%，Calls 占 0.21%，GPU 时间占 0.33%）。
