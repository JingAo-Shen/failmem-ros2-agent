# FailMem 独立验收证据索引与归档清单 (Acceptance Evidence Index)

**验收目标基准**: `de05246f251263fb60a98ca3995fb8d65f38905c` (短哈希: `de05246`)  
**对应工作区状态**: 独立 worktree 检出 (`/tmp/failmem_independent_acceptance`)，预检前 `git status` 为干净状态，无任何本地 `node_modules`。  
**验收模式界定**: **“独立源码检出＋本地Node锁文件依赖安装，使用现有Python与系统工具链”**（明确非从零新建操作系统与Python解释器）。  
**归档目录**: `reports/acceptance/`  
**归档生成时间**: 2026-10-14  

---

## 一、证据文件归档清单与来源区分

| 归档文件名 | 证据内容与属性 | 来源与状态 | 核心指标 / 退出码 |
| :--- | :--- | :--- | :---: |
| [`preflight_failure.log`](preflight_failure.log) | 未装 Node 依赖时的预检拦截日志 | **原始保留** (自 de05246 worktree 运行记录找回) | Exit Code: `1`；明确提示 `npm ci` |
| [`npm_ci_install.log`](npm_ci_install.log) | 本地锁文件依赖安装日志 | **原始保留** (自 de05246 worktree 运行记录找回) | Exit Code: `0`；8 个包就地安装耗时 978ms |
| [`tool_versions.log`](tool_versions.log) | 验收环境各工具链版本元数据 | **原始保留** (自 de05246 worktree 运行记录找回) | Python 3.13.5, Node 24.21.0, Pandoc 2.12, WeasyPrint 70.0 |
| [`build_report_standalone_de05246.json`](build_report_standalone_de05246.json) | 独立检出 worktree 下的 PDF 构建报告 | **原始保留** (自 de05246 worktree 运行记录找回) | 源码 SHA: `de05246`, `math_clean: true`, 表格结构通过 |
| [`pdf_build_standalone_task.log`](pdf_build_standalone_task.log) | 独立 worktree 下编译 PDF 的后台任务完整日志 | **原始保留** (自 task-20158.log 找回) | Exit Code: `0`；成功编译 10 页主文与 4 页附录 |
| [`d2_ledger_and_tables.log`](d2_ledger_and_tables.log) | 表格生成、轨迹图与 D2 时间账本分析日志 | **原始保留** (自 de05246 worktree 运行记录找回) | Exit Code: `0`；12 轮 D2 episode 代数闭合，27 组敏感度网格 |
| [`pytest_verbose.log`](pytest_verbose.log) | 全量单元测试详细日志（未截断完整版） | **补充重跑** (因原 worktree 控制台输出截断且临时树已删，按规程单项重跑) | Exit Code: `0`；**196 passed, 8 xfailed, 0 failed** |
| [`reproduction_run.log`](reproduction_run.log) | 离线复现流水线执行全量日志 | **补充重跑** (因原 worktree 产物目录已随临时树清除，按规程单项重跑保存) | Exit Code: `0`；271/271 SHA256 吻合，Replay 30/30 通过 |
| [`reproduction_audit/`](reproduction_audit/) | 离线复现产物目录 (含 report.json, CSVs) | **补充重跑** (同上，持久化存储复现衍生数据) | `reproduction_report.json`、`condition_summary.csv` 等完整落盘 |

---

## 二、构建报告来源与状态区分 (Build Report Distinction)

为保证审计真实性，严禁混淆主工作区与独立验收工作区的构建报告：

1. **主工作区构建报告 (`paper/build_report.json`)**:
   - **生成环境**: 主仓库开发目录 `/code/failmem-ros2-agent/`
   - **源码状态**: 记录在 `b19fccf` 之上包含未提交本地手稿编辑时的预检与构建记录（`source_dirty: true`）。
   - **用途**: 跟踪本地工作区手稿迭代与自动文本检查状态。
2. **独立验收构建报告 (`reports/acceptance/build_report_standalone_de05246.json`)**:
   - **生成环境**: 独立隔离目录 `/tmp/failmem_independent_acceptance/`
   - **检出源码**: 明确对应干净的提交 `de05246f251263fb60a98ca3995fb8d65f38905c`
   - **依赖状态**: 仅包含依据 `package-lock.json` 执行 `npm ci` 后的就地 `node_modules`。
   - **用途**: 证明在无主工作区隐式依赖借用情况下，独立工作树能够完整复现出版物 PDF 编译。

---

## 三、视觉走查状态与关联产物声明 (Visual Inspection Attribution)

1. **自动构建默认状态**:
   - 依据规程，构建脚本已修正为：在任何自动化构建（无论是本地还是独立 worktree）中，默认记录 `visual_inspection.status = "NOT_PERFORMED"`。
   - 自动构建流水线不得自动宣称已完成视觉走查。
2. **实际走查记录归属**:
   - 实际视觉走查是在页面生成后由代理（Antigravity AI Agent）对渲染得到的 14 张高分辨率页面逐页执行。
   - 历史完成的 14 页完整走查严格关联当时编译生成的 PDF 哈希（`0336b61f...` 与 `93f37e3e...`），走查记录明细见 [`release_acceptance.md`](../../release_acceptance.md)。
   - 本次由于手稿 Abstract 与 Contributions 收敛更新，重新生成了新版 PDF（SHA: `77707d90...` 与 `b86bdb0b...`）；针对发生文句修改的主文第 1 页与第 2 页，已重新执行高分辨率图像核验，确认格式与排版完整。
   - 明确删除“人工与代理双重核验”措辞，如实保留 `human_verified = false`，待人类作者投稿前最终核查。
