# FailMem 独立验收证据索引与归档清单 (Acceptance Evidence Index)

**验收状态**: **通过 (ACCEPTED)**  
**归档生成时间**: 2026-10-14  
**归档维护路径**: `reports/acceptance/`  
**核心说明**: 本清单为验收文件提供完整 SHA-256 哈希索引，并明确区分独立 worktree 构建与主工作区补充复算，如实标注已知记录缺口。

---

## 一、验收执行阶段与来源严格区分 (Execution Phases Distinction)

为杜绝混淆并确保科学审计真实性，严禁将两个不同执行阶段合并宣称为“同一轮干净源码验收”：

1. **阶段 A：`de05246` 独立隔离 worktree 验收构建**
   - **基准提交**: `de05246f251263fb60a98ca3995fb8d65f38905c` (`de05246`)
   - **执行目录**: `/tmp/failmem_independent_acceptance` (独立 worktree，无全局依赖污染)
   - **验收模式**: **“独立源码检出＋本地 Node 锁文件依赖安装，使用现有 Python 与系统工具链”**（非从零新建操作系统与 Python 解释器）。
   - **依赖状态**: 杜绝借用主工作区 `node_modules`；基于 `package-lock.json` 执行 `npm ci`（8 个版本锁定包，耗时 978ms）。
   - **产物与覆盖**: 验证预检拦截、锁文件安装、D2 账本代数分析闭合、PDF 自动化编译。
   - **已知记录缺口与状态解释**:
     * **运行前原始 git status**: 未单独保留独立日志文件（标记为“未单独保留日志文件”，严禁事后补造）。
     * **构建报告 source_dirty 状态解释**: `build_report_standalone_de05246.json` 中记录的 `source_dirty: true`，其产生原因完全为流水线在触发主构建前先执行了前序生成脚本（`generate_paper_tables.py`、`plot_trajectories_map.py` 等），在树内生成了中间衍生文件（`trajectories_map.pdf`、`paper.html`、`.draft_processed.md` 等），绝非未提交的外部代码污染。

2. **阶段 B：`202d7ac` 主工作区补充测试与离线复算**
   - **基准提交**: `202d7ac736d4b67c3b7b84ed39d8713d2f553f8b` (`202d7ac`)
   - **执行目录**: `/code/failmem-ros2-agent` (主开发工作区)
   - **补充原因**: 阶段 A 临时 worktree 执行后被移除，控制台输出部分截断且产物目录已清理；依据规程在主工作区单项重跑保存完整的落盘记录，避免重跑整套流程引入不必要的环境变动。
   - **产物与覆盖**: 全量未截断单元测试日志 (`pytest_verbose.log`，22KB)、离线复现流水线运行日志与审计产物目录 (`reproduction_audit/`)。

---

## 二、全量验收文件 SHA-256 哈希索引表 (Acceptance Hash Index)

| 归档文件路径 | SHA-256 哈希值 | 来源提交 | 运行目录 | 执行命令 | 退出码 | 已知记录缺口与属性说明 |
| :--- | :--- | :---: | :--- | :--- | :---: | :--- |
| `preflight_failure.log` | `991e7db985ee61881ff6b3d0bac2d75023f76b21f5e6ab169d4f193cd6427330` | `de05246` | `/tmp/failmem_independent_acceptance` | `./paper/scripts/build_paper_pdf.sh` | `1` | **原始保留**。无依赖时阻断构建，明确提示 `npm ci`。 |
| `npm_ci_install.log` | `5eec8e71b2ae86fe538feab5e11f02c56728c00b3e2e7b0daa1d64a4ade1fa91` | `de05246` | `/tmp/failmem_independent_acceptance` | `npm ci` | `0` | **原始保留**。锁定安装 8 个包（含 `mathjax-full@3.2.2`），耗时 978ms。 |
| `tool_versions.log` | `ffa1f3e446a07612bd411e4fd7909607b9a37c8f7146fc472c63ea87ec3050fc` | `de05246` | `/tmp/failmem_independent_acceptance` | `./paper/scripts/build_paper_pdf.sh --check-deps` | `0` | **原始保留**。记录 Python 3.13.5, Node 24.21.0, Pandoc 2.12 等版本。 |
| `build_report_standalone_de05246.json` | `facb2f3b19ee2373b5179ac9d8f1b2927d03b752041ec7887c9e0e7e5be11006` | `de05246` | `/tmp/failmem_independent_acceptance` | `./paper/scripts/build_paper_pdf.sh` | `0` | **原始保留**。记录 `source_dirty: true`（生成物所致），运行前 git status 日志未单独保留。 |
| `pdf_build_standalone_task.log` | `afb2f1ac4077bf29c04c386c4f0488df4cb06b11886c546add9ebf28d28f5995` | `de05246` | `/tmp/failmem_independent_acceptance` | 后台编译任务执行 | `0` | **原始保留** (找回自 task 日志)。生成 10 页正文与 4 页附录。 |
| `d2_ledger_and_tables.log` | `ffa86d251fd9fc3e987a5a5678f4c19a5f6d318972d985618617ecf7151d5e8a` | `de05246` | `/tmp/failmem_independent_acceptance` | `python3 paper/scripts/generate_paper_tables.py && ...` | `0` | **原始保留**。12 轮 D2 episode 代数闭合，27 组敏感度网格生成。 |
| `pytest_verbose.log` | `52d3801a9274c01f61cf0d26bfda51c8e60ee2991594db27a015398538c329ea` | `202d7ac` | `/code/failmem-ros2-agent` | `pytest tests/ -v` | `0` | **补充重跑**。全量未截断文本日志（22KB）：**196 passed, 8 xfailed, 0 failed**。 |
| `reproduction_run.log` | `32a5883509ebc10fe8c9c726bfbc0f137a93f9cab932f324eafe0b246a1f8c58` | `202d7ac` | `/code/failmem-ros2-agent` | `./scripts/reproduce_offline.sh --output-dir reports/acceptance/reproduction_audit` | `0` | **补充重跑**。271/271 SHA256 吻合，Replay 30/30 审计通过，Diff=0。 |
| `reproduction_audit/reproduction_report.json` | `1890f60d96e76b3737e65eb29558650419883b8f7523338d6f0ca43fe0e66a26` | `202d7ac` | `/code/failmem-ros2-agent` | 同上（由离线流水线自动生成） | `0` | **补充重跑**。离线复现综合评测报告，记录重算状态与一致性结果。 |
| `reproduction_audit/integrity_report.json` | `a5085ce55b65b91abd33454acebd63a1d0ee08e345a29e3b9d00d0fe146b5e1b` | `202d7ac` | `/code/failmem-ros2-agent` | 同上（由离线流水线自动生成） | `0` | **补充重跑**。完整性与校验和比对报告，确认无任何数据漂移。 |

---

## 三、构建报告来源与状态区分 (Build Report Distinction)

为保证审计真实性，严禁混淆主工作区与独立验收工作区的构建报告：

1. **主工作区构建报告 (`paper/build_report.json`)**:
   - **生成环境**: 主仓库开发目录 `/code/failmem-ros2-agent/`
   - **源码状态**: 记录在 `b19fccf` 之上包含未提交本地手稿编辑时的预检与构建记录（`source_dirty: true`）。
   - **用途**: 跟踪本地工作区手稿迭代与自动文本检查状态。
2. **独立验收构建报告 (`reports/acceptance/build_report_standalone_de05246.json`)**:
   - **生成环境**: 独立隔离目录 `/tmp/failmem_independent_acceptance/`
   - **检出源码**: 明确对应提交 `de05246f251263fb60a98ca3995fb8d65f38905c`。
   - **依赖状态**: 仅包含依据 `package-lock.json` 执行 `npm ci` 后的就地 `node_modules`。
   - **用途**: 证明在无主工作区隐式依赖借用情况下，独立工作树能够完整复现出版物 PDF 编译。

---

## 四、视觉走查状态与关联产物声明 (Visual Inspection Attribution)

1. **自动化构建默认状态**:
   - 构建脚本已修正为：在任何自动化构建（无论是本地还是独立 worktree）中，默认记录 `visual_inspection.status = "NOT_PERFORMED"`。
   - 自动构建流水线不得自动宣称已完成视觉走查。
2. **走查主体与责任边界**:
   - 实际视觉走查由代理（Antigravity AI Agent）对最新出版物 PDF（`paper.pdf`: `77707d90...`, `supplementary.pdf`: `b86bdb0b...`）的全量 14 张高分辨率页面逐页完成。
   - 彻底删除“人工与代理双重核验”措辞，如实保留 `human_verified = false`，明确界定最终责任待人类作者投稿前最终审阅。
