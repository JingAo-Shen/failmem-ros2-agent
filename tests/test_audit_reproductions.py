import pytest
import numpy as np
from src.sim_env import RobotSimEnvironment
from src.failmem import FailureMemoryStore
from src.evaluate import run_evaluation

class TestR0DefectReproduction:
    """
    R0 Authenticity Audit Reproduction Tests.
    Each test specifies the required scientific behavior.
    Under the current implementation, these tests fail due to critical design defects.
    They are marked with @pytest.mark.xfail(strict=True) to rigorously document and reproduce the defects.
    """

    @pytest.mark.xfail(strict=True, reason="Defect in src/evaluate.py: use_verifier is never checked or branched on, having zero effect on execution or feedback")
    def test_reproduce_verifier_toggle_affects_execution_and_feedback(self, tmp_path):
        """Verifier toggle (ON vs OFF) should alter postcondition verification events or agent decisions."""
        task = {
            "id": "test_t1",
            "goal_coord": [2.0, 2.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 2
        }
        out_on = tmp_path / "out_on"
        out_off = tmp_path / "out_off"
        
        m_on = run_evaluation([task], use_memory=True, use_verifier=True, output_dir=str(out_on))
        m_off = run_evaluation([task], use_memory=True, use_verifier=False, output_dir=str(out_off))
        
        # Scientific requirement: verifier toggle must affect verification behavior, events, or decisions
        # Currently, logic is 100% identical; use_verifier is only printed as an echo field in logs
        assert m_on["recovery_success_rate"] != m_off["recovery_success_rate"] or m_on["repeat_failure_rate"] != m_off["repeat_failure_rate"]

    @pytest.mark.xfail(strict=True, reason="Defect in src/failmem.py:44 - map_ver <= current_map_version retrieves stale memories on map version update")
    def test_reproduce_memory_expiry_when_map_version_updates_from_1_to_2(self):
        """When costmap/environment updates from version 1 to 2, old failure memory should expire and not be retrieved."""
        store = FailureMemoryStore()
        store.record_failure({
            "id": "m1",
            "symptom": "ERROR: Path blocked by dynamic obstacle.",
            "recovery_action": "clear_costmap",
            "map_version": 1
        })
        
        # At map_version 1, memory is valid
        assert store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=1) == "clear_costmap"
        
        # When environment changes to map_version 2, the old memory from version 1 must expire (return None)
        # BUG: src/failmem.py checks map_ver <= current_map_version (1 <= 2 is True), so it still returns the stale action!
        recovered_v2 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=2)
        assert recovered_v2 is None
        store.close()

    @pytest.mark.xfail(strict=True, reason="Defect in src/failmem.py:29 - unverified records default to 'RECOVERED', and retrieve_recovery does not check verification status")
    def test_reproduce_unverified_record_defaulted_to_recovered(self):
        """Unverified recovery experiences must not be recorded as verified RECOVERED, and unverified records must not be retrieved."""
        store = FailureMemoryStore()
        store.record_failure({
            "id": "m_unverified",
            "symptom": "ERROR: Path blocked by dynamic obstacle.",
            "recovery_action": "clear_costmap"
            # verified_outcome is omitted (no verification evidence provided)
        })
        c = store.conn.cursor()
        c.execute("SELECT verified_outcome FROM failure_records WHERE id = 'm_unverified'")
        row = c.fetchone()
        
        # Scientific requirement: missing verification evidence must NOT default to RECOVERED
        # BUG: line 29 has rec.get('verified_outcome', 'RECOVERED')
        assert row[0] != "RECOVERED"
        store.close()

    @pytest.mark.xfail(strict=True, reason="Defect in data/task-specs.jsonl & src/sim_env.py: start equals goal causes task to succeed before fault injection")
    def test_reproduce_start_equals_goal_avoids_fault_injection(self):
        """Task with start==goal should not trivially succeed at step 0/1 before fault step 2."""
        task = {
            "id": "fixture_robot_01",
            "goal_coord": [0.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 2
        }
        env = RobotSimEnvironment(task)
        
        # Scientific requirement: robot should have to navigate to goal; cannot already be at success before moving
        # BUG: distance is 0.0 < 0.3 at step 0!
        assert not env.is_success()
        succ, msg, _ = env.step("navigate")
        assert env.step_count >= 2, "Task completed before reaching injected fault step"

    @pytest.mark.xfail(strict=True, reason="Defect in src/sim_env.py:29 - fault only triggers when step_count == injected_fault_step; blind navigate passes at step 3")
    def test_reproduce_fault_disappears_enabling_blind_navigate(self):
        """A physical blockage should persist; continuing blind navigation without clearing obstacle should fail."""
        task = {
            "id": "persist_test",
            "goal_coord": [2.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 2
        }
        env = RobotSimEnvironment(task)
        env.step("navigate")  # step 1
        s2, m2, _ = env.step("navigate")  # step 2: fault triggers
        assert not s2, "Fault should trigger at step 2"
        
        # Step 3: Blind navigate without clear_costmap
        s3, m3, _ = env.step("navigate")
        # Scientific requirement: Obstacle should persist, blind navigation must fail!
        # BUG: step_count == 3 != 2, so fault vanishes and s3 is True!
        assert not s3, "Obstacle vanished after 1 step, allowing blind navigate to pass"

    @pytest.mark.xfail(strict=True, reason="Defect in src/sim_env.py:26,33 - navigate defaults to internal self.goal without requiring agent observation")
    def test_reproduce_target_moved_ground_truth_leakage(self):
        """When target relocates, agent should not automatically know new coordinates without observation."""
        task = {
            "id": "target_relocate_test",
            "goal_coord": [2.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "target_moved",
            "injected_fault_step": 2
        }
        env = RobotSimEnvironment(task)
        env.step("navigate")  # step 1
        env.step("navigate")  # step 2: target relocates to [3.0, 1.0]
        
        # Step 3: Agent calls navigate without explicit new goal parameter (as implemented in evaluate.py)
        # In current evaluate.py: env.step("navigate") is called with no params.
        # Inside sim_env.py: line 26 reads self.goal directly, navigating the robot straight to the moved target!
        succ, _, obs = env.step("navigate")
        # Scientific requirement: Agent has not observed or discovered new goal; cannot reach moved goal!
        # BUG: env.is_success() is True!
        assert not env.is_success(), "Agent reached moved goal via internal environment leakage without observation"

    @pytest.mark.xfail(strict=True, reason="Defect in src/sim_env.py:58 - is_success only checks distance < 0.3m, ignoring 2s stabilization time and observe action")
    def test_reproduce_success_condition_missing_stabilization_and_observation(self):
        """Success judgment must require target observation and 2s stabilization time as claimed in feasibility report."""
        task = {
            "id": "obs_time_test",
            "goal_coord": [1.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 99
        }
        env = RobotSimEnvironment(task)
        env.step("navigate")  # moves to [1.0, 0.0], distance = 0.0 < 0.3m
        
        # Scientific requirement: is_success should require observe() and 2s stabilization time
        # BUG: is_success returns True immediately without observe or time check
        assert not env.is_success(), "Task considered successful without target observation or stabilization verification"

    @pytest.mark.xfail(strict=True, reason="Defect in src/evaluate.py:87-94 - empty task set returns 0.0 instead of None/null")
    def test_reproduce_empty_task_metrics_return_zero_instead_of_null(self, tmp_path):
        """When task set is empty (denominator=0), metrics must output null/None, not 0.0 (per EXECUTION-CONTRACT.md:43)."""
        out_dir = tmp_path / "empty_run"
        metrics = run_evaluation([], output_dir=str(out_dir))
        
        # Scientific requirement: 0 denominator must yield None / null
        # BUG: max(total, 1) causes 0 / 1 = 0.0
        assert metrics["recovery_success_rate"] is None, f"Expected None but got {metrics['recovery_success_rate']}"
        assert metrics["repeat_failure_rate"] is None, f"Expected None but got {metrics['repeat_failure_rate']}"
