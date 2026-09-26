# FailMem 创新点与最近邻审计报告 (Novelty Audit)

- **阶段**: R0 审计收尾 / P0 待扩展
- **状态说明**: 原报告中声称的“显著提升”、“降低重复无效操作”等性能断言缺乏真实实验证据支撑，在 R0 阶段已纠正为 **待验证核心假设 (Unverified Hypotheses)**。

## 待验证核心假设 (Research Hypotheses)
- **Hypothesis 1 (H1: 结构化失败记忆有效性)**:
  提出面向移动机器人的失败记忆框架（FailMem）。假设在相同规划模型、感知信息、验证器和恢复预算下，记录结构化失败元组 $\langle \text{symptom}, \text{context\_signature}, \text{cause\_hypothesis}, \text{recovery\_action}, \text{verified\_outcome}, \text{expiry\_rules} \rangle$，能够在遇到导航受阻、超时等故障时检索出经验证有效的恢复策略，从而降低新任务中的重复失败率。*(待 P2/P3 真实仿真实验检验)*。
- **Hypothesis 2 (H2: 时效与地图感知失效规则)**:
  假设引入基于代价地图（Costmap）版本与局部障碍观测的确定性失效规则，能够避免在环境布局重构或障碍状态改变后错误套用旧失败经验。*(待 P2/P3 真实仿真实验检验)*。

*(注：P0 阶段将进一步阅读 Reflexion、REFLECT 等最近邻文献全文，系统更新与同类工作的细粒度差异分析。)*
