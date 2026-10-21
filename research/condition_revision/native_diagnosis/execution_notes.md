# Native Action Pass-Through Diagnosis Execution Notes
- **Run Command**: `python3 research/condition_revision/native_diagnosis/run_native_diagnosis.py`
- **Configuration**: `adapter_mode="native"`, `envStepLimit=30`, `max_steps=30`, model=`meta-llama/Llama-3-70b-chat-hf`, `temperature=0.0`.
- **Native Rules**: Raw action string stripped of leading/trailing whitespace only; no candidate filtering, synonym conversion, or look around fallback.
- **Initial State Consistency**: R11 vs R12 identical (`True`), R13 vs R14 identical (`True`).
- **Completion Status**: 4/4 episodes completed (R11: env_done/score -100.0/23 steps; R12: step_limit_30/score 55.0/30 steps; R13: env_done/score -100.0/5 steps; R14: step_limit_30/score 10.0/30 steps).
- **Resource Accounting**: 4 episodes, 88 model calls, 77,223 total tokens consumed, duration 435.2s.
