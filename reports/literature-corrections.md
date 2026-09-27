# 文献真实性核验与定点修正说明 (Literature Corrections & Status Review)

- **审查日期**: 2026-09-27
- **审查人**: 研究执行工程师
- **当前阶段状态**: **PARTIAL / NEEDS_CORRECTION (部分通过 / 需定点修正)**
- **关联文件**:
  - 文献核查清单: [`reports/literature.csv`](literature.csv)
  - 全文阅读笔记: [`reports/reading-notes.md`](reading-notes.md)
  - 创新点与边界分析: [`reports/novelty-audit.md`](novelty-audit.md)

---

## 1. 为什么 P0 状态调整为 PARTIAL / NEEDS_CORRECTION？

在前一轮交付中，我们过早宣布 P0 验收通过（PASSED）。经研究负责人复核和全量反查发现，上一版文献清单存在多处未严格核实的 arXiv 编号、作者信息、代码链接以及对前人工作机制的武断推断。根据学术严谨性原则，**正式撤回先前的 P0 PASSED 结论，将状态变更为 PARTIAL / NEEDS_CORRECTION**，并在本报告中完整保留定点修正记录。

---

## 2. 确认失效的旧结论与事实勘误清单

| 论文名称 | 原记录缺陷 / 错误内容 | 真实核验事实 | 修正后状态 |
| :--- | :--- | :--- | :---: |
| **ReSYNC** | 原记录使用了错误编号 `2308.01429`（实际为无关论文）；虚构了代码开源链接 `learning-and-intelligent-systems/resync` | 正确 arXiv 编号为 **[2606.18328](https://arxiv.org/abs/2606.18328)**，标题为 *Recover, Discover, Plan: Learning Skills and Concepts from Robot Failures* (Li et al., 2026)。项目主页为 https://jaraxxus-me.github.io/ReSYNC/ ，截至 v1 版本**尚未公开代码仓库**，代码链接更正为 `UNKNOWN`。 | **已修正** |
| **LifeMem** | 原记录使用了错误编号 `2410.15856`；作者与基线未严格核实 | 正确 arXiv 编号为 **[2609.12655](https://arxiv.org/abs/2609.12655)** (Qiu et al., EMNLP 2026 Main)。作者官方仓库为 https://github.com/BITHLP/LifeMem ，测试基准涵盖 10 个软件与高层交互环境（ALFWorld, VirtualHome, ToolBench 等），未发现物理底层 Costmap 验证。许可证在仓库中未见明确文件，标注为 `UNKNOWN (Repo Public)`。 | **已修正** |
| **RoboOS-NeXT** | 原记录使用了错误编号 `2501.18567` | 正确 arXiv 编号为 **[2510.26536](https://arxiv.org/abs/2510.26536)** (Tan et al., 2025)。项目主页为 https://flagopen.github.io/RoboOS/ ，官方开源仓库为 https://github.com/FlagOpen/RoboOS (Apache-2.0)。聚焦多机器人异构协同调度与 STEM 记忆，而非单机器人代价地图失效边界。 | **已修正** |
| **SayPlan** | 原记录使用了错误编号 `2307.06350`（实际为图像生成评测 T2I-CompBench++）；虚构了 github 代码链接 `sayplan/sayplan` (404) | 正确 arXiv 编号为 **[2307.06135](https://arxiv.org/abs/2307.06135)** (Rana et al., CoRL 2023 Oral)。项目主页为 https://sayplan.github.io ，主页上的 Code 按钮并未链接到有效公开仓库，代码链接更正为 `UNKNOWN`，许可证更正为 `UNKNOWN (paper CC-BY-NC-SA-4.0)`。 | **已修正** |
| **REFLECT** | 1. 误称其规划模型为 `GPT-4V`；<br>2. 误称其机器人形态为“真实移动双臂机器人”；<br>3. 记录了失效代码仓库 `robot-reflect/reflect` (404) | 1. 经查 Sec. 3.1 & Sec. 5，REFLECT 是将多模态数据先转为文本场景图与音频标签，再输入纯文本大模型 **GPT-4 (`gpt-4-0314`) 与 GPT-3.5 (`text-davinci-003`)** 进行推理，而非端到端 GPT-4V；<br>2. 机器人形态为 **AI2-THOR 虚拟 Agent**（仿真 100 例）与 **UR5e 桌面单机械臂**（真机 30 例），并非移动双臂机器人；<br>3. 官方真实代码开源仓库为 **https://github.com/columbia-ai-robotics/reflect** (MIT License)。 | **已修正** |
| **RoboMemory** | 1. 虚构了公共代码链接 `anonymous/RoboMemory`；<br>2. 缺少详细作者信息与实验基线 | 1. 论文作者共 19 人 (Lei et al., 2025)，v1 版本论文未提供公开代码链接，代码标记为 `UNKNOWN`，论文协议为 `CC-BY-NC-SA-4.0`；<br>2. 经查 Sec. 4.1.2，其实验对比基线明确包含三类 Agent 框架：**Reflexion, Voyager, Cradle**（均以 Qwen2.5-VL-72b-Ins 为骨干），以及 GPT-4o, Claude3.5-Sonnet, InternVL-3-72B 等 VLM 单模型，测试集为 EmbodiedBench。 | **已修正** |

---

## 3. 撤回武断推断与表述客观化

在上一版文档中，部分表述直接声称“该工作没有某某机制”、“该工作仅限于某种场景”，犯了非充分核查下的全称否定错误。现根据全文核验情况做如下撤回与限定调整：
1. **撤回关于“缺乏机制”的绝对全称断言**：
   - 原文：“REFLECT 没有适用条件与失效机制”、“SayPlan 没有失败记忆”。
   - 修正为：“在已检查的章节中（REFLECT Sec. 3-5, SayPlan Sec. 3-4），未发现针对跨 Episode 任务的持久化失败经验元组索引或基于局部代价地图变化的显式失效机制。”
2. **界定阅读范围与版本依据**：
   - 所有比较结论均在 [`reports/reading-notes.md`](reading-notes.md) 中标注了实际核查的 arXiv 具体版本号（如 REFLECT v4, Reflexion v4, SayPlan v2）、阅读的具体章节段落及页码。

---

## 4. 仍然保持证据支持的核心结论

1. **核心假说立论依然成立**:
   - Reflexion、REFLECT、Inner Monologue 无论在单任务内的多轮试错（Reflexion），还是单次物理失败的多模态诊断与一步修正（REFLECT），均未系统解决“室内移动机器人在环境局部变化（如动态障碍清理、静态重构）后，如何防止对过期经验错误复用”这一科学问题。
   - 近期的大型记忆系统（RoboMemory 2025、RoboOS-NeXT 2025、LifeMem 2026）偏向宏观的多模块知识图谱或多智能体协同，未对“物理代价地图版本与带前置条件的失败记忆”这一特定因果机制进行严格消融隔离。
2. **FailMem 收窄定位保持坚实**:
   - 将 FailMem 严格限定在“相同规划模型、感知信息、验证器和恢复预算下，带适用条件与失效规则的失败记忆对跨任务重复失败与错误复用的抑制”，具有清晰且未经充分探索的科学空间。
