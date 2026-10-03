"""
Unit tests for 24-Task Held-Out Benchmark and Diagnostic Components.
"""
import pytest
from research.agent_task_repair.env.heldout_tasks_24 import (
    get_24_heldout_tasks,
    verify_heldout_task_feasibility,
)
from research.agent_task_repair.eval.run_heldout_diagnosis_96 import create_repair_memory_store
from research.agent_task_repair.memory.repair_memory import VerificationStatus


def test_24_heldout_tasks_structure():
    tasks = get_24_heldout_tasks()
    assert len(tasks) == 24, f"Expected 24 tasks, got {len(tasks)}"

    categories = set(t["category"] for t in tasks)
    assert categories == {"path_obstacle", "credential_precondition", "recipient_status", "resource_depletion"}

    relevances = set(t["relevance"] for t in tasks)
    assert relevances == {"valid_applicable", "stale_invalidated", "irrelevant"}

    for t in tasks:
        assert "task_id" in t
        assert "instruction" in t
        assert "env_config" in t
        assert "seed_type" in t


def test_all_24_heldout_tasks_oracle_feasibility():
    tasks = get_24_heldout_tasks()
    for t in tasks:
        ok, msg, summary = verify_heldout_task_feasibility(t)
        assert ok, f"Task {t['task_id']} failed feasibility check: {msg}"
        assert summary["success"] is True


def test_repair_memory_store_creation_and_invalidation():
    # 1. Door blocked -> verified
    store1 = create_repair_memory_store("door_north_blocked", {}, [])
    mems1 = store1.get_all_memories()
    assert len(mems1) == 1
    assert mems1[0].verification_status == VerificationStatus.VERIFIED

    # 2. Door cleared observed -> invalidated
    shared_obs = {"door_north_state": "FREE"}
    store2 = create_repair_memory_store("door_north_cleared_observed", shared_obs, [])
    mems2 = store2.get_all_memories()
    assert len(mems2) == 1
    assert mems2[0].verification_status == VerificationStatus.INVALIDATED

    # 3. Lab badge -> verified
    store3 = create_repair_memory_store("lab_badge_required", {}, [])
    mems3 = store3.get_all_memories()
    assert len(mems3) == 1
    assert mems3[0].verification_status == VerificationStatus.VERIFIED
    assert mems3[0].failure_signature["error_code"] == "SECURITY_BADGE_REQUIRED"
