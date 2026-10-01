# Milestone P2c & H1 Reproduction Guide

This guide provides step-by-step instructions to reproduce the offline verification, statistical analysis, and simulation artifacts for Milestone P2c and the H1 feasibility check.

---

## 1. Environment & Dependencies

### Runtime Environment
- **Operating System**: Ubuntu 22.04 LTS (Jammy Jellyfish)
- **ROS Distribution**: ROS 2 Humble Hawksbill
- **Simulator**: Gazebo 11
- **Robot Model**: TurtleBot3 Waffle (`TB3_MODEL=waffle`)
- **Python Version**: Python 3.10+

### Python Dependencies
```bash
pip install -r requirements.txt  # Or: pip install numpy pandas matplotlib pytest
```

---

## 2. Fast Offline Verification & Reproduction (No ROS Daemon Required)

All raw evidence datasets are archived with raw sensor and costmap snapshots. You can run complete offline replay audits, statistical analysis, and unit test suites on any machine without starting Gazebo or ROS 2.

### Step 1: Run Full Automated Test Suite
Executes unit tests, event-driven replay audits, schema validations, and analysis script tests:
```bash
pytest
```
**Expected Output**:
```text
170 passed, 8 xfailed in ~1.5s
```
*(8 xfailed are expected negative corruption reproduction test cases)*.

---

### Step 2: Run Statistical Analysis & Regenerate CSVs/Figures
Runs the unified statistical analysis script over the 30-run physical pilot dataset:
```bash
python3 scripts/analyze_p2c_results.py reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35
```

**Expected Outputs** (written to `reports/evidence/p2c_pilot/p2c_pilot_20261001_022711_0d3c35/analysis/`):
1. `integrity_report.json`: Validates that all 30 episodes are present, data-complete, conflict-free, and audit-passed.
2. `episodes.csv`: Complete per-episode record of 30 runs across 10 conditions.
3. `condition_summary.csv`: Condition-level means, sample standard deviations ($ddof=1$), valid $n$ counts, and arrival rates.
4. `contrasts.csv`: Pairwise contrast differences ($F-R$, $F-O$, $F-M1$).
5. Figures:
   - `p2c_distances_by_condition.png`
   - `p2c_durations_by_condition.png`
   - `p2c_dead_ends_and_contrasts.png`

**Failure Criteria**:
- If any required field is missing, invalid type, or non-finite in `action_result.json`, `integrity_report.json` records the error and the CLI exits with non-zero exit code `1`.

---

### Step 3: Parse and Evaluate H1 Feasibility Check
Runs the offline parser and strict Go/No-Go decision evaluator over the H1 feasibility evidence:
```bash
python3 -c "from pathlib import Path; from scripts.verify_h1_feasibility import parse_and_derive_h1_evidence; res = parse_and_derive_h1_evidence(Path('reports/evidence/p2d_h1_feasibility'), Path('reports/evidence/p2d_h1_feasibility/derived')); print('Verdict:', res['evaluation_summary']['verdict'])"
```
**Expected Output**:
```text
Verdict: NO-GO (Scenario Not Established - 本场景未建立)
```

---

## 3. Physical Simulation Execution (Docker Environment)

To rerun physical simulations inside the verified container `failmem_humble`:

```bash
# Execute H1 limited feasibility check (4 physical runs)
docker exec failmem_humble bash -c "source /opt/ros/humble/setup.bash && cd /workspace && python3 scripts/verify_h1_feasibility.py --output-dir reports/evidence/p2d_h1_feasibility"
```

---

## 4. Key Evidence & Reports Directory Structure

```text
reports/
├── research-summary.md                   # Synthesis of questions, results, negative findings, and positioning
├── claim-evidence-matrix.md              # Traceability mapping claims to code, raw runs, and bounds
├── P2c-feasibility-pilot.md              # Detailed P2c 30-run exploratory benchmark report
├── P2c-research-decision.md              # Boundary analysis, F2 architecture, and O+ strong baseline
├── P2d-h1-feasibility-check.md           # H1 4-run feasibility check protocol, results, and No-Go verdict
└── evidence/
    ├── p2c_pilot/p2c_pilot_20261001_022711_0d3c35/ # 30 raw physical runs and analysis outputs
    └── p2d_h1_feasibility/               # 4 raw feasibility runs and derived parsed dataset
```
