#!/usr/bin/env bash
# FailMem P2c Offline Reproduction Wrapper Script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

python3 "${SCRIPT_DIR}/reproduce_offline.py" "$@"
