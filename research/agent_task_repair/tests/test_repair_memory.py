"""
Unit tests for Evidence-Backed Repair Memory (repair_memory.py).
Tests:
  - Structured schema validation
  - Invalidation engine
  - Variable substitution and template instantiation
  - Applicability evaluation
Zero LLM calls required.
"""
import pytest
from research.agent_task_repair.memory.repair_memory import RepairMemoryStore, RepairMemoryItem, VerificationStatus


def test_repair_memory_store_and_instantiation():
    store = RepairMemoryStore()
    item = store.record_repair_experience(
        memory_id="rmem_01",
        failure_signature={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        applicability={"origin": "Lobby", "blocked_entity": "door_north"},
        required_facts=["door_north_state == OCCUPIED"],
        repair_steps=[
            {"action": "navigate", "params": {"target_zone": "$detour_zone"}},
            {"action": "navigate", "params": {"target_zone": "$target"}},
        ],
        expected_effects=["at_location($target)"],
        evidence_refs=["evt_t1_s01", "evt_t1_s02_repair_ok"],
        invalidation_conditions={"door_north_state": "FREE"},
        verification_status=VerificationStatus.VERIFIED,
    )

    assert item.verification_status == VerificationStatus.VERIFIED
    assert len(store.get_all_memories()) == 1

    # Test retrieval and variable substitution
    current_state = {"robot_location": "Lobby"}
    known_facts = {"door_north_state": "OCCUPIED"}
    nodes = store.retrieve_repair_plan(
        failed_tool="navigate",
        failed_params={"target_zone": "Corridor_North"},
        error_code="DOORWAY_BLOCKED",
        current_state=current_state,
        known_facts=known_facts,
    )

    assert nodes is not None
    assert len(nodes) == 2
    assert nodes[0].action_type == "navigate"
    assert nodes[0].params["target_zone"] == "Corridor_South"  # $detour_zone bound to Corridor_South from Lobby


def test_repair_memory_invalidation():
    store = RepairMemoryStore()
    item = store.record_repair_experience(
        memory_id="rmem_02",
        failure_signature={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED"},
        applicability={"origin": "Lobby", "blocked_entity": "door_north"},
        required_facts=["door_north_state == OCCUPIED"],
        repair_steps=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
        expected_effects=["at_location(Corridor_South)"],
        evidence_refs=["evt_01"],
        invalidation_conditions={"door_north_state": "FREE"},
        verification_status=VerificationStatus.VERIFIED,
    )

    # Observation confirms door_north is FREE -> must INVALIDATE
    store.update_with_observation({"door": "door_north", "passage_state": "FREE"})
    assert item.verification_status == VerificationStatus.INVALIDATED

    # Retrieval after invalidation must return None
    current_state = {"robot_location": "Lobby"}
    known_facts = {"door_north_state": "FREE"}
    nodes = store.retrieve_repair_plan(
        failed_tool="navigate",
        failed_params={"target_zone": "Corridor_North"},
        error_code="DOORWAY_BLOCKED",
        current_state=current_state,
        known_facts=known_facts,
    )
    assert nodes is None
