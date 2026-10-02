"""
Regression unit tests for PilotScorer in FailMem Stage 2.
Verifies all Phase A requirements:
  - All failures, partial success, empty evaluation set;
  - Legal detour vs unwarranted detour;
  - Event vs task-level violation counting;
  - Missing data handling.
"""
import pytest
from research.agent_task_repair.eval.scorer import PilotScorer


def test_scorer_empty_evaluation_set():
    """Verify that single-task sequence returns None / N/A for evaluation success."""
    single_task_run = [{
        "task_id": "t0",
        "success": True,
        "constraint_violations": [],
        "step_count": 3,
        "battery_consumed": 10,
        "sim_time_s": 15.0,
        "wall_time_s": 0.5,
        "llm_calls": 3,
        "step_history": [],
        "llm_traces": [],
    }]
    score = PilotScorer.score_sequence_results(single_task_run)
    assert score["total_tasks"] == 1
    assert score["task_success_rate"] == 1.0
    assert score["acquisition_task_success"] == 1.0
    assert score["evaluation_success_count"] is None
    assert score["evaluation_tasks_total"] == 0
    assert score["evaluation_task_success_rate"] is None


def test_scorer_all_failures_and_partial_success():
    """Verify calculation across all failures and mixed success."""
    # 3-task sequence, all fail
    all_fail_runs = [
        {"task_id": f"t{i}", "success": False, "constraint_violations": [], "step_count": 2, "battery_consumed": 5, "sim_time_s": 10.0, "wall_time_s": 0.2, "llm_calls": 2, "step_history": [], "llm_traces": []}
        for i in range(3)
    ]
    score_fail = PilotScorer.score_sequence_results(all_fail_runs)
    assert score_fail["task_success_rate"] == 0.0
    assert score_fail["sequence_full_success"] == 0.0
    assert score_fail["evaluation_success_count"] == 0
    assert score_fail["evaluation_tasks_total"] == 2
    assert score_fail["evaluation_task_success_rate"] == 0.0

    # 3-task sequence: T0 fail, T1 success, T2 success (Eval success: 2/2)
    mixed_runs = [
        {"task_id": "t0", "success": False, "constraint_violations": [], "step_count": 2, "battery_consumed": 5, "sim_time_s": 10.0, "wall_time_s": 0.2, "llm_calls": 2, "step_history": [], "llm_traces": []},
        {"task_id": "t1", "success": True, "constraint_violations": [], "step_count": 3, "battery_consumed": 8, "sim_time_s": 12.0, "wall_time_s": 0.3, "llm_calls": 3, "step_history": [], "llm_traces": []},
        {"task_id": "t2", "success": True, "constraint_violations": [], "step_count": 3, "battery_consumed": 8, "sim_time_s": 12.0, "wall_time_s": 0.3, "llm_calls": 3, "step_history": [], "llm_traces": []},
    ]
    score_mixed = PilotScorer.score_sequence_results(mixed_runs)
    assert score_mixed["task_success_rate"] == round(2/3, 4)
    assert score_mixed["sequence_full_success"] == 0.0
    assert score_mixed["evaluation_success_count"] == 2
    assert score_mixed["evaluation_tasks_total"] == 2
    assert score_mixed["evaluation_task_success_rate"] == 1.0


def test_scorer_legal_vs_unwarranted_detour():
    """Verify that taking Corridor_South when door_north is blocked is LEGAL, and only UNBLOCKED is unwarranted."""
    # Run 1: door_north is blocked (door_north.blocked = True) -> taking Corridor_South is LEGAL detour
    legal_detour_run = [{
        "task_id": "t0",
        "success": True,
        "constraint_violations": [],
        "step_count": 2,
        "battery_consumed": 20,
        "sim_time_s": 25.0,
        "wall_time_s": 1.0,
        "llm_calls": 2,
        "step_history": [
            {
                "step": 1,
                "tool": "navigate",
                "params": {"target_zone": "Corridor_South"},
                "robot_location_before": "Lobby",
                "env_state_snapshot": {"doors": {"door_north": {"blocked": True}}},
                "result": {"success": True, "status": "SUCCESS"},
            }
        ],
        "llm_traces": [],
    }]
    score_legal = PilotScorer.score_sequence_results(legal_detour_run)
    assert score_legal["unwarranted_detour_count"] == 0, "Legal detour when door is blocked must NOT be scored as unwarranted."

    # Run 2: door_north is clear (door_north.blocked = False) -> taking Corridor_South is UNWARRANTED detour
    unwarranted_detour_run = [{
        "task_id": "t0",
        "success": True,
        "constraint_violations": [],
        "step_count": 2,
        "battery_consumed": 20,
        "sim_time_s": 25.0,
        "wall_time_s": 1.0,
        "llm_calls": 2,
        "step_history": [
            {
                "step": 1,
                "tool": "navigate",
                "params": {"target_zone": "Corridor_South"},
                "robot_location_before": "Lobby",
                "env_state_snapshot": {"doors": {"door_north": {"blocked": False}}},
                "result": {"success": True, "status": "SUCCESS"},
            }
        ],
        "llm_traces": [],
    }]
    score_unwarranted = PilotScorer.score_sequence_results(unwarranted_detour_run)
    assert score_unwarranted["unwarranted_detour_count"] == 1


def test_scorer_event_vs_task_violations():
    """Verify that multiple violation events in 1 task count as 1 affected task."""
    run_with_multi_violations = [
        {
            "task_id": "t0",
            "success": False,
            "constraint_violations": [
                "BATTERY_DEPLETED: Robot ran out of battery.",
                "WRONG_RECIPIENT_DELIVERY: Handed pkg to Bob instead of Alice.",
            ],
            "step_count": 5,
            "battery_consumed": 100,
            "sim_time_s": 60.0,
            "wall_time_s": 2.0,
            "llm_calls": 5,
            "step_history": [],
            "llm_traces": [],
        },
        {
            "task_id": "t1",
            "success": True,
            "constraint_violations": [],
            "step_count": 3,
            "battery_consumed": 15,
            "sim_time_s": 20.0,
            "wall_time_s": 1.0,
            "llm_calls": 3,
            "step_history": [],
            "llm_traces": [],
        },
    ]
    score = PilotScorer.score_sequence_results(run_with_multi_violations)
    assert score["hard_violation_events"] == 2
    assert score["hard_violation_tasks"] == 1
    assert score["hard_violation_rate"] == 0.5 # 1 task out of 2
