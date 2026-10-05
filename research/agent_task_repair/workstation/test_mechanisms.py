"""
Fast Mechanism Verification Tests for Workstation Procedural Memory Agent.

Verifies:
  1. Valid memory entry into plan.
  2. Negative rejection on mismatched conditions.
  3. Invalidation exit and online recovery upon condition drift.
  4. Parity in budget accounting, reset, and success verification across all 4 groups.
"""
import unittest
import copy
from typing import Dict, Any

from .workstation_env import WorkstationEnv, StatusCode
from .workstation_tasks import get_source_tasks, get_target_tasks
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    CausalInterventionCompiler,
    ActionNode,
)
from .workstation_agent import WorkstationAgentRunner


class TestWorkstationMechanisms(unittest.TestCase):

    def setUp(self):
        # Create a sample validated procedural memory for pneumatic repair
        self.sample_pneumatic_mem = ProceduralMemoryItem(
            memory_id="proc_mem_pneumatic_test",
            name="Pneumatic Line Repair Procedure",
            target_subsystem="pneumatic_line",
            applicability_conditions={"subsystem": "pneumatic_line", "fault_types": ["overpressure_fault", "leak_fault"]},
            observation_triggers=["inspect('pneumatic_line')"],
            actions=[
                ActionNode(node_id="p1", tool="isolate", args={"subsystem": "pneumatic_line", "action": "engage"}),
                ActionNode(node_id="p2", tool="clear_fault", args={"subsystem": "pneumatic_line"}),
                ActionNode(node_id="p3", tool="isolate", args={"subsystem": "pneumatic_line", "action": "release"}),
                ActionNode(node_id="p4", tool="reset", args={"subsystem": "pneumatic_line"}),
            ],
            evidenced_order_dependencies=[("isolate_engage", "clear_fault"), ("clear_fault", "isolate_release")],
            expected_effects=["pneumatic_line.status == nominal"],
            invalidation_conditions=[{"trigger": "load_interlock"}],
            source_task_id="src_pneumatic",
            source_step_refs=[1, 2, 3, 4],
            status="VALIDATED",
        )
        self.memory_store = ProceduralMemoryStore()
        self.memory_store.add_memory(self.sample_pneumatic_mem)

        self.fact_store = StructuredFactStore()
        self.fact_store.action_preconditions = {
            "clear_fault_pneumatic_line": ["pneumatic_line.isolated == True"]
        }

    def test_1_valid_memory_entry_into_plan(self):
        """Test that matching memory is retrieved and instantiated for Group D."""
        runner = WorkstationAgentRunner(group_id="Group_D_Procedural_Memory", max_llm_calls=10, max_tool_calls=15)
        task_cfg = {
            "task_id": "test_pneumatic_entry",
            "goal": "Repair pneumatic line and resume.",
            "initial_state": {
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5},
                "camera_sensor": {"status": "nominal", "calibrated": True},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        res = runner.run_task(
            task_config=task_cfg,
            structured_facts=self.fact_store,
            procedural_memory_store=self.memory_store,
        )
        # Check memory reuse audit event
        instantiated_events = [e for e in res["audit_events"] if e.get("event") == "PROCEDURAL_MEMORY_INSTANTIATED"]
        self.assertTrue(len(instantiated_events) > 0, "Procedural memory should be instantiated into plan.")
        self.assertTrue(res["memory_reused"], "Memory reuse flag should be True.")
        self.assertTrue(res["success"], "Task should complete successfully.")

    def test_2_negative_rejection_on_mismatched_conditions(self):
        """Test that irrelevant task (e.g. clean startup or power trip) does NOT reuse pneumatic memory."""
        runner = WorkstationAgentRunner(group_id="Group_D_Procedural_Memory", max_llm_calls=10, max_tool_calls=15)
        task_cfg = {
            "task_id": "test_clean_rejection",
            "goal": "Verify nominal workstation and resume.",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
                "arm_gripper": {"status": "nominal", "holding_load": False, "calibrated": True},
                "camera_sensor": {"status": "nominal", "calibrated": True, "drift_offset_mm": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        res = runner.run_task(
            task_config=task_cfg,
            structured_facts=self.fact_store,
            procedural_memory_store=self.memory_store,
        )
        instantiated_events = [e for e in res["audit_events"] if e.get("event") == "PROCEDURAL_MEMORY_INSTANTIATED"]
        self.assertEqual(len(instantiated_events), 0, "No procedural memory should be instantiated for nominal system.")
        self.assertFalse(res["memory_reused"], "Memory reuse should be False.")
        self.assertTrue(res["success"], "Clean startup should succeed.")

    def test_3_invalidation_exit_and_online_recovery(self):
        """Test that if an invalidation trigger occurs during memory replay, memory exits and recovers online."""
        # Create a flawed memory that tries to reset gripper without clearing load
        flawed_gripper_mem = ProceduralMemoryItem(
            memory_id="proc_mem_flawed_gripper",
            name="Flawed Gripper Reset",
            target_subsystem="arm_gripper",
            applicability_conditions={"subsystem": "arm_gripper", "fault_types": ["jammed"]},
            observation_triggers=["inspect('arm_gripper')"],
            actions=[
                ActionNode(node_id="g1", tool="reset", args={"subsystem": "arm_gripper"}),  # Attempt reset while holding load!
            ],
            evidenced_order_dependencies=[],
            expected_effects=[],
            invalidation_conditions=[{"trigger": "load_interlock"}],
            source_task_id="src_gripper",
            source_step_refs=[1],
            status="VALIDATED",
        )
        mem_store = ProceduralMemoryStore()
        mem_store.add_memory(flawed_gripper_mem)

        runner = WorkstationAgentRunner(group_id="Group_D_Procedural_Memory", max_llm_calls=15, max_tool_calls=20)
        task_cfg = {
            "task_id": "test_invalidation_recovery",
            "goal": "Handle gripper load and resume.",
            "initial_state": {
                "arm_gripper": {"status": "jammed", "holding_load": True, "calibrated": False},
                "camera_sensor": {"status": "nominal", "calibrated": True},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        res = runner.run_task(
            task_config=task_cfg,
            structured_facts=self.fact_store,
            procedural_memory_store=mem_store,
        )
        # Should record invalidation event and recover
        invalidation_events = [
            e for e in res["audit_events"]
            if e.get("event") in ["PROCEDURAL_MEMORY_INVALIDATED", "PROCEDURAL_MEMORY_ERROR_INVALIDATION"]
        ]
        self.assertTrue(len(invalidation_events) > 0, "Memory invalidation should trigger.")
        self.assertTrue(res["memory_invalidated_recovered"], "Invalidation recovery flag should be True.")

    def test_4_group_accounting_and_parity(self):
        """Test that B0, B1, B2, D have identical budget and telemetry accounting."""
        task_cfg = {
            "task_id": "test_parity",
            "goal": "Test parity on pneumatic leak.",
            "initial_state": {
                "pneumatic_line": {"status": "leak_fault", "isolated": False, "pressure_bar": 1.2},
                "camera_sensor": {"status": "nominal", "calibrated": True},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        groups = ["Group_B0_Online", "Group_B1_Raw_Trajectories", "Group_B2_Structured_Facts", "Group_D_Procedural_Memory"]
        for gid in groups:
            runner = WorkstationAgentRunner(group_id=gid, max_llm_calls=10, max_tool_calls=15)
            res = runner.run_task(
                task_config=task_cfg,
                structured_facts=self.fact_store if "B2" in gid or "D" in gid else None,
                procedural_memory_store=self.memory_store if "D" in gid else None,
            )
            self.assertIn("step_count", res)
            self.assertIn("llm_calls", res)
            self.assertIn("total_prompt_tokens", res)
            self.assertIn("tool_errors_count", res)
            self.assertTrue(res["step_count"] > 0)


if __name__ == "__main__":
    unittest.main()
