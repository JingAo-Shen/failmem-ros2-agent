"""
Unit tests for ConditionAwareMemoryStore and Baselines in FailMem Stage 2.
"""
import pytest
from research.agent_task_repair.memory.memory_store import (
    ConditionAwareMemoryStore,
    EpistemicLevel,
    MemoryStatus,
)
from research.agent_task_repair.memory.baselines import (
    B0_NoMemory,
    B1_UnstructuredNLMemory,
    B2_StaticConditionalMemory,
    B3_DecayMemory,
    F_ConditionAwareMemory,
)


def test_memory_store_recording_and_invalidation():
    store = ConditionAwareMemoryStore()
    
    # 1. Record door blockage failure
    mem = store.record_failure(
        task_id="task_1",
        action_name="navigate",
        target="Corridor_North",
        error_code="DOORWAY_BLOCKED",
        observable_conditions={"door_north_state": "OCCUPIED"},
        raw_message="door_north blocked by obstacle",
        epistemic_level=EpistemicLevel.FACT,
        sim_time=10.0,
    )
    assert mem.status == MemoryStatus.ACTIVE
    assert len(store.get_active_memories()) == 1

    # 2. Update with irrelevant observation -> still ACTIVE
    store.update_with_observation({"door": "door_south", "passage_state": "FREE"}, current_sim_time=15.0)
    assert mem.status == MemoryStatus.ACTIVE

    # 3. Update with door_north FREE observation -> INVALIDATED
    inv_ids = store.update_with_observation({"door": "door_north", "passage_state": "FREE"}, current_sim_time=20.0)
    assert mem.mem_id in inv_ids
    assert mem.status == MemoryStatus.INVALIDATED
    assert len(store.get_active_memories()) == 0


def test_baselines_comparative_retrieval():
    b0 = B0_NoMemory()
    b1 = B1_UnstructuredNLMemory()
    b2 = B2_StaticConditionalMemory()
    b3 = B3_DecayMemory(ttl_tasks=1)
    f = F_ConditionAwareMemory()

    # Record failure across all methods
    for m in [b0, b1, b2, b3, f]:
        m.record_action_failure(
            task_id="t1",
            action_name="navigate",
            target="Corridor_North",
            error_code="DOORWAY_BLOCKED",
            raw_message="door_north blocked",
            observation={"door": "door_north", "passage_state": "OCCUPIED"},
            sim_time=10.0,
        )

    ctx = {"target_zone": "Corridor_North"}
    assert len(b0.retrieve_relevant_memories(ctx)) == 0
    assert len(b1.retrieve_relevant_memories(ctx)) == 1
    assert len(b2.retrieve_relevant_memories(ctx)) == 1
    assert len(b3.retrieve_relevant_memories(ctx)) == 1
    assert len(f.retrieve_relevant_memories(ctx)) == 1

    # Simulate obstacle removal observation
    obs = {"door": "door_north", "passage_state": "FREE"}
    b2.record_observation(obs, sim_time=20.0)
    f.record_observation(obs, sim_time=20.0)

    # B2 stays active (static), F invalidates and yields 0 active memories for Corridor_North
    assert len(b2.retrieve_relevant_memories(ctx)) == 1  # Unwarranted avoidance risk!
    assert len(f.retrieve_relevant_memories(ctx)) == 0   # Correctly invalidated!
