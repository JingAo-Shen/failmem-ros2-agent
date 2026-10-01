# FailMem: Failure-Aware Memory for ROS 2 Autonomous Agents

> Research on episodic failure memory, verifiable execution contracts, and dynamic invalidation in ROS 2 / Nav2 autonomous navigation systems.

---

## Key Scientific Finding & Research Status (Milestone P2c / P2d)

> [!IMPORTANT]
> **核心研究发现与边界结论**：
> 1. **历史信息能够有效避免死胡同探索**：在双路径阻塞（D1）场景下，保留历史信息（失败记忆 $F$ 与空间缓存 $O$）相比反应式基线（$R$）消除死胡同重复进入（$0.0$ vs. $1.0$ 次）。FailMem ($F$) 相比反应式基线（$R$）节省 **$18.5\%$** 行驶距离与 **$22.3\%$** 运行时间（空间缓存 $O$ 相比 $R$ 节省 **$19.0\%$** 距离与 **$22.9\%$** 时间）。反应式基线（$R$）代表无跨任务记忆的死胡同盲目重试，非物理碰撞或控制器崩溃。
> 2. **动态失效机制避免永久绕路代价**：在障碍清除（D2）场景下，感知驱动的动态失效机制使机器人重新启用近路，相比永久禁用记忆（$M1$）节省 **$11.0\%$** 行驶距离（$16.25\,\text{m}$ vs. $18.25\,\text{m}$）。
> 3. **本探索性数据未显示 F 相对 O 的优势 (负结果 / 边界发现)**：在静态 2D 几何障碍环境中，显式失败记忆（$F$）与空间观测缓存（$O$）呈现功能路由等同性，两者总距离与总耗时差异 $<1\%$（D1 距离差异 $+0.6\%$，耗时 $+0.7\%$；D2 距离差异 $-0.9\%$，耗时 $+0.9\%$）。现有探索性实验数据未显示失败语义在静态几何场景中优于空间缓存。
> 4. **H1 动作条件失败场景可行性检查（No-Go 终止）**：在门区几何通畅（`doorway_state == FREE`）下，探索性测试的不同目标动作均成功通过 Nav2 导航（Nav2 成功率 4/4，严格物理到达 3/4），未建立预期动作可执行性差异。按预设规程立即终止 20 次对比实验。结论统一为：*本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。*

---

## Deliverables & Traceability Materials (研究交付材料)

- 📝 **[论文初稿 (Paper Draft)](paper/draft.md)** (`paper/draft.md`, `paper/references.bib`): 包含完整摘要、相关工作、系统架构、30次物理实验、4次可行性检查、边界分析与 BibTeX 引用。
- 📚 **[相关工作机制定位报告](reports/related-work-positioning.md)** (`reports/related-work-positioning.md`): 包含已核验的权威文献（DOI/URL）、机制分类与直接机制对照表。
- 🔄 **[离线全量复现核验报告](reports/offline-reproduction-check.md)** (`reports/offline-reproduction-check.md`): 记录依赖版本、执行命令、退出码、SHA256 校验与 8 个 xfailed 历史缺陷回归夹具解释。
- 📄 **[科研总结与综合定位总报告](reports/research-summary.md)** (`reports/research-summary.md`): 科学问题、真实实现、30次对比实验、4次可行性检查、负结果、局限性与研究定位。
- 📊 **[主张-证据映射矩阵](reports/claim-evidence-matrix.md)** (`reports/claim-evidence-matrix.md`): 逐项主张严格对应代码实现、原始仿真证据、统计分析产物与适用边界。
- 🛠️ **[离线审计与复现指南](docs/reproduce-p2c.md)** (`docs/reproduce-p2c.md`): 无需启动 ROS2 即可离线一键运行审计回放、统计分析与单测套件。
- 📈 **[P2c 30次探索性对比实验报告](reports/P2c-feasibility-pilot.md)** (`reports/P2c-feasibility-pilot.md`): 包含详细的 D0/D1/D2 场景分析与样本标准差统计。
- 📐 **[P2c 研究决策与边界分析报告](reports/P2c-research-decision.md)** (`reports/P2c-research-decision.md`): 机制分析、F2/O+ 概念设计与停止准则。
- 🔍 **[H1 场景可行性检查报告](reports/P2d-h1-feasibility-check.md)** (`reports/P2d-h1-feasibility-check.md`): 4次真实物理仿真实测、计时分解与 No-Go 判定结论。

---

## Quick Offline Reproduction (快速离线复现)

无需启动 ROS 2 或 Gazebo 守护进程，可在纯 Python 环境下复现全量审计与统计：

```bash
# 1. 运行完整自动化测试套件 (包含 176 项通过单测与 8 项历史缺陷回归夹具)
pytest

# 2. 运行统一统计分析脚本，验证 30 次运行证据完整性并生成 CSV/图表
python3 scripts/analyze_p2c_results.py reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35

# 3. 运行 H1 可行性离线解析器与判定器
python3 -c "from pathlib import Path; from scripts.verify_h1_feasibility import parse_and_derive_h1_evidence; res = parse_and_derive_h1_evidence(Path('reports/evidence/p2d_h1_feasibility'), Path('reports/evidence/p2d_h1_feasibility/derived')); print('H1 Verdict:', res['evaluation_summary']['verdict'])"
```

---

## System Architecture & Simulation Stack

- **OS / ROS Distribution**: Ubuntu 22.04 LTS + ROS 2 Humble Hawksbill
- **Simulator / Robot**: Gazebo 11 + TurtleBot3 Waffle
- **Nav2 Planners**: `DWBLocalPlanner` (Controller) + `NavFnPlanner` (Global Planner)
- **Immutable Observation Bundle**: `src/doorway_evaluator.py` 捕获未截断的原始激光点云、TF 坐标变换与 Costmap ROI 子网格
- **Independent Cryptographic Replay Auditor**: `scripts/replay_and_score_p2c.py` 严格校验事件时序因果与不可篡改记录
