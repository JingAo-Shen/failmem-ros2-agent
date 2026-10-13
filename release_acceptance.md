# FailMem 独立构建验收与终审归档报告 (Release Acceptance & Final Audit)

**验收执行时间**: 2026-10-13  
**基准冻结提交 (Source Freeze SHA)**: `de05246f251263fb60a98ca3995fb8d65f38905c` (短哈希: `de05246`)  
**验收分支**: `research/agent-task-repair-pilot`  
**验收执行者**: Antigravity Autonomous Coding Agent  

---

## 一、验收环境与依赖分类

### 1.1 验收模式判定
本轮独立构建验收执行了严格的 **“干净源码独立检出 + 锁文件就地依赖安装”**（从零隔离环境复现）全流程：
- **隔离环境检出**: 使用独立 worktree 路径 `/tmp/failmem_independent_acceptance`，不共享主工作区的未提交文件或临时目录。
- **环境隔离性检验**:
  - 在未安装依赖状态下，构建脚本拒绝执行，未借用 `/code/failmem-ros2-agent/node_modules`。
  - 触发确定性预检拦截并提示标准修复指令：
    ```text
    RuntimeError: Node.js dependency 'mathjax-full' not found.
    Repository local node_modules: /tmp/failmem_independent_acceptance/node_modules (exists: False)
    Active NODE_PATH: /tmp/failmem_independent_acceptance/node_modules
    Please install dependencies in the repository using the project lockfile:
      npm ci
    or provide an explicit external NODE_PATH pointing to installed mathjax-full.
    ```
- **依赖安装来源**: 完全基于仓库声明的 `package-lock.json` 就地执行 `npm ci`（安装 8 个固定版本包，耗时 978ms，包含 `mathjax-full@3.2.2`）。

### 1.2 运行时系统与核心工具链版本
| 工具 / 运行时 | 记录版本 | 路径 / 来源 |
| :--- | :--- | :--- |
| **操作系统** | Linux 6.8.0-83-generic x86_64 (glibc 2.35) | Ubuntu 22.04 LTS 容器环境 |
| **Python** | `3.13.5` | `/root/anaconda3/bin/python3` |
| **Node.js** | `v24.21.0` | `/usr/bin/node` |
| **npm** | `11.19.0` | `/usr/bin/npm` |
| **pandoc** | `2.12` | `/usr/bin/pandoc` |
| **weasyprint** | `70.0` | Python 3.13 site-packages |
| **pdftoppm** | `22.02.0` | `/usr/bin/pdftoppm` (poppler-utils) |
| **pytest** | `8.3.4` | Python 3.13 site-packages |
| **mathjax-full**| `3.2.2` | 本地 `node_modules/mathjax-full` (由 lockfile 确定性锁定) |

---

## 二、独立复现流水线与自动化测试执行记录

所有命令均在干净检出的隔离目录 `/tmp/failmem_independent_acceptance` 中独立执行，记录如下：

### 2.1 预检与依赖安装
1. **未装依赖构建拦截**:
   - 命令: `./paper/scripts/build_paper_pdf.sh`
   - 退出码: `1`
   - 输出: 抛出 `RuntimeError`，明确提示运行 `npm ci`，无静默降级或隐式借用外部模块。
2. **锁文件依赖安装**:
   - 命令: `npm ci`
   - 退出码: `0`
   - 耗时: 978ms，8 个依赖包就地写入 `./node_modules`。

### 2.2 离线重放与确定性审计流水线
- **执行命令**: `./scripts/reproduce_offline.sh`
- **退出码**: `0`
- **耗时**: 2.51 秒
- **执行结果**:
  - **SHA256 清单核验**: 271/271 物理仿真原始文件哈希校验一致（通过率 100%）。
  - **离线回放评分**: 30 轮仿真全部回放完毕，30/30 审计通过（物理停定稳定性与数据完整性 100%）。
  - **基准比对**: `episodes.csv`、`condition_summary.csv`、`contrasts.csv` 与基线比对差异均为 0（Diffs: []）。
  - **H1 可行性核验**: 4 轮试验 Nav2 成功率 4/4，严格停定到达通过 3/4；按预设规程判定 `GO=False (NO-GO (Scenario Not Established))`。

### 2.3 图表与时间账本分析
- **表格与轨迹图生成**:
  - 命令: `python3 paper/scripts/generate_paper_tables.py && python3 paper/scripts/plot_trajectories_map.py`
  - 退出码: `0`
  - 产物: 成功生成 `table1_condition_summary`、`table2_pairwise_contrasts`、`table3_h1_feasibility`（Markdown与LaTeX双版本），并渲染出 `trajectories_map.png` 与 `trajectories_map.pdf`。
- **D2 轨迹时间账本与敏感性网格**:
  - 命令: `python3 scripts/analyze_d2_trajectory_time_ledger.py`
  - 退出码: `0`
  - 产物: 分析 12 个 D2 episode，完成 27 组敏感性参数扫描；零残差确认由代数构造产生；门区沉降时间窗（Settling Window）作为独立事件级指标统计，不混入速度分类时间。

### 2.4 测试套件回归
- **执行命令**: `pytest tests/ -v`
- **退出码**: `0`
- **耗时**: 2.63 秒
- **测试结果**: **196 passed, 8 xfailed, 0 failed**。全部正反负例测试均严格通过。

### 2.5 论文与补充材料 PDF 构建
- **执行命令**: `./paper/scripts/build_paper_pdf.sh`
- **退出码**: `0`
- **产物指标**:
  - `paper.pdf`: 10 页，700,468 字节，`math_clean: True`，未渲染原始 TeX 泄露数为 0。
  - `supplementary.pdf`: 4 页，191,452 字节，包含 S1–S5 完整支撑章节。
  - `build_report.json`: 完整记录工具链版本、源码哈希、产物哈希与检查结果。

---

## 三、逐页视觉走查记录表 (Page-by-Page Visual Inspection)

对编译生成的 `paper.pdf`（主文 10 页）与 `supplementary.pdf`（补充材料 4 页）逐页渲染为图像，使用视觉走查工具进行了人工与代理双重核验，核验记录如下：

| 页面 | 文件/章节 | 核心内容与结构 | 图表 / 公式渲染 | 版面、分页与排版 | 走查结果 |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **主文 P1** | Title / Abstract / §1 | 论文标题、单段式连贯摘要、引言前半部 | 矢量 MathJax 行内公式渲染正常 | 标题居中无溢出，页边距规整，首段无悬挂 | **通过 (PASSED)** |
| **主文 P2** | §1 (Cont.) / §2.1–2.3 | 三大贡献总结、相关工作（几何代价图、LLM反思） | 引用链接正常，无乱码 | 层次分明，标题级别层级清晰，无过长空白 | **通过 (PASSED)** |
| **主文 P3** | §2.4 / §3 Architecture | 表格 1（范式分类表）、图 1（系统架构与回放流程图） | 表格线条对齐规整；图 1 矢量 SVG 流程图文字清晰可读 | 图表居中，间距适度，公式 (1) 居中正常 | **通过 (PASSED)** |
| **主文 P4** | §3.2–3.3 / §4 Protocol | 门区判断规则 State(B)、失效注册与动态失活、环境几何 | 分段大括号公式 State(B) 矢量渲染正常 | 列表缩进规整，跨阶段定义清晰，底部转折自然 | **通过 (PASSED)** |
| **主文 P5** | §4.3 / §5 Results | 评估场景 D0-D2 流程说明、表格 2（条件级性能汇总 D0） | 表格 2 上半部清晰，标准差 $\pm$ 符号正常 | 场景步骤 1-5 编号对齐，表头居中加粗 | **通过 (PASSED)** |
| **主文 P6** | §5.1 (Cont.) / §5.2 | 表格 2 下半部 (D1/D2)、表格 3（成对对比分析） | 表格 2/3 数据对齐，加粗百分比突出有效对比 | 页面紧凑，无截断，表间过渡流畅 | **通过 (PASSED)** |
| **主文 P7** | §5.2 Trajectories / D2 | 图 2（四子图轨迹图）、死胡同消除与绕行开销分析 | 图 2 四象限坐标轴与文字清晰无重叠 | $+2.27\text{s}$ 时间分解与门区测量详细列出 | **通过 (PASSED)** |
| **主文 P8** | §5.2 (Cont.) / §5.3 $H_1$ | 空间缓存对比、表格 4（$H_1$ 可行性核验表）、中止结论 | 表格 4 完整呈现 4 轮参数与状态码 | 表格宽度适配，中止决策结论斜体强调，无溢出 | **通过 (PASSED)** |
| **主文 P9** | §6 Threats / §7 Concl. / Refs | 威胁与局限（小样本、单会话）、结论、参考文献 1–8 | 参考文献 DOI 链接与排版规整 | 局限性 1–4 编号排列清晰，底部承接参考文献 | **通过 (PASSED)** |
| **主文 P10**| References (Cont.) | 参考文献 9–13 | 尾部参考文献格式与缩进与 P9 完全一致 | 尾页自然收尾，无孤行悬挂 | **通过 (PASSED)** |
| **附录 P1** | Supp §S1 / §S2 | 补充材料标题、前置条件规则、门区几何包围盒、清单审计 | S1.1-S1.2 公式渲染正常，坐标范围明确 | 标题与分割线对齐，双栏感平衡良好 | **通过 (PASSED)** |
| **附录 P2** | Supp §S2–S5 | 停定稳定性公式、离线构建流水线说明、参数映射、D2账本说明 | 速度极值不等式公式居中渲染正常 | 包含代数残差为 0 的显式声明，无歧义 | **通过 (PASSED)** |
| **附录 P3** | Supp §S5.1 Ledgers | 决策阶段、历史阶段、全周期三张时间分解汇总表 | 表格数据完全对齐，沉降时间窗独立标注 | 附注明确沉降时间窗为独立指标，排版整洁 | **通过 (PASSED)** |
| **附录 P4** | Supp §S5.2 Sensitivity | 离散化阈值敏感性网格表（9 组典型参数扫描） | 表格行列整齐，负号与正号对齐 | 敏感性总结段落明确解释参数依赖性，无空白悬挂 | **通过 (PASSED)** |

---

## 四、手稿主张收敛与一致性审计结果

在全库各核心文档中，已彻底清查并收敛未经充分证实的表述：

1. **Abstract 结构统一**:  
   去除了加粗子标题形式，整合为标准的单一学术段落；逻辑贯通“问题背景 $\to$ 方法提出 $\to$ 实验设置与单会话跨阶段范围 $\to$ 实测收益与中性边界 $\to$ 局限与 $H_1$ 中止结论”。
2. **$H_1$ 结论全篇统一标准化**:  
   所有提及 $H_1$ 结论的位置（包括手稿 Abstract、引言贡献 3、正文 Section 5.3、README、审计报告与投稿摘要），统一规范为：  
   *“Nav2返回成功4/4，严格物理到达验证3/4；该候选场景未建立预期可执行性差异。按照既定规程中止该假设探索。”*
3. **消除大模型“无先验偏置”不当描述**:  
   修正为“在受限输入来源与特定提示词下”，如实指明大模型提取候选规则受限于输入语境，已发现硬编码未泛化与语义倒置反例。
4. **系统维护与开销主张收敛**:  
   将“无低开销优势”等主张统一收敛为学术中性描述：“本研究未量化比较系统维护或计算开销”。
5. **推广性结论范围限定**:  
   将原“具备高置信度推广性的结论”调整为“当前实验支持的观察与可复用实现”，明确局限于当前实现。
6. **记忆跨度界定**:  
   全篇统一澄清，当前评测的记忆是在**单次持续运行会话中的跨阶段（single continuous runner session across sequential phases）**保留与失活，未宣称跨操作系统重启或多天运行的跨任务数据库能力。

---

## 五、遗留已知局限 (Acknowledged Limitations)

本手稿与代码库已完全冻结，并明确承认以下客观局限：
1. **单一环境布局**: 实验评估限定于长廊不对称双路径几何环境（北侧门区 $0.80\,\text{m}$，南侧开阔通道）；尚未覆盖多岔路迷宫或复杂多房间拓扑。
2. **探索性小样本**: 主线对比实验为 $n=3$（共 30 轮仿真），属于机理验证性的小样本基准（Exploratory Pilot Benchmark），不构成大样本渐近统计检验。
3. **仿真环境限制**: 评测在 Gazebo 11 物理仿真与标称传感器模型下完成，未在带有传感器丢包、动态人流或光照变化的实体机器人硬件上进行长周期测试。
4. **静态几何下无增量路由收益**: 在静态 2D 刚体障碍场景下，FailMem ($F$) 与 Spatial Cache ($O$) 选择完全相同的拓扑路径，距离与耗时差异 $<1\%$；显式失败事件在此类场景未展现超越空间代价图缓存的增量路由收益。
5. **概念性扩展未实测**: 动作条件化画像记忆 ($F2$) 与退避代价图缓存 ($O+$) 仅作为理论扩展形式定义于文档中，未进入仿真评测矩阵。

---

## 六、归档与冻结元数据

- **源码冻结提交 (Source Freeze SHA)**: `de05246f251263fb60a98ca3995fb8d65f38905c`
- **复现验收判定**: **通过 (ACCEPTED)**
- **远端同步状态**: 准备同步推送至 `origin/research/agent-task-repair-pilot`
