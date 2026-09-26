import pytest
import os
import json
import numpy as np
from src.sim_env import RobotSimEnvironment
from src.failmem import FailureMemoryStore
from src.evaluate import run_evaluation

class TestR0DefectReproduction:
    """
    R0 Authenticity Audit Reproduction Tests (Revised per Lead Review).
    Each test sets up an exact scientific requirement and asserts proper behavior.
    Under current mock implementations, these tests fail with AssertionError due to
    specific architectural and logical defects. They are marked with
    @pytest.mark.xfail(raises=AssertionError, strict=True) to strictly bound and
    reproduce each defect without masking unexpected errors.
    """

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Mock defect: use_verifier is not wired to any verifier execution, event emission, or feedback"
    )
    def test_reproduce_verifier_interface_and_feedback_missing(self, tmp_path):
        """
        Verifier configuration check:
        When use_verifier=True, the system should invoke postcondition verification,
        emit verification events in the event log, and provide visible feedback to the agent.
        In current evaluate.py, use_verifier is never branched on in logic; no verification
        event is produced and no feedback is delivered to the agent.
        """
        task = {
            "id": "verifier_check_task",
            "goal_coord": [5.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 2
        }
        out_on = tmp_path / "out_on"
        out_off = tmp_path / "out_off"
        
        run_evaluation([task], use_memory=True, use_verifier=True, output_dir=str(out_on))
        run_evaluation([task], use_memory=True, use_verifier=False, output_dir=str(out_off))
        
        with open(out_on / "events.jsonl") as f:
            events_on = [json.loads(line) for line in f]
            
        # Scientific requirement: Verifier execution must emit verification events or provide feedback.
        # Current mock only emits a single episode-level record echoing the boolean flag.
        has_verification_events = any(e.get("event_type") == "verification" or "verifier_feedback" in e for e in events_on)
        assert has_verification_events, (
            "No verification events or visible verifier feedback found in run output when use_verifier=True. "
            "Verifier switch is not connected to any operational interface."
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in src/failmem.py:44 - map_ver <= current_map_version retrieves stale memories when map updates 1->2"
    )
    def test_reproduce_costmap_conditioned_memory_expiry(self):
        """
        Costmap-dependent memory expiry check:
        A failure memory conditioned on obstacle state at map_version=1 must expire and not
        be retrieved without re-verification once the map updates to version 2.
        In src/failmem.py:44, 'if map_ver <= current_map_version' (1 <= 2 is True)
        wrongly allows stale records to persist across environment changes.
        """
        store = FailureMemoryStore()
        # Record an obstacle recovery rule that depends on obstacle state at map_version=1
        store.record_failure({
            "id": "mem_costmap_v1",
            "symptom": "ERROR: Path blocked by dynamic obstacle.",
            "recovery_action": "clear_costmap",
            "map_version": 1
        })
        
        # Precondition check: valid under map_version 1
        action_v1 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=1)
        assert action_v1 == "clear_costmap", "Failed to retrieve active memory under original map version"
        
        # Map version increments to 2 (e.g., environment map reconstruction or obstacle layout update).
        # Scientific requirement: Conditioned memory from version 1 must not be retrieved under version 2.
        action_v2 = store.retrieve_recovery("ERROR: Path blocked by dynamic obstacle.", current_map_version=2)
        assert action_v2 is None, (
            f"Stale memory retrieved under map_version=2: '{action_v2}'. "
            "Line 44 uses '<=' allowing past map records to remain permanently valid."
        )
        store.close()

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in src/failmem.py:29 - unverified failure records default to RECOVERED"
    )
    def test_reproduce_unverified_record_defaulted_to_recovered(self):
        """
        Verification provenance check:
        Records lacking postcondition verification evidence must not be committed as RECOVERED.
        In src/failmem.py:29, rec.get('verified_outcome', 'RECOVERED') automatically marks
        unverified records as RECOVERED, and line 38 does not filter by verified status.
        """
        store = FailureMemoryStore()
        store.record_failure({
            "id": "unverified_entry",
            "symptom": "ERROR: Path blocked by dynamic obstacle.",
            "recovery_action": "clear_costmap"
            # verified_outcome is deliberately omitted
        })
        c = store.conn.cursor()
        c.execute("SELECT verified_outcome FROM failure_records WHERE id = 'unverified_entry'")
        stored_outcome = c.fetchone()[0]
        store.close()
        
        # Scientific requirement: unverified experiences must be marked UNVERIFIED, not RECOVERED
        assert stored_outcome != "RECOVERED", (
            f"Omitted verification status was defaulted to '{stored_outcome}' in SQLite store."
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in benchmark accounting: start==goal tasks bypass fault injection but are counted as recovered"
    )
    def test_reproduce_fault_exposure_accounting_start_equals_goal(self, tmp_path):
        """
        Fault exposure accounting check:
        Start==goal is a valid physical edge case, but in a fault-injection experiment scheduled
        at step 2, a robot starting at the goal reaches success at step 1 and never exposes step 2.
        The evaluator must track whether faults were actually exposed, rather than counting
        unexposed tasks as successful fault recoveries.
        """
        task = {
            "id": "fixture_robot_01",
            "goal_coord": [0.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 2
        }
        out_dir = tmp_path / "exposure_check"
        metrics = run_evaluation([task], use_memory=True, use_verifier=True, output_dir=str(out_dir))
        
        with open(out_dir / "events.jsonl") as f:
            event = json.loads(f.readline())
            
        # Preconditions: start == goal, so step 1 succeeded
        assert event["steps"] < 2, "Task took 2 or more steps unexpectedly"
        
        # Scientific requirement: The benchmark must record whether the injected fault was actually exposed.
        # It must NOT record recovery_success_rate = 1.0 when no fault was ever triggered.
        assert "fault_exposed" in event and event["fault_exposed"] is False, (
            "Benchmark failed to distinguish unexposed fault tasks from exposed ones, "
            f"crediting an unexposed task as recovery success (rate={metrics['recovery_success_rate']})."
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in src/sim_env.py:29 - fault is momentary and disappears at step_count != injected_step"
    )
    def test_reproduce_fault_persistence_on_active_task(self):
        """
        Fault persistence check:
        In an actively running navigation task (goal=[5.0, 0.0], distance > 2m), a physical
        path blockage injected at step 2 must persist until an effective recovery action is taken.
        Continuing blind navigation at step 3 without clearing the obstacle should fail.
        In src/sim_env.py:29, fault only checks 'step_count == injected_fault_step', so the
        obstacle disappears on step 3.
        """
        task = {
            "id": "active_persist_task",
            "goal_coord": [5.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "path_blocked",
            "injected_fault_step": 2
        }
        env = RobotSimEnvironment(task)
        
        # Step 1: navigate advances 2.0m to [2.0, 0.0]
        s1, m1, _ = env.step("navigate")
        assert s1 is True and not env.is_success(), "Precondition failed: task terminated prematurely at step 1"
        assert env.step_count == 1
        
        # Step 2: navigate encounters fault
        s2, m2, _ = env.step("navigate")
        assert s2 is False and "Path blocked" in m2, "Precondition failed: fault not triggered at step 2"
        assert not env.is_success(), "Precondition failed: task marked success upon fault"
        assert env.step_count == 2
        
        # Step 3: Blind navigate without recovery action (clear_costmap)
        s3, m3, _ = env.step("navigate")
        
        # Scientific requirement: The obstacle must persist; blind navigation must fail!
        assert s3 is False, (
            f"Blind navigation at step 3 succeeded with message '{m3}'. "
            "Obstacle vanished automatically because fault check was guarded only by step_count == 2."
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in src/sim_env.py:26,33 - navigate leaks internal relocated goal when params are omitted"
    )
    def test_reproduce_target_moved_parameter_and_state_leakage(self):
        """
        Target relocated ground truth leakage check:
        When a target moves, the agent must not automatically navigate to the new position
        without discovering it via observation.
        In src/sim_env.py:26, target defaults to 'self.goal' when params is None.
        When step 2 updates self.goal = [6.0, 1.0], subsequent navigate() calls with no params
        silently use the updated environment internal goal.
        """
        task = {
            "id": "leakage_test_task",
            "goal_coord": [5.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "fault_type": "target_moved",
            "injected_fault_step": 2
        }
        env = RobotSimEnvironment(task)
        env.step("navigate") # step 1: moves to [2.0, 0.0]
        assert not env.is_success()
        
        s2, m2, _ = env.step("navigate") # step 2: target relocates to [6.0, 1.0]
        assert s2 is False and "relocated" in m2
        assert not env.is_success()
        
        # Step 3: Agent calls navigate without passing destination params (as in evaluate.py:49)
        # Check whether environment navigates towards original target [5.0, 0.0] or leaks relocated [6.0, 1.0]
        pos_before = env.pos.copy()
        s3, m3, _ = env.step("navigate")
        step_delta = env.pos - pos_before
        
        # Heading towards original goal [5,0] from [2,0] would be purely in +x direction: [2.0, 0.0]
        # Heading towards leaked goal [6,1] from [2,0] has positive y component: delta_y > 0
        leaked_y_displacement = float(step_delta[1])
        assert leaked_y_displacement == 0.0, (
            f"Robot navigated with positive Y displacement ({leaked_y_displacement:.3f}) towards "
            f"the hidden relocated target {env.goal.tolist()} without receiving goal coordinates from agent."
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in src/sim_env.py:58 - is_success only checks distance < 0.3m, ignoring observation and stabilization"
    )
    def test_reproduce_success_condition_missing_checks(self):
        """
        Evaluation criteria check:
        is_success() must enforce postcondition verification (target observation and 2s stabilization),
        as claimed in feasibility.md. Current sim_env.py only evaluates distance < 0.3m.
        """
        task = {
            "id": "success_criteria_task",
            "goal_coord": [1.0, 0.0],
            "initial_robot_pos": [0.0, 0.0],
            "injected_fault_step": 99
        }
        env = RobotSimEnvironment(task)
        env.step("navigate") # reaches [1.0, 0.0], distance = 0.0 < 0.3m
        
        # Preconditions: robot has not executed observe(), nor has 2s elapsed
        # Scientific requirement: is_success should require explicit observation confirmation
        assert not env.is_success(), (
            "Task marked as successful purely on position distance < 0.3m, "
            "without requiring target observation or stabilization."
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=True,
        reason="Defect in src/evaluate.py:87-94 - empty task set returns 0.0 instead of None/null"
    )
    def test_reproduce_empty_task_metrics_return_zero_division(self, tmp_path):
        """
        Contract compliance check:
        Per EXECUTION-CONTRACT.md line 43, when denominator is 0, the metric must be null (None),
        not 0.0. Current evaluate.py uses max(total, 1), converting 0/0 into 0.0.
        """
        out_dir = tmp_path / "empty_run"
        metrics = run_evaluation([], output_dir=str(out_dir))
        
        assert metrics["recovery_success_rate"] is None, (
            f"Expected None for empty task recovery rate, got {metrics['recovery_success_rate']}"
        )
        assert metrics["repeat_failure_rate"] is None, (
            f"Expected None for empty task repeat failure rate, got {metrics['repeat_failure_rate']}"
        )
