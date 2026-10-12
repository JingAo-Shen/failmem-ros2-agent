"""
Provenance Integrity Audit & CPU Re-collection Script.

Protocol:
1. Re-executes the 12 failure scenarios on real OS environments using MultiStepDeploymentEnv.
2. Captures 100% genuine raw tool returns without default fallbacks or synthetic text.
3. Explicitly binds visible observations to actual agent tool calls (e.g., probe_file, probe_directory, probe_port).
4. Audits the differences between the frozen 24 model prompt inputs and the genuine tool returns.
5. Marks unrecoverable discrepancies as '历史来源未完整保留' (Historical provenance not fully preserved).
6. Outputs:
   - results/provenance_integrity_audit.json
   - results/provenance_integrity_report.md
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from research.conditional_constraint_memory.multistep_deployment_env import MultiStepDeploymentEnv

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CORPUS_JSON_FILE = RESULTS_DIR / "natural_candidate_corpus.json"
AUDIT_JSON_FILE = RESULTS_DIR / "provenance_integrity_audit.json"
AUDIT_REPORT_FILE = RESULTS_DIR / "provenance_integrity_report.md"


def recollect_12_genuine_traces_clean(env: MultiStepDeploymentEnv) -> List[Dict[str, Any]]:
    """
    Re-collects the 12 failure scenarios with 100% genuine raw returns,
    zero default fallback strings, and observation binding to actual probe tools.
    """
    clean_traces = []

    # Trace 1: Persistent port 18080 conflict on start_service
    env.setup("inst1_port_conflict_persistent")
    w_res1 = env.write_config("/home/agentuser/service_conf/app_t1.json", port=18080)
    p_port1 = env.probe_port(18080)
    t1_res = env.start_service("/home/agentuser/service_conf/app_t1.json")
    clean_traces.append({
        "trace_id": "trace_01_port_18080_conflict",
        "category": "port_conflict",
        "scenario_setup": "controlled_os_recollection:inst1_port_conflict_persistent",
        "tool_name": "start_service",
        "tool_params": {"config_path": "/home/agentuser/service_conf/app_t1.json"},
        "raw_tool_return": t1_res,
        "call_id": t1_res.get("call_id"),
        "exit_code": t1_res.get("exit_code"),
        "stderr": t1_res.get("stderr"),
        "stdout": t1_res.get("stdout"),
        "status": t1_res.get("status"),
        "error_type": t1_res.get("error_type"),
        "bound_observations": {
            "probe_port_result": {"port": 18080, "is_occupied": p_port1.get("is_occupied")},
            "write_config_result": {"config_path": w_res1.get("config_path"), "success": w_res1.get("success")},
        },
    })
    env.teardown()

    # Trace 2: Non-root user write to /etc/service_demo
    env.setup("inst3_permission_fallback")
    p_dir2 = env.probe_directory("/etc/service_demo")
    t2_res = env.write_config("/etc/service_demo/app_sys.json", port=18080)
    clean_traces.append({
        "trace_id": "trace_02_etc_permission_denied",
        "category": "permission_denied",
        "scenario_setup": "controlled_os_recollection:inst3_permission_fallback",
        "tool_name": "write_config",
        "tool_params": {"config_path": "/etc/service_demo/app_sys.json", "port": 18080},
        "raw_tool_return": t2_res,
        "call_id": t2_res.get("call_id"),
        "exit_code": t2_res.get("exit_code"),
        "stderr": t2_res.get("stderr"),
        "stdout": t2_res.get("stdout"),
        "status": t2_res.get("status"),
        "error_type": t2_res.get("error_type"),
        "bound_observations": {
            "probe_directory_result": {
                "dirpath": "/etc/service_demo",
                "exists": p_dir2.get("exists"),
                "writable_by_user": p_dir2.get("writable_by_user"),
                "mode": p_dir2.get("mode"),
                "owner_uid": p_dir2.get("owner_uid"),
            }
        },
    })
    env.teardown()

    # Trace 3: Port 18081 reserved during start_service
    env.setup("inst7_midepisode_port_clash")
    w_res3 = env.write_config("/home/agentuser/service_conf/app_t3.json", port=18081)
    p_port3 = env.probe_port(18081)
    t3_res = env.start_service("/home/agentuser/service_conf/app_t3.json")
    clean_traces.append({
        "trace_id": "trace_03_port_18081_reserved",
        "category": "port_conflict",
        "scenario_setup": "controlled_os_recollection:inst7_midepisode_port_clash",
        "tool_name": "start_service",
        "tool_params": {"config_path": "/home/agentuser/service_conf/app_t3.json"},
        "raw_tool_return": t3_res,
        "call_id": t3_res.get("call_id"),
        "exit_code": t3_res.get("exit_code"),
        "stderr": t3_res.get("stderr"),
        "stdout": t3_res.get("stdout"),
        "status": t3_res.get("status"),
        "error_type": t3_res.get("error_type"),
        "bound_observations": {
            "probe_port_result": {"port": 18081, "is_occupied": p_port3.get("is_occupied")},
            "write_config_result": {"config_path": w_res3.get("config_path"), "success": w_res3.get("success")},
        },
    })
    env.teardown()

    # Trace 4: Write config to /root/ directory as non-root user
    env.setup("inst1_port_conflict_persistent")
    p_dir4 = env.probe_directory("/root")
    t4_res = env.write_config("/root/service_demo.json", port=18080)
    clean_traces.append({
        "trace_id": "trace_04_root_dir_permission_denied",
        "category": "permission_denied",
        "scenario_setup": "controlled_os_recollection:inst1_write_root",
        "tool_name": "write_config",
        "tool_params": {"config_path": "/root/service_demo.json", "port": 18080},
        "raw_tool_return": t4_res,
        "call_id": t4_res.get("call_id"),
        "exit_code": t4_res.get("exit_code"),
        "stderr": t4_res.get("stderr"),
        "stdout": t4_res.get("stdout"),
        "status": t4_res.get("status"),
        "error_type": t4_res.get("error_type"),
        "bound_observations": {
            "probe_directory_result": {
                "dirpath": "/root",
                "exists": p_dir4.get("exists"),
                "writable_by_user": p_dir4.get("writable_by_user"),
                "mode": p_dir4.get("mode"),
                "owner_uid": p_dir4.get("owner_uid"),
            }
        },
    })
    env.teardown()

    # Trace 5: Start service with non-existent config path
    env.setup("inst1_port_conflict_persistent")
    p_file5 = env.probe_file("/home/agentuser/service_conf/nonexistent_cfg_999.json")
    t5_res = env.start_service("/home/agentuser/service_conf/nonexistent_cfg_999.json")
    clean_traces.append({
        "trace_id": "trace_05_nonexistent_config_path",
        "category": "missing_resource",
        "scenario_setup": "controlled_os_recollection:start_service_missing_file",
        "tool_name": "start_service",
        "tool_params": {"config_path": "/home/agentuser/service_conf/nonexistent_cfg_999.json"},
        "raw_tool_return": t5_res,
        "call_id": t5_res.get("call_id"),
        "exit_code": t5_res.get("exit_code"),
        "stderr": t5_res.get("stderr"),
        "stdout": t5_res.get("stdout"),
        "status": t5_res.get("status"),
        "error_type": t5_res.get("error_type"),
        "bound_observations": {
            "probe_file_result": {
                "filepath": "/home/agentuser/service_conf/nonexistent_cfg_999.json",
                "exists": p_file5.get("exists"),
                "writable_by_user": p_file5.get("writable_by_user"),
            }
        },
    })
    env.teardown()

    # Trace 6: Start service with empty / malformed JSON configuration
    env.setup("inst1_port_conflict_persistent")
    malformed_path = Path("/home/agentuser/service_conf/malformed.json")
    malformed_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_path.write_text("{malformed_json_syntax: true,\n", encoding="utf-8")
    os.chown(malformed_path, 1001, 1001)
    p_file6 = env.probe_file(str(malformed_path))
    t6_res = env.start_service(str(malformed_path))
    clean_traces.append({
        "trace_id": "trace_06_malformed_json_config",
        "category": "invalid_configuration",
        "scenario_setup": "controlled_os_recollection:malformed_json_config",
        "tool_name": "start_service",
        "tool_params": {"config_path": str(malformed_path)},
        "raw_tool_return": t6_res,
        "call_id": t6_res.get("call_id"),
        "exit_code": t6_res.get("exit_code"),
        "stderr": t6_res.get("stderr"),
        "stdout": t6_res.get("stdout"),
        "status": t6_res.get("status"),
        "error_type": t6_res.get("error_type"),
        "bound_observations": {
            "probe_file_result": {
                "filepath": str(malformed_path),
                "exists": p_file6.get("exists"),
            }
        },
    })
    env.teardown()

    # Trace 7: Health check on non-listening port 18085
    env.setup("inst1_port_conflict_persistent")
    p_port7 = env.probe_port(18085)
    t7_res = env.check_health(18085)
    clean_traces.append({
        "trace_id": "trace_07_health_check_closed_port",
        "category": "connection_refused",
        "scenario_setup": "controlled_os_recollection:check_health_unbound_port",
        "tool_name": "check_health",
        "tool_params": {"port": 18085},
        "raw_tool_return": t7_res,
        "call_id": t7_res.get("call_id"),
        "exit_code": t7_res.get("exit_code"),  # Notice: check_health does not produce exit_code
        "stderr": t7_res.get("stderr"),        # Notice: check_health does not produce stderr
        "stdout": t7_res.get("stdout"),
        "status": t7_res.get("status"),        # Has status='DOWN'
        "error": t7_res.get("error"),          # Has error='Connection refused...'
        "bound_observations": {
            "probe_port_result": {
                "port": 18085,
                "is_occupied": p_port7.get("is_occupied"),
                "status": p_port7.get("status"),
            }
        },
    })
    env.teardown()

    # Trace 8: Mid-episode preemption on port 18080 (inst5)
    env.setup("inst5_stale_observation")
    env.probe_directory("/home/agentuser/service_conf")
    env.probe_directory("/home/agentuser/service_conf")
    env.probe_directory("/home/agentuser/service_conf")  # Triggers mid-episode occupier
    w_res8 = env.write_config("/home/agentuser/service_conf/app_stale.json", port=18080)
    t8_res = env.start_service("/home/agentuser/service_conf/app_stale.json")
    clean_traces.append({
        "trace_id": "trace_08_midflight_port_preemption",
        "category": "port_conflict",
        "scenario_setup": "controlled_os_recollection:inst5_stale_observation",
        "tool_name": "start_service",
        "tool_params": {"config_path": "/home/agentuser/service_conf/app_stale.json"},
        "raw_tool_return": t8_res,
        "call_id": t8_res.get("call_id"),
        "exit_code": t8_res.get("exit_code"),
        "stderr": t8_res.get("stderr"),
        "stdout": t8_res.get("stdout"),
        "status": t8_res.get("status"),
        "error_type": t8_res.get("error_type"),
        "bound_observations": {
            "write_config_result": {"config_path": w_res8.get("config_path"), "port": 18080}
        },
    })
    env.teardown()

    # Trace 9: Write config to non-existent parent directory
    env.setup("inst1_port_conflict_persistent")
    p_file9 = env.probe_file("/tmp/nonexistent_subfolder_xyz/app.json")
    t9_res = env.write_config("/tmp/nonexistent_subfolder_xyz/app.json", port=18080)
    clean_traces.append({
        "trace_id": "trace_09_nonexistent_parent_directory",
        "category": "missing_directory",
        "scenario_setup": "controlled_os_recollection:write_missing_parent_dir",
        "tool_name": "write_config",
        "tool_params": {"config_path": "/tmp/nonexistent_subfolder_xyz/app.json", "port": 18080},
        "raw_tool_return": t9_res,
        "call_id": t9_res.get("call_id"),
        "exit_code": t9_res.get("exit_code"),
        "stderr": t9_res.get("stderr"),
        "stdout": t9_res.get("stdout"),
        "status": t9_res.get("status"),
        "error_type": t9_res.get("error_type"),
        "bound_observations": {
            "probe_file_result": {
                "filepath": "/tmp/nonexistent_subfolder_xyz/app.json",
                "exists": p_file9.get("exists"),
                "parent_dir": p_file9.get("parent_dir"),
                "writable_by_user": p_file9.get("writable_by_user"),
            }
        },
    })
    env.teardown()

    # Trace 10: Overwrite read-only file
    env.setup("inst1_port_conflict_persistent")
    ro_file = Path("/home/agentuser/service_conf/readonly_app.json")
    ro_file.write_text('{"readonly": true}\n', encoding="utf-8")
    os.chmod(ro_file, 0o444)
    p_file10 = env.probe_file(str(ro_file))
    t10_res = env.write_config(str(ro_file), port=18080)
    clean_traces.append({
        "trace_id": "trace_10_overwrite_readonly_file",
        "category": "permission_denied",
        "scenario_setup": "controlled_os_recollection:overwrite_readonly_file",
        "tool_name": "write_config",
        "tool_params": {"config_path": str(ro_file), "port": 18080},
        "raw_tool_return": t10_res,
        "call_id": t10_res.get("call_id"),
        "exit_code": t10_res.get("exit_code"),
        "stderr": t10_res.get("stderr"),
        "stdout": t10_res.get("stdout"),
        "status": t10_res.get("status"),
        "error_type": t10_res.get("error_type"),
        "bound_observations": {
            "probe_file_result": {
                "filepath": str(ro_file),
                "exists": p_file10.get("exists"),
                "mode": p_file10.get("mode"),
                "writable_by_user": p_file10.get("writable_by_user"),
            }
        },
    })
    env.teardown()

    # Trace 11: Health check after simulated service crash
    env.setup("inst1_port_conflict_persistent")
    env.write_config("/home/agentuser/service_conf/app_crash.json", port=18081)
    env.start_service("/home/agentuser/service_conf/app_crash.json")
    env.simulate_service_crash("SIMULATED_SIGTERM")
    p_port11 = env.probe_port(18081)
    t11_res = env.check_health(18081)
    clean_traces.append({
        "trace_id": "trace_11_service_crashed_unhealthy",
        "category": "service_crash",
        "scenario_setup": "controlled_os_recollection:simulate_service_crash",
        "tool_name": "check_health",
        "tool_params": {"port": 18081},
        "raw_tool_return": t11_res,
        "call_id": t11_res.get("call_id"),
        "exit_code": t11_res.get("exit_code"),  # Missing in check_health
        "stderr": t11_res.get("stderr"),        # Missing in check_health
        "stdout": t11_res.get("stdout"),
        "status": t11_res.get("status"),
        "error": t11_res.get("error"),
        "bound_observations": {
            "probe_port_result": {
                "port": 18081,
                "is_occupied": p_port11.get("is_occupied"),
                "status": p_port11.get("status"),
            }
        },
    })
    env.teardown()

    # Trace 12: Dual composition: /etc/service_demo unwritable and 18080 occupied
    env.setup("inst8_permission_and_port_composition")
    p_dir12 = env.probe_directory("/etc/service_demo")
    t12_res = env.write_config("/etc/service_demo/app_comp.json", port=18080)
    clean_traces.append({
        "trace_id": "trace_12_permission_port_composition",
        "category": "permission_denied",
        "scenario_setup": "controlled_os_recollection:inst8_permission_and_port_composition",
        "tool_name": "write_config",
        "tool_params": {"config_path": "/etc/service_demo/app_comp.json", "port": 18080},
        "raw_tool_return": t12_res,
        "call_id": t12_res.get("call_id"),
        "exit_code": t12_res.get("exit_code"),
        "stderr": t12_res.get("stderr"),
        "stdout": t12_res.get("stdout"),
        "status": t12_res.get("status"),
        "error_type": t12_res.get("error_type"),
        "bound_observations": {
            "probe_directory_result": {
                "dirpath": "/etc/service_demo",
                "exists": p_dir12.get("exists"),
                "writable_by_user": p_dir12.get("writable_by_user"),
                "mode": p_dir12.get("mode"),
                "owner_uid": p_dir12.get("owner_uid"),
            }
        },
    })
    env.teardown()

    return clean_traces


def audit_historical_corpus_prompts(clean_traces: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compares the 24 historical frozen prompts against genuine tool returns.
    Identifies all discrepancies, fallback injections, fake provenance tags,
    and synthetic observations.
    """
    with open(CORPUS_JSON_FILE, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    clean_by_id = {t["trace_id"]: t for t in clean_traces}
    audit_records = []

    for item in corpus:
        c_idx = item["call_index"]
        t_id = item["trace_id"]
        method = item["extraction_method"]
        raw_prompt = item["raw_prompt"]
        raw_output = item["raw_output"]

        clean = clean_by_id.get(t_id, {})
        raw_ret = clean.get("raw_tool_return", {})

        # Extract prompt fields
        prompt_tool = None
        prompt_exit = None
        prompt_stderr = None
        prompt_obs = None

        for line in raw_prompt.split("\n"):
            if line.startswith("Tool:"):
                prompt_tool = line.split("Tool:", 1)[-1].strip()
            elif line.startswith("Exit Code:"):
                prompt_exit = line.split("Exit Code:", 1)[-1].strip()
            elif line.startswith("Error Output:"):
                prompt_stderr = line.split("Error Output:", 1)[-1].strip()
            elif line.startswith("Visible Observations:"):
                prompt_obs = line.split("Visible Observations:", 1)[-1].strip()

        # Audit Discrepancies
        discrepancies = []

        # 1. Stderr comparison
        actual_stderr = raw_ret.get("stderr") or raw_ret.get("error") or ""
        if prompt_stderr != actual_stderr:
            discrepancies.append({
                "field": "stderr / Error Output",
                "prompt_value": prompt_stderr,
                "genuine_tool_value": actual_stderr,
                "reason": "Preset error text fallback or manual truncation used in collection script",
            })

        # 2. Exit code comparison
        actual_exit = raw_ret.get("exit_code")
        if actual_exit is None:
            discrepancies.append({
                "field": "Exit Code",
                "prompt_value": prompt_exit,
                "genuine_tool_value": "MISSING (tool does not produce exit_code)",
                "reason": "Synthetic exit_code fallback injected into prompt for tool that lacks exit_code",
            })
        elif str(actual_exit) != str(prompt_exit):
            discrepancies.append({
                "field": "Exit Code",
                "prompt_value": prompt_exit,
                "genuine_tool_value": str(actual_exit),
                "reason": "Exit code mismatch with genuine tool return",
            })

        # 3. Source Origin check
        # In historical run_natural_candidate_corpus.py, lines 66, 83, 194, 268 tagged historical diagnostic_traces.json
        if t_id in ("trace_01_port_18080_conflict", "trace_02_etc_permission_denied",
                    "trace_08_midflight_port_preemption", "trace_12_permission_port_composition"):
            discrepancies.append({
                "field": "source_origin",
                "prompt_value": "diagnostic_traces.json (tagged in script)",
                "genuine_tool_value": clean.get("scenario_setup"),
                "reason": "Inaccurately labeled as historical diagnostic_traces.json when freshly executed in Python script",
            })

        # 4. Visible Observations check
        # Did visible_observations come from actual agent tools or synthetic setup knowledge?
        discrepancies.append({
            "field": "Visible Observations",
            "prompt_value": prompt_obs,
            "genuine_tool_value": clean.get("bound_observations"),
            "reason": "Historical prompt observations were manually assembled dictionaries rather than strict logs of preceding agent tool calls",
        })

        record = {
            "call_index": c_idx,
            "trace_id": t_id,
            "extraction_method": method,
            "provenance_status": "历史来源未完整保留" if discrepancies else "PROVENANCE_VERIFIED",
            "discrepancies": discrepancies,
            "prompt_tool_name": prompt_tool,
            "prompt_exit_code": prompt_exit,
            "prompt_error_output": prompt_stderr,
            "prompt_visible_observations": prompt_obs,
            "genuine_raw_return": raw_ret,
        }
        audit_records.append(record)

    return {
        "audit_timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "total_calls_audited": len(audit_records),
        "unpreserved_provenance_count": sum(1 for r in audit_records if r["provenance_status"] == "历史来源未完整保留"),
        "audit_records": audit_records,
    }


def generate_audit_report(audit_data: Dict[str, Any]):
    records = audit_data["audit_records"]
    lines = [
        "# 原始经历来源记录与历史提示词完整性审计报告 (Provenance Integrity Audit Report)",
        "",
        f"**审计时间**: {audit_data['audit_timestamp']}  ",
        f"**审计对象**: 24 次已冻结历史模型调用提示词 (`natural_candidate_corpus.json`) vs 真实 Linux OS 实际工具返回  ",
        f"**审计结论**: 共审计 24 次调用，其中 **{audit_data['unpreserved_provenance_count']} / 24 次标记为【历史来源未完整保留】**。  ",
        "",
        "---",
        "",
        "## 1. 核心审计发现与差异归因",
        "",
        "### 1.1 `result.get('error', '预设错误文本')` 导致的真实 stderr 被人工文本替换",
        "- 在早期收集脚本 `collect_12_genuine_failure_traces` 中，`start_service` 和 `write_config` 实际返回字段为 `stderr`，而非 `error`；",
        "- 代码使用了 `result.get('error', 'Address already in use: 18080')` 这一写法，导致字典找不到 `error` 键时自动使用了预先写好的人工字符串；",
        "- **实测对比**：",
        "  - 真实 `start_service` 端口冲突返回：`OSError: [Errno 98] Address already in use (Port 18080)`；历史提示词注入为：`Address already in use: 18080`；",
        "  - 真实 `write_config` 权限被拒返回：`bash: line 1: /etc/service_demo/app_sys.json: Permission denied`；历史提示词注入为：`Permission denied`；",
        "  - 真实 `start_service` 缺失文件返回：`FileNotFoundError: Config file not found: ...`；历史提示词注入为：`Config file not found`；",
        "  - 真实 `start_service` 非法 JSON 返回：`ValueError: Failed to parse config JSON: ...`；历史提示词注入为：`Failed to parse json config`。",
        "",
        "### 1.2 `check_health` 工具返回格式不一致与退出码硬编码",
        "- `check_health` 工具属于网络探针，实际返回格式为 `{'status': 'DOWN', 'healthy': False, 'error': 'Connection refused: port ... is not listening'}`；",
        "- 该工具根本不返回 `exit_code` 与 `stderr`，早期脚本硬编码注入了 `exit_code: 1` 和预设文本。",
        "",
        "### 1.3 `source_origin` 标签与真实执行来源错位",
        "- 早期脚本将部分受控临时执行标为 `diagnostic_traces.json:inst1_port_conflict_persistent`，然而这些调用是脚本临时 `setup()` 执行产生的，并非从旧有的诊断日志文件中回放读取；",
        "- 本次审计明确纠正来源标签为真实受控执行，不伪称历史文件回放。",
        "",
        "### 1.4 `visible_observations` 观测来源未与 Agent 工具链严格绑定",
        "- 早期提示词中的 `Visible Observations` 系人工构造的静态字典（例如在未调用探测工具的情况下直接注入 `target_dir_mode: 0755` 或 `config_file_exists: True`），将环境内部状态冒充为 Agent 观测。",
        "",
        "---",
        "",
        "## 2. 24 次历史调用提示词逐项审计总表",
        "",
        "| 调用编号 | Trace ID | 提取方式 | 来源完整性状态 | 提示词 Error Output | 真实工具输出 (stderr/error) | 提示词 Exit Code | 真实 Exit Code | 差异归因 |",
        "| :--- | :--- | :--- | :---: | :--- | :--- | :---: | :---: | :--- |",
    ]

    for r in records:
        c_idx = r["call_index"]
        t_id = r["trace_id"]
        method = "Method A" if "Method_A" in r["extraction_method"] else "Method B"
        status = r["provenance_status"]
        p_err = r["prompt_error_output"][:30] + ("..." if len(r["prompt_error_output"]) > 30 else "")
        raw_err = (r["genuine_raw_return"].get("stderr") or r["genuine_raw_return"].get("error") or "None")
        raw_err_short = raw_err[:30] + ("..." if len(raw_err) > 30 else "")
        p_exit = r["prompt_exit_code"]
        raw_exit = str(r["genuine_raw_return"].get("exit_code"))

        reasons = "; ".join(d["field"] for d in r["discrepancies"])

        lines.append(
            f"| #{c_idx} | {t_id} | {method} | **{status}** | `{p_err}` | `{raw_err_short}` | {p_exit} | {raw_exit} | {reasons} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. 科学诚信声明与约束",
        "",
        "1. **历史模型输出绝对冻结**：24 次历史调用的原始输出 (`raw_output`) 完全保留，绝不重新调用 GPU 或虚构模型在修正后输入上的表现；",
        "2. **历史证据不可追补**：对于早期输入中被预设文本或未绑定观测污染的部分，如实标记为【历史来源未完整保留】，不进行事后粉饰；",
        "3. **后续核验原则**：重写核验器时，必须直接核验模型输出的候选规则本身的内在语义与真实 OS 执行情况，不再依赖预先设定的 trace 故障类型。",
    ])

    with open(AUDIT_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[Audit] Generated provenance integrity report at {AUDIT_REPORT_FILE}")


def main():
    print("=" * 80)
    print("RUNNING PROVENANCE INTEGRITY AUDIT & CLEAN RE-COLLECTION (CPU ONLY)")
    print("=" * 80)

    env = MultiStepDeploymentEnv()

    # 1. Recollect clean traces on CPU
    print("[1/3] Collecting genuine traces with 100% provenance integrity...")
    clean_traces = recollect_12_genuine_traces_clean(env)
    print(f"      Collected {len(clean_traces)} clean traces.")

    # 2. Audit historical corpus prompts
    print("[2/3] Auditing 24 frozen historical model prompts against genuine returns...")
    audit_data = audit_historical_corpus_prompts(clean_traces)

    with open(AUDIT_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, indent=2)
    print(f"      Saved audit JSON to {AUDIT_JSON_FILE}")

    # 3. Generate report
    print("[3/3] Generating audit report...")
    generate_audit_report(audit_data)
    print("[Done] Provenance integrity audit complete.")


if __name__ == "__main__":
    main()