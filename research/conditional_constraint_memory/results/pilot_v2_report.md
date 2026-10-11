# Controlled Pilot Experiment Report (Version 2.0)

**Execution Date**: 2026-10-11 10:49:18 UTC  
**Environment**: Multi-Step Service Deployment Environment (Real Socket + Non-Root User Permissions)  
**Model**: Qwen3-14B-AWQ (RTX 2080 Ti, temp=0.0, AWQ 4-bit, enable_thinking=False)  
**Budget Adherence**: Exactly 36 model episodes executed (2 Smoke + 2 Source + 32 Target).  

---

## 1. Executive Summary & Audit Observations

### Key Empirical Observations:
- **Success Rates**: B0: 100.0%, B2: 100.0%, B2-G: 100.0%, M: 100.0%.
- **Executed Errors**: B0: 0, B2: 0, B2-G: 0, M: 0.
- **Gate Triggers**: Total TP Blocks across all groups: 0, Total FP Blocks: 0, Active UNKNOWN Probes: 0.
- **Gate Efficacy Assessment**: Because gate triggers did not occur in practice (0 blocks recorded), no claim of gate protection or false-positive reduction can be established from this pilot.

---

## 2. Comparative Metrics Table

| Metric | B0 (No Memory) | B2 (Dynamic Facts) | B2-G (Predicate Gate) | M (Lifecycle Gate) |
| :--- | :---: | :---: | :---: | :---: |
| **Success Rate (8 instances)** | 8/8 (100.0%) | 8/8 (100.0%) | 8/8 (100.0%) | 8/8 (100.0%) |
| **Proposed Error Actions** | 0 | 0 | 0 | 0 |
| **Executed Error Actions** | 0 | 0 | 0 | 0 |
| **TP Blocks / FP Blocks** | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| **Active Probes Triggered** | 0 | 0 | 0 | 0 |
| **Candidate Trials** | - | - | - | 0 |
| **Avg LLM Calls / Ep** | 7.50 | 7.50 | 7.50 | 7.50 |
| **Avg Tool Calls / Ep** | 7.50 | 7.50 | 7.50 | 7.50 |
| **Avg Prompt Tokens** | 6738.1 | 6741.9 | 6742.1 | 6787.8 |
| **Avg Generated Tokens** | 447.2 | 446.8 | 447.9 | 452.1 |
| **Avg Total Tokens** | 7185.4 | 7188.6 | 7190.0 | 7239.9 |
| **Avg Model Inference Time (s)** | 164.13s | 163.94s | 164.31s | 165.86s |
| **Avg End-to-End Latency (s)** | 164.51s | 164.32s | 164.69s | 166.24s |

---

## 3. Instance-by-Instance Breakdown

| Instance ID | B0 Success (Steps) | B2 Success (Steps) | B2-G Success (Steps) | M Success (Steps) |
| :--- | :---: | :---: | :---: | :---: |
| `inst1_port_conflict_persistent` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst2_blockage_cleared` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst3_permission_fallback` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst4_irrelevant_change` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst5_stale_observation` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst6_counterexample_feasibility` | Pass (7) | Pass (7) | Pass (7) | Pass (7) |
| `inst7_midepisode_port_clash` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |
| `inst8_permission_and_port_composition` | Pass (8) | Pass (8) | Pass (8) | Pass (8) |

---

## 4. Formal Research Conclusion

**Final Verdict**: **本轮未观察到独立收益**
**Rationale**: All baseline groups and Method M achieved comparable task outcomes; gating mechanisms did not provide an independent advantage over dynamic facts baseline.
