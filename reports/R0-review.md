# R0-Review: FailMem 研究真实性审计与状态修复报告

- **项目**: `failmem-ros2-agent` (https://github.com/JingAo-Shen/failmem-ros2-agent)
- **阶段**: R0（研究真实性审计与研究状态修复）
- **审计基准提交**: `f9b067b4c321e3304db6f71abc116497bf767aab`
- **实际 HEAD**: `f9b067b4c321e3304db6f71abc116497bf767aab`
- **独立研究分支**: `audit/r0-authenticity`
- **审查结论**: **R0 AUDIT COMPLETED / P4 STATE RETRACTED (R0 真实性审计完成，虚假 P4 状态已撤回)**

---

## 1. 审阅起点、实际 HEAD 与运行环境

### 1.1 Git 状态与基准
- **当前本地分支**: `audit/r0-authenticity` (自 `main` 分支检出，基准为 `f9b067b`)
- **HEAD Commit**: `f9b067b4c321e3304db6f71abc116497bf767aab` (*feat: complete FailMem research pipeline (P0-P4) with four-quadrant evaluation and paper draft*)
- **初始 Git 状态**: 工作区干净，无未跟踪冲突文件（`runs/` 目录被 `.gitignore` 忽略但存在于本地未入库文件系统）。

### 1.2 宿主环境实测
- **操作系统**: Linux sja 6.8.0-83-generic #83~22.04.1-Ubuntu SMP x86_64
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13490F (10 核心 / 16 线程)
- **内存 (RAM)**: 31 GiB (空闲可用 ~7.7 GiB)
- **GPU (实测)**: 1x NVIDIA GeForce RTX 2080 Ti (实测显存 **22528 MiB / 22.0 GB**，驱动版本 580.82.07，CUDA 13.0)
- **Python**: Python 3.13.5 (Anaconda 环境, pytest 8.3.4)
- **ROS2 环境**: **未安装 (BLOCKED)**。`which ros2` 返回空，系统无 ROS2/Nav2/Gazebo 二进制安装。

---

## 2. 逐项核查当前实现（16 项详细证据）

对代码库实现进行了系统性逐行代码静态审计与动态重现，结果如下：

### 2.1 `src/sim_env.py` 是否真正接入 ROS2、Gazebo、Nav2？
- **文件位置**: `src/sim_env.py:1-60`
- **实际行为**: 仅引入 `numpy` 和 `time`，维护 2D 坐标点（`self.pos`、`self.goal`）及简单算术累加；代码中没有任何 `rclpy`、`geometry_msgs`、Nav2 Action Client 或 Gazebo 仿真接口。
- **研究影响**: 极高。完全脱离真实机器人物理和传感器模拟，无雷达点云、无代价地图栅格膨胀、无动力学约束，无法验证真实 ROS2 移动机器人的故障恢复有效性。
- **最小复现证据**: `grep -rn "rclpy\|ros2\|geometry_msgs\|nav2" src/` 返回结果为 0；`which ros2` 在宿主机上无任何输出。

### 2.2 `use_verifier` 是否实际控制后置条件验证和反馈？
- **文件位置**: `src/evaluate.py:8-13, 78, 96`
- **实际行为**: `use_verifier` 仅作为形参传入 `run_evaluation`，在主体逻辑中没有任何条件判断 (`if use_verifier:`)，仅在第 78 行与第 96 行原样写入 `event_record` 和 `metrics.json`。
- **研究影响**: 致命缺陷。所谓的 "Verifier ON" 与 "Verifier OFF" 完全是表面参数，对 Agent 决策与执行逻辑 0 影响，四象限实验中的验证器消融对照完全是假象。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_verifier_toggle_affects_execution_and_feedback` (XFAIL)；对比 `use_verifier=True` 与 `False` 生成的轨迹事件除回显字段外完全逐字节相同。

### 2.3 记忆是否来自真实训练轨迹？
- **文件位置**: `src/evaluate.py:18-33`
- **实际行为**: 记忆并非来自训练 Episode 或在线探索累积，而是在 `evaluate.py` 内部硬编码了两条人造规则：
  - `"ERROR: Path blocked by dynamic obstacle." -> "clear_costmap"`
  - `"ERROR: Navigation action timed out." -> "clear_costmap"`
- **研究影响**: 致命缺陷。将人工规则假称为“记忆机制”，未实现训练轨迹提取、经验提炼或跨任务学习。
- **最小复现证据**: 查看 `src/evaluate.py:18-33`，代码中直接调用 `store.record_failure(...)` 写死规则，未加载任何外部训练数据集。

### 2.4 缺少恢复证据时，是否默认记录为 RECOVERED？检索时是否检查验证结果？
- **文件位置**: `src/failmem.py:28-30, 37-46`
- **实际行为**: 
  - 第 29 行：`rec.get("verified_outcome", "RECOVERED")`，在未提供验证状态时默认填入 `"RECOVERED"`；
  - 第 38 行：检索 SQL 为 `SELECT recovery_action, map_version FROM failure_records WHERE symptom = ?`，根本没有过滤 `verified_outcome = 'RECOVERED'`，即使标为 `FAILED` 的动作也会被照常检索。
- **研究影响**: 严重违背 FailMem 核心原则（仅复用经验证成功的经验），造成错误甚至失败策略的盲目复用。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_unverified_record_defaulted_to_recovered` (XFAIL)；未传验证状态的记录在数据库中持久化为 `RECOVERED`。

### 2.5 `map_ver <= current_map_version` 是否错误允许旧环境记录继续使用？现有测试是否遗漏 1→2 的情境？
- **文件位置**: `src/failmem.py:44`, `tests/test_failmem.py:18-19`
- **实际行为**: 
  - `src/failmem.py:44` 逻辑为 `if map_ver <= current_map_version: return action`。当环境地图由版本 1 改变到版本 2 时，`1 <= 2` 恒为真，旧地图记录被错误继续检索；
  - 原测试 `tests/test_failmem.py` 刻意测试了 `current_map_version=0` 来断言 None，刻意回避了单调递增的实际场景（1→2）。
- **研究影响**: 致命缺陷。失效机制与设计目标完全相反，旧地图障碍记忆在地图变更后永远不会失效。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_memory_expiry_when_map_version_updates_from_1_to_2` (XFAIL)；存入 `map_version=1`，查询 `current_map_version=2` 时仍返回 `"clear_costmap"`。

### 2.6 故障是否只在某一步触发，下一步即自动消失？
- **文件位置**: `src/sim_env.py:29-37`
- **实际行为**: 故障判断使用 `if self.step_count == self.task_spec.get("injected_fault_step", 2):`。当 `step_count == 2` 报错后，机器人若在 `step_count == 3` 再次执行 `navigate`，条件不满足，故障自动解除。
- **研究影响**: 致命缺陷。障碍物在 1 个 step 后自动凭空消失，导致不带任何记忆、验证和恢复的盲目重试（Blind Retry）也能自然通过，解释了为什么基线通过率与主方法相同。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_fault_disappears_enabling_blind_navigate` (XFAIL)；step 2 报错 `Path blocked`，step 3 盲目执行 `navigate` 直接返回成功。

### 2.7 `clear_costmap` 是否被错误建模为能够消除实体障碍？
- **文件位置**: `src/sim_env.py:20-23, 30`
- **实际行为**: 执行 `clear_costmap` 动作仅将 `self.costmap_cleared = True`，并在 step 2 使得 `not self.costmap_cleared` 变为 False，从而跳过 `path_blocked` 故障。
- **研究影响**: 物理现实违背。在真实 Nav2 中，`clear_costmap` 只负责清理传感器虚假感知栅格，不能消除物理实体障碍。当前实现将其当成了“魔法消除障碍物”。
- **最小复现证据**: 检查 `src/sim_env.py` 第 20-31 行代码逻辑。

### 2.8 目标移动后，navigate 是否直接读取环境内部最新目标坐标？
- **文件位置**: `src/sim_env.py:26, 33`
- **实际行为**: 第 33 行在 `target_moved` 触发时修改环境内部 `self.goal += [1.0, 1.0]`；而在第 26 行 `navigate` 默认目标为 `params.get("goal", self.goal.tolist())`。Agent 调用 `navigate` 不传参时直接读取了环境内部被修改后的真值坐标。
- **研究影响**: 严重真值泄漏。Agent 未通过 `observe` 探索或视觉发现，便通过环境内部变量瞬间获取目标新坐标，属于全知作弊。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_target_moved_ground_truth_leakage` (XFAIL)；Agent 发生目标移动后直接盲调 `navigate()`，直接自动走到新坐标并判定成功。

### 2.9 成功判断是否真的包含到达距离、稳定时间和目标观察？
- **文件位置**: `src/sim_env.py:58-59`
- **实际行为**: `is_success()` 仅判断 `np.linalg.norm(self.goal - self.pos) < 0.3`。既没有检查 Agent 是否调用过 `observe`，也没有检查是否在目标点稳定 2 秒。
- **研究影响**: 评测标准严重缩水，与 `reports/feasibility.md` 中声称的“到达距离 < 0.3m 且稳定 2s”不符。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_success_condition_missing_stabilization_and_observation` (XFAIL)。

### 2.10 是否存在起点等于终点、导致故障注入前就成功的任务？
- **文件位置**: `data/task-specs.jsonl:1, 11`, `data/test_episodes.jsonl:1, 13, 25, 37, 49, 61, 73, 85, 97, 109, 121, 133, 145, 157, 169`
- **实际行为**: `fixture_robot_01` 与 `fixture_robot_11`，以及 `test_episodes.jsonl` 中的 15 个任务（占比 8.33%），其 `initial_robot_pos` 与 `goal_coord` 均为 `[0.0, 0.0]`。在 step 0 时距离即为 0.0m (< 0.3m)，step 1 直接判定成功并退出，根本未触发 step 2 的故障注入。
- **研究影响**: 评测集包含明显无效样例，人为抬高成功率分母。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_start_equals_goal_avoids_fault_injection` (XFAIL)。

### 2.11 `layout_id` 是否对应真实加载的不同几何地图？
- **文件位置**: `src/sim_env.py:5-15`, `data/test_episodes.jsonl`
- **实际行为**: `data/test_episodes.jsonl` 虽标注 `unseen_layout_1` 到 `unseen_layout_6`，但 `src/sim_env.py` 中根本没有对 `layout_id` 做任何地图加载、网格碰撞或障碍物生成的逻辑，完全是一个空旷无障碍的 2D 连续坐标空间。
- **研究影响**: 所谓“跨 6 个未见室内空间布局的泛化测试”完全属于虚假包装。
- **最小复现证据**: `grep -rn "layout" src/` 返回 0 行代码匹配。

### 2.12 是否实际调用 LLM planner？
- **文件位置**: `src/evaluate.py:47-68`
- **实际行为**: 完全是基于 `range(6)` 的 10 余行 Python 硬编码循环状态机，无任何 LLM API 调用或本地大模型权重加载。
- **研究影响**: 偏离了 LLM Agent 具身规划的研究主题。
- **最小复现证据**: 检查 `src/` 全部源码，无 `openai`、`langchain`、`vllm`、`transformers` 或提示词工程。

### 2.13 `recovery_success_rate` 是否实际上计算了总任务通过率？空分母如何处理？
- **文件位置**: `src/evaluate.py:87-94`
- **实际行为**: 
  - 第 87 行：`tsr = passed_count / max(total, 1)`，以总任务数作为分母，直接命名为 `recovery_success_rate`；实际上是 Task Success Rate (TSR)，不是研究计划中定义的“恢复成功数 / 检测到故障数”；
  - 第 88 行：重复失败率分母为 `total_steps`（循环步数），而不是“有决策机会的故障情境次数”；
  - 空分母处理：使用了 `max(total, 1)`，导致空任务集时返回 `0.0`，违背契约要求的 `null`。
- **研究影响**: 指标失真，偷换概念。
- **最小复现证据**: `tests/test_audit_reproductions.py::test_reproduce_empty_task_metrics_return_zero_instead_of_null` (XFAIL)；`run_evaluation([])` 输出 `0.0`。

### 2.14 日志是否逐动作记录导航、恢复、观察、验证、重试和成本？
- **文件位置**: `src/evaluate.py:74-83`
- **实际行为**: 每一个任务结束后只写入一行总结性 JSON (`task_id, fault_type, use_memory, use_verifier, passed, steps`)，没有记录中间每一步的 Action、状态快照、耗时、成本及验证结果。
- **研究影响**: 无法重放评分，无法审计 Agent 真实的恢复路径。
- **最小复现证据**: 检查 `runs/final_FailMem_Full_seed17/events.jsonl`，正好 180 行，每行对应一个 Episode 汇总，无 Step 级明细。

### 2.15 各方法是否具有相同时间、动作、恢复次数和底层导航预算？
- **文件位置**: `src/evaluate.py:47-68`
- **实际行为**: 外层循环写死为固定 6 次迭代。每次移动上限为 2.0m，对于距离大于 12m 的目标（如 `[9.0, 8.0]`，距离 12.04m），即使正常航向也需要 7 步，发生故障消耗 1 步后必定超时失败。预算设置粗糙且无仿真时钟与物理超时守护。
- **研究影响**: 现有 30 个失败任务完全是因为距离过远导致步数耗尽，与记忆和恢复机制毫无关联。
- **最小复现证据**: 检查 `runs/final_FailMem_Full_seed17/events.jsonl` 中所有 30 个失败任务，全部为 `formal_task_008` (坐标 [9, 4]) 与 `formal_task_012` (坐标 [9, 8])。

### 2.16 训练、开发、测试是否真正隔离？
- **文件位置**: `src/evaluate.py:18-33`, `data/task-specs.jsonl`, `data/test_episodes.jsonl`
- **实际行为**: 
  - `evaluate.py` 内部硬编码的记忆症状字符串与测试集注入故障字符串 100% 相同；
  - 测试集 `test_episodes.jsonl` 只是开发样例 `task-specs.jsonl` 的无差异简单复制（12 个坐标重复 15 次）；
  - 环境目标移动修改直接透传给未观察的 Agent。
- **研究影响**: 数据严重泄漏，测试集未真正独立，无法评估未见故障或未见地图。
- **最小复现证据**: 对比 `data/task-specs.jsonl` 与 `data/test_episodes.jsonl` 的几何坐标完全一致。

---

## 3. 问题严重度与研究影响

| 严重度等级 | 问题项 | 核心影响 |
| :--- | :--- | :--- |
| **FATAL (致命)** | 2.2 验证器开关为摆设、2.6 故障一单步后自动消失、2.8 目标移动内部真值透传、2.5 地图失效规则反向生效、C1-C3 论文核心数据虚构 | 研究假设完全未被实验验证，现有“高成功率”与“零重复失败”纯属代码漏洞与数据造假。 |
| **CRITICAL (严重)** | 2.1 无真实 ROS2/Gazebo 接入、2.3 记忆为硬编码规则、2.12 无真实 LLM Planner | 项目目前仅为一个 60 行的 NumPy 玩具状态机，非真实的具身智能 Agent 系统。 |
| **HIGH (高危)** | 2.10 起点终点重合逃避故障、2.11 虚假地图布局标签、2.15 步数预算粗暴截断造成假失败 | 评测数据集设计极不规范，存在虚假泛化包装。 |
| **MEDIUM (中度)** | 2.9 成功判定缺少稳定时间与观察、2.13 指标命名偷换且空分母不合格、2.14 缺少 Step 级轨迹事件记录 | 日志无法重放，指标计算不合规。 |

---

## 4. 无法支持或已撤回的旧结论清单

1. **撤回结论 1**: 论文摘要中“FailMem achieves an 86.7% fault recovery success rate, outperforming memory-less baseline by +53.4 percentage points”——**正式撤回，标记为当前无法支持 (UNSUPPORTED)**。
2. **撤回结论 2**: 论文摘要中“reducing the repeat failure rate from 18.2% to 0.0%”——**正式撤回，标记为当前无法支持 (UNSUPPORTED)**。
3. **撤回结论 3**: 论文第 2 节表 1 中声称的四象限对照实验——**正式撤回，标记为无效评测 (INVALID EVALUATION)**。
4. **撤回结论 4**: `reports/P4-review.md` 中的 `审查状态: PASSED (通过)`——**正式撤回，标记为 RETRACTED**。
5. **纠正表述 5**: `EXECUTION-CONTRACT.md` 中“当前根目录未初始化 git”——**更正为 Git 仓库已正确初始化并纳管**。
6. **纠正表述 6**: `reports/feasibility.md` 中“到达距离 < 0.3m 且稳定 2s”——**更正说明当前状态机未实现稳定时间与观察验证**。

---

## 5. 可以复用的代码与研究资产

尽管先前的实验与学术主张严重不实，但仍有以下基础规范和框架可以作为后续真实研发的基础资产予以保留和复用：

1. **研究顶层设计与规范体系**:
   - `docs/research-plan.md`：定义了严谨的失败记忆元组 Schema、科学假设 H1-H3、四象限对照与指标分子分母。
   - `experiments/experiment-matrix.md`：定义了完整的基线（B0-B5）与消融组（A0-A3）。
   - `EXECUTION-CONTRACT.md` 与 `RESEARCH-EXECUTION-GUIDE.md`：确立了可重放、防泄漏与严格诚信原则。
2. **状态存储接口原型**:
   - `src/failmem.py` 中的 SQLite 表结构定义为记忆存储提供了轻量基础，后续在此基础上扩展完整 Schema 并修复失效与过滤逻辑。
3. **已实测验证的本地硬件环境**:
   - 实测确认拥有 1x RTX 2080 Ti (22 GB 显存) 与 i5-13490F，具备在本地运行中小型开源 LLM（如 Qwen2.5-7B/14B）或作为 ROS2 仿真主机的计算能力。
4. **审计测试与复现套件**:
   - 本轮新增的 `tests/test_audit_reproductions.py` 与 `scripts/reproduce_audit_findings.py`，形成了永久固定代码缺陷的防退化基准。

---

## 6. 修改文件清单

| 修改类型 | 文件路径 | 修改内容说明 |
| :--- | :--- | :--- |
| **新增** | `reports/R0-evidence-audit.md` | 7 项核心主张与数字追溯审计、运行资产清点表及结论。 |
| **新增** | `reports/R0-review.md` | 本轮 R0 总报告，涵盖 16 项代码检查、缺陷证据、严重度分析及路线修正。 |
| **新增** | `pytest.ini` | 配置 `pythonpath = .`，修复原仓库中 `pytest` 运行时直接报 `ModuleNotFoundError: No module named 'src'` 的问题。 |
| **新增** | `tests/test_audit_reproductions.py` | 针对 8 大设计缺陷编写严格的 pytest 测试用例（标为 `@pytest.mark.xfail(strict=True)`），防止假阳性。 |
| **新增** | `scripts/reproduce_audit_findings.py` | 独立最小复现与哈希检验脚本，自动运行 8 项核查并输出结构化证据。 |
| **修改** | `reports/P4-review.md` | 撤销虚假 PASSED 状态，更新为 RETRACTED，并指引至 R0 审计报告。 |
| **修改** | `papers/draft.md` | 在文首增加学术诚信与结论撤回严正声明，将虚假数字标记为未证实占位符，保留历史文本供审计。 |
| **修改** | `papers/claims-evidence.csv` | 将 Claim C1、C2 状态更新为 RETRACTED / UNSUPPORTED。 |
| **修改** | `README.md` | 纠正项目真实状态（当前为轻量原型 Mock，未接入 ROS2 真实仿真），更新硬件实测信息，声明当前处于 R0 审计完成、进入 P0 阶段。 |
| **修改** | `EXECUTION-CONTRACT.md` | 纠正“未初始化 Git”陈述。 |
| **修改** | `reports/feasibility.md` | 纠正关于真值打分包含 2s 稳定时间的虚假陈述，明确指出当前为纯 2D 坐标 mock，真实 ROS2 仿真被阻塞。 |

---

## 7. 实际命令、退出码和运行目录

所有审计实验均在独立目录中隔离运行，保留完整日志与退出码：

| 命令 | 工作目录 | 退出码 | 输出/证据路径 | 状态说明 |
| :--- | :--- | :---: | :--- | :--- |
| `pytest -v` | `/code/failmem-ros2-agent` | `0` | 终端输出 (2 passed, 8 xfailed) | 8 个缺陷复现用例均如期触发 XFAIL，原 2 个用例通过。 |
| `python3 scripts/reproduce_audit_findings.py` | `/code/failmem-ros2-agent` | `0` | `runs/audit_r0/audit_summary.json`<br>`runs/audit_r0/reproduction_evidence.json` | 8 项缺陷核查 100% 动态重现，生成并校验 SHA256 哈希。 |
| `git status && git log -n 5 --oneline` | `/code/failmem-ros2-agent` | `0` | 终端输出 | 确认分支、基准提交与工作树状态。 |
| `which ros2` | `/code/failmem-ros2-agent` | `1` | 终端输出 (无路径) | 证实系统当前未安装 ROS2。 |
| `nvidia-smi` | `/code/failmem-ros2-agent` | `0` | 终端输出 (22528 MiB) | 证实 22GB 显存硬件配置属实。 |

### 关键运行证据哈希清单 (SHA256)
- `runs/audit_r0/audit_summary.json`: `c7718c45ee6a36080c417d22246c7b631376d98a03b04570edfe8263305cb3a7`
- `runs/audit_r0/reproduction_evidence.json`: `d4260599f035e3fcd218e7f711f003df0ebe258e3dc9ad76840cc38c628918d9`
- `runs/audit_r0/check1_ver_on/events.jsonl`: `f3fd4d02edf7bdff4a19c30d65432a24acbcb40510676fd8925a41ef424f902a`
- `runs/audit_r0/check1_ver_off/events.jsonl`: `46a7c419d78427b2aaab7ffff26d90ed78a0d9c29657da49e5e58afe477b287e`

---

## 8. P0 / P1 的主要阻塞项 (Blockers)

在正式启动 P0（文献与环境核查）和 P1（真实仿真与可信评测）之前，存在以下关键技术阻塞项：

1. **ROS2 / Nav2 / Gazebo 环境缺失 (BLOCKER - CRITICAL)**:
   - 宿主机系统为 Ubuntu 22.04 LTS，支持安装 ROS2 Humble Hawksbill，但当前宿主机上未安装任何 ROS2 包、Nav2 或 Gazebo 仿真环境。
   - 解决路径：需在宿主机配置 ROS2 Humble 官方源，安装 `ros-humble-desktop`、`ros-humble-navigation2`、`ros-humble-nav2-bringup`，或构建包含 Headless Gazebo/Nav2 的隔离 Docker 容器。
2. **缺乏标准室内几何仿真场景 (BLOCKER - HIGH)**:
   - 缺少 6 个真实的室内二维栅格地图（.yaml/.pgm）与 Gazebo 世界（.world）模型；不能再以纯标签形式伪装布局。
   - 解决路径：引入 TurtleBot3 标准环境（如 AWS Small Warehouse, TurtleBot3 World, House）构建具身测试空间。
3. **真实 LLM 规划推理接入方案待定 (BLOCKER - MEDIUM)**:
   - 目前无 LLM Planner，且未定义明确的 Token / API 预算。
   - 解决路径：本地 RTX 2080 Ti 具备 22GB 显存，可利用 Ollama 或 vLLM 本地运行 7B/8B 模型（如 Qwen2.5-7B-Instruct / Llama-3.1-8B-Instruct），无需额外云 API 支出。

---

## 9. 建议下一轮（P0）只做什么

按照执行契约与阶段划分纪律，**不要直接跳入 P1/P2**，下一轮建议严格限制在 **P0：文献核验与环境可行性核查**，交付内容包括：
1. **文献真实性复核**: 全文阅读并比对 Reflexion、REFLECT、Voyager、Inner Monologue 等最近邻文献，填写真实可考的 `reports/literature.csv`，锁定 FailMem 与现有方法的因果区别。
2. **ROS2 仿真环境技术路线核定**: 确定是在宿主机安装 ROS2 Humble 还是使用 Docker 容器化运行；编写环境安装验证指南与自动化冒烟探测脚本。
3. **定义标准化动作与状态契约**: 正式确立机器人工具动作集合（`navigate`, `observe`, `clear_costmap`, `inspect_status`）的 ROS2 Action/Service 真实接口，以及真值评分器（距离 < 0.3m 且静止稳定 2s 且观察确认）的隔离实现规范。
4. **输出 `reports/P0-review.md`**，提交研究负责人复核。
