#!/usr/bin/env bash
set -euo pipefail

# FailMem Conditional Constraint Memory Pilot Entrypoint Script
echo "=========================================================="
echo "FailMem Conditional Constraint Memory Pilot Runner"
echo "=========================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

echo "[Step 1/3] Running Unit and Acceptance Test Suite..."
pytest "${SCRIPT_DIR}/test_constraint_lifecycle.py" "${SCRIPT_DIR}/test_task_environment.py" -v

echo "[Step 2/3] Checking GPU Readiness..."
nvidia-smi

echo "[Step 3/3] Launching Controlled Pilot Experiment (Budget <= 36 runs)..."
python3 "${SCRIPT_DIR}/run_pilot.py"

echo "=========================================================="
echo "Pilot experiment completed successfully."
echo "Results available in: ${SCRIPT_DIR}/results/"
echo "=========================================================="
