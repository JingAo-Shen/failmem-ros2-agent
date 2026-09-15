import pytest
from src.sim_env import RobotSimEnvironment
from src.failmem import FailureMemoryStore

def test_sim_environment_fault_injection():
    task = {"id": "t1", "fault_type": "path_blocked", "injected_fault_step": 1, "goal_coord": [5.0, 5.0]}
    env = RobotSimEnvironment(task)
    success, msg, obs = env.step("navigate")
    assert not success
    assert "Path blocked" in msg

def test_failure_memory_expiry():
    store = FailureMemoryStore()
    store.record_failure({"id": "m1", "symptom": "blocked", "recovery_action": "clear_costmap", "map_version": 1})
    
    # Map version 1 -> valid
    assert store.retrieve_recovery("blocked", current_map_version=1) == "clear_costmap"
    # Map version 0 -> invalid/stale
    assert store.retrieve_recovery("blocked", current_map_version=0) is None
    store.close()
