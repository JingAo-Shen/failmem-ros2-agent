import random
import json
import hashlib
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "manifest.json")

random.seed(3409)

variations = [0, 2]
conditions = ["A", "G", "C", "GC"]

# Block 5 combinations
b5_combos = [(v, c) for v in variations for c in conditions]
random.shuffle(b5_combos)

# Block 6 combinations
b6_combos = [(v, c) for v in variations for c in conditions]
random.shuffle(b6_combos)

desc_map = {
    "A": "No-Memory baseline (extra_context='', generic_semantics='')",
    "G": "Generic action semantics only (extra_context='')",
    "C": "Success-With-Failure experience C only (generic_semantics='')",
    "GC": "Generic action semantics + Success-With-Failure experience C"
}

runs = []
run_idx = 1
for b, combos in [(5, b5_combos), (6, b6_combos)]:
    for i, (v, c) in enumerate(combos, 1):
        ep_id = f"M{run_idx:02d}"
        run_idx += 1
        runs.append({
            "episode_id": ep_id,
            "block": b,
            "run_index_in_block": i,
            "task_name": "boil",
            "variation": v,
            "is_source_instance_replay": (v == 2),
            "condition": c,
            "condition_description": desc_map[c],
            "generic_semantics_sha256": "ab7aadf7f7f0aa52fa23c789c1f479fdb93e45579658da74b53b760473d124f7" if "G" in c else None,
            "experience_sha256": "3ecb0e984256d3f81c995bd57141dced84c08fe76355d48990b11cadce3edf15" if "C" in c else None,
            "step_limit": 30
        })

manifest = {
    "phase": "P1d_GENERIC_INTERFACE_CONTROL",
    "seed": 3409,
    "seed_usage_note": "Seed 3409 used strictly for local ordering pseudo-randomization across blocks; does not claim remote API determinism.",
    "total_episodes": 16,
    "task_name": "boil",
    "variations": [0, 2],
    "conditions": ["A", "G", "C", "GC"],
    "blocks": [5, 6],
    "runs": runs
}

with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

with open(MANIFEST_PATH, "rb") as f:
    m_sha = hashlib.sha256(f.read()).hexdigest()

print(f"Manifest written to {MANIFEST_PATH}")
print(f"Manifest SHA256: {m_sha}")
for r in runs:
    print(f"  {r['episode_id']}: Block {r['block']}, Var {r['variation']}, Cond {r['condition']}")

