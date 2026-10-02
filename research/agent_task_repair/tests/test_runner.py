"""
Unit tests for PilotScorer and Runner on development tasks.
"""
import pytest
from research.agent_task_repair.env.scenarios import get_development_scenarios
from research.agent_task_repair.eval.runner import run_pilot_benchmark
from research.agent_task_repair.eval.scorer import PilotScorer


def test_dev_benchmark_execution(tmp_path):
    dev_scenarios = get_development_scenarios()
    res = run_pilot_benchmark(
        model_path=None,  # deterministic fallback
        output_dir=str(tmp_path),
        device="cpu",
        scenarios=dev_scenarios,
    )
    assert res["total_units_evaluated"] == len(dev_scenarios) * 5
    assert "method_aggregates" in res
    assert "B0" in res["method_aggregates"]
    assert "F" in res["method_aggregates"]
