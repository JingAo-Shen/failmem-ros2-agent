# FailMem: Failure-Aware Memory for ROS2 Agents

> Research on episodic failure memory, execution verification, recovery, and reusable skill formation in long-horizon ROS2 agents.

## Research Goal

在相同规划模型、感知信息、验证器和恢复预算下，带适用条件与失效规则的失败记忆，能否减少机器人在新任务中的重复失败，并避免环境变化后的错误经验复用？

## Current Repository Status (R0 Audit Completed — 2026-09-26)

- **阶段状态**: **R0 研究真实性审计已完成，进入 P0 文献核验与环境可行性核查阶段**。
- **环境真实性说明**: 当前代码实现（`src/sim_env.py` 等）仅为 **轻量 2D 坐标 mock 原型**，**尚未真正接入 ROS2、Gazebo 或 Nav2**。系统目前未安装 ROS2 运行环境。
- **历史结论状态**: 先前提交中包含的虚假 P4 PASSED 状态及未经实验支持的论文数字（如 86.7% 恢复率、+53.4pp 增益）已正式全部撤回，详见审计报告：
  - [R0 主张与证据审计报告](reports/R0-evidence-audit.md)
  - [R0 研究真实性审计总报告](reports/R0-review.md)
  - [P4 撤回声明](reports/P4-review.md)

## Hardware Verification (实测确认)

- **GPU**: 1x NVIDIA GeForce RTX 2080 Ti (魔改 **22.0 GB / 22528 MiB** 显存，已实测验证)
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13490F (10 核心 / 16 线程)
- **RAM**: 31 GiB (Ubuntu 22.04 LTS)
- **ROS2 状态**: `which ros2` 返回空，ROS2 依赖未安装，为 P1 阶段关键阻塞项。

## Research Execution Roadmap

本项目严格遵循六阶段科研规程：
1. **R0 研究真实性审计** *(已完成)*: 核查代码真实性、复现设计缺陷、清点运行证据、撤回无效主张。
2. **P0 文献与环境核查** *(下一阶段)*: 深度比对最近邻文献、确立物理动作契约、评估 ROS2 安装方案。
3. **P1 真实仿真及可信评测**: 搭建 ROS2 Humble / Nav2 真实仿真冒烟环境，实现独立真值打分与防泄漏事件重放。
4. **P2 方法、基线与开发集实验**: 开发集机制实验与消融分析。
5. **P3 冻结后正式实验**: 冻结评测协议，三随机种子运行正式测试集与多维对比。
6. **P4 论文证据整理**: 从真实不可篡改的日志中自动聚合图表，撰写学术手稿。

## Project Structure

- `docs/research-plan.md` — 科学问题、假设、元组 Schema 与控制指标
- `docs/roadmap.md` — 阶段依赖与检查点
- `experiments/experiment-matrix.md` — 核心基线与消融设计
- `reports/` — 各阶段评审与审计报告
- `src/` — 核心代码实现
- `tests/` — 审计复现与防退化测试套件
- `runs/` — 独立运行日志与原始证据输出
