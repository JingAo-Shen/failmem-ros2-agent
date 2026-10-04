"""
Unit tests for Evidence-Backed Repair Memory (repair_memory.py).
Tests:
  - Structured schema validation and variable substitution
  - Invalidation engine
  - Single trusted verification entry point (verify_and_promote)
  - 4 Required Counterexample Tests:
      1. Only failure evidence in trajectory (no subsequent repair execution)
      2. Same action type but mismatched parameters (e.g. wrong room navigated)
      3. Cross-task spliced evidence (events from different task_id / run_id)
      4. Manual verified=True / bypass flags in record_repair_experience ignored
Zero LLM calls required.
"""
import pytest
from research.agent_task_repair.memory.repair_memory import RepairMemoryStore, RepairMemoryItem, VerificationStatus, MemoryLifecycleState


def test_repair_memory_store_and_instantiation():
    store = RepairMemoryStore()
    item = store.propose_repair(
        memory_id="rmem_01",
        source_task_id="task_t1",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED", "event_id": "evt_t1_s01"},
        applicability={"origin": "Lobby", "blocked_entity": "door_north"},
        required_facts={"door_north_state": "OCCUPIED"},
        repair_proposal=[
            {"action": "navigate", "params": {"target_zone": "$detour_zone"}},
            {"action": "navigate", "params": {"target_zone": "$target"}},
        ],
        expected_effects=["at_location(Corridor_North)"],
        invalidation_conditions={"door_north_state": "FREE"},
    )
    assert item.verification_status == VerificationStatus.UNVERIFIED

    # Authentic trajectory execution on task_t1
    valid_traj = [
        {
            "step": 1,
            "task_id": "task_t1",
            "run_id": "run_01",
            "event_id": "evt_t1_s01",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"success": False, "error_code": "DOORWAY_BLOCKED"},
            "robot_location": "Lobby",
        },
        {
            "step": 2,
            "task_id": "task_t1",
            "run_id": "run_01",
            "event_id": "evt_t1_s02",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_South"},
            "result": {"success": True},
            "robot_location": "Corridor_South",
            "robot_location_after": "Corridor_South",
        },
        {
            "step": 3,
            "task_id": "task_t1",
            "run_id": "run_01",
            "event_id": "evt_t1_s03",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"success": True},
            "robot_location": "Corridor_North",
            "robot_location_after": "Corridor_North",
        },
    ]

    ok, msg = store.verify_and_promote("rmem_01", valid_traj, expected_effects=["at_location(Corridor_North)"])
    assert ok is True
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
    assert nodes[0].params["target_zone"] == "Corridor_South"  # detour zone
    assert nodes[1].action_type == "navigate"
    assert nodes[1].params["target_zone"] == "Corridor_North"  # final target


def test_repair_memory_invalidation():
    store = RepairMemoryStore()
    item = store.propose_repair(
        memory_id="rmem_02",
        source_task_id="task_t1",
        failure_event={"action_name": "navigate", "target": "Corridor_North", "error_code": "DOORWAY_BLOCKED", "event_id": "evt_t1_s01"},
        applicability={"origin": "Lobby", "blocked_entity": "door_north"},
        required_facts={"door_north_state": "OCCUPIED"},
        repair_proposal=[{"action": "navigate", "params": {"target_zone": "Corridor_South"}}],
        expected_effects=["at_location(Corridor_South)"],
        invalidation_conditions={"door_north_state": "FREE"},
    )

    valid_traj = [
        {
            "step": 1,
            "task_id": "task_t1",
            "run_id": "run_01",
            "event_id": "evt_t1_s01",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_North"},
            "result": {"success": False, "error_code": "DOORWAY_BLOCKED"},
            "robot_location": "Lobby",
        },
        {
            "step": 2,
            "task_id": "task_t1",
            "run_id": "run_01",
            "event_id": "evt_t1_s02",
            "tool": "navigate",
            "params": {"target_zone": "Corridor_South"},
            "result": {"success": True},
            "robot_location": "Corridor_South",
            "robot_location_after": "Corridor_South",
        },
    ]

    ok, _ = store.verify_and_promote("rmem_02", valid_traj)
    assert ok is True
    assert item.verification_status == VerificationStatus.VERIFIED

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


# =========================================================================
# 4 Required Counterexample Tests
# =========================================================================

def test_counterexample_1_only_failure_no_repair():
    """Counterexample 1: Trajectory contains only the failure event with no subsequent repair execution."""
    store = RepairMemoryStore()
    store.propose_repair(
        memory_id="rmem_ce1",
        source_task_id="task_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_01"},
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
        expected_effects=["has_credential(security_badge)"],
    )

    traj_only_fail = [
        {
            "step": 1,
            "task_id": "task_01",
            "run_id": "run_01",
            "event_id": "evt_01",
            "tool": "navigate",
            "params": {"target_zone": "Lab_Secure"},
            "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"},
            "robot_location": "Corridor_South",
        }
    ]

    ok, msg = store.verify_and_promote("rmem_ce1", traj_only_fail)
    assert ok is False
    assert store.memories["rmem_ce1"].verification_status == VerificationStatus.UNVERIFIED
    assert "No subsequent actions" in msg or "only failure evidence" in msg


def test_counterexample_2_mismatched_params():
    """Counterexample 2: Trajectory executes same action type (navigate) but with wrong target room."""
    store = RepairMemoryStore()
    store.propose_repair(
        memory_id="rmem_ce2",
        source_task_id="task_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_01"},
        repair_proposal=[
            {"action": "navigate", "params": {"target_zone": "Office_A"}},
            {"action": "acquire_credential", "params": {"credential_name": "security_badge"}},
        ],
        expected_effects=["has_credential(security_badge)"],
    )

    traj_wrong_params = [
        {
            "step": 1,
            "task_id": "task_01",
            "run_id": "run_01",
            "event_id": "evt_01",
            "tool": "navigate",
            "params": {"target_zone": "Lab_Secure"},
            "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"},
            "robot_location": "Corridor_South",
        },
        {
            "step": 2,
            "task_id": "task_01",
            "run_id": "run_01",
            "event_id": "evt_02",
            "tool": "navigate",
            "params": {"target_zone": "Office_B"},  # Went to Office_B instead of Office_A!
            "result": {"success": True},
            "robot_location": "Office_B",
            "robot_location_after": "Office_B",
        },
        {
            "step": 3,
            "task_id": "task_01",
            "run_id": "run_01",
            "event_id": "evt_03",
            "tool": "acquire_credential",
            "params": {"credential_name": "security_badge"},
            "result": {"success": True, "observation": {"credentials": ["security_badge"]}},
            "robot_location": "Office_B",
            "robot_location_after": "Office_B",
        },
    ]

    ok, msg = store.verify_and_promote("rmem_ce2", traj_wrong_params)
    assert ok is False
    assert store.memories["rmem_ce2"].verification_status == VerificationStatus.UNVERIFIED
    assert "parameter mismatch" in msg


def test_counterexample_3_cross_task_splicing():
    """Counterexample 3: Trajectory combines steps from different tasks / run IDs."""
    store = RepairMemoryStore()
    store.propose_repair(
        memory_id="rmem_ce3",
        source_task_id="task_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_01"},
        repair_proposal=[
            {"action": "navigate", "params": {"target_zone": "Office_A"}},
            {"action": "acquire_credential", "params": {"credential_name": "security_badge"}},
        ],
        expected_effects=["has_credential(security_badge)"],
    )

    traj_spliced = [
        {
            "step": 1,
            "task_id": "task_01",
            "run_id": "run_01",
            "event_id": "evt_run1_s01",
            "tool": "navigate",
            "params": {"target_zone": "Lab_Secure"},
            "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"},
            "robot_location": "Corridor_South",
        },
        {
            "step": 2,
            "task_id": "task_99",  # Cross-task spliced event!
            "run_id": "run_99",
            "event_id": "evt_run99_s02",
            "tool": "navigate",
            "params": {"target_zone": "Office_A"},
            "result": {"success": True},
            "robot_location": "Office_A",
            "robot_location_after": "Office_A",
        },
    ]

    ok, msg = store.verify_and_promote("rmem_ce3", traj_spliced)
    assert ok is False
    assert store.memories["rmem_ce3"].verification_status == VerificationStatus.UNVERIFIED
    assert "Cross-task spliced" in msg


def test_counterexample_4_manual_verified_flag_ignored():
    """Counterexample 4: Passing verified=True or VERIFIED status to record_repair_experience cannot bypass verification."""
    store = RepairMemoryStore()
    item = store.record_repair_experience(
        memory_id="rmem_ce4",
        source_task_id="task_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED"},
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
        verification_evidence={"verified": True, "evidence_refs": ["evt_fake_01"]},
        verification_status=VerificationStatus.VERIFIED,  # Attempted manual bypass!
    )

    # Must strictly remain UNVERIFIED
    assert item.verification_status == VerificationStatus.UNVERIFIED
    assert item.lifecycle_state == MemoryLifecycleState.PROPOSED

    # Retrieval must return None because it is not verified
    nodes = store.retrieve_repair_plan(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        current_state={"robot_location": "Corridor_South"},
        known_facts={},
    )
    assert nodes is None
