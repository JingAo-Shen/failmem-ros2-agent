"""
Unit Test Suite for Constraint Lifecycle Management Module.
Verifies all 6 core invariant behaviors required by engineering review:
1. Conjunction order invariance (False + Unknown evaluated in both directions).
2. CANDIDATE rules allow probationary trials (no hard-blocking).
3. Candidate promotion to SUPPORTED upon replication.
4. Premise cleared success retains SUPPORTED validity (no false contradiction).
5. Premise restored re-activates APPLICABLE and BLOCK gate.
6. Genuine counter-example (success under APPLICABLE) causes CONTRADICTED downgrade.
7. Injectable clock & TTL expiration.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import unittest
from constraint_lifecycle import (
    ConstraintLifecycleManager,
    ConstraintRule,
    PreconditionPredicate,
    ValidityState,
    ApplicabilityState,
    GateDecision
)

class MockClock:
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    def advance(self, seconds: float):
        self.current_time += seconds


class TestConstraintLifecycle(unittest.TestCase):
    def setUp(self):
        self.clock = MockClock(1000.0)
        self.manager = ConstraintLifecycleManager(time_provider=self.clock.time)

    def test_conjunction_order_invariance(self):
        """Test that any fresh False predicate forces NOT_APPLICABLE regardless of iteration order."""
        # Predicate A: observed False
        # Predicate B: unobserved / unknown
        pred_a = PreconditionPredicate(key="pred_false", expected_value=True, ttl=10.0)
        pred_b = PreconditionPredicate(key="pred_unknown", expected_value=True, ttl=10.0)

        self.manager.register_observation("pred_false", False, timestamp=1000.0)

        # Rule 1: [pred_a, pred_b] (False first, then Unknown)
        rule_1 = ConstraintRule(
            rule_id="r1",
            action_signature="act:test",
            predicates=[pred_a, pred_b],
            failure_evidence={"error_code": 1}
        )
        # Rule 2: [pred_b, pred_a] (Unknown first, then False)
        rule_2 = ConstraintRule(
            rule_id="r2",
            action_signature="act:test",
            predicates=[pred_b, pred_a],
            failure_evidence={"error_code": 1}
        )

        app_1 = self.manager.evaluate_applicability(rule_1)
        app_2 = self.manager.evaluate_applicability(rule_2)

        self.assertEqual(app_1, ApplicabilityState.NOT_APPLICABLE, "Order [False, Unknown] must be NOT_APPLICABLE")
        self.assertEqual(app_2, ApplicabilityState.NOT_APPLICABLE, "Order [Unknown, False] must be NOT_APPLICABLE")

    def test_candidate_rule_probationary_trial(self):
        """Test that CANDIDATE rule does not hard-block actions."""
        pred = PreconditionPredicate(key="port_occupied", expected_value=True, ttl=10.0)
        self.manager.register_observation("port_occupied", True, timestamp=1000.0)

        rule = ConstraintRule(
            rule_id="c_cand",
            action_signature="bind_port:18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.CANDIDATE,
            support_threshold=2,
            support_count=1
        )
        self.manager.add_rule(rule)

        decision = self.manager.make_gate_decision("bind_port:18080")
        self.assertEqual(decision["decision"], GateDecision.ALLOW)
        self.assertTrue(decision.get("probationary", False))
        self.assertEqual(decision["validity"], ValidityState.CANDIDATE)
        self.assertEqual(decision["applicability"], ApplicabilityState.APPLICABLE)

    def test_candidate_promotion_to_supported(self):
        """Test that candidate promotes to SUPPORTED upon verified replication and then blocks."""
        pred = PreconditionPredicate(key="port_occupied", expected_value=True, ttl=10.0)
        self.manager.register_observation("port_occupied", True, timestamp=1000.0)

        rule = ConstraintRule(
            rule_id="c_promote",
            action_signature="bind_port:18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.CANDIDATE,
            support_threshold=2,
            support_count=1
        )
        self.manager.add_rule(rule)

        # Before replication: CANDIDATE allows trial
        d1 = self.manager.make_gate_decision("bind_port:18080")
        self.assertEqual(d1["decision"], GateDecision.ALLOW)

        # Action is executed and fails again with matching evidence under APPLICABLE premise
        updates = self.manager.record_action_outcome("bind_port:18080", success=False, error_details={"error_code": 98})
        self.assertEqual(rule.validity_state, ValidityState.SUPPORTED)
        self.assertEqual(rule.support_count, 2)

        # Now: SUPPORTED + APPLICABLE -> BLOCK!
        d2 = self.manager.make_gate_decision("bind_port:18080")
        self.assertEqual(d2["decision"], GateDecision.BLOCK)

    def test_premise_cleared_success_retains_rule(self):
        """Test that action success when premise is NOT_APPLICABLE does NOT contradict rule."""
        pred = PreconditionPredicate(key="port_occupied", expected_value=True, ttl=10.0)
        rule = ConstraintRule(
            rule_id="r_cleared",
            action_signature="bind_port:18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.SUPPORTED,
            support_threshold=2,
            support_count=2
        )
        self.manager.add_rule(rule)

        # Port is cleared (is_occupied=False)
        self.manager.register_observation("port_occupied", False, timestamp=1000.0)
        app = self.manager.evaluate_applicability(rule)
        self.assertEqual(app, ApplicabilityState.NOT_APPLICABLE)

        # Gate allows execution because premise is cleared
        d = self.manager.make_gate_decision("bind_port:18080")
        self.assertEqual(d["decision"], GateDecision.ALLOW)

        # Action succeeds!
        updates = self.manager.record_action_outcome("bind_port:18080", success=True)
        # CRUCIAL INVARIANT: Rule MUST remain SUPPORTED! Contradict count must remain 0!
        self.assertEqual(rule.validity_state, ValidityState.SUPPORTED)
        self.assertEqual(rule.contradict_count, 0)

    def test_premise_restoration_reactivates_block(self):
        """Test that when premise returns to True, rule becomes APPLICABLE and BLOCK again."""
        pred = PreconditionPredicate(key="port_occupied", expected_value=True, ttl=10.0)
        rule = ConstraintRule(
            rule_id="r_restore",
            action_signature="bind_port:18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.SUPPORTED,
            support_threshold=2,
            support_count=2
        )
        self.manager.add_rule(rule)

        # 1. Blocked when True
        self.manager.register_observation("port_occupied", True, timestamp=1000.0)
        self.assertEqual(self.manager.make_gate_decision("bind_port:18080")["decision"], GateDecision.BLOCK)

        # 2. Allowed when False
        self.manager.register_observation("port_occupied", False, timestamp=1001.0)
        self.assertEqual(self.manager.make_gate_decision("bind_port:18080")["decision"], GateDecision.ALLOW)

        # 3. Blocked again when restored to True
        self.manager.register_observation("port_occupied", True, timestamp=1002.0)
        self.assertEqual(self.manager.make_gate_decision("bind_port:18080")["decision"], GateDecision.BLOCK)

    def test_true_counter_example_causes_contradiction(self):
        """Test that success while premise is confirmed APPLICABLE causes CONTRADICTED downgrade."""
        pred = PreconditionPredicate(key="port_occupied", expected_value=True, ttl=10.0)
        rule = ConstraintRule(
            rule_id="r_counter",
            action_signature="bind_port:18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.SUPPORTED,
            support_threshold=2,
            support_count=2
        )
        self.manager.add_rule(rule)

        # Premise confirmed APPLICABLE (port is True)
        self.manager.register_observation("port_occupied", True, timestamp=1000.0)
        self.assertEqual(self.manager.evaluate_applicability(rule), ApplicabilityState.APPLICABLE)

        # Action is executed anyway and SUCCEEDS! (True contradiction)
        self.manager.record_action_outcome("bind_port:18080", success=True)
        self.assertEqual(rule.validity_state, ValidityState.CONTRADICTED)
        self.assertEqual(rule.contradict_count, 1)

        # Since CONTRADICTED, gate no longer hard-blocks
        d = self.manager.make_gate_decision("bind_port:18080")
        self.assertEqual(d["decision"], GateDecision.ALLOW)

    def test_ttl_and_clock_injection(self):
        """Test TTL expiration using injectable clock."""
        pred = PreconditionPredicate(key="file_lock", expected_value=True, ttl=5.0)
        rule = ConstraintRule(
            rule_id="r_ttl",
            action_signature="access_file",
            predicates=[pred],
            failure_evidence={"error_code": 11},
            validity_state=ValidityState.SUPPORTED
        )
        self.manager.add_rule(rule)

        # Fresh observation at t=1000.0, current_time=1000.0
        self.manager.register_observation("file_lock", True, timestamp=1000.0)
        self.assertEqual(self.manager.evaluate_applicability(rule), ApplicabilityState.APPLICABLE)

        # Advance clock within TTL (t=1003.0) -> still APPLICABLE
        self.clock.advance(3.0)
        self.assertEqual(self.manager.evaluate_applicability(rule), ApplicabilityState.APPLICABLE)

        # Advance clock past TTL (t=1006.0 > 1000.0 + 5.0) -> UNKNOWN
        self.clock.advance(3.0)
        self.assertEqual(self.manager.evaluate_applicability(rule), ApplicabilityState.UNKNOWN)

        # UNKNOWN triggers PROBE gate
        d = self.manager.make_gate_decision("access_file")
        self.assertEqual(d["decision"], GateDecision.PROBE)

    def test_multi_rule_order_invariance(self):
        """Test that matching rules evaluated in any permutation order produce identical aggregated gate decisions."""
        pred = PreconditionPredicate(key="port_18080_state", expected_value=True, ttl=10.0)
        self.manager.register_observation("port_18080_state", True, timestamp=1000.0)

        r_candidate = ConstraintRule(
            rule_id="r_cand",
            action_signature="start_service:port=18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.CANDIDATE,
            support_threshold=2,
            support_count=1
        )
        r_supported = ConstraintRule(
            rule_id="r_supp",
            action_signature="start_service:port=18080",
            predicates=[pred],
            failure_evidence={"error_code": 98},
            validity_state=ValidityState.SUPPORTED,
            support_threshold=2,
            support_count=2
        )

        # Order 1: Candidate first, Supported second
        mgr1 = ConstraintLifecycleManager(time_provider=self.clock.time)
        mgr1.register_observation("port_18080_state", True, timestamp=1000.0)
        mgr1.add_rule(r_candidate)
        mgr1.add_rule(r_supported)
        dec1 = mgr1.make_gate_decision("start_service:port=18080")

        # Order 2: Supported first, Candidate second
        mgr2 = ConstraintLifecycleManager(time_provider=self.clock.time)
        mgr2.register_observation("port_18080_state", True, timestamp=1000.0)
        mgr2.add_rule(r_supported)
        mgr2.add_rule(r_candidate)
        dec2 = mgr2.make_gate_decision("start_service:port=18080")

        # Both MUST BLOCK because Supported rule is APPLICABLE, candidate must not short-circuit to ALLOW
        self.assertEqual(dec1["decision"], GateDecision.BLOCK, "Candidate must not short-circuit Supported block in Order 1")
        self.assertEqual(dec2["decision"], GateDecision.BLOCK, "Supported must block in Order 2")
        self.assertEqual(dec1["decision"], dec2["decision"])

    def test_pre_action_snapshot_preservation(self):
        """Test that outcome updating uses pre-action applicability instead of post-action contaminated observation."""
        pred = PreconditionPredicate(key="resource_locked", expected_value=True, ttl=10.0)
        self.manager.register_observation("resource_locked", True, timestamp=1000.0)

        rule = ConstraintRule(
            rule_id="r_snap",
            action_signature="acquire_lock",
            predicates=[pred],
            failure_evidence={"error_code": 5},
            validity_state=ValidityState.SUPPORTED,
            support_count=2
        )
        self.manager.add_rule(rule)

        # Pre-action evaluation: APPLICABLE
        pre_app = {"r_snap": self.manager.evaluate_applicability(rule)}
        self.assertEqual(pre_app["r_snap"], ApplicabilityState.APPLICABLE)

        # Environment changes during/after action execution (resource is now unlocked)
        self.manager.register_observation("resource_locked", False, timestamp=1001.0)
        self.assertEqual(self.manager.evaluate_applicability(rule), ApplicabilityState.NOT_APPLICABLE)

        # If action succeeded, updating with pre-action applicability MUST detect counter-evidence!
        updates = self.manager.record_action_outcome(
            "acquire_lock",
            success=True,
            pre_action_applicability=pre_app
        )
        self.assertEqual(rule.validity_state, ValidityState.CONTRADICTED, "Must be contradicted based on pre-action APPLICABLE state")
        self.assertEqual(updates[0]["prior_applicability"], ApplicabilityState.APPLICABLE)

    def test_evidence_deduplication(self):
        """Test that duplicate evidence IDs do not artificially inflate rule support count."""
        pred = PreconditionPredicate(key="file_perm", expected_value=False, ttl=10.0)
        self.manager.register_observation("file_perm", False, timestamp=1000.0)

        rule = ConstraintRule(
            rule_id="r_dedup",
            action_signature="write_file",
            predicates=[pred],
            failure_evidence={"error_code": 13, "evidence_id": "ev_001"},
            validity_state=ValidityState.CANDIDATE,
            support_threshold=2,
            support_count=1,
            evidence_ids=["ev_001"]
        )
        self.manager.add_rule(rule)

        # Duplicate evidence: ev_001 again
        self.manager.record_action_outcome(
            "write_file",
            success=False,
            error_details={"error_code": 13, "evidence_id": "ev_001"}
        )
        self.assertEqual(rule.support_count, 1, "Duplicate evidence ID must not increment support count")
        self.assertEqual(rule.validity_state, ValidityState.CANDIDATE, "Must remain CANDIDATE with duplicate evidence")

        # Distinct fresh evidence: ev_002
        self.manager.record_action_outcome(
            "write_file",
            success=False,
            error_details={"error_code": 13, "evidence_id": "ev_002"}
        )
        self.assertEqual(rule.support_count, 2, "Distinct evidence ID must increment support count to 2")
        self.assertEqual(rule.validity_state, ValidityState.SUPPORTED, "Must promote to SUPPORTED upon 2 distinct evidences")


if __name__ == "__main__":
    unittest.main()

