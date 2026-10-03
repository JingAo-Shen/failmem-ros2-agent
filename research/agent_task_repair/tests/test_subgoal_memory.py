"""
Unit tests for Subgoal-Aware Memory Retrieval and 2x3 Matrix Scoping.
Zero model calls required.
"""
import pytest
from research.agent_task_repair.memory.subgoal_memory_adapter import SubgoalMemoryAdapter
from research.agent_task_repair.memory.memory_store import MemoryStatus, ConditionMatchResult


def test_subgoal_scoping_excludes_nav_memory_during_local_pickup():
    """Verify that M2 scopes out navigation failure memories when robot is at origin with pickable packages."""
    adapter_m2 = SubgoalMemoryAdapter(injection_mode="subgoal", store_mode="F")
    adapter_m1 = SubgoalMemoryAdapter(injection_mode="global", store_mode="F")

    # Seed failure: navigate(Corridor_North) failed
    for ad in (adapter_m2, adapter_m1):
        ad.on_task_start("task_0", 0)
        ad.record_action_failure(
            event_id="evt_t0_s01",
            task_id="task_0",
            action_name="navigate",
            target="Corridor_North",
            error_code="DOORWAY_BLOCKED",
            raw_message="door_north blocked",
            observation={"door": "door_north", "passage_state": "OCCUPIED"},
            sim_time=8.0,
        )
        ad.on_task_start("task_1", 1)

    # Robot at Lobby, empty inventory, package pkg_parts available in Lobby
    context_query = {
        "step_index": 1,
        "current_location": "Lobby",
        "adjacent_zones": ["Corridor_North", "Corridor_South"],
        "task_targets": ["Office_B"],
        "task_recipients": ["Charlie"],
        "candidate_entities": ["Corridor_North", "Corridor_South", "Office_B", "Charlie", "Lobby"],
        "inventory": [],
        "credentials": [],
        "task_instruction": "Deliver pkg_parts to Charlie in Office_B",
        "pickable_here": [{"package_id": "pkg_parts", "pickup_location": "Lobby"}],
        "deliverable_here": [],
    }
    known_state = {}

    # M1 (Global) WILL retrieve the navigation failure
    res_m1 = adapter_m1.retrieve_relevant_memories(known_state, context_query)
    assert len(res_m1) == 1
    assert "DOORWAY_BLOCKED" in res_m1[0]

    # M2 (Subgoal-Aware) will SCOPE OUT navigation failure because local pickup is pending and inventory is empty!
    res_m2 = adapter_m2.retrieve_relevant_memories(known_state, context_query)
    assert len(res_m2) == 0, "M2 must not inject navigation obstacle into initial pickup decision."
    assert len(adapter_m2.retrieval_audit_log) == 1
    assert len(adapter_m2.retrieval_audit_log[0]["excluded_records"]) == 1
    assert "scoped out to prevent pickup preemption" in adapter_m2.retrieval_audit_log[0]["excluded_records"][0]["reason"]


def test_subgoal_scoping_injects_nav_memory_during_navigation():
    """Verify that M2 properly injects navigation failure memory when package is held and robot is navigating."""
    adapter_m2 = SubgoalMemoryAdapter(injection_mode="subgoal", store_mode="F")
    adapter_m2.on_task_start("task_0", 0)
    adapter_m2.record_action_failure(
        event_id="evt_t0_s01",
        task_id="task_0",
        action_name="navigate",
        target="Corridor_North",
        error_code="DOORWAY_BLOCKED",
        raw_message="door_north blocked",
        observation={"door": "door_north", "passage_state": "OCCUPIED"},
        sim_time=8.0,
    )
    adapter_m2.on_task_start("task_1", 1)

    # Robot at Lobby, NOW HOLDING package pkg_parts in inventory
    context_query = {
        "step_index": 2,
        "current_location": "Lobby",
        "adjacent_zones": ["Corridor_North", "Corridor_South"],
        "task_targets": ["Office_B"],
        "task_recipients": ["Charlie"],
        "candidate_entities": ["Corridor_North", "Corridor_South", "Office_B", "Charlie", "Lobby"],
        "inventory": ["pkg_parts"],
        "credentials": [],
        "task_instruction": "Deliver pkg_parts to Charlie in Office_B",
        "pickable_here": [],
        "deliverable_here": [],
    }
    known_state = {}

    # Now that robot holds package and needs to navigate, M2 INJECTS the navigation memory!
    res_m2 = adapter_m2.retrieve_relevant_memories(known_state, context_query)
    assert len(res_m2) == 1
    assert "DOORWAY_BLOCKED" in res_m2[0]


def test_shared_observation_visibility_and_invalidation():
    """Verify that new observations update known_state and trigger dynamic invalidation in F."""
    adapter_f = SubgoalMemoryAdapter(injection_mode="subgoal", store_mode="F")
    adapter_b2 = SubgoalMemoryAdapter(injection_mode="subgoal", store_mode="B2")

    for ad in (adapter_f, adapter_b2):
        ad.on_task_start("task_0", 0)
        ad.record_action_failure(
            event_id="evt_t0_s01",
            task_id="task_0",
            action_name="navigate",
            target="Corridor_North",
            error_code="DOORWAY_BLOCKED",
            raw_message="door_north blocked",
            observation={"door": "door_north", "passage_state": "OCCUPIED"},
            sim_time=8.0,
        )
        ad.on_task_start("task_1", 1)

    # Shared observation occurs: door_north observed FREE
    obs = {"door": "door_north", "passage_state": "FREE"}
    adapter_f.record_observation("evt_obs_01", obs, 15.0)
    adapter_b2.record_observation("evt_obs_01", obs, 15.0)

    # Check F store: memory is INVALIDATED
    mem_f = adapter_f.store.get_all_memories()[0]
    assert mem_f.status == MemoryStatus.INVALIDATED

    # Check B2 store: memory remains ACTIVE (B2 ignores invalidations by definition)
    mem_b2 = adapter_b2.store.get_all_memories()[0]
    assert mem_b2.status == MemoryStatus.ACTIVE


def test_inapplicable_credential_memory_excluded():
    """Verify that Lab_Secure credential requirement is excluded when delivering to Office_A."""
    adapter_m2 = SubgoalMemoryAdapter(injection_mode="subgoal", store_mode="F")
    adapter_m2.on_task_start("task_0", 0)
    adapter_m2.record_action_failure(
        event_id="evt_t0_s01",
        task_id="task_0",
        action_name="navigate",
        target="Lab_Secure",
        error_code="ACCESS_DENIED_NO_BADGE",
        raw_message="Access denied: requires security_badge",
        observation={"door": "door_lab", "access_status": "DENIED", "required_credential": "security_badge"},
        sim_time=14.0,
    )
    adapter_m2.on_task_start("task_1", 1)

    # Current task is delivering to Office_A (no badge required)
    context_query = {
        "step_index": 1,
        "current_location": "Lobby",
        "adjacent_zones": ["Corridor_North", "Corridor_South"],
        "task_targets": ["Office_A"],
        "task_recipients": ["Alice"],
        "candidate_entities": ["Corridor_North", "Corridor_South", "Office_A", "Alice", "Lobby"],
        "inventory": ["pkg_docs"],
        "credentials": [],
        "task_instruction": "Deliver pkg_docs to Alice in Office_A",
        "pickable_here": [],
        "deliverable_here": [],
    }
    known_state = {}

    res_m2 = adapter_m2.retrieve_relevant_memories(known_state, context_query)
    assert len(res_m2) == 0, "Lab badge requirement must not be injected for Office_A delivery."
