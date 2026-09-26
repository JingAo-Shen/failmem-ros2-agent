# P0-Review: FailMem 文献、环境与研究协议核查报告

- **项目**: `failmem-ros2-agent` (https://github.com/JingAo-Shen/failmem-ros2-agent)
- **阶段**: P0（文献、环境可行性与研究协议核查）
- **审查状态**: **PASSED (通过，建议进入 P1 准备阶段)**
- **执行分支**: `audit/r0-authenticity`
- **关联依据**:
  - 文献核查: [`reports/literature.csv`](literature.csv), [`reports/novelty-audit.md`](novelty-audit.md)
  - 环境探针: [`reports/feasibility.md`](feasibility.md), [`reports/evidence/p0/model_probe.json`](evidence/p0/model_probe.json)
  - 最小契约: [`docs/problem-lock.md`](../docs/problem-lock.md)

---

## 1. 本轮解决的问题与冻结的选择

1. **文献基线核验与创新边界锁定**:
   - 彻底排除了将“结构化失败记录”、“ROS2 接口接入”、“大模型失败后反思”单独声称为创新的不当做法；
   - 深入阅读并比对了 Reflexion (NeurIPS 2023)、REFLECT (CoRL 2023) 与 RoboMemory (2025) 的全文实验设置，锁定了 FailMem 的真实研究问题：“在相同规划模型、感知信息、验证器和恢复预算下，带适用条件与失效规则的失败记忆，能否减少机器人在新任务中的重复失败，并避免环境变化后的错误经验复用？”
   - 更新了包含 8 篇直接相关论文的 `literature.csv`，其中 3 篇为 2024—2025 年近邻工作（LifeMem, RoboOS-NeXT, RoboMemory）。
2. **本地环境与算力可行性现场核验**:
   - 实测确认本地 RTX 2080 Ti 拥有 22.0 GB 物理显存，CUDA 13.0 驱动；
   - 现场核查确认本地 ModelScope 缓存中已完整存在 **Qwen2.5-Coder-7B-Instruct** (15 GB safetensors)；
   - 执行了 3 场景的结构化模型推理探针：在 bfloat16 模式下显存占用 15.23 GB（低于 22 GB 上限），平均单步生成时延 1.782s，格式合法率 100%，具备纯本地部署 LLM Planner 的可行性，无需新增付费云端 API。
3. **真实物理仿真方案核定**:
   - 现场系统探测确认：当前 shell 未发现 ros2，宿主机未安装 ROS 依赖；
   - 鉴于宿主机为 Anaconda Python 3.13.5 环境，为避免与 ROS Python 发生致命底层符号冲突，正式核定采用 **基于 Ubuntu 22.04 + ROS2 Humble + Gazebo Fortress + Nav2 的隔离 Docker 容器** 技术路线，并编写了容器配置与验证脚本。
4. **冻结 P1 最小研究契约 (`docs/problem-lock.md`)**:
   - 严格限定为单个移动机器人室内导航与目标观察；
   - 明确定义 `navigate`, `observe`, `inspect_status`, `clear_costmap`, `retry` 动作接口与超时预算；
   - 建立公共 Verifier 与独立 Evaluator 的单向数据隔离防护，严禁全知泄漏目标坐标；
   - 确立物理障碍持续性机制，纠正“清图即可消除实体障碍”的物理谬误；
   - 规范三种独立时空版本号（静态地图版本、动态 Costmap 纪元、目标观察纪元）；
   - 统一环境资产划分为 3 训练 / 2 开发 / 3 冻结测试场景，P1 仅需 1 个真实物理闭环。

---

## 2. 输入检查（真实存在与缺失清单）

- [x] **本地硬件环境**: 真实存在。RTX 2080 Ti 22GB、i5-13490F、31GB RAM。
- [x] **本地大模型权重**: 真实存在。Qwen2.5-Coder-7B-Instruct 完整缓存于 `/root/.cache/modelscope/...`。
- [x] **容器基础环境**: 真实存在。Docker 29.1.3 已安装且正常运行。
- [ ] **宿主机原生 ROS2 环境**: 缺失（`/opt/ros` 不存在，shell 未发现 ros2）。已通过容器化方案解耦。
- [ ] **物理室内 Gazebo 地图世界**: 待构建（目前仅有 2D 坐标标签）。需在 P1 构建首个物理仿真闭环。

---

## 3. 修改与新增文件清单

| 文件路径 | 状态 | 作用说明 |
| :--- | :---: | :--- |
| `reports/literature.csv` | 修改 | 更新 8 篇直接相关论文（包含 3 篇 2024-2025 年近邻工作），记录全文比对与待检验差异。 |
| `reports/novelty-audit.md` | 修改 | 扩展 Reflexion、REFLECT、RoboMemory 3 篇文献的全文实验深度比对，锁定研究问题与 H1-H3 假设。 |
| `reports/feasibility.md` | 修改 | 补充 CUDA 驱动/Toolkit/PyTorch 运行时区分，记录本地 Qwen2.5 7B 模型探针与容器方案。 |
| `docs/problem-lock.md` | 新增 | 锁定 P1 至 P3 的最小研究契约（动作空间、隔离真值、障碍持续性、失效规则、地图划分）。 |
| `docker/Dockerfile.ros2_humble` | 新增 | 基于 ROS2 Humble + Gazebo Fortress + Nav2 的标准化仿真环境容器构建文件。 |
| `docker/docker-compose.yml` | 新增 | 具备 NVIDIA GPU 穿透与工作区挂载的容器编排配置。 |
| `scripts/verify_p0_env.sh` | 新增 | 宿主系统硬件、CUDA、ROS2 与容器的一键自动化探针脚本。 |
| `scripts/probe_model.py` | 新增 | 本地 Qwen2.5-Coder-7B-Instruct 结构化推理时延、显存与 JSON 合法率评测脚本。 |
| `reports/evidence/p0/model_probe.json` | 新增 | 大模型探测原始运行日志与评测证据。 |
| `reports/P0-review.md` | 新增 | 本评审总报告。 |

---

## 4. 运行记录（命令、目录、退出码与输出）

| 执行命令 | 工作目录 | 退出码 | 关键输出与证据 |
| :--- | :--- | :---: | :--- |
| `./scripts/verify_p0_env.sh` | `/code/failmem-ros2-agent` | `0` | 探测确认：Ubuntu 22.04.5 LTS，RTX 2080 Ti 22GB，Docker 29.1.3，Qwen2.5-7B 模型 15GB。 |
| `python3 scripts/probe_model.py` | `/code/failmem-ros2-agent` | `0` | 生成 `reports/evidence/p0/model_probe.json`：模型加载 16.64s，显存 15.23 GB，平均时延 1.782s，合法率 100%。 |
| `python3 -c "import torch; print(torch.cuda.is_available())"` | `/code/failmem-ros2-agent` | `0` | 确认 PyTorch 2.10.0+cu128 可正常调用 GPU 0。 |

---

## 5. 泄漏与公平性自检

1. **防泄漏机制已在契约中锁定**:
   - `docs/problem-lock.md` 第 3 节与第 4 节明确要求：Evaluator 真值通道与故障注入标签严禁反向流入 Agent，目标重定位后严禁直接返回最新真值坐标；
   - 必须通过 `observe` 视锥检测判定可见性；
2. **计算公平性契约已确立**:
   - `docs/problem-lock.md` 第 7 节规定：LLM 规划推理期间仿真时钟冻结，避免大模型生成延迟影响物理超时判定；所有方法使用相同规划模型、相同动作与恢复预算上限。

---

## 6. 与工作包验收条件逐条对照 (P0 验收)

| 工作包要求 | 验收标准 | 当前达成状态 | 证据路径 |
| :--- | :--- | :---: | :--- |
| **文献核验** | 核查 Reflexion/REFLECT 及至少 6 篇相关工作，3 篇 2025-2026 年近邻；明确科学问题差异 | **PASSED** | `reports/literature.csv`, `reports/novelty-audit.md` |
| **硬件与环境实测** | 探针实测硬件、CUDA 运行时、ROS2 安装情况与容器；不凭型号猜显存 | **PASSED** | `reports/feasibility.md`, `scripts/verify_p0_env.sh` |
| **本地大模型盘点** | 盘点本地模型权重，执行真实结构化输出探针，测量显存、时延与合法率 | **PASSED** | `scripts/probe_model.py`, `reports/evidence/p0/model_probe.json` |
| **定义契约与规则** | 定义工具 Schema、真值与公共验证器隔离、故障持续与解除、地图版本与失效规则 | **PASSED** | `docs/problem-lock.md` |
| **不伪造未运行项目** | 未运行项目标 NOT_RUN，真实缺失标 BLOCKED，不擅自改动宿主系统 | **PASSED** | 宿主无 ROS 明确标出，通过隔离 Docker 方案解耦 |

---

## 7. P1 阶段关键阻塞项与最小实现清单

### 7.1 前置阻塞项 (Blockers)
- **容器镜像构建与图形虚拟化**: 需构建 `docker/Dockerfile.ros2_humble` 并验证 Headless 模式下 Gazebo Fortress 物理仿真的稳定性。

### 7.2 P1 最小实现清单 (Target for Next Phase)
1. **构建与验证仿真容器**: 执行 `docker compose -f docker/docker-compose.yml build`，验证 ROS2 Humble + Nav2 + Gazebo 容器；
2. **实现单场景物理最小闭环**:
   - 采用标准场景（TurtleBot3 World），配置静态地图与 Gazebo 物理世界；
   - 实现真实 `NavigateToPose` Action 调用与基础导航冒烟；
3. **实现真值隔离评测器与物理故障注入器**:
   - 基于 Gazebo 状态服务实现到达距离（<0.3m）与 2s 稳定时间、视锥无遮挡观察真值打分；
   - 实现物理障碍注入与持续阻挡机制。
4. **输出 P1-review.md** 并提交复核。

---

## 8. 建议与总结

- **审查结论**: **P0 阶段各项文献核查、硬件探针、本地大模型实测与问题锁定契约均已严格完成，验收通过 (PASSED)**。
- **阶段流转建议**: 建议提交研究负责人复核，在确认批准后，正式开启 **P1：真实仿真及可信评测（单环境最小闭环）** 阶段。
