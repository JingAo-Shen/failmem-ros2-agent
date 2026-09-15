# FailMem agent 工作包

## P0：确认仿真可行性
输入：研究计划、矩阵及公共文件。
步骤：核查 Reflexion/REFLECT 和至少 6 篇相关工作；检查现有 Linux/WSL/容器、ROS2/Gazebo/Nav2 与 GPU 条件，查官方兼容表并记录链接；定义机器人、工具 schema、公开观察、隔离真值及三类故障规格；写地图划分与成本计划。
产出：reports/literature.csv、novelty-audit.md、feasibility.md、problem-lock.md、P0-review.md；data/scenario-specs.jsonl。
验收：不会把仿真注入标签交给 planner；真实环境缺失就标 BLOCKED，不用 mock 声称已解决。常规配置可提出，但不擅自改宿主系统或启动真机。

## P1：事件重放和真实冒烟
前提：P0 已复核且仿真环境可用。
步骤：实现工具适配、独立真值评分、故障注入器；12 fixtures；一次 navigate→observe 真实仿真；固定动作/时间限制；记录世界快照和 episode seed。
产出：src/ros_adapter.py、src/faults.py、src/memory.py、src/evaluate.py、src/cli.py；configs/smoke.json、runs/smoke-*、P1-review.md。
验收：虚假成功被真值评分否决；故障标签不可读；同快照能恢复；导航超时会退出且留下事件；mock/真实运行清楚分列。

## P2：同 verifier 的失败记忆比较
前提：P1 已复核。
步骤：收集训练恢复经验；实现条件检索与失效；按 45 故障+45 无故障 dev 场景执行 B1/B2/B3/B4/F/A2；手工对账 5 次失败；检查旧地图/目标位置变化后是否错误复用。
产出：data/manifests/scenarios.json、configs/pilot.json、runs/pilot-*、reports/P2-review.md。
验收：各组同观察与恢复预算；没有通过更多重试获得假优势；含无故障损伤与碰撞统计；不把 unverified 原因写为真值。

## P3：冻结与正式实验
前提：研究负责人复核 P2，确认继续该方向和预算。输入为冻结数据清单、开发选择和实验矩阵。
步骤：
1. 生成 reports/protocol-lock.json：主指标/比较/阈值/数据 hash/模型版本/种子/样本规模/预算/失败处理；附功效或精度评估。测试开启时间记录为独立事件。
2. 按矩阵执行主实验和消融，默认 seeds 17/29/43；基线运行失败先修复并保留原记录，不得把缺失行悄悄删掉。
3. 从逐样本结果做配对聚类区间；报告每种子、全部失败和成本。只在冻结范围内运行，不因 test 不理想改方法。
产出：configs/final.json、reports/protocol-lock.json、runs/final-*、reports/P3-review.md、原始 predictions 与指标。
验收：可从原始预测重算表；正式与 pilot 分开；若 test 暴露实现错误，保存无效结果、记录修复并将后续运行标 corrected，不能装作首次测试。

## P4：论文证据包
前提：P3 已复核。
步骤：实现 scripts/build_tables.py 从 runs 生成 CSV/图；写 papers/claims-evidence.csv（claim、run_id、metric、figure、scope、limitation）；撰写方法、设置、结果、失败与限制，再写摘要。
产出：papers/draft.md、tables、figures、claims-evidence.csv、reproduce.md、reports/P4-review.md。
验收：每个数字有原始记录；负结果和未满足约束在摘要/结论中如实体现；论文标题匹配实际完成设置。无数据或未运行部分不能生成示意数字混作实验结果。

## 统一执行入口（P1 需实现）
以下是接口规格，当前不可假称已存在。命令均在本方向目录运行：
- python -m src.cli validate --config configs/smoke.json
- python -m src.cli run --config configs/smoke.json
- python -m src.cli summarize --run-dir runs/<真实run_id>

实现 --help、非零错误退出码、日志输出目录；不支持的配置要报错，不能静默回退。禁止让 validate 命令触发训练/付费调用。真实框架入口可由 CLI 包装，保持重放信息完整。

