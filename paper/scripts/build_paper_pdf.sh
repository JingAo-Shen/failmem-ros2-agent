#!/usr/bin/env bash
# Build FailMem Paper PDF
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

python3 "${SCRIPT_DIR}/generate_paper_tables.py"
python3 "${SCRIPT_DIR}/plot_trajectories_map.py"
python3 "${SCRIPT_DIR}/build_paper_pdf.py"
