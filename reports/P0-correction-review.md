# P0-Correction-Review: 文献定点核验、研究契约修正与状态更新报告

- **项目**: `failmem-ros2-agent` (https://github.com/JingAo-Shen/failmem-ros2-agent)
- **阶段**: P0 定点修正 (P0 Targeted Correction)
- **审查状态**: **PARTIAL / NEEDS_CORRECTION (部分通过 / 需定点修正)**
- **前次状态**: PASSED (已正式撤回并保留修正记录)
- **执行分支**: `audit/r0-authenticity`
- **关联文件**:
  - 文献勘误与核验说明: [`reports/literature-corrections.md`](literature-corrections.md)
  - 全量核查文献表: [`reports/literature.csv`](literature.csv)
  - 全文阅读笔记: [`reports/reading-notes.md`](reading-notes.md)
  - 创新点与边界分析: [`reports/novelty-audit.md`](novelty-audit.md)
  - 最小研究契约 v0.2: [`docs/problem-lock.md`](../docs/problem-lock.md)

---

## 1. 为什么调整 P0 结论？
在上一轮提交中，文献核查清单中存在多处 arXiv 编号混淆（如将 2308.01429 误当作 ReSYNC，2410.15856 误当作 LifeMem，2501.18567 误当作 RoboOS-NeXT，2307.06350 误当作 SayPlan）、非真实开源链接（如不存在的 `robot-reflect/reflect` 和 `sayplan/sayplan` 仓库）以及武断的全称否定断言（如“该工作没有某机制”）。
根据研究负责人的复核意见，我们**撤回原 P0 PASSED 结论，将状态变更为 PARTIAL / NEEDS_CORRECTION**，并在本轮工作中完成了全量核验与定点修正。

---

## 2. 文献真实性核验完成度

1. **8 篇核心文献全量核验**:
   - 包含 Reflexion (NeurIPS 2023), REFLECT (CoRL 2023), Inner Monologue (CoRL 2022), SayPlan (CoRL 2023), ReSYNC (2026), LifeMem (EMNLP 2026), RoboOS-NeXT (2025), RoboMemory (2025)；
   - 每篇论文均核验了准确的 arXiv 页面、提交版本号、作者完整列表、开源代码真实可用性与许可证协议；
   - 无法核实的代码链接或许可证严格标注为 `UNKNOWN`，杜绝任何臆测或虚构。
2. **全文阅读笔记与章节页码锚定**:
   - 撰写了独立的 [`reports/reading-notes.md`](reading-notes.md)，逐篇列出核查的具体章节、段落、页码及支持对比的核心原文内容；
   - 修正了 REFLECT 的骨干模型（GPT-4/GPT-3.5 纯文本 LLM 输入文本摘要，非端到端 GPT-4V）与机器人形态（AI2-THOR 虚拟环境与 UR5e 单机械臂桌面操作，非移动双臂机器人）；
   - 修正了 RoboMemory 的作者（Lei et al., 2025，19位作者）与对比基线（包含 Reflexion、Voyager、Cradle 三类 Agent 框架及主流 VLM，测试基准为 EmbodiedBench）。
3. **撤回缺乏依据的武断断言**:
   - 将所有未在检查章节中见到的机制描述调整为“在已检查的章节中未发现”，明确划定阅读范围。

---

## 3. 研究契约 (Problem Lock) 升级为 v0.2 草案

在 [`docs/problem-lock.md`](../docs/problem-lock.md) 中完成了针对评审意见的定点修改：
1. **隐藏真值与公开感知彻底解耦**: 目标移动等隐藏事件仅注入物理世界并供独立 Evaluator 打分；Agent 侧记忆状态更新仅依赖公开观察、公开地图更新与显式重验；增加了未观察时记忆不得改变的反例契约；
2. **目标实体与安全观察站位分离**: 定义了机器人的观察停靠站位 $P_{\text{stance}}$ 与目标实体包围盒 $P_{\text{target}}$ 的物理间隙，给出了具体几何数值实例（距离 1.1m，站位误差 0.1m，安全间隙 0.65m，稳定时间 2.2s），证明成功条件可同时满足且避免碰撞；
3. **动作空间 Schema 补齐**: 补齐 `action`, `action_id`, `params` 强类型定义，移除未实现的 `Back-up` 动作；
4. **纠正故障因果确定性表述**: 明确障碍物生命周期由外生计划决定，不因方法调用或成功声明而自动消失；实体障碍存在不必然导致重试发生物理碰撞（机器人可刹停或避障拒绝）；
5. **恢复地图划分与规模为待评审计划**: 撤回 3/2/3 地图正式划分的结论，明确 P1 仅使用 1 个用于开发的单场景，后续测试规模由运行成本与统计精度决定；
6. **仿真暂停机制规范**: 明确暂停只能在动作终态后的高层规划边界触发，在未打通该机制前标记为 `NOT_RUN`。

---

## 4. 结论与下一步流转
- **P0 阶段定点修正已全部落实并可核查**；
- 状态维持为 `PARTIAL / NEEDS_CORRECTION`，以诚实记录学术演进与修正轨迹；
- 允许在独立容器环境下开展 P1a 单场景真实导航冒烟测试。
