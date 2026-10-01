# FailMem Offline Reproduction and Verification Report

**Date**: 2026-10-01  
**Execution Environment**: Ubuntu Linux 22.04 LTS x86_64, Python 3.13.5 (Host environment; not isolated sandbox)  
**Core Dependencies**: `pytest==8.3.4`, `pandas==2.2.3`, `numpy==2.1.3`, `matplotlib==3.10.0`, `scipy==1.15.3`, `pyyaml==6.0.2`  
**Git Commit**: `c2bf01a`  
**Purpose**: Document the offline reproduction of P2c and H1 datasets, verifying file checksums, offline replaying, objective re-scoring, automated statistical aggregation, and pytest suite execution.

---

## 1. Reproduction Commands & Workflow

To reproduce the analysis and audit from raw evidence without running ROS 2 or Gazebo daemons:

```bash
# 1. Create a fresh reproduction working directory and copy raw evidence
mkdir -p reports/evidence/p2c_pilot_reproduced
cp -r reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/* reports/evidence/p2c_pilot_reproduced/

# 2. Verify SHA256 hashes against frozen checksum manifest
cd reports/evidence/p2c_pilot_reproduced && sha256sum -c checksums.sha256 && cd ../../..

# 3. Execute independent replay and objective scoring
python3 scripts/replay_and_score_p2c.py reports/evidence/p2c_pilot_reproduced/

# 4. Run statistical aggregation and generate CSV summaries and plots
python3 scripts/analyze_p2c_results.py reports/evidence/p2c_pilot_reproduced/

# 5. Parse and derive H1 feasibility evidence
python3 -c "from pathlib import Path; from scripts.verify_h1_feasibility import parse_and_derive_h1_evidence; parse_and_derive_h1_evidence(Path('reports/evidence/p2d_h1_feasibility'), Path('reports/evidence/p2d_h1_feasibility/derived'))"

# 6. Execute full test suite
pytest
```

---

## 2. Checksum Verification & Replay Audit Outputs

### 2.1 Raw Evidence Integrity Check (SHA256)
- **Target Dataset**: `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/`
- **Result**: `241/241` files matched SHA256 checksums (`OK`), exit code `0`.
- **H1 Feasibility Dataset**: `reports/evidence/p2d_h1_feasibility/`
- **Result**: `25/25` files matched SHA256 checksums (`OK`), exit code `0`.

### 2.2 Replay Audit Results (`p2c_replay_summary.json`)
- **Episodes Evaluated**: 30 / 30
- **Summary**: All 30 episodes passed multi-layer offline replay audit (`audit_pass: True`), validating trajectory integration, 180s simulation budget, physical halt stability window, and memory lifecycle bindings.
- **Log File**: `reports/evidence/p2c_pilot_reproduced/reproduction_commands.log`

---

## 3. Comparison Between Baseline and Reproduced Statistics

The script compared the newly generated CSVs in `reports/evidence/p2c_pilot_reproduced/` against the baseline dataset in `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/`:

```json
{
  "all_matched": true,
  "comparisons": {
    "episodes.csv": {
      "orig_rows": 30,
      "repro_rows": 30,
      "exact_dataframe_equal": true
    },
    "condition_summary.csv": {
      "orig_rows": 10,
      "repro_rows": 10,
      "exact_dataframe_equal": true
    },
    "contrasts.csv": {
      "orig_rows": 35,
      "repro_rows": 35,
      "exact_dataframe_equal": true
    }
  }
}
```
*Verification*: All 30 rows in `episodes.csv`, 10 rows in `condition_summary.csv`, and 35 contrast pairs in `contrasts.csv` are strictly identical.

---

## 4. Summary Table of Reproduced Condition Metrics (Gazebo 11, $n=3$ per Condition)

| Scenario | Condition | $n$ | Actual Route | Dead-End Traversals | Decision Dist (m) | Decision Time (s) | Total Dist (m) | Total Time (s) | Replay Audit Pass |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **D0** | $R$ (Reactive) | 3 | `Path_A` | $0.0 \pm 0.0$ | $6.160 \pm 0.040$ | $51.533 \pm 1.662$ | $6.160 \pm 0.040$ | $51.533 \pm 1.662$ | 3/3 (100%) |
| **D0** | $O$ (Spatial Cache) | 3 | `Path_A` | $0.0 \pm 0.0$ | $6.203 \pm 0.012$ | $49.967 \pm 0.850$ | $6.203 \pm 0.012$ | $49.967 \pm 0.850$ | 3/3 (100%) |
| **D0** | $F$ (FailMem) | 3 | `Path_A` | $0.0 \pm 0.0$ | $6.196 \pm 0.031$ | $49.900 \pm 0.458$ | $6.196 \pm 0.031$ | $49.900 \pm 0.458$ | 3/3 (100%) |
| **D1** | $R$ (Reactive) | 3 | `Path_A_then_Path_B` | $1.0 \pm 0.0$ | $10.816 \pm 0.067$ | $82.067 \pm 4.388$ | $17.220 \pm 0.243$ | $141.000 \pm 5.912$ | 3/3 (100%) |
| **D1** | $O$ (Spatial Cache) | 3 | `Path_B` | $0.0 \pm 0.0$ | $7.550 \pm 0.053$ | $50.033 \pm 1.986$ | $13.947 \pm 0.071$ | $108.700 \pm 2.718$ | 3/3 (100%) |
| **D1** | $F$ (FailMem) | 3 | `Path_B` | $0.0 \pm 0.0$ | $7.536 \pm 0.005$ | $48.200 \pm 0.954$ | $14.027 \pm 0.252$ | $109.500 \pm 1.572$ | 3/3 (100%) |
| **D2** | $R$ (Reactive) | 3 | `Path_A` | $0.0 \pm 0.0$ | $5.915 \pm 0.038$ | $49.567 \pm 1.595$ | $16.344 \pm 0.031$ | $148.167 \pm 3.156$ | 3/3 (100%) |
| **D2** | $O$ (Spatial Cache) | 3 | `Path_A` | $0.0 \pm 0.0$ | $5.939 \pm 0.070$ | $52.033 \pm 1.747$ | $16.396 \pm 0.237$ | $149.767 \pm 0.551$ | 3/3 (100%) |
| **D2** | $F$ (FailMem) | 3 | `Path_A` | $0.0 \pm 0.0$ | $5.886 \pm 0.021$ | $51.100 \pm 0.954$ | $16.247 \pm 0.103$ | $151.100 \pm 7.763$ | 3/3 (100%) |
| **D2** | $M_1$ (Persistent) | 3 | `Path_B` | $0.0 \pm 0.0$ | $7.895 \pm 0.023$ | $51.300 \pm 2.000$ | $18.248 \pm 0.089$ | $148.833 \pm 2.401$ | 3/3 (100%) |

---

## 5. Test Suite Execution & Clarification of XFailed Tests

### 5.1 Pytest Execution
- **Command**: `pytest`
- **Result**: `176 passed, 8 xfailed in 2.1s`, exit code `0`.

### 5.2 Clarification of the 8 XFailed Tests
The 8 `xfailed` tests reside in `tests/test_audit_reproductions.py` (`TestR0DefectReproduction`). They are strictly marked with `@pytest.mark.xfail(raises=AssertionError, strict=True)`.

*Scope & Limitation*: These fixtures are designed to reproduce specific defects present in the legacy Phase R0 mock implementation (such as missing verifier execution, outdated map leakage, and mock state machine artifacts). They serve as permanent documentation of historical defects. They do **not** provide complete regression prevention for unexercised production paths, which are instead tested by the 176 passing unit and event-driven integration tests in `tests/`.
