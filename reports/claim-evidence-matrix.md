# FailMem Claim-Evidence Mapping Matrix

**Date**: 2026-10-01  
**Repository Branch**: `audit/r0-authenticity`  
**Purpose**: Direct traceability matrix linking every scientific and architectural claim to source code, raw simulation evidence, analysis outputs, and validity boundaries.

---

## Traceability Table

| Claim ID | Claim Description | Status | Source Code References | Raw Evidence Artifacts | Analysis / Verification Outputs | Scope of Validity & Boundaries |
| :--- | :--- | :---: | :--- | :--- | :--- | :--- |
| **C1** | **Historical Information Eliminates Redundant Dead-End Exploration** | **Supported by Data** | [`src/failure_memory.py`](file:///code/failmem-ros2-agent/src/failure_memory.py)<br>[`scripts/run_p2c_experiment.py`](file:///code/failmem-ros2-agent/scripts/run_p2c_experiment.py) | `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/D1_*` (9 runs) | `reports/evidence/p2c_pilot/.../analysis/condition_summary.csv`<br>`episodes.csv` | In D1 blocked dual-path layout, both $F$ and $O$ exhibit $0.0$ dead ends vs. Reactive $R$'s $1.0$, reducing total distance by $-18.5\%$ and time by $-22.3\%$. |
| **C2** | **Dynamic Memory Invalidation Prevents Permanent Detour Overhead** | **Supported by Data** | [`src/failure_memory.py:350`](file:///code/failmem-ros2-agent/src/failure_memory.py)<br>[`src/doorway_evaluator.py`](file:///code/failmem-ros2-agent/src/doorway_evaluator.py) | `reports/evidence/p2c_pilot/.../D2_F_*`<br>`reports/evidence/p2c_pilot/.../D2_M1_*` (6 runs) | `reports/evidence/p2c_pilot/.../analysis/contrasts.csv` ($F$ vs $M1$) | In D2 cleared environment, $F$ dynamically clears suppression upon seeing `FREE`, saving $2.00\,\text{m}$ ($-11.0\%$) total distance relative to persistent memory $M1$. Total execution times are comparable ($151.1\,\text{s}$ vs $148.8\,\text{s}$). |
| **C3** | **Failure Memory Does Not Exceed Spatial Cache in Static 2D Geometry** | **Boundary Finding (Negative Result)** | [`src/failure_memory.py`](file:///code/failmem-ros2-agent/src/failure_memory.py)<br>[`src/spatial_cache.py`](file:///code/failmem-ros2-agent/src/spatial_cache.py) | `reports/evidence/p2c_pilot/.../D1_F_*`<br>`reports/evidence/p2c_pilot/.../D1_O_*`<br>`reports/evidence/p2c_pilot/.../D2_F_*`<br>`reports/evidence/p2c_pilot/.../D2_O_*` (12 runs) | `reports/evidence/p2c_pilot/.../analysis/contrasts.csv` ($F$ vs $O$ in D1 & D2) | In static geometric blockages, $F$ and $O$ produce identical route choices with $<1\%$ cost differences (within simulation variance). Current empirical data does NOT prove $F$ is superior to $O$. |
| **C4** | **Candidate Action-Conditioned Scenario Feasibility Check ($H_1$)** | **Scenario Not Established (No-Go)** | [`scripts/verify_h1_feasibility.py`](file:///code/failmem-ros2-agent/scripts/verify_h1_feasibility.py) | `reports/evidence/p2d_h1_feasibility/` (4 physical runs, checksums verified) | `reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json`<br>[`reports/P2d-h1-feasibility-check.md`](file:///code/failmem-ros2-agent/reports/P2d-h1-feasibility-check.md) | In clear doorway geometry (`FREE`), both candidate aligned and oblique goal actions succeeded (`SUCCEEDED`, 4/4 Nav2 success). Executability divergence did not manifest; 20-run trial was terminated. Does not refute the general hypothesis. |
| **C5** | **Zero-Bypass Immutable Observation & Replay Audit Contracts** | **Verified by Test Suite** | [`src/doorway_evaluator.py`](file:///code/failmem-ros2-agent/src/doorway_evaluator.py)<br>[`scripts/replay_and_score_p2c.py`](file:///code/failmem-ros2-agent/scripts/replay_and_score_p2c.py) | `reports/evidence/p2c_pilot/.../*/scan_snapshots.json`<br>`costmap_snapshots.json` | [`tests/test_p2c_event_driven.py`](file:///code/failmem-ros2-agent/tests/test_p2c_event_driven.py) (21 paired test cases passed) | Every replay step recomputes subgrid ROI metrics directly from raw sensor observations, rejecting placeholder fields (`"unknown"` / empty) and invalid timestamps. |
| **C6** | **Action-Conditioned Memory ($F2$) & Backoff Baseline ($O+$) Design** | **Conceptual Specification (Unimplemented)** | [`reports/P2c-research-decision.md:80`](file:///code/failmem-ros2-agent/reports/P2c-research-decision.md) | None (Explicitly unexecuted) | [`reports/P2c-research-decision.md`](file:///code/failmem-ros2-agent/reports/P2c-research-decision.md) Section 5 | Architectural specification for binding failure to `action_profile_id` and contrasting with retry backoff $O+$. Preserved as future work without empirical claims. |

---

## Evidence Integrity Guarantee

All raw simulation evidence artifacts are cryptographically hashed and cross-verified:
- Milestone P2c Raw Dataset: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/checksums.sha256`
- H1 Feasibility Raw Dataset: `reports/evidence/p2d_h1_feasibility/checksums.sha256`
- Derived Parsed Artifacts: `reports/evidence/p2d_h1_feasibility/derived/h1_feasibility_parsed.json`
