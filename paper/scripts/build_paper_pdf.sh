#!/usr/bin/env bash
# Build FailMem Paper PDF
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
if [[ -n "${NODE_PATH:-}" ]]; then
  export NODE_PATH="${REPO_ROOT}/node_modules:${NODE_PATH}"
else
  export NODE_PATH="${REPO_ROOT}/node_modules"
fi

python3 "${SCRIPT_DIR}/generate_paper_tables.py"
python3 "${SCRIPT_DIR}/plot_trajectories_map.py"
python3 "${SCRIPT_DIR}/build_paper_pdf.py"
