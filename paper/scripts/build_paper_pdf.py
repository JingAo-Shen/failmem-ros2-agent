#!/usr/bin/env python3
"""Build publication-ready paper.pdf from paper/draft.md and references.bib."""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PAPER_DIR = REPO_ROOT / "paper"
DRAFT_MD = PAPER_DIR / "draft.md"
STYLE_CSS = PAPER_DIR / "paper_style.css"
REFERENCES_BIB = PAPER_DIR / "references.bib"
OUTPUT_HTML = PAPER_DIR / "paper.html"
OUTPUT_PDF = PAPER_DIR / "paper.pdf"


def prepare_markdown_content(input_path: Path) -> str:
    """Prepare Markdown content: convert LaTeX cite commands to Pandoc citation keys."""
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace \cite{k1, k2} with [@k1; @k2]
    def repl_cite(match):
        keys = [k.strip() for k in match.group(1).split(",")]
        return "[" + "; ".join(f"@{k}" for k in keys) + "]"

    content = re.sub(r"\\cite\{([^}]+)\}", repl_cite, content)

    # Remove LaTeX bibliography boilerplate at end if present
    content = re.sub(r"\\bibliographystyle\{[^}]+\}", "", content)
    content = re.sub(r"\\bibliography\{[^}]+\}", "", content)

    return content


def build_pdf():
    print(f"Building paper PDF from {DRAFT_MD}...")
    
    # 1. Process Markdown
    processed_md_path = PAPER_DIR / ".draft_processed.md"
    processed_content = prepare_markdown_content(DRAFT_MD)
    with open(processed_md_path, "w", encoding="utf-8") as f:
        f.write(processed_content)

    # 2. Run Pandoc to generate HTML with citeproc
    pandoc_cmd = [
        "pandoc",
        str(processed_md_path),
        "--citeproc",
        f"--bibliography={REFERENCES_BIB}",
        f"--css={STYLE_CSS}",
        "--standalone",
        "--mathjax",
        "--metadata", "title=Auditable Failure Memory for ROS 2 Navigation: An Exploratory Comparison with Spatial Caching",
        "-o", str(OUTPUT_HTML),
    ]
    print(f"Running pandoc: {' '.join(pandoc_cmd)}")
    subprocess.run(pandoc_cmd, check=True, cwd=PAPER_DIR)

    # 3. Run WeasyPrint to generate PDF
    weasyprint_cmd = [
        "weasyprint",
        str(OUTPUT_HTML),
        str(OUTPUT_PDF),
    ]
    print(f"Running weasyprint: {' '.join(weasyprint_cmd)}")
    subprocess.run(weasyprint_cmd, check=True, cwd=PAPER_DIR)

    # Clean up temporary processed markdown
    if processed_md_path.exists():
        processed_md_path.unlink()

    print(f"\n[SUCCESS] Successfully compiled {OUTPUT_PDF} ({OUTPUT_PDF.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build_pdf()
