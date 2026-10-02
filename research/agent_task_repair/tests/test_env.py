"""
Unit tests for DeliveryTaskEnv in FailMem Stage 2.
"""
import pytest
from research.agent_task_repair.env.task_env import DeliveryTaskEnv
from research.agent_task_repair.env.tools import StatusCode


def test_env_basic_navigation_and_battery():
    env = DeliveryTaskEnv({
        "robot_start_location": "Lobby",
        "robot_start_battery": 100,
    })
    res = env.step("navigate", {"target_zone": "Corridor_North"})
    assert res.success is True
    assert env.robot_location == "Corridor_North"
    assert env.battery < 100
    assert env.sim_time_s > 0.0


def test_env_door_blocked():
    env = DeliveryTaskEnv({
        "robot_start_location": "Lobby",
        "doors": {
            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
        },
    })
    res = env.step("navigate", {"target_zone": "Corridor_North"})
    assert res.success is False
    assert res.status == StatusCode.DOOR_BLOCKED
    assert res.error_code == "DOORWAY_BLOCKED"
    assert env.robot_location == "Lobby"  # stays at Lobby


def test_env_security_badge_requirement():
    env = DeliveryTaskEnv({
        "robot_start_location": "Corridor_South",
        "doors": {
            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
        },
        "robot_start_credentials": [],
    })
    res = env.step("navigate", {"target_zone": "Lab_Secure"})
    assert res.success is False
    assert res.status == StatusCode.ACCESS_DENIED_NO_BADGE

    # Add credential and retry
    env.credentials.add("security_badge")
    res2 = env.step("navigate", {"target_zone": "Lab_Secure"})
    assert res2.success is True
    assert env.robot_location == "Lab_Secure"


def test_env_pickup_and_delivery_lifecycle():
    env = DeliveryTaskEnv({
        "robot_start_location": "Lobby",
        "packages": {
            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
        },
        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
    })
    # 1. Pickup package
    res_pk = env.step("pickup", {"package_id": "pkg_docs", "from_location": "Lobby"})
    assert res_pk.success is True
    assert "pkg_docs" in env.inventory

    # 2. Navigate to Office_A
    env.step("navigate", {"target_zone": "Corridor_North"})
    env.step("navigate", {"target_zone": "Office_A"})
    assert env.robot_location == "Office_A"

    # 3. Deliver to Alice
    res_del = env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"})
    assert res_del.success is True
    assert "pkg_docs" not in env.inventory
    assert env.is_all_delivered() is True


def test_env_recipient_busy():
    env = DeliveryTaskEnv({
        "robot_start_location": "Office_B",
        "packages": {
            "pkg_meds": {"location": "Office_B", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
        },
        "recipients": {"Charlie": {"room": "Office_B", "status": "in_meeting"}},
    })
    env.inventory.append("pkg_meds")
    res = env.step("deliver", {"package_id": "pkg_meds", "recipient": "Charlie"})
    assert res.success is False
    assert res.status == StatusCode.RECIPIENT_BUSY
