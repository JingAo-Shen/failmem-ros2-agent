# FailMem P1a-v3 Review Report: 被动停车验证、作用域UUID、实证坐标系证明与P1b最小Observe接口

- **Stage**: P1a-v3 (Passive Halt Verification, Scoped Goal UUIDs, Empirical Coordinate Proof, and P1b Minimal Observe Interface)
- **Status**: PASSED
  - 被动停车验证（移除正常验收路径 cmd_vel 发送，独立安全干预记录）：已通过 (PASSED)
  - 运动中取消与物理停止验证（前置新鲜 odom 运动确认 $v=0.099\,\text{m/s} > 0.05\,\text{m/s}$ + cancel accepted + CANCELED 终态 + 2.0s 停稳）：已通过 (PASSED)
  - 严格滑动窗口与数据新鲜度（废除样本数代用指标，严格校验时间单调递增、无 NaN/Inf、仿真时长 $\ge 2.0\,\text{s}$、最大间隔 $\le 0.5\,\text{s}$）：已通过 (PASSED)
  - 离线独立评测打分器（`src/scoring_evaluator.py` 严格读取 `configs/scoring_rules.yaml`）：已通过 (PASSED)
  - 真实 ROS 2 执行链与作用域 UUID（`derive_ros_goal_uuid` 传入 `ActionClient.send_goal_async`，验证 `GoalHandle.goal_id` 严格一致，重试还原原始动作参数，记录 ACCEPTED 与终端状态）：已通过 (PASSED)
  - 实证坐标系一致性证明（`src/coordinate_alignment.py` 实测 5 处非共线静态地标，最大残差 $0.0459\,\text{m} \le 0.075\,\text{m}$）：已通过 (PASSED)
  - 独立进程组管理（`os.setsid` 与 `os.killpg`，杜绝全局盲杀）：已通过 (PASSED)
  - P1b 最小 observe 接口（`src/observe_interface.py` 只读观测，严格白名单安全过滤，绝不泄漏 GT 与故障标注）：已实现并通过全量单测 (PASSED)
- **Run ID**: `p1a_v3_20260928_012052_b272f5`
- **Execution Timestamp**: 2026-09-28T01:22:26.491890+00:00
- **Base Commit**: `3eb228a`
- **Review Date**: 2026-09-28
- **Evidence Path**: `reports/evidence/p1a_v3/p1a_v3_20260928_012052_b272f5/`
- **Domain Isolation**: `ROS_DOMAIN_ID=42`, `ROS_LOCALHOST_ONLY=1`

---

## 1. Executive Summary & Review Scope

本报告针对研究负责人对 P1a-v2 的复核意见，完成 **P1a-v3** 修复与复验，并同步交付 **P1b 最小 observe 接口**。

### 核心改进与修复闭环对照

1. **被动停车验证修复**：
   - 移除 `wait_for_settling()` 中对 `/cmd_vel` 发送零速度的主动干预代码。在正常验收路径上，仅被动观察 Nav2 自身控制停止行为、Odom 与 Ground Truth；
   - 设立独立安全干预机制：仅在超过安全超时且车辆仍未减速时触发强制停车，并标记 `safety_intervention=true`，直接判定自主停车失败；
   - 本轮 4 个 Episode 的 `safety_intervention` 均为 `false`，全部实现完全被动的自主物理停稳。

2. **严密的 Cancel 动作安全测试**：
   - 彻底废除仅打印警告即放行的逻辑。在发送取消前，必须通过新鲜 odom 确认机器人线速度 $|v| > 0.05\,\text{m/s}$（实测 $v = 0.099\,\text{m/s}$）；
   - 取消请求返回 `return_code == 0`（`ACCEPTED`），并收到 Action 最终 `CANCELED` 状态；
   - 取消后在无外部干预下，连续 2.4s 仿真时间内线速度保持 $0.0001\,\text{m/s}$、角速度 $0.0003\,\text{rad/s}$、GT 位移变化 $0.0000\,\text{m}$，通过停稳验收。

3. **严格窗口覆盖与样本新鲜度检验**：
   - 彻底废除 `len(samples) >= 10` 等样本数代用指标；
   - 基于样本序列号与时间戳去重，过滤重复缓存读取；
   - 严密检查无 NaN / Inf，校验仿真时长覆盖（实测 2.400s $\ge 2.0\text{s}$），最大采样间隔 $0.10\text{s} \le 0.50\text{s}$；
   - 区分 `cmd_vel` 状态（`ZERO_COMMANDS_RECEIVED` vs `NO_COMMANDS_RECEIVED` vs `NON_ZERO`）。

4. **抽离离线评测打分器 (`src/scoring_evaluator.py`)**：
   - 将所有几何容差、停稳速度阈值、窗口时长等评测逻辑从执行脚本完全抽离为独立纯函数；
   - 严格从 `configs/scoring_rules.yaml` 读取配置参数，供在线 runner 与离线 CI/CD 评测双向调用；
   - 包含针对陈旧缓存、缺失里程计、NaN 坐标/速度、窗口不足、时钟冻结、提前取消、取消拒绝、外部安全干预、超差等 11 项负例与正例单元测试，全部通过。

5. **真实执行链接入与作用域 UUID 传递**：
   - 基于 `(action_id, run_id, episode_id)` 派生 UUID5 确定性 ROS Goal UUID；
   - 修复 ROS 2 Humble 下 `ActionClient.send_goal_async(goal_msg, goal_uuid=ros_uuid)` 传递，并通过 `bytes(goal_handle.goal_id.uuid) == goal_uuid.bytes` 严格验证；
   - 重试动作自动还原被引用的原始动作参数，并在派生 UUID 中引入重试序号隔离；
   - 显式向动作历史上下文回写 `ACCEPTED` 状态与最终终端状态。

6. **实证式坐标系一致性证明 (`src/coordinate_alignment.py`)**：
   - 提取 PGM 地图图像像素与 SDF 世界文件，验证图像行反转变换：$y_{\text{map}} = y_0 + (H - v) \times \text{resolution}$；
   - 实测 5 处非共线静态柱体地标（中心、东、南、西、北），最大残差仅 $0.0459\,\text{m} \le 0.075\,\text{m}$（$1.5 \times \text{resolution}$），严格证明 $p_{\text{world}} \equiv p_{\text{map}}$。

7. **优雅进程组生命周期管理**：
   - 使用 `os.setsid` 隔离仿真子进程组，退出时先发送 `SIGTERM` 并在超时后升级为 `SIGKILL`，杜绝跨 Episode 进程残留与盲目 `pkill -9 -f`。

8. **P1b 最小 observe 接口交付 (`src/observe_interface.py`)**：
   - 提供标准化的只读感知观测，返回 AMCL 估计位姿与协方差、Odom 速度、LiDAR 扫描可用性与新鲜度、Nav2 状态；
   - 严格实施白名单安全过滤，绝不泄漏 Ground Truth、世界绝对坐标、故障注入标签或环境真值。

> [!IMPORTANT]
> **严格边界声明**：
> 本阶段限定为 P1a-v3 真实导航执行修复与 P1b 最小 observe 接口交付。
> - 暂不连接外部 LLM；
> - 暂不实现 FailMem 检索或记忆失效算法；
> - 暂不开展 P2 方法对比或基准扩增。

---

## 2. P1a-v3 Episode Execution Results (`p1a_v3_20260928_012052_b272f5`)

| Episode Index | Action ID | Action Type & Goal | Nav2 Status | GT Position Error | GT Yaw Error | Passive Halt Verified | Safety Intervention | Window Coverage | Final Strict Arrival |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ep 1** | `nav_ep1_fwd_corridor` | `navigate` $[-0.5, -0.5, 0.0]$ | `SUCCEEDED` | **$0.2613\,\text{m}$** ($\le 0.30$) | **$0.0599\,\text{rad}$** ($\le 0.35$) | **True** ($v=0.0001$) | **False** | 2.4s (74 samples) | **PASSED** |
| **Ep 2** | `nav_ep2_lateral_rot` | `navigate` $[0.5, -0.5, 1.57]$ | `SUCCEEDED` | **$0.2339\,\text{m}$** ($\le 0.30$) | **$0.2403\,\text{rad}$** ($\le 0.35$) | **True** ($v=0.0001$) | **False** | 2.4s (74 samples) | **PASSED** |
| **Ep 3** | `nav_ep3_return_rot` | `navigate` $[-1.8, -0.5, 3.14]$ | `SUCCEEDED` | **$0.2000\,\text{m}$** ($\le 0.30$) | **$0.2310\,\text{rad}$** ($\le 0.35$) | **True** ($v=0.0001$) | **False** | 2.4s (74 samples) | **PASSED** |
| **Ep 4** | `nav_ep4_cancel_test` | `navigate` $[0.5, 1.8, 0.0]$ (Cancel) | `CANCELED` | N/A (Cancel) | N/A (Cancel) | **True** ($v=0.0001$) | **False** | 2.4s (74 samples) | **PASSED** |

### 4.1 详细指标与审计记录

#### Episode 1: `nav_ep1_fwd_corridor`
- **Goal**: $[-0.5, -0.5, 0.0]$ | **Goal UUID**: `e5220ff6-0029-5fcf-846a-885c1a55d009` (GoalHandle UUID Match: `True`)
- **Nav2 耗时**: 仿真时间 $6.6\,\text{s}$，单调墙上时间 $5.412\,\text{s}$
- **最终 GT 位姿**: $[-0.7537, -0.5626, 0.0599\,\text{rad}]$，位置误差 **$0.2613\,\text{m}$**，航向角误差 **$0.0599\,\text{rad}$**
- **稳定窗口**: 2.4s 仿真时间（74 个独立样本），线速度最大值 $0.0001\,\text{m/s}$，角速度最大值 $0.0003\,\text{rad/s}$，GT 位移 $0.0000\,\text{m}$
- **AMCL vs GT 对齐审计**: 4 个时间对齐样本（$\Delta t \le 0.1\text{s}$），平均定位差异 **$0.0250\,\text{m}$**

#### Episode 2: `nav_ep2_lateral_rot`
- **Goal**: $[0.5, -0.5, 1.57]$ | **Goal UUID**: `7d5b8c4c-32ef-52d1-bc79-a40cebe3d8fa` (GoalHandle UUID Match: `True`)
- **Nav2 耗时**: 仿真时间 $14.8\,\text{s}$，单调墙上时间 $13.672\,\text{s}$
- **最终 GT 位姿**: $[0.2700, -0.5423, 1.3297\,\text{rad}]$，位置误差 **$0.2339\,\text{m}$**，航向角误差 **$0.2403\,\text{rad}$**
- **稳定窗口**: 2.4s 仿真时间（74 个独立样本），线速度最大值 $0.0001\,\text{m/s}$，角速度最大值 $0.0004\,\text{rad/s}$，GT 位移 $0.0000\,\text{m}$
- **AMCL vs GT 对齐审计**: 13 个时间对齐样本，平均定位差异 **$0.0174\,\text{m}$**

#### Episode 3: `nav_ep3_return_rot`
- **Goal**: $[-1.8, -0.5, 3.14]$ | **Goal UUID**: `9bed3480-c22f-50c5-84b3-3b6b8125e7ca` (GoalHandle UUID Match: `True`)
- **Nav2 耗时**: 仿真时间 $6.3\,\text{s}$，单调墙上时间 $4.812\,\text{s}$
- **最终 GT 位姿**: $[-2.0000, -0.5039, 2.9090\,\text{rad}]$，位置误差 **$0.2000\,\text{m}$**，航向角误差 **$0.2310\,\text{rad}$**
- **稳定窗口**: 2.4s 仿真时间（74 个独立样本），线速度最大值 $0.0001\,\text{m/s}$，角速度最大值 $0.0018\,\text{rad/s}$，GT 位移 $0.0002\,\text{m}$
- **AMCL vs GT 对齐审计**: 10 个时间对齐样本，平均定位差异 **$0.0531\,\text{m}$**

#### Episode 4: `nav_ep4_cancel_test`
- **Goal**: $[0.5, 1.8, 0.0]$ | **Goal UUID**: `18581e1a-2b7c-511e-9f37-62f57298deb5` (GoalHandle UUID Match: `True`)
- **前置运动确认**: 实时里程计确认线速度 $v = 0.099\,\text{m/s} > 0.05\,\text{m/s}$ 后触发取消
- **取消请求响应**: `cancel_accepted = True` (`return_code = 0`)
- **终端状态**: `CANCELED` (Code 5)
- **被动停稳验证**: 无外部安全干预，2.4s 仿真时间内线速度最大 $0.0001\,\text{m/s}$，角速度最大 $0.0003\,\text{rad/s}$，GT 位移 $0.0000\,\text{m}$，`cancel_stop_verified = True`

---

## 3. Empirical Coordinate Alignment Proof (`coordinate_alignment_proof.json`)

系统通过 `src/coordinate_alignment.py` 实测了地图与仿真世界的几何一致性：

| Landmark Name | World $(x, y)$ | Expected Pixel $(u, v)$ | Detected Map $(x, y)$ | Residual Error | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `two_two (center)` | $(0.0, 0.0)$ | $(200.0, 184.0)$ | $(0.0000, 0.0446)$ | **$0.0446\,\text{m}$** | PASSED ($< 0.075\text{m}$) |
| `one_two (west)` | $(-1.1, 0.0)$ | $(178.0, 184.0)$ | $(-1.0919, 0.0452)$ | **$0.0459\,\text{m}$** | PASSED ($< 0.075\text{m}$) |
| `three_two (east)` | $(1.1, 0.0)$ | $(222.0, 184.0)$ | $(1.0875, -0.0031)$ | **$0.0129\,\text{m}$** | PASSED ($< 0.075\text{m}$) |
| `two_three (north)` | $(0.0, 1.1)$ | $(200.0, 162.0)$ | $(0.0161, 1.1000)$ | **$0.0161\,\text{m}$** | PASSED ($< 0.075\text{m}$) |
| `two_one (south)` | $(0.0, -1.1)$ | $(200.0, 206.0)$ | $(-0.0069, -1.0759)$ | **$0.0251\,\text{m}$** | PASSED ($< 0.075\text{m}$) |

- **图像变换数学关系**:
  $$x_{\text{map}} = -10.0 + u \times 0.05, \quad y_{\text{map}} = -10.0 + (384 - v) \times 0.05$$
- **结论**: 5 处地标最大残差仅 $0.0459\,\text{m} \le 0.075\,\text{m}$（小于 $1.5$ 个网格单元），实证证明 Gazebo 物理世界与 Nav2 占据栅格地图完全重合，具备数学与工程一致性。

---

## 4. P1b Minimal Observe Interface Implementation (`src/observe_interface.py`)

`src/observe_interface.py` 实现了满足 P1b 契约的轻量只读观察接口：

```python
class ObserveInterface:
    def observe(self, target: Optional[str] = None) -> Dict[str, Any]:
        """Collect read-only robotic observation with whitelist security filtering."""
        ...
```

### 关键特性与安全约束
1. **只读数据流集成**：
   - AMCL 当前估计位姿 $(x, y, \theta)$ 及其协方差对角线元素；
   - 里程计实时线速度与角速度；
   - 2D LiDAR `/scan` 探测点数、最小障碍物测距与数据新鲜度；
   - Nav2 动作执行状态。
2. **严格白名单与信息防泄漏过滤**：
   - 严禁包含 `ground_truth`, `gt`, `world_pose`, `fault`, `fault_type`, `label`, `oracle`, `answer` 等敏感关键字；
   - 仅返回真实机器人可公开获取的板载感知与自定位数据，彻底杜绝特权真值泄漏。
3. **单元测试与异常防御**：
   - `tests/test_observe_interface.py` 覆盖正常观测、AMCL 缺失、AMCL 陈旧、Odom 缺失、Odom 陈旧、白名单过滤 6 项测试，全部通过。

---

## 5. Automated Test Suite Status

执行 `pytest -v`，测试总览如下：
- **Total Tests**: 66
- **Passed**: 58
- **XFailed**: 8 (明确重现 R0 原作者注入与审计缺陷，符合预期)
- **Failed**: 0

```
tests/test_action_dispatcher.py::TestActionDispatcher (9 passed)
tests/test_action_runtime.py::TestActionRuntime (7 passed)
tests/test_audit_reproductions.py::TestR0DefectReproduction (8 xfailed)
tests/test_failmem.py (2 passed)
tests/test_observe_interface.py::TestObserveInterface (6 passed)
tests/test_schema_validator.py::TestStrictSchemaValidator (21 passed)
tests/test_scoring_evaluator.py::TestScoringEvaluatorNegativeCases (11 passed)
tests/test_scoring_evaluator.py::TestScoringEvaluatorPositiveCases (2 passed)
```

---

## 6. Deliverable Artifacts & Checksums

本轮权威产物完整保存在 `reports/evidence/p1a_v3/p1a_v3_20260928_012052_b272f5/`：

```
reports/evidence/p1a_v3/p1a_v3_20260928_012052_b272f5/
├── checksums.sha256
├── coordinate_alignment_proof.json
├── run_config.json
├── summary.json
├── episode_1/
│   ├── episode_summary.json
│   ├── events.log
│   ├── nav2_sim.log
│   ├── ros_actions.txt
│   ├── ros_nodes.txt
│   ├── ros_topics.txt
│   ├── stability_window.json
│   └── trajectory.json
├── episode_2/...
├── episode_3/...
└── episode_4/...
```

所有文件的 SHA-256 哈希值均记录在 `checksums.sha256` 中，可供随时复核。
