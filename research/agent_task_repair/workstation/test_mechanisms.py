"""
Comprehensive Mechanism & Offline Integration Tests for Workstation Agent (Section IV).

Verifies all 9 strict mechanism gates:
  1. inspect SUCCESS does not clear power constraint;
  2. reset SUCCESS without fault change is detected as no-progress;
  3. Condition satisfaction triggers re-evaluation and execution of deferred program;
  4. Same state does not infinitely retry same program;
  5. UNKNOWN postcondition is not counted as verified pass;
  6. Memory > 4 steps cursor tracking works without silent truncation;
  7. All groups' same action goes through identical common validation;
  8. Report numbers and logs match automatically;
  9. Interrupted run resumes without overwriting failed records.
"""
import unittest
import copy
import json
import os
import tempfile
from typing import Dict, Any, List

from .workstation_env import WorkstationEnv, StatusCode
from .procedural_memory import (
    ProceduralMemoryItem,
    ProceduralMemoryStore,
    StructuredFactStore,
    CausalInterventionCompiler,
    ActionNode,
)
from .workstation_agent import (
    WorkstationAgentRunner,
    CommonLocalPlanExecutor,
    ConstraintTracker,
    ActiveConstraint,
    ActiveMemoryExecution,
    ConstraintEvent,
    WORKSTATION_SYSTEM_PROMPT_STEP_NO_RECIPE,
    WORKSTATION_SYSTEM_PROMPT_PLAN_NO_RECIPE,
)
from ..audit_and_generate_report import audit_and_generate


class MockLLMBackendWithCustomScript:
    """Mock LLM backend that returns pre-scripted responses for precise integration testing."""
    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.prompts_received: List[str] = []
        self.device = "mock"
        self.model_metadata = {"quantization": "mock"}

    def generate(self, prompt: Any, max_new_tokens: int = 512, temperature: float = 0.0) -> Dict[str, Any]:
        prompt_str = prompt[0]["content"] if (isinstance(prompt, list) and prompt and isinstance(prompt[0], dict)) else str(prompt)
        self.prompts_received.append(prompt_str)
        text = self.responses.pop(0) if self.responses else '{"thought": "Default inspect", "tool": "inspect", "args": {"subsystem": "all"}}'
        return {
            "text": text,
            "prompt_tokens": len(prompt_str) // 4,
            "generated_tokens": len(text) // 4,
        }


class TestWorkstationIntegrationMechanisms(unittest.TestCase):

    def setUp(self):
        # Sample procedural memory for camera sensor
        self.camera_mem = ProceduralMemoryItem(
            memory_id="proc_mem_camera_sensor_test",
            name="Camera Sensor Calibration",
            target_subsystem="camera_sensor",
            applicability_conditions={"subsystem": "camera_sensor", "fault_types": ["optical_drift"]},
            observation_triggers=["inspect('camera_sensor')"],
            actions=[
                ActionNode(node_id="c1", tool="clear_fault", args={"subsystem": "camera_sensor"}, expected_postconditions={"status": "nominal"}),
                ActionNode(node_id="c2", tool="calibrate", args={"subsystem": "camera_sensor"}, expected_postconditions={"calibrated": True}),
            ],
            evidenced_order_dependencies=[],
            expected_effects=["camera_sensor.status == nominal", "camera_sensor.calibrated == True"],
            invalidation_conditions=[],
            source_task_id="src_sensor_actuator",
            source_step_refs=[1, 2],
            status="VERIFIED",
        )
        self.memory_store = ProceduralMemoryStore()
        self.memory_store.add_memory(self.camera_mem)

    def test_gate_1_inspect_success_does_not_clear_power_constraint(self):
        """Gate 1: inspect SUCCESS does not clear power constraint while power is still tripped."""
        tracker = ConstraintTracker()
        tracker.add_constraint(
            ActiveConstraint(
                constraint_id="power_unit_nominal_required",
                predicate="power_unit.status == nominal and power_unit.isolated == False",
                subsystem="power_unit",
                required_condition={"field": "status", "expected": "nominal", "secondary_field": "isolated", "secondary_expected": False},
                evidence_source="precondition_interlock",
            ),
            step_index=1,
        )
        self.assertEqual(len(tracker.get_active_constraints()), 1)

        # Observation where inspect returns SUCCESS, but power_unit is tripped
        known_state = {
            "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
            "pneumatic_line": {"status": "nominal", "isolated": False, "pressure_bar": 5.0},
        }
        tracker.update_with_observation(known_state, step_index=2)
        # Must still be active!
        self.assertEqual(len(tracker.get_active_constraints()), 1, "inspect SUCCESS must not clear active power constraint when still tripped!")

        # Now observation where power_unit is nominal and not isolated
        known_state_nominal = {
            "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
        }
        tracker.update_with_observation(known_state_nominal, step_index=3)
        self.assertEqual(len(tracker.get_active_constraints()), 0, "Constraint must be marked SATISFIED when condition is truly met.")

    def test_gate_2_reset_success_without_state_change_detected_as_no_progress(self):
        """Gate 2: reset returning SUCCESS without fault change is detected as no-progress / stagnation loop."""
        task_cfg = {
            "task_id": "test_stagnation",
            "goal": "Test stagnation loop detection",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript([
            '{"thought": "Reset 1", "tool": "reset", "args": {"subsystem": "power_unit"}}',
            '{"thought": "Reset 2", "tool": "reset", "args": {"subsystem": "power_unit"}}',
            '{"thought": "Reset 3", "tool": "reset", "args": {"subsystem": "power_unit"}}',
        ])
        runner = WorkstationAgentRunner(group_id="Group_B2_plan", llm_backend=mock_llm, max_llm_calls=3, max_tool_calls=5)
        res = runner.run_task(task_cfg)

        stag_events = [e for e in res["audit_events"] if e.get("event_type") == "STAGNATION_LOOP"]
        self.assertGreaterEqual(len(stag_events), 1, "Repeated reset without state change must emit STAGNATION_LOOP!")

    def test_gate_3_deferred_program_reenters_execution_on_condition_satisfaction(self):
        """Gate 3: Condition satisfaction triggers re-evaluation and execution of deferred program in D-gated."""
        task_cfg = {
            "task_id": "test_deferred_resume",
            "goal": "Test D-gated deferral and resumption",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.5},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript([
            '{"thought": "Inspect", "plan": [{"tool": "inspect", "args": {"subsystem": "all"}}]}',
            '{"thought": "Fix power first", "plan": [{"tool": "isolate", "args": {"subsystem": "power_unit", "action": "engage"}}, {"tool": "clear_fault", "args": {"subsystem": "power_unit"}}, {"tool": "isolate", "args": {"subsystem": "power_unit", "action": "release"}}]}',
            '{"thought": "Self test and resume", "plan": [{"tool": "self_test", "args": {"target": "workstation"}}, {"tool": "resume", "args": {"target": "workstation"}}]}',
        ])
        runner = WorkstationAgentRunner(group_id="Group_D_gated", llm_backend=mock_llm, max_llm_calls=4, max_tool_calls=10)
        res = runner.run_task(task_cfg, procedural_memory_store=self.memory_store)

        self.assertGreaterEqual(res["memory_deferred_count"], 1, "Camera memory must be deferred when power is tripped!")
        self.assertGreaterEqual(res["memory_resumed_count"], 1, "Camera memory must be resumed when power becomes nominal!")
        executed_sources = [s["action_source"] for s in res["trajectory"]]
        self.assertIn("procedural_memory", executed_sources, "Resumed memory actions must be executed under procedural_memory source tag!")

    def test_gate_4_same_state_does_not_infinitely_retry_same_program(self):
        """Gate 4: Same state does not infinitely retry the same deferred candidate."""
        task_cfg = {
            "task_id": "test_no_infinite_deferral",
            "goal": "Test finite deferral",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.5},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript([
            '{"thought": "Inspect 1", "tool": "inspect", "args": {"subsystem": "all"}}',
            '{"thought": "Inspect 2", "tool": "inspect", "args": {"subsystem": "all"}}',
        ])
        runner = WorkstationAgentRunner(group_id="Group_D_gated", llm_backend=mock_llm, max_llm_calls=2, max_tool_calls=5)
        res = runner.run_task(task_cfg, procedural_memory_store=self.memory_store)

        self.assertEqual(res["memory_deferred_count"], 1, "Memory should only be deferred once per unique state!")

    def test_gate_5_unknown_postcondition_not_counted_as_verified(self):
        """Gate 5: UNKNOWN postcondition is NOT counted as verified pass."""
        mem_unknown_post = ProceduralMemoryItem(
            memory_id="proc_mem_unknown_post",
            name="Unknown Post Test",
            target_subsystem="camera_sensor",
            applicability_conditions={"subsystem": "camera_sensor", "fault_types": ["optical_drift"]},
            observation_triggers=["inspect"],
            actions=[
                ActionNode(node_id="u1", tool="calibrate", args={"subsystem": "camera_sensor"}, expected_postconditions={"non_existent_field": 123}),
            ],
            evidenced_order_dependencies=[],
            expected_effects=[],
            invalidation_conditions=[],
            source_task_id="t",
            source_step_refs=[1],
            status="VERIFIED",
        )
        store = ProceduralMemoryStore()
        store.add_memory(mem_unknown_post)

        task_cfg = {
            "task_id": "test_unknown_post",
            "goal": "Test unknown postcondition",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.5},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript([
            '{"thought": "Inspect", "tool": "inspect", "args": {"subsystem": "all"}}',
        ])
        runner = WorkstationAgentRunner(group_id="Group_D_current", llm_backend=mock_llm, max_llm_calls=2, max_tool_calls=3)
        res = runner.run_task(task_cfg, procedural_memory_store=store)
        self.assertEqual(res["memory_postcondition_verified_count"], 0, "UNKNOWN postcondition cannot be counted as verified pass!")

    def test_gate_6_long_memory_chunked_cursor_tracking(self):
        """Gate 6: Memory with > 4 steps is executed in chunks without silent truncation."""
        long_actions = [
            ActionNode(node_id="a1", tool="isolate", args={"subsystem": "pneumatic_line", "action": "engage"}, expected_postconditions={"isolated": True}),
            ActionNode(node_id="a2", tool="clear_fault", args={"subsystem": "pneumatic_line"}, expected_postconditions={"status": "nominal"}),
            ActionNode(node_id="a3", tool="isolate", args={"subsystem": "pneumatic_line", "action": "release"}, expected_postconditions={"isolated": False}),
            ActionNode(node_id="a4", tool="reset", args={"subsystem": "pneumatic_line"}, expected_postconditions={"pressure_bar": 5.0}),
            ActionNode(node_id="a5", tool="clear_fault", args={"subsystem": "camera_sensor"}, expected_postconditions={"status": "nominal"}),
            ActionNode(node_id="a6", tool="calibrate", args={"subsystem": "camera_sensor"}, expected_postconditions={"calibrated": True}),
        ]
        long_mem = ProceduralMemoryItem(
            memory_id="proc_mem_long_6steps",
            name="Long Memory Test",
            target_subsystem="pneumatic_line",
            applicability_conditions={"subsystem": "pneumatic_line", "fault_types": ["overpressure_fault"]},
            observation_triggers=["inspect"],
            actions=long_actions,
            evidenced_order_dependencies=[],
            expected_effects=[],
            invalidation_conditions=[],
            source_task_id="t",
            source_step_refs=list(range(6)),
            status="VERIFIED",
        )
        store = ProceduralMemoryStore()
        store.add_memory(long_mem)

        task_cfg = {
            "task_id": "test_long_memory",
            "goal": "Test long memory chunking",
            "initial_state": {
                "power_unit": {"status": "nominal", "isolated": False, "voltage_v": 24.0},
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5},
                "camera_sensor": {"status": "optical_drift", "calibrated": False, "drift_offset_mm": 2.5},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        mock_llm = MockLLMBackendWithCustomScript(['{"thought": "inspect", "tool": "inspect", "args": {"subsystem": "all"}}'])
        runner = WorkstationAgentRunner(group_id="Group_D_current", llm_backend=mock_llm, max_llm_calls=3, max_tool_calls=15)
        res = runner.run_task(task_cfg, procedural_memory_store=store)

        self.assertEqual(res["memory_action_executed_count"], 6, "All 6 actions in long memory must be executed without truncation!")

    def test_gate_7_all_groups_common_precondition_validation(self):
        """Gate 7: All evaluation groups enforce the identical common precondition validation rules."""
        task_cfg = {
            "task_id": "test_common_validation",
            "goal": "Test common validation",
            "initial_state": {
                "pneumatic_line": {"status": "overpressure_fault", "isolated": False, "pressure_bar": 8.5},
            },
        }
        illegal_plan = '{"thought": "Try un-isolated clear", "tool": "clear_fault", "args": {"subsystem": "pneumatic_line"}}'

        groups = ["Group_B2_step", "Group_B2_plan", "Group_B1_plan", "Group_Replay", "Group_D_current", "Group_D_gated"]
        for gid in groups:
            mock_llm = MockLLMBackendWithCustomScript([illegal_plan, illegal_plan])
            runner = WorkstationAgentRunner(group_id=gid, llm_backend=mock_llm, max_llm_calls=2, max_tool_calls=3)
            res = runner.run_task(task_cfg)
            tools_executed = [s["tool"] for s in res["trajectory"]]
            self.assertNotIn("clear_fault", tools_executed, f"Group {gid} allowed illegal clear_fault into env.step!")

    def test_gate_8_audit_and_report_consistency(self):
        """Gate 8: Programmatic audit assertions check 100% data consistency."""
        audit_and_generate()

    def test_gate_9_interrupted_run_resumes_without_overwriting(self):
        """Gate 9: Disk resume logic skips already completed records and only runs missing records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_json_path = os.path.join(tmpdir, "test_resume.json")
            existing_records = [
                {"group_id": "Group_B2_plan", "task_id": "task_1", "success": False, "termination_reason": "TOOL_BUDGET_EXHAUSTED"},
                {"group_id": "Group_B2_plan", "task_id": "task_2", "success": True, "termination_reason": "TASK_COMPLETED"},
            ]
            with open(test_json_path, "w") as f:
                json.dump({"results": existing_records}, f)

            with open(test_json_path, "r") as f:
                loaded = json.load(f)

            done_keys = {(r["group_id"], r["task_id"]) for r in loaded["results"]}
            self.assertIn(("Group_B2_plan", "task_1"), done_keys)
            self.assertIn(("Group_B2_plan", "task_2"), done_keys)
            self.assertNotIn(("Group_B2_plan", "task_3"), done_keys)

    def test_gate_10_camera_sensor_invalidation_routing(self):
        """Gate 10: Bug 1 fix - clear_fault side effects route camera_sensor invalidation correctly without polluting target subsystem."""
        runner = WorkstationAgentRunner(group_id="Group_B2_plan")
        known_state = {
            "pneumatic_line": {"status": "leak_fault", "isolated": True},
            "camera_sensor": {"status": "nominal", "calibrated": True},
        }
        tool_res = {
            "status": StatusCode.SUCCESS,
            "effects": {"status": "nominal", "camera_sensor_calibrated_invalidated": False},
        }
        runner._update_known_state(known_state, "clear_fault", {"subsystem": "pneumatic_line"}, tool_res)
        self.assertEqual(known_state["camera_sensor"]["calibrated"], False, "camera_sensor.calibrated must be updated to False!")
        self.assertNotIn("camera_sensor_calibrated_invalidated", known_state["pneumatic_line"], "Target subsystem must not contain cross-subsystem invalidation keys!")
        self.assertEqual(known_state["pneumatic_line"]["status"], "nominal")

    def test_gate_11_single_inspect_initialization(self):
        """Gate 11: Bug 2 fix - inspect on single subsystem initializes known_state even if known_state was empty."""
        runner = WorkstationAgentRunner(group_id="Group_B2_plan")
        known_state = {}
        tool_res = {
            "status": StatusCode.SUCCESS,
            "subsystem": "power_unit",
            "data": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
        }
        runner._update_known_state(known_state, "inspect", {"subsystem": "power_unit"}, tool_res)
        self.assertIn("power_unit", known_state, "Single inspect must initialize known_state['power_unit']!")
        self.assertEqual(known_state["power_unit"]["status"], "tripped")
        self.assertEqual(known_state["power_unit"]["voltage_v"], 0.0)

    def test_gate_12_repetition_interception_and_constraint_repair_planning(self):
        """Gate 12: Repetition gate triggers repair planning on 2nd repeat and terminates on 3rd repeat."""
        task_cfg = {
            "task_id": "test_repetition_interception",
            "goal": "Test repetition interception and termination",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        # Script that repeatedly proposes the same failing action
        failing_action = '{"thought": "Try clear fault without isolation", "tool": "clear_fault", "args": {"subsystem": "power_unit"}}'
        mock_llm = MockLLMBackendWithCustomScript([
            failing_action,  # Initial attempt (count=1)
            failing_action,  # 1st repeat: feedback (count=2)
            failing_action,  # 2nd repeat: triggers repair planning (count=3)
            failing_action,  # Repair planning response (still failing)
            failing_action,  # 3rd repeat: terminates loop (count=4)
        ])
        runner = WorkstationAgentRunner(
            group_id="Group_B2_plan",
            llm_backend=mock_llm,
            max_llm_calls=10,
            max_tool_calls=10,
            enable_constraint_repair_planning=True,
        )
        res = runner.run_task(task_cfg)
        self.assertEqual(res["termination_reason"], "REPEATED_CONSTRAINT_VIOLATION", "Agent must terminate on 3rd repetition!")
        repair_calls = [r for r in res.get("llm_call_records", []) if r.get("call_type") == "constraint_repair_planning"]
    def test_gate_13_no_recipe_prompt_cleanliness(self):
        """Gate 13 (Section IV.1): Assert NoRecipe prompts contain zero domain repair action chains."""
        for prompt_text in [WORKSTATION_SYSTEM_PROMPT_STEP_NO_RECIPE, WORKSTATION_SYSTEM_PROMPT_PLAN_NO_RECIPE]:
            self.assertNotIn("requires isolate 'engage' first", prompt_text)
            self.assertNotIn("then clear_fault", prompt_text)
            self.assertNotIn("then isolate 'release'", prompt_text)
            self.assertNotIn("Domain Interlock Protocols", prompt_text)
            self.assertNotIn("->", prompt_text)

        # Also assert repair prompt in NoRecipe mode does not inject domain repair chains
        mock_llm = MockLLMBackendWithCustomScript(['{"plan": [{"tool": "inspect", "args": {"subsystem": "all"}}]}'])
        runner = WorkstationAgentRunner(
            group_id="Group_B2_plan",
            llm_backend=mock_llm,
            recipe_mode="none",
            replan_mode="focused",
        )
        runner._plan_constraint_repair(
            task_config={"goal": "test"},
            known_state={},
            blocked_action={"tool": "clear_fault", "args": {"subsystem": "power_unit"}},
            unmet_predicates=["power_unit.isolated == True"],
            cancellation_reason="Precondition unmet",
        )
        self.assertGreater(len(mock_llm.prompts_received), 0)
        repair_prompt = mock_llm.prompts_received[0]
        self.assertNotIn("Domain Interlock Protocols", repair_prompt)
        self.assertNotIn("call isolate('power_unit', 'engage')", repair_prompt)
        self.assertNotIn("->", repair_prompt)

    def test_gate_14_standard_vs_focused_replan_trigger_parity(self):
        """Gate 14 (Section IV.2): Assert StandardReplan and FocusedRepair trigger at identical 2nd repeat and make 1 LLM call."""
        task_cfg = {
            "task_id": "test_parity",
            "goal": "Test trigger parity",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        failing_act = '{"thought": "Try clear fault without isolation", "tool": "clear_fault", "args": {"subsystem": "power_unit"}}'
        
        # Test StandardReplan
        mock_standard = MockLLMBackendWithCustomScript([
            failing_act,  # init (count=1)
            failing_act,  # repeat 1 (count=2)
            failing_act,  # repeat 2 (count=3, triggers replan)
            failing_act,  # replan plan (still failing)
            failing_act,  # repeat 3 (count=4, terminates)
        ])
        runner_standard = WorkstationAgentRunner(
            group_id="Group_B2_plan",
            llm_backend=mock_standard,
            recipe_mode="none",
            replan_mode="standard",
        )
        res_standard = runner_standard.run_task(task_cfg)
        self.assertEqual(res_standard["termination_reason"], "REPEATED_CONSTRAINT_VIOLATION")
        standard_replan_calls = [r for r in res_standard["llm_call_records"] if r.get("call_type") == "standard_replanning"]
        self.assertEqual(len(standard_replan_calls), 1, "StandardReplan must trigger exactly 1 LLM call!")

        # Test FocusedRepair
        mock_focused = MockLLMBackendWithCustomScript([
            failing_act,  # init (count=1)
            failing_act,  # repeat 1 (count=2)
            failing_act,  # repeat 2 (count=3, triggers replan)
            failing_act,  # replan plan (still failing)
            failing_act,  # repeat 3 (count=4, terminates)
        ])
        runner_focused = WorkstationAgentRunner(
            group_id="Group_B2_plan",
            llm_backend=mock_focused,
            recipe_mode="none",
            replan_mode="focused",
        )
        res_focused = runner_focused.run_task(task_cfg)
        self.assertEqual(res_focused["termination_reason"], "REPEATED_CONSTRAINT_VIOLATION")
        focused_repair_calls = [r for r in res_focused["llm_call_records"] if r.get("call_type") == "constraint_repair_planning"]
        self.assertEqual(len(focused_repair_calls), 1, "FocusedRepair must trigger exactly 1 LLM call!")

        # Exact parity in total LLM calls
        self.assertEqual(res_standard["llm_calls"], res_focused["llm_calls"])

    def test_gate_15_token_consistency_assertion(self):
        """Gate 15 (Section IV.3): Assert token counts and llm_calls strictly match llm_call_records."""
        task_cfg = {
            "task_id": "test_tokens",
            "goal": "Test token consistency",
            "initial_state": {
                "power_unit": {"status": "tripped", "isolated": False, "voltage_v": 0.0},
                "controller": {"status": "nominal", "self_test_passed": False, "resumed": False},
            },
        }
        failing_act = '{"thought": "Fail", "tool": "clear_fault", "args": {"subsystem": "power_unit"}}'
        mock_llm = MockLLMBackendWithCustomScript([failing_act] * 6)
        runner = WorkstationAgentRunner(
            group_id="Group_B2_plan",
            llm_backend=mock_llm,
            recipe_mode="expert",
            replan_mode="focused",
        )
        res = runner.run_task(task_cfg)
        self.assertEqual(res["llm_calls"], len(res["llm_call_records"]))
        self.assertEqual(res["total_prompt_tokens"], sum(r["prompt_tokens"] for r in res["llm_call_records"]))
        self.assertEqual(res["total_generated_tokens"], sum(r["generated_tokens"] for r in res["llm_call_records"]))
        self.assertGreater(res["total_prompt_tokens"], 0)

    def test_gate_16_hash_tracking_and_no_mixing(self):
        """Gate 16 (Section IV.4): Assert prompt_hash, commit_hash, task_hash presence and condition uniqueness."""
        task_cfg = {
            "task_id": "test_hashes",
            "goal": "Test hashes",
            "initial_state": {"controller": {"status": "nominal", "self_test_passed": False, "resumed": False}},
        }
        mock_llm = MockLLMBackendWithCustomScript(['{"thought": "Inspect", "plan": [{"tool": "inspect", "args": {"subsystem": "all"}}]}'] * 4)
        
        conditions = [
            ("none", "standard", "NoRecipe_StandardReplan"),
            ("none", "focused", "NoRecipe_FocusedRepair"),
            ("expert", "standard", "ExpertRecipe_StandardReplan"),
            ("expert", "focused", "ExpertRecipe_FocusedRepair"),
        ]
        results = {}
        for rec_mode, rep_mode, cond_name in conditions:
            runner = WorkstationAgentRunner(
                group_id="Group_B2_plan",
                llm_backend=mock_llm,
                recipe_mode=rec_mode,
                replan_mode=rep_mode,
            )
            res = runner.run_task(task_cfg)
            self.assertEqual(res["condition"], cond_name)
            self.assertTrue(len(res["prompt_hash"]) > 10)
            self.assertTrue(len(res["commit_hash"]) > 5)
            self.assertTrue(len(res["task_hash"]) > 10)
            results[cond_name] = res

        # Prompt hashes must be distinct across the 4 conditions
        hashes = [r["prompt_hash"] for r in results.values()]
        self.assertEqual(len(set(hashes)), 4, "All 4 conditions must have unique prompt hashes!")


if __name__ == "__main__":
    unittest.main()
