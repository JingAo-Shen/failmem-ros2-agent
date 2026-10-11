"""
Closed-Loop CPU Integration Test Suite for Non-Empty Constraint Memory.
Validates Loops A through I with real OS resources (sockets, directories, permissions, processes).
100% CPU execution without any neural model or GPU budget consumption.
"""

import os
import sys
import time
import json
import socket
import pytest
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
    is_port_listening,
    wait_for_port,
)
from research.conditional_constraint_memory.multistep_agent_runner import (
    MultiStepAgentRunner,
)


class DummyLLM:
    def generate(self, messages):
        return {"content": "{}", "prompt_tokens": 10, "generated_tokens": 10, "latency_s": 0.01}


@pytest.fixture
def env():
    e = MultiStepDeploymentEnv()
    yield e
    e.teardown()


def test_loop_a_seeded_rule_blocks_action(env):
    """Loop A: Seed memory rule -> Premise confirmed occupied -> Gate Blocks action."""
    env.setup("inst1_port_conflict_persistent")
    assert is_port_listening(18080) is True

    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate(
        key="port:18080:occupied",
        expected_value=True,
        ttl=30.0,
        resource_type="port",
        resource_path="18080",
        property="occupied",
    )
    rule = ConstraintRule(
        rule_id="rule_seeded_18080",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_seed_1"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_seed_1", "ev_seed_2"],
    )
    mgr.add_rule(rule)

    # Perform probe
    runner = MultiStepAgentRunner(DummyLLM())
    probe_res = env.probe_port(18080)
    runner._update_observations_from_probe_result(
        "probe_port", {"port": 18080}, probe_res, lifecycle_manager=mgr
    )

    # Gate decision must be BLOCK
    dec = mgr.make_gate_decision("start_service:port=18080")
    assert dec["decision"] == GateDecision.BLOCK
    assert "rule_seeded_18080" in dec["matching_rule_id"]


def test_loop_b_precondition_cleared_unblocks_action(env):
    """Loop B: Premise cleared -> Fresh probe -> Gate Unblocks & action succeeds."""
    env.setup("inst2_blockage_cleared")
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate(
        key="port:18080:occupied",
        expected_value=True,
        ttl=30.0,
        resource_type="port",
        resource_path="18080",
        property="occupied",
    )
    rule = ConstraintRule(
        rule_id="rule_18080",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_b1"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_b1", "ev_b2"],
    )
    mgr.add_rule(rule)
    runner = MultiStepAgentRunner(DummyLLM())

    # Step 1: discover
    env.discover_environment()
    # Step 2: probe port 18080 (initially occupied)
    p_occ = env.probe_port(18080)
    assert p_occ["is_occupied"] is True
    runner._update_observations_from_probe_result("probe_port", {"port": 18080}, p_occ, lifecycle_manager=mgr)
    dec_blocked = mgr.make_gate_decision("start_service:port=18080")
    assert dec_blocked["decision"] == GateDecision.BLOCK

    # Step 3: probe directory (triggers dynamic event: blockage cleared!)
    env.probe_directory("/home/agentuser/service_conf")

    # Step 4: fresh probe port 18080 (cleared!)
    p_free = env.probe_port(18080)
    assert p_free["is_occupied"] is False
    runner._update_observations_from_probe_result("probe_port", {"port": 18080}, p_free, lifecycle_manager=mgr)

    # Gate evaluation: applicability is NOT_APPLICABLE -> ALLOW!
    app = mgr.evaluate_applicability(rule)
    assert app == ApplicabilityState.NOT_APPLICABLE
    dec_allowed = mgr.make_gate_decision("start_service:port=18080")
    assert dec_allowed["decision"] == GateDecision.ALLOW

    # Execute action and verify end-to-end success
    conf_path = "/home/agentuser/service_conf/loop_b.json"
    w_res = env.write_config(conf_path, port=18080)
    assert w_res["success"] is True
    s_res = env.start_service(conf_path)
    assert s_res["success"] is True
    ok, msg = env.verify_completion()
    assert ok is True


def test_loop_c_forced_execution_under_matching_premise_reinforces_rule(env):
    """Loop C: Premise occupied -> Forced execution fails with matching error -> Rule support count increments."""
    env.setup("inst1_port_conflict_persistent")
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate(
        key="port:18080:occupied",
        expected_value=True,
        ttl=30.0,
        resource_type="port",
        resource_path="18080",
        property="occupied",
    )
    rule = ConstraintRule(
        rule_id="rule_c",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c1"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_c1", "ev_c2"],
    )
    mgr.add_rule(rule)
    mgr.register_observation("port:18080:occupied", True)

    # Force execution of start_service on occupied port
    conf_path = "/home/agentuser/service_conf/loop_c.json"
    env.write_config(conf_path, port=18080)
    start_res = env.start_service(conf_path)
    assert start_res["success"] is False
    assert start_res["exit_code"] == 98
    assert start_res["error_type"] == "AddressAlreadyInUse"

    # Record outcome with genuine new evidence ID
    pre_app = {rule.rule_id: ApplicabilityState.APPLICABLE}
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=False,
        error_details={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c3"},
        pre_action_applicability=pre_app,
    )
    assert rule.support_count == 3
    assert "ev_c3" in rule.evidence_ids


def test_loop_d_counter_evidence_contradicts_and_retires_rule():
    """Loop D: Premise occupied -> Action succeeds -> True counter-evidence degrades rule to CONTRADICTED -> RETIRED."""
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="rule_d",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_d0"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_d0", "ev_d01"],
    )
    mgr.add_rule(rule)
    mgr.register_observation("port:18080:occupied", True)

    # Action unexpectedly SUCCEEDS while premise is APPLICABLE!
    pre_app = {rule.rule_id: ApplicabilityState.APPLICABLE}
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=True,
        error_details={"evidence_id": "ev_counter_1"},
        pre_action_applicability=pre_app,
    )
    assert rule.validity_state == ValidityState.CONTRADICTED
    assert rule.contradict_count == 1

    # Second counter-evidence retires rule completely
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=True,
        error_details={"evidence_id": "ev_counter_2"},
        pre_action_applicability=pre_app,
    )
    assert rule.validity_state == ValidityState.RETIRED
    assert rule.contradict_count == 2

    # Retired rule cannot block anymore
    dec = mgr.make_gate_decision("start_service:port=18080")
    assert dec["decision"] == GateDecision.ALLOW


def test_loop_e_success_under_cleared_premise_does_not_contradict_rule():
    """Loop E: Premise cleared -> Action succeeds -> NOT_APPLICABLE (does not contradict rule)."""
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="rule_e",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_e0"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_e0", "ev_e01"],
    )
    mgr.add_rule(rule)
    # Port is free -> NOT_APPLICABLE
    mgr.register_observation("port:18080:occupied", False)
    pre_app = {rule.rule_id: mgr.evaluate_applicability(rule)}
    assert pre_app[rule.rule_id] == ApplicabilityState.NOT_APPLICABLE

    # Action succeeds
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=True,
        error_details={"evidence_id": "ev_e_succ"},
        pre_action_applicability=pre_app,
    )
    # Rule validity remains SUPPORTED, contradict_count remains 0!
    assert rule.validity_state == ValidityState.SUPPORTED
    assert rule.contradict_count == 0


def test_loop_f_candidate_probation_trial_and_promotion(env):
    """Loop F: CANDIDATE rule (count=1) -> Probation trial -> Upgrades to SUPPORTED upon reproduced failure."""
    env.setup("inst1_port_conflict_persistent")
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="rule_cand",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_cand_1"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_cand_1"],
    )
    mgr.add_rule(rule)
    mgr.register_observation("port:18080:occupied", True)

    # In CANDIDATE state, make_gate_decision ALLOWs with probation warning
    dec = mgr.make_gate_decision("start_service:port=18080")
    assert dec["decision"] == GateDecision.ALLOW
    assert "probation" in dec["reason"].lower() or "candidate" in dec["reason"].lower()

    # Probation trial executes and fails with real exit code 98
    conf_path = "/home/agentuser/service_conf/loop_f.json"
    env.write_config(conf_path, port=18080)
    start_res = env.start_service(conf_path)
    assert start_res["success"] is False
    assert start_res["exit_code"] == 98

    # Record outcome with new evidence ID
    pre_app = {rule.rule_id: ApplicabilityState.APPLICABLE}
    mgr.record_action_outcome(
        "start_service:port=18080",
        success=False,
        error_details={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_cand_2"},
        pre_action_applicability=pre_app,
    )

    # Promoted to SUPPORTED!
    assert rule.validity_state == ValidityState.SUPPORTED
    assert rule.support_count == 2

    # Next attempt is BLOCKED
    dec2 = mgr.make_gate_decision("start_service:port=18080")
    assert dec2["decision"] == GateDecision.BLOCK


def test_loop_g_ttl_expiration_triggers_probe(env):
    """Loop G: TTL expiration -> Observation UNKNOWN -> Gate triggers active probe."""
    env.setup("inst1_port_conflict_persistent")
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=1.0)
    rule = ConstraintRule(
        rule_id="rule_ttl",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_g"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_g", "ev_g2"],
    )
    mgr.add_rule(rule)

    # Register stale observation (older than TTL 1.0s)
    stale_time = time.time() - 5.0
    mgr.register_observation("port:18080:occupied", True, timestamp=stale_time)

    # Gate decision must be PROBE
    dec = mgr.make_gate_decision("start_service:port=18080")
    assert dec["decision"] == GateDecision.PROBE

    # Probe port now
    runner = MultiStepAgentRunner(DummyLLM())
    probe_res = env.probe_port(18080)
    runner._update_observations_from_probe_result("probe_port", {"port": 18080}, probe_res, lifecycle_manager=mgr)

    # Observation is now fresh -> evaluates to BLOCK
    dec2 = mgr.make_gate_decision("start_service:port=18080")
    assert dec2["decision"] == GateDecision.BLOCK


def test_loop_h_unprivileged_write_permission_denied_and_memory_extraction(env):
    """Loop H: Non-root write permission failure -> Real OS permission denied -> Memory extraction -> Next execution blocked."""
    env.setup("inst3_permission_fallback")

    # Real unprivileged attempt to write into /etc/service_demo (root 0755)
    bad_conf = "/etc/service_demo/app.conf"
    w_res = env.write_config(bad_conf, port=18080)
    assert w_res["success"] is False
    assert w_res["exit_code"] != 0
    assert w_res["error_type"] == "PermissionDenied"
    assert w_res["error_code"] == 13

    # Construct FailureTrace from genuine execution
    trace = FailureTrace(
        run_id="run_h",
        step=1,
        tool_name="write_config",
        tool_params={"config_path": bad_conf, "port": 18080},
        exit_code=w_res["exit_code"],
        stderr=w_res["stderr"],
        stdout=w_res["stdout"],
        observation_snapshot={"file:/etc/service_demo/app.conf:writable": False},
        error_code=w_res["error_code"],
        error_type=w_res["error_type"],
        config_snapshot=w_res.get("config_snapshot"),
        resource_id=w_res.get("resource_id"),
        evidence_id="ev_h_perm",
    )

    # Extract rule without reading disk (enforces CANDIDATE from production pipeline)
    extracted_rule = MemoryPipeline.extract_rule_for_m(trace)
    assert extracted_rule is not None
    assert extracted_rule.validity_state == ValidityState.CANDIDATE
    assert extracted_rule.action_signature == f"write_config:filepath={bad_conf}"
    assert extracted_rule.predicates[0].resource_type == "file"
    assert extracted_rule.predicates[0].expected_value is False

    # Explicit fixture upgrade to SUPPORTED for downstream gate test
    extracted_rule.validity_state = ValidityState.SUPPORTED
    extracted_rule.support_count = 2

    mgr = ConstraintLifecycleManager()
    mgr.add_rule(extracted_rule)
    mgr.register_observation(extracted_rule.predicates[0].key, False)

    # Next attempt is BLOCKED by gate
    dec = mgr.make_gate_decision(extracted_rule.action_signature)
    assert dec["decision"] == GateDecision.BLOCK


def test_loop_i_evidence_deduplication_prevents_ghost_increments():
    """Loop I: Deduplication -> Identical evidence ID does not ghost-increment support count."""
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="rule_dedup",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_same_01"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_same_01"],
    )
    mgr.add_rule(rule)
    mgr.register_observation("port:18080:occupied", True)

    pre_app = {rule.rule_id: ApplicabilityState.APPLICABLE}
    for _ in range(5):
        mgr.record_action_outcome(
            "start_service:port=18080",
            success=False,
            error_details={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_same_01"},
            pre_action_applicability=pre_app,
        )

    # Must NOT have incremented
    assert rule.support_count == 1
    assert rule.validity_state == ValidityState.CANDIDATE
    assert len(rule.evidence_ids) == 1
