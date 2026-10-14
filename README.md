# FailMem: Failure-Aware Memory for ROS 2 Autonomous Agents

> Research on episodic failure memory, verifiable execution contracts, and dynamic invalidation in ROS 2 / Nav2 autonomous navigation systems.

---

## Key Scientific Finding & Research Status (Milestone P2c / P2d)

> [!IMPORTANT]
> **核心研究发现与边界结论**：
> 1. **历史信息能够有效避免死胡同探索**：在双路径阻塞（D1）场景下，保留历史信息（失败记忆 $F$ 与空间缓存 $O$）相比反应式基线（$R$）消除死胡同重复进入（$0.0$ vs. $1.0$ 次）。FailMem ($F$) 相比反应式基线（$R$）节省 **$18.5\%$** 行驶距离与 **$22.3\%$** 运行时间（空间缓存 $O$ 相比 $R$ 节省 **$19.0\%$** 距离与 **$22.9\%$** 时间）。反应式基线（$R$）代表单会话内无跨阶段记忆的死胡同盲目重试，非碰撞或控制器崩溃。
> 2. **动态失效机制避免永久绕路代价**：在障碍清除（D2）场景下，感知驱动的动态失效机制使机器人重新启用近路，相比永久禁用记忆（$M1$）节省 **$11.0\%$** 行驶距离（$16.25\,\text{m}$ vs. $18.25\,\text{m}$）。
> 3. **本探索性数据中路线选择相同，未显示 F 的额外收益；尚未进行统计等效或一般化验证**：在静态 2D 几何障碍环境中，显式失败记忆（$F$）与空间观测缓存（$O$）选择了相同的高层路径，两者总距离与总耗时差异 $<1\%$（D1 距离差异 $+0.6\%$，耗时 $+0.7\%$；D2 距离差异 $-0.9\%$，耗时 $+0.9\%$）。现有探索性实验数据未显示失败语义在静态几何场景中优于空间缓存；本研究未量化比较系统维护或计算开销。
> 4. **H1 动作条件失败场景可行性检查（No-Go 终止）**：在门区几何通畅（`doorway_state == FREE`）下，可行性检查统一确认：“Nav2返回成功4/4，严格物理到达验证3/4；该候选场景未建立预期可执行性差异。” 按预设规程终止后续实验，不构成对一般动作条件失败记忆假设的证伪。

---

## Manuscript Status & Synchronization Policy (主稿与参考稿定位)

- 📄 **[投稿编辑主稿 (Primary Submission Source)](paper/submission_source/)** (`paper/submission_source/main.tex`, `paper/submission_source/supplementary.tex`):  
  **后续所有投稿排版、刊会模板迁移与审稿修订均以该目录为唯一主稿**。采用渠道中立的标准 LaTeX `article` 双栏排版，模块化拆分章节（`sections/`）、独立表格（`tables/`）、矢量插图（`figures/`）与核验文献库（`references.bib`），使用标准 `build.sh` 脚本编译并产出无警告 PDF 与 `build.log`。
- 🧊 **[冻结参考稿 (Frozen Reference Draft)](paper/draft.md)** (`paper/draft.md`, `paper/supplementary.md`, `paper/paper.pdf`, `paper/supplementary.pdf`):  
  对应提交 `de05246` 与 `5e6ed1f` 的 Markdown 终审产物。**作为版本基准永久冻结，仅供学术核对参考，严禁后续与主稿分头双向修改**，防止多格式源文件内容漂移。

---

## Deliverables & Traceability Materials (研究交付材料)

- 📄 **[投稿主稿及编译脚本](paper/submission_source/)** (`paper/submission_source/main.pdf`, `supplementary.pdf`, `build.sh`, `build.log`): 渠道中立 LaTeX 主稿套件。
- 🗺️ **[方法-代码映射表 (Method-Code Mapping)](paper/method-code-map.csv)**: 33 条参数与公式精确映射到源码行号。
- 📚 **[相关工作文献核验表](paper/reference-verification.csv)**: 全部 15 项核心文献均由出版社主源一手核验。
- 🗄️ **[冻结实验数据与证据库](reports/evidence/)**:
  - `reports/evidence/p2c_pilot_reproduced/`: 30 轮 Gazebo 仿真运行原始数据包、事件记录与 SHA256 清单；
  - `reports/evidence/p2d_h1_feasibility/`: 4 轮动作条件化导航可行性探索完整数据；
  - `reports/evidence/d2_time_ledger/`: D2 轨迹时间三阶段账本与离散化敏感性分析数据；
  - `reports/acceptance/`: 独立环境从零复现验收原始日志与哈希索引。
- 🔄 **[一键离线全量复现脚本](scripts/reproduce_offline.sh)** (`scripts/reproduce_offline.sh`, `scripts/reproduce_offline.py`): 自动校验 271 项哈希、执行独立回放评分、统计分析与基准差异对比。
- 📊 **[主张-证据映射矩阵](reports/claim-evidence-matrix.md)** (`reports/claim-evidence-matrix.md`): 逐项主张严格对应代码实现、原始仿真证据、统计分析产物与适用边界。
- 📋 **[作者投稿决策备忘录](author_decision.md)** (`author_decision.md`): 汇总定位、投稿风险、期刊 vs 研讨会路径对比及作者待填项。
- 🔍 **[Markdown-LaTeX 对齐账本](paper/submission_source/RECONCILIATION.md)** (`paper/submission_source/RECONCILIATION.md`): 记录格式迁移映射与严格措辞对齐。

---

## Build & Reproduction Commands (构建与复现命令)

无需启动 ROS 2 或 Gazebo 仿真，在本地 CPU 环境下可直接运行编译与验证：

```bash
# 1. 编译投稿编辑主稿 (LaTeX 原生管线，编译 main.pdf 与 supplementary.pdf，检查引用并保存 build.log)
./paper/submission_source/build.sh

# 2. 编译冻结参考稿 (Pandoc / WeasyPrint 管线，生成 paper.pdf 与 supplementary.pdf)
./paper/scripts/build_paper_pdf.sh

# 3. 运行一键全量离线复现（自动校验 SHA256、回放 30 个 episode、计算统计、比对基准 CSV、复核 H1）
./scripts/reproduce_offline.sh --output-dir "reports/evidence/p2c_pilot_reproduced_$(date +%Y%m%d_%H%M%S)"

# 4. 运行完整自动化测试套件 (196 项通过单测与 8 项历史缺陷回归夹具)
pytest tests/
```

---

## System Architecture & Simulation Stack

- **OS / ROS Distribution**: Ubuntu 22.04 LTS + ROS 2 Humble Hawksbill
- **Simulator / Robot**: Gazebo 11 + TurtleBot3 Waffle (30 Gazebo simulation runs + 4 feasibility runs)
- **Nav2 Planners**: `DWBLocalPlanner` (Controller) + `NavFnPlanner` (Global Planner)
- **Immutable Observation Bundle**: `src/doorway_evaluator.py` 捕获未截断的原始激光点云、TF 坐标变换与 Costmap ROI 子网格
- **Independent Replay Auditor**: `scripts/replay_and_score_p2c.py` 严格校验事件时序因果并依据哈希清单检测文件变动
