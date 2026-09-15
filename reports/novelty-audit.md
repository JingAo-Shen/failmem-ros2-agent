# FailMem 创新点与最近邻审计报告 (Novelty Audit)

## 核心贡献
- **Claim 1 (主贡献)**: 提出面向具身机器人的可验证失败记忆（Verified Failure Memory, FailMem）。通过记录结构化失败元组 $\langle \text{symptom}, \text{context\_signature}, \text{cause\_hypothesis}, \text{recovery\_action}, \text{verified\_outcome}, \text{expiry\_rules} \rangle$，在遇到导航受阻、目标移动或超时等故障时，精准检索可复用恢复策略，在跨 Episode 任务中显著提升故障恢复成功率并降低重复无效操作（Repeat Failure Rate）。
- **Claim 2 (时效与地图感知失效)**: 引入基于代价地图（Costmap）版本与局部障碍观测的确定性失效规则，防止在环境布局重构后错误套用旧失败经验。
