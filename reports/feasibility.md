# 硬件与仿真环境审计与可行性报告 (Feasibility Audit)

- **阶段**: R0 审计收尾 / P0 前置更新 (2026-09-26)
- **关联报告**: `reports/R0-evidence-audit.md`, `reports/R0-review.md`, `reports/evidence/r0/environment_probe.json`

## 1. 本地硬件与运行时审计（实测现场探针）
- **GPU**: 1x NVIDIA GeForce RTX 2080 Ti，实测物理显存 **22528 MiB (22.0 GB)**。
- **CUDA 运行时层次区分**:
  - `nvidia-smi` 显示驱动兼容最高版本: **CUDA 13.0** (NVIDIA Driver: 580.82.07)
  - 宿主机已安装 CUDA Toolkit: **CUDA 13.0.88** (`/usr/local/cuda-13.0/bin/nvcc`)
  - Python 框架运行时: **PyTorch 2.10.0+cu128** (内置 CUDA 12.8 动态运行时，`torch.cuda.is_available() == True`)
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13490F (10 核心 / 16 线程)。
- **内存 (RAM)**: 31 GiB RAM (可用约 7.7 GiB)。
- **磁盘与操作系统**: Ubuntu 22.04 LTS (Linux 6.8.0-83-generic)。
- **本地 LLM 权重与推理实测**:
  - 经实测盘点，本地已完整缓存 **Qwen2.5-Coder-7B-Instruct** (位于 `/root/.cache/modelscope/models/Qwen--Qwen2.5-Coder-7B-Instruct/snapshots/master/`，15 GB safetensors)；
  - 现场探针实测：在 bfloat16 模式下加载耗时 16.69s，占用显存 **15.23 GB**（在 22.0 GB 显存容限内），单次结构化故障恢复 JSON 生成时延为 **2.05s**，格式合法率 100%；
  - 确认具备无需额外云端付费 API 即可支撑本地 LLM 规划与诊断推理的算力条件。

## 2. 仿真环境真实性审计（客观纠偏）
- **历史报告陈述**: ~~“采用轻量 Headless 机器人状态机沙箱，支持完整导航坐标、Costmap 障碍物更新、距离计算与真值打分（到达距离 < 0.3m 且稳定 2s）。”~~
- **R0 现场核验事实**:
  1. 当前代码 `src/sim_env.py` 仅为 60 行的连续 2D 坐标简单算术状态机，**完全未接入 ROS2、Nav2 或 Gazebo 物理仿真**。
  2. 代码中的 `clear_costmap` 仅在内存中切换布尔标志，未进行任何真实的栅格层或障碍物感知计算。
  3. `is_success()` 仅判断欧氏距离 `< 0.3m`，**未实现 2 秒静止稳定时间检查，亦未检查 observe() 动作**。
- **当前系统 ROS2 与容器安装情况**:
  - 当前 shell 未发现 ros2（`which ros2` 返回非零）；
  - 系统目录 `/opt/ros` 不存在，`dpkg -l` 无 ROS 相关包；
  - `/etc/apt/sources.list.d/ros2-latest.list` 存在官方 Jammy 源；
  - 容器运行时 `/usr/bin/docker` 已安装且守护进程正常运行；
  - **环境评估**: 鉴于宿主机为 Anaconda Python 3.13.5 环境，直接在宿主全局安装 ROS2 Python 绑定极易发生版本冲突。推荐采用 **基于 Ubuntu 22.04 + ROS2 Humble + Gazebo Fortress + Nav2 的隔离 Docker 容器** 技术路线。
