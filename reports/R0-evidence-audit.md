# R0 真实性审计报告：主张与证据审计 (Evidence Audit)

- **项目**: `failmem-ros2-agent`
- **审计基准提交**: `f9b067b4c321e3304db6f71abc116497bf767aab`
- **审计阶段**: R0（研究真实性审计与研究状态修复，修订版）
- **审计日期**: 2026-09-26
- **执行分支**: `audit/r0-authenticity`
- **证据包路径**: [`reports/evidence/r0/`](evidence/r0/) (完整校验哈希见 `reports/evidence/r0/checksums.sha256`)

---

## 1. 核心主张与关键数字逐项审计

审计遵循标准格式：**主张或数字 → 所需证据 → 实际证据路径 → 能否重算 → 当前状态**。

| 序号 | 主张或数字 | 所需证据 | 实际证据路径 | 能否重算 | 当前状态 | 审计核查客观说明 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C1** | **摘要中声称 86.7% 恢复成功率** (`papers/draft.md:8`) | 完整的正式测试运行日志、逐样本判定记录及聚合结果，显示恢复成功率为 86.7%（如 156/180） | `papers/claims-evidence.csv` 引用 `runs/p3_final_summary.json`，但该文件 `FailMem_Full` 的 `mean_recovery_rate` 实际记录为 `0.8333` (83.33%) | **否**（重算所有现有 runs 均为 83.33%，86.7% 在原始数据中不存在） | **当前无法支持 (UNSUPPORTED / 撤回)** | 论文摘要中的 86.7% 与引用的实验汇总文件 `p3_final_summary.json` 不一致，无任何原始日志支撑。已从有效学术结论撤回。 |
| **C2** | **相对基线提高 53.4 个百分点 (+53.4 pp vs 33.3%)** (`papers/draft.md:8`, `papers/claims-evidence.csv:2`) | Baseline (MemOFF) 实际运行日志显示恢复率 33.3%，且主方法比其高出 53.4 个百分点 | `runs/final_MemOFF_VerOFF_seed*/metrics.json` 显示基线通过率亦为 `0.8333` (83.33%)，`runs/p3_final_summary.json` 中四组配置完全一致 | **否**（重算现有 runs 差值为 `83.33% - 83.33% = 0.0 pp`） | **当前无法支持 (UNSUPPORTED / 撤回)** | 53.4 百分点提升无实验数据支撑，基线运行记录为 83.33%，未得出过 33.3%；四组代码在 mock 环境下因单步后故障消失均通过，通过率完全相同。 |
| **C3** | **重复失败率从 18.2% 降到 0.0%** (`papers/draft.md:8`, `papers/claims-evidence.csv:3`) | 包含多次重复无效动作的基线轨迹日志，显示基线重复失败率为 18.2%，主方法降为 0.0% | `runs/final_MemOFF_VerOFF_seed*/metrics.json` 中基线 `repeat_failure_rate` 均为 `0.0`，`runs/p3_final_summary.json` 中所有组 `mean_repeat_rate` 均为 `0.0` | **否**（无任何 18.2% 的运行或计算记录） | **当前无法支持 (UNSUPPORTED / 撤回)** | 18.2% 在任何现有运行日志中均无对应记录，现有 mock 运行中所有配置均记录为 0.0%。已撤回。 |
| **C4** | **主表四组均为 83.3%** (`papers/draft.md:24-27`, `runs/p3_final_summary.json`) | 4 个独立配置 (MemOFF/ON × VerOFF/ON) 在受控仿真中的实验结果 | `runs/final_*/metrics.json` 和 `runs/p3_final_summary.json` | **可重算（仅针对现有 mock 产物）**（150/180 = 83.33%） | **无效评测 / 无机制信号 (INVALID EVALUATION)** | 1. `use_verifier` 未接入执行逻辑；2. 故障在 step 2 触发后，step 3 即自然消失，导致无记忆基线（盲重试）直接通过；3. 失败的 30 个任务纯粹因目标距离与步骤预算限制耗尽；4. 该指标是总任务通过率，非故障恢复率。因此该 83.3% 不能支撑任何科学结论。 |
| **C5** | **180 个故障任务、6 个未见布局、3 个随机种子** (`papers/draft.md:8, 20`) | 包含真实 6 个室内物理几何地图（.world/.yaml/costmap）及种子控制的随机环境 | `data/test_episodes.jsonl` | **可重算文件条目**（行数为 180） | **仅为标签占位与合成数据重复 (PSEUDO-DATA)** | 180 行测试数据仅为 12 组人造 2D 坐标循环平铺 15 次；`layout_id` 只是无任何几何地图文件的字符串标签；代码中完全没有种子随机性，不同 seed 仅复制了确定性逻辑。 |
| **C6** | **reports/P4-review.md 中 P4 PASSED** (`reports/P4-review.md:4`) | 经复核的 P0 文献与可行性报告、P1 真实 ROS2 冒烟与隔离评测器、P2 开发集机制实验与消融、P3 冻结正式实验以及 P4 论文证据包 | `reports/P4-review.md` 全文仅 5 行，无任何执行记录；`reports/` 目录下缺失 P0/P1/P2/P3 评审报告 | **否** | **完全不合格，撤回有效状态 (RETRACTED)** | P0-P3 阶段全部跳过，未开展真实 ROS2 仿真，直接标为 P4 PASSED，严重违背科研规程与执行契约。 |
| **C7** | **硬件报告中的显存和其他配置** (`reports/feasibility.md:2`, `README.md:32`) | 本地系统真实硬件审计命令（`nvidia-smi`, `lscpu`, `free -h`, `uname -a`） | 宿主系统现场执行输出 | **是（已实测）** | **硬件实测属实，但 ROS2 软件栈缺失 (HARDWARE CONFIRMED; ROS2 BLOCKED)** | 宿主实测为 1x NVIDIA RTX 2080 Ti (魔改 22 GB / 22528 MiB 显存)，CPU 为 i5-13490F (16 线程)，内存 31 GiB，系统为 Ubuntu 22.04 LTS。硬件属实。当前 shell 未发现 ros2，真实 ROS2 依赖未安装。 |

---

## 2. 仓库与本地运行资产清点清单

按照审计规范，对当前仓库及本地工作区中的运行目录与数据资产进行分类清点：

| 资产路径 | 产生时间 / 来源 | 当前状态分类 | 详细说明与审计证据 |
| :--- | :--- | :--- | :--- |
| `runs/final_FailMem_Full_seed17` 等 12 个运行目录 | 2026-09-15 23:12 (未入 Git) | **本地存在但未入库，且与声称结论无法对应** | 包含 `metrics.json`、`events.jsonl`、`predictions.jsonl`。各目录结果完全确定性一致（150/180，通过率 83.33%，重复率 0.0%）。但与论文声称的 86.7%、+53.4pp、18.2% 严重冲突。详细清单与哈希见 `reports/evidence/r0/historical_runs_manifest.json`。 |
| `runs/p3_final_summary.json` | 2026-09-15 23:12 (未入 Git) | **本地存在但未入库，且为粗糙 mock 汇总** | 仅包含四组配置的均值汇总（全为 0.8333 与 0.0）。被 `claims-evidence.csv` 引用为 86.7% 的来源。 |
| `reports/evidence/r0/` | 2026-09-26 23:40 (本轮 R0 审计收尾生成) | **已运行且原始证据完整 (R0 证据包，可入库)** | 包含：`audit_summary.json`、`reproduction_evidence.json`、`dataset_audit.json`、`failure_attribution_trace.json`、`environment_probe.json`、`historical_runs_manifest.json`、`pytest_output.txt`、`checksums.sha256` 及完整运行产物。 |
| `data/task-specs.jsonl` | commit `f9b067b` (入库) | **轻量样例集，含 2 项起终点相同** | 包含 12 条任务，覆盖 10 个独立坐标对与 3 个布局标签，其中 2 条任务（fixture_robot_01 与 11）起点等于终点 `[0,0]`。详见 `dataset_audit.json`。 |
| `data/test_episodes.jsonl` | commit `f9b067b` (入库) | **平铺模板集，含 15 项起终点相同** | 包含 180 条任务，由 12 个独立坐标对在 6 个未见布局标签下平铺 15 次生成。包含 15 条起点等于终点 `[0,0]` 的任务。并非 task-specs 的直接坐标复制，而是独立网格平铺。 |
| 真实 ROS2 / Gazebo 仿真运行记录 | 无 | **未运行 (NOT_RUN / BLOCKED)** | 仓库中没有任何 ROS2 launch 文件、bag 包、Gazebo 世界文件或真实仿真日志。系统未安装 ROS2。 |
| 真实 LLM 模型推理与规划日志 | 无 | **未运行 (NOT_RUN)** | `src/` 中没有任何 LLM 接口调用或 API 日志，仅为本地 10 行固定规则循环。 |

---

## 3. 数据集对比与失败归因客观分析

### 3.1 `task-specs.jsonl` 与 `test_episodes.jsonl` 的精确对比
经 `scripts/analyze_datasets.py` 计算（完整输出见 `reports/evidence/r0/dataset_audit.json`）：
- **任务条数**: `task-specs.jsonl` 共 12 条；`test_episodes.jsonl` 共 180 条。
- **唯一坐标数**: `task-specs.jsonl` 有 10 个唯一坐标对（包含重复坐标但不同布局/故障的组合）；`test_episodes.jsonl` 有 12 个唯一坐标对。
- **坐标分布差异**: `test_episodes.jsonl` 并不是简单复制 `task-specs.jsonl` 的坐标（`task-specs` 中的 `[4,6]`, `[8,2]`, `[2,8]`, `[4,1]`, `[8,7]`, `[2,3]` 未在 `test_episodes` 出现；而 `test_episodes` 包含 `[3,4]`, `[9,0]`, `[0,4]`, `[3,8]`, `[9,4]`, `[3,0]`, `[9,8]` 等全新坐标）。
- **起点终点相同**: `task-specs.jsonl` 有 2 条（16.7%）；`test_episodes.jsonl` 有 15 条（8.33%），均为 `initial_pos = [0,0]` 且 `goal = [0,0]`。在步进距离为 2.0m 的状态机中，这 15 条任务在 step 1 即判定成功，根本未达到 step 2 预设故障步。

### 3.2 180 任务中 30 项失败的精确逐步轨迹与归因
经 `scripts/trace_failures.py` 对 `formal_task_008` 与 `formal_task_012` 的逐步轨迹重放（详见 `reports/evidence/r0/failure_attribution_trace.json`）：
1. **`formal_task_008` (target_moved, 坐标 `[9.0, 4.0]`, 占 15 个失败任务)**:
   - 初始距离为 $\sqrt{9^2+4^2} \approx 9.85\text{m}$。
   - 第 1 步导航前进 2.0m，剩余 7.85m；
   - 第 2 步触发 `target_moved`，目标重定位为 `[10.0, 5.0]`，剩余距离突增至 9.18m；记忆库中未注册 `target_moved` 对应动作，执行盲重试（不产生前进位移，位移 0m）；
   - 第 3-6 步连续导航 4 次（每步 2.0m，共前进 8.0m）；
   - 6 轮循环耗尽，总有效导航仅 5 次（总航程 10.0m），而起点到重定位目标的距离为 $\sqrt{10^2+5^2} \approx 11.18\text{m}$，最终距离为 $1.18\text{m} > 0.3\text{m}$，因而失败。
2. **`formal_task_012` (action_timeout, 坐标 `[9.0, 8.0]`, 占 15 个失败任务)**:
   - 初始距离为 $\sqrt{9^2+8^2} \approx 12.04\text{m}$。
   - 即使无故障情况下，6 步导航最多覆盖 $6 \times 2.0\text{m} = 12.0\text{m}$，刚好到达边缘；
   - 第 2 步发生超时，无论记忆开启（执行 `clear_costmap`）还是关闭（执行 `retry`），均消耗 1 步且不产生位移；
   - 剩余 4 步加上第 1 步仅有 5 次有效导航（总航程 10.0m），距离目标剩余 $2.04\text{m} > 0.3\text{m}$，因而失败。
- **结论**: 失败原因在于固定 6 步预算与单步 2m 位移上限，发生故障消耗 1 步后导致有效导航步数不足（仅 5 步/10m），无法覆盖 11.18m 和 12.04m 的几何距离，并非恢复机制优劣的体现。

---

## 4. 审计结论

1. **撤回核心结论**: 论文初稿 `papers/draft.md` 与 `papers/claims-evidence.csv` 中的所有核心增益数字（86.7% 恢复率、+53.4 pp 相对提升、18.2% 重复失败率下降）全部标记为 **当前无法支持 (UNSUPPORTED)** 并正式撤回。
2. **撤回阶段状态**: `reports/P4-review.md` 中的 `PASSED` 结论正式撤回，标记为 **RETRACTED (撤回/无效)**。
3. **确认当前阶段**: 项目从虚假的 P4 阶段全面纠正回退至 **R0 真实性审计已完成（待研究负责人复核确认），准备进入 P0 文献核验与环境可行性核查阶段**。
