# 原始经历来源记录与历史提示词完整性审计报告 (Provenance Integrity Audit Report)

**审计时间**: 2026-10-12 05:28:56 UTC  
**审计对象**: 24 次已冻结历史模型调用提示词 (`natural_candidate_corpus.json`) vs 真实 Linux OS 实际工具返回  
**审计结论**: 共审计 24 次调用，其中 **24 / 24 次标记为【历史来源未完整保留】**。  

---

## 1. 核心审计发现与差异归因

### 1.1 `result.get('error', '预设错误文本')` 导致的真实 stderr 被人工文本替换
- 在早期收集脚本 `collect_12_genuine_failure_traces` 中，`start_service` 和 `write_config` 实际返回字段为 `stderr`，而非 `error`；
- 代码使用了 `result.get('error', 'Address already in use: 18080')` 这一写法，导致字典找不到 `error` 键时自动使用了预先写好的人工字符串；
- **实测对比**：
  - 真实 `start_service` 端口冲突返回：`OSError: [Errno 98] Address already in use (Port 18080)`；历史提示词注入为：`Address already in use: 18080`；
  - 真实 `write_config` 权限被拒返回：`bash: line 1: /etc/service_demo/app_sys.json: Permission denied`；历史提示词注入为：`Permission denied`；
  - 真实 `start_service` 缺失文件返回：`FileNotFoundError: Config file not found: ...`；历史提示词注入为：`Config file not found`；
  - 真实 `start_service` 非法 JSON 返回：`ValueError: Failed to parse config JSON: ...`；历史提示词注入为：`Failed to parse json config`。

### 1.2 `check_health` 工具返回格式不一致与退出码硬编码
- `check_health` 工具属于网络探针，实际返回格式为 `{'status': 'DOWN', 'healthy': False, 'error': 'Connection refused: port ... is not listening'}`；
- 该工具根本不返回 `exit_code` 与 `stderr`，早期脚本硬编码注入了 `exit_code: 1` 和预设文本。

### 1.3 `source_origin` 标签与真实执行来源错位
- 早期脚本将部分受控临时执行标为 `diagnostic_traces.json:inst1_port_conflict_persistent`，然而这些调用是脚本临时 `setup()` 执行产生的，并非从旧有的诊断日志文件中回放读取；
- 本次审计明确纠正来源标签为真实受控执行，不伪称历史文件回放。

### 1.4 `visible_observations` 观测来源未与 Agent 工具链严格绑定
- 早期提示词中的 `Visible Observations` 系人工构造的静态字典（例如在未调用探测工具的情况下直接注入 `target_dir_mode: 0755` 或 `config_file_exists: True`），将环境内部状态冒充为 Agent 观测。

---

## 2. 24 次历史调用提示词逐项审计总表

| 调用编号 | Trace ID | 提取方式 | 来源完整性状态 | 提示词 Error Output | 真实工具输出 (stderr/error) | 提示词 Exit Code | 真实 Exit Code | 差异归因 |
| :--- | :--- | :--- | :---: | :--- | :--- | :---: | :---: | :--- |
| #1 | trace_01_port_18080_conflict | Method A | **历史来源未完整保留** | `Address already in use: 18080` | `OSError: [Errno 98] Address al...` | 98 | 98 | stderr / Error Output; source_origin; Visible Observations |
| #2 | trace_01_port_18080_conflict | Method B | **历史来源未完整保留** | `Address already in use: 18080` | `OSError: [Errno 98] Address al...` | 98 | 98 | stderr / Error Output; source_origin; Visible Observations |
| #3 | trace_02_etc_permission_denied | Method A | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /etc/service_dem...` | 1 | 1 | stderr / Error Output; source_origin; Visible Observations |
| #4 | trace_02_etc_permission_denied | Method B | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /etc/service_dem...` | 1 | 1 | stderr / Error Output; source_origin; Visible Observations |
| #5 | trace_03_port_18081_reserved | Method A | **历史来源未完整保留** | `Address already in use: 18081` | `OSError: [Errno 98] Address al...` | 98 | 98 | stderr / Error Output; Visible Observations |
| #6 | trace_03_port_18081_reserved | Method B | **历史来源未完整保留** | `Address already in use: 18081` | `OSError: [Errno 98] Address al...` | 98 | 98 | stderr / Error Output; Visible Observations |
| #7 | trace_04_root_dir_permission_denied | Method A | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /root/service_de...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #8 | trace_04_root_dir_permission_denied | Method B | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /root/service_de...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #9 | trace_05_nonexistent_config_path | Method A | **历史来源未完整保留** | `Config file not found` | `FileNotFoundError: Config file...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #10 | trace_05_nonexistent_config_path | Method B | **历史来源未完整保留** | `Config file not found` | `FileNotFoundError: Config file...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #11 | trace_06_malformed_json_config | Method A | **历史来源未完整保留** | `Failed to parse json config` | `ValueError: Failed to parse co...` | 2 | 2 | stderr / Error Output; Visible Observations |
| #12 | trace_06_malformed_json_config | Method B | **历史来源未完整保留** | `Failed to parse json config` | `ValueError: Failed to parse co...` | 2 | 2 | stderr / Error Output; Visible Observations |
| #13 | trace_07_health_check_closed_port | Method A | **历史来源未完整保留** | `Connection refused: port 18085...` | `Connection refused: port 18085...` | 1 | None | Exit Code; Visible Observations |
| #14 | trace_07_health_check_closed_port | Method B | **历史来源未完整保留** | `Connection refused: port 18085...` | `Connection refused: port 18085...` | 1 | None | Exit Code; Visible Observations |
| #15 | trace_08_midflight_port_preemption | Method A | **历史来源未完整保留** | `Address already in use: 18080` | `OSError: [Errno 98] Address al...` | 98 | 98 | stderr / Error Output; source_origin; Visible Observations |
| #16 | trace_08_midflight_port_preemption | Method B | **历史来源未完整保留** | `Address already in use: 18080` | `OSError: [Errno 98] Address al...` | 98 | 98 | stderr / Error Output; source_origin; Visible Observations |
| #17 | trace_09_nonexistent_parent_directory | Method A | **历史来源未完整保留** | `No such file or directory` | `bash: line 1: /tmp/nonexistent...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #18 | trace_09_nonexistent_parent_directory | Method B | **历史来源未完整保留** | `No such file or directory` | `bash: line 1: /tmp/nonexistent...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #19 | trace_10_overwrite_readonly_file | Method A | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /home/agentuser/...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #20 | trace_10_overwrite_readonly_file | Method B | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /home/agentuser/...` | 1 | 1 | stderr / Error Output; Visible Observations |
| #21 | trace_11_service_crashed_unhealthy | Method A | **历史来源未完整保留** | `Connection refused: port 18081...` | `Connection refused: port 18081...` | 1 | None | Exit Code; Visible Observations |
| #22 | trace_11_service_crashed_unhealthy | Method B | **历史来源未完整保留** | `Connection refused: port 18081...` | `Connection refused: port 18081...` | 1 | None | Exit Code; Visible Observations |
| #23 | trace_12_permission_port_composition | Method A | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /etc/service_dem...` | 1 | 1 | stderr / Error Output; source_origin; Visible Observations |
| #24 | trace_12_permission_port_composition | Method B | **历史来源未完整保留** | `Permission denied` | `bash: line 1: /etc/service_dem...` | 1 | 1 | stderr / Error Output; source_origin; Visible Observations |

---

## 3. 科学诚信声明与约束

1. **历史模型输出绝对冻结**：24 次历史调用的原始输出 (`raw_output`) 完全保留，绝不重新调用 GPU 或虚构模型在修正后输入上的表现；
2. **历史证据不可追补**：对于早期输入中被预设文本或未绑定观测污染的部分，如实标记为【历史来源未完整保留】，不进行事后粉饰；
3. **后续核验原则**：重写核验器时，必须直接核验模型输出的候选规则本身的内在语义与真实 OS 执行情况，不再依赖预先设定的 trace 故障类型。
