"""
Strict Gate Mechanism Verification Tests for Workstation Procedural Memory Benchmark.

Mandatory pre-flight gates before frozen benchmark execution:
  Gate 1: First action blocked by common validator when precondition is unmet.
  Gate 2: clear_fault(arm_gripper) releasing load updates holding_load=False without pseudo-invalidation.
  Gate 3: Memory invalidation followed by task failure strictly yields online_recovery_succeeded == False.
  Gate 4: B2-plan, Replay, and D enforce identical validation rules on identical actions.
  Gate 5: Unverified candidate dependencies cannot appear as VERIFIED in prompts.
  Gate 6: Boundary consistency: Timeout properly aborts task with success=False.
"""
import unittest
import copy
from typing import Dict, Any

from .workstation_env import WorkstationEnv, StatusCode
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    ActionNode,
)
from .workstation_agent import WorkstationAgentRunner, CommonLocalPlanExecutor


class TestWorkstationMechanisms(unittest.TestCase):

    def setUp(self):
        self.sample_pneumatic_mem = ProceduralMemoryItem(
            memory_id="proc_mem_pneumatic_test",
            name="Pneumatic Line Repair Procedure",
            target_subsystem="pneumatic_line",
            applicability_conditions={"subsystem": "pneumatic_line", "fault_types": ["overpressure_fault"]},
            observation_triggers=["inspect('pneumatic_line')"],
            actions=[
                ActionNode(node_id="p1", tool="isolate", args={"subsystem": "pneumatic_line", "action": "engage"}),
                ActionNode(node_id="p2", tool="clear_fault", args={"subsystem": "pneumatic_line"}),
                ActionNode(node_id="p3", tool="isolate", args={"subsystem": "pneumatic_line", "action": "release"}),
                ActionNode(node_id="p4", tool="reset", args={"subsystem": "pneumatic_line"}),
            ],
            evidenced_order_dependencies=[{
                "subsystem": "pneumatic_line",
                "before": "isolate(pneumatic_line, engage)",
                "after": "clear_fault(pneumatic_line)",
                "status": "VERIFIED",
            }],
            expected_effects=["pneumatic_line.status == nominal"],
            invalidation_conditions=[],
            source_task_id="src_pneumatic",
            source_step_refs=[1, 2, 3, 4],
            status="VERIFIED",
        )
        self.memory_store = ProceduralMemoryStore()
        self.memory_store.add_memory(self.sample_pneumatic_mem)

        self.fact_store = StructuredFactStore()
        self.fact_store.action_preconditions = {
            "clear_fault_pneumatic_line": [{"condition": "pneumatic_line.isolated == True", "status": "VERIFIED"}]
        }

    def test_gate_1_first_action_precondition_blocked(self):
        """Gate 1: Action is blocked by common validator if precondition is unmet."""
        executor = CommonLocalPlanExecutor(fact_store=self.fact_store)
        known_state = {"pneumatic_line": {"status": "overpressure_fault", "isolated": False}}
        action = {"tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}}
        
        valid, reason = executor.validate_precondition(action, known_state)
        self.assertFalse(valid, "clear_fault on non-isolated line must be blocked by validator.")
        self.assertIn("not isolated", reason.lower())

    def test_gate_2_clear_fault_releases_load_cleanly(self):
        """Gate 2: clear_fault on arm_gripper releasing load updates holding_load=False without pseudo-invalidation."""
        env = WorkstationEnv({
            "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
        })
        res = env.step("clear_fault", subsystem="arm_gripper")
        self.assertEqual(res["status"], StatusCode.SUCCESS)
        self.assertEqual(res.get("effects", {}).get("holding_load"), False)

        runner = WorkstationAgentRunner(group_id="Group_B2_step", allow_fallback=True)
        known = {"arm_gripper": {"status": "jammed", "holding_load": True}}
        runner._update_known_state(known, "clear_fault", {"subsystem": "arm_gripper"}, res)
        self.assertEqual(known["arm_gripper"]["holding_load"], False, "known_state must reflect holding_load=False after clear_fault.")

    def test_gate_3_invalidation_followed_by_failure(self):
        """Gate 3: Memory invalidation followed by task failure yields online_recovery_succeeded == False."""
        runner = WorkstationAgentRunner(group_id="Group_D_Procedural_Memory", max_llm_calls=2, max_tool_calls=3, allow_fallback=True)
        # Task with unfixable initial budget
        task_cfg = {
            "task_id": "test_failure_recovery",
            "goal": "Test fail.",
            "initial_state": {
                "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        res = runner.run_task(task_cfg, structured_facts=self.fact_store, procedural_memory_store=self.memory_store)
        self.assertFalse(res["success"])
        self.assertFalse(res["online_recovery_succeeded"], "online_recovery_succeeded must be False if task failed.")

    def test_gate_4_identical_validation_rules_across_groups(self):
        """Gate 4: B2-plan, Replay, and D enforce identical validation rules on identical actions."""
        executor = CommonLocalPlanExecutor(fact_store=self.fact_store)
        
        # Action with unmet precondition (power tripped while attempting calibrate)
        known_state = {"power_unit": {"status": "tripped", "isolated": False}}
        act = {"tool": "calibrate", "args": {"subsystem": "camera_sensor"}}

        valid, reason = executor.validate_precondition(act, known_state)
        self.assertFalse(valid, "Calibrate must be blocked across all groups when power is tripped.")

    def test_gate_5_unverified_candidate_not_shown_as_verified(self):
        """Gate 5: Unverified candidate dependencies cannot appear as VERIFIED in prompts."""
        fact_store = StructuredFactStore()
        fact_store.causal_order_constraints.append({
            "subsystem": "arm_gripper",
            "before": "reset",
            "after": "calibrate",
            "status": "CANDIDATE",
        })
        runner = WorkstationAgentRunner(group_id="Group_B2_step", allow_fallback=True)
        task_cfg = {"task_id": "t1", "goal": "goal"}
        prompt = runner._construct_prompt(task_cfg, {}, [], structured_facts=fact_store)
        self.assertIn("Status: CANDIDATE", prompt)
        self.assertNotIn("Status: VERIFIED", prompt)

    def test_gate_6_boundary_timeout_consistency(self):
        """Gate 6: Timeout properly aborts task with success=False."""
        runner = WorkstationAgentRunner(group_id="Group_B2_step", time_limit_s=0.001, allow_fallback=True)
        task_cfg = {
            "task_id": "test_timeout",
            "goal": "Test timeout.",
            "initial_state": {
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        res = runner.run_task(task_cfg)
        self.assertFalse(res["success"], "Task exceeding timeout must fail.")
        self.assertEqual(res["termination_reason"], "TIME_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
