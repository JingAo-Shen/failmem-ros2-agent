"""
Automated Engineering Acceptance Tests for Task Environments.
Asserts:
- Readiness check passed for all states.
- 100-probe stability test has 0 jitter.
- State A has persistent blockage + legal alternative path completes task.
- State B blockage cleared -> primary path succeeds.
- State C irrelevant attribute changed -> blockage persists, alternative path succeeds.
- State D uninspected -> probe reveals status.
- Independent verifiers detect success accurately without leaking answers.
"""

import pytest
import time
from research.conditional_constraint_memory.task_environment import (
    PortTaskEnvironment,
    FilePermissionTaskEnvironment,
    ConfigVersionMismatchSyntheticEnvironment,
    test_probe_stability_100_runs as run_100_probe_stability_check,
)


def test_100_probe_stability():
    res = run_100_probe_stability_check()
    assert res["port_stability_passed"], f"Port probe stability failed: {res['details']}"
    assert res["file_stability_passed"], f"File probe stability failed: {res['details']}"


def test_port_environment_states_and_verifier():
    env = PortTaskEnvironment()
    try:
        # State A: 18080 occupied, alternate 18081 works
        env.setup("A")
        assert env.readiness_check(), "Port readiness failed in State A"
        probe_res = env.probe(18080)
        assert probe_res["is_occupied"] is True
        
        # Primary action fails with real OS errno 98
        action_primary = env.execute_start_service(18080)
        assert action_primary["success"] is False
        assert action_primary["error_code"] == 98
        assert "Address already in use" in action_primary["stderr"]

        # Alternate action succeeds
        action_alt = env.execute_start_service(18081)
        assert action_alt["success"] is True
        assert env.verify_completion() is True

        # State B: 18080 free, primary action succeeds directly
        env.setup("B")
        assert env.readiness_check(), "Port readiness failed in State B"
        probe_b = env.probe(18080)
        assert probe_b["is_occupied"] is False
        action_b = env.execute_start_service(18080)
        assert action_b["success"] is True
        assert env.verify_completion() is True

        # State C: Irrelevant attribute changed, 18080 still occupied, 18081 succeeds
        env.setup("C")
        assert env.readiness_check(), "Port readiness failed in State C"
        probe_c = env.probe(18080)
        assert probe_c["is_occupied"] is True
        action_c1 = env.execute_start_service(18080)
        assert action_c1["success"] is False
        action_c2 = env.execute_start_service(18081)
        assert action_c2["success"] is True
        assert env.verify_completion() is True

        # State D: Uninspected/expired, probe reveals status
        env.setup("D")
        assert env.readiness_check()
        probe_d = env.probe(18080)
        assert probe_d["is_occupied"] is True

    finally:
        env.teardown()


def test_file_environment_states_and_verifier():
    env = FilePermissionTaskEnvironment()
    try:
        # State A: /etc/service_demo/app.conf 0644 non-writable, user override works
        env.setup("A")
        assert env.readiness_check(), "File readiness failed in State A"
        probe_sys = env.probe(str(env.sys_file))
        assert probe_sys["writable_by_agentuser"] is False

        # Direct write to sys file fails
        action_sys = env.execute_write_config(str(env.sys_file), "ENABLE_TELEMETRY", "true")
        assert action_sys["success"] is False
        assert action_sys["error_code"] != 0
        assert "Permission denied" in action_sys["stderr"]
        assert env.verify_completion() is False

        # Alternate write to user override succeeds
        action_user = env.execute_write_config(str(env.user_file), "ENABLE_TELEMETRY", "true")
        assert action_user["success"] is True
        assert env.verify_completion() is True

        # State B: Sys file is 0666, direct write succeeds
        env.setup("B")
        assert env.readiness_check(), "File readiness failed in State B"
        probe_b = env.probe(str(env.sys_file))
        assert probe_b["writable_by_agentuser"] is True
        action_b = env.execute_write_config(str(env.sys_file), "ENABLE_TELEMETRY", "true")
        assert action_b["success"] is True
        assert env.verify_completion() is True

        # State C: Irrelevant comment/mtime change, sys file still 0644, user override succeeds
        env.setup("C")
        assert env.readiness_check(), "File readiness failed in State C"
        probe_c = env.probe(str(env.sys_file))
        assert probe_c["writable_by_agentuser"] is False
        action_c1 = env.execute_write_config(str(env.sys_file), "ENABLE_TELEMETRY", "true")
        assert action_c1["success"] is False
        action_c2 = env.execute_write_config(str(env.user_file), "ENABLE_TELEMETRY", "true")
        assert action_c2["success"] is True
        assert env.verify_completion() is True

        # State D: Uninspected, probe reveals 0644
        env.setup("D")
        assert env.readiness_check()
        probe_d = env.probe(str(env.sys_file))
        assert probe_d["writable_by_agentuser"] is False

    finally:
        env.teardown()


def test_synthetic_config_version_environment():
    env = ConfigVersionMismatchSyntheticEnvironment()
    try:
        env.setup("A")
        assert env.readiness_check()
        assert env.probe()["is_compatible"] is False
        assert env.execute_build()["success"] is False

        env.setup("B")
        assert env.readiness_check()
        assert env.probe()["is_compatible"] is True
        assert env.execute_build()["success"] is True
        assert env.verify_completion() is True
    finally:
        env.teardown()
