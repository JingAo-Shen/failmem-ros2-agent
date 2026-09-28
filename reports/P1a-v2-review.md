# FailMem P1a-v2 Review Report: 独立 Episode、统一时钟与可靠终态验证

- **Stage**: P1a-v2 (Independent Episodes, Unified Sim Time, and Reliable Final-State Verification)
- **Status**: PASSED (Within P1a-v2 Scope)
  - 独立 Episode 仿真复位与进程生命周期管理：已通过 (PASSED)
  - 统一 ROS 仿真时间与多重时间戳体系：已通过 (PASSED)
  - 坐标系一致性证明 (`world == map`)：已完成数学与几何核验 (PASSED)
  - 严格到达判定（$\le 0.30\,\text{m}$ 契约阈值 + 2.0s 稳定停稳窗口）：3/3 已通过 (PASSED)
  - 运动中取消与物理停止验证（$v > 0.05\,\text{m/s}$ 下取消 + 2.0s 零速度停稳）：已通过 (PASSED)
  - 时间对齐的 AMCL 与 Ground Truth 定位误差审计（$\Delta t \le 0.1\,\text{s}$）：已通过 (PASSED)
  - 统一动作调度器（校验、归一化、历史约束与 UUID 映射）：已集成并实测通过 (PASSED)
- **Run ID**: `p1a_v2_20260928_005206_479fbc`
- **Execution Timestamp**: 2026-09-28T00:53:53.868642+00:00
- **Base Commit**: `5cb22a1` (`refactor(p1a): move p1a execution to scripts and add entrypoint`)
- **Review Date**: 2026-09-28
- **Domain Isolation**: `ROS_DOMAIN_ID=42`, `ROS_LOCALHOST_ONLY=1`

---

## 1. Executive Summary & Review Scope

本报告针对研究负责人对前一轮 P1a 冒烟提出的复核意见，完成 **P1a-v2** 的系统升级与独立执行验证。

### 历史问题闭环对照
1. **非独立 Episode 纠偏**：上一轮旧运行（`reports/evidence/p1a/`）是在单一仿真生命周期中连续行进的航点移动，已更名为“连续航点链路冒烟”，原样归档保留作为历史链路调通证据。本轮 P1a-v2 在每个 Episode 开始前彻底清空仿真进程与共享内存，独立启动 Gazebo/Nav2，实现真正的仿真复位。
2. **严格 0.30m 契约阈值执行**：完全废除静默放宽至 0.35m 的做法。本轮三段导航的真实 Ground Truth 误差分别为 **$0.2587\,\text{m}$**、**$0.2217\,\text{m}$** 和 **$0.2001\,\text{m}$**，均严格满足 $\le 0.30\,\text{m}$ 契约。
3. **物理停稳观察窗口**：到达后设置 $\ge 2.0\,\text{s}$ 仿真时间的高频连续采样窗口。验证车辆在窗口内线速度 $|v| < 0.05\,\text{m/s}$、角速度 $|\omega| < 0.05\,\text{rad/s}$，位移波动 $\le 0.0023\,\text{m}$，彻底排除滑动或未停稳情况。
4. **运动中取消验证**：在车辆线速度达到 $0.068\,\text{m/s}$（$> 0.05\,\text{m/s}$）的行驶过程中发送取消指令，Nav2 正确返回 `CANCELED`，机器人随后完全静止（线速度 $0.0000\,\text{m/s}$，角速度 $0.0003\,\text{rad/s}$），并在连续 2.0s 稳定窗口内位移变化为 $0.0000\,\text{m}$。
5. **统一动作调度器接入**：通过 `src/action_dispatcher.py` 串联解析、严格 schema 校验、参数补全、重试历史与状态指纹约束（同状态至多 1 次重试，总预算 3 次），并生成确定性 ROS Goal UUID 后分发。

> [!IMPORTANT]
> **严格边界声明**：
> 本阶段仍限定为 P1a-v2 单机器人室内仿真导航链路可靠性验证。
> - `observe` 动作接口因感知与识别算法尚未接入，明确标记为 **DEFERRED**；
> - 暂不接入 LLM 循环；
> - 暂不实现 FailMem 检索或记忆失效算法；
> - 暂不开展 P2 方法对比，不声称任何下游基准收益。

---

## 2. Environment Stack & Architecture Decisions

| Component | Specification / Version | Rationale & Evidence |
| :--- | :--- | :--- |
| **Simulator Platform** | Gazebo Classic 11.10.2 (`gazebo_ros_pkgs`) | **记录为 P1 开发选择**。官方 TurtleBot3 原生 SDF 模型、差分驱动插件及真实状态插件成熟稳定，避免在 P1 阶段因迁移仿真器造成不必要的工程震荡与契约失效。 |
| **Container & Base OS** | `ros:humble@sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` on Ubuntu 22.04 | 锁定官方多架构镜像 digest，确保环境绝对复现。 |
| **Robot Model** | TurtleBot3 Waffle (`TURTLEBOT3_MODEL=waffle`) | 标准差分移动机器人，配备 2D LiDAR (`/scan`)，两轮差速驱动。 |
| **Navigation Stack** | Navigation2 1.1.20 (`nav2_bringup`) | 包含 `bt_navigator` 行为树、`planner_server` (Navfn)、`controller_server` (DWB)、`amcl` 粒子滤波定位。 |
| **Ground Truth Sensor**| `libgazebo_ros_state.so` (`<plugin name="gazebo_ros_state">`) | 在仿真世界直接发布各 model 的物理绝对位姿于 `/gazebo/model_states`。 |
| **Scoring Rules** | `configs/scoring_rules.yaml` | 严格声明公差、稳定窗口、坐标系对齐证明与动作约束。 |

---

## 3. Clock Synchronization & Coordinate Frames Alignment

### 3.1 统一仿真时钟 (`use_sim_time=True`)
- 所有节点统一声明 `use_sim_time=True`，严禁使用系统墙上时间驱动运动控制与超时；
- 在每个 Episode 启动后，调度器持续监听 `/clock` 话题，必须观察到仿真时间递增至少 $1.0\,\text{s}$ 后方可向下进行；
- 解决 DDS 发现延时与 Action 拒绝问题：通过服务调用轮询 `/bt_navigator/get_state`，直到其生命周期状态从 `2 (inactive)` 转换至 `3 (active)`，彻底消除冷启动初期 Action 丢弃现象。

### 3.2 多重时间戳体系与 Gazebo 状态戳审计
记录的每个传感器样本均包含以下四维时间戳与元数据：
1. `msg_stamp_sec`：来自 ROS 消息 header 的时间戳（秒）；
2. `recv_sim_time_sec`：节点在回调收到消息时的 ROS 仿真时间；
3. `monotonic_wall_sec`：系统单调墙上时间（秒，用于看门狗监测）；
4. `frame_id`：对应的坐标系字符串。

> [!NOTE]
> **Gazebo ModelStates 消息无 Header 审计说明**：
> `gazebo_msgs/msg/ModelStates` 消息结构在 ROS 2 中原生不包含 `std_msgs/Header`。为此，系统在元数据中明确标记：
> - `timestamp_type: "RECEIPT_ROS_SIM_TIME_APPROX"`
> - `synchronization_note: "ModelStates has no header; timestamp is ROS sim time at callback receipt."`
> 避免将无 header 消息伪造为带有完美硬件时间戳。

### 3.3 坐标系一致性几何与数学证明 (`world == map`)
评测标准要求明确 Ground Truth 所在坐标系 `world` 与 AMCL/Nav2 目标所在坐标系 `map` 的数学等价关系：
1. **世界原点定义**：`configs/world_with_state.model` 中，中心圆柱位于 Gazebo 世界几何中心 $(0, 0, 0)$；
2. **地图元数据映射**：`configs/turtlebot3_world.yaml` 定义：
   $$\text{resolution} = 0.050000\,\text{m/pixel},\quad \text{origin} = [-10.0, -10.0, 0.0]$$
   地图图像尺寸为 $384 \times 384$ 像素。像素坐标 $(200, 200)$ 对应的地图坐标为：
   $$x_{\text{map}} = -10.0 + 200 \times 0.05 = 0.0\,\text{m},\quad y_{\text{map}} = -10.0 + 200 \times 0.05 = 0.0\,\text{m}$$
   该位置与 Gazebo 世界原点 $(0, 0)$ 重合；
3. **出生点对齐**：机器人出生点在 Gazebo 中配置为 $[-2.0, -0.5, 0.0]$，AMCL 初始化发布的初始位姿同样为 $[-2.0, -0.5, 0.0, \text{frame\_id}="map"]$；
4. **结论**：
   $$\mathbf{p}_{\text{map}} \equiv \mathbf{p}_{\text{world}}, \quad \theta_{\text{map}} \equiv \theta_{\text{world}}$$
   因此，Nav2 下发的地图目标坐标可以直接与 Gazebo 模型物理坐标进行几何欧氏距离计算。

---

## 4. Independent Episode Test Results (Run: `p1a_v2_20260928_005206_479fbc`)

各 Episode 间均执行完整的进程杀灭、共享内存清理、仿真重启与 AMCL 重置收敛，彻底杜绝航点连续累积状态。

### 4.1 独立导航 Episode 1：前进走廊 (`nav_ep1_fwd`)
- **目标位姿**: $[x=-0.50\,\text{m}, y=-0.50\,\text{m}, \text{yaw}=0.00\,\text{rad}]$
- **初始位姿 (Spawn)**:
  - GT: $[-2.0000, -0.5000, 0.0001\,\text{rad}]$
  - AMCL: $[-2.0083, -0.4894, 0.0060\,\text{rad}]$
- **执行时间**: 仿真耗时 $6.500\,\text{s}$（墙上耗时 $5.362\,\text{s}$）
- **Nav2 Action 终端状态**: `SUCCEEDED` (Code 4)
- **终点位姿**:
  - GT: $[-0.7556, -0.5397, 0.0357\,\text{rad}]$
  - AMCL: $[-0.8796, -0.5414, 0.0684\,\text{rad}]$
- **几何终态误差**:
  - GT 位置误差: **$0.2587\,\text{m}$**（契约阈值 $\le 0.30\,\text{m}$，**PASSED**）
  - GT 航向误差: **$0.0357\,\text{rad}$** ($2.05^\circ$，契约阈值 $\le 0.35\,\text{rad}$，**PASSED**）
  - AMCL 估计误差: 位置 $0.3819\,\text{m}$，航向 $0.0684\,\text{rad}$
- **2.0s 稳定观察窗口**:
  - 采样样本数: 123 个
  - 窗口内位置全部合规: `TRUE`
  - 窗口内航向全部合规: `TRUE`
  - 车辆完全停稳 ($|v| < 0.05\,\text{m/s}, |\omega| < 0.05\,\text{rad/s}$): `TRUE`
  - 窗口内最大 GT 物理漂移: $0.0023\,\text{m}$
- **时间对齐定位审计 ($\Delta t \le 0.1\,\text{s}$)**:
  - 匹配对齐样本数: 5
  - AMCL 与 GT 平均位移差异: **$0.0355\,\text{m}$** ($3.55\,\text{cm}$)
- **最终综合判定**: `strict_physical_arrival_and_stable = TRUE`

---

### 4.2 独立导航 Episode 2：横向跨越与 90° 旋转 (`nav_ep2_lateral`)
- **目标位姿**: $[x=0.50\,\text{m}, y=-0.50\,\text{m}, \text{yaw}=1.57\,\text{rad}]$
- **初始位姿 (Spawn)**:
  - GT: $[-2.0000, -0.5000, 0.0001\,\text{rad}]$
  - AMCL: $[-1.9970, -0.4973, 0.0056\,\text{rad}]$
- **执行时间**: 仿真耗时 $13.600\,\text{s}$（墙上耗时 $13.222\,\text{s}$）
- **Nav2 Action 终端状态**: `SUCCEEDED` (Code 4)
- **终点位姿**:
  - GT: $[0.2794, -0.5218, 1.3251\,\text{rad}]$
  - AMCL: $[0.2778, -0.5511, 1.2577\,\text{rad}]$
- **几何终态误差**:
  - GT 位置误差: **$0.2217\,\text{m}$**（契约阈值 $\le 0.30\,\text{m}$，**PASSED**）
  - GT 航向误差: **$0.2449\,\text{rad}$** ($14.03^\circ$，契约阈值 $\le 0.35\,\text{rad}$，**PASSED**）
  - AMCL 估计误差: 位置 $0.2280\,\text{m}$，航向 $0.3123\,\text{rad}$
- **2.0s 稳定观察窗口**:
  - 采样样本数: 123 个
  - 窗口内位置全部合规: `TRUE`
  - 窗口内航向全部合规: `TRUE`
  - 车辆完全停稳 ($|v| < 0.05\,\text{m/s}, |\omega| < 0.05\,\text{rad/s}$): `TRUE`
  - 窗口内最大 GT 物理漂移: $0.0000\,\text{m}$
- **时间对齐定位审计 ($\Delta t \le 0.1\,\text{s}$)**:
  - 匹配对齐样本数: 14
  - AMCL 与 GT 平均位移差异: **$0.0376\,\text{m}$** ($3.76\,\text{cm}$)
- **最终综合判定**: `strict_physical_arrival_and_stable = TRUE`

---

### 4.3 独立导航 Episode 3：掉头返回原点邻域 (`nav_ep3_return`)
- **目标位姿**: $[x=-1.80\,\text{m}, y=-0.50\,\text{m}, \text{yaw}=3.14\,\text{rad}]$
- **初始位姿 (Spawn)**:
  - GT: $[-2.0000, -0.5000, 0.0001\,\text{rad}]$
  - AMCL: $[-1.9955, -0.4935, 0.0055\,\text{rad}]$
- **执行时间**: 仿真耗时 $6.400\,\text{s}$（墙上耗时 $5.912\,\text{s}$）
- **Nav2 Action 终端状态**: `SUCCEEDED` (Code 4)
- **终点位姿**:
  - GT: $[-2.0001, -0.5039, 2.8756\,\text{rad}]$
  - AMCL: $[-1.9445, -0.5701, 2.8067\,\text{rad}]$
- **几何终态误差**:
  - GT 位置误差: **$0.2001\,\text{m}$**（契约阈值 $\le 0.30\,\text{m}$，**PASSED**）
  - GT 航向误差: **$0.2644\,\text{rad}$** ($15.15^\circ$，契约阈值 $\le 0.35\,\text{rad}$，**PASSED**）
  - AMCL 估计误差: 位置 $0.1606\,\text{m}$，航向 $0.3333\,\text{rad}$
- **2.0s 稳定观察窗口**:
  - 采样样本数: 119 个
  - 窗口内位置全部合规: `TRUE`
  - 窗口内航向全部合规: `TRUE`
  - 车辆完全停稳 ($|v| < 0.05\,\text{m/s}, |\omega| < 0.05\,\text{rad/s}$): `TRUE`
  - 窗口内最大 GT 物理漂移: $0.0002\,\text{m}$
- **时间对齐定位审计 ($\Delta t \le 0.1\,\text{s}$)**:
  - 匹配对齐样本数: 10
  - AMCL 与 GT 平均位移差异: **$0.0634\,\text{m}$** ($6.34\,\text{cm}$)
- **最终综合判定**: `strict_physical_arrival_and_stable = TRUE`

---

### 4.4 独立取消测试 Episode 4：长距离动态行驶取消 (`nav_ep4_cancel`)
- **目标位姿**: $[x=0.50\,\text{m}, y=1.80\,\text{m}, \text{yaw}=0.00\,\text{rad}]$（无遮挡长距离可达航点）
- **初始位姿 (Spawn)**:
  - GT: $[-2.0000, -0.5000, 0.0001\,\text{rad}]$
  - AMCL: $[-1.9883, -0.4868, 0.0067\,\text{rad}]$
- **运动中取消判定逻辑**:
  1. Action 分发后，调度器持续以 20 Hz 轮询 `/odom` 的 `linear.x`；
  2. 观察到线速度升至 **$0.068\,\text{m/s}$**（$> 0.05\,\text{m/s}$），确认处于真实物理行进中；
  3. 立即通过 ActionClient 调用 `cancel_goal_async()`；
  4. 验证 Action 终端状态为 `STATUS_CANCELED`（Code 5）；
  5. 允许不超过 2.0s 仿真时间的减速刹车，轮询至线速度与角速度降至零；
  6. 开启连续 2.0s 稳定停止观察窗口。
- **取消测试执行指标**:
  - 动态取消触发速度: $v = 0.068\,\text{m/s}$
  - Action 状态: `CANCELED` (Code 5)
  - 减速稳定时间: 仿真时间 $0.126\,\text{s}$ 即完全静止
  - 静止态线速度: $0.0000\,\text{m/s}$
  - 静止态角速度: $0.0003\,\text{rad/s}$
  - 2.0s 停止窗口采样数: 125 个
  - 停止窗口内最大 GT 位移变化: **$0.0000\,\text{m}$**
  - 最终距未达目标的残留误差: $3.3894\,\text{m}$
- **最终综合判定**: `cancel_stop_verified = TRUE`

---

## 5. Unified Action Dispatcher Verification

系统已通过 `src/action_dispatcher.py` 与 `src/action_runtime.py` 实现统一动作接入控制，并编写了单元测试套件 `tests/test_action_dispatcher.py`。

### 5.1 调度与拦截流水线
```
Action JSON / Markdown Codeblock
  │
  ▼
1. Strict Parsing & Syntax Validation (JSON 解析，禁止 NaN/Inf/多对象/外包裹文本)
  │
  ▼
2. Schema & Coordinate Validation (action 存在性、有限三维坐标、有效 frame_id)
  │
  ▼
3. Parameter Normalization (补齐默认 frame_id='map', timeout_sec=60.0)
  │
  ▼
4. Runtime Context & History Verification:
     - 检查 action_id 唯一性
     - 检查 retry 目标存在性，禁止自引用与递归引用
     - 计算可见状态指纹（排除隐藏状态/GT 标签）
     - 限制相同状态指纹至多 1 次重试
     - 限制每 Episode 至多 3 次重试预算
     - 重试时自动恢复被引用的原始动作参数，防参数篡改
  │
  ▼
5. ROS Goal UUID 确定性派生 (基于 episode_id + action_id 生成 uuid5)
  │
  ▼
6. ROS 2 ActionClient Dispatch & Terminal Record
```

### 5.2 单元测试覆盖率
执行 `pytest -v` 验证结果：
- `test_duplicate_action_id_never_dispatches_to_ros`: **PASSED**
- `test_exceeding_retry_budget_blocked`: **PASSED**
- `test_parameter_tampering_on_retry_never_dispatches`: **PASSED**
- `test_repeated_retry_under_identical_visible_state_blocked`: **PASSED**
- `test_syntax_invalid_action_never_dispatches`: **PASSED**
- `test_valid_navigate_dispatch_with_defaults`: **PASSED**
- `test_valid_retry_restores_original_params`: **PASSED**
- 全局测试统计: **37 passed, 8 xfailed**（8 个 xfail 为 R0 缺陷复现探针，符合预期）。

---

## 6. Audit Checksums & Artifact Verification

证据目录：`reports/evidence/p1a_v2/p1a_v2_20260928_005206_479fbc/`

| File Relative Path | SHA256 Checksum | Description |
| :--- | :--- | :--- |
| `summary.json` | `219bac5ad56f39bb510ee0c92af1ba3b7d74aed085480dfafaef4a02b96f1098` | 汇总结果（四组 Episode 完整指标、评分阈值与结论） |
| `run_config.json` | `a96ab0f9b3275dd65a40ec08b0e8ac0572b7e3215085bc7a1bb6ecb858298db7` | 运行配置（环境参数、节点参数与阈值配置） |
| `checksums.sha256` | `c7c646b5e1bfe48cf5f42be7e04f2f5fcbb4b5536e65bb896895318db4b830d9` | 本次运行全部 34 个文件的权威哈希清单 |
| `episode_1/episode_summary.json` | `82e0d660567597fe9e6b7b9b8726aa0a90d3848f12395835a9edcbdbbc61b1ac` | Episode 1 独立指标文件 |
| `episode_1/events.log` | `ef8714ba7f12d679619b4ca2ac8676c705ecb17a493538d8987c6940eb129db3` | Episode 1 节点事件时序日志 |
| `episode_1/trajectory.json` | `aa4dcf6762b7f6ad6407ce776e1749d8a46073cc098a97f982bf98afaebd364b` | Episode 1 全程轨迹与时间对齐定位审计样本 |
| `episode_1/stability_window.json`| `080fea6dcb5dfd87ef30018d04057f552904db1d39b1b0ea55ce56178dd1eaaf` | Episode 1 连续 2.0s 稳定窗口高频采样（123 帧） |
| `episode_2/episode_summary.json` | `42047b0fee6665f319e0001fc9f8196f5c21cd8c8d0d0ca87cf8e2dab814e059` | Episode 2 独立指标文件 |
| `episode_2/trajectory.json` | `cd078b67422c9ead56a7da870345108d00619c0696dea6c3e9e11f0f8de33faf` | Episode 2 全程轨迹与时间对齐定位审计样本 |
| `episode_2/stability_window.json`| `fa6865964d633bbe85f639c0020ad91f8ddae7f663f76b3cc601d806b3293596` | Episode 2 连续 2.0s 稳定窗口高频采样（123 帧） |
| `episode_3/episode_summary.json` | `aaf2ca7d5478d2f86961e8b4cc303857bb3c5df909c7d6cac92826ff0a578f1d` | Episode 3 独立指标文件 |
| `episode_3/trajectory.json` | `da021773dffe3f442ee7cde6e84c221cc1f3d44360a17c31b47d6408d5321947` | Episode 3 全程轨迹与时间对齐定位审计样本 |
| `episode_3/stability_window.json`| `285ca1c75c08c875c50a2482d306a19a8eb9422147ffeef0d72e9f90cbcbb88f` | Episode 3 连续 2.0s 稳定窗口高频采样（119 帧） |
| `episode_4/episode_summary.json` | `4fadf83676f2b25ed8e14c2c46bfc10dfd15b874952d9f7f8d7fa7ba22e74327` | Episode 4 取消测试指标文件 |
| `episode_4/stability_window.json`| `e5d1b0fb3f48b4bf7ed3d3adc619ac50749125dcde972100603ec1e6f0209f3c` | Episode 4 取消后连续 2.0s 停稳窗口高频采样（125 帧） |

---

## 7. Status Matrix: Verified vs Deferred Items

| Item / Capability | Target Status | P1a-v2 Reality | Verdict |
| :--- | :--- | :--- | :--- |
| **Independent Episode Simulation Reset** | Clean process restart per episode | Complete kill of Gazebo/Nav2, /clock restart, lifecycle verified | **PASSED** |
| **Unified ROS Sim Time** | `use_sim_time=True` on all nodes | Verified node parameter, /clock advance check, 4-way timestamps | **PASSED** |
| **Coordinate Frame Equivalence** | Prove $p_{\text{map}} \equiv p_{\text{world}}$ | Validated through world center $(0,0)$ and map origin $[-10,-10]$ | **PASSED** |
| **Position Tolerance (0.30m)** | $\le 0.30\,\text{m}$ strictly enforced | Ep1: 0.2587m, Ep2: 0.2217m, Ep3: 0.2001m (All $\le 0.30\,\text{m}$) | **PASSED** |
| **Stability Window Halt** | $\ge 2.0\,\text{s}$ sim time, $\|v\| < 0.05\,\text{m/s}$ | 119–125 samples, $|v| < 0.05\,\text{m/s}$, $|\omega| < 0.05\,\text{rad/s}$, drift $\le 0.0023\,\text{m}$ | **PASSED** |
| **Cancel Safety Halt** | Active move $\to$ Cancel $\to$ Halted | Cancel at $v=0.068\,\text{m/s}$, terminal `CANCELED`, stopped in 0.13s, drift $0.0\,\text{m}$ | **PASSED** |
| **Time-Aligned Localization Audit** | $\Delta t \le 0.1\,\text{s}$ AMCL vs GT | Mean discrepancy: Ep1 3.5cm, Ep2 3.8cm, Ep3 6.3cm, Ep4 4.1cm | **PASSED** |
| **Strict Action Dispatcher** | Parse $\to$ Validate $\to$ Restrict $\to$ UUID | Integrated into runner; 7 unit tests passing | **PASSED** |
| **Observe Action** | Target visual inspection | Not yet implemented in simulation | **DEFERRED** (to P1b) |
| **LLM Planning Loop** | Autonomous agent plan & recover | Not connected in P1a | **DEFERRED** (to P2) |
| **FailMem Retrieval & Expiry** | Failure memory indexing | Not implemented in P1a | **DEFERRED** (to P2) |
| **Formal Test Benchmark** | Comparative claims | Not conducted | **DEFERRED** (to P3) |

---

## 8. Exact Reproduction Commands

```bash
# 1. 运行全部单元测试（校验器、动作历史约束、调度器流水线）
pytest -v

# 2. 执行 P1a-v2 四组独立 Episode 仿真评测
docker run --rm -v /code/failmem-ros2-agent:/workspace failmem:ros2_humble_p1a python3 /workspace/scripts/run_p1a_v2.py
# 或通过封装入口：
docker run --rm -v /code/failmem-ros2-agent:/workspace failmem:ros2_humble_p1a /workspace/scripts/entrypoint_p1a.sh v2

# 3. 校验生成产物的完整性哈希
cd /code/failmem-ros2-agent/reports/evidence/p1a_v2/p1a_v2_20260928_005206_479fbc
sha256sum -c checksums.sha256
```
