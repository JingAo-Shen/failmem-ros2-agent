"""
Unit Test Suite for Memory Pipeline & Error Classification.
Asserts:
1. Deterministic heuristic parser classifies confirmed errors accurately.
2. Unrecognized errors are strictly rejected (no false attribution).
3. Two different failures are never misattributed to the same condition.
4. Extracted rules initialize to CANDIDATE with support_count = 1.
5. Evidence provenance (error_code, stderr, evidence_id) is complete.
"""

import unittest
from research.conditional_constraint_memory.memory_pipeline import (
    FailureTrace,
    DeterministicHeuristicRuleParser,
    MemoryPipeline,
)
from research.conditional_constraint_memory.constraint_lifecycle import ValidityState


class TestMemoryPipeline(unittest.TestCase):
    def test_port_conflict_classification(self):
        trace = FailureTrace(
            run_id="run_01",
            step=1,
            tool_name="start_service",
            tool_params={"port": 18080},
            exit_code=98,
            stderr="OSError: [Errno 98] Address already in use (Port 18080)",
            stdout="",
            observation_snapshot={"port:18080:occupied": True},
        )
        clf = DeterministicHeuristicRuleParser.classify_failure(trace)
        self.assertIsNotNone(clf)
        self.assertEqual(clf["category"], "port_conflict")
        self.assertEqual(clf["pred_key"], "port:18080:occupied")
        self.assertEqual(clf["expected_val"], True)
        self.assertEqual(clf["error_code"], 98)

        rule = MemoryPipeline.extract_rule_for_m(trace)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.validity_state, ValidityState.CANDIDATE)
        self.assertEqual(rule.support_count, 1)
        self.assertEqual(rule.failure_evidence["error_code"], 98)
        self.assertEqual(rule.failure_evidence["evidence_id"], trace.evidence_id)

    def test_file_permission_classification(self):
        trace = FailureTrace(
            run_id="run_02",
            step=2,
            tool_name="write_config",
            tool_params={"filepath": "/etc/service_demo/app.conf"},
            exit_code=1,
            stderr="bash: /etc/service_demo/app.conf: Permission denied",
            stdout="",
            observation_snapshot={"file:/etc/service_demo/app.conf:writable": False},
        )
        clf = DeterministicHeuristicRuleParser.classify_failure(trace)
        self.assertIsNotNone(clf)
        self.assertEqual(clf["category"], "permission_denied")
        self.assertEqual(clf["pred_key"], "file:/etc/service_demo/app.conf:writable")
        self.assertEqual(clf["expected_val"], False)

        rule = MemoryPipeline.extract_rule_for_m(trace)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.validity_state, ValidityState.CANDIDATE)
        self.assertEqual(rule.support_count, 1)
        self.assertEqual(rule.failure_evidence["error_code"], 1)

    def test_unrecognized_errors_strictly_rejected(self):
        """Unrecognized errors must be rejected rather than hallucinating rules."""
        # 1. start_service failure due to invalid argument / syntax
        bad_service_trace = FailureTrace(
            run_id="run_03",
            step=1,
            tool_name="start_service",
            tool_params={"port": 18080},
            exit_code=2,
            stderr="ValueError: Invalid service configuration file",
            stdout="",
            observation_snapshot={},
        )
        clf1 = DeterministicHeuristicRuleParser.classify_failure(bad_service_trace)
        self.assertIsNone(clf1, "Non-address error in start_service must be rejected")
        rule1 = MemoryPipeline.extract_rule_for_m(bad_service_trace)
        self.assertIsNone(rule1)

        # 2. write_config failure due to disk full
        disk_full_trace = FailureTrace(
            run_id="run_04",
            step=1,
            tool_name="write_config",
            tool_params={"filepath": "/tmp/app.conf"},
            exit_code=28,
            stderr="No space left on device",
            stdout="",
            observation_snapshot={},
        )
        clf2 = DeterministicHeuristicRuleParser.classify_failure(disk_full_trace)
        self.assertIsNone(clf2, "Disk full error in write_config must not be attributed to permission denied")
        rule2 = MemoryPipeline.extract_rule_for_m(disk_full_trace)
        self.assertIsNone(rule2)

    def test_different_failures_not_conflated(self):
        """Ensure port failure and file failure do not share or conflate rule signatures."""
        port_trace = FailureTrace(
            run_id="run_p",
            step=1,
            tool_name="start_service",
            tool_params={"port": 18080},
            exit_code=98,
            stderr="Address already in use",
            stdout="",
            observation_snapshot={},
        )
        file_trace = FailureTrace(
            run_id="run_f",
            step=1,
            tool_name="write_config",
            tool_params={"filepath": "/etc/app.conf"},
            exit_code=13,
            stderr="Permission denied",
            stdout="",
            observation_snapshot={},
        )
        rule_p = MemoryPipeline.extract_rule_for_m(port_trace)
        rule_f = MemoryPipeline.extract_rule_for_m(file_trace)
        self.assertNotEqual(rule_p.action_signature, rule_f.action_signature)
        self.assertNotEqual(rule_p.predicates[0].key, rule_f.predicates[0].key)


if __name__ == "__main__":
    unittest.main()
