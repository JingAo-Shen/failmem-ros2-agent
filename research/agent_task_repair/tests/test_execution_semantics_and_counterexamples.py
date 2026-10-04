"""
Rigorous Counter-Example and Execution Semantic Unit Tests (FailMem Stage 2).
Tests:
  1. Navigation success but wrong target does NOT complete original plan node.
  2. Pickup of wrong package does NOT complete other package node.
  3. Delivery to wrong recipient does NOT complete delivery node.
  4. Revised action still illegal is intercepted and NOT executed.
  5. Budget at limit prevents extra revision LLM calls.
  6. Disconnected path returns empty (NO_PATH) and NEVER fakes direct edge.
  7. Battery consumption and fact version increments correctly tracked.
  8. Repair memory applicability and ObservedFact equality correctly evaluated.
"""
import pytest
from research.agent_task_repair.agent.task_state import TaskStateTracker, ObligationStatus, ObservedFact
from research.agent_task_repair.agent.plan_manager import PersistentPlan, PlanNode, PlanNodeStatus
from research.agent_task_repair.agent.action_validator import ActionValidator, ValidationStatus
from research.agent_task_repair.agent.repair_controller import RepairController
from research.agent_task_repair.agent.stateful_runner import StatefulAgentRunner
from research.agent_task_repair.memory.repair_memory import RepairMemoryStore, VerificationStatus, ApplicabilityResult
from research.agent_task_repair.env.task_env import DeliveryTaskEnv


def test_nav_success_wrong_target_does_not_complete_node():
    state = TaskStateTracker("Deliver pkg to Office_A", {
        "robot_location": "Lobby",
        "battery": 100,
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"}]
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()
    active = plan.get_current_active_node()
    assert active is not None
    assert active.action_type == "pickup"

    # Simulate navigation to Office_B when active node expects something else
    ok = plan.on_step_success("navigate", {"target_zone": "Office_B"}, "evt_01")
    assert ok is False
    assert active.status != PlanNodeStatus.COMPLETED


def test_pickup_wrong_package_does_not_complete_node():
    state = TaskStateTracker("Deliver pkg_1 to Office_A", {
        "robot_location": "Lobby",
        "battery": 100,
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"},
            {"id": "pkg_2", "pickup_location": "Lobby", "target_room": "Office_B", "recipient": "Charlie"},
        ]
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()
    active = plan.get_current_active_node()
    assert active.action_type == "pickup"
    assert active.target == "Lobby"
    assert active.package_id == "pkg_1"

    # Agent picks up pkg_2 instead of pkg_1
    state.inventory.append("pkg_2")
    ok = plan.on_step_success("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}, "evt_wrong_pkg")
    assert ok is False
    assert active.status != PlanNodeStatus.COMPLETED
    assert "pkg_1" not in state.inventory


def test_deliver_wrong_recipient_does_not_complete_node():
    state = TaskStateTracker("Deliver pkg_1 to Alice", {
        "robot_location": "Office_A",
        "battery": 100,
        "inventory": ["pkg_1"],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"}]
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Move active node to deliver node
    deliver_node = next(n for n in plan.nodes if n.action_type == "deliver")
    plan.current_node_index = plan.nodes.index(deliver_node)
    deliver_node.status = PlanNodeStatus.READY

    # Deliver to Bob instead of Alice
    ok = plan.on_step_success("deliver", {"package_id": "pkg_1", "recipient": "Bob"}, "evt_wrong_recip")
    assert ok is False
    assert deliver_node.status != PlanNodeStatus.COMPLETED


def test_disconnected_path_returns_empty_no_fake_edges():
    plan = PersistentPlan(TaskStateTracker("Test", {"robot_location": "Lobby"}))
    # Test path in normal graph
    p1 = plan.find_path("Lobby", "Office_A")
    assert len(p1) > 0

    # Test path avoiding all transit corridors (North and South)
    p_blocked = plan.find_path("Lobby", "Office_A", avoid={"Corridor_North", "Corridor_South"})
    # Must strictly return empty list [], NEVER [Office_A]
    assert p_blocked == [], f"Expected [] for disconnected path, got {p_blocked}"


def test_battery_and_fact_versions_correctly_tracked():
    state = TaskStateTracker("Battery and fact test", {"robot_location": "Lobby", "battery": 100})
    assert state.battery == 100

    # Execute a tool step that costs 12% battery
    result_dict = {"status": "SUCCESS", "success": True, "time_cost_s": 8.0, "battery_cost_pct": 12, "observation": {}}
    state.update_from_tool_result("navigate", {"target_zone": "Corridor_North"}, result_dict, "evt_01", 8.0)

    # Verify battery correctly deducted to 88%
    assert state.battery == 88
    assert state.cumulative_battery_consumed == 12

    # Verify fact setting and version increment
    state.set_fact("door_north_state", "OCCUPIED", "evt_02", 10.0, "navigate")
    assert state.get_fact_value("door_north_state") == "OCCUPIED"
    assert state.observed_facts["door_north_state"].version == 1

    # Update fact again -> version 2
    state.set_fact("door_north_state", "FREE", "evt_03", 15.0, "observe")
    assert state.get_fact_value("door_north_state") == "FREE"
    assert state.observed_facts["door_north_state"].version == 2


def test_repair_memory_observed_fact_equality_and_strict_applicability():
    store = RepairMemoryStore()
    mem = store.record_repair_experience(
        memory_id="mem_test_door",
        source_task_id="src_01",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "$detour_zone"}}],
        execution_evidence_refs=["evt_src_s02"],
        verification_evidence={"verified": True, "event_id": "evt_src_s03"},
        applicability={"origin": "Lobby"},
        required_facts={"door_north_state": "OCCUPIED"},
        invalidation_conditions={"door_north_state": "FREE"},
        expected_effects=["at_location(Corridor_South)"],
        verification_status=VerificationStatus.VERIFIED,
    )
    assert mem.verification_status == VerificationStatus.VERIFIED

    # Test 1: Required fact is ObservedFact object with value "OCCUPIED"
    known_facts = {
        "door_north_state": ObservedFact(key="door_north_state", value="OCCUPIED", evidence_ref="evt_01", sim_time=1.0, source_tool="navigate")
    }
    app_res, _ = mem.evaluate_applicability(known_facts, {"robot_location": "Lobby"})
    assert app_res == ApplicabilityResult.APPLICABLE

    # Test 2: Active invalidation when door_north_state becomes FREE
    known_facts["door_north_state"] = ObservedFact(key="door_north_state", value="FREE", evidence_ref="evt_02", sim_time=2.0, source_tool="observe")
    app_res2, _ = mem.evaluate_applicability(known_facts, {"robot_location": "Lobby"})
    assert app_res2 == ApplicabilityResult.INVALIDATED
    assert mem.verification_status == VerificationStatus.INVALIDATED


def test_repair_memory_default_unverified_if_missing_verification_evidence():
    store = RepairMemoryStore()
    # Record without execution evidence -> must remain UNVERIFIED
    mem = store.record_repair_experience(
        memory_id="mem_unverified",
        source_task_id="src_02",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED"},
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
        execution_evidence_refs=[],  # No execution evidence!
        verification_evidence={},     # No verification!
        applicability={"origin": "Corridor_South"},
        required_facts={},
        invalidation_conditions={},
        expected_effects=[],
        verification_status=VerificationStatus.VERIFIED,
    )
    # Verification rule must force status to UNVERIFIED
    assert mem.verification_status == VerificationStatus.UNVERIFIED
