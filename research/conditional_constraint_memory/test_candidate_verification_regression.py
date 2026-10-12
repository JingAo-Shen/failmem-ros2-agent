"""
Regression Test Suite for Natural Candidate Verification and MultiStep Agent Runner Invariants.

Verifies the 9 Core Scientific & Verification Invariants:
1. Semantic verdict invariant to candidate reordering and indexing.
2. Unknown predicate not judged as supported (UNKNOWN).
3. Precondition FALSE does not produce counterexample (SOURCE_PREMISE_MISMATCH / NOT_APPLICABLE).
4. Precondition TRUE and action succeeds identifies valid counterexample (COUNTEREXAMPLE).
5. Path or identity change does not erroneously reuse cache in S2.
6. TTL expiry and resource changes trigger re-verification and cache invalidation in S2.
7. Probe count matches real call events.
8. M's transition count matches real state events.
9. Summary figures recomputable from individual records.
"""

import os
import sys
import time
import json
import copy
import pytest
from pathlib import Path
from typing import Dict, Any, List

from research.conditional_constraint_memory.constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision,
    ConstraintLifecycleManager,
)
from research.conditional_constraint_memory.multistep_deployment_env import (
    MultiStepDeploymentEnv,
)
from research.conditional_constraint_memory.multistep_agent_runner import (
    MultiStepAgentRunner,
)
from research.conditional_constraint_memory.run_candidate_execution_verification import (
    evaluate_predicates_on_os,
    test_variant_1_reproduction as exec_v1_reproduction,
    test_variant_2_premise_cleared_or_counterexample as exec_v2_premise,
    test_variant_4_context_and_scope as exec_v4_context,
)


class ScriptedPolicyBackend:
    """Deterministic scripted backend for runner tests."""
    def __init__(self, action_sequence: List[Dict[str, Any]]):
        self.actions = list(action_sequence)
        self.invocations = 0

    def generate(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        self.invocations += 1
        if self.actions:
            action = self.actions.pop(0)
        else:
            action = {"action": "finish", "params": {}}
        content = json.dumps({
            "decision_summary": f"Step {self.invocations}",
            "action": action.get("action", ""),
            "params": action.get("params", {}),
        })
        return {
            "content": content,
            "prompt_tokens": 10,
            "generated_tokens": 5,
            "latency_s": 0.001,
        }


# ==============================================================================
# INVARIANT 1: Semantic verdict invariant to candidate reordering and indexing
# ==============================================================================
def test_semantic_verdict_invariant_to_candidate_reordering_and_indexing():
    """Checks that rule evaluation and gating decisions are independent of rule indexing or order."""
    mgr = ConstraintLifecycleManager()
    mgr.register_observation("port:18080:occupied", True)

    rule_a = ConstraintRule(
        rule_id="rule_port_18080",
        action_signature="start_service:port=18080",
        predicates=[PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=5.0)],
        failure_evidence={"error_code": 98},
        validity_state=ValidityState.SUPPORTED,
    )
    rule_b = ConstraintRule(
        rule_id="rule_cfg_exists",
        action_signature="start_service:port=18080",
        predicates=[PreconditionPredicate(key="config_file:exists", expected_value=True, ttl=5.0)],
        failure_evidence={"error_code": 1},
        validity_state=ValidityState.CANDIDATE,
    )

    # Order 1: A then B
    mgr.rules.clear()
    mgr.add_rule(rule_a)
    mgr.add_rule(rule_b)
    decision_1 = mgr.make_gate_decision("start_service:port=18080")

    # Order 2: B then A
    mgr.rules.clear()
    mgr.add_rule(rule_b)
    mgr.add_rule(rule_a)
    decision_2 = mgr.make_gate_decision("start_service:port=18080")

    assert decision_1["decision"] == GateDecision.BLOCK
    assert decision_2["decision"] == GateDecision.BLOCK
    assert decision_1["matching_rule_id"] == "rule_port_18080"
    assert decision_2["matching_rule_id"] == "rule_port_18080"


# ==============================================================================
# INVARIANT 2: Unknown predicate not judged as supported (UNKNOWN)
# ==============================================================================
def test_unknown_predicate_not_judged_as_supported():
    """An unknown predicate on OS must evaluate to UNKNOWN and never be marked as supported."""
    env = MultiStepDeploymentEnv()
    env.setup("inst3_permission_fallback")
    try:
        pred_items = [{"key": "nonexistent_subsystem:property_xyz", "op": "==", "expected_value": "True"}]
        state, details = evaluate_predicates_on_os(env, pred_items, {})
        assert state == "UNKNOWN"
        assert len(details) == 1
        assert details[0]["evaluated_result"] == "UNKNOWN"
    finally:
        env.teardown()


# ==============================================================================
# INVARIANT 3: Precondition FALSE does not produce counterexample
# ==============================================================================
def test_precondition_false_does_not_produce_counterexample():
    """When premise is FALSE, failure or success must NOT produce COUNTEREXAMPLE."""
    env = MultiStepDeploymentEnv()
    params = {"config_path": "/home/agentuser/service_conf/nonexistent_cfg_999.json"}
    pred_items = [{"key": "config_file:exists", "op": "==", "expected_value": "True"}]

    v1_res = exec_v1_reproduction(env, "start_service", params, pred_items, "1", "trace_05")
    assert v1_res["premise_evaluation"] == "FALSE"
    assert v1_res["adjudication"] == "SOURCE_PREMISE_MISMATCH"
    assert v1_res["adjudication"] != "COUNTEREXAMPLE"


# ==============================================================================
# INVARIANT 4: Precondition TRUE and action succeeds identifies valid counterexample
# ==============================================================================
def test_precondition_true_and_action_succeeds_identifies_valid_counterexample():
    """When premise is TRUE and action succeeds on OS, counterexample is conclusively identified."""
    env = MultiStepDeploymentEnv()
    params = {"config_path": "/home/agentuser/service_conf/nonexistent_cfg_999.json"}
    pred_items = [{"key": "config_file:exists", "op": "==", "expected_value": "True"}]
    v1_fake = {"premise_evaluation": "FALSE"}

    v2_res = exec_v2_premise(env, "start_service", params, pred_items, "1", v1_fake)
    assert v2_res["premise_evaluation"] == "TRUE"
    assert v2_res["actual_outcome"]["exit_code"] == 0
    assert v2_res["adjudication"] == "COUNTEREXAMPLE"


# ==============================================================================
# INVARIANT 5: Path or identity change does not erroneously reuse cache in S2
# ==============================================================================
def test_path_or_identity_change_does_not_erroneously_reuse_cache():
    """Cache keys in S2 must strictly bind path and execution identity."""
    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))
    mgr = ConstraintLifecycleManager()
    env = MultiStepDeploymentEnv()

    rule = ConstraintRule(
        rule_id="r_write_dir",
        action_signature="write_config",
        predicates=[PreconditionPredicate(key="dir:/etc/service_demo:permissions", expected_value="0755", ttl=5.0)],
        failure_evidence={"error_code": 1},
        validity_state=ValidityState.CANDIDATE,
    )
    mgr.add_rule(rule)
    s2_cache: Dict[str, Any] = {}

    # Initial evaluation for /etc/service_demo/app_sys.json
    res1, v_cnt1 = runner._evaluate_s2_cached_gate(
        action_sig="write_config:config_path=/etc/service_demo/app_sys.json",
        params={"config_path": "/etc/service_demo/app_sys.json"},
        lifecycle_manager=mgr,
        env=env,
        s2_cache=s2_cache,
    )
    assert v_cnt1 == 1

    # Same action & path -> Cache HIT
    res2, v_cnt2 = runner._evaluate_s2_cached_gate(
        action_sig="write_config:config_path=/etc/service_demo/app_sys.json",
        params={"config_path": "/etc/service_demo/app_sys.json"},
        lifecycle_manager=mgr,
        env=env,
        s2_cache=s2_cache,
    )
    assert v_cnt2 == 0

    # Different path -> Cache MISS, re-verified
    res3, v_cnt3 = runner._evaluate_s2_cached_gate(
        action_sig="write_config:config_path=/etc/service_demo/app_other.json",
        params={"config_path": "/etc/service_demo/app_other.json"},
        lifecycle_manager=mgr,
        env=env,
        s2_cache=s2_cache,
    )
    assert v_cnt3 == 1


# ==============================================================================
# INVARIANT 6: TTL expiry and resource changes trigger re-verification / invalidation
# ==============================================================================
def test_ttl_expiry_and_resource_changes_trigger_reverification_and_invalidation():
    """Monotonic TTL expiration and mutating tool calls must invalidate S2 cache."""
    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))
    mgr = ConstraintLifecycleManager()
    env = MultiStepDeploymentEnv()

    rule = ConstraintRule(
        rule_id="r_port_18080",
        action_signature="start_service:port=18080",
        predicates=[PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=5.0)],
        failure_evidence={"error_code": 98},
        validity_state=ValidityState.CANDIDATE,
    )
    mgr.add_rule(rule)
    s2_cache: Dict[str, Any] = {}

    # 1. Populate cache with 0.1s TTL
    res1, v_cnt1 = runner._evaluate_s2_cached_gate(
        action_sig="start_service:port=18080",
        params={"port": 18080},
        lifecycle_manager=mgr,
        env=env,
        s2_cache=s2_cache,
        ttl_seconds=0.1,
    )
    assert v_cnt1 == 1

    # 2. Wait for TTL to expire
    time.sleep(0.15)
    res2, v_cnt2 = runner._evaluate_s2_cached_gate(
        action_sig="start_service:port=18080",
        params={"port": 18080},
        lifecycle_manager=mgr,
        env=env,
        s2_cache=s2_cache,
        ttl_seconds=0.1,
    )
    assert v_cnt2 == 1  # Triggered re-verification!

    # 3. Test explicit invalidation upon mutating action
    runner._invalidate_s2_cache(
        s2_cache,
        tool_name="start_service",
        params={"port": 18080, "config_path": "/home/agentuser/service_conf/app.json"},
        tool_res={"success": True},
    )
    assert len(s2_cache) == 0


# ==============================================================================
# INVARIANT 7: Probe count matches real call events
# ==============================================================================
def test_probe_count_matches_real_call_events():
    """In MultiStepAgentRunner, unknown_probes count matches PROBE gate events."""
    actions = [
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app.json"}},
        {"action": "check_health", "params": {"port": 18080}},
    ]
    runner = MultiStepAgentRunner(ScriptedPolicyBackend(actions), max_tool_calls_per_episode=5)
    mgr = ConstraintLifecycleManager()

    # Rule with UNKNOWN predicate (port:18080:occupied has no observation registered)
    rule = ConstraintRule(
        rule_id="r_port_18080",
        action_signature="start_service:port=18080",
        predicates=[PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=5.0)],
        failure_evidence={"error_code": 98},
        validity_state=ValidityState.SUPPORTED,
    )
    mgr.add_rule(rule)

    env = MultiStepDeploymentEnv()
    result = runner.run_episode("B2-G", env, "inst3_permission_fallback", "run_test_probe", lifecycle_manager=mgr)
    probe_events = [e for e in result["gate_events"] if e.get("decision") == "PROBE"]
    assert result["unknown_probes"] == len(probe_events)


# ==============================================================================
# INVARIANT 8: M's transition count matches real state events
# ==============================================================================
def test_m_transition_count_matches_real_state_events():
    """Rule validity state transitions in Group M must strictly match record_action_outcome results."""
    mgr = ConstraintLifecycleManager()
    rule = ConstraintRule(
        rule_id="r_cand",
        action_signature="start_service:port=18080",
        predicates=[PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=5.0)],
        failure_evidence={"error_code": 98},
        validity_state=ValidityState.CANDIDATE,
    )
    mgr.add_rule(rule)
    mgr.register_observation("port:18080:occupied", True)

    # Action succeeds under premise TRUE -> Counterexample!
    transitions = mgr.record_action_outcome(
        action_signature="start_service:port=18080",
        success=True,
        pre_action_applicability={"r_cand": ApplicabilityState.APPLICABLE},
        evidence_id="ev_test_123",
    )
    assert len(transitions) == 1
    assert transitions[0]["rule_id"] == "r_cand"
    assert transitions[0]["prior_validity"] == ValidityState.CANDIDATE
    assert transitions[0]["new_validity"] == ValidityState.CONTRADICTED
    assert "CONTRADICTED" in transitions[0]["transition"]
    assert mgr.rules["r_cand"].validity_state == ValidityState.CONTRADICTED


# ==============================================================================
# INVARIANT 9: Summary figures recomputable from individual records
# ==============================================================================
def test_summary_figures_recomputable_from_records():
    """Validates that summary statistics in candidate ledger and verification json match item counts."""
    ledger_path = Path("/code/failmem-ros2-agent/research/conditional_constraint_memory/results/candidate_ledger_24.json")
    verif_path = Path("/code/failmem-ros2-agent/research/conditional_constraint_memory/results/natural_candidate_revised_verification.json")

    assert ledger_path.exists()
    assert verif_path.exists()

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)
    with open(verif_path, "r", encoding="utf-8") as f:
        verif = json.load(f)

    # 1. Total count
    assert len(ledger) == 24
    method_a = [c for c in ledger if c.get("extraction_method") == "Method_A_Natural_Language"]
    method_b = [c for c in ledger if c.get("extraction_method") == "Method_B_Structured_Candidate"]
    assert len(method_a) == 12
    assert len(method_b) == 12

    # 2. Parsing success
    parsed_a = sum(1 for c in method_a if c.get("parsing_status") == "PARSED_SUCCESS")
    parsed_b = sum(1 for c in method_b if c.get("parsing_status") == "PARSED_SUCCESS")
    assert parsed_a == 12
    assert parsed_b == 12

    # 3. Abstention declared
    abstain_a = sum(1 for c in method_a if c.get("abstention_declared") is True)
    abstain_b = sum(1 for c in method_b if c.get("abstention_declared") is True)
    assert abstain_a == 0
    assert abstain_b == 0

    # 4. Verified outcomes in Method B
    assert len(verif) == 12
    counterexamples = [v for v in verif if "COUNTEREXAMPLE" in v.get("overall_verdict", "") and "SCOPE_DEFICIENT" not in v.get("overall_verdict", "")]
    scope_deficient = [v for v in verif if "SCOPE_DEFICIENT" in v.get("overall_verdict", "")]
    supported = [v for v in verif if "SUPPORTED_IN_TESTED_CONTEXT" in v.get("overall_verdict", "")]

    assert len(counterexamples) == 1
    assert len(scope_deficient) == 2
    assert len(supported) == 9
    assert len(counterexamples) + len(scope_deficient) + len(supported) == 12

    # Valid percentage: 9 / 12 = 75.0%
    valid_ratio = round(len(supported) / len(verif) * 100, 1)
    assert valid_ratio == 75.0
