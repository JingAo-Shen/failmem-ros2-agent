"""
24-Task Capability Screening Benchmark for Model Evaluation (FailMem Stage 2).
Evaluates foundational model capability WITHOUT cross-task memory across 6 categories:
  1. Basic Delivery & Tool Calling (4 tasks)
  2. Capacity Constraint & Multi-Package (4 tasks)
  3. Battery Management & Recharging (4 tasks)
  4. Credential Acquisition & Preconditions (4 tasks)
  5. First-Time Obstacle Recovery (4 tasks)
  6. Multi-Target Switching & Task Completion (4 tasks)

Includes programmatic oracle feasibility verifier ensuring 100% solvability.
"""
from typing import Dict, Any, List, Tuple
import copy
from .task_env import DeliveryTaskEnv
from .tools import StatusCode


def get_24_screening_tasks() -> List[Dict[str, Any]]:
    tasks = []

    # =========================================================================
    # Group 1: Basic Delivery & Tool Calling (Tasks 1-4)
    # =========================================================================
    tasks.append({
        "task_id": "screen_01_basic_office_a",
        "category": "1_basic_delivery",
        "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_02_basic_office_b",
        "category": "1_basic_delivery",
        "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False}},
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_03_basic_from_corridor",
        "category": "1_basic_delivery",
        "instruction": "Deliver package pkg_sample from Corridor_South to Alice in Office_A.",
        "env_config": {
            "robot_start_location": "Corridor_South",
            "robot_start_battery": 100,
            "doors": {
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_sample": {"location": "Corridor_South", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_04_basic_query_and_deliver",
        "category": "1_basic_delivery",
        "instruction": "Check Charlie's status and deliver package pkg_mail from Lobby to Charlie in Office_B.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_mail": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False}},
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })

    # =========================================================================
    # Group 2: Capacity Constraints & Multi-Package (Tasks 5-8)
    # =========================================================================
    tasks.append({
        "task_id": "screen_05_cap2_two_packages",
        "category": "2_capacity_constraint",
        "instruction": "Deliver pkg_1 to Alice in Office_A and pkg_2 to Charlie in Office_B.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_06_cap2_three_packages_multitrip",
        "category": "2_capacity_constraint",
        "instruction": "Deliver pkg_1 to Alice in Office_A, pkg_2 to Charlie in Office_B, and pkg_3 to Alice in Office_A.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                "pkg_3": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_07_cap1_two_packages_multitrip",
        "category": "2_capacity_constraint",
        "instruction": "Deliver pkg_1 and pkg_2 to Alice in Office_A with limited backpack space (capacity 1).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 1,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_08_held_and_floor_packages",
        "category": "2_capacity_constraint",
        "instruction": "Deliver held pkg_1 to Alice in Office_A, and floor package pkg_2 to Charlie in Office_B.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "robot_start_inventory": ["pkg_1"],
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {
                "pkg_1": {"location": "robot_inventory", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Charlie": {"room": "Office_B", "status": "available"}},
        },
    })

    # =========================================================================
    # Group 3: Battery Management & Recharging (Tasks 9-12)
    # =========================================================================
    tasks.append({
        "task_id": "screen_09_battery_low_at_lobby",
        "category": "3_battery_management",
        "instruction": "Deliver package pkg_urgent from Lobby to Charlie in Office_B (battery critically low at 10%).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 10,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_urgent": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False}},
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_10_battery_recharge_remote",
        "category": "3_battery_management",
        "instruction": "Deliver package pkg_docs from Corridor_North to Alice in Office_A (battery low at 15%).",
        "env_config": {
            "robot_start_location": "Corridor_North",
            "robot_start_battery": 15,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_docs": {"location": "Corridor_North", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_11_battery_sufficient_tour",
        "category": "3_battery_management",
        "instruction": "Deliver pkg_1 to Office_A and pkg_2 to Office_B (full battery 100%).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_12_battery_recharge_before_multitrip",
        "category": "3_battery_management",
        "instruction": "Deliver 2 packages to Office_B with starting battery 15%.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 15,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
            },
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })

    # =========================================================================
    # Group 4: Credential Acquisition & Preconditions (Tasks 13-16)
    # =========================================================================
    tasks.append({
        "task_id": "screen_13_badge_at_lobby",
        "category": "4_credential_precondition",
        "instruction": "Acquire security_badge at Lobby and deliver pkg_secure to Bob in Lab_Secure.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {"pkg_secure": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False}},
            "room_items": {"Lobby": ["security_badge"]},
            "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_14_badge_at_office_a",
        "category": "4_credential_precondition",
        "instruction": "Deliver pkg_sample from Lobby to Bob in Lab_Secure (security_badge is in Office_A).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {"pkg_sample": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False}},
            "room_items": {"Office_A": ["security_badge"]},
            "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_15_badge_already_held",
        "category": "4_credential_precondition",
        "instruction": "Deliver pkg_hardware to Bob in Lab_Secure (badge already acquired).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "robot_start_credentials": ["security_badge"],
            "doors": {
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {"pkg_hardware": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False}},
            "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_16_badge_and_office_delivery",
        "category": "4_credential_precondition",
        "instruction": "Deliver pkg_1 to Alice in Office_A and pkg_2 to Bob in Lab_Secure (badge at Lobby).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
            },
            "room_items": {"Lobby": ["security_badge"]},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })

    # =========================================================================
    # Group 5: First-Time Obstacle Discovery & Recovery (Tasks 17-20)
    # =========================================================================
    tasks.append({
        "task_id": "screen_17_door_north_blocked_detour",
        "category": "5_obstacle_recovery",
        "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A (door_north is blocked).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_18_door_north_blocked_to_office_b",
        "category": "5_obstacle_recovery",
        "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B (door_north is blocked).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False}},
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_19_door_office_b_blocked",
        "category": "5_obstacle_recovery",
        "instruction": "Deliver package pkg_parts from Corridor_North to Charlie in Office_B (nominal door blocked).",
        "env_config": {
            "robot_start_location": "Corridor_North",
            "robot_start_battery": 100,
            "doors": {
                "door_office_b": {"blocked": True, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_parts": {"location": "Corridor_North", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_20_door_south_blocked_north_clear",
        "category": "5_obstacle_recovery",
        "instruction": "Deliver package pkg_tools from Lobby to Alice in Office_A (door_south blocked, door_north open).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_tools": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })

    # =========================================================================
    # Group 6: Multi-Target Switching & Completion Verification (Tasks 21-24)
    # =========================================================================
    tasks.append({
        "task_id": "screen_21_multitarget_two_offices",
        "category": "6_multitarget_completion",
        "instruction": "Deliver pkg_a to Alice in Office_A, and pkg_b to Charlie in Office_B.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {
                "pkg_a": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_b": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Charlie": {"room": "Office_B", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_22_multitarget_office_and_lab",
        "category": "6_multitarget_completion",
        "instruction": "Deliver pkg_a to Alice in Office_A, and pkg_b to Bob in Lab_Secure (badge at Lobby).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {
                "pkg_a": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_b": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
            },
            "room_items": {"Lobby": ["security_badge"]},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}, "Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "screen_23_multitarget_three_recipients",
        "category": "6_multitarget_completion",
        "instruction": "Deliver pkg_1 to Alice (Office_A), pkg_2 to Charlie (Office_B), and pkg_3 to Bob (Lab_Secure).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {
                "pkg_1": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_2": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                "pkg_3": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
            },
            "room_items": {"Lobby": ["security_badge"]},
            "recipients": {
                "Alice": {"room": "Office_A", "status": "available"},
                "Charlie": {"room": "Office_B", "status": "available"},
                "Bob": {"room": "Lab_Secure", "status": "available"},
            },
        },
    })
    tasks.append({
        "task_id": "screen_24_verify_all_obligations_delivered",
        "category": "6_multitarget_completion",
        "instruction": "Deliver pkg_x and pkg_y to Alice in Office_A and ensure both are verified delivered.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {
                "pkg_x": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                "pkg_y": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
            },
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })

    return tasks


def verify_screening_task_feasibility(task: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """Programmatic oracle solving each screening task to prove 100% solvability."""
    env = DeliveryTaskEnv(task["env_config"])
    tid = task["task_id"]
    actions = []

    if tid == "screen_01_basic_office_a":
        actions.append(env.step("pickup", {"package_id": "pkg_docs", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"}))

    elif tid == "screen_02_basic_office_b":
        actions.append(env.step("pickup", {"package_id": "pkg_parts", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_parts", "recipient": "Charlie"}))

    elif tid == "screen_03_basic_from_corridor":
        actions.append(env.step("pickup", {"package_id": "pkg_sample", "from_location": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_sample", "recipient": "Alice"}))

    elif tid == "screen_04_basic_query_and_deliver":
        actions.append(env.step("query_status", {"entity": "Charlie"}))
        actions.append(env.step("pickup", {"package_id": "pkg_mail", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_mail", "recipient": "Charlie"}))

    elif tid == "screen_05_cap2_two_packages":
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))

    elif tid == "screen_06_cap2_three_packages_multitrip":
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_3", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_3", "recipient": "Alice"}))

    elif tid == "screen_07_cap1_two_packages_multitrip":
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Alice"}))

    elif tid == "screen_08_held_and_floor_packages":
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))

    elif tid == "screen_09_battery_low_at_lobby":
        actions.append(env.step("recharge", {}))
        actions.append(env.step("pickup", {"package_id": "pkg_urgent", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_urgent", "recipient": "Charlie"}))

    elif tid == "screen_10_battery_recharge_remote":
        actions.append(env.step("pickup", {"package_id": "pkg_docs", "from_location": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"}))

    elif tid == "screen_11_battery_sufficient_tour":
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))

    elif tid == "screen_12_battery_recharge_before_multitrip":
        actions.append(env.step("recharge", {}))
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Charlie"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))

    elif tid == "screen_13_badge_at_lobby":
        actions.append(env.step("pickup", {"package_id": "pkg_secure", "from_location": "Lobby"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_secure", "recipient": "Bob"}))

    elif tid == "screen_14_badge_at_office_a":
        actions.append(env.step("pickup", {"package_id": "pkg_sample", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_sample", "recipient": "Bob"}))

    elif tid == "screen_15_badge_already_held":
        actions.append(env.step("pickup", {"package_id": "pkg_hardware", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_hardware", "recipient": "Bob"}))

    elif tid == "screen_16_badge_and_office_delivery":
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Bob"}))

    elif tid == "screen_17_door_north_blocked_detour":
        actions.append(env.step("pickup", {"package_id": "pkg_docs", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"}))

    elif tid == "screen_18_door_north_blocked_to_office_b":
        actions.append(env.step("pickup", {"package_id": "pkg_parts", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_parts", "recipient": "Charlie"}))

    elif tid == "screen_19_door_office_b_blocked":
        actions.append(env.step("pickup", {"package_id": "pkg_parts", "from_location": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_parts", "recipient": "Alice"}))

    elif tid == "screen_20_door_south_blocked_north_clear":
        actions.append(env.step("pickup", {"package_id": "pkg_tools", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_tools", "recipient": "Alice"}))

    elif tid == "screen_21_multitarget_two_offices":
        actions.append(env.step("pickup", {"package_id": "pkg_a", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_b", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_a", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_b", "recipient": "Charlie"}))

    elif tid == "screen_22_multitarget_office_and_lab":
        actions.append(env.step("pickup", {"package_id": "pkg_a", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_b", "from_location": "Lobby"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_a", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_b", "recipient": "Bob"}))

    elif tid == "screen_23_multitarget_three_recipients":
        actions.append(env.step("pickup", {"package_id": "pkg_1", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_2", "from_location": "Lobby"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_1", "recipient": "Alice"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_2", "recipient": "Charlie"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_3", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_3", "recipient": "Bob"}))

    elif tid == "screen_24_verify_all_obligations_delivered":
        actions.append(env.step("pickup", {"package_id": "pkg_x", "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": "pkg_y", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_x", "recipient": "Alice"}))
        actions.append(env.step("deliver", {"package_id": "pkg_y", "recipient": "Alice"}))

    summary = env.get_summary()
    all_ok = all(a.success for a in actions) and summary["success"]
    msg = f"Executed {len(actions)} actions. Final battery: {summary['final_battery']}%. Violations: {summary['constraint_violations']}."
    return all_ok, msg, summary
