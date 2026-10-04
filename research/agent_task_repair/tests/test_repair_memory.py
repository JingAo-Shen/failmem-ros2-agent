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


def test_two_layer_memory_structure_and_dynamic_route():
    """Tests two-layer memory structure and dynamic route generation from arbitrary start locations."""
    store = RepairMemoryStore()
    item = store.propose_repair(
        memory_id="mem_badge_oa",
        source_task_id="task_src_01",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_01"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
    )
    item.raw_experience = {
        "failure_step": {"tool": "navigate", "params": {"target_zone": "Lab_Secure"}},
        "explored_rooms": ["Office_A"],
    }
    item.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": "Office_A",
        "target_door": "door_lab",
    }

    # Verify and promote with authentic trajectory
    traj = [
        {"step": 1, "task_id": "task_src_01", "event_id": "evt_fail_01", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_01", "event_id": "evt_s02", "tool": "navigate", "params": {"target_zone": "Office_A"}, "result": {"success": True}, "robot_location": "Office_A"},
        {"step": 3, "task_id": "task_src_01", "event_id": "evt_s03", "tool": "observe", "params": {"target": "Office_A"}, "result": {"success": True, "observation": {"items": ["security_badge"]}}, "robot_location": "Office_A"},
        {"step": 4, "task_id": "task_src_01", "event_id": "evt_s04", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}, "robot_location": "Office_A"},
    ]
    # Proposal must match to verify
    item.repair_proposal = [
        {"action": "navigate", "params": {"target_zone": "Office_A"}},
        {"action": "observe", "params": {"target": "Office_A"}},
        {"action": "acquire_credential", "params": {"credential_name": "security_badge"}},
    ]
    ok, _ = store.verify_and_promote("mem_badge_oa", traj, ["has_credential(security_badge)"])
    assert ok is True
    assert item.verification_status == VerificationStatus.VERIFIED

    # Test dynamic instantiation from Office_B (different start location!)
    adj = {
        "Lobby": ["Corridor_North", "Corridor_South"],
        "Corridor_North": ["Lobby", "Office_A", "Office_B", "Corridor_South"],
        "Corridor_South": ["Lobby", "Corridor_North", "Office_A", "Lab_Secure"],
        "Office_A": ["Corridor_North", "Corridor_South"],
        "Office_B": ["Corridor_North"],
        "Lab_Secure": ["Corridor_South"],
    }
    nodes_from_b = item.instantiate_repair_nodes(
        variable_bindings={"origin": "Office_B", "target": "Lab_Secure"},
        robot_location="Office_B",
        adjacency_map=adj,
    )
    # Expected path from Office_B to Office_A: Corridor_North -> Office_A
    node_actions = [n.action_type for n in nodes_from_b]
    node_targets = [n.target for n in nodes_from_b]
    assert node_actions == ["navigate", "navigate", "observe", "acquire_credential"]
    assert node_targets == ["Corridor_North", "Office_A", "Office_A", "security_badge"]


def test_target_lifecycle_audit_logging():
    """Tests target-side lifecycle tracking: TARGET_RETRIEVED, TARGET_INSTANTIATED, TARGET_STEP_EXECUTED, TARGET_EFFECT_VERIFIED, TARGET_REJECTED, TARGET_INVALIDATED."""
    store = RepairMemoryStore()
    item = store.propose_repair(
        memory_id="mem_target_test",
        source_task_id="task_src_02",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_02"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    item.reusable_repair_plan = {
        "credential_name": "security_badge",
        "candidate_location": "Office_A",
    }
    traj = [
        {"step": 1, "task_id": "task_src_02", "event_id": "evt_fail_02", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_02", "event_id": "evt_s02", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    store.verify_and_promote("mem_target_test", traj, ["has_credential(security_badge)"])

    # 1. Successful Retrieval and Instantiation
    known_facts = {"requires_credential(door_lab,security_badge)": True}
    nodes = store.retrieve_repair_plan(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        current_state={"robot_location": "Corridor_South"},
        known_facts=known_facts,
        target_run_id="target_run_01",
        sim_time=15.0,
    )
    assert nodes is not None

    events = [e["event"] for e in store.target_audit_log]
    assert "TARGET_RETRIEVED" in events
    assert "TARGET_INSTANTIATED" in events

    # 2. Step execution logging
    store.log_target_step_executed(
        target_run_id="target_run_01",
        memory_id="mem_target_test",
        plan_node_id=nodes[0].id,
        tool=nodes[0].action_type,
        params=nodes[0].params,
        success=True,
        event_id="evt_tgt_s01",
        sim_time=18.0,
    )
    events = [e["event"] for e in store.target_audit_log]
    assert "TARGET_STEP_EXECUTED" in events

    # 3. Effect verification logging
    store.log_target_effect_verified(
        target_run_id="target_run_01",
        memory_id="mem_target_test",
        verified_effects=["has_credential(security_badge)"],
        sim_time=25.0,
    )
    events = [e["event"] for e in store.target_audit_log]
    assert "TARGET_EFFECT_VERIFIED" in events

    # 4. Target Invalidated
    store.update_with_observation(
        {"credential_not_found_in_Office_A": True},
        target_run_id="target_run_01",
        event_id="evt_obs_empty",
        sim_time=30.0,
    )
    events = [e["event"] for e in store.target_audit_log]
    assert "TARGET_INVALIDATED" in events
    assert item.verification_status == VerificationStatus.INVALIDATED


def test_unified_credential_fact_and_negative_applicability():
    """Tests that mismatched door/credential facts correctly reject retrieval."""
    store = RepairMemoryStore()
    item = store.propose_repair(
        memory_id="mem_lab_badge",
        source_task_id="task_src_03",
        failure_event={"action_name": "navigate", "target": "Lab_Secure", "error_code": "SECURITY_BADGE_REQUIRED", "event_id": "evt_fail_03"},
        applicability={"target": "Lab_Secure"},
        required_facts={"requires_credential(door_lab,security_badge)": True},
        invalidation_conditions={"credential_not_found_in_Office_A": True},
        expected_effects=["has_credential(security_badge)"],
        repair_proposal=[{"action": "acquire_credential", "params": {"credential_name": "security_badge"}}],
    )
    traj = [
        {"step": 1, "task_id": "task_src_03", "event_id": "evt_fail_03", "tool": "navigate", "params": {"target_zone": "Lab_Secure"}, "result": {"success": False, "error_code": "SECURITY_BADGE_REQUIRED"}},
        {"step": 2, "task_id": "task_src_03", "event_id": "evt_s02", "tool": "acquire_credential", "params": {"credential_name": "security_badge"}, "result": {"success": True, "observation": {"credentials": ["security_badge"]}}},
    ]
    store.verify_and_promote("mem_lab_badge", traj, ["has_credential(security_badge)"])

    # Test A: Unrelated door (e.g. door_vault) with different required fact
    known_facts_wrong_door = {"requires_credential(door_vault,security_badge)": True}
    res_wrong_door = store.retrieve_repair_plan(
        failed_tool="navigate",
        failed_params={"target_zone": "Vault"},
        error_code="SECURITY_BADGE_REQUIRED",
        current_state={"robot_location": "Corridor_South"},
        known_facts=known_facts_wrong_door,
        target_run_id="target_run_neg",
    )
    assert res_wrong_door is None

    # Test B: Correct door but required fact is unknown (not yet failed or observed)
    res_unknown = store.retrieve_repair_plan(
        failed_tool="navigate",
        failed_params={"target_zone": "Lab_Secure"},
        error_code="SECURITY_BADGE_REQUIRED",
        current_state={"robot_location": "Corridor_South"},
        known_facts={},
        target_run_id="target_run_neg",
    )
    assert res_unknown is None
    rej_events = [e for e in store.target_audit_log if e["event"] == "TARGET_REJECTED"]
    assert len(rej_events) > 0
    assert "UNKNOWN" in rej_events[-1]["reason"]

