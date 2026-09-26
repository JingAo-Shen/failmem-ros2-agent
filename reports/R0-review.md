# R0-Review: FailMem 研究真实性审计与状态修复总报告 (修订版)

- **项目**: `failmem-ros2-agent` (https://github.com/JingAo-Shen/failmem-ros2-agent)
- **阶段**: R0（研究真实性审计与研究状态修复，收尾修订版）
- **审计基准提交**: `f9b067b4c321e3304db6f71abc116497bf767aab`
- **实际 HEAD**: `65a0219f4d022735b95d0ab3a873730c4d81abb2`
- **独立研究分支**: `audit/r0-authenticity`
- **审查结论**: **R0 AUDIT COMPLETED / P4 STATE RETRACTED (R0 真实性审计执行完成，待负责人复核确认；虚假 P4 状态已撤回)**
- **证据包归档**: [`reports/evidence/r0/`](evidence/r0/) (包含完整运行日志、环境探针、数据集对比、失败归因追踪与 SHA256 校验清单)

---

## 1. 审阅起点、实际 HEAD 与运行环境

### 1.1 Git 状态与基准
- **当前本地分支**: `audit/r0-authenticity`
- **HEAD Commit**: `65a0219f4d022735b95d0ab3a873730c4d81abb2` (*feat(audit): complete R0 research authenticity audit and state repair*)
- **审计基准 Commit**: `f9b067b4c321e3304db6f71abc116497bf767aab`
- **工作区状态**: 干净，未提交修改与新增测试工具均已纳管。

### 1.2 宿主环境实测探针（详见 `reports/evidence/r0/environment_probe.json`）
- **操作系统**: Linux sja 6.8.0-83-generic #83~22.04.1-Ubuntu SMP x86_64 (Ubuntu 22.04 LTS)
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13490F (10 核心 / 16 线程)
- **内存 (RAM)**: 31 GiB (空闲可用 ~7.7 GiB)
- **GPU (实测)**: 1x NVIDIA GeForce RTX 2080 Ti (实测物理显存 **22528 MiB / 22.0 GB**，驱动版本 580.82.07)
- **CUDA 区分**:
  - `nvidia-smi` 驱动兼容 CUDA 版本: **CUDA 13.0**
  - 宿主机已安装 CUDA Toolkit: **CUDA 13.0.88** (`/usr/local/cuda-13.0/bin/nvcc`)
  - Python PyTorch 运行时: **PyTorch 2.10.0+cu128** (内置 CUDA 12.8 运行时，`torch.cuda.is_available() == True`)
- **Python 环境**: Python 3.13.5 (Anaconda 环境, pytest 8.3.4, transformers 5.17.0)
- **ROS2 与容器系统探测**:
  - 当前 shell 未发现 ros2（`which ros2` 返回非零）；
  - 系统目录 `/opt/ros` 不存在；
  - `dpkg -l` 无任何 ROS 相关软件包安装；
  - `/etc/apt/sources.list.d/ros2-latest.list` 存在官方源配置 (`deb http://packages.ros.org/ros2/ubuntu jammy main`)；
  - 容器环境：`/usr/bin/docker` 已安装且 Docker 守护进程运行正常，可用于隔离容器化部署。

---

## 2. 逐项核查当前实现（16 项详细客观分析与证据）

### 2.1 `src/sim_env.py` 是否真正接入 ROS2、Gazebo、Nav2？
- **文件位置**: `src/sim_env.py:1-60`
- **实际行为**: 仅引入 `numpy` 和 `time`，维护连续 2D 坐标（`self.pos`、`self.goal`）；未调用任何 `rclpy`、ROS2 Topic/Service/Action、Nav2 Costmap 或 Gazebo 物理仿真接口。
- **研究影响**: 当前代码脱离真实机器人物理和传感器模拟，无雷达点云、无代价地图栅格膨胀、无动力学约束，无法验证真实 ROS2 移动机器人的故障恢复有效性。
- **最小复现证据**: `grep -rn "rclpy\|ros2\|geometry_msgs\|nav2" src/` 返回结果为 0；系统探测确认当前 shell 未发现 ros2，`/opt/ros` 不存在。

### 2.2 `use_verifier` 是否实际控制后置条件验证和反馈？
- **文件位置**: `src/evaluate.py:8-13, 78, 96`
- **实际行为**: `use_verifier` 仅作为布尔形参传入 `run_evaluation`，主体循环中没有该变量的条件分支逻辑，未调用任何验证器方法，也未向 Agent 返回验证器反馈；仅在第 78 行与第 96 行原样写入日志回显字段。
- **研究影响**: 观察接口缺失且开关未接入执行逻辑。因此两组最终成功率相同并不代表验证器无用，而是实验未真正执行验证器逻辑，四象限实验中的验证器消融对照未实际发生。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_verifier_interface_and_feedback_missing` (XFAIL)；检查 `events.jsonl` 中没有任何 `event_type == "verification"` 事件或验证器反馈记录。

### 2.3 记忆是否来自真实训练轨迹？
- **文件位置**: `src/evaluate.py:18-33`
- **实际行为**: 记忆库未通过训练 Episode 或自主探索积累，而是在 `evaluate.py` 内部人工硬编码了两条经验规则（`"ERROR: Path blocked..." -> "clear_costmap"` 与 `"ERROR: Navigation action timed out." -> "clear_costmap"`）。
- **研究影响**: 将人工预置规则等同于“学得记忆”，未实现从历史轨迹提炼经验的跨任务机制。
- **最小复现证据**: 检查 `src/evaluate.py:18-33`，两项记录被直接写入内存 SQLite，未加载任何外部训练集。

### 2.4 缺少恢复证据时，是否默认记录为 RECOVERED？检索时是否检查验证结果？
- **文件位置**: `src/failmem.py:28-30, 37-46`
- **实际行为**: 
  - 第 29 行：`rec.get("verified_outcome", "RECOVERED")`，在未提供验证状态时默认填入 `"RECOVERED"`；
  - 第 38 行：检索 SQL 为 `SELECT recovery_action, map_version FROM failure_records WHERE symptom = ?`，未过滤 `verified_outcome = 'RECOVERED'`，标为 `FAILED` 的动作也会被返回。
- **研究影响**: 无法区分经验证与未经验证的恢复动作，存在检索并执行失败动作的风险。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_unverified_record_defaulted_to_recovered` (XFAIL)。

### 2.5 `map_ver <= current_map_version` 是否错误允许旧环境记录继续使用？
- **文件位置**: `src/failmem.py:44`, `tests/test_failmem.py:18-19`
- **实际行为**: 
  - `src/failmem.py:44` 逻辑为 `if map_ver <= current_map_version: return action`。当环境地图由版本 1 改变到版本 2 时，依赖旧地图版本 1 障碍条件的记录因 `1 <= 2` 恒为真而被照常检索；
  - 原测试 `tests/test_failmem.py` 仅覆盖了 `current_map_version=0` 的边界情况，未覆盖单调递增的实际场景（1→2）。
- **研究影响**: 该条件未能实现依赖环境状态的记忆失效，导致在地图更新后依赖旧地图条件的记录继续被使用。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_costmap_conditioned_memory_expiry` (XFAIL)。

### 2.6 故障是否只在某一步触发，下一步即自动消失？
- **文件位置**: `src/sim_env.py:29-37`
- **实际行为**: 故障判断使用 `if self.step_count == self.task_spec.get("injected_fault_step", 2):`。在仍未完成的任务上（如目标在 5.0m 外），step 2 报错 `Path blocked` 后，若 step 3 再次盲目执行 `navigate`，因 `step_count == 3` 不满足故障条件，故障自动解除并允许机器人前进。
- **研究影响**: 物理障碍未能持续存在，使得不带恢复机制的无记忆基线（盲重试）在单步后自然通过，直接导致基线通过率虚高。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_fault_persistence_on_active_task` (XFAIL)；在 `assert not env.is_success()` 的未完成任务上，step 2 故障后 step 3 盲导航直接成功。

### 2.7 `clear_costmap` 是否被错误建模为能够消除实体障碍？
- **文件位置**: `src/sim_env.py:20-23, 30`
- **实际行为**: 执行 `clear_costmap` 动作仅将 `self.costmap_cleared = True`，并在 step 2 使得 `not self.costmap_cleared` 为 False，从而避开 `path_blocked` 故障。
- **研究影响**: 真实 Nav2 中清图只重置传感器瞬态图层，不能消除物理实体障碍。当前模拟将其等效为消除实体障碍。
- **最小复现证据**: 检查 `src/sim_env.py` 第 20-31 行代码逻辑。

### 2.8 目标移动后，navigate 是否直接读取环境内部最新目标坐标？
- **文件位置**: `src/sim_env.py:26, 33`
- **实际行为**: 发生 `target_moved` 故障时，环境内部将 `self.goal` 变更为新坐标；第 26 行在 Agent 调用 `navigate` 且未提供 `params["goal"]` 时，默认回退读取内部 `self.goal`，导致机器人在无参数输入且未执行 `observe` 的情况下向新目标位移。
- **研究影响**: 造成动作参数与内部环境状态的真值泄漏，Agent 无需观察即可获取目标新位置。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_target_moved_parameter_and_state_leakage` (XFAIL)；检测到机器人在未传参数时产生了朝向隐藏重定位目标的非零位移分量。

### 2.9 成功判断是否真的包含到达距离、稳定时间和目标观察？
- **文件位置**: `src/sim_env.py:58-59`
- **实际行为**: `is_success()` 仅判断 `np.linalg.norm(self.goal - self.pos) < 0.3`。未检查 Agent 是否调用过 `observe`，未检查是否在目标点维持 2 秒稳定。
- **研究影响**: 评测标准与 `reports/feasibility.md` 中声称的“到达距离 < 0.3m 且稳定 2s”不符。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_success_condition_missing_checks` (XFAIL)。

### 2.10 起点等于终点任务的处理与故障暴露分母
- **文件位置**: `data/task-specs.jsonl:1, 11`, `data/test_episodes.jsonl:15条任务`
- **实际行为**: 起点等于终点本身是机器人的合法边界场景，但在预设 step 2 注入故障的评测集中，起点等于终点的任务在 step 1 即判定成功退出，根本未触发故障注入。当前 runner 将其记录为通过并计入恢复率分子。
- **研究影响**: 评测未将“总分配任务主分析分母”与“实际暴露故障的子集”区分，导致未触发故障的样本被人为计为恢复成功。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_fault_exposure_accounting_start_equals_goal` (XFAIL)；`dataset_audit.json` 显示 `test_episodes.jsonl` 中有 15 条此类任务。

### 2.11 `layout_id` 是否对应真实加载的不同几何地图？
- **文件位置**: `src/sim_env.py:5-15`, `data/test_episodes.jsonl`
- **实际行为**: 数据集中的 `layout_1` 到 `layout_6` 仅为字符串标签，`src/sim_env.py` 未实现任何几何地图加载、栅格碰撞或障碍物生成逻辑。
- **研究影响**: 论文中“跨 6 个未见室内空间布局的泛化测试”在当前代码中仅为标签平铺，无几何泛化意义。
- **最小复现证据**: `grep -rn "layout" src/` 返回 0 行匹配。

### 2.12 是否实际调用 LLM planner？
- **文件位置**: `src/evaluate.py:47-68`
- **实际行为**: 执行主体为固定 6 步的 Python 规则状态机循环，无任何 LLM API 调用或本地大模型权重推理。
- **研究影响**: 当前代码未实现 LLM Agent 的具身决策。
- **最小复现证据**: 检查 `src/` 全部源码，无提示词、大模型客户端或调用接口。

### 2.13 `recovery_success_rate` 是否实际上计算了总任务通过率？空分母如何处理？
- **文件位置**: `src/evaluate.py:87-94`
- **实际行为**: 
  - `recovery_success_rate` 使用 `passed_count / max(total, 1)` 计算，实际是总任务通过率 (Task Success Rate)；
  - `repeat_failure_rate` 以总循环步数 `total_steps` 为分母，而非有决策机会的故障情境次数；
  - 空分母使用 `max(total, 1)` 输出 `0.0`，违背契约要求的 `null`。
- **研究影响**: 指标定义不一致，空集合输出失真。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_empty_task_metrics_return_zero_division` (XFAIL)。

### 2.14 日志是否逐动作记录导航、恢复、观察、验证、重试和成本？
- **文件位置**: `src/evaluate.py:74-83`
- **实际行为**: 每个任务结束后仅写入一行 Episode 汇总 JSON (`task_id, fault_type, use_memory, use_verifier, passed, steps`)，缺失 Step 级的 Action、传感器输入、真值状态、验证判定和时延成本。
- **研究影响**: 日志不可重放，无法独立重算评分。
- **最小复现证据**: 查看 `reports/evidence/r0/run_artifacts/check1_ver_on/events.jsonl`，仅有 1 行记录，缺少步进明细。

### 2.15 各方法是否具有相同时间、动作、恢复次数和底层导航预算？
- **文件位置**: `src/evaluate.py:47-68`
- **实际行为**: 统一硬编码为 6 次外层循环，每次导航最多位移 2.0m（最大覆盖航程 12.0m）。若第 2 步发生故障，因恢复动作不产生前进位移，有效导航次数被压缩至 5 步（最大位移 10.0m）。无仿真时钟与物理超时守护。
- **研究影响**: 对于实际距离超过 10.0m 的目标，发生故障后必定因步数不足而失败，导致通过率受制于几何距离而非恢复策略。
- **最小复现证据**: `reports/evidence/r0/failure_attribution_trace.json` 对 `formal_task_008` 与 `formal_task_012` 的逐步轨迹分析。

### 2.16 训练、开发、测试是否真正隔离？
- **文件位置**: `src/evaluate.py:18-33`, `data/task-specs.jsonl`, `data/test_episodes.jsonl`
- **实际行为**: 
  - `evaluate.py` 内部硬编码记忆的症状字符串与测试集注入故障字符串完全一致；
  - `test_episodes.jsonl` 由 12 个模板任务在 6 个布局标签下重复 15 次生成；
  - 目标移动后的内部状态直接被未观察的 Agent 默认读取。
- **研究影响**: 存在先验字符串硬编码与真值泄漏问题。
- **最小复现证据**: 对比 `dataset_audit.json` 与 `sim_env.py:26`。

---

## 3. 问题严重度与研究影响分级

| 严重度等级 | 核查项 | 核心影响与定位 |
| :--- | :--- | :--- |
| **FATAL (致命)** | 2.2 验证器开关未接入逻辑、2.5 地图失效规则判断颠倒、2.6 故障非持续（盲重试自然通过）、2.8 目标移动内部真值泄漏、C1-C3 核心数字缺乏数据支撑 | 核心机制未发挥实际作用，先前的“高成功率”与“零重复失败”不能成立。 |
| **CRITICAL (严重)** | 2.1 无 ROS2/Gazebo 真实接入、2.3 记忆为硬编码规则、2.12 无真实 LLM 规划器 | 系统目前属于轻量 mock 状态机，未达到具身 Agent 仿真标准。 |
| **HIGH (高危)** | 2.10 未暴露故障任务计入恢复率、2.11 虚假地图布局标签、2.15 固定步数截断造成假失败 | 评测集设计与预算设定不完备，影响评测可信度。 |
| **MEDIUM (中度)** | 2.9 成功判定缺少稳定时间与观察、2.13 指标定义不一致与空分母处理不合规、2.14 缺少 Step 级轨迹事件明细 | 日志不可重放，指标计算不合规。 |

---

## 4. 无法支持或已撤回的旧结论清单

1. **撤回结论 1**: 论文摘要中“FailMem achieves an 86.7% fault recovery success rate, outperforming memory-less baseline by +53.4 percentage points”——**正式撤回，标记为当前无法支持 (UNSUPPORTED)**。
2. **撤回结论 2**: 论文摘要中“reducing the repeat failure rate from 18.2% to 0.0%”——**正式撤回，标记为当前无法支持 (UNSUPPORTED)**。
3. **撤回结论 3**: 论文第 2 节表 1 中声称的四象限对照实验——**正式撤回，标记为无效评测 (INVALID EVALUATION)**。
4. **撤回结论 4**: `reports/P4-review.md` 中的 `审查状态: PASSED (通过)`——**正式撤回，标记为 RETRACTED**。
5. **纠偏说明 5**: `EXECUTION-CONTRACT.md` 中“当前根目录未初始化 git”——**更正为 Git 仓库已正确初始化并纳管**。
6. **纠偏说明 6**: `reports/feasibility.md` 中“到达距离 < 0.3m 且稳定 2s”——**更正说明当前状态机未实现稳定时间与观察验证**。

---

## 5. 可以复用的代码与研究资产

1. **研究顶层设计与规范体系**:
   - `docs/research-plan.md`：定义了严谨的失败记忆元组 Schema、科学假设 H1-H3、四象限对照与指标分子分母。
   - `experiments/experiment-matrix.md`：定义了完整的基线（B0-B5）与消融组（A0-A3）。
   - `EXECUTION-CONTRACT.md` 与 `RESEARCH-EXECUTION-GUIDE.md`：确立了可重放、防泄漏与严格诚信原则。
2. **状态存储接口原型**:
   - `src/failmem.py` 中的 SQLite 表结构定义为记忆存储提供了轻量基础，后续可扩展完整 Schema 并修复失效与过滤逻辑。
3. **已实测验证的本地计算与大模型资产**:
   - 宿主硬件拥有 1x RTX 2080 Ti (22 GB 显存) 与 i5-13490F；
   - 经实测探针确认，本地已完整缓存 **Qwen2.5-Coder-7B-Instruct** 权重（15GB safetensors），在 bfloat16 下加载占用 15.23 GB 显存，单次结构化推理解析耗时 2.05s，格式合法率 100%，具备无需云端付费 API 即可开展本地推理的能力。
4. **审计测试与复现套件**:
   - 本轮构建的 `tests/test_audit_reproductions.py`、`scripts/reproduce_audit_findings.py`、`scripts/analyze_datasets.py`、`scripts/trace_failures.py`，形成了可自动化复现与检验的防退化资产。

---

## 6. 修改文件清单

| 修改类型 | 文件路径 | 修改内容说明 |
| :--- | :--- | :--- |
| **新增** | `reports/evidence/r0/` | 完整 R0 证据包（JSON、环境探针、数据集对比、失败轨迹、pytest 输出、哈希清单）。 |
| **新增** | `scripts/analyze_datasets.py` | 两个 JSONL 数据集的条数、唯一坐标、故障分布与相同起终点对比脚本。 |
| **新增** | `scripts/trace_failures.py` | 失败任务（formal_task_008 与 012）逐步轨迹重放与数学归因分析脚本。 |
| **新增** | `scripts/generate_environment_probe.py` | 收集宿主机硬件、CUDA、Python、ROS2、Docker与Git状态探针脚本。 |
| **新增** | `scripts/generate_historical_runs_manifest.py` | 扫描并哈希化本地历史 runs 目录的归档脚本。 |
| **修改** | `tests/test_audit_reproductions.py` | 根据复核意见校正 8 个用例：改用未完成任务、检查验证器接口与反馈、区分故障暴露统计、参数泄漏检测、限制 AssertionError 异常类型。 |
| **修改** | `scripts/reproduce_audit_findings.py` | 支持 `--output-dir` 参数，更新 8 项核查逻辑，输出包含 Git 状态与时间戳的审计证据。 |
| **修改** | `reports/R0-evidence-audit.md` | 更新数据集对比、失败归因分析，采用客观中立描述，关联 evidence/r0 路径。 |
| **修改** | `reports/R0-review.md` | 本报告，更新详细证据、客观措辞与环境探针事实。 |
| **修改** | `README.md` | 明确 R0 执行完成（待负责人复核确认）；更新 ROS2 状态说明。 |
| **修改** | `reports/novelty-audit.md` | 将未获证据支持的贡献降级为“待验证假设 (Hypotheses)”。 |
| **修改** | `reports/feasibility.md` | 补充完整环境探针结果（CUDA、Docker、模型权重缓存）。 |

---

## 7. 实际命令、退出码和运行目录

| 命令 | 工作目录 | 退出码 | 输出/证据路径 | 状态说明 |
| :--- | :--- | :---: | :--- | :--- |
| `pytest -v` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/pytest_output.txt` | 8 个缺陷用例均准确触发预期的 AssertionError XFAIL，原 2 个用例通过。 |
| `python3 scripts/reproduce_audit_findings.py --output-dir reports/evidence/r0/run_artifacts` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/run_artifacts/` | 8 项设计缺陷 100% 确认存在。 |
| `python3 scripts/analyze_datasets.py` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/dataset_audit.json` | 准确分析两数据集的结构差异。 |
| `python3 scripts/trace_failures.py` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/failure_attribution_trace.json` | 完成 30 个失败任务的逐步轨迹与步数预算数学归因。 |
| `python3 scripts/generate_environment_probe.py` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/environment_probe.json` | 生成系统硬件、CUDA、Docker、ROS2 的现场探针记录。 |
| `python3 scripts/generate_historical_runs_manifest.py` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/historical_runs_manifest.json` | 完成历史未入库 12 个 runs 的文件与哈希归档。 |
| `sha256sum ... > checksums.sha256` | `/code/failmem-ros2-agent` | `0` | `reports/evidence/r0/checksums.sha256` | 校验清单生成完毕。 |

---

## 8. P0 / P1 的主要阻塞项 (Blockers)

1. **ROS2 / Nav2 软件栈缺失 (BLOCKER - CRITICAL)**:
   - 当前 shell 未发现 ros2，`/opt/ros` 不存在，dpkg 无包；
   - 宿主机存在 Docker 环境，优先考虑基于 Ubuntu 22.04 + ROS2 Humble + Gazebo Fortress + Nav2 构建标准容器镜像。
2. **物理仿真几何场景缺失 (BLOCKER - HIGH)**:
   - 需在 P1 准备一个真实的室内栅格与 Gazebo 世界闭环，解决地图标签与物理环境脱节的问题。
3. **统一物理动作与真值接口规范 (BLOCKER - MEDIUM)**:
   - 需通过 P0 交付 `docs/problem-lock.md`，冻结动作接口、传感器观察、真值评分器与失效规则规范。

---

## 9. 建议下一轮（P0）只做什么

待研究负责人复核通过本轮 R0 审计收尾后，下一轮严格执行 **P0：文献、环境与研究协议核查**：
1. **文献真实性复核**: 核查 Reflexion、REFLECT 及 2025-2026 近邻工作，更新 `reports/literature.csv`，在 `reports/novelty-audit.md` 明确本项目的差异化假设；
2. **环境可行性与容器方案**: 评估 Ubuntu 22.04 + ROS2 Humble + Gazebo Fortress + Nav2 兼容方案，准备 Dockerfile 与启动探测；
3. **大模型本地规划验证**: 制定基于已缓存 Qwen2.5-Coder-7B 的结构化输出与容错方案；
4. **冻结问题契约**: 输出 `docs/problem-lock.md`，锁定物理动作 Schema、真值评分条件与地图划分。
