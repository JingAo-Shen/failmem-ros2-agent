"""
Generates the deterministic execution manifest for 24 episodes:
4 variations x 3 conditions x 2 blocks = 24 episodes.
Pseudorandom shuffle with seed 3407 per block.
"""
import os
import sys
import json
import random

def generate_manifest():
    frozen_path = "/code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/frozen_experiences.json"
    with open(frozen_path, "r", encoding="utf-8") as f:
        frozen = json.load(f)

    sha_b = frozen["experience_b"]["sha256"]
    sha_c = frozen["experience_c"]["sha256"]

    items1 = [{"variation": v, "condition": c} for v in [0, 1, 2, 3] for c in ["A", "B", "C"]]
    items2 = [{"variation": v, "condition": c} for v in [0, 1, 2, 3] for c in ["A", "B", "C"]]

    rng = random.Random(3407)
    rng.shuffle(items1)
    rng.shuffle(items2)

    cond_descs = {
        "A": "No-Memory baseline (extra_context='')",
        "B": "Failure-Only experience (D6 steps 1-3)",
        "C": "Success-With-Failure experience (D6 steps 1-17)"
    }

    cond_shas = {
        "A": None,
        "B": sha_b,
        "C": sha_c
    }

    manifest_runs = []
    
    # Block 1: 1 to 12
    for idx, item in enumerate(items1, 1):
        v = item["variation"]
        c = item["condition"]
        ep_id = f"E{idx:02d}"
        manifest_runs.append({
            "episode_id": ep_id,
            "block": 1,
            "run_index_in_block": idx,
            "task_name": "boil",
            "variation": v,
            "condition": c,
            "condition_description": cond_descs[c],
            "experience_sha256": cond_shas[c],
            "step_limit": 30
        })

    # Block 2: 13 to 24
    for idx, item in enumerate(items2, 1):
        global_idx = idx + 12
        v = item["variation"]
        c = item["condition"]
        ep_id = f"E{global_idx:02d}"
        manifest_runs.append({
            "episode_id": ep_id,
            "block": 2,
            "run_index_in_block": idx,
            "task_name": "boil",
            "variation": v,
            "condition": c,
            "condition_description": cond_descs[c],
            "experience_sha256": cond_shas[c],
            "step_limit": 30
        })

    manifest = {
        "phase": "P1b_NATURAL_EXPERIENCE_SCREEN",
        "seed": 3407,
        "total_episodes": len(manifest_runs),
        "task_name": "boil",
        "variations": [0, 1, 2, 3],
        "conditions": ["A", "B", "C"],
        "blocks": [1, 2],
        "runs": manifest_runs
    }

    out_path = "/code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/manifest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Manifest written successfully to {out_path} ({len(manifest_runs)} runs).")

if __name__ == "__main__":
    generate_manifest()
