# History Window Comparison Execution Notes
- **Run Command**: `python3 research/condition_revision/history_window_comparison/run_history_comparison.py`
- **Model Verification**: Verified live object `Qwen2ForCausalLM` from `/models/Qwen2.5-Coder-7B-Instruct` (torch.bfloat16, greedy/do_sample=False).
- **Correction Note**: Prior batch 8 notes text mistakenly wrote Llama-3-70B; actual loaded model in all code, JSONs, and batches is `/models/Qwen2.5-Coder-7B-Instruct`.
- **Initial State Consistency**: All 4 runs (R15-R18) verified 100% identical initial task description, observation, candidate list, and score (`True`).
- **Steps 1-6 Consistency**: R15 vs R17 and R16 vs R18 have 100% identical prompts, proposed actions, executed actions, and scores across steps 1-6.
- **Divergence Points**: R15/R17 diverged at Step 7 (R15: focus on paper clip -> env_done at step 23, -100.0; R17: disconnect red light bulb -> step 30, 55.0); R16/R18 diverged at Step 8 (both reached step 30, 55.0).
- **Completion & Resources**: 4/4 episodes, 113/240 calls used, 116,618 tokens, duration 600.3s.
