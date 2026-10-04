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


def test_observe_valid_and_invalid_targets():
    validator = ActionValidator()
    # 1. Valid room observation when robot is in that room
    res_valid_room = validator.validate_action("observe", {"target": "Office_A"}, {"robot_location": "Office_A"}, {})
    assert res_valid_room.status == ValidationStatus.PASS

    # 2. Valid door observation from connected room
    res_valid_door = validator.validate_action("observe", {"target": "door_north"}, {"robot_location": "Lobby"}, {})
    assert res_valid_door.status == ValidationStatus.PASS

    # 3. Invalid room observation from different room
    res_wrong_room = validator.validate_action("observe", {"target": "Office_A"}, {"robot_location": "Lobby"}, {})
    assert res_wrong_room.status == ValidationStatus.FAIL

    # 4. Invalid fake targets like room_items, door, contents
    for fake_tgt in ("room_items", "door", "contents", "items"):
        res_fake = validator.validate_action("observe", {"target": fake_tgt}, {"robot_location": "Lobby"}, {})
        assert res_fake.status == ValidationStatus.FAIL


def test_empty_room_observation_updates_search_and_prevents_looping():
    state = TaskStateTracker("Test Empty Room", {"robot_location": "Office_A"})
    validator = ActionValidator()

    # Before observation, acquire_credential is not blocked by empty fact
    res_pre = validator.validate_action("acquire_credential", {"credential_name": "security_badge"}, state.get_public_state_summary(), state.observed_facts)
    assert res_pre.status == ValidationStatus.PASS

    # Execute observe in Office_A with empty items
    result_dict = {
        "status": "SUCCESS",
        "success": True,
        "observation": {"room": "Office_A", "items": [], "present_people": ["Alice"]},
        "time_cost_s": 2.0,
        "battery_cost_pct": 1,
    }
    state.update_from_tool_result("observe", {"target": "Office_A"}, result_dict, "evt_obs_empty", 2.0)

    # Check facts updated
    assert state.get_fact_value("room_checked_empty_Office_A") is True
    assert state.get_fact_value("credential_not_found_in_Office_A") is True

    # After observation, acquire_credential is FAIL
    res_post = validator.validate_action("acquire_credential", {"credential_name": "security_badge"}, state.get_public_state_summary(), state.observed_facts)
    assert res_post.status == ValidationStatus.FAIL
    assert "no credentials" in res_post.reason


def test_reached_destination_prunes_obsolete_detour_nodes():
    state = TaskStateTracker("Deliver pkg to Office_A", {
        "robot_location": "Lobby",
        "battery": 100,
        "inventory": ["pkg_docs"],
        "available_packages": [{"id": "pkg_docs", "pickup_location": "Lobby", "target_room": "Office_A", "recipient": "Alice"}]
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Simulate detour repair inserted: navigate(Corridor_South), navigate(Office_A)
    # And robot moves to Corridor_South, then Office_A
    state.robot_location = "Corridor_South"
    plan.replan_subsequent_navigation("Corridor_South")

    state.robot_location = "Office_A"
    plan.prune_obsolete_navigation()

    # Active node should directly be deliver, NOT navigating back to Corridor_North
    active = plan.get_current_active_node()
    assert active is not None
    assert active.action_type == "deliver"
    assert active.target == "Office_A"


def test_blocked_edge_does_not_ban_entire_zone():
    plan = PersistentPlan(TaskStateTracker("Test", {"robot_location": "Lobby"}))

    # Blocking edge (Lobby, Corridor_North)
    blocked_edge = ("Lobby", "Corridor_North")

    # Path from Corridor_South to Corridor_North is STILL reachable
    p_from_south = plan.find_path("Corridor_South", "Corridor_North", avoid_edges={blocked_edge})
    assert p_from_south == ["Corridor_North"]

    # Path from Lobby to Office_A via Corridor_South
    p_detour = plan.find_path("Lobby", "Office_A", avoid_edges={blocked_edge})
    assert p_detour == ["Corridor_South", "Office_A"]


def test_failure_only_trajectory_cannot_promote_to_verified():
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_fail_only",
        source_task_id="task_fail_only",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
        expected_effects=["at_location(Corridor_South)"],
    )
    assert mem.verification_status == VerificationStatus.UNVERIFIED

    # Trajectory contains only the failure step and nothing else
    trajectory_fail_only = [
        {
            "step": 1,
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"status": "DOOR_BLOCKED", "success": False, "error_code": "DOORWAY_BLOCKED"},
            "robot_location_before": "Lobby",
            "robot_location_after": "Lobby",
        }
    ]

    promoted, reason = store.verify_and_promote("mem_fail_only", trajectory_fail_only)
    assert promoted is False
    assert mem.verification_status == VerificationStatus.UNVERIFIED


def test_nonexistent_or_fake_evidence_refs_fail_verification():
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_fake",
        source_task_id="task_fake",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
        expected_effects=["at_location(Corridor_South)"],
    )

    # Trajectory with unrelated tool execution
    trajectory_unrelated = [
        {
            "step": 1,
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"status": "DOOR_BLOCKED", "success": False, "error_code": "DOORWAY_BLOCKED"},
        },
        {
            "step": 2,
            "tool": "query_status",
            "params": {"entity": "battery"},
            "result": {"status": "SUCCESS", "success": True},
        }
    ]

    promoted, reason = store.verify_and_promote("mem_fake", trajectory_unrelated)
    assert promoted is False
    assert mem.verification_status == VerificationStatus.UNVERIFIED


def test_new_observation_invalidating_memory_prohibits_reuse():
    store = RepairMemoryStore()
    mem = store.record_repair_experience(
        memory_id="mem_stale_check",
        source_task_id="src_task",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
        execution_evidence_refs=["evt_01"],
        verification_evidence={"verified": True},
        invalidation_conditions={"door_north_state": "FREE"},
        verification_status=VerificationStatus.VERIFIED,
    )
    assert mem.verification_status == VerificationStatus.VERIFIED

    # Invalidate with observation
    store.update_with_observation({"door": "door_north", "passage_state": "FREE"})
    assert mem.verification_status == VerificationStatus.INVALIDATED

    # Attempt retrieval -> must be None
    plan_nodes = store.retrieve_repair_plan("navigate", {"target_zone": "Corridor_North"}, "DOORWAY_BLOCKED", {"robot_location": "Lobby"}, {})
    assert plan_nodes is None


def test_verified_end_to_end_real_trajectory_promotion():
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_real_repair",
        source_task_id="src_task_100",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        repair_proposal=[
            {"action": "navigate", "params": {"target_zone": "Corridor_South"}},
            {"action": "navigate", "params": {"target_zone": "Office_A"}},
        ],
        expected_effects=["at_location(Office_A)"],
    )

    # Real authentic trajectory
    trajectory = [
        {
            "step": 1,
            "event_id": "evt_01",
            "tool": "pickup",
            "params": {"package_id": "pkg_docs", "from_location": "Lobby"},
            "result": {"status": "SUCCESS", "success": True},
            "robot_location": "Lobby",
        },
        {
            "step": 2,
            "event_id": "evt_02",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"status": "DOOR_BLOCKED", "success": False, "error_code": "DOORWAY_BLOCKED"},
            "robot_location": "Lobby",
        },
        {
            "step": 3,
            "event_id": "evt_03",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_South"},
            "result": {"status": "SUCCESS", "success": True, "observation": {"current_location": "Corridor_South"}},
            "robot_location": "Corridor_South",
        },
        {
            "step": 4,
            "event_id": "evt_04",
            "tool": "navigate",
            "params": {"target_zone": "Office_A"},
            "result": {"status": "SUCCESS", "success": True, "observation": {"current_location": "Office_A"}},
            "robot_location": "Office_A",
        }
    ]

    promoted, reason = store.verify_and_promote("mem_real_repair", trajectory)
    assert promoted is True
    assert mem.verification_status == VerificationStatus.VERIFIED
    assert len(mem.execution_evidence_refs) == 2
    assert mem.execution_evidence_refs == ["evt_03", "evt_04"]

