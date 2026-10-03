"""
Unit tests for PublicTaskSkeleton and Task Dependency Tracking.
Zero model calls required.
"""
import pytest
from research.agent_task_repair.agent.task_skeleton import PublicTaskSkeleton, DeliveryObligation
from research.agent_task_repair.agent.planner import MAP_ADJACENCY


def test_skeleton_preserves_pickup_obligation_after_nav_failure():
    """Verify that a navigation failure event never erases or modifies pending pickup obligations."""
    skeleton = PublicTaskSkeleton(MAP_ADJACENCY, max_inventory_capacity=2)
    current_state = {
        "robot_location": "Lobby",
        "battery": 90,
        "inventory": [],
        "credentials": [],
        "available_packages": [
            {"id": "pkg_parts", "pickup_location": "Lobby", "target_room": "Office_B", "recipient": "Charlie"}
        ],
    }
    step_history = [
        {
            "step": 1,
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"status": "DOOR_BLOCKED", "success": False, "error_code": "DOORWAY_BLOCKED"},
        }
    ]
    known_state = {"door_north_state": "OCCUPIED"}

    obligations = skeleton.parse_obligations(current_state, step_history)
    assert len(obligations) == 1
    assert obligations[0].package_id == "pkg_parts"
    assert obligations[0].is_delivered is False
    assert obligations[0].in_inventory is False
    assert obligations[0].status_str == "AT_PICKUP_LOCATION (Lobby)"

    eval_res = skeleton.evaluate_dependencies(current_state, known_state, obligations)
    # The candidate subgoals must clearly include PICKUP_PACKAGE at Lobby
    pickup_subgoals = [sg for sg in eval_res["candidate_subgoals"] if sg["action_type"] == "pickup"]
    assert len(pickup_subgoals) == 1
    assert pickup_subgoals[0]["package_id"] == "pkg_parts"
    assert pickup_subgoals[0]["target"] == "Lobby"


def test_skeleton_inventory_capacity_precondition():
    """Verify that when inventory is full (capacity=2), pickup dependencies are marked unsatisfied."""
    skeleton = PublicTaskSkeleton(MAP_ADJACENCY, max_inventory_capacity=2)
    current_state = {
        "robot_location": "Lobby",
        "battery": 80,
        "inventory": ["pkg_1", "pkg_2"],
        "credentials": [],
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"},
            {"id": "pkg_2", "pickup_location": "Lobby", "target_room": "Office_B", "recipient": "Charlie"},
            {"id": "pkg_3", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"},
        ],
    }
    step_history = []
    known_state = {}

    obligations = skeleton.parse_obligations(current_state, step_history)
    eval_res = skeleton.evaluate_dependencies(current_state, known_state, obligations)

    # Robot cannot pickup pkg_3 because inventory is full
    pickup_subgoals = [sg for sg in eval_res["candidate_subgoals"] if sg["action_type"] == "pickup"]
    assert len(pickup_subgoals) == 0, "No pickup subgoals should be candidate when inventory is full."
    assert any("Inventory is full" in dep for dep in eval_res["unsatisfied_dependencies"])


def test_skeleton_delivery_requires_holding_package():
    """Verify that deliver requires holding package and being at target room."""
    skeleton = PublicTaskSkeleton(MAP_ADJACENCY, max_inventory_capacity=2)
    current_state = {
        "robot_location": "Office_B",
        "battery": 70,
        "inventory": [],
        "credentials": [],
        "available_packages": [
            {"id": "pkg_parts", "pickup_location": "Lobby", "target_room": "Office_B", "recipient": "Charlie"}
        ],
    }
    step_history = []
    known_state = {}

    obligations = skeleton.parse_obligations(current_state, step_history)
    eval_res = skeleton.evaluate_dependencies(current_state, known_state, obligations)

    # Cannot deliver because package is at Lobby, not in inventory
    deliver_subgoals = [sg for sg in eval_res["candidate_subgoals"] if sg["action_type"] == "deliver"]
    assert len(deliver_subgoals) == 0
    assert any("requires being at 'Office_B'" not in dep for dep in eval_res["unsatisfied_dependencies"])
    assert any("Must navigate to pickup location" in dep for dep in eval_res["unsatisfied_dependencies"])
