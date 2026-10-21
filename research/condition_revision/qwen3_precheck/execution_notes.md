# Qwen3-14B-AWQ Candidate Planner Pre-Check Execution Notes
- **Run Command**: `python3 research/condition_revision/qwen3_precheck/run_qwen3_precheck.py`
- **Model Loaded**: `/models/Qwen3-14B-AWQ` via AutoAWQ (torch.float16, enable_thinking=False, temp=0.7, top_p=0.8, top_k=20, max_new_tokens=256, peak VRAM 10.861 GiB).
- **JSON Output Check**: Passed on first attempt (`{"ok": true}`, 1 call, latency 3.07s).
- **Environment Settings**: 6 tasks under adapter_mode="native", history_mode="all_steps", seed=3407 fixed before each task, 30-step horizon, extra_context="".
- **Task Outcomes**: C1 (cond var 0): 100.0 (15 steps); C2 (cond var 460): 100.0 (7 steps); C3 (cond var 160): 60.0 (6 steps, env_done); C4 (cond var 230): 60.0 (30 steps, step_limit_30); C5 (melt var 4): -100.0 (9 steps, env_done); C6 (boil var 2): -100.0 (4 steps, env_done).
- **Failure Breakdown**: 2 successes (C1, C2), 4 task failures (C3, C4, C5, C6); 0 loading failures, 0 parsing failures, 0 environment exceptions.
- **Resource Accounting**: 6 episodes, 72 model calls (1 check + 71 task calls), 60,348 tokens, duration 1734.5s. P1 remaining budget: 13 episodes.
