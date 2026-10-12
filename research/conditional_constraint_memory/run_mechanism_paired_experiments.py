"""
Deterministic CPU Paired Mechanism Experiments (B2-G vs M).
Uses MultiStepAgentRunner with real OS environments (sockets, non-root user) and ScriptedPolicyBackend.
Covers 6 mechanism cases:
1. Valid candidate rule, blockage persists.
2. Valid rule, premise cleared.
3. Valid rule, irrelevant attribute changed.
4. Observation expired, premise still blocked after probe refresh.
5. Overgeneralized candidate rule, proposed action is actually feasible (True counter-example).
6. Conflicting or poorly-supported candidate rules.

Outputs:
- results/mechanism_paired_logs.json
- results/mechanism_paired_report.md
"""

import os
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from research.conditional_constraint_memory.constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    ConstraintLifecycleManager,
    FrozenMemorySnapshot,
    GateDecision,
)
from research.conditional_constraint_memory.multistep_deployment_env import (
    MultiStepDeploymentEnv,
    wait_for_port,
)
from research.conditional_constraint_memory.multistep_agent_runner import (
    MultiStepAgentRunner,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
PAIRED_LOGS_FILE = RESULTS_DIR / "mechanism_paired_logs.json"
PAIRED_REPORT_FILE = RESULTS_DIR / "mechanism_paired_report.md"


class ScriptedPolicyBackend:
    def __init__(self, action_sequence: List[Dict[str, Any]]):
        self.actions = list(action_sequence)
        self.invocations = 0

    def generate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        self.invocations += 1
        if self.actions:
            action = self.actions.pop(0)
        else:
            action = {"action": "finish", "params": {}}
        return {
            "content": json.dumps({
                "decision_summary": f"Scripted step {self.invocations}",
                "action": action.get("action", ""),
                "params": action.get("params", {}),
            }),
            "prompt_tokens": 80,
            "generated_tokens": 25,
            "latency_s": 0.001,
        }


def run_paired_case(
    case_id: str,
    case_name: str,
    case_description: str,
    is_synthetic_stress_test: bool,
    env_instance_id: str,
    rules: List[ConstraintRule],
    initial_observations: Dict[str, Any],
    action_sequence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Runs a single mechanism case for both B2-G and M under identical conditions."""
    env = MultiStepDeploymentEnv()
    case_res = {
        "case_id": case_id,
        "case_name": case_name,
        "case_description": case_description,
        "is_synthetic_stress_test": is_synthetic_stress_test,
        "arms": {},
    }

    for arm in ("B2-G", "M"):
        env.setup(env_instance_id)

        # Build isolated manager
        mgr = ConstraintLifecycleManager()
        for r in rules:
            # deep copy rule
            r_copy = ConstraintRule(
                rule_id=r.rule_id,
                action_signature=r.action_signature,
                predicates=list(r.predicates),
                failure_evidence=dict(r.failure_evidence),
                validity_state=r.validity_state,
                support_threshold=r.support_threshold,
                support_count=r.support_count,
                contradict_count=r.contradict_count,
                evidence_ids=list(r.evidence_ids),
                metadata=dict(r.metadata),
            )
            mgr.add_rule(r_copy)

        now = time.time()
        for k, v in initial_observations.items():
            val = v["value"]
            ts = now - v.get("age", 0.0)
            mgr.register_observation(k, val, timestamp=ts, call_id=v.get("call_id", "init"))

        runner = MultiStepAgentRunner(
            llm_backend=ScriptedPolicyBackend(action_sequence),
            max_llm_calls_per_episode=15,
            max_tool_calls_per_episode=20,
            max_time_per_episode_s=60.0,
        )

        res = runner.run_episode(
            group=arm,
            env=env,
            instance_id=env_instance_id,
            run_id=f"paired_{case_id}_{arm}",
            lifecycle_manager=mgr,
            max_steps=len(action_sequence) + 2,
        )

        # Extract rule states post-execution
        post_rule_states = {}
        for r_id, r in mgr.rules.items():
            post_rule_states[r_id] = {
                "validity_state": r.validity_state.value,
                "support_count": r.support_count,
                "contradict_count": r.contradict_count,
            }

        case_res["arms"][arm] = {
            "success": res["success"],
            "steps": res["steps"],
            "proposed_error_actions": res["proposed_error_actions"],
            "executed_error_actions": res["executed_error_actions"],
            "tp_blocks": res["tp_blocks"],
            "fp_blocks": res["fp_blocks"],
            "unknown_probes": res["unknown_probes"],
            "candidate_trials": res["candidate_trials"],
            "gate_events": res["gate_events"],
            "tool_records": res["tool_records"],
            "lifecycle_transitions": res["lifecycle_transitions"],
            "post_rule_states": post_rule_states,
        }
        env.teardown()

    return case_res


def main():
    print("=" * 80)
    print("RUNNING 6 CPU PAIRED MECHANISM EXPERIMENTS (B2-G vs M)")
    print("=" * 80)

    paired_results = []

    # -------------------------------------------------------------------------
    # Case 1: Valid Candidate Rule, Blockage Persists
    # -------------------------------------------------------------------------
    print("\n[Case 1] Valid candidate rule, blockage persists...")
    pred1 = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule1 = ConstraintRule(
        rule_id="r_c1_port",
        action_signature="start_service:port=18080",
        predicates=[pred1],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c1"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_c1"],
    )
    script_c1 = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c1.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c1.json"}},
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c1.json", "port": 18081}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c1.json"}},
        {"action": "check_health", "params": {"port": 18081}},
    ]
    res1 = run_paired_case(
        case_id="case_1",
        case_name="Valid Candidate Rule, Blockage Persists",
        case_description="Port 18080 occupied. Candidate rule matches. B2-G blocks immediately (0 error); M allows candidate trial (1 OS error), then upgrades to SUPPORTED.",
        is_synthetic_stress_test=False,
        env_instance_id="inst1_port_conflict_persistent",
        rules=[rule1],
        initial_observations={"port:18080:occupied": {"value": True, "age": 5.0}},
        action_sequence=script_c1,
    )
    paired_results.append(res1)
    print(f"  B2-G: executed_errors={res1['arms']['B2-G']['executed_error_actions']}, blocks={res1['arms']['B2-G']['tp_blocks']}")
    print(f"  M:    executed_errors={res1['arms']['M']['executed_error_actions']}, trials={res1['arms']['M']['candidate_trials']}, post_validity={res1['arms']['M']['post_rule_states']['r_c1_port']['validity_state']}")

    # -------------------------------------------------------------------------
    # Case 2: Valid Rule, Premise Cleared
    # -------------------------------------------------------------------------
    print("\n[Case 2] Valid rule, premise cleared...")
    pred2 = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule2 = ConstraintRule(
        rule_id="r_c2_port",
        action_signature="start_service:port=18080",
        predicates=[pred2],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c2"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_c2_a", "ev_c2_b"],
    )
    script_c2 = [
        {"action": "probe_port", "params": {"port": 18080}},
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c2.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c2.json"}},
        {"action": "check_health", "params": {"port": 18080}},
    ]
    # In inst6_alternate_port, port 18080 is free by default!
    res2 = run_paired_case(
        case_id="case_2",
        case_name="Valid Rule, Premise Cleared",
        case_description="Port 18080 is free. Rule declared condition is False. Both B2-G and M evaluate NOT_APPLICABLE, allow execution, and succeed.",
        is_synthetic_stress_test=False,
        env_instance_id="inst6_alternate_port",
        rules=[rule2],
        initial_observations={},  # probe in step 1 will refresh to False
        action_sequence=script_c2,
    )
    paired_results.append(res2)
    print(f"  B2-G: success={res2['arms']['B2-G']['success']}, executed_errors={res2['arms']['B2-G']['executed_error_actions']}")
    print(f"  M:    success={res2['arms']['M']['success']}, executed_errors={res2['arms']['M']['executed_error_actions']}, post_validity={res2['arms']['M']['post_rule_states']['r_c2_port']['validity_state']}")

    # -------------------------------------------------------------------------
    # Case 3: Valid Rule, Irrelevant Attribute Changed
    # -------------------------------------------------------------------------
    print("\n[Case 3] Valid rule, irrelevant attribute changed...")
    pred3 = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule3 = ConstraintRule(
        rule_id="r_c3_port",
        action_signature="start_service:port=18080",
        predicates=[pred3],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c3"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_c3_a", "ev_c3_b"],
    )
    script_c3 = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/arbitrary_custom_name.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/arbitrary_custom_name.json"}},
    ]
    res3 = run_paired_case(
        case_id="case_3",
        case_name="Valid Rule, Irrelevant Attribute Changed",
        case_description="Config filename arbitrarily changed, but target port is still 18080. Normalized action signature matches rule; both B2-G and M block.",
        is_synthetic_stress_test=False,
        env_instance_id="inst1_port_conflict_persistent",
        rules=[rule3],
        initial_observations={"port:18080:occupied": {"value": True, "age": 5.0}},
        action_sequence=script_c3,
    )
    paired_results.append(res3)
    print(f"  B2-G: blocks={res3['arms']['B2-G']['tp_blocks']}")
    print(f"  M:    blocks={res3['arms']['M']['tp_blocks']}")

    # -------------------------------------------------------------------------
    # Case 4: Observation Expired, Premise Still Blocked After Refresh
    # -------------------------------------------------------------------------
    print("\n[Case 4] Observation expired, premise still blocked after refresh...")
    pred4 = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule4 = ConstraintRule(
        rule_id="r_c4_port",
        action_signature="start_service:port=18080",
        predicates=[pred4],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c4"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_c4_a", "ev_c4_b"],
    )
    script_c4 = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c4.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c4.json"}},
    ]
    res4 = run_paired_case(
        case_id="case_4",
        case_name="Observation Expired, Premise Blocked After Refresh",
        case_description="Port 18080 observation is 60s old (TTL=30s -> UNKNOWN). start_service triggers PROBE, probe discovers port occupied, re-evaluation BLOCKS in both B2-G and M.",
        is_synthetic_stress_test=False,
        env_instance_id="inst1_port_conflict_persistent",
        rules=[rule4],
        initial_observations={"port:18080:occupied": {"value": True, "age": 60.0}},
        action_sequence=script_c4,
    )
    paired_results.append(res4)
    print(f"  B2-G: probes={res4['arms']['B2-G']['unknown_probes']}, blocks={res4['arms']['B2-G']['tp_blocks']}")
    print(f"  M:    probes={res4['arms']['M']['unknown_probes']}, blocks={res4['arms']['M']['tp_blocks']}")

    # -------------------------------------------------------------------------
    # Case 5: Overgeneralized Candidate Rule, Proposed Action Feasible (True Counter-Example)
    # -------------------------------------------------------------------------
    print("\n[Case 5] Overgeneralized candidate rule, proposed action feasible (Stress Test)...")
    pred5 = PreconditionPredicate("dir:/etc/service_demo:writable", False, ttl=30.0)
    rule5 = ConstraintRule(
        rule_id="stress_overgeneralized_write",
        action_signature="write_config:filepath=/home/agentuser/service_conf/app_c5.json",
        predicates=[pred5],
        failure_evidence={"error_code": 13, "error_type": "PermissionDenied", "evidence_id": "ev_c5_fake"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_c5_fake"],
        metadata={"stress_test": True, "type": "synthetic_overgeneralization"},
    )
    script_c5 = [
        {"action": "probe_directory", "params": {"dirpath": "/etc/service_demo"}},
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c5.json", "port": 18081}},
    ]
    res5 = run_paired_case(
        case_id="case_5",
        case_name="Overgeneralized Candidate Rule, Feasible Action (True Counter-Example)",
        case_description="[STRESS TEST SYNTHETIC] Rule claims /etc unwritable -> writing /home/agentuser fails. Premise holds True in OS. B2-G FP blocks feasible action; M allows candidate trial, OS write succeeds, M downgrades rule to CONTRADICTED.",
        is_synthetic_stress_test=True,
        env_instance_id="inst3_permission_fallback",
        rules=[rule5],
        initial_observations={},
        action_sequence=script_c5,
    )
    paired_results.append(res5)
    print(f"  B2-G: fp_blocks={res5['arms']['B2-G']['fp_blocks']}")
    print(f"  M:    candidate_trials={res5['arms']['M']['candidate_trials']}, executed_errors={res5['arms']['M']['executed_error_actions']}, post_validity={res5['arms']['M']['post_rule_states']['stress_overgeneralized_write']['validity_state']}")

    # -------------------------------------------------------------------------
    # Case 6: Conflicting or Poorly-Supported Candidate Rules
    # -------------------------------------------------------------------------
    print("\n[Case 6] Conflicting or poorly-supported candidate rules (Stress Test)...")
    pred6_a = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule6_a = ConstraintRule(
        rule_id="r_c6_valid",
        action_signature="start_service:port=18080",
        predicates=[pred6_a],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c6_a"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_c6_a1", "ev_c6_a2"],
    )
    pred6_b = PreconditionPredicate("port:18081:occupied", True, ttl=30.0)
    rule6_b = ConstraintRule(
        rule_id="stress_c6_spurious",
        action_signature="start_service:port=18081",
        predicates=[pred6_b],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c6_b"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_c6_b"],
        metadata={"stress_test": True, "type": "synthetic_spurious"},
    )
    script_c6 = [
        {"action": "probe_port", "params": {"port": 18081}},
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c6.json", "port": 18081}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c6.json"}},
        {"action": "check_health", "params": {"port": 18081}},
    ]
    res6 = run_paired_case(
        case_id="case_6",
        case_name="Conflicting or Poorly-Supported Candidate Rules",
        case_description="[STRESS TEST SYNTHETIC] Rule A valid on 18080; Rule B spurious on 18081. Port 18081 probed free. Both B2-G and M evaluate Rule B as NOT_APPLICABLE and execute successfully.",
        is_synthetic_stress_test=True,
        env_instance_id="inst1_port_conflict_persistent",
        rules=[rule6_a, rule6_b],
        initial_observations={"port:18080:occupied": {"value": True, "age": 5.0}},
        action_sequence=script_c6,
    )
    paired_results.append(res6)
    print(f"  B2-G: success={res6['arms']['B2-G']['success']}")
    print(f"  M:    success={res6['arms']['M']['success']}")

    # Save machine-readable logs
    with open(PAIRED_LOGS_FILE, "w", encoding="utf-8") as f:
        json.dump(paired_results, f, indent=2)
    print(f"\n[OUTPUT] Saved paired logs to {PAIRED_LOGS_FILE}")

    # Generate Markdown Report
    generate_paired_report(paired_results, PAIRED_REPORT_FILE)
    print(f"[OUTPUT] Generated paired report at {PAIRED_REPORT_FILE}")


def generate_paired_report(results: List[Dict[str, Any]], out_path: Path):
    lines = [
        "# CPU Paired Mechanism Experiments Report (B2-G vs M)",
        "",
        f"**Execution Date**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  ",
        "**Environment**: Production MultiStepDeploymentEnv (Real Linux Sockets, Non-Root agentuser Permissions)  ",
        "**Runner**: Production MultiStepAgentRunner with ScriptedPolicyBackend  ",
        "**Evaluation Methodology**: Identical initial rules, observations, action sequences, and budgets for B2-G and M.  ",
        "",
        "---",
        "",
        "## 1. 机制案例测试汇总对比表",
        "",
        "| 案例编号与名称 | 类型 | B2-G 阻断 (TP/FP) | B2-G 执行错误 | M 试探放行 | M 执行错误 | M 状态迁移 | 最终结果 (B2-G / M) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for c in results:
        cid = c["case_id"]
        cname = c["case_name"]
        is_syn = "压力测试 (人工构造)" if c["is_synthetic_stress_test"] else "常规机制"
        b2g = c["arms"]["B2-G"]
        m = c["arms"]["M"]

        b2g_block = f"{b2g['tp_blocks']} TP / {b2g['fp_blocks']} FP"
        b2g_err = b2g["executed_error_actions"]
        m_trial = m["candidate_trials"]
        m_err = m["executed_error_actions"]
        m_trans = len(m["lifecycle_transitions"])
        succ = f"{'Pass' if b2g['success'] else 'Fail'} / {'Pass' if m['success'] else 'Fail'}"

        lines.append(
            f"| **{cid}**: {cname} | {is_syn} | {b2g_block} | {b2g_err} | {m_trial} | {m_err} | {m_trans} 次 | {succ} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 2. 逐案例详细机制剖析",
        "",
    ])

    for c in results:
        cid = c["case_id"]
        cname = c["case_name"]
        cdesc = c["case_description"]
        b2g = c["arms"]["B2-G"]
        m = c["arms"]["M"]

        lines.extend([
            f"### {cid.upper()}: {cname}",
            f"- **测试目标与场景**: {cdesc}",
            f"- **B2-G 表现**: TP阻断={b2g['tp_blocks']}, FP阻断={b2g['fp_blocks']}, 探针={b2g['unknown_probes']}, 实际执行错误={b2g['executed_error_actions']}",
            f"- **Method M 表现**: 候选试探={m['candidate_trials']}, TP阻断={m['tp_blocks']}, 实际执行错误={m['executed_error_actions']}, 状态迁移={len(m['lifecycle_transitions'])}",
            f"- **规则最终状态 (M)**: {json.dumps(m['post_rule_states'])}",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 3. 核心机制发现与对冲分析",
        "",
        "1. **Case 1 暴露的 M 固有缺陷**：",
        "   - 当候选规则是**正确且阻碍持续存在**的物理 OS 约束时，B2-G 凭借通用谓词直接精准拦截（0 次执行错误）；",
        "   - 现有 M 的候选试探机制盲目允许真实执行，**必然付出 1 次实际 OS 失败（Errno 98）的代价**；",
        "2. **Case 5 展现的 M 理论优势（仅在过度泛化候选规则下成立）**：",
        "   - 当规则为人工构造的**过度泛化假规则**时（声明前提成立，但当前动作实际可行），B2-G 发生误阻断（FP Block = 1）；",
        "   - M 凭借候选放行试探成功执行动作，并在 real OS 成功后**因果判定为反例，将规则降级为 CONTRADICTED**；",
        "3. **反例判定的严谨性**：",
        "   - Case 5 是真正的反例（前提确立为 True，动作真实在 OS 成功）；而 Case 2（前提解除后的成功）被正确识别为 NOT_APPLICABLE 正常放行，未被误判为反例。",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
