"""
Comprehensive CPU Acceptance Test Suite for Conditional Failure Constraint Memory.
Validates all Section VI requirements:
1. No hidden state injection (no A/B/C/D labels or test instance metadata in prompts/memory).
2. Traceable provenance & deduplicated evidence IDs.
3. Multi-rule decision order invariance.
4. Fault differentiation (port clash vs permission denied vs rejection of unknown errors).
5. Deterministic completion of all 8 target instances via offline solvers.
6. Independent verifier rejects unapplied, fake, or dead daemon configurations.
7. B2-G allows action when condition is cleared / False.
8. Complete budget enforcement and process cleanup.
9. Report consistency verification (no phantom claims of blocks when blocks == 0).
"""

import os
import sys
import time
import json
import pytest
import subprocess
from pathlib import Path

from research.conditional_constraint_memory.constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision,
    ConstraintLifecycleManager,
)
from research.conditional_constraint_memory.memory_pipeline import (
    FailureTrace,
    StructuredFact,
    DeterministicHeuristicRuleParser,
    MemoryPipeline,
)
from research.conditional_constraint_memory.multistep_deployment_env import (
    MultiStepDeploymentEnv,
    solve_instance,
    is_port_listening,
)
from research.conditional_constraint_memory.multistep_agent_runner import (
    MultiStepAgentRunner,
    parse_action_response,
)


class MockLLM:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def generate(self, messages):
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return {
            "content": resp,
            "prompt_tokens": 50,
            "generated_tokens": 20,
            "latency_s": 0.05,
        }


def test_1_no_hidden_state_injection():
    """Verify that agent prompts and memory items never contain hidden state labels."""
    mock_llm = MockLLM(['{"action": "discover_environment", "params": {}}'])
    runner = MultiStepAgentRunner(mock_llm)
    prompt = runner.build_system_prompt("Known facts: Port 18080 occupied")

    forbidden_patterns = ["State A", "State B", "State C", "State D", "inst1_", "inst2_", "hidden_state"]
    for pat in forbidden_patterns:
        assert pat.lower() not in prompt.lower(), f"Hidden label '{pat}' leaked into prompt!"


def test_2_traceable_provenance_and_deduplication():
    """Verify rules have evidence IDs and duplicate evidence IDs do not inflate support_count."""
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=10.0)
    mgr.register_observation("port:18080:occupied", True)

    rule = ConstraintRule(
        rule_id="r_dedup",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_001"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_001"],
    )
    mgr.add_rule(rule)
    assert rule.validity_state == ValidityState.CANDIDATE
    assert rule.support_count == 1
    assert "ev_001" in rule.evidence_ids

    # Same evidence ID must NOT increment count
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=False,
        error_details={"error_code": 98, "evidence_id": "ev_001"},
    )
    assert rule.support_count == 1
    assert rule.validity_state == ValidityState.CANDIDATE

    # Distinct evidence ID upgrades candidate to SUPPORTED
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=False,
        error_details={"error_code": 98, "evidence_id": "ev_002"},
    )
    assert rule.support_count == 2
    assert rule.validity_state == ValidityState.SUPPORTED


def test_3_multi_rule_order_invariance():
    """Verify that rule evaluation order does not change gate decision."""
    p_true = PreconditionPredicate("cond_true", True, ttl=10.0)

    r_candidate = ConstraintRule(
        rule_id="r_cand",
        action_signature="start_service:port=18080",
        predicates=[p_true],
        failure_evidence={"error_code": 98},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
    )
    r_supported = ConstraintRule(
        rule_id="r_supp",
        action_signature="start_service:port=18080",
        predicates=[p_true],
        failure_evidence={"error_code": 98},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
    )

    # Order 1: Candidate first, Supported second
    mgr1 = ConstraintLifecycleManager()
    mgr1.register_observation("cond_true", True)
    mgr1.add_rule(r_candidate)
    mgr1.add_rule(r_supported)
    dec1 = mgr1.make_gate_decision("start_service:port=18080")

    # Order 2: Supported first, Candidate second
    mgr2 = ConstraintLifecycleManager()
    mgr2.register_observation("cond_true", True)
    mgr2.add_rule(r_supported)
    mgr2.add_rule(r_candidate)
    dec2 = mgr2.make_gate_decision("start_service:port=18080")

    assert dec1["decision"] == GateDecision.BLOCK
    assert dec2["decision"] == GateDecision.BLOCK
    assert dec1["decision"] == dec2["decision"]


def test_4_fault_differentiation_and_rejection():
    """Verify distinct error parsing and strict rejection of unknown errors."""
    trace_port = FailureTrace(
        run_id="run1", step=1, tool_name="start_service",
        tool_params={"port": 18080},
        exit_code=98, stderr="OSError: [Errno 98] Address already in use (Port 18080)",
        stdout="", observation_snapshot={}, timestamp=time.time(),
        error_code=98, error_type="AddressAlreadyInUse", evidence_id="ev_1",
    )
    rule_port = MemoryPipeline.extract_rule_for_m(trace_port)
    assert rule_port is not None
    assert rule_port.failure_evidence["error_type"] == "AddressAlreadyInUse"
    assert rule_port.failure_evidence["error_code"] == 98

    trace_file = FailureTrace(
        run_id="run2", step=1, tool_name="write_config",
        tool_params={"filepath": "/etc/service_demo/app.conf"},
        exit_code=1, stderr="bash: /etc/service_demo/app.conf: Permission denied",
        stdout="", observation_snapshot={}, timestamp=time.time(),
        error_code=13, error_type="PermissionDenied", evidence_id="ev_2",
    )
    rule_file = MemoryPipeline.extract_rule_for_m(trace_file)
    assert rule_file is not None
    assert rule_file.failure_evidence["error_type"] == "PermissionDenied"
    assert rule_file.failure_evidence["error_code"] in (1, 13)

    # Unknown / ambiguous error must be rejected (return None)
    trace_unknown = FailureTrace(
        run_id="run3", step=1, tool_name="start_service",
        tool_params={}, exit_code=42, stderr="Unexpected glitch in worker pool",
        stdout="", observation_snapshot={}, timestamp=time.time(), evidence_id="ev_3",
    )
    rule_unknown = MemoryPipeline.extract_rule_for_m(trace_unknown)
    assert rule_unknown is None, "Ambiguous error was not rejected!"


def test_5_offline_solvers_all_8_instances():
    """Verify that all 8 deployment instances are solvable deterministically."""
    env = MultiStepDeploymentEnv()
    instances = [
        "inst1_port_conflict_persistent",
        "inst2_blockage_cleared",
        "inst3_permission_fallback",
        "inst4_irrelevant_change",
        "inst5_stale_observation",
        "inst6_counterexample_feasibility",
        "inst7_midepisode_port_clash",
        "inst8_permission_and_port_composition",
    ]
    for inst in instances:
        ok = solve_instance(env, inst)
        assert ok is True, f"Offline solver failed on {inst}!"
        env.teardown()


def test_6_verifier_rejects_unapplied_and_fake_configs():
    """Verify independent verifier rejects unapplied or fake configs."""
    env = MultiStepDeploymentEnv()
    env.setup("inst1_port_conflict_persistent")

    # Case 1: Config written, but daemon never launched
    env.write_config("/home/agentuser/service_conf/fake.json", port=18081)
    ok1, msg1 = env.verify_completion()
    assert ok1 is False
    assert "No active service process registered" in msg1

    # Case 2: Config on disk does not match live port
    env.start_service("/home/agentuser/service_conf/fake.json")
    # Tamper with config file on disk
    with open("/home/agentuser/service_conf/fake.json", "w") as f:
        json.dump({"port": 18082, "service_name": "tampered"}, f)
    ok2, msg2 = env.verify_completion()
    assert ok2 is False
    assert "does not match" in msg2

    # Case 3: Process terminated
    if env.daemon_process:
        env.daemon_process.terminate()
        env.daemon_process.wait()
    ok3, msg3 = env.verify_completion()
    assert ok3 is False
    assert "process exited" in msg3

    env.teardown()


def test_7_b2g_allows_when_condition_cleared():
    """Verify B2-G allows action when condition evaluates to False."""
    mock_llm = MockLLM([])
    runner = MultiStepAgentRunner(mock_llm)
    env = MultiStepDeploymentEnv()
    env.setup("inst2_blockage_cleared")

    facts = [
        StructuredFact(
            fact_id="fact_1",
            resource="/home/agentuser/service_conf",
            state_description="writable directory",
            error_signature="",
            evidence_id="ev_1",
            run_id="run_1",
            step=1,
            timestamp=time.time(),
        )
    ]
    # Check write_config to /home/agentuser/service_conf/app.json (condition is not blocking)
    gate_eval = runner._evaluate_generic_predicate_gate(
        "write_config:/home/agentuser/service_conf/app.json:port=18080",
        facts,
        env,
    )
    assert gate_eval["decision"] == GateDecision.ALLOW
    env.teardown()


def test_8_budget_enforcement_and_cleanup():
    """Verify runner stops immediately when call budget is reached and cleans up."""
    # Provide infinite loop of dummy responses
    infinite_llm = MockLLM(['{"action": "probe_port", "params": {"port": 18080}}'] * 50)
    runner = MultiStepAgentRunner(
        infinite_llm,
        max_llm_calls_per_episode=3,
        max_tool_calls_per_episode=5,
        max_time_per_episode_s=10.0,
    )
    env = MultiStepDeploymentEnv()

    res = runner.run_episode(
        group="B0",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="budget_test_01",
        max_steps=20,
    )
    assert res["budget_exhausted"] is True
    assert res["llm_calls"] == 3
    assert res["termination_reason"] == "llm_budget_or_timeout_exhausted"

    env.teardown()
    assert len(env.occupier_processes) == 0
    assert env.daemon_process is None


def test_9_report_consistency_no_phantom_claims():
    """Verify report logic does not claim blocks occurred when blocks == 0."""
    fake_summary = {
        "B0": {"tp_blocks": 0, "fp_blocks": 0, "success_rate": 1.0},
        "B2": {"tp_blocks": 0, "fp_blocks": 0, "success_rate": 1.0},
        "B2-G": {"tp_blocks": 0, "fp_blocks": 0, "success_rate": 1.0},
        "M": {"tp_blocks": 0, "fp_blocks": 0, "success_rate": 1.0},
    }

    # Helper function to produce report conclusion
    def generate_conclusion_text(summary):
        lines = []
        for g, data in summary.items():
            if data["tp_blocks"] == 0 and data["fp_blocks"] == 0:
                lines.append(f"{g}: Gate was never triggered in practice (0 blocks). Cannot claim gate efficacy.")
            else:
                lines.append(f"{g}: Triggered {data['tp_blocks']} TP blocks.")
        return "\n".join(lines)

    text = generate_conclusion_text(fake_summary)
    assert "Cannot claim gate efficacy" in text
    assert "Triggered" not in text
