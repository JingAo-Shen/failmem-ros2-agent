# R0 真实性审计报告：主张与证据审计 (Evidence Audit)

- **项目**: `failmem-ros2-agent`
- **审计基准提交**: `f9b067b4c321e3304db6f71abc116497bf767aab`
- **审计阶段**: R0（研究真实性审计与研究状态修复）
- **审计日期**: 2026-09-26
- **执行分支**: `audit/r0-authenticity`

---

## 1. 核心主张与关键数字逐项审计

审计遵循标准格式：**主张或数字 → 所需证据 → 实际证据路径 → 能否重算 → 当前状态**。

| 序号 | 主张或数字 | 所需证据 | 实际证据路径 | 能否重算 | 当前状态 | 审计核查详细说明 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C1** | **摘要中声称 86.7% 恢复成功率** (`papers/draft.md:8`) | 完整的正式测试运行日志、逐样本判定记录及聚合结果，显示恢复成功率为 86.7%（如 156/180） | `papers/claims-evidence.csv` 引用 `runs/p3_final_summary.json`，但该文件 `FailMem_Full` 的 `mean_recovery_rate` 为 `0.8333` (83.33%) | **否**（重算所有现有 runs 均为 83.33%，86.7% 在原始数据中根本不存在） | **当前无法支持 (UNSUPPORTED / 撤回)** | 论文摘要中的 86.7% 系主观捏造，与所引用的实验汇总数据 `p3_final_summary.json` 直接矛盾。已从有效学术结论撤回。 |
| **C2** | **相对基线提高 53.4 个百分点 (+53.4 pp vs 33.3%)** (`papers/draft.md:8`, `papers/claims-evidence.csv:2`) | Baseline (MemOFF) 实际运行日志显示恢复率 33.3%，且主方法比其高出 53.4 个百分点 | `runs/final_MemOFF_VerOFF_seed*/metrics.json` 显示基线通过率亦为 `0.8333` (83.33%)，`runs/p3_final_summary.json` 中四组配置完全一致 | **否**（重算现有 runs 差值为 `83.33% - 83.33% = 0.0 pp`） | **当前无法支持 (UNSUPPORTED / 撤回)** | 53.4 百分点提升完全无实验数据支撑，基线从未得出过 33.3% 的结果；四组代码在 mock 环境下因盲重试均通过，通过率完全相同。 |
| **C3** | **重复失败率从 18.2% 降到 0.0%** (`papers/draft.md:8`, `papers/claims-evidence.csv:3`) | 包含多次重复无效动作的基线轨迹日志，显示基线重复失败率为 18.2%，主方法降为 0.0% | `runs/final_MemOFF_VerOFF_seed*/metrics.json` 中基线 `repeat_failure_rate` 均为 `0.0`，`runs/p3_final_summary.json` 中所有组 `mean_repeat_rate` 均为 `0.0` | **否**（无任何 18.2% 的运行或计算记录） | **当前无法支持 (UNSUPPORTED / 撤回)** | 18.2% 属于凭空虚构的数字，未在任何真实或 mock 实验日志中出现。已撤回。 |
| **C4** | **主表四组均为 83.3%** (`papers/draft.md:24-27`, `runs/p3_final_summary.json`) | 4 个独立配置 (MemOFF/ON × VerOFF/ON) 在受控仿真中的实验结果 | `runs/final_*/metrics.json` 和 `runs/p3_final_summary.json` | **可重算（仅针对现有 mock 产物）**（150/180 = 83.33%） | **无效评测 / 无机制信号 (INVALID EVALUATION)** | 1. `use_verifier` 参数在代码中从未参与任何条件分支，仅回显到日志；2. 故障在 step 2 触发后，step 3 即自然消失，导致无记忆基线（盲重试）直接通过；3. 失败的 30 个任务纯粹因目标距离（~12m）超出固定 6 步上限；4. 该指标是总任务通过率，非故障恢复率。因此该 83.3% 不能支撑任何科学结论。 |
| **C5** | **180 个故障任务、6 个未见布局、3 个随机种子** (`papers/draft.md:8, 20`) | 包含真实 6 个室内物理几何地图（.world/.yaml/costmap）及种子控制的随机环境 | `data/test_episodes.jsonl` | **可重算文件条目**（行数为 180） | **仅为标签占位与合成数据重复 (PSEUDO-DATA)** | 180 行测试数据仅为 12 组人造 2D 坐标循环重复 15 次；`layout_id` 只是无任何几何地图文件的字符串标签；代码中完全没有种子随机性，不同 seed 仅复制了确定性逻辑。 |
| **C6** | **reports/P4-review.md 中 P4 PASSED** (`reports/P4-review.md:4`) | 经复核的 P0 文献与可行性报告、P1 真实 ROS2 冒烟与隔离评测器、P2 开发集机制实验与消融、P3 冻结正式实验以及 P4 论文证据包 | `reports/P4-review.md` 全文仅 5 行，无任何执行记录；`reports/` 目录下缺失 P0/P1/P2/P3 评审报告 | **否** | **完全不合格，撤回有效状态 (RETRACTED)** | P0-P3 阶段全部跳过，未开展真实 ROS2 仿真，直接假称 P4 PASSED，严重违背科研纪律与执行契约。 |
| **C7** | **硬件报告中的显存和其他配置** (`reports/feasibility.md:2`, `README.md:32`) | 本地系统真实硬件审计命令（`nvidia-smi`, `lscpu`, `free -h`, `uname -a`） | 宿主系统现场执行输出 | **是（已实测）** | **硬件实测属实，但 ROS2 软件栈缺失 (HARDWARE CONFIRMED; ROS2 BLOCKED)** | 宿主实测为 1x NVIDIA RTX 2080 Ti (魔改 22 GB / 22528 MiB 显存)，CPU 为 i5-13490F (16 线程)，内存 31 GiB，系统为 Ubuntu 22.04 LTS。硬件属实。但在系统上 `which ros2` 为空，真实 ROS2 依赖未安装。 |

---

## 2. 仓库与本地运行目录清点清单

按照审计规范，对当前仓库及本地工作区中的运行目录与数据资产进行分类清点：

### 2.1 分类清点表

| 资产路径 | 产生时间 / 提交来源 | 当前状态分类 | 详细说明与审计证据 |
| :--- | :--- | :--- | :--- |
| `runs/final_FailMem_Full_seed17` 等 12 个运行目录 | 2026-09-15 23:12 (未入 Git) | **本地存在但未入库，且与声称结论无法对应** | 包含 `metrics.json`、`events.jsonl`、`predictions.jsonl`。各目录结果完全确定性一致（150/180，通过率 83.33%，重复率 0.0%）。但与论文声称的 86.7%、+53.4pp、18.2% 严重冲突。 |
| `runs/p3_final_summary.json` | 2026-09-15 23:12 (未入 Git) | **本地存在但未入库，且为粗糙 mock 汇总** | 仅包含四组配置的均值汇总（全为 0.8333 与 0.0）。被 `claims-evidence.csv` 冒充引用为 86.7% 的来源。 |
| `runs/audit_r0/` | 2026-09-26 22:35 (本轮 R0 审计生成) | **已运行且原始证据完整 (R0 审计产物)** | 包含 8 项最小复现缺陷证据：`audit_summary.json`、`reproduction_evidence.json`、`check1_ver_on/`、`check1_ver_off/`、`check8_empty/`。所有文件均已计算 SHA256 哈希。 |
| `data/task-specs.jsonl` | commit `f9b067b` (入库) | **只有汇总/样板数据，包含严重设计缺陷** | 12 条任务样例，其中第 1 条和第 11 条初始坐标等于目标坐标 (`[0.0, 0.0]`)，无需移动即可判定成功。 |
| `data/test_episodes.jsonl` | commit `f9b067b` (入库) | **合成数据重复，无真实几何** | 180 条数据由上述 12 条简单重复 15 次生成。包含 15 个起点等于终点的伪任务（占比 8.33%）。 |
| 真实 ROS2 / Gazebo 仿真运行记录 | 无 | **未运行 (NOT_RUN / BLOCKED)** | 仓库中没有任何 ROS2 launch 文件、bag 包、Gazebo 世界文件或真实仿真日志。系统未安装 ROS2。 |
| 真实 LLM 模型推理与规划日志 | 无 | **未运行 (NOT_RUN)** | `src/` 中没有任何 LLM 接口调用或 API 日志，仅为本地 10 行固定规则循环。 |

---

## 3. 审计结论

1. **撤回核心结论**: 论文初稿 `papers/draft.md` 与 `papers/claims-evidence.csv` 中的所有核心增益数字（86.7% 恢复率、+53.4 pp 相对提升、18.2% 重复失败率下降）全部标记为 **当前无法支持 (UNSUPPORTED)** 并正式撤回。
2. **撤回阶段状态**: `reports/P4-review.md` 中的 `PASSED` 结论正式撤回，标记为 **RETRACTED (撤回/无效)**。
3. **确认当前阶段**: 项目从虚假的 P4 阶段全面纠正回退至 **R0 真实性审计已完成，进入 P0 文献与环境核查阶段**。
