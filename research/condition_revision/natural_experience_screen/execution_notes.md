# Natural Experience Transfer Screening (P1b) Execution Notes

- **Phase**: `P1b_NATURAL_EXPERIENCE_SCREEN`
- **Execution Timestamp**: 2026-10-22T12:30:00Z
- **Model**: `deepseek-flash` (Target: DeepSeek-V4.1-Flash-1017, system fingerprint: `e72d3c7f663d3e1383b00b3884cb4501`)
- **Generation Parameters**: `thinking={"type":"enabled"}`, `reasoning_effort="high"`, `response_format={"type":"json_object"}`, `max_tokens=8192`, `stream=false`, timeout 180s. No `temperature`, `top_p`, or `seed` sent to API.
- **ScienceWorld Protocol**: `adapter_mode="native"`, `prompt_mode="action_templates"` (dynamically queried from `env.get_action_templates()`), `history_mode="all_steps"` (150-character observation truncation), step limit 30.
- **Randomization Seed**: Local `seed=3407` used for pseudo-random shuffling of execution order within Block 1 and Block 2 (does not claim control over remote model randomness).

---

## 1. Environment & Variation Pre-Flight Inspection

Verified via read-only inspection prior to running model episodes ([`variation_status_preflight.json`](./variation_status_preflight.json)):
- **Variation 0**: sink = normal (`The sink is now activated.`), stove = normal (`The stove is now activated.`)
- **Variation 1**: sink = normal (`The sink is now activated.`), stove = broken (`The stove appears broken, and can't be activated or deactivated.`)
- **Variation 2** (Source trajectory instance): sink = broken (`The sink appears broken, and can't be activated or deactivated.`), stove = normal (`The stove is now activated.`)
- **Variation 3**: sink = broken (`The sink appears broken, and can't be activated or deactivated.`), stove = broken (`The stove appears broken, and can't be activated or deactivated.`)

All 4 variations 100% matched design specifications.

---

## 2. Frozen Experience Texts

Extracted strictly from `deepseek_precheck/D6_boil_var2.json` using the fixed prompt ([`frozen_experiences.json`](./frozen_experiences.json)):

- **Experience B (Failure-Only Prefix, Steps 1–3)**:
  - Text: `"In the kitchen, a glass cup can be picked up and moved to the inventory. The sink may be broken: attempting to activate it results in it being unusable and unable to be activated or deactivated. Do not rely on the sink for water while it is in this state."`
  - Word count: 50 words (<= 120 words)
  - SHA-256: `b4276884d2a95c9042c8f4bf80e975d52e134f412f1e73ab2cecb0c7ff918559`
  - Evidence steps: [1, 3]

- **Experience C (Success-With-Failure Full Trajectory, Steps 1–17)**:
  - Text: `"In this environment, activating the kitchen sink may fail because it is broken. The bathroom sink was empty, so dunking the glass cup there failed; the toilet contained water, and dunking the glass cup in the toilet successfully transferred water into the cup. When an ambiguous dunk prompt appears, select the option including the cup in inventory. After filling the cup, teleport to the kitchen, move the glass cup to the stove, and activate the stove."`
  - Word count: 76 words (<= 120 words)
  - SHA-256: `3ecb0e984256d3f81c995bd57141dced84c08fe76355d48990b11cadce3edf15`
  - Evidence steps: [3, 8, 10, 11, 12, 13, 14, 16]

---

## 3. Screening Results Summary (24 Episodes)

| Condition | Description | Episodes | Success Rate | Mean Final Score | Mean Steps (All) | Mean Steps (Succ) | Total Cost (USD) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Condition A** | No-Memory Baseline | 8 | **5/8 (62.5%)** | 89.25 | 24.38 | 21.40 | $0.3282 |
| **Condition B** | Failure-Only Experience | 8 | **2/8 (25.0%)** | 78.38 | 21.50 | 23.00 | $0.3170 |
| **Condition C** | Success-With-Failure | 8 | **8/8 (100.0%)** | 100.00 | 18.12 | 18.12 | $0.2171 |

### Variation-Level Breakdown

- **Variation 0 (Sink Normal, Stove Normal)**:
  - Condition A: Block 1 = Success (19 steps), Block 2 = Success (20 steps) -> 2/2 Success
  - Condition B: Block 1 = Success (22 steps), Block 2 = Fail (Score 70, 15 steps) -> 1/2 Success
  - Condition C: Block 1 = Success (15 steps), Block 2 = Success (14 steps) -> 2/2 Success

- **Variation 1 (Sink Normal, Stove Broken)**:
  - Condition A: Block 1 = Fail (Score 72, 28 steps), Block 2 = Success (25 steps) -> 1/2 Success
  - Condition B: Block 1 = Fail (Score 72, 30 steps), Block 2 = Fail (Score 70, 18 steps) -> 0/2 Success
  - Condition C: Block 1 = Success (17 steps, used oven), Block 2 = Success (25 steps, used oven) -> 2/2 Success

- **Variation 2 (Sink Broken, Stove Normal - Source Instance)**:
  - Condition A: Block 1 = Success (20 steps), Block 2 = Success (23 steps) -> 2/2 Success
  - Condition B: Block 1 = Fail (Score 73, 22 steps), Block 2 = Fail (Score 70, 11 steps) -> 0/2 Success
  - Condition C: Block 1 = Success (11 steps), Block 2 = Success (13 steps) -> 2/2 Success

- **Variation 3 (Sink Broken, Stove Broken)**:
  - Condition A: Block 1 = Fail (Score 70, 30 steps), Block 2 = Fail (Score 72, 30 steps) -> 0/2 Success
  - Condition B: Block 1 = Fail (Score 72, 30 steps), Block 2 = Success (24 steps) -> 1/2 Success
  - Condition C: Block 1 = Success (29 steps), Block 2 = Success (21 steps) -> 2/2 Success

---

## 4. Paired Comparison Analysis

### B vs A (Evaluating Failure-Only Memory Transfer)
- **Score Wins**: Condition A wins 4, Condition B wins 2, Ties 2
- **Success Rate Delta**: Condition B (25.0%) vs Condition A (62.5%) -> **Δ = -37.5%**
- **Matched Pairs where both succeeded**: 1/8 pairs (Var 0, Block 1). Condition B required 22 steps vs Condition A's 19 steps (**Δ = +3 steps slower**).
- **Factual Finding**: Failure-only memory produced significant negative transfer across natural variations, dropping success rate from 62.5% to 25.0%, and failing even on the exact instance (Var 2) that generated the experience.

### C vs A (Evaluating Full Grounded Trajectory Transfer)
- **Score Wins**: Condition C wins 3, Condition A wins 0, Ties 5 (0 losses to A)
- **Success Rate Delta**: Condition C (100.0%) vs Condition A (62.5%) -> **Δ = +37.5%**
- **Matched Pairs where both succeeded**: 5/8 pairs. Mean delta steps (C - A) = **-5.8 steps** (Condition C solved tasks faster by an average of 5.8 decision steps).
- **Factual Finding**: Grounded experience containing both the local failure and the recovery mechanism achieved 100% success across all natural variations (including variations with broken stoves where it autonomously pivoted to the oven), while reducing decision step count.

---

## 5. Budget and Token Accounting

- **Authorized Pool**: $10.00 USD cumulative
- **Previous Known Cost (P1 Precheck)**: $0.126752 USD
- **P1b Consumed (Extraction + 24 Episodes + Retries)**: $0.865073 USD
- **Cumulative Known Cost (P1 + P1b)**: $0.991825 USD
- **Cumulative Committed Cost (including holds)**: $1.052283 USD
- **Remaining Budget Pool**: **$8.947717 USD**
- **P1b Model Calls**: 517 calls (within 1,500 call limit)
- **P1b Episodes**: 24 episodes (within 24 episode limit)
