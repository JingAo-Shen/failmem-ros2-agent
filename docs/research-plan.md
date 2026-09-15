# FailMem：可验证失败经验的跨任务复用

## 1. 研究问题与边界

同样传感器观察、验证器和恢复预算下，带适用条件/失效规则的失败记忆能否减少新任务中重复失败？暂定题目：Verified Failure Memory for Cross-Episode Robot Recovery。

第一篇限定 ROS2 移动机器人仿真，到达位置并观察目标；不做抓取、技能合成和真机。P0 核验 ROS2/Gazebo/Nav2 兼容版本；Windows 工作区不代表已有仿真环境。Reflexion 与 REFLECT 已研究反思和修正，贡献不能只是 ROS2 接口。

H1：同验证器下提高注入故障后的成功率。H2：比文本反思/失败检索减少重复无效操作。H3：地图/目标变化后的失效机制降低错误复用。

## 2. 最小环境

工具：navigate(goal)、observe(target)、inspect_status()、clear_costmap()、retry(action)。重定位等动作仅在真实实现后纳入；模型输出类型化动作。

故障先选路径暂时阻塞、目标移动、导航 action 超时。每种配无故障控制。固定阶段注入，方法间相同配置；真值标签只给评估器，agent 仅看工具/传感器。

公开后置条件验证与最终评分分开。最终评分使用隔离仿真真值，如到达距离<0.3m 且稳定 2s 并确认观察（P1 按机器人尺寸定稿）；模型说成功不算成功。所有方法传感器相同。

- P1：12 个重放 fixture + 一个真实仿真冒烟。mock 不能支撑机器人结果。
- P2：3 个开发布局×3 故障×5 起终点=45 故障 episode，另配 45 无故障。
- P3 起始：4 个训练/2 个开发/至少 6 个未见测试布局；每测试布局 3 故障×10 起终点=180 故障 episode，配 180 无故障，3 seeds。近重复几何不跨 split；仅六个布局的泛化 CI 需谨慎。

## 3. 状态机与记忆

plan→execute→observe→verify→success 或 diagnose→retrieve→recover→store。

schema：symptom, context_signature, attempted_action, evidence_ids, cause_hypothesis, recovery_action, verified_outcome, preconditions, expiry_rule, map_version。

- 原因只是 hypothesis；只有实际观测与恢复后置条件可标 verified，注入标签不得写入。
- context 用导航错误、局部障碍摘要、地图版本、目标观察时间；禁止用测试 layout ID 记答案。
- 最多检索 3 条，先检查地图/目标前置条件，再症状排序；同状态同无效动作最多重试一次，各基线一致。
- 保存真实执行和验证的恢复，包括失败恢复；地图更新/目标新观察使旧记录失效。
- 测试库源自训练，episode 自身可见事件可追加，但结束清空；在线积累另立协议。
- 初始统一预算：180s 仿真时间、20 高层动作、最多 3 次恢复；另有 wall-clock watchdog。P1 实测后可全方法统一调整一次再冻结。

## 4. 控制与指标

必须 memory {off,on} × verifier {off,on}。off 仅关闭额外后置条件反馈，各组仍有工具返回、共同安全限制和独立最终评分器。主比较是 verifier-on 的无记忆/反思/检索。

- 主指标：成功故障 episode / 全部注入 episode。
- recovery rate = 检测到且恢复成功 / 检测到故障；同时报检测率，防止只检测简单案例。
- repeat-failure = 状态未变重复已知无效动作次数 / 有再次决策机会的故障情境次数，规则冻结或盲审。
- false-success = 宣告成功但真值失败 / 宣告成功；另报该事件/全部 episode。
- 恢复延迟 p50/p95、动作数、碰撞次数、tokens 和重试成本；按布局聚类分析。

## 5. 继续/停止

P2 成功率 +5pp 或重复失败相对下降≥20%，且无碰撞/误报成功上升，是继续信号；检查是否仅因更多时间/动作。验证器解释全部收益则不能声称记忆有效。mock 有益、真实仿真无益时停止扩跑并报告差异。

论文证据需未见布局、旧记忆陷阱、同起点轨迹和失败盲审；仿真结果不支持真机安全结论。
