"""
Task Manifest for Counterexample-Driven Condition Revision Feasibility Study.
Defines:
1. 12 Experience Collection tasks (exploratory tasks to acquire natural experiences).
2. 10 Diagnostic Task Pairs (Task A: valid condition holds; Task B: superficially similar, critical condition differs).
"""

from typing import Dict, List, Any

# 12 Experience Collection Tasks for Natural Experience Acquisition
COLLECTION_TASKS = [
    {"id": "col_01", "task_name": "boil", "variation": 0, "description": "boil water in kitchen"},
    {"id": "col_02", "task_name": "boil", "variation": 1, "description": "boil water in kitchen (var 1)"},
    {"id": "col_03", "task_name": "melt", "variation": 4, "description": "melt ice"},
    {"id": "col_04", "task_name": "melt", "variation": 5, "description": "melt ice (var 5)"},
    {"id": "col_05", "task_name": "freeze", "variation": 0, "description": "freeze water"},
    {"id": "col_06", "task_name": "freeze", "variation": 1, "description": "freeze water (var 1)"},
    {"id": "col_07", "task_name": "test-conductivity", "variation": 0, "description": "test conductivity of aluminum foil"},
    {"id": "col_08", "task_name": "test-conductivity", "variation": 300, "description": "test conductivity of metal fork"},
    {"id": "col_09", "task_name": "power-component", "variation": 0, "description": "power red light bulb"},
    {"id": "col_10", "task_name": "power-component", "variation": 1, "description": "power red light bulb (var 1)"},
    {"id": "col_11", "task_name": "find-living-thing", "variation": 0, "description": "find living thing"},
    {"id": "col_12", "task_name": "chemistry-mix", "variation": 0, "description": "create salt water"},
]

# 10 Diagnostic Task Pairs (20 tasks total)
# Each pair has Task A (Original Valid Context) and Task B (Counterexample Context)
DIAGNOSTIC_TASK_PAIRS = [
    {
        "pair_id": "pair_01",
        "category": "thermal_state_liquid_vs_solid",
        "task_a": {"id": "eval_01_a", "task_name": "boil", "variation": 2, "target": "water (liquid)", "expected_rule_applicable": True},
        "task_b": {"id": "eval_01_b", "task_name": "boil", "variation": 10, "target": "chocolate (solid/sugar)", "expected_rule_applicable": False, "distinguishing_feature": "substance_phase_or_burnable"}
    },
    {
        "pair_id": "pair_02",
        "category": "phase_ice_vs_already_liquid",
        "task_a": {"id": "eval_02_a", "task_name": "melt", "variation": 4, "target": "ice (solid)", "expected_rule_applicable": True},
        "task_b": {"id": "eval_02_b", "task_name": "melt", "variation": 0, "target": "water (already liquid)", "expected_rule_applicable": False, "distinguishing_feature": "current_state_already_liquid"}
    },
    {
        "pair_id": "pair_03",
        "category": "conductivity_metal_vs_fruit",
        "task_a": {"id": "eval_03_a", "task_name": "test-conductivity", "variation": 0, "target": "aluminum foil (metal conductor)", "expected_rule_applicable": True},
        "task_b": {"id": "eval_03_b", "task_name": "test-conductivity", "variation": 80, "target": "apricot (organic fruit)", "expected_rule_applicable": False, "distinguishing_feature": "material_non_metallic"}
    },
    {
        "pair_id": "pair_04",
        "category": "conductivity_metal_vs_glass",
        "task_a": {"id": "eval_04_a", "task_name": "test-conductivity", "variation": 300, "target": "metal fork (metal conductor)", "expected_rule_applicable": True},
        "task_b": {"id": "eval_04_b", "task_name": "test-conductivity", "variation": 230, "target": "glass jar (glass insulator)", "expected_rule_applicable": False, "distinguishing_feature": "material_glass"}
    },
    {
        "pair_id": "pair_05",
        "category": "conductivity_metal_vs_paper",
        "task_a": {"id": "eval_05_a", "task_name": "test-conductivity", "variation": 380, "target": "metal pot (metal conductor)", "expected_rule_applicable": True},
        "task_b": {"id": "eval_05_b", "task_name": "test-conductivity", "variation": 150, "target": "book (paper insulator)", "expected_rule_applicable": False, "distinguishing_feature": "material_cellulose_paper"}
    },
    {
        "pair_id": "pair_06",
        "category": "circuit_red_vs_green_bulb",
        "task_a": {"id": "eval_06_a", "task_name": "power-component", "variation": 0, "target": "red light bulb", "expected_rule_applicable": True},
        "task_b": {"id": "eval_06_b", "task_name": "power-component", "variation": 4, "target": "green light bulb", "expected_rule_applicable": False, "distinguishing_feature": "target_component_color"}
    },
    {
        "pair_id": "pair_07",
        "category": "freezing_liquid_vs_already_frozen",
        "task_a": {"id": "eval_07_a", "task_name": "freeze", "variation": 0, "target": "water (liquid)", "expected_rule_applicable": True},
        "task_b": {"id": "eval_07_b", "task_name": "freeze", "variation": 4, "target": "ice (already frozen)", "expected_rule_applicable": False, "distinguishing_feature": "current_state_already_frozen"}
    },
    {
        "pair_id": "pair_08",
        "category": "matter_juice_vs_marshmallow",
        "task_a": {"id": "eval_08_a", "task_name": "change-the-state-of-matter-of", "variation": 6, "target": "orange juice", "expected_rule_applicable": True},
        "task_b": {"id": "eval_08_b", "task_name": "change-the-state-of-matter-of", "variation": 12, "target": "marshmallow", "expected_rule_applicable": False, "distinguishing_feature": "high_sugar_combustion_risk"}
    },
    {
        "pair_id": "pair_09",
        "category": "living_vs_non_living",
        "task_a": {"id": "eval_09_a", "task_name": "find-living-thing", "variation": 1, "target": "living thing", "expected_rule_applicable": True},
        "task_b": {"id": "eval_09_b", "task_name": "find-non-living-thing", "variation": 1, "target": "non-living thing", "expected_rule_applicable": False, "distinguishing_feature": "vital_status_non_living"}
    },
    {
        "pair_id": "pair_10",
        "category": "chemistry_salt_vs_soap",
        "task_a": {"id": "eval_10_a", "task_name": "chemistry-mix", "variation": 0, "target": "salt water", "expected_rule_applicable": True},
        "task_b": {"id": "eval_10_b", "task_name": "chemistry-mix", "variation": 1, "target": "soapy water", "expected_rule_applicable": False, "distinguishing_feature": "reagent_soap_vs_salt"}
    }
]
