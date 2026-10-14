#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=========================================="
echo "Compiling main.tex"
echo "=========================================="
pdflatex -interaction=nonstopmode main.tex
bibtex main
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex

echo "=========================================="
echo "Compiling supplementary.tex"
echo "=========================================="
pdflatex -interaction=nonstopmode supplementary.tex
pdflatex -interaction=nonstopmode supplementary.tex

echo "=========================================="
echo "Build complete! Verifying PDFs..."
echo "=========================================="
ls -lh main.pdf supplementary.pdf

echo "Done."
