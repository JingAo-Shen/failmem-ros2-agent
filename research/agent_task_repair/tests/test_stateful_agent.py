"""
Unit tests for Stateful Agent Architecture (Stage 2).
Tests:
  - TaskStateTracker (obligation lifecycle, epistemic fact recording, evidence refs)
  - ActionValidator (schema check, topology bounds, capacity preconditions, holding requirements)
  - PersistentPlan (plan decomposition, step advance, repair node insertion)
  - CompletionChecker (tool-evidence certification, violation detection)
  - RepairController (local repair synthesis, dead-loop abort prevention)
Zero LLM calls required.
"""
import pytest
from research.agent_task_repair.agent.task_state import TaskStateTracker, ObligationStatus
from research.agent_task_repair.agent.action_validator import ActionValidator, ValidationStatus
from research.agent_task_repair.agent.plan_manager import PersistentPlan, PlanNode, PlanNodeStatus
from research.agent_task_repair.agent.completion_checker import CompletionChecker
from research.agent_task_repair.agent.repair_controller import RepairController
from research.agent_task_repair.agent.planner import MAP_ADJACENCY


def test_task_state_tracker_lifecycle():
    initial_state = {
        "robot_location": "Lobby",
        "battery": 100,
        "inventory": [],
        "credentials": [],
        "max_inventory_capacity": 2,
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"}
        ],
    }
    tracker = TaskStateTracker("Deliver pkg_1 to Alice", initial_state)
    assert len(tracker.obligations) == 1
    assert tracker.obligations["pkg_1"].status == ObligationStatus.PENDING
    assert tracker.is_all_completed() is False

    # Simulate pickup
    tracker.update_from_tool_result(
        tool_name="pickup",
        params={"package_id": "pkg_1", "from_location": "Lobby"},
        result={"success": True, "observation": {"inventory": ["pkg_1"]}},
        event_id="evt_01",
        sim_time=3.0,
    )
    assert tracker.obligations["pkg_1"].status == ObligationStatus.ACTIVE
    assert "pkg_1" in tracker.inventory

    # Simulate deliver
    tracker.update_from_tool_result(
        tool_name="deliver",
        params={"package_id": "pkg_1", "recipient": "Alice"},
        result={"success": True, "observation": {"delivered_package": "pkg_1"}},
        event_id="evt_02",
        sim_time=15.0,
    )
    assert tracker.obligations["pkg_1"].status == ObligationStatus.DONE
    assert "pkg_1" not in tracker.inventory
    assert tracker.is_all_completed() is True


def test_action_validator_preconditions():
    validator = ActionValidator(MAP_ADJACENCY)
    current_state = {
        "robot_location": "Lobby",
        "battery": 100,
        "inventory": ["pkg_1", "pkg_2"],
        "max_inventory_capacity": 2,
        "credentials": [],
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"},
            {"id": "pkg_2", "pickup_location": "Lobby", "target_room": "Office_B", "recipient": "Charlie"},
            {"id": "pkg_3", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"},
        ],
    }
    known_facts = {}

    # 1. Capacity check: inventory full -> pickup must FAIL
    res = validator.validate_action("pickup", {"package_id": "pkg_3", "from_location": "Lobby"}, current_state, known_facts)
    assert res.status == ValidationStatus.FAIL
    assert "Inventory is full" in res.reason

    # 2. Topology check: non-adjacent navigation -> must FAIL
    res = validator.validate_action("navigate", {"target_zone": "Office_B"}, current_state, known_facts)
    assert res.status == ValidationStatus.FAIL
    assert "No direct transit connection" in res.reason

    # 3. Holding check: deliver package not held -> must FAIL
    res = validator.validate_action("deliver", {"package_id": "pkg_3", "recipient": "Alice"}, current_state, known_facts)
    assert res.status == ValidationStatus.FAIL
    assert "not holding package" in res.reason


def test_persistent_plan_lifecycle_and_repair():
    initial_state = {
        "robot_location": "Lobby",
        "battery": 100,
        "inventory": [],
        "credentials": [],
        "max_inventory_capacity": 2,
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"}
        ],
    }
    tracker = TaskStateTracker("Deliver pkg_1", initial_state)
    plan = PersistentPlan(tracker, MAP_ADJACENCY)
    plan.initialize_initial_plan()

    assert len(plan.nodes) >= 3
    node0 = plan.get_current_active_node()
    assert node0 is not None
    assert node0.action_type == "pickup"

    # Advance plan
    tracker.on_tool_success("pickup", {"package_id": "pkg_1"}, "evt_step1")
    plan.on_step_success("pickup", {"package_id": "pkg_1"}, "evt_step1")
    node1 = plan.get_current_active_node()
    assert node1 is not None
    assert node1.action_type == "navigate"

    # Insert repair node
    repair_node = PlanNode(
        id="repair_01",
        goal="Detour via Corridor_South",
        action_type="navigate",
        target="Corridor_South",
        params={"target_zone": "Corridor_South"},
        status=PlanNodeStatus.READY,
    )
    plan.insert_repair_nodes([repair_node], reason="Blocked doorway")
    assert plan.plan_version == 2
    active = plan.get_current_active_node()
    assert active.id == "repair_01"


def test_completion_checker_evidence():
    initial_state = {
        "robot_location": "Lobby",
        "battery": 100,
        "inventory": [],
        "credentials": [],
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"}
        ],
    }
    tracker = TaskStateTracker("Deliver pkg_1", initial_state)

    # Incomplete test
    ok, msg, _ = CompletionChecker.verify_completion(tracker, [], [])
    assert ok is False
    assert "Incomplete" in msg

    # Complete test
    tracker.obligations["pkg_1"].status = ObligationStatus.DONE
    step_history = [
        {"tool": "deliver", "params": {"package_id": "pkg_1", "recipient": "Alice"}, "result": {"success": True}}
    ]
    ok, msg, _ = CompletionChecker.verify_completion(tracker, step_history, [])
    assert ok is True
    assert "Success" in msg


def test_repair_controller_dead_loop_prevention():
    controller = RepairController(MAP_ADJACENCY, max_repeated_attempts=3)
    initial_state = {
        "robot_location": "Lobby",
        "battery": 100,
        "inventory": [],
        "credentials": [],
        "available_packages": [],
    }
    tracker = TaskStateTracker("Test", initial_state)
    plan = PersistentPlan(tracker, MAP_ADJACENCY)
    plan.initialize_initial_plan()

    # Attempt 1
    abort1, _, _ = controller.handle_failure("navigate", {"target_zone": "Corridor_North"}, "DOORWAY_BLOCKED", {}, tracker, plan)
    assert abort1 is False

    # Attempt 2
    abort2, _, _ = controller.handle_failure("navigate", {"target_zone": "Corridor_North"}, "DOORWAY_BLOCKED", {}, tracker, plan)
    assert abort2 is False

    # Attempt 3 (Identical state and evidence) -> must ABORT
    abort3, msg, _ = controller.handle_failure("navigate", {"target_zone": "Corridor_North"}, "DOORWAY_BLOCKED", {}, tracker, plan)
    assert abort3 is True
    assert "DEAD_LOOP_ABORT" in msg
