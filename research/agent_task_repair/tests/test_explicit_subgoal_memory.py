"""
Comprehensive Anti-Pattern and Interface Unit Tests for Explicit Subgoal Memory (G vs H vs B vs A).
Zero model calls required.
"""
import pytest
from research.agent_task_repair.agent.task_skeleton import PublicTaskSkeleton, Subgoal
from research.agent_task_repair.memory.subgoal_memory_adapter import SubgoalMemoryAdapter
from research.agent_task_repair.memory.memory_store import MemoryStatus, ConditionMatchResult


def test_antipattern_1_local_pickable_when_delivering_held_package():
    """
    Counterexample 1:
    A package is on the floor in current room (pickable), BUT the robot's inventory is full
    and active subgoal is NAVIGATE to deliver the already-held package.
    G MUST NOT exclude navigation memory about the destination route just because a package is on the floor!
    """
    custom_adj = {"Room_A": ["Corridor_1"], "Corridor_1": ["Room_A", "Room_B"], "Room_B": ["Corridor_1"]}
    skeleton = PublicTaskSkeleton(custom_adj, max_inventory_capacity=1)
    
    current_state = {
        "robot_location": "Room_A",
        "inventory": ["pkg_held"],
        "max_inventory_capacity": 1,
        "available_packages": [
            {"id": "pkg_held", "pickup_location": "Room_A", "target_room": "Room_B", "recipient": "Bob"},
            {"id": "pkg_floor", "pickup_location": "Room_A", "target_room": "Room_B", "recipient": "Bob"},
        ],
    }
    step_history = []
    known_state = {}

    obligations = skeleton.parse_obligations(current_state, step_history)
    eval_res = skeleton.evaluate_dependencies_and_subgoals(current_state, known_state, obligations)
    active_sg = eval_res["active_subgoal"]
    
    # Active subgoal must be NAVIGATE to Room_B (delivery destination) because inventory is full
    assert active_sg is not None
    assert active_sg.type == "NAVIGATE"
    assert active_sg.target == "Room_B"

    # Setup G (explicit subgoal memory adapter) with a navigation failure on Corridor_1
    adapter_g = SubgoalMemoryAdapter(injection_mode="explicit_subgoal", store_mode="F", adjacency_map=custom_adj)
    adapter_g.on_task_start("task_0", 0)
    adapter_g.record_action_failure(
        event_id="evt_01",
        task_id="task_0",
        action_name="navigate",
        target="Corridor_1",
        error_code="DOORWAY_BLOCKED",
        raw_message="Corridor_1 doorway is blocked",
        observation={"door": "door_c1", "passage_state": "OCCUPIED"},
        sim_time=5.0,
    )
    adapter_g.on_task_start("task_1", 1)

    context_query = {
        "step_index": 1,
        "current_location": "Room_A",
        "adjacent_zones": ["Corridor_1"],
        "task_targets": ["Room_B"],
        "active_subgoal": active_sg,
        "pickable_here": [{"package_id": "pkg_floor", "pickup_location": "Room_A"}],
        "inventory": ["pkg_held"],
        "max_inventory_capacity": 1,
    }

    retrieved = adapter_g.retrieve_relevant_memories(known_state, context_query)
    # G MUST inject the navigation memory for Corridor_1 because the active subgoal is NAVIGATE!
    assert len(retrieved) == 1
    assert "DOORWAY_BLOCKED" in retrieved[0]


def test_antipattern_2_empty_backpack_when_active_subgoal_is_recharge():
    """
    Counterexample 2:
    Robot has empty inventory, but critical battery (15%) -> active subgoal is RECHARGE.
    G must properly scope to recharge and not confuse it with pickup.
    """
    custom_adj = {"Lobby": ["Hall_A"], "Hall_A": ["Lobby"]}
    skeleton = PublicTaskSkeleton(custom_adj, max_inventory_capacity=2, charger_location="Lobby")
    
    current_state = {
        "robot_location": "Lobby",
        "battery": 15,
        "inventory": [],
        "available_packages": [
            {"id": "pkg_1", "pickup_location": "Lobby", "target_room": "Hall_A", "recipient": "Alice"},
        ],
    }
    eval_res = skeleton.evaluate_dependencies_and_subgoals(current_state, {}, skeleton.parse_obligations(current_state, []))
    active_sg = eval_res["active_subgoal"]
    assert active_sg.type == "RECHARGE"

    adapter_g = SubgoalMemoryAdapter(injection_mode="explicit_subgoal", store_mode="F")
    adapter_g.on_task_start("task_0", 0)
    # Failure memory on navigation to Hall_A
    adapter_g.record_action_failure(
        event_id="evt_02",
        task_id="task_0",
        action_name="navigate",
        target="Hall_A",
        error_code="DOORWAY_BLOCKED",
        raw_message="Hall_A blocked",
        observation={"door": "door_hall", "passage_state": "OCCUPIED"},
        sim_time=5.0,
    )
    adapter_g.on_task_start("task_1", 1)

    context_query = {
        "step_index": 1,
        "current_location": "Lobby",
        "active_subgoal": active_sg,
        "inventory": [],
        "adjacent_zones": ["Hall_A"],
    }
    retrieved = adapter_g.retrieve_relevant_memories({}, context_query)
    # G excludes navigation memory because active subgoal is RECHARGE
    assert len(retrieved) == 0
    assert "Active subgoal is RECHARGE" in adapter_g.retrieval_audit_log[0]["excluded_records"][0]["reason"]


def test_antipattern_3_navigation_to_credential_protected_room_includes_badge_memory():
    """
    Counterexample 3:
    Active subgoal is NAVIGATE to Secure_Vault.
    A failure memory exists about missing badge: ACCESS_DENIED_NO_BADGE.
    G MUST NOT exclude the credential requirement memory merely because the action type is 'navigate'!
    """
    sg_nav_vault = Subgoal(
        id="sg_nav_vault",
        type="NAVIGATE",
        target="Secure_Vault",
        preconditions=[],
        completion_conditions=["at_location(Secure_Vault)"],
    )

    adapter_g = SubgoalMemoryAdapter(injection_mode="explicit_subgoal", store_mode="F")
    adapter_g.on_task_start("task_0", 0)
    adapter_g.record_action_failure(
        event_id="evt_03",
        task_id="task_0",
        action_name="navigate",
        target="Secure_Vault",
        error_code="ACCESS_DENIED_NO_BADGE",
        raw_message="Access denied: door requires keycard_gold",
        observation={"door": "door_vault", "access_status": "DENIED", "required_credential": "keycard_gold"},
        sim_time=10.0,
    )
    adapter_g.on_task_start("task_1", 1)

    context_query = {
        "step_index": 1,
        "current_location": "Corridor_Central",
        "adjacent_zones": ["Secure_Vault"],
        "task_targets": ["Secure_Vault"],
        "active_subgoal": sg_nav_vault,
    }
    retrieved = adapter_g.retrieve_relevant_memories({}, context_query)
    assert len(retrieved) == 1
    assert "ACCESS_DENIED_NO_BADGE" in retrieved[0]


def test_antipattern_4_irrelevant_room_memory_excluded_by_g():
    """
    Counterexample 4:
    Active subgoal is NAVIGATE to North_Wing.
    Memory exists about South_Wing failure.
    G MUST exclude South_Wing memory.
    """
    sg_nav_north = Subgoal(
        id="sg_nav_north",
        type="NAVIGATE",
        target="North_Wing",
    )

    adapter_g = SubgoalMemoryAdapter(injection_mode="explicit_subgoal", store_mode="F")
    adapter_g.on_task_start("task_0", 0)
    adapter_g.record_action_failure(
        event_id="evt_04",
        task_id="task_0",
        action_name="navigate",
        target="South_Wing",
        error_code="DOORWAY_BLOCKED",
        raw_message="South_Wing blocked",
        observation={"door": "door_south", "passage_state": "OCCUPIED"},
        sim_time=8.0,
    )
    adapter_g.on_task_start("task_1", 1)

    context_query = {
        "step_index": 1,
        "current_location": "Lobby",
        "adjacent_zones": ["North_Wing", "South_Wing"],
        "task_targets": ["North_Wing"],
        "active_subgoal": sg_nav_north,
    }
    retrieved = adapter_g.retrieve_relevant_memories({}, context_query)
    assert len(retrieved) == 0


def test_antipattern_5_dynamic_observation_invalidation():
    """
    Counterexample 5:
    A door was blocked, but a new observation confirms FREE.
    Memory status is set to INVALIDATED and G excludes it.
    """
    sg_nav_north = Subgoal(id="sg_1", type="NAVIGATE", target="North_Wing")
    adapter_g = SubgoalMemoryAdapter(injection_mode="explicit_subgoal", store_mode="F")
    adapter_g.on_task_start("task_0", 0)
    adapter_g.record_action_failure(
        event_id="evt_05",
        task_id="task_0",
        action_name="navigate",
        target="North_Wing",
        error_code="DOORWAY_BLOCKED",
        raw_message="North_Wing blocked",
        observation={"door": "door_north", "passage_state": "OCCUPIED"},
        sim_time=8.0,
    )
    adapter_g.on_task_start("task_1", 1)

    # Observation confirms door is FREE
    adapter_g.record_observation("evt_obs_free", {"door": "door_north", "passage_state": "FREE"}, 20.0)

    context_query = {
        "step_index": 1,
        "current_location": "Lobby",
        "adjacent_zones": ["North_Wing"],
        "active_subgoal": sg_nav_north,
    }
    retrieved = adapter_g.retrieve_relevant_memories({}, context_query)
    assert len(retrieved) == 0
    assert adapter_g.store.get_all_memories()[0].status == MemoryStatus.INVALIDATED


def test_antipattern_6_generic_names_and_capacity_scaling():
    """
    Counterexample 6:
    Custom graph topology with renamed rooms (Zone_Alpha, Zone_Beta, Zone_Gamma) and capacity=3.
    Verifies that no hardcoded 'Lab_Secure' or capacity=2 dependencies exist.
    """
    custom_adj = {
        "Zone_Alpha": ["Zone_Beta"],
        "Zone_Beta": ["Zone_Alpha", "Zone_Gamma"],
        "Zone_Gamma": ["Zone_Beta"],
    }
    skeleton = PublicTaskSkeleton(custom_adj, max_inventory_capacity=3)
    current_state = {
        "robot_location": "Zone_Alpha",
        "inventory": ["pkg_a", "pkg_b"],
        "max_inventory_capacity": 3,
        "available_packages": [
            {"id": "pkg_a", "pickup_location": "Zone_Alpha", "target_room": "Zone_Gamma", "recipient": "Zeta"},
            {"id": "pkg_b", "pickup_location": "Zone_Alpha", "target_room": "Zone_Gamma", "recipient": "Zeta"},
            {"id": "pkg_c", "pickup_location": "Zone_Alpha", "target_room": "Zone_Gamma", "recipient": "Zeta"},
        ],
    }
    eval_res = skeleton.evaluate_dependencies_and_subgoals(current_state, {}, skeleton.parse_obligations(current_state, []))
    active_sg = eval_res["active_subgoal"]
    # With capacity 3 and 2 held items, picking up pkg_c at Zone_Alpha is valid and ready
    assert active_sg is not None
    assert active_sg.type == "PICKUP"
    assert active_sg.package_id == "pkg_c"
