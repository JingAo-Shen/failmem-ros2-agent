# Menu Protocol Recheck (P1c) Execution Notes

- **Phase**: `P1c_MENU_PROTOCOL_RECHECK`
- **Execution Timestamp**: 2026-10-22T14:35:00Z
- **Model**: `deepseek-flash` (Target: DeepSeek-V4.1-Flash-1017, system fingerprint: `e72d3c7f663d3e1383b00b3884cb4501`)
- **Generation Parameters**: `thinking={"type":"enabled"}`, `reasoning_effort="high"`, `response_format={"type":"json_object"}`, `max_tokens=8192`, `stream=false`, timeout 180s. No `temperature`, `top_p`, or `seed` sent to API.
- **ScienceWorld Protocol**: Unified `BaseAgent` adapter protocol:
  - If current observation contains `Ambiguous request:` and `blank to cancel`, and model outputs `action: ""`, the empty action passes safely to `env.step("")` with `adapter_reason="menu_blank_cancellation"`.
  - Normal observations or null/missing actions continue to terminate via `empty_or_non_string_terminate`.
  - Verified by 30/30 offline unit tests in `tests/test_remote_planner_offline.py`.
- **Decision Step Request Cap**: Strict upper bound of at most 2 model calls per step (including transport retries and internal JSON parse retries).
- **Experimental Design**:
  - 12 episodes across ScienceWorld `boil` variations 0 and 2 (source trajectory replay instance).
  - Conditions: A (No-Memory baseline), B (Failure-Only experience, D6 steps 1–3, SHA: `b4276884...`), C (Success-With-Failure experience, D6 steps 1–17, SHA: `3ecb0e98...`).
  - 2 Blocks: Block 3 (R01–R06) and Block 4 (R07–R12), pseudo-randomized with seed=3408.

---

## 1. Protocol Verification & Premature Abort Elimination

- **Empty Action Abort Count**: **0 / 12 episodes (0.0%)** (down from 3/8 in P1b Condition B).
- **Menu Interaction Observations**: In multiple episodes (e.g., R05, R06, R07, R09, R10, R11, R12), ambiguous disambiguation menus were encountered (such as dunking cups or closing drains). The model was able to navigate menus and make choices without being prematurely aborted by adapter string validation.

---

## 2. Recheck Results Summary (12 Episodes)

| Condition | Description | Episodes | Completion Rate | Empty Action Terminations | Mean Final Score | Mean Steps (All) | Mean Steps (Succ) | Total Cost (USD) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Condition A** | No-Memory Baseline | 4 | **1/4 (25.0%)** | 0/4 (0.0%) | 78.75 | 23.25 | 18.00 | $0.1821 |
| **Condition B** | Failure-Only Experience | 4 | **2/4 (50.0%)** | 0/4 (0.0%) | 85.75 | 24.00 | 18.00 | $0.1451 |
| **Condition C** | Success-With-Failure | 4 | **4/4 (100.0%)** | 0/4 (0.0%) | 100.00 | 12.75 | 12.75 | $0.0602 |

### Variation-Level Breakdown

- **Variation 0 (Sink Normal, Stove Normal)**:
  - Condition A: Block 3 = Success (18 steps), Block 4 = Fail (Score 75, 15 steps [env_done]) -> 1/2 Success
  - Condition B: Block 3 = Success (21 steps), Block 4 = Fail (Score 70, 30 steps [step_limit_30]) -> 1/2 Success
  - Condition C: Block 3 = Success (14 steps), Block 4 = Success (15 steps) -> 2/2 Success

- **Variation 2 (Sink Broken, Stove Normal - Source Instance Replay)**:
  - Condition A: Block 3 = Fail (Score 70, 30 steps), Block 4 = Fail (Score 70, 30 steps) -> 0/2 Success
  - Condition B: Block 3 = Success (15 steps), Block 4 = Fail (Score 73, 30 steps) -> 1/2 Success
  - Condition C: Block 3 = Success (10 steps), Block 4 = Success (12 steps) -> 2/2 Success

---

## 3. Paired Comparison Analysis (Blocks 3 & 4)

### B vs A
- **Score Wins / Losses / Ties**: Condition B scored higher in 2 pairs, Condition A scored higher in 1 pair, and 1 pair had equal scores (both 100.0).
- **Success / Completion Distribution**:
  - Condition B succeeded while Condition A failed: 1 pair (Var 2, Block 3: R04 score 100 vs R05 score 70)
  - Condition A succeeded while Condition B failed: 0 pairs
  - Both had identical success outcome: 3 pairs (Var 0 Block 3 [both succ], Var 0 Block 4 [both fail], Var 2 Block 4 [both fail])
- **Dual-Success Step Delta**: 1/4 pairs (Var 0, Block 3). Condition B required 21 steps vs Condition A's 18 steps (**Δ = +3 steps slower**).
- **Observation on this Sample**: With the menu cancellation protocol bug fixed, Condition B completed 2/4 episodes (including 1 success on the source replay instance Var 2), whereas Condition A completed 1/4. In Var 2, Condition B scored 100 and 73, outperforming Condition A's 70 and 70.

### C vs A
- **Score Wins / Losses / Ties**: Condition C scored higher in 3 pairs, Condition A scored higher in 0 pairs, and 1 pair had equal scores (both 100.0).
- **Success / Completion Distribution**:
  - Condition C succeeded while Condition A failed: 3 pairs (Var 0 Block 4, Var 2 Block 3, Var 2 Block 4)
  - Condition A succeeded while Condition C failed: 0 pairs
  - Both had identical success outcome: 1 pair (Var 0 Block 3, both succeeded)
- **Dual-Success Step Delta**: 1/4 pairs. Condition C required 14 steps vs Condition A's 18 steps (**Δ = -4 steps faster**).
- **Observation on this Sample**: Condition C maintained 100% completion (4/4) with a mean of 12.75 decision steps, demonstrating consistent positive transfer.

---

## 4. Cumulative Budget and Interaction Ledger

### Model Requests & Financial Ledger
- **Authorized Pool**: $10.00 USD cumulative
- **P1 Precheck Known Cost**: $0.126752 USD (57 calls)
- **P1b Screen Known Cost**: $0.865073 USD (517 calls)
- **P1c Recheck Known Cost**: $0.387430 USD (242 calls, 129,651 input tokens, 73,507 output tokens)
- **Cumulative Known Cost**: **$1.379255 USD** (816 calls, 701,382 input tokens, 431,117 output tokens)
- **Conservative Reserved Hold**: $0.081020 USD
- **Cumulative Committed Cost**: **$1.460275 USD**
- **Remaining Budget Pool**: **$8.539725 USD**
- **Audited Official Bill**: $0.00 (pending monthly billing statement)

### Environmental Interaction Accounting (Full Lifecycle)
- **P1 Historical Allocation Usage**: 159 episodes (141 local 7B, 12 Qwen3 precheck, 6 remote DeepSeek admission D1–D6)
- **P1b Natural Experience Screen**: 24 episodes (E01–E24)
- **P1c Menu Protocol Recheck**: 12 episodes (R01–R12)
- **P0 Interface & Calibration**: 8 episodes
- **Total Physical Environment Episodes**: **203 episodes** (well within total hard limit of 3,000 episodes).
