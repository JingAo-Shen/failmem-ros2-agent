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
from research.agent_task_repair.agent.task_state import TaskStateTracker, ObligationStatus, ObservedFact, ConstraintEvent
from research.agent_task_repair.agent.plan_manager import PersistentPlan, PlanNode, PlanNodeStatus
from research.agent_task_repair.agent.action_validator import ActionValidator, ValidationStatus
from research.agent_task_repair.agent.repair_controller import RepairController
from research.agent_task_repair.agent.stateful_runner import StatefulAgentRunner
from research.agent_task_repair.memory.repair_memory import RepairMemoryStore, VerificationStatus, ApplicabilityResult, MemoryLifecycleState
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
    mem = store.propose_repair(
        memory_id="mem_test_door",
        source_task_id="src_01",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED", "event_id": "evt_src_s01"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "$detour_zone"}}],
        applicability={"origin": "Lobby"},
        required_facts={"door_north_state": "OCCUPIED"},
        invalidation_conditions={"door_north_state": "FREE"},
        expected_effects=["at_location(Corridor_South)"],
    )
    traj = [
        {"tool": "navigate", "params": {"target_zone": "Corridor_North"}, "result": {"success": False, "error_code": "DOORWAY_BLOCKED"}, "event_id": "evt_src_s01", "task_id": "src_01"},
        {"tool": "navigate", "params": {"target_zone": "Corridor_South"}, "result": {"success": True}, "event_id": "evt_src_s02", "task_id": "src_01", "robot_location": "Corridor_South"},
    ]
    ok, _ = store.verify_and_promote("mem_test_door", traj, ["at_location(Corridor_South)"])
    assert ok is True
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
    mem = store.propose_repair(
        memory_id="mem_stale_check",
        source_task_id="src_task",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED", "event_id": "evt_01"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
        invalidation_conditions={"door_north_state": "FREE"},
        expected_effects=["at_location(Corridor_South)"],
    )
    traj = [
        {"step": 1, "task_id": "src_task", "event_id": "evt_01", "tool": "navigate", "params": {"target_zone": "Corridor_North"}, "result": {"success": False, "error_code": "DOORWAY_BLOCKED"}},
        {"step": 2, "task_id": "src_task", "event_id": "evt_02", "tool": "navigate", "params": {"target_zone": "Corridor_South"}, "result": {"success": True, "observation": {"current_location": "Corridor_South"}}},
    ]
    ok, _ = store.verify_and_promote("mem_stale_check", traj)
    assert ok is True
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
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED", "event_id": "evt_02"},
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
            "task_id": "src_task_100",
            "event_id": "evt_01",
            "tool": "pickup",
            "params": {"package_id": "pkg_docs", "from_location": "Lobby"},
            "result": {"status": "SUCCESS", "success": True},
            "robot_location": "Lobby",
        },
        {
            "step": 2,
            "task_id": "src_task_100",
            "event_id": "evt_02",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"status": "DOOR_BLOCKED", "success": False, "error_code": "DOORWAY_BLOCKED"},
            "robot_location": "Lobby",
        },
        {
            "step": 3,
            "task_id": "src_task_100",
            "event_id": "evt_03",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_South"},
            "result": {"status": "SUCCESS", "success": True, "observation": {"current_location": "Corridor_South"}},
            "robot_location": "Corridor_South",
            "robot_location_after": "Corridor_South",
        },
        {
            "step": 4,
            "task_id": "src_task_100",
            "event_id": "evt_04",
            "tool": "navigate",
            "params": {"target_zone": "Office_A"},
            "result": {"status": "SUCCESS", "success": True, "observation": {"current_location": "Office_A"}},
            "robot_location": "Office_A",
            "robot_location_after": "Office_A",
        }
    ]

    promoted, reason = store.verify_and_promote("mem_real_repair", trajectory)
    assert promoted is True
    assert mem.verification_status == VerificationStatus.VERIFIED
    assert len(mem.execution_evidence_refs) == 2
    assert mem.execution_evidence_refs == ["evt_03", "evt_04"]


def test_credential_search_observe_obligation_enforced():
    """Execution chain test: Robot in search room cannot depart without observing."""
    validator = ActionValidator()
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Office_A",
        "battery": 80,
        "inventory": ["pkg_sec"],
        "credentials": [],
        "available_packages": [{"id": "pkg_sec", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}],
    })
    plan = PersistentPlan(state)
    obs_node = PlanNode(
        id="repair_observe_Office_A",
        goal="Observe room Office_A to search for security_badge",
        action_type="observe",
        target="Office_A",
        params={"target": "Office_A"},
        status=PlanNodeStatus.READY,
        is_repair_node=True,
    )
    plan.nodes = [obs_node]

    # Attempting navigate away while observe is active must FAIL validation
    v_res = validator.validate_action(
        tool_name="navigate",
        params={"target_zone": "Corridor_South"},
        current_state=state.get_public_state_summary(),
        known_facts=state.observed_facts,
        active_plan_node=obs_node,
    )
    assert v_res.status == ValidationStatus.FAIL
    assert "observation obligation" in v_res.reason.lower()

    # Executing observe passes validation
    v_res_obs = validator.validate_action(
        tool_name="observe",
        params={"target": "Office_A"},
        current_state=state.get_public_state_summary(),
        known_facts=state.observed_facts,
        active_plan_node=obs_node,
    )
    assert v_res_obs.status == ValidationStatus.PASS


def test_credential_search_multi_room_closed_loop():
    """Execution chain test: Searching empty Office_A automatically transitions to Office_B, finds badge, acquires it, and replans to Lab_Secure."""
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 90,
        "inventory": ["pkg_sec"],
        "credentials": [],
        "available_packages": [{"id": "pkg_sec", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}],
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Mark Lobby as already checked to specifically test transition from Office_A to Office_B
    state.set_fact("room_checked_empty_Lobby", True, "evt_lobby_init", 0.0, "observe")

    # 1. Simulate failure at Lab_Secure
    controller = RepairController()
    abort, msg, r_nodes = controller.handle_failure(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        observation={"required_credential": "security_badge"},
        task_state=state,
        plan=plan,
    )
    assert abort is False
    assert len(r_nodes) > 0

    # 2. Next active node should lead to Office_A

    # 3. Next active node should lead to Office_A
    node_a = plan.get_current_active_node()
    assert node_a is not None
    assert node_a.action_type in ("navigate", "observe")

    # Navigate to Office_A
    state.robot_location = "Office_A"
    plan.on_step_success("navigate", {"target_zone": "Office_A"}, "evt_nav_oa")

    # Observe Office_A (empty)
    state.update_from_tool_result("observe", {"target": "Office_A"}, {"success": True, "observation": {"room": "Office_A", "items": []}}, "evt_obs_oa", 20.0)
    plan.on_step_success("observe", {"target": "Office_A"}, "evt_obs_oa")

    # 4. Next active node must be navigation towards Office_B!
    node_b = plan.get_current_active_node()
    assert node_b is not None
    assert node_b.target in ("Corridor_North", "Office_B")

    # Navigate to Corridor_North then Office_B
    state.robot_location = "Corridor_North"
    plan.on_step_success("navigate", {"target_zone": "Corridor_North"}, "evt_nav_cn")
    state.robot_location = "Office_B"
    plan.on_step_success("navigate", {"target_zone": "Office_B"}, "evt_nav_ob")

    # Observe Office_B (finds security_badge!)
    state.update_from_tool_result("observe", {"target": "Office_B"}, {"success": True, "observation": {"room": "Office_B", "items": ["security_badge"]}}, "evt_obs_ob", 40.0)
    plan.on_step_success("observe", {"target": "Office_B"}, "evt_obs_ob")

    # 5. Next active node must be acquire_credential("security_badge")
    node_acq = plan.get_current_active_node()
    assert node_acq is not None
    assert node_acq.action_type == "acquire_credential"

    # Acquire badge
    state.update_from_tool_result("acquire_credential", {"credential_name": "security_badge"}, {"success": True, "observation": {"credentials": ["security_badge"]}}, "evt_acq", 45.0)
    plan.on_step_success("acquire_credential", {"credential_name": "security_badge"}, "evt_acq")
    assert "security_badge" in state.credentials

    # 6. Next active node must be navigation back towards Lab_Secure!
    node_next = plan.get_current_active_node()
    assert node_next is not None
    assert node_next.action_type == "navigate"
    assert node_next.target in ("Corridor_North", "Corridor_South", "Lab_Secure")


def test_static_vs_dynamic_fact_tracker_contradiction():
    """Tests static baseline (is_static=True) vs dynamic updated baseline (is_static=False)."""
    # 1. Static tracker
    state_static = TaskStateTracker("Test Static", {"robot_location": "Office_A"}, is_static=True)
    state_static.set_fact("badge_location", "Office_A", "evt_seed", 0.0, "observe")
    state_static.set_fact("room_items_Office_A", ["security_badge"], "evt_seed", 0.0, "observe")

    # Observe empty room
    obs_empty = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_A", "items": []}}
    state_static.update_from_tool_result("observe", {"target": "Office_A"}, obs_empty, "evt_obs", 10.0)
    # Under static mode, historical facts are NOT erased
    assert state_static.get_fact_value("badge_location") == "Office_A"
    assert state_static.get_fact_value("room_items_Office_A") == ["security_badge"]
    assert state_static.get_fact_value("room_checked_empty_Office_A") is None

    # 2. Dynamic tracker
    state_dynamic = TaskStateTracker("Test Dynamic", {"robot_location": "Office_A"}, is_static=False)
    state_dynamic.set_fact("badge_location", "Office_A", "evt_seed", 0.0, "observe")
    state_dynamic.set_fact("room_items_Office_A", ["security_badge"], "evt_seed", 0.0, "observe")

    state_dynamic.update_from_tool_result("observe", {"target": "Office_A"}, obs_empty, "evt_obs", 10.0)
    # Under dynamic mode, facts are updated
    assert state_dynamic.get_fact_value("badge_location") is None
    assert state_dynamic.get_fact_value("room_checked_empty_Office_A") is True
    assert state_dynamic.get_fact_value("credential_not_found_in_Office_A") is True


def test_smoke_target_preserved_memory_reuse():
    """Smoke Test 1: Historical badge location preserved. Verifies genuine memory retrieval and execution."""
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_badge_oa",
        source_task_id="task_src_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_src"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    mem.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": "Office_A",
    }
    traj = [
        {"step": 1, "task_id": "task_src_01", "event_id": "evt_fail_src", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_01", "event_id": "evt_src_acq", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    store.verify_and_promote("mem_badge_oa", traj, ["has_credential(security_badge)"])

    # Simulate Target 1 Execution
    state = TaskStateTracker("Deliver pkg to Bob in Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 95,
        "inventory": ["pkg_t1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_t1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}],
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Robot fails at door_lab
    fail_res = {
        "status": "ACCESS_DENIED_NO_BADGE",
        "success": False,
        "error_code": "SECURITY_BADGE_REQUIRED",
        "observation": {"door": "door_lab", "required_credential": "security_badge"},
    }
    state.update_from_tool_result("navigate", {"target_zone": "Lab_Secure"}, fail_res, "evt_tgt_fail", 10.0)

    controller = RepairController()
    abort, msg, r_nodes = controller.handle_failure(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        observation=fail_res["observation"],
        task_state=state,
        plan=plan,
        repair_memory_adapter=store,
        target_run_id="smoke_tgt_1",
    )
    assert abort is False
    assert len(r_nodes) > 0

    # Verify that nodes lead to Office_A
    node_targets = [n.target for n in r_nodes]
    assert "Office_A" in node_targets
    assert "security_badge" in node_targets

    # Check target lifecycle events
    events = [e["event"] for e in store.target_audit_log]
    assert "TARGET_RETRIEVED" in events
    assert "TARGET_INSTANTIATED" in events


def test_smoke_target_location_changed_invalidation_and_fallback():
    """Smoke Test 2: Location changed (Office_A empty, badge in Office_B). Verifies invalidation and BFS search fallback."""
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_badge_oa",
        source_task_id="task_src_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_src"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    mem.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": "Office_A",
    }
    traj = [
        {"step": 1, "task_id": "task_src_01", "event_id": "evt_fail_src", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_01", "event_id": "evt_src_acq", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    store.verify_and_promote("mem_badge_oa", traj, ["has_credential(security_badge)"])

    # Simulate Target 3 Execution
    state = TaskStateTracker("Deliver pkg to Bob in Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 95,
        "inventory": ["pkg_t3"],
        "credentials": [],
        "available_packages": [{"id": "pkg_t3", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}],
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Robot fails at door_lab
    fail_res = {
        "status": "ACCESS_DENIED_NO_BADGE",
        "success": False,
        "error_code": "SECURITY_BADGE_REQUIRED",
        "observation": {"door": "door_lab", "required_credential": "security_badge"},
    }
    state.update_from_tool_result("navigate", {"target_zone": "Lab_Secure"}, fail_res, "evt_tgt3_fail", 10.0)

    controller = RepairController()
    abort, msg, r_nodes = controller.handle_failure(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        observation=fail_res["observation"],
        task_state=state,
        plan=plan,
        repair_memory_adapter=store,
        target_run_id="smoke_tgt_3",
    )
    assert abort is False

    # Execute navigation to Office_A
    state.robot_location = "Office_A"
    plan.on_step_success("navigate", {"target_zone": "Office_A"}, "evt_nav_oa")

    # Observe Office_A (empty!)
    obs_empty = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_A", "items": []}}
    state.update_from_tool_result("observe", {"target": "Office_A"}, obs_empty, "evt_obs_oa", 20.0)
    store.update_with_observation(state.observed_facts, target_run_id="smoke_tgt_3", event_id="evt_obs_oa", sim_time=20.0)
    plan.on_step_success("observe", {"target": "Office_A"}, "evt_obs_oa")

    # Verify memory is INVALIDATED
    assert mem.verification_status == VerificationStatus.INVALIDATED
    events = [e["event"] for e in store.target_audit_log]
    assert "TARGET_INVALIDATED" in events

    # Check fallback: Next plan node transitions to search Office_B
    node_next = plan.get_current_active_node()
    assert node_next is not None
    assert node_next.target in ("Corridor_North", "Office_B")


def test_regression_target_1_no_duplicate_acquire_nodes_and_clean_attribution():
    """Regression Test: Target 1 verified memory reuse has no duplicate acquire nodes and clean post-repair attribution."""
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_badge_oa",
        source_task_id="task_src_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_src"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    mem.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": "Office_A",
        "required_facts": {"requires_credential(door_lab,security_badge)": True},
        "invalidation_conditions": {"credential_not_found_in_Office_A": True},
        "expected_effects": ["has_credential(security_badge)"],
    }
    traj = [
        {"step": 1, "task_id": "task_src_01", "event_id": "evt_fail_src", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_01", "event_id": "evt_src_acq", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    ok, _ = store.verify_and_promote("mem_badge_oa", traj, ["has_credential(security_badge)"])
    assert ok is True

    state = TaskStateTracker("Deliver pkg to Bob in Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 95,
        "inventory": ["pkg_t1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_t1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}],
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Trigger failure at door_lab
    fail_res = {
        "status": "ACCESS_DENIED_NO_BADGE",
        "success": False,
        "error_code": "SECURITY_BADGE_REQUIRED",
        "observation": {"door": "door_lab", "required_credential": "security_badge"},
    }
    state.update_from_tool_result("navigate", {"target_zone": "Lab_Secure"}, fail_res, "evt_fail_t1", 10.0)

    controller = RepairController()
    abort, msg, r_nodes = controller.handle_failure(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        observation=fail_res["observation"],
        task_state=state,
        plan=plan,
        repair_memory_adapter=store,
        target_run_id="target_run_t1",
    )
    assert abort is False
    assert len(r_nodes) == 3
    # Check origin fields on instantiated memory nodes
    for rn in r_nodes:
        assert rn.origin_type == "memory"
        assert rn.origin_memory_id == "mem_badge_oa"
        assert rn.repair_instance_id == "repair_inst_mem_badge_oa"

    # Robot navigates to Office_A
    state.robot_location = "Office_A"
    plan.on_step_success("navigate", {"target_zone": "Office_A"}, "evt_nav_oa")

    # Robot observes Office_A (badge is present!)
    obs_res = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_A", "items": ["security_badge"]}}
    state.update_from_tool_result("observe", {"target": "Office_A"}, obs_res, "evt_obs_oa", 20.0)
    plan.on_step_success("observe", {"target": "Office_A"}, "evt_obs_oa")

    # Verify: Deduplication check - there must be EXACTLY ONE acquire_credential node downstream!
    pending_acq_nodes = [
        n for n in plan.nodes
        if n.action_type == "acquire_credential" and n.status in (PlanNodeStatus.READY, PlanNodeStatus.PENDING)
    ]
    assert len(pending_acq_nodes) == 1, f"Expected exactly 1 acquire node, found {len(pending_acq_nodes)}: {pending_acq_nodes}"
    acq_node = pending_acq_nodes[0]
    assert acq_node.origin_memory_id == "mem_badge_oa"

    # Robot acquires credential
    state.credentials.add("security_badge")
    plan.on_step_success("acquire_credential", {"credential_name": "security_badge"}, "evt_acq_badge")

    # Verify post-acquire replanned navigation nodes are base_plan, NOT memory
    remaining_nav_nodes = [n for n in plan.nodes if n.action_type == "navigate" and n.status in (PlanNodeStatus.READY, PlanNodeStatus.PENDING)]
    for n in remaining_nav_nodes:
        assert n.origin_type == "base_plan"
        assert n.origin_memory_id is None
        assert n.is_repair_node is False


def test_regression_target_3_invalidation_and_no_false_memory_credit():
    """Regression Test: Target 3 invalidated memory is NOT credited with TARGET_EFFECT_VERIFIED."""
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_badge_oa",
        source_task_id="task_src_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_src"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    mem.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": "Office_A",
        "required_facts": {"requires_credential(door_lab,security_badge)": True},
        "invalidation_conditions": {"credential_not_found_in_Office_A": True},
        "expected_effects": ["has_credential(security_badge)"],
    }
    traj = [
        {"step": 1, "task_id": "task_src_01", "event_id": "evt_fail_src", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_01", "event_id": "evt_src_acq", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    store.verify_and_promote("mem_badge_oa", traj, ["has_credential(security_badge)"])

    state = TaskStateTracker("Deliver pkg to Bob in Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 95,
        "inventory": ["pkg_t3"],
        "credentials": [],
        "available_packages": [{"id": "pkg_t3", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}],
    })
    state.set_fact("room_checked_empty_Lobby", True, "evt_init_lobby", 0.0, "observe")
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Door failure triggers memory retrieval
    fail_res = {
        "status": "ACCESS_DENIED_NO_BADGE",
        "success": False,
        "error_code": "SECURITY_BADGE_REQUIRED",
        "observation": {"door": "door_lab", "required_credential": "security_badge"},
    }
    state.update_from_tool_result("navigate", {"target_zone": "Lab_Secure"}, fail_res, "evt_fail_t3", 10.0)

    controller = RepairController()
    controller.handle_failure(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        observation=fail_res["observation"],
        task_state=state,
        plan=plan,
        repair_memory_adapter=store,
        target_run_id="target_run_t3",
    )

    # Robot navigates to Office_A
    state.robot_location = "Office_A"
    plan.on_step_success("navigate", {"target_zone": "Office_A"}, "evt_nav_oa")

    # Robot observes Office_A (empty!)
    obs_res = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_A", "items": []}}
    state.update_from_tool_result("observe", {"target": "Office_A"}, obs_res, "evt_obs_oa", 20.0)
    store.update_with_observation(state.observed_facts, target_run_id="target_run_t3", event_id="evt_obs_oa", sim_time=20.0)
    plan.on_step_success("observe", {"target": "Office_A"}, "evt_obs_oa")

    assert mem.verification_status == VerificationStatus.INVALIDATED
    assert mem.lifecycle_state == MemoryLifecycleState.INVALIDATED

    # Robot online-searches and reaches Office_B, observes badge
    state.robot_location = "Corridor_North"
    plan.on_step_success("navigate", {"target_zone": "Corridor_North"}, "evt_nav_cn")
    state.robot_location = "Office_B"
    plan.on_step_success("navigate", {"target_zone": "Office_B"}, "evt_nav_ob")

    obs_ob_res = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_B", "items": ["security_badge"]}}
    state.update_from_tool_result("observe", {"target": "Office_B"}, obs_ob_res, "evt_obs_ob", 30.0)
    plan.on_step_success("observe", {"target": "Office_B"}, "evt_obs_ob")

    # Robot acquires badge in Office_B
    active = plan.get_current_active_node()
    assert active is not None
    assert active.action_type == "acquire_credential"

    # Simulate acquisition completion
    plan.on_step_success("acquire_credential", {"credential_name": "security_badge"}, "evt_acq_ob")

    # Verify: TARGET_EFFECT_VERIFIED was NEVER called for the invalidated memory
    effect_verified_events = [
        e for e in store.target_audit_log
        if e.get("event") == "TARGET_EFFECT_VERIFIED"
    ]
    assert len(effect_verified_events) == 0, f"Expected 0 TARGET_EFFECT_VERIFIED events for invalidated memory, got {effect_verified_events}"


def test_regression_plan_deviation_does_not_complete_node():
    """Regression Test: Executing an action that deviates from the active plan node does not complete it."""
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

    # Agent executes navigate instead of pickup
    ok = plan.on_step_success("navigate", {"target_zone": "Corridor_North"}, "evt_deviated")
    assert ok is False
    assert active.status != PlanNodeStatus.COMPLETED
    assert plan.get_current_active_node() == active


def test_interface_1_known_door_restriction_pre_execution_repair():
    """Test 1: Known door restriction, no badge -> pre-execution interception triggers handle_constraint_event -> repair plan inserted."""
    validator = ActionValidator()
    controller = RepairController(enable_observation_guard=True)
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 100,
        "inventory": ["pkg_1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}]
    })
    state.set_fact("requires_credential(door_lab,security_badge)", True, "evt_seed_fact", 0.0, "observe")
    state.set_fact("badge_location", "Office_A", "evt_seed_fact", 0.0, "observe")

    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Validator checks navigate to Lab_Secure without badge
    v_res = validator.validate_action("navigate", {"target_zone": "Lab_Secure"}, state.get_public_state_summary(), state.observed_facts)
    assert v_res.status == ValidationStatus.FAIL
    assert v_res.is_schema_error is False
    assert v_res.constraint_event is not None
    assert v_res.constraint_event.origin == "pre_execution"
    assert v_res.constraint_event.constraint_type == "SECURITY_BADGE_REQUIRED"

    # Trigger handle_constraint_event
    abort, msg, r_nodes = controller.handle_constraint_event(v_res.constraint_event, state, plan)
    assert abort is False
    assert len(r_nodes) > 0
    # Repair sub-nodes should route to Office_A and observe
    active = plan.get_current_active_node()
    assert active is not None
    assert active.is_repair_node is True
    assert active.action_type == "navigate"
    assert active.target in ("Corridor_North", "Office_A")


def test_interface_2_unknown_door_restriction_tool_result_repair():
    """Test 2: Unknown door restriction -> physical failure -> origin='tool_result' -> same repair flow."""
    controller = RepairController(enable_observation_guard=True)
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 100,
        "inventory": ["pkg_1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}]
    })
    state.set_fact("badge_location", "Office_A", "evt_seed_fact", 0.0, "observe")
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Tool failure event
    c_event = ConstraintEvent(
        origin="tool_result",
        constraint_type="SECURITY_BADGE_REQUIRED",
        proposed_action={"tool": "navigate", "params": {"target_zone": "Lab_Secure"}},
        observation={"door": "door_lab", "required_credential": "security_badge"},
        current_state_version=1,
        reason="Access denied: door_lab requires security_badge",
    )
    abort, msg, r_nodes = controller.handle_constraint_event(c_event, state, plan)
    assert abort is False
    assert len(r_nodes) > 0
    active = plan.get_current_active_node()
    assert active.is_repair_node is True


def test_interface_3_arrival_at_candidate_badge_room_observation_obligation():
    """Test 3: Arrival at candidate badge room -> observation obligation preserved and enforced."""
    validator = ActionValidator()
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Office_A",
        "battery": 100,
        "inventory": ["pkg_1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}]
    })
    plan = PersistentPlan(state)
    plan.nodes = [
        PlanNode(
            id="repair_observe_Office_A",
            goal="Observe room Office_A to confirm security_badge presence",
            action_type="observe",
            target="Office_A",
            params={"target": "Office_A"},
            status=PlanNodeStatus.READY,
            is_repair_node=True,
        )
    ]
    # Agent tries to skip observe and immediately acquire or navigate
    v_res = validator.validate_action("acquire_credential", {"credential_name": "security_badge"}, state.get_public_state_summary(), state.observed_facts, active_plan_node=plan.nodes[0])
    assert v_res.status == ValidationStatus.FAIL
    assert "Active observation obligation" in v_res.reason
    assert v_res.suggested_revision == {"action": "observe", "params": {"target": "Office_A"}}


def test_interface_4_candidate_room_empty_invalidates_acquire_continues_search():
    """Test 4: Candidate room empty -> clears facts, invalidates acquire node, continues search."""
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Office_A",
        "battery": 100,
        "inventory": ["pkg_1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}]
    })
    state.set_fact("room_checked_empty_Lobby", True, "evt_lobby", 0.0, "observe")
    plan = PersistentPlan(state)
    plan.nodes = [
        PlanNode(
            id="repair_observe_Office_A",
            goal="Observe room Office_A",
            action_type="observe",
            target="Office_A",
            params={"target": "Office_A"},
            status=PlanNodeStatus.READY,
            is_repair_node=True,
        ),
        PlanNode(
            id="repair_acquire_badge",
            goal="Acquire security_badge",
            action_type="acquire_credential",
            target="security_badge",
            params={"credential_name": "security_badge"},
            status=PlanNodeStatus.PENDING,
            is_repair_node=True,
        ),
    ]
    # Tool result from observe Office_A returns empty items
    obs_res = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_A", "items": []}}
    state.update_from_tool_result("observe", {"target": "Office_A"}, obs_res, "evt_obs_oa", 10.0)
    plan.on_step_success("observe", {"target": "Office_A"}, "evt_obs_oa")

    # Acquire node in Office_A should be INVALIDATED
    invalidated_acq = [n for n in plan.nodes if n.action_type == "acquire_credential" and n.status == PlanNodeStatus.INVALIDATED]
    assert len(invalidated_acq) == 1
    # A subsequent search node to another uninspected room (e.g. Office_B) should be inserted/ready
    active = plan.get_current_active_node()
    assert active is not None
    assert active.action_type in ("navigate", "observe")
    assert "Office_B" in active.goal or active.target in ("Corridor_North", "Office_B")


def test_interface_5_acquisition_success_restores_delivery_target_deduplicates():
    """Test 5: Acquisition success -> restores delivery target, no duplicate acquire nodes."""
    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Office_A",
        "battery": 100,
        "inventory": ["pkg_1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}]
    })
    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    # Insert observe and acquire
    obs_node = PlanNode(id="obs_oa", goal="Observe Office_A", action_type="observe", target="Office_A", params={"target": "Office_A"}, status=PlanNodeStatus.READY, is_repair_node=True)
    plan.insert_repair_nodes([obs_node], reason="test_insert")

    # Observe success with badge
    obs_res = {"status": "SUCCESS", "success": True, "observation": {"room": "Office_A", "items": ["security_badge"]}}
    state.update_from_tool_result("observe", {"target": "Office_A"}, obs_res, "evt_obs_oa", 10.0)
    plan.on_step_success("observe", {"target": "Office_A"}, "evt_obs_oa")

    # Active node is acquire
    active = plan.get_current_active_node()
    assert active is not None
    assert active.action_type == "acquire_credential"

    # Acquire success
    state.credentials.add("security_badge")
    plan.on_step_success("acquire_credential", {"credential_name": "security_badge"}, "evt_acq")

    # Check no duplicate acquire nodes
    remaining_acq = [n for n in plan.nodes if n.action_type == "acquire_credential" and n.status in (PlanNodeStatus.READY, PlanNodeStatus.PENDING)]
    assert len(remaining_acq) == 0

    # Next ready node should navigate towards Lab_Secure for delivery
    active_after = plan.get_current_active_node()
    assert active_after is not None
    assert active_after.action_type in ("navigate", "deliver")


def test_interface_6_template_invalidation_falls_back_to_online_recovery():
    """Test 6: Template rejected or invalidated -> uses online recovery, does not abort task."""
    store = RepairMemoryStore()
    mem = store.propose_repair(
        memory_id="mem_stale",
        source_task_id="src_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    traj = [
        {"step": 1, "task_id": "src_01", "event_id": "evt_src_1", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "src_01", "event_id": "evt_src_2", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    store.verify_and_promote("mem_stale", traj, ["has_credential(security_badge)"])

    state = TaskStateTracker("Deliver pkg to Lab_Secure", {
        "robot_location": "Corridor_South",
        "battery": 100,
        "inventory": ["pkg_1"],
        "credentials": [],
        "available_packages": [{"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob"}]
    })
    # State has fact that invalidates the memory
    state.set_fact("requires_credential(door_lab,security_badge)", True, "evt_1", 0.0, "observe")
    state.set_fact("credential_not_found_in_Office_A", True, "evt_2", 0.0, "observe")
    state.set_fact("room_checked_empty_Lobby", True, "evt_3", 0.0, "observe")
    store.update_with_observation(state.observed_facts)
    assert mem.lifecycle_state == MemoryLifecycleState.INVALIDATED

    plan = PersistentPlan(state)
    plan.initialize_initial_plan()

    controller = RepairController(enable_observation_guard=True)
    c_event = ConstraintEvent(
        origin="pre_execution",
        constraint_type="SECURITY_BADGE_REQUIRED",
        proposed_action={"tool": "navigate", "params": {"target_zone": "Lab_Secure"}},
        affected_goal_id="node_01",
        reason="Security badge required",
    )
    abort, msg, r_nodes = controller.handle_constraint_event(c_event, state, plan, repair_memory_adapter=store)
    assert abort is False
    assert len(r_nodes) > 0
    # Since memory was invalidated and Office_A/Lobby are empty, online repair should search Office_B
    assert any("Office_B" in n.goal or n.target == "Office_B" for n in r_nodes)


def test_interface_7_repeated_constraint_zero_progress_dead_loop_abort():
    """Test 7: Repeated constraint with zero progress -> terminates with DEAD_LOOP_ABORT."""
    controller = RepairController(max_repeated_attempts=3)
    state = TaskStateTracker("Test dead loop", {"robot_location": "Corridor_South"})
    plan = PersistentPlan(state)

    c_event = ConstraintEvent(
        origin="pre_execution",
        constraint_type="SECURITY_BADGE_REQUIRED",
        proposed_action={"tool": "navigate", "params": {"target_zone": "Lab_Secure"}},
        affected_goal_id="node_01",
        reason="Security badge required",
    )

    # Attempt 1
    abort1, msg1, _ = controller.handle_constraint_event(c_event, state, plan)
    assert abort1 is False

    # Attempt 2 (no state change)
    abort2, msg2, _ = controller.handle_constraint_event(c_event, state, plan)
    assert abort2 is False

    # Attempt 3 (no state change -> aborts)
    abort3, msg3, _ = controller.handle_constraint_event(c_event, state, plan)
    assert abort3 is True
    assert "DEAD_LOOP_ABORT" in msg3



