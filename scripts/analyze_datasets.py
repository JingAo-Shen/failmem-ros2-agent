#!/usr/bin/env python3
"""
Dataset Analysis Script:
Compares data/task-specs.jsonl and data/test_episodes.jsonl
Computes line counts, unique coordinates, scenario signatures,
fault type distributions, start==goal counts, and duplication patterns.
"""

import json
from collections import Counter
import os

def analyze_jsonl(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    
    total = len(records)
    coords = [(tuple(r.get("initial_robot_pos", [])), tuple(r.get("goal_coord", []))) for r in records]
    unique_coords = sorted(list(set(coords)))
    coord_counts = Counter(coords)
    
    fault_types = Counter(r.get("fault_type") for r in records)
    same_start_goal = sum(1 for (s, g) in coords if s == g)
    same_start_goal_ids = [r["id"] for r in records if r.get("initial_robot_pos") == r.get("goal_coord")]
    
    signatures = [(r.get("layout_id"), r.get("fault_type"), tuple(r.get("goal_coord", []))) for r in records]
    unique_signatures = sorted(list(set(signatures)))
    signature_counts = Counter(signatures)
    
    return {
        "filepath": filepath,
        "total_lines": total,
        "unique_coordinate_pairs": len(unique_coords),
        "unique_scenario_signatures": len(unique_signatures),
        "same_start_goal_count": same_start_goal,
        "same_start_goal_ids": same_start_goal_ids,
        "fault_type_distribution": dict(fault_types),
        "coordinate_repetition": {str(k): v for k, v in coord_counts.items()},
        "signature_repetition": {str(k): v for k, v in signature_counts.items()}
    }

def main():
    specs_res = analyze_jsonl("data/task-specs.jsonl")
    tests_res = analyze_jsonl("data/test_episodes.jsonl")
    
    report = {
        "task_specs_summary": specs_res,
        "test_episodes_summary": tests_res,
        "comparison_notes": [
            "task-specs.jsonl has 12 items with 10 unique coordinate pairs (2 coordinates are duplicated with different layouts/faults).",
            "test_episodes.jsonl has 180 items with exactly 12 unique coordinate pairs, each repeated 15 times.",
            "test_episodes.jsonl is NOT a direct copy of task-specs.jsonl coordinates: task-specs contains coords like (4,6), (8,2), (2,8), (4,1), (8,7), (2,3) not present in test_episodes; test_episodes contains coords like (3,4), (9,0), (0,4), (3,8), (9,4), (3,0), (9,8) not in task-specs.",
            "Both datasets contain tasks where initial_robot_pos == goal_coord ([0.0, 0.0]): task-specs has 2 (16.7%), test_episodes has 15 (8.33%).",
            "In test_episodes.jsonl, 12 template tasks are systematically tiled 15 times across 6 layout labels."
        ]
    }
    
    os.makedirs("reports/evidence/r0", exist_ok=True)
    out_path = "reports/evidence/r0/dataset_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"Dataset analysis completed. Saved to {out_path}")
    print(f"task-specs: {specs_res['total_lines']} lines, {specs_res['unique_coordinate_pairs']} unique coords, {specs_res['same_start_goal_count']} same start-goal")
    print(f"test_episodes: {tests_res['total_lines']} lines, {tests_res['unique_coordinate_pairs']} unique coords, {tests_res['same_start_goal_count']} same start-goal")

if __name__ == "__main__":
    main()
