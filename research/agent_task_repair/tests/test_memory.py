"""
Unit tests for ConditionAwareMemoryStore, Baselines, and Three-Valued Logic in FailMem Stage 2.
"""
import pytest
from research.agent_task_repair.memory.memory_store import (
    ConditionAwareMemoryStore,
    EpistemicLevel,
    MemoryStatus,
    ConditionMatchResult,
)
from research.agent_task_repair.memory.baselines import (
    B0_NoMemory,
    B1_UnstructuredNLMemory,
    B2_StaticConditionalMemory,
    B3_DecayMemory,
    F_ConditionAwareMemory,
)


def test_three_valued_condition_matching():
    """Verify that 3-valued condition matching returns MATCH, MISMATCH, and UNKNOWN."""
    store = ConditionAwareMemoryStore()
    mem = store.record_failure(
        event_id="evt_t0_s01_fail",
        task_id="task_1",
        action_name="navigate",
        target="Corridor_North",
        error_code="DOORWAY_BLOCKED",
        observable_conditions={"door_north_state": "OCCUPIED", "robot_mode": "STANDARD"},
        raw_message="door_north blocked",
    )

    # 1. State matches all conditions -> MATCH
    state_match = {"door_north_state": "OCCUPIED", "robot_mode": "STANDARD"}
    assert mem.evaluate_applicability(state_match) == ConditionMatchResult.MATCH

    # 2. State contradicts at least one condition -> MISMATCH
    state_mismatch = {"door_north_state": "FREE", "robot_mode": "STANDARD"}
    assert mem.evaluate_applicability(state_mismatch) == ConditionMatchResult.MISMATCH

    # 3. State has missing condition -> UNKNOWN (cannot assume MATCH)
    state_unknown = {"robot_mode": "STANDARD"}  # door_north_state missing
    assert mem.evaluate_applicability(state_unknown) == ConditionMatchResult.UNKNOWN
    assert mem.evaluate_applicability(state_unknown) != ConditionMatchResult.MATCH


def test_observation_invalidates_only_relevant_memory():
    """Verify that observation only invalidates contradicted conditions in Method F."""
    store = ConditionAwareMemoryStore()
    m1 = store.record_failure(
        event_id="evt_1",
        task_id="t1",
        action_name="navigate",
        target="Corridor_North",
        error_code="DOORWAY_BLOCKED",
        observable_conditions={"door_north_state": "OCCUPIED"},
        raw_message="door_north blocked",
    )
    m2 = store.record_failure(
        event_id="evt_2",
        task_id="t1",
        action_name="navigate",
        target="Lab_Secure",
        error_code="SECURITY_BADGE_REQUIRED",
        observable_conditions={"required_credential": "security_badge"},
        raw_message="badge needed",
    )

    # Observation: door_north is FREE
    inv_ids = store.update_with_observation({"door": "door_north", "passage_state": "FREE"}, current_sim_time=10.0)
    assert m1.mem_id in inv_ids
    assert m1.status == MemoryStatus.INVALIDATED
    assert m2.status == MemoryStatus.ACTIVE  # Unrelated memory remains intact


def test_ttl_expiration_triggers_on_calibrated_task():
    """Verify that B3 TTL=1 expires correctly on Task T+2."""
    b3 = B3_DecayMemory(ttl_tasks=1)
    
    # Task 0: record failure
    b3.on_task_start("t0", 0)
    b3.record_action_failure(
        event_id="evt_t0_s01",
        task_id="t0",
        action_name="navigate",
        target="Corridor_North",
        error_code="DOORWAY_BLOCKED",
        raw_message="door_north blocked",
        observation={"door": "door_north", "passage_state": "OCCUPIED"},
        sim_time=10.0,
    )

    # Task 1 (age = 1 <= 1) -> ACTIVE
    b3.on_task_start("t1", 1)
    res_t1 = b3.retrieve_relevant_memories({}, {"target_zone": "Corridor_North"})
    assert len(res_t1) == 1

    # Task 2 (age = 2 > 1) -> EXPIRED
    b3.on_task_start("t2", 2)
    res_t2 = b3.retrieve_relevant_memories({}, {"target_zone": "Corridor_North"})
    assert len(res_t2) == 0, "Memory should have expired at age=2 under TTL=1"


def test_baselines_comparative_retrieval():
    b0 = B0_NoMemory()
    b1 = B1_UnstructuredNLMemory()
    b2 = B2_StaticConditionalMemory()
    b3 = B3_DecayMemory(ttl_tasks=1)
    f = F_ConditionAwareMemory()

    for m in [b0, b1, b2, b3, f]:
        m.on_task_start("t0", 0)
        m.record_action_failure(
            event_id="evt_0",
            task_id="t0",
            action_name="navigate",
            target="Corridor_North",
            error_code="DOORWAY_BLOCKED",
            raw_message="door_north blocked",
            observation={"door": "door_north", "passage_state": "OCCUPIED"},
            sim_time=10.0,
        )

    ctx = {"target_zone": "Corridor_North"}
    known = {"door_north_state": "OCCUPIED"}
    assert len(b0.retrieve_relevant_memories(known, ctx)) == 0
    assert len(b1.retrieve_relevant_memories(known, ctx)) == 1
    assert len(b2.retrieve_relevant_memories(known, ctx)) == 1
    assert len(b3.retrieve_relevant_memories(known, ctx)) == 1
    assert len(f.retrieve_relevant_memories(known, ctx)) == 1

    # Observation: door_north is now FREE
    obs = {"door": "door_north", "passage_state": "FREE"}
    b2.record_observation("evt_obs", obs, sim_time=20.0)
    f.record_observation("evt_obs", obs, sim_time=20.0)

    # In B2, memory stays active (static); in F, memory is invalidated
    known_free = {"door_north_state": "FREE"}
    assert len(b2.retrieve_relevant_memories(known_free, ctx)) == 0  # Precondition mismatch in retrieval
    assert len(f.retrieve_relevant_memories(known_free, ctx)) == 0   # Active invalidation in store
