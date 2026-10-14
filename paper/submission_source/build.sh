#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

LOG_FILE="${SCRIPT_DIR}/build.log"
exec > >(tee "${LOG_FILE}") 2>&1

echo "=========================================="
echo "FailMem LaTeX Submission Build Pipeline"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=========================================="

echo "--- [1/2] Compiling main.tex ---"
pdflatex -interaction=nonstopmode main.tex
bibtex main
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex

echo "--- [2/2] Compiling supplementary.tex ---"
pdflatex -interaction=nonstopmode supplementary.tex
pdflatex -interaction=nonstopmode supplementary.tex

echo "=========================================="
echo "Build Verification & Inspection"
echo "=========================================="

# Check undefined citations or references
echo "Checking for undefined references or citations..."
UNDEFINED_REFS=$(grep -E -i "(undefined reference|citation.*undefined)" main.log supplementary.log || true)
if [ -n "${UNDEFINED_REFS}" ]; then
    echo "ERROR: Found undefined references/citations:"
    echo "${UNDEFINED_REFS}"
    exit 1
else
    echo "Clean: 0 undefined references and 0 undefined citations."
fi

# Check overfull warnings
echo "Checking for overfull warnings (> 15pt)..."
OVERFULL_WARNINGS=$(grep -E "Overfull \\\\hbox \([2-9][0-9]\." main.log supplementary.log || true)
if [ -n "${OVERFULL_WARNINGS}" ]; then
    echo "WARNING: Noticeable overfull hboxes found:"
    echo "${OVERFULL_WARNINGS}"
else
    echo "Clean: No significant overfull hboxes found."
fi

echo "=========================================="
echo "Artifact Summary"
echo "=========================================="
pdfinfo main.pdf | grep -E "(Pages|File size)"
pdfinfo supplementary.pdf | grep -E "(Pages|File size)"
sha256sum main.pdf supplementary.pdf

echo "Build complete. Log saved to ${LOG_FILE}"
