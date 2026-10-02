"""
Task Scenario Generators for FailMem Stage 2 Pilot Evaluation.
Generates paired task sequences across Development, Category 1 (Valid),
Category 2 (Stale), and Category 3 (Inapplicable).
"""
from typing import Dict, Any, List


def get_development_scenarios() -> List[Dict[str, Any]]:
    """3 development sequences for calibration and interface verification."""
    return [
        {
            "sequence_id": "dev_seq_1",
            "name": "Dev Basic Multi-Delivery",
            "category": "dev",
            "tasks": [
                {
                    "task_id": "dev_t1",
                    "instruction": "Deliver pkg_docs from Lobby to Alice in Office_A.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 100,
                        "doors": {
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        },
                        "packages": {
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                }
            ],
        },
        {
            "sequence_id": "dev_seq_2",
            "name": "Dev Door Obstacle Calibration",
            "category": "dev",
            "tasks": [
                {
                    "task_id": "dev_t2_learn",
                    "instruction": "Deliver pkg_docs to Alice in Office_A. If Corridor_North is blocked, use Corridor_South detour.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "doors": {
                            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                        },
                        "packages": {
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                    },
                }
            ],
        },
        {
            "sequence_id": "dev_seq_3",
            "name": "Dev Badge Requirement Calibration",
            "category": "dev",
            "tasks": [
                {
                    "task_id": "dev_t3_learn",
                    "instruction": "Deliver pkg_hardware to Bob in Lab_Secure. Lab requires security badge.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "doors": {
                            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                        },
                        "packages": {
                            "pkg_hardware": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                        },
                        "room_items": {"Office_A": ["security_badge"]},
                    },
                }
            ],
        },
    ]


def get_pilot_scenarios() -> List[Dict[str, Any]]:
    """
    15 paired pilot evaluation sequences (5 per category).
    Each sequence consists of:
      Task 1 (Acquisition Task): Agent encounters an environment event / failure / condition.
      Task 2 (Evaluation Task): Evaluates whether memory correctly guides or misguides the agent.
    """
    scenarios = []

    # =========================================================================
    # CATEGORY 1: Valid Experience (5 Sequences)
    # The barrier/condition persists in Task 2. Memory should prevent retrying.
    # =========================================================================
    for i in range(1, 6):
        scenarios.append({
            "sequence_id": f"cat1_valid_seq_{i}",
            "category": "Cat1_Valid",
            "name": f"Valid Memory Sequence {i} (Persisting Obstacle / Lock)",
            "tasks": [
                {
                    "task_id": f"cat1_s{i}_t1_learn",
                    "instruction": "Deliver urgent package pkg_docs to Alice in Office_A.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 90,
                        "doors": {
                            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                        },
                        "packages": {
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
                {
                    "task_id": f"cat1_s{i}_t2_eval",
                    "instruction": "Deliver second package pkg_meds to Charlie in Office_B.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 80,
                        "doors": {
                            # Obstacle still present!
                            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                        },
                        "packages": {
                            "pkg_meds": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                        },
                        "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                    },
                },
            ],
        })

    # =========================================================================
    # CATEGORY 2: Stale Experience (5 Sequences)
    # The barrier/condition resolves in Task 2. Memory should NOT cause unwarranted avoidance.
    # =========================================================================
    for i in range(1, 6):
        scenarios.append({
            "sequence_id": f"cat2_stale_seq_{i}",
            "category": "Cat2_Stale",
            "name": f"Stale Memory Sequence {i} (Obstacle Cleared / Recipient Available)",
            "tasks": [
                {
                    "task_id": f"cat2_s{i}_t1_learn",
                    "instruction": "Attempt delivery of pkg_docs to Alice in Office_A (door_north is blocked in T1).",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 90,
                        "doors": {
                            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        },
                        "packages": {
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
                {
                    "task_id": f"cat2_s{i}_t2_eval",
                    "instruction": "Deliver urgent package pkg_meds to Alice in Office_A. Obstacle has been removed.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 75,
                        "doors": {
                            # Obstacle cleared! Door north is now FREE!
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        },
                        "packages": {
                            "pkg_meds": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
            ],
        })

    # =========================================================================
    # CATEGORY 3: Inapplicable Experience (5 Sequences)
    # Surface similarity exists, but target room/action/condition differs.
    # =========================================================================
    for i in range(1, 6):
        scenarios.append({
            "sequence_id": f"cat3_inapplicable_seq_{i}",
            "category": "Cat3_Inapplicable",
            "name": f"Inapplicable Memory Sequence {i} (Distinct Preconditions)",
            "tasks": [
                {
                    "task_id": f"cat3_s{i}_t1_learn",
                    "instruction": "Attempt delivery of pkg_hardware to Bob in Lab_Secure (blocked by missing badge).",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 90,
                        "doors": {
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        },
                        "packages": {
                            "pkg_hardware": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                        },
                        "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                    },
                },
                {
                    "task_id": f"cat3_s{i}_t2_eval",
                    "instruction": "Deliver pkg_docs to Alice in Office_A (Office_A does not require security badge).",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 80,
                        "doors": {
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        },
                        "packages": {
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
            ],
        })

    return scenarios
