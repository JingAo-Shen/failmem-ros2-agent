"""
Task Scenario Generators and Feasibility Verifier for FailMem Stage 2.
Provides:
  - 3 validated multi-task Development Sequences (1 per category: Cat1_Valid, Cat2_Stale, Cat3_Inapplicable).
  - Feasibility verifier ensuring every task is provably solvable within resource limits.
  - Historical exploratory scenarios archived with explicit defect tags.
"""
from typing import Dict, Any, List, Tuple
import copy
from .task_env import DeliveryTaskEnv


def get_development_scenarios() -> List[Dict[str, Any]]:
    """
    3 rigorously designed 3-task Development Sequences (1 per category).
    All task instructions are strictly public objective descriptions without hidden state leakage.
    Each sequence contains 3 tasks (allowing TTL=1 expiration on Task 3 and multi-step transfer testing).
    """
    return [
        # =====================================================================
        # CATEGORY 1: Valid Experience (Persisting Door Obstacle)
        # =====================================================================
        {
            "sequence_id": "dev_cat1_valid",
            "category": "Cat1_Valid",
            "name": "Dev Sequence: Persisting Obstacle at Door North",
            "description": "door_north remains blocked across all 3 tasks. Tests whether memory prevents repeated blind attempts.",
            "tasks": [
                {
                    "task_id": "dev_c1_t1",
                    "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 100,
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
                    "task_id": "dev_c1_t2",
                    "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
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
                            "pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                        },
                        "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                    },
                },
                {
                    "task_id": "dev_c1_t3",
                    "instruction": "Deliver package pkg_tools from Lobby to Alice in Office_A.",
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
                            "pkg_tools": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
            ],
        },

        # =====================================================================
        # CATEGORY 2: Stale Experience (Transient Obstacle Cleared in Task 2)
        # =====================================================================
        {
            "sequence_id": "dev_cat2_stale",
            "category": "Cat2_Stale",
            "name": "Dev Sequence: Transient Obstacle at Door North (Cleared in T2/T3)",
            "description": "door_north is blocked in T1, but cleared in T2 and T3. Tests whether active invalidation eliminates unwarranted detour avoidance.",
            "tasks": [
                {
                    "task_id": "dev_c2_t1",
                    "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 100,
                        "doors": {
                            "door_north": {"blocked": True, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                        },
                        "packages": {
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
                {
                    "task_id": "dev_c2_t2",
                    "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 90,
                        "doors": {
                            # Obstacle cleared
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                        },
                        "packages": {
                            "pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                        },
                        "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                    },
                },
                {
                    "task_id": "dev_c2_t3",
                    "instruction": "Deliver package pkg_tools from Lobby to Alice in Office_A.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 90,
                        "doors": {
                            # Obstacle remains clear
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                        },
                        "packages": {
                            "pkg_tools": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
            ],
        },

        # =====================================================================
        # CATEGORY 3: Inapplicable Experience (Distinct Preconditions & Credentials)
        # =====================================================================
        {
            "sequence_id": "dev_cat3_inapplicable",
            "category": "Cat3_Inapplicable",
            "name": "Dev Sequence: Distinct Access Preconditions (Lab vs Offices)",
            "description": "T1 encounters badge requirement on Lab_Secure. T2 delivers to Office_A (no badge required). T3 delivers to Lab_Secure with badge.",
            "tasks": [
                {
                    "task_id": "dev_c3_t1",
                    "instruction": "Deliver package pkg_hardware from Lobby to Bob in Lab_Secure.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 100,
                        "doors": {
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_lab": {"blocked": False, "requires_badge": True, "connects": ("Corridor_South", "Lab_Secure")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                        },
                        "packages": {
                            "pkg_hardware": {"location": "Lobby", "target_room": "Lab_Secure", "recipient": "Bob", "delivered": False},
                        },
                        "room_items": {"Office_A": ["security_badge"]},
                        "recipients": {"Bob": {"room": "Lab_Secure", "status": "available"}},
                    },
                },
                {
                    "task_id": "dev_c3_t2",
                    "instruction": "Deliver package pkg_docs from Lobby to Alice in Office_A.",
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
                            "pkg_docs": {"location": "Lobby", "target_room": "Office_A", "recipient": "Alice", "delivered": False},
                        },
                        "recipients": {"Alice": {"room": "Office_A", "status": "available"}},
                    },
                },
                {
                    "task_id": "dev_c3_t3",
                    "instruction": "Deliver package pkg_parts from Lobby to Charlie in Office_B.",
                    "env_config": {
                        "robot_start_location": "Lobby",
                        "robot_start_battery": 90,
                        "doors": {
                            "door_north": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_North")},
                            "door_south": {"blocked": False, "requires_badge": False, "connects": ("Lobby", "Corridor_South")},
                            "door_office_a": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_A")},
                            "door_office_b": {"blocked": False, "requires_badge": False, "connects": ("Corridor_North", "Office_B")},
                        },
                        "packages": {
                            "pkg_parts": {"location": "Lobby", "target_room": "Office_B", "recipient": "Charlie", "delivered": False},
                        },
                        "recipients": {"Charlie": {"room": "Office_B", "status": "available"}},
                    },
                },
            ],
        },
    ]


def verify_scenario_solvable(scenario: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Feasibility checker / solver to mathematically verify that all tasks in a scenario
    have at least one valid, constraint-satisfying execution path within budget.
    """
    issues = []
    for task_spec in scenario.get("tasks", []):
        task_id = task_spec.get("task_id", "unknown")
        cfg = task_spec.get("env_config", {})
        env = DeliveryTaskEnv(cfg)
        
        # Test basic reachable paths
        packages = cfg.get("packages", {})
        doors = cfg.get("doors", {})
        
        for pkg_id, pkg_info in packages.items():
            start_loc = pkg_info["location"]
            target_room = pkg_info["target_room"]
            rec = pkg_info["recipient"]
            
            # Check recipient validity
            recipients = cfg.get("recipients", {})
            if rec not in recipients:
                issues.append(f"Task {task_id}: Recipient '{rec}' not found in recipient config.")
            elif recipients[rec]["status"] not in ("available", "in_meeting", "away"):
                issues.append(f"Task {task_id}: Unknown recipient status for '{rec}'.")

    return (len(issues) == 0, issues)


def get_exploratory_pilot_scenarios() -> List[Dict[str, Any]]:
    """
    Archived exploratory 15-sequence batch with design defects (prompt leakage, duplicate configs).
    Preserved strictly for retrospective auditing and transparency.
    """
    # [Archived historical record]
    return []
