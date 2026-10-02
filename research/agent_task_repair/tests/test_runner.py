"""
Unit tests for AgentPlanner, PilotScorer, and Runner in FailMem Stage 2.
"""
import pytest
from pathlib import Path
from research.agent_task_repair.env.scenarios import get_development_scenarios
from research.agent_task_repair.agent.planner import AgentPlanner
from research.agent_task_repair.agent.llm_backend import LLMBackend
from research.agent_task_repair.memory.baselines import B0_NoMemory
from research.agent_task_repair.eval.scorer import PilotScorer
from research.agent_task_repair.eval.runner import run_benchmark
from research.agent_task_repair.eval.generate_report import generate_pilot_report


def test_strict_parser_no_heuristic_guessing():
    """Verify that parser does NOT guess actions from unformatted raw natural language."""
    llm = LLMBackend(model_path=None, allow_fallback=True)
    planner = AgentPlanner(llm, B0_NoMemory())

    # Raw conversational text with action mentions but no JSON
    raw_text = "I think I should navigate to Corridor_South to avoid the door, then pickup pkg_docs."
    decision, parse_ok = planner._strict_parse_json(raw_text)
    assert parse_ok is False
    assert decision == {}, "Parser must return empty dict on malformed input, never guess parameters."

    # Valid JSON
    valid_json = '```json\n{\n  "decision_summary": "Moving to Corridor_North",\n  "action": "navigate",\n  "params": {"target_zone": "Corridor_North"}\n}\n```'
    decision2, parse_ok2 = planner._strict_parse_json(valid_json)
    assert parse_ok2 is True
    assert decision2["action"] == "navigate"
    assert decision2["params"]["target_zone"] == "Corridor_North"


def test_scorer_grounded_metrics():
    """Verify that PilotScorer computes grounded detour, cumulative battery, and repeated failures."""
    mock_runs = [
        {
            "task_id": "t0",
            "success": False,
            "constraint_violations": ["DOORWAY_BLOCKED"],
            "step_count": 2,
            "battery_consumed": 15,
            "sim_time_s": 20.0,
            "wall_time_s": 1.2,
            "llm_calls": 2,
            "step_history": [
                {"step": 1, "tool": "navigate", "params": {"target_zone": "Corridor_North"}, "result": {"success": False, "error_code": "DOORWAY_BLOCKED"}},
                {"step": 2, "tool": "navigate", "params": {"target_zone": "Corridor_North"}, "result": {"success": False, "error_code": "DOORWAY_BLOCKED"}},
            ],
            "llm_traces": [{"prompt_tokens": 100, "generated_tokens": 20}, {"prompt_tokens": 120, "generated_tokens": 25}],
        },
        {
            "task_id": "t1",
            "success": True,
            "constraint_violations": [],
            "step_count": 3,
            "battery_consumed": 22,
            "sim_time_s": 25.0,
            "wall_time_s": 1.5,
            "llm_calls": 3,
            "step_history": [
                # Unwarranted detour: navigating via Corridor_South in task 1
                {"step": 1, "tool": "navigate", "params": {"target_zone": "Corridor_South"}, "robot_location_before": "Lobby", "env_state_snapshot": {"doors": {"door_north": {"blocked": False}}}, "result": {"success": True}},
                {"step": 2, "tool": "navigate", "params": {"target_zone": "Office_A"}, "robot_location_before": "Corridor_South", "result": {"success": True}},
                {"step": 3, "tool": "deliver", "params": {"package_id": "pkg_docs", "recipient": "Alice"}, "robot_location_before": "Office_A", "result": {"success": True}},
            ],
            "llm_traces": [{"prompt_tokens": 100, "generated_tokens": 20}],
        },
    ]

    score = PilotScorer.score_sequence_results(mock_runs)
    assert score["total_tasks"] == 2
    assert score["task_success_rate"] == 0.5
    assert score["sequence_full_success"] == 0.0
    assert score["acquisition_task_success"] == 0.0
    assert score["evaluation_task_success_rate"] == 1.0
    assert score["total_battery_consumed"] == 37  # 15 + 22
    assert score["repeated_failures"] == 1        # navigate:Corridor_North repeated once
    assert score["unwarranted_detour_count"] == 1 # Corridor_South chosen in task 1
    assert score["total_llm_calls"] == 5


def test_dev_benchmark_execution_with_fallback(tmp_path):
    """Verify that benchmark runner executes cleanly on development scenarios."""
    dev_scenarios = get_development_scenarios()
    res = run_benchmark(
        model_path=None,
        output_dir=str(tmp_path),
        output_filename="test_dev_results.json",
        device="cpu",
        scenarios=dev_scenarios,
        allow_fallback=True,
    )
    assert res["total_units_evaluated"] == len(dev_scenarios) * 5
    assert "method_aggregates" in res
    assert "F" in res["method_aggregates"]
    assert res["method_aggregates"]["F"]["total_tokens"] > 0
