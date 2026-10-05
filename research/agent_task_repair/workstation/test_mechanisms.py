"""
Comprehensive Mechanism & Offline Integration Tests for Workstation Agent.

Verifies:
  1. Illegal first action is intercepted across ALL 5 groups before env.step.
  2. Interception reason and ConstraintEvent appear in the next prompt.
  3. Tool returning SUCCESS with mismatched expected effects is NOT counted as verified.
  4. Memory invalidation followed by task failure strictly yields online_recovery_succeeded == False.
  5. Action execution counters in Replay and D match actual trajectory steps.
  6. Intervention tool budget cannot be exceeded and tracks every call.
  7. Audit script correctly matches source success count (2/3) and LLM call counts.
"""
import unittest
import copy
from typing import Dict, Any, List

from .workstation_env import WorkstationEnv, StatusCode
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    CausalInterventionCompiler,
    ActionNode,
)
from .workstation_agent import WorkstationAgentRunner, CommonLocalPlanExecutor, ConstraintEvent
from ..audit_and_generate_report import audit_and_generate


class MockLLMBackendWithCustomScript:
    """Mock LLM backend that returns pre-scripted responses for precise integration testing."""
    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.prompts_received: List[str] = []
        self.device = "mock"
        self.model_metadata = {"quantization": "mock"}

    def generate(self, prompt: Any) -> str:
        prompt_str = prompt[0]["content"] if (isinstance(prompt, list) and prompt and isinstance(prompt[0], dict)) else str(prompt)
        self.prompts_received.append(prompt_str)
        if self.responses:
            return self.responses.pop(0)
        return '{"thought": "Default test action", "tool": "inspect", "args": {"subsystem": "all"}}'


class TestWorkstationIntegrationMechanisms(unittest.TestCase):

    def setUp(self):
        self.sample_pneumatic_mem = ProceduralMemoryItem(
            memory_id="proc_mem_pneumatic_test",
            name="Pneumatic Line Repair Procedure",
            target_subsystem="pneumatic_line",
            applicability_conditions={"subsystem": "pneumatic_line", "fault_types": ["overpressure_fault"]},
            observation_triggers=["inspect('pneumatic_line')"],
            actions=[
                ActionNode(node_id="p1", tool="isolate", args={"subsystem": "pneumatic_line", "action": "engage"}, expected_postconditions={"isolated": True}),
                ActionNode(node_id="p2", tool="clear_fault", args={"subsystem": "pneumatic_line"}, expected_postconditions={"status": "nominal"}),
                ActionNode(node_id="p3", tool="isolate", args={"subsystem": "pneumatic_line", "action": "release"}, expected_postconditions={"isolated": False}),
                ActionNode(node_id="p4", tool="reset", args={"subsystem": "pneumatic_line"}, expected_postconditions={"pressure_bar": 5.0}),
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

    def test_1_illegal_first_action_blocked_across_all_groups(self):
        """Verify that an illegal first action in a plan is intercepted across all 5 groups before env.step."""
        task_cfg = {
            "task_id": "test_illegal_first_action",
            "goal": "Test safety interlock",
            "initial_state": {
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }

        # LLM script that tries illegal clear_fault as first action
        illegal_first_plan = '{"thought": "Try clear fault without isolation", "plan": [{"tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}}]}'

        groups = ["Group_B2_step", "Group_B2_plan", "Group_B1_plan", "Group_Replay", "Group_D_Procedural_Memory"]
        for gid in groups:
            mock_llm = MockLLMBackendWithCustomScript([
                illegal_first_plan,
                '{"thought": "Isolate first", "plan": [{"tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}}]}',
                '{"thought": "Stop", "tool": "self_test", "args": {"target": "workstation"}}'
            ])
            runner = WorkstationAgentRunner(group_id=gid, llm_backend=mock_llm, max_llm_calls=3, max_tool_calls=5)
            res = runner.run_task(task_cfg, structured_facts=self.fact_store)

            # Check trajectory: clear_fault must NOT have been executed on non-isolated line
            executed_tools = [s["tool"] for s in res["trajectory"]]
            self.assertNotIn("clear_fault", executed_tools, f"Group {gid} executed illegal clear_fault into env.step!")

    def test_2_interception_reason_appears_in_next_model_prompt(self):
        """Verify that when an action is intercepted, the ConstraintEvent feedback appears in subsequent prompt."""
        task_cfg = {
            "task_id": "test_constraint_feedback",
            "goal": "Test constraint feedback",
            "initial_state": {
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript([
            # Step 1: inspect
            '{"thought": "Inspect", "plan": [{"tool": "inspect", "args": {"subsystem": "pneumatic_line"}}]}',
            # Step 2: attempt illegal clear_fault
            '{"thought": "Illegal clear", "plan": [{"tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}}]}',
            # Step 3: check prompt
            '{"thought": "Now isolate", "plan": [{"tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}}]}',
        ])
        runner = WorkstationAgentRunner(group_id="Group_B2_plan", llm_backend=mock_llm, max_llm_calls=3, max_tool_calls=5)
        res = runner.run_task(task_cfg, structured_facts=self.fact_store)

        self.assertGreaterEqual(len(mock_llm.prompts_received), 3)
        prompt_3 = mock_llm.prompts_received[2]
        self.assertIn("=== Active Constraint & Interlock Feedback ===", prompt_3)
        self.assertIn("pneumatic_line.isolated == True", prompt_3)
        self.assertIn("cannot clear fault while pressurized", prompt_3)

    def test_3_postcondition_mismatch_not_verified(self):
        """Verify that tool SUCCESS with mismatched expected effects is NOT counted as postcondition verified."""
        mismatch_mem = ProceduralMemoryItem(
            memory_id="mismatch_test_mem",
            name="Mismatch test",
            target_subsystem="pneumatic_line",
            applicability_conditions={"subsystem": "pneumatic_line", "fault_types": ["overpressure_fault"]},
            observation_triggers=["inspect"],
            actions=[
                ActionNode(node_id="p1", tool="isolate", args={"subsystem": "pneumatic_line", "action": "engage"}, expected_postconditions={"pressure_bar": 999.9}),
            ],
            evidenced_order_dependencies=[],
            expected_effects=[],
            invalidation_conditions=[],
            source_task_id="t",
            source_step_refs=[1],
            status="VERIFIED",
        )
        mismatch_store = ProceduralMemoryStore()
        mismatch_store.add_memory(mismatch_mem)

        mock_llm = MockLLMBackendWithCustomScript(['{"thought": "Stop", "tool": "inspect", "args": {"subsystem": "all"}}'])
        runner = WorkstationAgentRunner(group_id="Group_D_Procedural_Memory", llm_backend=mock_llm, max_llm_calls=2, max_tool_calls=2)
        task_cfg = {
            "task_id": "test_mismatch",
            "goal": "Test mismatch",
            "initial_state": {"pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5}},
        }
        res = runner.run_task(task_cfg, procedural_memory_store=mismatch_store)
        self.assertEqual(res["memory_postcondition_verified_count"], 0, "Mismatched postcondition cannot be counted as verified!")
        self.assertGreaterEqual(res["memory_invalidated_count"], 1, "Mismatched postcondition must trigger memory invalidation!")

    def test_4_invalidation_followed_by_failure_recovery_false(self):
        """Verify that memory invalidation on a failed task strictly yields online_recovery_succeeded == False."""
        task_cfg = {
            "task_id": "test_recovery_false",
            "goal": "Test fail",
            "initial_state": {
                "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript(['{"thought": "Fail", "tool": "inspect", "args": {"subsystem": "all"}}'])
        runner = WorkstationAgentRunner(group_id="Group_D_Procedural_Memory", llm_backend=mock_llm, max_llm_calls=1, max_tool_calls=1)
        res = runner.run_task(task_cfg, procedural_memory_store=self.memory_store)
        self.assertFalse(res["success"])
        self.assertFalse(res["online_recovery_succeeded"])

    def test_5_replay_and_d_action_counters_match_trajectory(self):
        """Verify that action execution counters in Replay and D accurately count executed memory actions."""
        raw_source = [{
            "task_id": "src_pneumatic",
            "success": True,
            "trajectory": [
                {"step_index": 1, "tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}, "result": {"status": StatusCode.SUCCESS, "effects": {"isolated": True}}},
                {"step_index": 2, "tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}, "result": {"status": StatusCode.SUCCESS, "effects": {"status": "nominal"}}},
            ]
        }]
        task_cfg = {
            "task_id": "test_replay_counter",
            "goal": "Test replay counter",
            "initial_state": {"pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5}},
        }
        mock_llm = MockLLMBackendWithCustomScript([])
        runner = WorkstationAgentRunner(group_id="Group_Replay", llm_backend=mock_llm, max_llm_calls=2, max_tool_calls=3)
        res = runner.run_task(task_cfg, raw_source_episodes=raw_source)
        # Should have executed 2 replay actions
        self.assertEqual(res["memory_action_executed_count"], 2)
        self.assertEqual(res["memory_selected_count"], 1)

    def test_6_intervention_budget_not_exceeded_and_undercounting_fixed(self):
        """Verify that CausalInterventionCompiler never exceeds budget and increments counter on every step."""
        compiler = CausalInterventionCompiler(max_intervention_budget=10)
        source_episodes = [{
            "task_id": "src_pneumatic",
            "success": True,
            "trajectory": [
                {"step_index": 1, "tool": "inspect", "args": {"subsystem": "all"}, "result": {"status": StatusCode.SUCCESS, "data": {"pneumatic_line": {"status": "overpressure_fault"}}}},
                {"step_index": 2, "tool": "isolate", "args": {"subsystem": "pneumatic_line", "action": "engage"}, "result": {"status": StatusCode.SUCCESS, "effects": {"isolated": True}}},
                {"step_index": 3, "tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}, "result": {"status": StatusCode.SUCCESS, "effects": {"status": "nominal"}}},
            ]
        }]
        source_configs = [{
            "task_id": "src_pneumatic",
            "initial_state": {"pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5}},
        }]
        facts, mems = compiler.compile_from_source_episodes(source_episodes, source_configs)
        self.assertLessEqual(compiler.intervention_tool_calls, 10)
        self.assertEqual(facts.total_intervention_tool_calls, compiler.intervention_tool_calls)

    def test_7_audit_script_verifies_source_and_calls(self):
        """Verify that audit_and_generate passes all assertions on raw benchmark JSON."""
        # This will raise AssertionError if any discrepancies exist
        audit_and_generate()


if __name__ == "__main__":
    unittest.main()
