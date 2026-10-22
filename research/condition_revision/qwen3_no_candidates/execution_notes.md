# Qwen3-14B-AWQ No-Candidates Diagnostic Execution Notes
- **Run Command**: `python3 research/condition_revision/qwen3_no_candidates/run_no_candidates_diagnosis.py`
- **Configuration**: `/models/Qwen3-14B-AWQ` via AutoAWQ (torch.float16, enable_thinking=False, temp=0.7, top_p=0.8, top_k=20, max_new_tokens=256, peak VRAM 10.861 GiB).
- **Prompt Modification**: `prompt_mode="no_candidates"` (omitted candidate action list and title; guideline 3 set to "Choose the single most effective valid action.").
- **Initial State Consistency**: All 6 tasks (N1–N6 vs C1–C6) verified 100% initial task description, observation, and score match (`True`).
- **Diagnostic Outcomes**: N1: 60.0 (30 steps); N2: 55.0 (30 steps); N3: 60.0 (30 steps); N4: 60.0 (30 steps); N5: 3.0 (30 steps); N6: -100.0 (1 step, env_done).
- **Decision Tag**: `LOCAL_BASELINE_QUALIFICATION_FAILED` (0/6 success, threshold of >=4/6 with melt/boil success not met; further local tuning paused).
- **Resource Accounting**: 6 episodes, 151 model calls, 112,216 tokens, duration 3466.1s. P1 consumed: 153/160 episodes (7 remaining).
