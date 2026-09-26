# FailMem: Failure-Aware Memory for ROS2 Agents

> Research on episodic failure memory, execution verification, recovery, and reusable skill formation in long-horizon ROS2 agents.

## Research Goal

在相同规划模型、感知信息、验证器和恢复预算下，带适用条件与失效规则的失败记忆，能否减少机器人在新任务中的重复失败，并避免环境变化后的错误经验复用？

## Repository Status (R0 Audit Completed — 2026-09-26)

- **阶段状态**: **R0 研究真实性审计执行完成（当前待研究负责人复核确认）**。进入下一阶段（P0）须待复核批准。
- **环境真实性说明**: 当前代码实现（`src/sim_env.py` 等）仅为 **轻量 2D 坐标 mock 原型**，**尚未接入 ROS2、Gazebo 或 Nav2 物理仿真**。系统目前未安装 ROS2 运行环境。
- **历史结论状态**: 先前提交中包含的虚假 P4 PASSED 状态及未经实验支持的论文数字（如 86.7% 恢复率、+53.4pp 增益）已正式全部撤回，详见审计报告与证据包：
  - [R0 主张与证据审计报告](reports/R0-evidence-audit.md)
  - [R0 研究真实性审计总报告](reports/R0-review.md)
  - [P4 撤回声明](reports/P4-review.md)
  - [R0 可复核证据包 (包含日志、探针与哈希)](reports/evidence/r0/)

## Hardware Verification (现场探针实测)

- **GPU**: 1x NVIDIA GeForce RTX 2080 Ti (物理显存 **22.0 GB / 22528 MiB**，实测显存与 CUDA 13.0 支持)
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13490F (10 核心 / 16 线程)
- **RAM**: 31 GiB (Ubuntu 22.04 LTS)
- **ROS2 状态**: 当前 shell 未发现 ros2（`/opt/ros` 不存在，`dpkg` 无 ros 相关包）；宿主机 `/usr/bin/docker` 可用，建议后续采用隔离容器部署。
- **本地 LLM 权重**: 实测已完整缓存 **Qwen2.5-Coder-7B-Instruct**，bfloat16 加载占 15.23 GB 显存，单次推理时延 2.05s，格式合法率 100%，具备纯本地部署条件。

## Research Execution Roadmap

本项目严格遵循六阶段科研规程，阶段推进需经研究负责人复核批准：
1. **R0 研究真实性审计** *(执行完成，待复核)*: 核查代码真实性、复现 8 项设计缺陷、清点运行证据、撤回无效主张。
2. **P0 文献、环境与研究协议核查** *(待启动)*: 深度比对最近邻文献、确立物理动作契约、评估 ROS2 容器方案与问题锁定。
3. **P1 真实仿真及可信评测**: 搭建 ROS2 Humble / Nav2 真实仿真冒烟环境，实现独立真值打分与防泄漏事件重放。
4. **P2 方法、基线与开发集实验**: 开发集机制实验与消融分析。
5. **P3 冻结后正式实验**: 冻结评测协议，三随机种子运行正式测试集与多维对比。
6. **P4 论文证据整理**: 从真实不可篡改的日志中自动聚合图表，撰写学术手稿。

## Project Structure

- `docs/research-plan.md` — 科学问题、假设、元组 Schema 与控制指标
- `docs/roadmap.md` — 阶段依赖与检查点
- `experiments/experiment-matrix.md` — 核心基线与消融设计
- `reports/` — 各阶段评审与审计报告
- `reports/evidence/r0/` — R0 现场复核证据包（环境探针、数据集对比、失败轨迹、pytest输出、SHA256清单）
- `src/` — 核心代码实现
- `tests/` — 审计复现与防退化测试套件
- `runs/` — 独立运行日志与原始证据输出
