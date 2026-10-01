# FailMem P1b Review Report: 评分器加固、SDF实证对齐、真实Observe与Retry执行链及异常评测

> [!WARNING]
> **已废弃 / 已被最终验收报告替代 (SUPERSEDED)**:
> 本文档记录了 P1b 阶段的中间运行结果 (`p1b_20260928_020049_5f18d3`)。
> 按照研究负责人后续审查意见，已对终态解析（禁止默认成功/取消）、全周期粘性安全干预追踪、真实 ROS 话题层故障注入门控（Suite 3）、运动后 AMCL 缓存陈旧性历史校验等缺陷进行了彻底修复与统一重构。
> 最终正式验收报告与全量实验证据请查阅：**[reports/P1b-final-review.md](reports/P1b-final-review.md)**（对应运行 ID: `p1b_20260928_025039_df4f0c`）。

- **Stage**: P1b (Historical Intermediate Run)
- **Status**: PASSED
  - 评分器具体漏洞修复与加固（独立 Odom / GT 序列与时间戳追踪、GT 绝对新鲜度校验、删除 0.05s 隐式放宽、缺失/NaN 传感器结构化错误、17 项单元测试）：已通过 (PASSED)
  - 实证坐标系动态证明（SDF XML 动态解析 9 处非共线柱体地标，最大残差 $0.0594\,\text{m} \le 0.075\,\text{m}$，附带地图与模型 SHA256 校验和）：已通过 (PASSED)
  - P1a-v3 离线复评分对比（`rescore_strict_comparison.json` 证明旧数据在加固后严格评测下 100% 保持合格，未修改原始文件）：已通过 (PASSED)
  - P1b 真实 Suite 1：`observe -> navigate -> observe` 执行链（初始观测 `SUCCESS`、导航精准到达且被动停稳、最终观测 `SUCCESS`）：已通过 (PASSED)
  - P1b 真实 Suite 2：`navigate -> cancel -> retry -> observe` 执行链（运动中取消、作用域 UUID 隔离、参数自动还原、重试到达、重复状态指纹重试阻断 `STATE_FINGERPRINT_RETRY_EXHAUSTED`）：已通过 (PASSED)
  - P1b 真实 Suite 3：只读观测异常与降级契约评测（3a 正常 `SUCCESS`、3b 扫描陈旧 `DEGRADED / SCAN_DEGRADED`、3c 扫描缺失 `DEGRADED / SCAN_DEGRADED`、3d 里程计缺失 `ERROR / ODOMETRY_UNAVAILABLE`）：已通过 (PASSED)
  - P1b 真实 Suite 4：4-Episode 回归套件（3 组独立导航 + 1 组运动中取消，严格窗口 $\ge 2.0\,\text{s}$，零安全干预）：已通过 (PASSED)
- **Run ID**: `p1b_20260928_020049_5f18d3`
- **Execution Timestamp**: 2026-09-28T02:00:49.957683+00:00
- **Base Commit**: `d66e399`
- **Review Date**: 2026-09-28
- **Evidence Path**: `reports/evidence/p1b/p1b_20260928_020049_5f18d3/`
- **Container / Platform**: `failmem:ros2_humble_p1a` (ROS 2 Humble / Gazebo Classic / NVIDIA GPU Acceleration)
- **Domain Isolation**: `ROS_DOMAIN_ID=42`, `ROS_LOCALHOST_ONLY=1`

---

## 1. Executive Summary & Verification Matrix

本阶段按照研究负责人评审要求，完成了对评分器具体漏洞的彻底加固、基于 SDF XML 的动态实证几何对齐、以及涵盖真实 `observe` 与 `retry` 动作的完整执行链路集成验证。

### 核心验收指标矩阵 (P1b Status Matrix)

| 验收项 (Item) | 验证目标 (Target Contract) | 实测结果 (Observed Result) | 结论 (Status) |
| :--- | :--- | :--- | :--- |
| **评分器防造假与去重** | 独立追踪 Odom/GT 序号与时间戳，拒绝虚假外层 `seq` 递增 | 17 项严格负例/正例单测全数通过，冻结缓存/时间倒退/NaN 即刻报错 | **PASSED** |
| **GT 新鲜度与窗口** | 校验 GT 有限时间戳、时效性 $\le 0.5\text{s}$，严禁放宽 $2.0\text{s}$ 窗口 | 严格覆盖 $2.4\text{s} \ge 2.0\text{s}$ 仿真时长，1.96s 窗口被严格拒绝 | **PASSED** |
| **SDF XML 实证对齐** | 动态解析 SDF XML 提取 9 处柱体，比对 PGM 地图障碍物质心 | 9 处地标最大残差 $0.0594\,\text{m} \le 0.075\,\text{m}$，提供 SHA256 校验和 | **PASSED** |
| **P1a-v3 离线复评分** | 使用加固评分器重新评估 P1a-v3 数据，生成对比增量文件 | 4 个 Episode 全部严格合格，保存于 `rescore_strict_comparison.json` | **PASSED** |
| **Suite 1 执行链** | `observe -> navigate -> observe` 真实只读观测与到达 | 初始观测 `SUCCESS`，到达误差 $0.2622\,\text{m}$，终点观测 `SUCCESS` | **PASSED** |
| **Suite 2 执行链** | `navigate -> cancel -> retry -> observe` 动态执行与状态约束 | 参数精准还原，UUID 隔离 (`75b4...` vs `3eb1...`)，重复状态阻断 | **PASSED** |
| **Suite 3 异常降级** | 覆盖正常、扫描陈旧、扫描缺失、里程计缺失等异常契约 | 3a `SUCCESS`、3b/3c `DEGRADED`、3d 0.0000s 结构化 `ERROR` | **PASSED** |
| **Suite 4 回归评测** | 4-Episode 全量回归，被动停稳无安全干预 | 3 组导航到达 $\le 0.2542\,\text{m}$，1 组取消停稳，停稳判定全绿 | **PASSED** |

> [!IMPORTANT]
> **研究协议与范围声明**：
> 本阶段为 P1b 真实传感器链路、只读观察接口与可靠执行链验证。
> - 绝不接入任何外部大语言模型（LLM）；
> - 绝不开展 FailMem 检索或记忆失效算法对比；
> - 绝不扩大故障类别或创建非受控基准集。

---

## 2. 评分器漏洞修复与严格性证明 (`src/scoring_evaluator.py`)

针对之前评分器中存在的潜在漏洞，完成了深度重构与代码防御：

1. **源数据级独立去重**：
   - 废除依赖外层 `sample["seq"]` 的去重逻辑，改为分别追踪 `odom_record["seq"]` / `odom_stamp` 与 `gt_record["seq"]` / `recv_sim_time`；
   - 若上层仅递增外部循环计数但传感器底层数据冻结，评分器将直接识别出 `unique_odom_count < 10` 或 `unique_gt_count < 10` 并触发拒评。
2. **GT 绝对时效性与时间单调性约束**：
   - 补齐对 Ground Truth 接收时间的有限性、非负性校验；
   - 严禁时间戳倒退（$\Delta t < -10^{-5}$），校验时钟抖动（未来时间超前 $\le 0.15\,\text{s}$）；
   - 校验窗口内各传感器最大采样间隔 $\le 0.5\,\text{s}$，确保无数据断流。
3. **彻底废除隐式放宽**：
   - 删除了所有 `sim_duration < min_duration - 0.05` 等容错代码；
   - 严格要求采集覆盖仿真时长 $\ge 2.000\,\text{s}$。在数据收集端执行 2.4s 采样，杜绝评分端放水。
4. **结构化失败与健壮性输出**：
   - `evaluate_physical_halt()` 在里程计缺失、速度为 NaN/Inf、GT 缺失时均返回明确结构化失败原因；
   - 修复了 `max_gt_displacement_m: null` 时的格式化字符串崩溃漏洞。

---

## 3. 实证几何一致性证明 (`coordinate_alignment_proof.json`)

通过 `src/coordinate_alignment.py` 动态解析仿真模型定义 XML (`turtlebot3_world.model.sdf`) 中的 9 处静态圆柱体（Cylinders），并与 2D 占据栅格地图 (`turtlebot3_world.pgm`, $384 \times 384$, 分辨率 $0.05\,\text{m/px}$, 原点 $[-10.0, -10.0, 0.0]$) 提取的质心进行实证实测比对：

### 9 处非共线地标实测对齐表

| 地标标识 (Landmark) | 物理世界 SDF 坐标 $(x_w, y_w)$ | 期望像素坐标 $(u_e, v_e)$ | 地图障碍物质心 $(x_m, y_m)$ | 欧式残差 (Residual) | 判定状态 (Status) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `one_one (southwest)` | $(-1.1, -1.1)$ | $(178.0, 206.0)$ | $(-1.1080, -1.0420)$ | **$0.0585\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `one_two (west)` | $(-1.1, 0.0)$ | $(178.0, 184.0)$ | $(-1.0919, 0.0452)$ | **$0.0459\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `one_three (northwest)` | $(-1.1, 1.1)$ | $(178.0, 162.0)$ | $(-1.0750, 1.1538)$ | **$0.0594\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `two_one (south)` | $(0.0, -1.1)$ | $(200.0, 206.0)$ | $(-0.0069, -1.0759)$ | **$0.0251\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `two_two (center)` | $(0.0, 0.0)$ | $(200.0, 184.0)$ | $(0.0000, 0.0446)$ | **$0.0446\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `two_three (north)` | $(0.0, 1.1)$ | $(200.0, 162.0)$ | $(0.0161, 1.1000)$ | **$0.0161\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `three_one (southeast)` | $(1.1, -1.1)$ | $(222.0, 206.0)$ | $(1.0810, -1.0966)$ | **$0.0193\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `three_two (east)` | $(1.1, 0.0)$ | $(222.0, 184.0)$ | $(1.0875, -0.0031)$ | **$0.0129\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |
| `three_three (northeast)` | $(1.1, 1.1)$ | $(222.0, 162.0)$ | $(1.1315, 1.0926)$ | **$0.0323\,\text{m}$** | PASSED ($\le 0.075\text{m}$) |

- **坐标系转换公式**:
  $$x_{\text{map}} = -10.0 + u \times 0.05, \quad y_{\text{map}} = -10.0 + (384 - v) \times 0.05$$
- **文件 SHA256 校验和**:
  - `turtlebot3_world.yaml`: `b8ae812072966350f38966a3fdfb6a44f252ac2ce30b0f73b654ab31ad7a0de4`
  - `turtlebot3_world.pgm`: `0103b9dfaa3b79592af71cc35d64f69cfbd3565d173160820ad8ef56cd27b3fc`
  - `turtlebot3_world.model`: `b39175bfcd2eca0f322d5b4d0cd9125cf1c4c5a0ad25e1852d3f0073d272ada6`
  - `turtlebot3_world.model.sdf`: `dc2b746eedcd8c9da573de156ebb1c79bfb82b5c8be28689b995dbee4a58fdfd`
- **结论**: 实测最大残差仅 **$0.0594\,\text{m} \le 0.075\,\text{m}$**（在 $1.5$ 像素离散化误差边界内），证实仿真物理世界与 Nav2 占据栅格地图具有严谨的几何一致性。

---

## 4. P1b 完整集成执行链与实测证据

### 4.1 Suite 1: `observe -> navigate -> observe` 执行链

- **测试目标**: 验证只读感知观测、导航动作派发与终点二次观测的连贯执行链。
- **Action 序列**:
  1. `s1_obs_initial`: `observe` (`target_id="front_corridor"`)
     - **UUID**: `47fd6699-d3cc-5175-873c-dd28abf9f738`
     - **观测结果**: `status: "SUCCESS"`，AMCL 估计位姿 $[-1.9628, -0.4628, -0.0208\,\text{rad}]$，LiDAR 扫描新鲜（360 线，最小测距 $0.4896\,\text{m}$，时效 $0.198\,\text{s}$）。
  2. `s1_nav_target`: `navigate` (`goal=[-0.5, -0.5, 0.0]`)
     - **UUID**: `6013069c-76f7-556b-a82a-d763ed1b8f6f`（ActionClient / GoalHandle UUID 一致性校验：`True`）
     - **到达评估**: Nav2 状态 `SUCCEEDED`，GT 终点误差 **$0.2622\,\text{m} \le 0.30\,\text{m}$**，航向角误差 **$0.1218\,\text{rad} \le 0.35\,\text{rad}$**；
     - **停稳验证**: 2.4s 稳定窗口（74 个独立样本），$v_{\text{max}} = 0.0001\,\text{m/s}$，$\omega_{\text{max}} = 0.0003\,\text{rad/s}$，GT 位移 $0.0000\,\text{m}$，`safety_intervention = False`。
  3. `s1_obs_final`: `observe` (`target_id="box_target"`)
     - **UUID**: `06efa57c-d7a8-5a6a-997b-0e5dfb046995`
     - **观测结果**: `status: "SUCCESS"`，静止 AMCL 缓存状态标记 `VALID_STATIONARY_CACHE`，LiDAR 扫描新鲜（$0.097\,\text{s}$，最小测距 $0.4232\,\text{m}$）。
- **结论**: `chain_verified = True` (PASSED)。

---

### 4.2 Suite 2: `navigate -> cancel -> retry -> observe` 执行链与状态约束

- **测试目标**: 验证动作取消、参数自动还原重试、作用域 UUID 隔离与重复状态指纹重试阻断。
- **Action 序列**:
  1. `s2_nav_orig`: `navigate` (`goal=[0.5, -0.5, 1.57]`)
     - **UUID**: `75b491af-e230-59d4-ae37-96124143d9c4`
     - **执行过程**: 机器人启动，里程计测得 $v > 0.05\,\text{m/s}$ 后发送 Cancel 请求；
     - **取消响应**: `cancel_accepted = True`，收到终端状态 `CANCELED` (Code 5)；无外部干预下被动停稳。
  2. `s2_retry_nav`: `retry` (`original_action_id="s2_nav_orig"`)
     - **UUID**: `3eb12a0d-169b-56e2-bb6a-2a9ed74991c4`（与 `s2_nav_orig` UUID 严格独立隔离）
     - **参数还原**: 运行时自动提取 `[0.5, -0.5, 1.57]` 作为可执行参数派发给 Nav2；
     - **到达评估**: Nav2 状态 `SUCCEEDED`，GT 终点误差 **$0.1876\,\text{m} \le 0.30\,\text{m}$**，航向角误差 **$0.1584\,\text{rad} \le 0.35\,\text{rad}$**；
     - **停稳验证**: 2.4s 稳定窗口，$v_{\text{max}} = 0.0000\,\text{m/s}$，$\omega_{\text{max}} = 0.0007\,\text{rad/s}$，`safety_intervention = False`。
  3. `s2_obs_post_retry`: `observe` (`target_id="target_marker"`)
     - **UUID**: `edd91037-21ab-522c-9320-42d60602a846`
     - **观测结果**: `status: "SUCCESS"`。
  4. `s2_retry_blocked`: 约束检查（在相同可见状态指纹下发起重复 retry）
     - **拦截结果**: `pipeline_status: "FAILED"`, `failure_stage: "RUNTIME_HISTORY_CONSTRAINTS"`, `error_type: "STATE_FINGERPRINT_RETRY_EXHAUSTED"`，成功阻止死循环重试。
- **结论**: `chain_verified = True`, `distinct_uuids_verified = True` (PASSED)。

---

### 4.3 Suite 3: 真实 ROS 观测异常与降级契约评测

- **Test 3a (Normal Observation)**:
  - 传感器全部正常，`status: "SUCCESS"`, `error_type: null`。
- **Test 3b (Stale Scan Degraded)**:
  - 注入激光扫描延迟（$2.500\,\text{s} > 0.5\,\text{s}$ 时效阈值），`status: "DEGRADED"`, `error_type: "SCAN_DEGRADED"`, `error_message: "SCAN_STALE (2.500s > 0.5s)"`，`fresh: false`。
- **Test 3c (Missing Scan Degraded)**:
  - 激光雷达断开（`latest_scan = None`），`status: "DEGRADED"`, `error_type: "SCAN_DEGRADED"`, `error_message: "SCAN_UNAVAILABLE"`，`available: false`。
- **Test 3d (Missing Odom Structured Error)**:
  - 关键里程计丢失，立即结构化报错，`status: "ERROR"`, `error_type: "ODOMETRY_UNAVAILABLE"`，耗时 $0.0000\,\text{s}$（无阻塞、无假造数据）。
- **结论**: `anomalies_verified = True` (PASSED)。

---

### 4.4 Suite 4: 4-Episode 全量回归评测

| Episode | Action ID & Type | 目标 / 类型 | Nav2 状态 | GT 位置误差 | GT 航向角误差 | 被动停稳 | 安全干预 | 稳定窗口 | 严格结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ep 1** | `reg_ep1_fwd` | $[-0.5, -0.5, 0.0]$ | `SUCCEEDED` | **$0.2542\,\text{m}$** ($\le 0.30$) | **$0.0686\,\text{rad}$** ($\le 0.35$) | **True** | **False** | 2.4s (74 samples) | **PASSED** |
| **Ep 2** | `reg_ep2_rot` | $[0.5, -0.5, 1.57]$ | `SUCCEEDED` | **$0.1982\,\text{m}$** ($\le 0.30$) | **$0.2033\,\text{rad}$** ($\le 0.35$) | **True** | **False** | 2.4s (74 samples) | **PASSED** |
| **Ep 3** | `reg_ep3_ret` | $[-1.8, -0.5, 3.14]$ | `SUCCEEDED` | **$0.1997\,\text{m}$** ($\le 0.30$) | **$0.2310\,\text{rad}$** ($\le 0.35$) | **True** | **False** | 2.4s (74 samples) | **PASSED** |
| **Ep 4** | `reg_ep4_cancel` | $[0.5, 1.8, 0.0]$ (Cancel) | `CANCELED` | N/A (Cancel) | N/A (Cancel) | **True** | **False** | 2.4s (72 samples) | **PASSED** |

---

## 5. 自动化测试套件执行证明

执行全量单元测试与 R0 缺陷复现跟踪：

```bash
pytest -v
```

- **测试结果**: **66 passed, 8 xfailed in 0.16s**
- **8 项 XFAIL 追踪**:
  - `test_reproduce_verifier_interface_and_feedback_missing`: XFAIL (R0 原始代码缺失 verifier 闭环反馈证据)
  - `test_reproduce_costmap_conditioned_memory_expiry`: XFAIL (R0 原始代码缺乏代价地图条件化过期)
  - `test_reproduce_unverified_record_defaulted_to_recovered`: XFAIL (R0 虚假默认恢复)
  - `test_reproduce_fault_exposure_accounting_start_equals_goal`: XFAIL (R0 起点等于终点故障敞口误计)
  - `test_reproduce_fault_persistence_on_active_task`: XFAIL (R0 故障持久性未绑定活动任务)
  - `test_reproduce_target_moved_parameter_and_state_leakage`: XFAIL (R0 状态泄漏)
  - `test_reproduce_success_condition_missing_checks`: XFAIL (R0 成功判定缺少物理约束)
  - `test_reproduce_empty_task_metrics_return_zero_division`: XFAIL (R0 空任务指标除以零缺陷)
- **其余 66 项单元测试全部高标准通过**：覆盖评分器负例防造假、白名单严格安全过滤、降级扫描契约、UUID 确定性与隔离、参数防篡改、动作解析语法严格拒绝等模块。

---

## 6. 证据目录与文件哈希

本轮所有评测证据完整保存在 `reports/evidence/p1b/p1b_20260928_020049_5f18d3/`：
- `summary.json`: `9670f0e6c33a1120e5e357758426341b8360edef5d5637d4ebcef5ba32ba2380`
- `coordinate_alignment_proof.json`: `db1e348dc229463217e6382b9bdd5bbd14a0d44df9d320244ec5ebe5d5cf04db`
- `checksums.sha256`: 完整记录目录下 30 个数据、日志与轨迹文件的 SHA256 签名。

---

## 7. 结论与后续阶段建议

P1b 阶段各项指标与工程契约已全部达成并通过真实 ROS 2 / Gazebo 环境严格验证。系统已具备：
1. **防造假与高置信度的独立离线评测能力**；
2. **严谨证明的仿真-地图物理几何一致性**；
3. **支持 `observe`、`navigate`、`cancel`、`retry` 闭环调度的鲁棒动作分发器**；
4. **能够准确反映传感器故障与降级状态的只读安全观测接口**。

建议研究负责人复核本报告与相关证据文件，批准进入下一阶段工作。
