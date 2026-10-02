"""
Unit tests for DeliveryTaskEnv and Scenarios in FailMem Stage 2.
Verifies no information leakage, mathematical solvability, and environment accounting.
"""
import pytest
from research.agent_task_repair.env.task_env import DeliveryTaskEnv
from research.agent_task_repair.env.tools import StatusCode
from research.agent_task_repair.env.scenarios import (
    get_development_scenarios,
    verify_scenario_solvable,
)


def test_hidden_state_no_leak_in_prompt():
    """Verify that development scenario instructions do not leak hidden environment state."""
    forbidden_leak_terms = ["obstacle has been removed", "is blocked", "door_north is blocked", "does not require", "use corridor_south detour"]
    scenarios = get_development_scenarios()
    for seq in scenarios:
        for task in seq["tasks"]:
            inst_lower = task["instruction"].lower()
            for term in forbidden_leak_terms:
                assert term not in inst_lower, f"Information leakage detected in {task['task_id']}: '{term}' found in instruction."


def test_scenario_feasibility_solvability():
    """Verify that all development scenarios are mathematically solvable."""
    scenarios = get_development_scenarios()
    for seq in scenarios:
        solvable, issues = verify_scenario_solvable(seq)
        assert solvable is True, f"Scenario {seq['sequence_id']} failed feasibility check: {issues}"


def test_env_basic_navigation_and_energy_accumulation():
    """Verify energy accounting is strictly cumulative."""
    env = DeliveryTaskEnv({
        "robot_start_location": "Lobby",
        "robot_start_battery": 100,
    })
    assert env.cumulative_battery_consumed == 0
    res = env.step("navigate", {"target_zone": "Corridor_North"})
    assert res.success is True
    assert env.robot_location == "Corridor_North"
    assert env.cumulative_battery_consumed == res.battery_cost_pct
    assert env.battery == 100 - res.battery_cost_pct


def test_env_door_blocked():
    env = DeliveryTaskEnv({
        "robot_start_location": "Lobby",
        "doors": {
            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
        },
    })
    res = env.step("navigate", {"target_zone": "Corridor_North"})
    assert res.success is False
    assert res.status == StatusCode.DOOR_BLOCKED
    assert res.error_code == "DOORWAY_BLOCKED"
    assert env.robot_location == "Lobby"


def test_env_security_badge_requirement():
    env = DeliveryTaskEnv({
        "robot_start_location": "Corridor_South",
        "doors": {
            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
        },
        "robot_start_credentials": [],
    })
    res = env.step("navigate", {"target_zone": "Lab_Secure"})
    assert res.success is False
    assert res.status == StatusCode.ACCESS_DENIED_NO_BADGE

    env.credentials.add("security_badge")
    res2 = env.step("navigate", {"target_zone": "Lab_Secure"})
    assert res2.success is True
    assert env.robot_location == "Lab_Secure"


def test_env_pickup_and_delivery_lifecycle():
    env = DeliveryTaskEnv({
        "robot_start_location": "Lobby",
        "packages": {
            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
        },
        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
    })
    res_pk = env.step("pickup", {"package_id": "pkg_docs", "from_location": "Lobby"})
    assert res_pk.success is True
    assert "pkg_docs" in env.inventory

    env.step("navigate", {"target_zone": "Corridor_North"})
    env.step("navigate", {"target_zone": "Office_A"})
    assert env.robot_location == "Office_A"

    res_del = env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"})
    assert res_del.success is True
    assert "pkg_docs" not in env.inventory
    assert env.is_all_delivered() is True
