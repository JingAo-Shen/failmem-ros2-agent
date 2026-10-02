# FailMem: Failure-Aware Memory for ROS 2 Autonomous Agents

> Research on episodic failure memory, verifiable execution contracts, and dynamic invalidation in ROS 2 / Nav2 autonomous navigation systems.

---

## Key Scientific Finding & Research Status (Milestone P2c / P2d)

> [!IMPORTANT]
> **核心研究发现与边界结论**：
> 1. **历史信息能够有效避免死胡同探索**：在双路径阻塞（D1）场景下，保留历史信息（失败记忆 $F$ 与空间缓存 $O$）相比反应式基线（$R$）消除死胡同重复进入（$0.0$ vs. $1.0$ 次）。FailMem ($F$) 相比反应式基线（$R$）节省 **$18.5\%$** 行驶距离与 **$22.3\%$** 运行时间（空间缓存 $O$ 相比 $R$ 节省 **$19.0\%$** 距离与 **$22.9\%$** 时间）。反应式基线（$R$）代表无跨任务记忆的死胡同盲目重试，非物理碰撞或控制器崩溃。
> 2. **动态失效机制避免永久绕路代价**：在障碍清除（D2）场景下，感知驱动的动态失效机制使机器人重新启用近路，相比永久禁用记忆（$M1$）节省 **$11.0\%$** 行驶距离（$16.25\,\text{m}$ vs. $18.25\,\text{m}$）。
> 3. **本探索性数据中路线选择相同，未显示 F 的额外收益；尚未进行统计等效或一般化验证**：在静态 2D 几何障碍环境中，显式失败记忆（$F$）与空间观测缓存（$O$）选择了相同的高层路径，两者总距离与总耗时差异 $<1\%$（D1 距离差异 $+0.6\%$，耗时 $+0.7\%$；D2 距离差异 $-0.9\%$，耗时 $+0.9\%$）。现有探索性实验数据未显示失败语义在静态几何场景中优于空间缓存。
> 4. **H1 动作条件失败场景可行性检查（No-Go 终止）**：在门区几何通畅（`doorway_state == FREE`）下，探索性测试的不同目标动作均成功通过 Nav2 导航（Nav2 成功率 4/4，严格物理到达 3/4），未建立预期动作可执行性差异。按预设规程立即终止 20 次对比实验。结论统一为：*本次候选场景未建立预期的动作可执行性差异，因此停止本轮 H1 探索；不构成对一般动作条件失败记忆假设的证伪。*

---

## Deliverables & Traceability Materials (研究交付材料)

- 📝 **[论文稿件 (Paper Draft & PDF)](paper/draft.md)** (`paper/draft.md`, `paper/paper.pdf`, `paper/references.bib`): 包含完整摘要、相关工作、系统架构、30次物理实验、4次可行性检查、边界分析、矢量架构图与 BibTeX 引用。
- 🗺️ **[方法-代码映射表 (Method-Code Mapping)](paper/method-code-map.csv)** (`paper/method-code-map.csv`): 33 条参数与公式精确映射到源码行号。
- 📚 **[相关工作文献核验表](paper/reference-verification.csv)** (`paper/reference-verification.csv`): 全部 15 项核心文献均由出版社主源核验。
- 🔄 **[一键离线全量复现脚本](scripts/reproduce_offline.sh)** (`scripts/reproduce_offline.sh`, `scripts/reproduce_offline.py`): 自动校验 271 项哈希、执行独立回放评分、统计分析与基准差异对比。
- 📊 **[主张-证据映射矩阵](reports/claim-evidence-matrix.md)** (`reports/claim-evidence-matrix.md`): 逐项主张严格对应代码实现、原始仿真证据、统计分析产物与适用边界。
- 🛠️ **[离线审计与复现指南](docs/reproduce-p2c.md)** (`docs/reproduce-p2c.md`): 离线一键运行审计回放、统计分析、图表生成与单测套件。

---

## Quick Offline Reproduction (快速离线复现)

无需启动 ROS 2 或 Gazebo 守护进程，在具有 Python 3.10+、Node.js 18+ (`npm install`)、Pandoc 与 WeasyPrint 的环境下可一键复现全量审计、统计分析与论文编译：

```bash
# 1. 运行一键全量离线复现（自动校验 SHA256、回放 30 个 episode、计算统计、比对基准 CSV、复核 H1）
./scripts/reproduce_offline.sh --output-dir "reports/evidence/p2c_pilot_reproduced_$(date +%Y%m%d_%H%M%S)"

# 2. 重新生成论文表格、轨迹地图与编译 PDF 论文 (包含 MathJax 矢量公式预渲染与表格行数校验)
./paper/scripts/build_paper_pdf.sh

# 3. 运行完整自动化测试套件 (包含 190 项通过单测与 8 项历史缺陷回归夹具)
pytest tests/
```

---

## System Architecture & Simulation Stack

- **OS / ROS Distribution**: Ubuntu 22.04 LTS + ROS 2 Humble Hawksbill
- **Simulator / Robot**: Gazebo 11 + TurtleBot3 Waffle
- **Nav2 Planners**: `DWBLocalPlanner` (Controller) + `NavFnPlanner` (Global Planner)
- **Immutable Observation Bundle**: `src/doorway_evaluator.py` 捕获未截断的原始激光点云、TF 坐标变换与 Costmap ROI 子网格
- **Independent Cryptographic Replay Auditor**: `scripts/replay_and_score_p2c.py` 严格校验事件时序因果与不可篡改记录
