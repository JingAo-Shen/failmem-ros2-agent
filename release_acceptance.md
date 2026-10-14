# FailMem 独立构建验收与终审归档报告 (Release Acceptance & Final Audit)

**验收执行时间**: 2026-10-14  
**研究源码冻结基准 (Source Freeze SHA)**: `de05246f251263fb60a98ca3995fb8d65f38905c` (短哈希: `de05246`)  
**验收分支**: `research/agent-task-repair-pilot`  
**验收执行者**: Antigravity Autonomous Coding Agent  
**验收证据归档目录**: [`reports/acceptance/`](reports/acceptance/) (详见 [`reports/acceptance/INDEX.md`](reports/acceptance/INDEX.md))  

---

## 一、验收环境与依赖分类

### 1.1 验收模式判定
本轮独立构建验收执行的严格模式分类为：  
**“独立源码检出＋本地Node锁文件依赖安装，使用现有Python与系统工具链”**。  
- **明确边界**：本验收并非从零创建全新操作系统镜像或重新安装全部系统依赖；它复用了宿主环境现有的 Python 3.13 解释器、系统 Pandoc 与 WeasyPrint 等全局二进制工具。
- **独立性保障**：
  - 在独立目录 `/tmp/failmem_independent_acceptance`（基于 `de05246` 检出）中运行，杜绝了与主工作区未提交修改的交叉污染。
  - **杜绝依赖借用**：在未安装本地 `node_modules` 状态下，构建脚本拒绝执行，未借用 `/code/failmem-ros2-agent/node_modules`，严格触发报错并提示：
    ```text
    RuntimeError: Node.js dependency 'mathjax-full' not found.
    Repository local node_modules: /tmp/failmem_independent_acceptance/node_modules (exists: False)
    Active NODE_PATH: /tmp/failmem_independent_acceptance/node_modules
    Please install dependencies in the repository using the project lockfile:
      npm ci
    or provide an explicit external NODE_PATH pointing to installed mathjax-full.
    ```
  - **锁文件就地安装**：依据仓库声明的 `package-lock.json` 执行 `npm ci`（8 个版本锁定包，耗时 978ms，包含 `mathjax-full@3.2.2`）。

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
| **mathjax-full**| `3.2.2` | 本地 `node_modules/mathjax-full` (由 package-lock.json 锁定) |

---

## 二、验收证据归档与命令执行记录

所有证据原始日志与生成文件均已归档于 [`reports/acceptance/`](reports/acceptance/) 目录下：

### 2.1 原始保留证据 (自 de05246 独立 worktree 运行记录找回)
1. **未装依赖构建拦截** ([`preflight_failure.log`](reports/acceptance/preflight_failure.log)):
   - 命令: `./paper/scripts/build_paper_pdf.sh` (在无 node_modules 环境下)
   - 退出码: `1`
   - 输出: 抛出 `RuntimeError`，明确提示运行 `npm ci`，无静默降级或隐式借用。
2. **锁文件依赖安装** ([`npm_ci_install.log`](reports/acceptance/npm_ci_install.log)):
   - 命令: `npm ci`
   - 退出码: `0`
   - 耗时: 978ms，8 个依赖包就地写入 `./node_modules`。
3. **环境工具链版本** ([`tool_versions.log`](reports/acceptance/tool_versions.log)):
   - 记录独立检出执行时的各工具版本。
4. **独立 PDF 构建后台任务日志** ([`pdf_build_standalone_task.log`](reports/acceptance/pdf_build_standalone_task.log)):
   - 命令: `./paper/scripts/build_paper_pdf.sh` (在已执行 `npm ci` 的独立 worktree 下)
   - 退出码: `0`
   - 产物: 成功生成 10 页 `paper.pdf` 与 4 页 `supplementary.pdf`，表格结构验证 100% 通过。
5. **独立 PDF 构建报告** ([`build_report_standalone_de05246.json`](reports/acceptance/build_report_standalone_de05246.json)):
   - 记录源码 SHA `de05246`、产物哈希（`147e7eb...` / `3c6e504...`）、`math_clean: true` 与 0 处 TeX 泄露。
6. **图表与 D2 时间账本分析** ([`d2_ledger_and_tables.log`](reports/acceptance/d2_ledger_and_tables.log)):
   - 命令: `python3 paper/scripts/generate_paper_tables.py && python3 paper/scripts/plot_trajectories_map.py && python3 scripts/analyze_d2_trajectory_time_ledger.py`
   - 退出码: `0`
   - 结果: 12 个 D2 episode 闭合分析完成，27 组敏感度网格扫描完成，零残差确认由代数构造产生。

### 2.2 补充重跑证据 (按规程单项重跑以补齐完整落盘记录)
因原临时 worktree 在执行完后被移除，控制台输出部分截断或目录已清除，依据用户规程单项重跑保存完整落盘记录：
1. **测试套件回归完整日志** ([`pytest_verbose.log`](reports/acceptance/pytest_verbose.log)):
   - 命令: `pytest tests/ -v`
   - 退出码: `0`
   - 测试结果: **196 passed, 8 xfailed, 0 failed**（未截断完整 22KB 文本日志）。
2. **离线复现流水线执行日志与产物** ([`reproduction_run.log`](reports/acceptance/reproduction_run.log) 与 [`reproduction_audit/`](reports/acceptance/reproduction_audit/)):
   - 命令: `./scripts/reproduce_offline.sh --output-dir reports/acceptance/reproduction_audit`
   - 退出码: `0`
   - 结果: 271/271 SHA256 吻合，Replay 30/30 审计通过，CSV 比对 0 差异，完整持久化存储 `reproduction_report.json` 等文件。

### 2.3 构建报告来源区分说明
- **历史主工作区构建报告** ([`paper/build_report.json`](paper/build_report.json)):
  - 来源: 主工作区开发构建（包含对手稿的持续跟踪，`source_dirty: true`）。
- **独立验收构建报告** ([`reports/acceptance/build_report_standalone_de05246.json`](reports/acceptance/build_report_standalone_de05246.json)):
  - 来源: 独立 worktree 干净检出 `de05246` 后的独立构建。
- 两者分开保留，来源界定清晰。

---

## 三、视觉走查记录修正 (Visual Inspection Audit)

### 3.1 规则与状态修正
1. **构建脚本自动状态**:
   - 构建脚本已修正为：默认记录 `visual_inspection: performed = false, status = "NOT_PERFORMED"`。
   - 构建脚本不再自动宣称完成视觉走查。
2. **走查主体真实性**:
   - 明确删除“人工与代理双重核验”表述。
   - 真实状态为：**由 Antigravity AI Agent 逐页查看高分辨率图像，`human_verified = false`（待人类作者在投稿前进行最终审阅）**。

### 3.2 历史全量 14 页走查记录（关联查看时的 PDF 哈希）
**关联查看产物哈希**:  
- `paper.pdf`: `0336b61f771acd2bd66d223b961df937362269c8c855cffdf3691b8a2886d115`  
- `supplementary.pdf`: `93f37e3e405f9a6b5ebf599f7f7887b4fb46effed1fbb03974a6fa66f36e0303`  

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

### 3.3 最新手稿修订页再核验
本轮对 Abstract（移除细粒度时间数值）与 Contributions（严格限定三项）进行了最终润色，重新编译生成了最新 PDF：
- 最新 `paper.pdf` SHA256: `77707d90162e3c10b9749a81ea7da00320ff5b0cbb55af81186ae98f423872e8`
- 最新 `supplementary.pdf` SHA256: `b86bdb0b14ce528091cbe6d589c0760c71948eebec8fd3409490e7f743e09055`
针对改动的 **主文第 1 页** 与 **主文第 2 页**，已单独重新渲染并完成视觉查看：
- **P1**: 摘要单段呈现，行文连贯；引言衔接自然，底部与 P2 平滑过渡。
- **P2**: 三大贡献限定清晰，相关工作段落与表格引用规整，排版通过。

---

## 四、手稿终审编辑与主张严格收敛

1. **论文标题与定位保持一致**:  
   `Auditable Failure Memory for ROS 2 Navigation: An Exploratory Comparison with Spatial Caching`
2. **三大核心贡献严格限定**:  
   - 感知证据绑定的事件记录与动态失效实现；
   - 可复算的探索性导航比较；
   - 当前布局中未观察到 FailMem 优于 Spatial Cache 的边界结果。
3. **摘要精炼**:  
   摘要仅保留主线结果（D1 死胡同消除、D2 距离缩短、总耗时未见改善、拓扑路径一致中性边界、H1 中止），细粒度 D2 账本分量留存正文第 5 节与补充材料 S5。
4. **统计等效主张禁止**:  
   正文与全部报告明确禁止将小样本（$n=3$）下的均值接近表述为“统计等效”；强调仅在当前布局与样本下未观察到路由收益。
5. **清除防御性与非学术性措辞**:  
   全面清除“防守策略”、“最佳策略”等字眼，转为客观事实与证据边界描述。
6. **科学定位与工程区分**:  
   明确指出离线复现流水线、哈希清单与自动化构建属于可审计工程实践，不直接等同于学术创新充分，亦不宣称满足具体刊会的投稿标准，由作者团队决定后续研究安排。

---

## 五、遗留已知局限 (Acknowledged Limitations)

本研究代码与手稿已彻底冻结，明确承认以下客观局限：
1. **单一环境布局**: 实验评估限定于长廊不对称双路径几何环境（北侧门区 $0.80\,\text{m}$，南侧开阔通道）；尚未覆盖多岔路迷宫或复杂多房间拓扑。
2. **探索性小样本**: 主线对比实验为 $n=3$（共 30 轮仿真），属于机理验证性的小样本基准（Exploratory Pilot Benchmark），不构成大样本渐近统计检验。
3. **仿真环境限制**: 评测在 Gazebo 11 物理仿真与标称传感器模型下完成，未在带有传感器丢包、动态人流或光照变化的实体机器人硬件上进行长周期测试。
4. **静态几何下无增量路由收益**: 在静态 2D 刚体障碍场景下，FailMem ($F$) 与 Spatial Cache ($O$) 选择完全相同的拓扑路径，距离与耗时差异 $<1\%$；显式失败事件在此类场景未展现超越空间代价图缓存的增量路由收益。
5. **概念性扩展未实测**: 动作条件化画像记忆 ($F2$) 与退避代价图缓存 ($O+$) 仅作为理论扩展形式定义于文档中，未进入仿真评测矩阵。

---

## 六、关键提交元数据 (Commit Hashes)

- **研究源码冻结基准 (Source Freeze SHA)**: `de05246f251263fb60a98ca3995fb8d65f38905c` (`de05246`)
- **最终稿提交 (Final Manuscript SHA)**: `5e6ed1ff3e36e19195b0fe637ce02047ee2d7fc7` (`5e6ed1f`)
- **验收证据归档提交 (Acceptance Archive SHA)**: 包含本报告与 `reports/acceptance/` 归档目录的提交
- **上轮基准 (Prior Benchmark SHA)**: `202d7ac736d4b67c3b7b84ed39d8713d2f553f8b` (`202d7ac`)
- **复现验收状态**: **通过 (ACCEPTED)**

