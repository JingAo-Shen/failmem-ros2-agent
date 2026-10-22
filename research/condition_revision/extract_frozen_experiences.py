"""
Script to extract and freeze Experience B and Experience C from deepseek_precheck/D6_boil_var2.json.
Uses deepseek-flash via official OpenAI-compatible API.
"""
import os
import sys
import json
import hashlib

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from remote_llm_client import RemoteLLMClient

os.makedirs("/code/failmem-ros2-agent/research/condition_revision/natural_experience_screen", exist_ok=True)

d6_path = "/code/failmem-ros2-agent/research/condition_revision/deepseek_precheck/D6_boil_var2.json"
with open(d6_path, "r", encoding="utf-8") as f:
    d6_data = json.load(f)

steps = d6_data["steps"]

def format_records(step_list):
    lines = []
    for s in step_list:
        lines.append(f"Step {s['step']}:")
        lines.append(f"Action: {s['executed_action']}")
        lines.append(f"Observation: {s['observation']}")
    return "\n".join(lines)

b_steps = steps[:3]   # Steps 1 to 3
c_steps = steps[:17]  # Steps 1 to 17

b_record = format_records(b_steps)
c_record = format_records(c_steps)

fixed_prompt = (
    "Use only the supplied interaction record. Produce one reusable experience for a future ScienceWorld agent. "
    "Do not add facts or successful actions absent from the record. Return a JSON object with experience_text, "
    "containing at most 120 English words, and evidence_steps, an array of supporting step numbers. "
    "If no grounded reusable experience can be extracted, set experience_text to null."
)

client = RemoteLLMClient(
    allow_live_network=True,
    initial_cost_usd=0.126752,
    initial_calls=57,
    max_budget_usd=10.00,
    max_attempts=1557
)

print("Starting extraction for Experience B...")
user_prompt_b = f"{fixed_prompt}\n\nInteraction Record:\n{b_record}"
parsed_b, stats_b = client.generate_json(user_prompt_b, system_prompt="You are a helpful assistant. Output ONLY a valid JSON object.")

print("Experience B parsed:", json.dumps(parsed_b, indent=2))

print("\nStarting extraction for Experience C...")
user_prompt_c = f"{fixed_prompt}\n\nInteraction Record:\n{c_record}"
parsed_c, stats_c = client.generate_json(user_prompt_c, system_prompt="You are a helpful assistant. Output ONLY a valid JSON object.")

print("Experience C parsed:", json.dumps(parsed_c, indent=2))

exp_b_text = parsed_b.get("experience_text")
exp_c_text = parsed_c.get("experience_text")

if not exp_b_text or not exp_c_text:
    print("FATAL: Experience text extracted as null or empty!")
    sys.exit(1)

words_b = len(exp_b_text.split())
words_c = len(exp_c_text.split())

sha_b = hashlib.sha256(exp_b_text.encode("utf-8")).hexdigest()
sha_c = hashlib.sha256(exp_c_text.encode("utf-8")).hexdigest()

print(f"\nExp B word count: {words_b}, sha256: {sha_b}")
print(f"Exp C word count: {words_c}, sha256: {sha_c}")

frozen_data = {
    "fixed_prompt_instruction": fixed_prompt,
    "source_file": "research/condition_revision/deepseek_precheck/D6_boil_var2.json",
    "experience_b": {
        "description": "Failure-Only experience from D6 steps 1-3",
        "steps_used": [1, 2, 3],
        "interaction_record": b_record,
        "raw_response": stats_b.get("raw_text"),
        "parsed_response": parsed_b,
        "experience_text": exp_b_text,
        "evidence_steps": parsed_b.get("evidence_steps", []),
        "word_count": words_b,
        "sha256": sha_b,
        "stats": stats_b
    },
    "experience_c": {
        "description": "Success-With-Failure experience from D6 steps 1-17",
        "steps_used": list(range(1, 18)),
        "interaction_record": c_record,
        "raw_response": stats_c.get("raw_text"),
        "parsed_response": parsed_c,
        "experience_text": exp_c_text,
        "evidence_steps": parsed_c.get("evidence_steps", []),
        "word_count": words_c,
        "sha256": sha_c,
        "stats": stats_c
    },
    "client_budget_ledger": client.get_budget_ledger()
}

out_p1 = "/code/failmem-ros2-agent/research/condition_revision/natural_experience_screen/frozen_experiences.json"
out_p2 = "/code/failmem-ros2-agent/research/condition_revision/frozen_experiences.json"
with open(out_p1, "w", encoding="utf-8") as f:
    json.dump(frozen_data, f, indent=2, ensure_ascii=False)
with open(out_p2, "w", encoding="utf-8") as f:
    json.dump(frozen_data, f, indent=2, ensure_ascii=False)

print("Saved frozen_experiences.json to both locations successfully.")
