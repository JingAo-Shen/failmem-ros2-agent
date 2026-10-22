"""
Generates the deterministic execution manifest for Phase P1c:
boil variations 0, 2 x conditions A, B, C x blocks 3, 4 = 12 episodes.
Pseudorandom shuffle with seed 3408 per block.
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

    items3 = [{"variation": v, "condition": c} for v in [0, 2] for c in ["A", "B", "C"]]
    items4 = [{"variation": v, "condition": c} for v in [0, 2] for c in ["A", "B", "C"]]

    rng = random.Random(3408)
    rng.shuffle(items3)
    rng.shuffle(items4)

    cond_descs = {
        "A": "No-Memory baseline (extra_context='')",
        "B": "Failure-Only experience (D6 steps 1-3, sha=" + sha_b[:8] + ")",
        "C": "Success-With-Failure experience (D6 steps 1-17, sha=" + sha_c[:8] + ")"
    }

    cond_shas = {
        "A": None,
        "B": sha_b,
        "C": sha_c
    }

    manifest_runs = []

    # Block 3: R01 to R06
    for idx, item in enumerate(items3, 1):
        v = item["variation"]
        c = item["condition"]
        ep_id = f"R{idx:02d}"
        manifest_runs.append({
            "episode_id": ep_id,
            "block": 3,
            "run_index_in_block": idx,
            "task_name": "boil",
            "variation": v,
            "is_source_instance_replay": (v == 2),
            "condition": c,
            "condition_description": cond_descs[c],
            "experience_sha256": cond_shas[c],
            "step_limit": 30
        })

    # Block 4: R07 to R12
    for idx, item in enumerate(items4, 1):
        global_idx = idx + 6
        v = item["variation"]
        c = item["condition"]
        ep_id = f"R{global_idx:02d}"
        manifest_runs.append({
            "episode_id": ep_id,
            "block": 4,
            "run_index_in_block": idx,
            "task_name": "boil",
            "is_source_instance_replay": (v == 2),
            "condition": c,
            "condition_description": cond_descs[c],
            "experience_sha256": cond_shas[c],
            "step_limit": 30
        })

    manifest = {
        "phase": "P1c_MENU_PROTOCOL_RECHECK",
        "seed": 3408,
        "total_episodes": len(manifest_runs),
        "task_name": "boil",
        "variations": [0, 2],
        "conditions": ["A", "B", "C"],
        "blocks": [3, 4],
        "runs": manifest_runs
    }

    out_path = "/code/failmem-ros2-agent/research/condition_revision/menu_protocol_recheck/manifest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Manifest written successfully to {out_path} ({len(manifest_runs)} runs).")

if __name__ == "__main__":
    generate_manifest()
