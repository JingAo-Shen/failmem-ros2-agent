"""
Task Manifest for Counterexample-Driven Condition Revision Research.
Strictly partitioned into:
1. COLLECTION_TASKS: Tasks for natural experience acquisition.
2. P1_DEV_DIAGNOSTIC_PAIRS: Development pairs for P1 phenomenon confirmation & P2 method prototyping.
   - Contains explicit flags: is_training_support (True for regression check, False for unseen transfer).
3. P3_HELD_OUT_CONFIRMATION_PAIRS: Strictly reserved for P3 final confirmation (disjoint variations and objects).
"""

from typing import Dict, List, Any

# 1. Experience Collection Tasks for Natural Experience Acquisition (4 tasks)
COLLECTION_TASKS = [
    {"id": "col_01", "task_name": "test-conductivity", "variation": 0, "description": "test conductivity of aluminum foil", "target": "aluminum foil"},
    {"id": "col_02", "task_name": "test-conductivity", "variation": 300, "description": "test conductivity of metal fork", "target": "metal fork"},
    {"id": "col_03", "task_name": "melt", "variation": 4, "description": "melt ice", "target": "ice"},
    {"id": "col_04", "task_name": "boil", "variation": 2, "description": "boil water in kitchen", "target": "water"}
]

# 2. P1/P2 Development Diagnostic Pairs (4 pairs)
# Used to observe natural over-generalization, verify causal misuse, and test local revision
P1_DEV_DIAGNOSTIC_PAIRS = [
    {
        "pair_id": "dev_pair_01_conductivity_foil_vs_apricot",
        "category": "conductivity_metal_vs_fruit",
        "task_a": {
            "id": "dev_01_a",
            "task_name": "test-conductivity",
            "variation": 0,
            "target": "aluminum foil",
            "is_training_support": True,  # Same instance as col_01 (used strictly for in-training regression replay)
            "expected_rule_applicable": True
        },
        "task_b": {
            "id": "dev_01_b",
            "task_name": "test-conductivity",
            "variation": 80,
            "target": "apricot",
            "is_training_support": False,
            "expected_rule_applicable": False,
            "distinguishing_feature": "material_non_metallic"
        }
    },
    {
        "pair_id": "dev_pair_02_conductivity_fork_vs_glass",
        "category": "conductivity_metal_vs_glass",
        "task_a": {
            "id": "dev_02_a",
            "task_name": "test-conductivity",
            "variation": 300,
            "target": "metal fork",
            "is_training_support": True,  # Same instance as col_02 (in-training regression check)
            "expected_rule_applicable": True
        },
        "task_b": {
            "id": "dev_02_b",
            "task_name": "test-conductivity",
            "variation": 230,
            "target": "glass jar",
            "is_training_support": False,
            "expected_rule_applicable": False,
            "distinguishing_feature": "material_glass"
        }
    },
    {
        "pair_id": "dev_pair_03_melt_ice_vs_water",
        "category": "phase_ice_vs_already_liquid",
        "task_a": {
            "id": "dev_03_a",
            "task_name": "melt",
            "variation": 4,
            "target": "ice",
            "is_training_support": True,
            "expected_rule_applicable": True
        },
        "task_b": {
            "id": "dev_03_b",
            "task_name": "melt",
            "variation": 0,
            "target": "water",
            "is_training_support": False,
            "expected_rule_applicable": False,
            "distinguishing_feature": "current_state_already_liquid"
        }
    },
    {
        "pair_id": "dev_pair_04_boil_water_vs_chocolate",
        "category": "thermal_state_liquid_vs_solid",
        "task_a": {
            "id": "dev_04_a",
            "task_name": "boil",
            "variation": 2,
            "target": "water",
            "is_training_support": True,
            "expected_rule_applicable": True
        },
        "task_b": {
            "id": "dev_04_b",
            "task_name": "boil",
            "variation": 10,
            "target": "chocolate",
            "is_training_support": False,
            "expected_rule_applicable": False,
            "distinguishing_feature": "substance_solid_chocolate"
        }
    }
]

# 3. P3 Strictly Held-Out Confirmation Diagnostic Pairs (6 pairs)
# Disjoint variations and unseen objects reserved for final confirmation only
P3_HELD_OUT_CONFIRMATION_PAIRS = [
    {
        "pair_id": "conf_pair_01_conductivity_pot_vs_book",
        "category": "conductivity_metal_vs_paper",
        "task_a": {"id": "conf_01_a", "task_name": "test-conductivity", "variation": 380, "target": "metal pot", "is_training_support": False, "expected_rule_applicable": True},
        "task_b": {"id": "conf_01_b", "task_name": "test-conductivity", "variation": 150, "target": "book", "is_training_support": False, "expected_rule_applicable": False}
    },
    {
        "pair_id": "conf_pair_02_circuit_red_vs_green",
        "category": "circuit_red_vs_green_bulb",
        "task_a": {"id": "conf_02_a", "task_name": "power-component", "variation": 0, "target": "red light bulb", "is_training_support": False, "expected_rule_applicable": True},
        "task_b": {"id": "conf_02_b", "task_name": "power-component", "variation": 4, "target": "green light bulb", "is_training_support": False, "expected_rule_applicable": False}
    },
    {
        "pair_id": "conf_pair_03_freeze_liquid_vs_ice",
        "category": "freezing_liquid_vs_already_frozen",
        "task_a": {"id": "conf_03_a", "task_name": "freeze", "variation": 0, "target": "water", "is_training_support": False, "expected_rule_applicable": True},
        "task_b": {"id": "conf_03_b", "task_name": "freeze", "variation": 4, "target": "ice", "is_training_support": False, "expected_rule_applicable": False}
    },
    {
        "pair_id": "conf_pair_04_matter_juice_vs_marshmallow",
        "category": "matter_juice_vs_marshmallow",
        "task_a": {"id": "conf_04_a", "task_name": "change-the-state-of-matter-of", "variation": 6, "target": "orange juice", "is_training_support": False, "expected_rule_applicable": True},
        "task_b": {"id": "conf_04_b", "task_name": "change-the-state-of-matter-of", "variation": 12, "target": "marshmallow", "is_training_support": False, "expected_rule_applicable": False}
    },
    {
        "pair_id": "conf_pair_05_living_vs_non_living",
        "category": "living_vs_non_living",
        "task_a": {"id": "conf_05_a", "task_name": "find-living-thing", "variation": 1, "target": "living thing", "is_training_support": False, "expected_rule_applicable": True},
        "task_b": {"id": "conf_05_b", "task_name": "find-non-living-thing", "variation": 1, "target": "non-living thing", "is_training_support": False, "expected_rule_applicable": False}
    },
    {
        "pair_id": "conf_pair_06_chemistry_salt_vs_soap",
        "category": "chemistry_salt_vs_soap",
        "task_a": {"id": "conf_06_a", "task_name": "chemistry-mix", "variation": 0, "target": "salt water", "is_training_support": False, "expected_rule_applicable": True},
        "task_b": {"id": "conf_06_b", "task_name": "chemistry-mix", "variation": 1, "target": "soapy water", "is_training_support": False, "expected_rule_applicable": False}
    }
]
