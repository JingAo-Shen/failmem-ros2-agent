"""
24-Task Held-Out Verification Benchmark for FailMem Stage 2.
Evaluates 4 Groups (A: S1_M0, B: Stateful Agent, C: Fact Memory, D: Repair Memory)
across a 4 x 3 x 2 factorial design:
  - 4 Recovery Problem Categories:
      1. path_obstacle (door blocked / detour)
      2. credential_precondition (badge required)
      3. recipient_status (recipient busy / reschedule)
      4. resource_depletion (low battery recharge / multi-trip)
  - 3 Historical Relevance Types:
      1. valid_applicable (historical repair applies)
      2. stale_invalidated (environment changed / obstacle cleared)
      3. irrelevant (failure in unrelated area)
  - 2 Parameter Instances (distinct entities, origins, package sets)

Total 24 Tasks. Includes programmatic oracle feasibility verifier.
"""
from typing import Dict, Any, List, Tuple
import copy
from .task_env import DeliveryTaskEnv
from .tools import StatusCode


def get_24_heldout_tasks() -> List[Dict[str, Any]]:
    tasks = []

    # =========================================================================
    # Category 1: Path Obstacle (Tasks 1-6)
    # =========================================================================
    # 1.1 Valid Applicable (Instance A & B)
    tasks.append({
        "task_id": "heldout_01_path_valid_inst_a",
        "category": "path_obstacle",
        "relevance": "valid_applicable",
        "seed_type": "door_north_blocked",
        "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A (door_north blocked).",
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
        "task_id": "heldout_02_path_valid_inst_b",
        "category": "path_obstacle",
        "relevance": "valid_applicable",
        "seed_type": "door_north_blocked",
        "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B (door_north blocked).",
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

    # 1.2 Stale Invalidated (Instance A & B)
    tasks.append({
        "task_id": "heldout_03_path_stale_inst_a",
        "category": "path_obstacle",
        "relevance": "stale_invalidated",
        "seed_type": "door_north_cleared_observed",
        "instruction": "Deliver package pkg_tools from Lobby to Alice in Office_A (door_north cleared).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_tools": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "heldout_04_path_stale_inst_b",
        "category": "path_obstacle",
        "relevance": "stale_invalidated",
        "seed_type": "door_north_cleared_observed",
        "instruction": "Deliver package pkg_supplies from Lobby to Charlie in Office_B (door_north cleared).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_supplies": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False}},
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })

    # 1.3 Irrelevant (Instance A & B)
    tasks.append({
        "task_id": "heldout_05_path_irrelevant_inst_a",
        "category": "path_obstacle",
        "relevance": "irrelevant",
        "seed_type": "unrelated_door_office_b_blocked",
        "instruction": "Deliver package pkg_mail from Lobby to Alice in Office_A (Office_B failure irrelevant).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_mail": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "heldout_06_path_irrelevant_inst_b",
        "category": "path_obstacle",
        "relevance": "irrelevant",
        "seed_type": "unrelated_door_office_b_blocked",
        "instruction": "Deliver package pkg_letter from Corridor_South to Alice in Office_A.",
        "env_config": {
            "robot_start_location": "Corridor_South",
            "robot_start_battery": 100,
            "doors": {
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_letter": {"location": "Corridor_South", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })

    # =========================================================================
    # Category 2: Credential Preconditions (Tasks 7-12)
    # =========================================================================
    # 2.1 Valid Applicable (Instance A & B)
    tasks.append({
        "task_id": "heldout_07_cred_valid_inst_a",
        "category": "credential_precondition",
        "relevance": "valid_applicable",
        "seed_type": "lab_badge_required",
        "instruction": "Deliver package pkg_secure from Lobby to Bob in Lab_Secure (badge at Lobby).",
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
        "task_id": "heldout_08_cred_valid_inst_b",
        "category": "credential_precondition",
        "relevance": "valid_applicable",
        "seed_type": "lab_badge_required",
        "instruction": "Deliver package pkg_chem from Lobby to Bob in Lab_Secure (badge in Office_A).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {"pkg_chem": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False}},
            "room_items": {"Office_A": ["security_badge"]},
            "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })

    # 2.2 Stale Invalidated (Instance A & B)
    tasks.append({
        "task_id": "heldout_09_cred_stale_inst_a",
        "category": "credential_precondition",
        "relevance": "stale_invalidated",
        "seed_type": "lab_badge_required",
        "instruction": "Deliver pkg_sample to Bob in Lab_Secure (door_lab unlocked/no badge needed).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_lab": {"blocked": False, "requires_badge": False, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {"pkg_sample": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False}},
            "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "heldout_10_cred_stale_inst_b",
        "category": "credential_precondition",
        "relevance": "stale_invalidated",
        "seed_type": "lab_badge_required",
        "instruction": "Deliver pkg_device to Bob in Lab_Secure (badge already acquired).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "robot_start_credentials": ["security_badge"],
            "doors": {
                "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
            },
            "packages": {"pkg_device": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False}},
            "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
        },
    })

    # 2.3 Irrelevant (Instance A & B)
    tasks.append({
        "task_id": "heldout_11_cred_irrelevant_inst_a",
        "category": "credential_precondition",
        "relevance": "irrelevant",
        "seed_type": "lab_badge_required",
        "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A (Lab badge irrelevant).",
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
        "task_id": "heldout_12_cred_irrelevant_inst_b",
        "category": "credential_precondition",
        "relevance": "irrelevant",
        "seed_type": "lab_badge_required",
        "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B (Lab badge irrelevant).",
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

    # =========================================================================
    # Category 3: Recipient Status & Order Adjustment (Tasks 13-18)
    # =========================================================================
    # 3.1 Valid Applicable (Instance A & B)
    tasks.append({
        "task_id": "heldout_13_recip_valid_inst_a",
        "category": "recipient_status",
        "relevance": "valid_applicable",
        "seed_type": "clean_history",
        "instruction": "Check Charlie's status and deliver package pkg_parts to Office_B.",
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
        "task_id": "heldout_14_recip_valid_inst_b",
        "category": "recipient_status",
        "relevance": "valid_applicable",
        "seed_type": "clean_history",
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

    # 3.2 Stale Invalidated (Instance A & B)
    tasks.append({
        "task_id": "heldout_15_recip_stale_inst_a",
        "category": "recipient_status",
        "relevance": "stale_invalidated",
        "seed_type": "clean_history",
        "instruction": "Deliver pkg_docs to Alice in Office_A.",
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
        "task_id": "heldout_16_recip_stale_inst_b",
        "category": "recipient_status",
        "relevance": "stale_invalidated",
        "seed_type": "clean_history",
        "instruction": "Deliver pkg_items to Charlie in Office_B.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
            },
            "packages": {"pkg_items": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False}},
            "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
        },
    })

    # 3.3 Irrelevant (Instance A & B)
    tasks.append({
        "task_id": "heldout_17_recip_irrelevant_inst_a",
        "category": "recipient_status",
        "relevance": "irrelevant",
        "seed_type": "unrelated_door_office_b_blocked",
        "instruction": "Deliver pkg_sample to Alice in Office_A.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_sample": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })
    tasks.append({
        "task_id": "heldout_18_recip_irrelevant_inst_b",
        "category": "recipient_status",
        "relevance": "irrelevant",
        "seed_type": "unrelated_door_office_b_blocked",
        "instruction": "Deliver pkg_tools to Alice in Office_A.",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "doors": {
                "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
            },
            "packages": {"pkg_tools": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False}},
            "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
        },
    })

    # =========================================================================
    # Category 4: Resource Depletion & Recharging / Batching (Tasks 19-24)
    # =========================================================================
    # 4.1 Valid Applicable (Instance A & B)
    tasks.append({
        "task_id": "heldout_19_res_valid_inst_a",
        "category": "resource_depletion",
        "relevance": "valid_applicable",
        "seed_type": "clean_history",
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
        "task_id": "heldout_20_res_valid_inst_b",
        "category": "resource_depletion",
        "relevance": "valid_applicable",
        "seed_type": "clean_history",
        "instruction": "Deliver pkg_1 to Office_A, pkg_2 to Office_B, and pkg_3 to Office_A (capacity=2, multi-trip needed).",
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

    # 4.2 Stale Invalidated (Instance A & B)
    tasks.append({
        "task_id": "heldout_21_res_stale_inst_a",
        "category": "resource_depletion",
        "relevance": "stale_invalidated",
        "seed_type": "clean_history",
        "instruction": "Deliver pkg_parts to Charlie in Office_B (battery full 100%, no recharge needed).",
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
        "task_id": "heldout_22_res_stale_inst_b",
        "category": "resource_depletion",
        "relevance": "stale_invalidated",
        "seed_type": "clean_history",
        "instruction": "Deliver pkg_1 and pkg_2 to Alice in Office_A (capacity 2, single-trip feasible).",
        "env_config": {
            "robot_start_location": "Lobby",
            "robot_start_battery": 100,
            "max_inventory_capacity": 2,
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

    # 4.3 Irrelevant (Instance A & B)
    tasks.append({
        "task_id": "heldout_23_res_irrelevant_inst_a",
        "category": "resource_depletion",
        "relevance": "irrelevant",
        "seed_type": "unrelated_door_office_b_blocked",
        "instruction": "Deliver pkg_docs to Alice in Office_A (full battery 100%).",
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
        "task_id": "heldout_24_res_irrelevant_inst_b",
        "category": "resource_depletion",
        "relevance": "irrelevant",
        "seed_type": "unrelated_door_office_b_blocked",
        "instruction": "Deliver pkg_parts to Charlie in Office_B (full battery 100%).",
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

    return tasks


def verify_heldout_task_feasibility(task: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """Oracle feasibility verifier ensuring every heldout task is solvable."""
    env = DeliveryTaskEnv(task["env_config"])
    tid = task["task_id"]
    actions = []

    if tid == "heldout_01_path_valid_inst_a":
        actions.append(env.step("pickup", {"package_id": "pkg_docs", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_docs", "recipient": "Alice"}))

    elif tid == "heldout_02_path_valid_inst_b":
        actions.append(env.step("pickup", {"package_id": "pkg_parts", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_parts", "recipient": "Charlie"}))

    elif tid in ("heldout_03_path_stale_inst_a", "heldout_05_path_irrelevant_inst_a", "heldout_11_cred_irrelevant_inst_a", "heldout_15_recip_stale_inst_a", "heldout_17_recip_irrelevant_inst_a", "heldout_18_recip_irrelevant_inst_b", "heldout_23_res_irrelevant_inst_a"):
        actions.append(env.step("pickup", {"package_id": list(env.packages.keys())[0], "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": list(env.packages.keys())[0], "recipient": "Alice"}))

    elif tid in ("heldout_04_path_stale_inst_b", "heldout_12_cred_irrelevant_inst_b", "heldout_16_recip_stale_inst_b", "heldout_21_res_stale_inst_a", "heldout_24_res_irrelevant_inst_b"):
        actions.append(env.step("pickup", {"package_id": list(env.packages.keys())[0], "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": list(env.packages.keys())[0], "recipient": "Charlie"}))

    elif tid == "heldout_06_path_irrelevant_inst_b":
        actions.append(env.step("pickup", {"package_id": "pkg_letter", "from_location": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": "pkg_letter", "recipient": "Alice"}))

    elif tid == "heldout_07_cred_valid_inst_a":
        actions.append(env.step("pickup", {"package_id": "pkg_secure", "from_location": "Lobby"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_secure", "recipient": "Bob"}))

    elif tid == "heldout_08_cred_valid_inst_b":
        actions.append(env.step("pickup", {"package_id": "pkg_chem", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("acquire_credential", {"credential_name": "security_badge"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_chem", "recipient": "Bob"}))

    elif tid == "heldout_09_cred_stale_inst_a":
        actions.append(env.step("pickup", {"package_id": "pkg_sample", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_sample", "recipient": "Bob"}))

    elif tid == "heldout_10_cred_stale_inst_b":
        actions.append(env.step("pickup", {"package_id": "pkg_device", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_South"}))
        actions.append(env.step("navigate", {"target_zone": "Lab_Secure"}))
        actions.append(env.step("deliver", {"package_id": "pkg_device", "recipient": "Bob"}))

    elif tid in ("heldout_13_recip_valid_inst_a",):
        actions.append(env.step("query_status", {"entity": "Charlie"}))
        actions.append(env.step("pickup", {"package_id": "pkg_parts", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_parts", "recipient": "Charlie"}))

    elif tid in ("heldout_14_recip_valid_inst_b", "heldout_22_res_stale_inst_b"):
        pkgs = list(env.packages.keys())
        actions.append(env.step("pickup", {"package_id": pkgs[0], "from_location": "Lobby"}))
        actions.append(env.step("pickup", {"package_id": pkgs[1], "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_A"}))
        actions.append(env.step("deliver", {"package_id": pkgs[0], "recipient": "Alice"}))
        if len(pkgs) > 1 and env.packages[pkgs[1]]["target_room"] == "Office_B":
            actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
            actions.append(env.step("navigate", {"target_zone": "Office_B"}))
            actions.append(env.step("deliver", {"package_id": pkgs[1], "recipient": "Charlie"}))
        else:
            actions.append(env.step("deliver", {"package_id": pkgs[1], "recipient": "Alice"}))

    elif tid == "heldout_19_res_valid_inst_a":
        actions.append(env.step("recharge", {}))
        actions.append(env.step("pickup", {"package_id": "pkg_urgent", "from_location": "Lobby"}))
        actions.append(env.step("navigate", {"target_zone": "Corridor_North"}))
        actions.append(env.step("navigate", {"target_zone": "Office_B"}))
        actions.append(env.step("deliver", {"package_id": "pkg_urgent", "recipient": "Charlie"}))

    elif tid == "heldout_20_res_valid_inst_b":
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

    summary = env.get_summary()
    all_ok = all(a.success for a in actions) and summary["success"]
    msg = f"Executed {len(actions)} actions. Final battery: {summary['final_battery']}%. Violations: {summary['constraint_violations']}."
    return all_ok, msg, summary
