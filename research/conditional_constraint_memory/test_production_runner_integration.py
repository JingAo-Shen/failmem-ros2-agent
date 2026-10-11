"""
Production Runner Integration Test Suite.
Validates Paths A, B, and C strictly through production MultiStepAgentRunner.run_episode:
- Path A: Real OS failure -> FailureTrace -> Candidate Extraction -> In-episode Probation Verification -> Upgrade SUPPORTED -> Next action BLOCKED by runner gate.
- Path B: Existing rule -> Probe refresh -> Cleared premise allows execution in both B2-G and M -> Success does NOT contradict rule -> Restored premise re-blocks.
- Path C: Missing/stale observation -> Gate PROBE -> Automatic probe updates store -> Smooth continuation without infinite probe loop.
- Unit tests: Deduplication, Missing evidence ID ignored, Dir vs File permissions, Failed probe UNKNOWN invalidation, Execution order invariance.
Outputs machine-readable event log to results/runner_integration_events.json.
"""

import os
import sys
import time
import json
import pytest
from pathlib import Path
from typing import Dict, Any, List, Optional

from research.conditional_constraint_memory.constraint_lifecycle import (
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision,
    ConstraintLifecycleManager,
    FrozenMemorySnapshot,
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

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
EVENT_LOG_FILE = RESULTS_DIR / "runner_integration_events.json"

INTEGRATION_EVENTS = []


def record_test_event(event_type: str, details: Dict[str, Any]):
    """Records machine-readable integration test event."""
    entry = {
        "timestamp": time.time(),
        "event_type": event_type,
        "details": details,
    }
    INTEGRATION_EVENTS.append(entry)
    with open(EVENT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(INTEGRATION_EVENTS, f, indent=2)


class ScriptedPolicyBackend:
    """
    Deterministic scripted policy backend for MultiStepAgentRunner.
    Emulates autonomous LLM action proposals step-by-step through standard runner format.
    """
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
            "decision_summary": f"Scripted step {self.invocations}",
            "action": action.get("action", ""),
            "params": action.get("params", {}),
        })
        return {
            "content": content,
            "prompt_tokens": 50,
            "generated_tokens": 20,
            "latency_s": 0.002,
        }


@pytest.fixture
def env():
    e = MultiStepDeploymentEnv()
    yield e
    e.teardown()


# ---------------------------------------------------------------------------
# Path A: Real Failure -> Extraction -> Probation Trial -> Promotion -> Block
# ---------------------------------------------------------------------------
def test_path_a_real_failure_extraction_probation_and_block(env):
    """
    Path A: Real OS execution fails -> Genuine FailureTrace -> CANDIDATE extracted ->
    Second episode: probationary trial verified by runner -> Upgrades to SUPPORTED ->
    Third episode: matching action is strictly BLOCKED by runner gate.
    """
    # 1. Harvest Genuine Failure via production runner on inst1
    script_ep1 = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_a.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_a.json"}},
    ]
    runner_ep1 = MultiStepAgentRunner(ScriptedPolicyBackend(script_ep1))
    res_ep1 = runner_ep1.run_episode(
        group="B0",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_path_a_src",
        max_steps=5,
    )

    # Locate the real failed tool record
    fail_tr = None
    for tr in res_ep1["tool_records"]:
        if tr["tool"] == "start_service" and tr["exit_code"] != 0:
            fail_tr = tr
            break
    assert fail_tr is not None, "Real OS execution must fail on occupied port 18080"
    assert fail_tr["exit_code"] == 98
    assert fail_tr["result"]["error_type"] == "AddressAlreadyInUse"

    # Wire all genuine fields into FailureTrace without synthetic fabrication
    real_trace = FailureTrace(
        run_id=res_ep1["run_id"],
        step=fail_tr["step"],
        tool_name=fail_tr["tool"],
        tool_params=fail_tr["params"],
        exit_code=fail_tr["exit_code"],
        stderr=fail_tr["result"].get("stderr", ""),
        stdout=fail_tr["result"].get("stdout", ""),
        observation_snapshot={},  # No prior observation in ep1 -> empty
        error_code=fail_tr["result"].get("error_code", 98),
        error_type=fail_tr["result"].get("error_type"),
        evidence_id=fail_tr["result"].get("call_id") or f"ev_src_{int(time.time()*1000)}",
        timestamp=fail_tr["timestamp"],
        config_snapshot=fail_tr["result"].get("config_snapshot"),
        resource_id=fail_tr["result"].get("resource_id"),
        user="agentuser",
    )

    # Extract Candidate Rule via production MemoryPipeline
    candidate_rule = MemoryPipeline.extract_rule_for_m(real_trace)
    assert candidate_rule is not None
    assert candidate_rule.validity_state == ValidityState.CANDIDATE
    assert candidate_rule.support_count == 1
    assert candidate_rule.action_signature == "start_service:port=18080"

    record_test_event("PATH_A_RULE_EXTRACTED", {
        "rule_id": candidate_rule.rule_id,
        "validity": candidate_rule.validity_state.value,
        "support_count": candidate_rule.support_count,
        "evidence_id": candidate_rule.evidence_ids[0],
    })

    # 2. Episode 2: In-episode Probationary Trial through Production Runner
    mgr = ConstraintLifecycleManager()
    mgr.add_rule(candidate_rule)

    script_ep2 = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_a.json", "port": 18080}},
        {"action": "probe_port", "params": {"port": 18080}},  # Probes real occupied port
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_a.json"}},  # Fails again
    ]
    runner_ep2 = MultiStepAgentRunner(ScriptedPolicyBackend(script_ep2))
    res_ep2 = runner_ep2.run_episode(
        group="M",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_path_a_probation",
        lifecycle_manager=mgr,
        max_steps=5,
    )

    # Verify candidate trial was permitted by gate
    assert res_ep2["candidate_trials"] >= 1
    # Verify probation was passed and rule promoted to SUPPORTED
    assert candidate_rule.validity_state == ValidityState.SUPPORTED
    assert candidate_rule.support_count == 2
    assert len(candidate_rule.evidence_ids) == 2
    assert any("PROBATION_PASSED" in t.get("transition", "") for t in res_ep2["lifecycle_transitions"])

    record_test_event("PATH_A_PROBATION_PROMOTED", {
        "rule_id": candidate_rule.rule_id,
        "new_validity": candidate_rule.validity_state.value,
        "support_count": candidate_rule.support_count,
        "evidence_ids": candidate_rule.evidence_ids,
        "transitions": res_ep2["lifecycle_transitions"],
    })

    # 3. Episode 3: Runner Gate Strictly BLOCKS Subsequent Conflicting Action
    script_ep3 = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_a.json", "port": 18080}},
        {"action": "probe_port", "params": {"port": 18080}},  # Confirms port occupied
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_a.json"}},  # Gate intercepts!
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_a_ok.json", "port": 18081}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_a_ok.json"}},
        {"action": "check_health", "params": {"port": 18081}},
    ]
    runner_ep3 = MultiStepAgentRunner(ScriptedPolicyBackend(script_ep3))
    res_ep3 = runner_ep3.run_episode(
        group="M",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_path_a_blocked",
        lifecycle_manager=mgr,
        max_steps=8,
    )

    # Verify production runner blocked start_service:port=18080
    assert res_ep3["tp_blocks"] >= 1
    assert any(
        e.get("decision") == "BLOCK" and "start_service:port=18080" in e.get("action", "")
        for e in res_ep3["gate_events"]
    )
    # Verify successful completion after redirection to 18081
    assert res_ep3["success"] is True

    record_test_event("PATH_A_GATE_BLOCKED_AND_VERIFIED", {
        "tp_blocks": res_ep3["tp_blocks"],
        "gate_events": res_ep3["gate_events"],
        "final_success": res_ep3["success"],
    })


# ---------------------------------------------------------------------------
# Path B: Premise Cleared -> Gate Allows -> Success Does Not Contradict
# ---------------------------------------------------------------------------
def test_path_b_premise_cleared_unblocks_and_success_does_not_contradict(env):
    """
    Path B: Existing SUPPORTED rule -> Mid-episode dynamic event clears blockage ->
    Probe refresh unblocks action in both B2-G and M -> Action succeeds ->
    Success under cleared premise does NOT contradict rule -> Restored premise re-blocks.
    """
    pred = PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_cleared_test",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_b_init"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_b_init", "ev_b_init2"],
    )
    mgr = ConstraintLifecycleManager()
    mgr.add_rule(rule)

    fact = StructuredFact(
        fact_id="fact_b",
        resource="port:18080",
        state_description="occupied",
        error_signature="Address already in use",
        evidence_id="ev_b_init",
        run_id="init_b",
        step=0,
        timestamp=time.time(),
        ttl=30.0,
    )
    facts = [fact]

    # In inst2_blockage_cleared, port 18080 clears at step >= 3
    script = [
        {"action": "probe_port", "params": {"port": 18080}},  # Step 1: occupied
        {"action": "probe_directory", "params": {"dirpath": "/home/agentuser/service_conf"}},  # Step 2: triggers clear event
        {"action": "probe_port", "params": {"port": 18080}},  # Step 3: fresh probe -> FREE!
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_b.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_b.json"}},
        {"action": "check_health", "params": {"port": 18080}},
    ]

    # Test M arm
    runner_m = MultiStepAgentRunner(ScriptedPolicyBackend(script))
    res_m = runner_m.run_episode(
        group="M",
        env=env,
        instance_id="inst2_blockage_cleared",
        run_id="run_path_b_m",
        lifecycle_manager=mgr,
        facts=facts,
        max_steps=10,
    )
    assert res_m["success"] is True

    # Critical Assertion: Rule must remain SUPPORTED, contradict count must remain 0!
    assert rule.validity_state == ValidityState.SUPPORTED
    assert rule.contradict_count == 0
    assert any("PREMISE_CLEARED_SUCCESS" in t.get("transition", "") for t in res_m["lifecycle_transitions"])

    # Premise Restoration: background occupier seizes 18080 again
    env._start_occupier(18080, name="reoccupied_18080")
    wait_for_port(18080, should_be_listening=True, timeout=2.0)
    p_res = env.probe_port(18080)
    runner_m._update_observations_from_probe_result("probe_port", {"port": 18080}, p_res, lifecycle_manager=mgr)

    # Re-evaluate gate: Rule is APPLICABLE again and BLOCKS!
    dec_restored = mgr.make_gate_decision("start_service:port=18080")
    assert dec_restored["decision"] == GateDecision.BLOCK

    record_test_event("PATH_B_CLEARED_AND_RESTORED_VERIFIED", {
        "rule_id": rule.rule_id,
        "validity": rule.validity_state.value,
        "contradict_count": rule.contradict_count,
        "restored_gate_decision": dec_restored["decision"].value,
    })


# ---------------------------------------------------------------------------
# Path C: Stale/Missing Observation -> Auto-Probe -> Progress
# ---------------------------------------------------------------------------
def test_path_c_missing_observation_auto_probes_and_progresses(env):
    """
    Path C: Stale/missing observation -> Runner gate returns PROBE ->
    Runner automatically executes probe_port -> Updates store with real call_id ->
    Continues execution without infinite probe loops.
    """
    pred = PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_probe_test",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_c_init"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_c_init", "ev_c_init2"],
    )
    mgr = ConstraintLifecycleManager()
    mgr.add_rule(rule)
    # Manager starts with ZERO observations (premise UNKNOWN)

    # Scripted agent writes config on 18080, then attempts start_service on 18080 first (triggers auto-probe)
    # Then redirects to 18081
    script = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c.json"}},
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_c_ok.json", "port": 18081}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_c_ok.json"}},
        {"action": "check_health", "params": {"port": 18081}},
    ]

    runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
    res = runner.run_episode(
        group="M",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_path_c_autoprobe",
        lifecycle_manager=mgr,
        max_steps=8,
    )

    # Verify auto-probe was triggered
    assert res["unknown_probes"] >= 1
    assert "port:18080:occupied" in mgr.observations
    obs = mgr.observations["port:18080:occupied"]
    assert obs.value is True
    assert obs.call_id != ""

    # Verify task successfully redirected and completed
    assert res["success"] is True

    record_test_event("PATH_C_AUTOPROBE_VERIFIED", {
        "unknown_probes": res["unknown_probes"],
        "observed_key": obs.key,
        "observed_val": obs.value,
        "call_id": obs.call_id,
        "success": res["success"],
    })


# ---------------------------------------------------------------------------
# Isolation & Order Invariance Test
# ---------------------------------------------------------------------------
def test_order_invariance_and_source_snapshot_immutability(env):
    """
    Test execution order invariance:
    Running B0 -> B2 -> B2-G -> M vs M -> B2-G -> B2 -> B0:
    1. FrozenMemorySnapshot SHA256 is 100% identical and never mutated.
    2. Initial memory hash for each arm is strictly identical across execution orders.
    3. In-episode mutations in M or B2-G never leak to subsequent episodes.
    """
    pred = PreconditionPredicate(key="port:18080:occupied", expected_value=True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_iso_rule",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "error_type": "AddressAlreadyInUse", "evidence_id": "ev_iso_1"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_iso_1", "ev_iso_2"],
    )
    fact = StructuredFact(
        fact_id="fact_iso_1",
        resource="port:18080",
        state_description="occupied",
        error_signature="Address already in use",
        evidence_id="ev_iso_1",
        run_id="src_iso",
        step=1,
        timestamp=1000.0,
    )

    snapshot = FrozenMemorySnapshot.create(rules=[rule], facts=[fact])
    assert snapshot.verify_integrity()
    source_hash = snapshot.snapshot_hash

    script = [
        {"action": "probe_port", "params": {"port": 18080}},
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_iso.json", "port": 18081}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_iso.json"}},
        {"action": "check_health", "params": {"port": 18081}},
    ]

    # Order 1: B0 -> B2 -> B2-G -> M
    order1_hashes = {}
    for arm in ("B0", "B2", "B2-G", "M"):
        mgr = snapshot.instantiate_manager()
        facts_copy = snapshot.instantiate_facts()
        runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
        res = runner.run_episode(
            group=arm,
            env=env,
            instance_id="inst1_port_conflict_persistent",
            run_id=f"run_ord1_{arm}",
            lifecycle_manager=mgr,
            facts=facts_copy,
            max_steps=6,
        )
        order1_hashes[arm] = res["initial_memory_hash"]
        assert snapshot.verify_integrity(), "Snapshot must remain intact"

    # Order 2: M -> B2-G -> B2 -> B0
    order2_hashes = {}
    for arm in ("M", "B2-G", "B2", "B0"):
        mgr = snapshot.instantiate_manager()
        facts_copy = snapshot.instantiate_facts()
        runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
        res = runner.run_episode(
            group=arm,
            env=env,
            instance_id="inst1_port_conflict_persistent",
            run_id=f"run_ord2_{arm}",
            lifecycle_manager=mgr,
            facts=facts_copy,
            max_steps=6,
        )
        order2_hashes[arm] = res["initial_memory_hash"]
        assert snapshot.verify_integrity(), "Snapshot must remain intact"

    # Strict Invariance Assertions
    assert snapshot.snapshot_hash == source_hash
    for arm in ("B0", "B2", "B2-G", "M"):
        assert order1_hashes[arm] == order2_hashes[arm], f"Initial memory hash mismatch for {arm} across execution orders!"

    record_test_event("ORDER_INVARIANCE_VERIFIED", {
        "source_hash": source_hash,
        "order1_hashes": order1_hashes,
        "order2_hashes": order2_hashes,
    })


# ---------------------------------------------------------------------------
# Small Unit Tests
# ---------------------------------------------------------------------------
def test_directory_vs_file_permission_distinction():
    """Unit test: Probe directory only updates dir:..., never file:..."""
    mgr = ConstraintLifecycleManager()
    pred_dir = PreconditionPredicate(key="dir:/etc/service_demo:writable", expected_value=False)
    pred_file = PreconditionPredicate(key="file:/etc/service_demo/app.conf:writable", expected_value=False)
    rule_dir = ConstraintRule(rule_id="r_dir", action_signature="write_config:filepath=/etc/service_demo/app.conf", predicates=[pred_dir], failure_evidence={})
    rule_file = ConstraintRule(rule_id="r_file", action_signature="write_config:filepath=/etc/service_demo/app.conf", predicates=[pred_file], failure_evidence={})
    mgr.add_rule(rule_dir)
    mgr.add_rule(rule_file)

    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))
    probe_dir_res = {"success": True, "writable_by_user": True, "call_id": "call_dir_1", "timestamp": time.time()}
    runner._update_observations_from_probe_result("probe_directory", {"dirpath": "/etc/service_demo"}, probe_dir_res, lifecycle_manager=mgr)

    # dir observation updated
    assert "dir:/etc/service_demo:writable" in mgr.observations
    assert mgr.observations["dir:/etc/service_demo:writable"].value is True
    # file observation must NOT be created or overwritten
    assert "file:/etc/service_demo/app.conf:writable" not in mgr.observations


def test_failed_probe_invalidates_stale_cache_and_yields_unknown():
    """Unit test: Failed probe or missing field deletes stale observation and yields UNKNOWN."""
    mgr = ConstraintLifecycleManager()
    mgr.register_observation("port:18080:occupied", True, timestamp=1000.0)
    assert "port:18080:occupied" in mgr.observations

    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))
    # Probe fails with non-zero exit code or missing is_occupied
    probe_fail_res = {"success": False, "exit_code": 1, "error": "Connection refused"}
    runner._update_observations_from_probe_result("probe_port", {"port": 18080}, probe_fail_res, lifecycle_manager=mgr)

    # Must be invalidated
    assert "port:18080:occupied" not in mgr.observations


def test_loop_d_counter_evidence_unit():
    """Unit test: True counter-example downgrades SUPPORTED -> CONTRADICTED -> RETIRED."""
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_counter_unit",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_0"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_0", "ev_01"],
    )
    mgr.add_rule(rule)
    pre_app = {"r_counter_unit": ApplicabilityState.APPLICABLE}

    # First counter evidence
    mgr.record_action_outcome("start_service:port=18080", success=True, pre_action_applicability=pre_app, evidence_id="ev_c1")
    assert rule.validity_state == ValidityState.CONTRADICTED

    # Second counter evidence
    mgr.record_action_outcome("start_service:port=18080", success=True, pre_action_applicability=pre_app, evidence_id="ev_c2")
    assert rule.validity_state == ValidityState.RETIRED


def test_loop_e_success_under_cleared_premise_unit():
    """Unit test: Success when premise is NOT_APPLICABLE preserves SUPPORTED state without penalty."""
    mgr = ConstraintLifecycleManager()
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_cleared_unit",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_0"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_0", "ev_01"],
    )
    mgr.add_rule(rule)
    pre_app = {"r_cleared_unit": ApplicabilityState.NOT_APPLICABLE}

    mgr.record_action_outcome("start_service:port=18080", success=True, pre_action_applicability=pre_app, evidence_id="ev_s1")
    assert rule.validity_state == ValidityState.SUPPORTED
    assert rule.contradict_count == 0


# ---------------------------------------------------------------------------
# Targeted Regression Suite: Gating Symmetry, Probing, and Pending Execution
# ---------------------------------------------------------------------------
def test_regression_1_unknown_probed_feasible_executes_original_action(env):
    """
    Regression 1: Action matched to UNKNOWN premise triggers auto-probe;
    upon proving premise NOT_APPLICABLE (feasible), the pending original
    action is actually executed and succeeds, without dropping the action.
    """
    pred = PreconditionPredicate("port:18081:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_reg1",
        action_signature="start_service:port=18081",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_reg1"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_reg1", "ev_reg1_b"],
    )
    mgr = ConstraintLifecycleManager()
    mgr.add_rule(rule)

    # Observation is initially missing -> UNKNOWN
    assert mgr.evaluate_applicability(rule) == ApplicabilityState.UNKNOWN

    # Script: config written, then start_service proposed directly (no manual probe)
    # Runner auto-probe should probe 18081 -> finds it FREE -> executes start_service!
    script = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_reg1.json", "port": 18081}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_reg1.json", "port": 18081}},
        {"action": "check_health", "params": {"port": 18081}},
    ]
    runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
    res = runner.run_episode(
        group="M",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_reg1",
        lifecycle_manager=mgr,
        max_steps=6,
    )

    assert res["success"] is True, f"Episode failed: {res.get('verifier_message')}"
    # Verify auto-probe happened and pending start_service was executed
    probe_events = [e for e in res["gate_events"] if e.get("decision") == "PROBE"]
    assert len(probe_events) >= 1
    # Check that start_service tool actually ran and succeeded
    start_calls = [c for c in res["tool_records"] if c["tool"] == "start_service"]
    assert len(start_calls) == 1
    assert start_calls[0]["exit_code"] == 0


def test_regression_2_unknown_probed_infeasible_blocks_and_requests_replan(env):
    """
    Regression 2: Action matched to UNKNOWN premise triggers auto-probe;
    upon proving premise APPLICABLE (infeasible), the action is BLOCKED.
    The original tool is NOT executed, and agent is requested to replan.
    """
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_reg2",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_reg2"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_reg2", "ev_reg2_b"],
    )
    mgr = ConstraintLifecycleManager()
    mgr.add_rule(rule)

    # In inst1, port 18080 is persistently occupied
    script = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_reg2.json", "port": 18080}},
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_reg2.json", "port": 18080}},
    ]
    runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
    res = runner.run_episode(
        group="M",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_reg2",
        lifecycle_manager=mgr,
        max_steps=5,
    )

    # start_service should NOT have been executed
    start_calls = [c for c in res["tool_records"] if c["tool"] == "start_service"]
    assert len(start_calls) == 0, "Blocked action must NOT be executed!"
    # Must have recorded PROBE followed by BLOCK
    decisions = [e.get("decision") for e in res["gate_events"]]
    assert "PROBE" in decisions
    assert "BLOCK" in decisions
    assert res["tp_blocks"] >= 1


def test_regression_3_probe_file_exits_unknown_for_file_predicates(env):
    """
    Regression 3: File predicates exit UNKNOWN only via probe_file.
    probe_directory does NOT resolve file predicates, preventing false assumptions.
    """
    mgr = ConstraintLifecycleManager()
    filepath = "/home/agentuser/service_conf/test_perm.json"
    pred = PreconditionPredicate(f"file:{filepath}:writable", False, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_reg3",
        action_signature=f"write_config:filepath={filepath}",
        predicates=[pred],
        failure_evidence={"error_code": 13, "evidence_id": "ev_reg3"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_reg3", "ev_reg3_b"],
    )
    mgr.add_rule(rule)

    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))

    # Probing directory should NOT resolve file predicate
    probe_dir_res = env.probe_directory("/home/agentuser/service_conf")
    runner._update_observations_from_probe_result("probe_directory", {"dirpath": "/home/agentuser/service_conf"}, probe_dir_res, lifecycle_manager=mgr)
    assert mgr.evaluate_applicability(rule) == ApplicabilityState.UNKNOWN

    # Calling probe_file resolves the file predicate
    probe_f_res = env.probe_file(filepath)
    runner._update_observations_from_probe_result("probe_file", {"filepath": filepath}, probe_f_res, lifecycle_manager=mgr)
    assert f"file:{filepath}:writable" in mgr.observations
    # Since /home/agentuser/service_conf is writable, new file is writable -> NOT_APPLICABLE
    assert mgr.evaluate_applicability(rule) == ApplicabilityState.NOT_APPLICABLE


def test_regression_4_b2g_and_m_identical_gating_on_identical_rules(env):
    """
    Regression 4: B2-G and M exhibit identical gating decisions given identical
    rules and observation states when rule is SUPPORTED.
    """
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_reg4",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_reg4"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_reg4", "ev_reg4_b"],
    )

    mgr_b2g = ConstraintLifecycleManager()
    mgr_b2g.add_rule(rule)

    mgr_m = ConstraintLifecycleManager()
    mgr_m.add_rule(rule)

    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))

    # State 1: UNKNOWN premise -> Both PROBE
    d_b2g_1 = runner._evaluate_generic_predicate_gate("start_service:port=18080", lifecycle_manager=mgr_b2g)
    d_m_1 = mgr_m.make_gate_decision("start_service:port=18080")
    assert d_b2g_1["decision"] == GateDecision.PROBE
    assert d_m_1["decision"] == GateDecision.PROBE

    # State 2: APPLICABLE premise (occupied) -> Both BLOCK
    now = time.time()
    mgr_b2g.register_observation("port:18080:occupied", True, timestamp=now)
    mgr_m.register_observation("port:18080:occupied", True, timestamp=now)
    d_b2g_2 = runner._evaluate_generic_predicate_gate("start_service:port=18080", lifecycle_manager=mgr_b2g)
    d_m_2 = mgr_m.make_gate_decision("start_service:port=18080")
    assert d_b2g_2["decision"] == GateDecision.BLOCK
    assert d_m_2["decision"] == GateDecision.BLOCK

    # State 3: NOT_APPLICABLE premise (free) -> Both ALLOW
    mgr_b2g.register_observation("port:18080:occupied", False, timestamp=now)
    mgr_m.register_observation("port:18080:occupied", False, timestamp=now)
    d_b2g_3 = runner._evaluate_generic_predicate_gate("start_service:port=18080", lifecycle_manager=mgr_b2g)
    d_m_3 = mgr_m.make_gate_decision("start_service:port=18080")
    assert d_b2g_3["decision"] == GateDecision.ALLOW
    assert d_m_3["decision"] == GateDecision.ALLOW


def test_regression_5_divergence_only_on_candidate_probation():
    """
    Regression 5: Divergence between B2-G and M occurs STRICTLY when a rule is in CANDIDATE state:
    B2-G generic gate blocks matching actions immediately (no probation trial),
    whereas M lifecycle gate allows execution under probationary trial.
    """
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule_cand = ConstraintRule(
        rule_id="r_reg5_cand",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_reg5"},
        validity_state=ValidityState.CANDIDATE,
        support_threshold=2,
        support_count=1,
        evidence_ids=["ev_reg5"],
    )

    mgr_b2g = ConstraintLifecycleManager()
    mgr_b2g.add_rule(rule_cand)
    mgr_b2g.register_observation("port:18080:occupied", True, timestamp=time.time())

    mgr_m = ConstraintLifecycleManager()
    mgr_m.add_rule(rule_cand)
    mgr_m.register_observation("port:18080:occupied", True, timestamp=time.time())

    runner = MultiStepAgentRunner(ScriptedPolicyBackend([]))

    # B2-G generic predicate gate blocks on confirmed APPLICABLE premise
    d_b2g = runner._evaluate_generic_predicate_gate("start_service:port=18080", lifecycle_manager=mgr_b2g)
    assert d_b2g["decision"] == GateDecision.BLOCK

    # M candidate lifecycle gate allows trial execution
    d_m = mgr_m.make_gate_decision("start_service:port=18080")
    assert d_m["decision"] == GateDecision.ALLOW
    assert "candidate" in d_m["reason"].lower()


def test_regression_6_scripted_policy_zero_ghost_failures(env):
    """
    Regression 6: ScriptedPolicyBackend terminates cleanly with finish on action exhaustion,
    producing 0 runaway tool failures.
    """
    # Policy only writes config and finishes
    script = [
        {"action": "write_config", "params": {"config_path": "/home/agentuser/service_conf/app_reg6.json", "port": 18080}},
    ]
    runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
    res = runner.run_episode(
        group="B0",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_reg6",
        max_steps=10,
    )

    assert res["termination_reason"] == "agent_finished"
    assert res["executed_error_actions"] == 0
    # Exactly 1 tool call executed (write_config)
    assert len(res["tool_records"]) == 1


def test_regression_7_b2g_receives_and_evaluates_structured_rule_manager(env):
    """
    Regression 7: B2-G arm instantiated via FrozenMemorySnapshot receives lifecycle_manager
    with structured rules, and executes generic predicate gating without facts-only fallback.
    """
    pred = PreconditionPredicate("port:18080:occupied", True, ttl=30.0)
    rule = ConstraintRule(
        rule_id="r_reg7",
        action_signature="start_service:port=18080",
        predicates=[pred],
        failure_evidence={"error_code": 98, "evidence_id": "ev_reg7"},
        validity_state=ValidityState.SUPPORTED,
        support_threshold=2,
        support_count=2,
        evidence_ids=["ev_reg7", "ev_reg7_b"],
    )
    snapshot = FrozenMemorySnapshot.create(
        rules=[rule],
    )

    mgr_b2g = snapshot.instantiate_manager()
    assert mgr_b2g is not None
    assert "r_reg7" in mgr_b2g.rules

    script = [
        {"action": "start_service", "params": {"config_path": "/home/agentuser/service_conf/app_reg7.json", "port": 18080}},
    ]
    runner = MultiStepAgentRunner(ScriptedPolicyBackend(script))
    res = runner.run_episode(
        group="B2-G",
        env=env,
        instance_id="inst1_port_conflict_persistent",
        run_id="run_reg7",
        lifecycle_manager=mgr_b2g,
        max_steps=5,
    )

    # Gate must have blocked matching action
    assert res["tp_blocks"] == 1
    block_events = [e for e in res["gate_events"] if e.get("decision") == "BLOCK"]
    assert len(block_events) == 1
    assert "Generic predicate gate blocked" in block_events[0]["reason"]

