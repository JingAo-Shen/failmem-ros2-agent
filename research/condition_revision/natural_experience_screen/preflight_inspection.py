"""
Pre-flight read-only inspection of ScienceWorld boil variations 0, 1, 2, 3.
Verifies broken/normal state of sink and stove in the kitchen.
"""
import os
import sys
import json
from scienceworld import ScienceWorldEnv

def inspect_variations():
    env = ScienceWorldEnv("", "", envStepLimit=30)
    results = {}
    
    expected_states = {
        0: {"sink": "normal", "stove": "normal"},
        1: {"sink": "normal", "stove": "broken"},
        2: {"sink": "broken", "stove": "normal"},
        3: {"sink": "broken", "stove": "broken"}
    }
    
    for var in [0, 1, 2, 3]:
        env.load("boil", var, simplificationStr="teleportAction,openDoors")
        obs, info = env.reset()
        start_room = obs.strip().splitlines()[0]
        
        # Teleport to kitchen
        obs_k, _, _, _ = env.step("teleport to kitchen")
        
        # Probe sink
        obs_sink, _, _, _ = env.step("activate sink")
        if "is now activated" in obs_sink:
            sink_status = "normal"
            env.step("deactivate sink")
        elif "appears broken" in obs_sink:
            sink_status = "broken"
        else:
            sink_status = f"unknown: {obs_sink.strip()}"
            
        # Probe stove
        obs_stove, _, _, _ = env.step("activate stove")
        if "is now activated" in obs_stove:
            stove_status = "normal"
            env.step("deactivate stove")
        elif "appears broken" in obs_stove:
            stove_status = "broken"
        else:
            stove_status = f"unknown: {obs_stove.strip()}"
            
        matches_expected = (
            sink_status == expected_states[var]["sink"] and
            stove_status == expected_states[var]["stove"]
        )
        
        results[f"variation_{var}"] = {
            "variation": var,
            "starting_room_observation": start_room,
            "sink_probe_action": "activate sink",
            "sink_observation": obs_sink.strip(),
            "sink_status": sink_status,
            "stove_probe_action": "activate stove",
            "stove_observation": obs_stove.strip(),
            "stove_status": stove_status,
            "expected_sink": expected_states[var]["sink"],
            "expected_stove": expected_states[var]["stove"],
            "matches_expected": matches_expected
        }
        print(f"Variation {var}: sink={sink_status}, stove={stove_status}, matches={matches_expected}")
        assert matches_expected, f"Variation {var} state does not match expected!"
        
    env.close()
    
    out_path = "/code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/variation_status_preflight.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Pre-flight inspection successfully saved to {out_path}")

if __name__ == "__main__":
    inspect_variations()
