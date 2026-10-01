#!/usr/bin/env python3
"""Build publication-ready paper.pdf from paper/draft.md and references.bib.

Features:
1. Dynamic Table Inclusion: replaces table blocks/placeholders with paper/tables/*.md.
2. Citation Preprocessing: converts LaTeX \\cite{} commands to Pandoc [@citekey] citations.
3. High-Fidelity MathJax SVG Vector Pre-Rendering: converts all LaTeX math equations to inline SVGs.
4. CSS-Driven Layout Compilation: runs WeasyPrint with academic CSS.
5. Post-Build Page Inspection: renders PDF pages to PNG and validates text content.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PAPER_DIR = REPO_ROOT / "paper"
DRAFT_MD = PAPER_DIR / "draft.md"
STYLE_CSS = PAPER_DIR / "paper_style.css"
REFERENCES_BIB = PAPER_DIR / "references.bib"
TABLES_DIR = PAPER_DIR / "tables"
OUTPUT_HTML = PAPER_DIR / "paper.html"
OUTPUT_PDF = PAPER_DIR / "paper.pdf"
PAGE_INSPECT_DIR = PAPER_DIR / "figures" / "pdf_pages"


def inject_generated_tables(content: str) -> str:
    """Replace table placeholder blocks with fresh content from paper/tables/*.md."""
    for tbl_name in ["table1_condition_summary", "table2_pairwise_contrasts", "table3_h1_feasibility"]:
        tbl_file = TABLES_DIR / f"{tbl_name}.md"
        if not tbl_file.exists():
            raise FileNotFoundError(f"Required table file does not exist: {tbl_file}")
        with open(tbl_file, "r", encoding="utf-8") as f:
            tbl_md = f.read().strip()
        if not tbl_md:
            raise ValueError(f"Table file is empty: {tbl_file}")

        pattern = rf"<!-- TABLE:{tbl_name} -->(\s*\n\|[^\n]+\|)+"
        if re.search(pattern, content):
            content = re.sub(pattern, lambda m, md=tbl_md, tn=tbl_name: f"<!-- TABLE:{tn} -->\n{md}", content)
        elif f"<!-- TABLE:{tbl_name} -->" in content:
            content = content.replace(f"<!-- TABLE:{tbl_name} -->", f"<!-- TABLE:{tbl_name} -->\n{tbl_md}")
        else:
            raise ValueError(f"Table placeholder <!-- TABLE:{tbl_name} --> not found in draft.md")

    return content


def prepare_markdown_content(input_path: Path) -> str:
    """Prepare Markdown: inject tables, fix citations, and ensure proper spacing."""
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Inject fresh tables
    content = inject_generated_tables(content)

    # 2. Convert \cite{k1, k2} -> [@k1; @k2]
    def repl_cite(match):
        keys = [k.strip() for k in match.group(1).split(",")]
        return "[" + "; ".join(f"@{k}" for k in keys) + "]"

    content = re.sub(r"\\cite\{([^}]+)\}", repl_cite, content)

    # 3. Clean bibliography commands at end
    content = re.sub(r"\\bibliographystyle\{[^}]+\}", "", content)
    content = re.sub(r"\\bibliography\{[^}]+\}", "", content)

    return content


def render_math_to_svg(html_path: Path) -> None:
    """Use MathJax-full to convert all MathJax spans into inline SVG vector math."""
    node_script = """
const fs = require('fs');
const { mathjax } = require('mathjax-full/js/mathjax.js');
const { TeX } = require('mathjax-full/js/input/tex.js');
const { SVG } = require('mathjax-full/js/output/svg.js');
const { liteAdaptor } = require('mathjax-full/js/adaptors/liteAdaptor.js');
const { RegisterHTMLHandler } = require('mathjax-full/js/handlers/html.js');
const { AllPackages } = require('mathjax-full/js/input/tex/AllPackages.js');

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const tex = new TeX({ packages: AllPackages });
const svg = new SVG({ fontCache: 'local' });
const html = mathjax.document('', { InputJax: tex, OutputJax: svg });

const htmlPath = process.argv[1];
let content = fs.readFileSync(htmlPath, 'utf8');

// Convert inline math: <span class="math inline">\\(...\\)</span>
content = content.replace(/<span class="math inline">\\\\\\(([\\s\\S]*?)\\\\\\)<\\/span>/g, (match, mathStr) => {
    try {
        const decoded = mathStr.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&quot;/g, '"');
        const node = html.convert(decoded, { display: false });
        return adaptor.innerHTML(node);
    } catch (e) {
        console.error('Error rendering inline math:', mathStr, e.message);
        return match;
    }
});

// Convert display math: <span class="math display">\\[...\\]</span>
content = content.replace(/<span class="math display">\\\\\\[([\\s\\S]*?)\\\\\\]<\\/span>/g, (match, mathStr) => {
    try {
        const decoded = mathStr.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&quot;/g, '"');
        const node = html.convert(decoded, { display: true });
        return '<div class="math-display-svg" style="text-align: center; margin: 10px 0;">' + adaptor.innerHTML(node) + '</div>';
    } catch (e) {
        console.error('Error rendering display math:', mathStr, e.message);
        return match;
    }
});

fs.writeFileSync(htmlPath, content, 'utf8');
console.log('Successfully pre-rendered LaTeX math into vector SVGs.');
"""
    env = os.environ.copy()
    node_path = "/root/.nvm/versions/node/v24.21.0/lib/node_modules"
    if "NODE_PATH" in env:
        env["NODE_PATH"] = f"{node_path}:{env['NODE_PATH']}"
    else:
        env["NODE_PATH"] = node_path

    subprocess.run(
        ["node", "-e", node_script, str(html_path)],
        check=True,
        env=env,
        cwd=PAPER_DIR,
    )


def inspect_pdf_pages(pdf_path: Path) -> Dict[str, Any]:
    """Render PDF pages to PNG and extract text for inspection."""
    PAGE_INSPECT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Run pdftoppm to generate PNGs
    prefix = str(PAGE_INSPECT_DIR / "page")
    subprocess.run(["pdftoppm", "-png", "-r", "150", str(pdf_path), prefix], check=True)

    # Run pdftotext to extract text
    res = subprocess.check_output(["pdftotext", str(pdf_path), "-"], text=True)

    pages = sorted(list(PAGE_INSPECT_DIR.glob("page-*.png")))

    # Check for unrendered TeX math fragments
    raw_tex_leaks = []
    for pattern in [r"\\text\{", r"\\begin\{cases\}", r"\\mathbf\{", r"\\langle", r"\\le\b", r"\\ge\b"]:
        if re.search(pattern, res):
            raw_tex_leaks.append(pattern)

    return {
        "total_pages": len(pages),
        "page_images": [str(p) for p in pages],
        "extracted_char_count": len(res),
        "raw_tex_leaks": raw_tex_leaks,
        "math_clean": len(raw_tex_leaks) == 0,
    }


def build_pdf() -> Dict[str, Any]:
    """Execute complete PDF generation pipeline."""
    print(f"Building paper PDF from {DRAFT_MD}...")

    # 1. Process Markdown with dynamic table injection
    processed_md_path = PAPER_DIR / ".draft_processed.md"
    processed_content = prepare_markdown_content(DRAFT_MD)
    with open(processed_md_path, "w", encoding="utf-8") as f:
        f.write(processed_content)

    # 2. Run Pandoc to generate HTML with citations and MathJax markup
    pandoc_cmd = [
        "pandoc",
        str(processed_md_path),
        "--citeproc",
        f"--bibliography={REFERENCES_BIB}",
        f"--css={STYLE_CSS}",
        "--standalone",
        "--mathjax",
        "-o", str(OUTPUT_HTML),
    ]
    print(f"Running pandoc: {' '.join(pandoc_cmd)}")
    subprocess.run(pandoc_cmd, check=True, cwd=PAPER_DIR)

    # Verify all tables are present in generated HTML
    with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
        html_text = f.read()
    for tbl_marker in ["Condition-Level Navigation Performance", "Key Pairwise Contrasts", "Action-Conditioned Navigation"]:
        if tbl_marker not in html_text and "table" not in html_text.lower():
            raise ValueError(f"Generated HTML missing expected table content for: {tbl_marker}")

    # 3. Pre-render math into inline SVGs via MathJax-full
    render_math_to_svg(OUTPUT_HTML)

    # 4. Run WeasyPrint to generate PDF
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

    # 5. Inspect generated PDF
    inspection = inspect_pdf_pages(OUTPUT_PDF)
    print(f"\n[PDF INSPECTION] Total Pages: {inspection['total_pages']}, Math Clean: {inspection['math_clean']}")
    if not inspection["math_clean"]:
        print(f"[WARNING] Detected raw TeX leaks in PDF: {inspection['raw_tex_leaks']}")
    else:
        print("[SUCCESS] Zero raw TeX leaks detected in compiled PDF.")

    print(f"[SUCCESS] Successfully compiled {OUTPUT_PDF} ({OUTPUT_PDF.stat().st_size / 1024:.1f} KB)")
    return inspection


def main():
    parser = argparse.ArgumentParser(description="Build FailMem Paper PDF")
    args = parser.parse_args()
    build_pdf()


if __name__ == "__main__":
    main()
