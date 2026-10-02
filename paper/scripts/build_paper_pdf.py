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
        process.exit(1);
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
        process.exit(1);
    }
});

fs.writeFileSync(htmlPath, content, 'utf8');
console.log('Successfully pre-rendered LaTeX math into vector SVGs.');
"""
    # Execute node with REPO_ROOT as cwd so local node_modules is automatically resolved
    res = subprocess.run(
        ["node", "-e", node_script, str(html_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        raise RuntimeError(f"Node.js math pre-rendering failed with code {res.returncode}: {res.stderr}")
    print(res.stdout.strip())

    # Verify no unrendered math tags remained
    with open(html_path, "r", encoding="utf-8") as f:
        rendered_content = f.read()
    if '<span class="math inline">' in rendered_content or '<span class="math display">' in rendered_content:
        raise RuntimeError("Unrendered math spans remained in HTML after MathJax rendering.")


def validate_html_tables(html_path: Path) -> Dict[str, Any]:
    """Strictly validate that all three required tables are present in HTML with exact row counts."""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    tables = re.findall(r"<table[\s\S]*?</table>", content)
    if len(tables) < 3:
        raise ValueError(f"Expected at least 3 HTML tables, found {len(tables)}")

    t1_found = False
    t2_found = False
    t3_found = False
    t1_rows = 0
    t2_rows = 0
    t3_rows = 0

    for tbl in tables:
        rows = re.findall(r"<tr[\s\S]*?</tr>", tbl)
        data_rows = [r for r in rows if "<th" not in r]

        if "Actual Route" in tbl or "Replay Audit Pass" in tbl:
            t1_found = True
            t1_rows = len(data_rows)
            if t1_rows != 10:
                raise ValueError(f"Table 1 (Condition Summary) must have exactly 10 data rows, found {t1_rows}")
        elif "Comparison" in tbl and "Abs Diff" in tbl:
            t2_found = True
            t2_rows = len(data_rows)
            if t2_rows != 10:
                raise ValueError(f"Table 2 (Pairwise Contrasts) must have exactly 10 data rows, found {t2_rows}")
        elif "Action Profile" in tbl and "Target Goal" in tbl:
            t3_found = True
            t3_rows = len(data_rows)
            if t3_rows != 4:
                raise ValueError(f"Table 3 (H1 Feasibility) must have exactly 4 data rows, found {t3_rows}")

    if not t1_found:
        raise ValueError("Table 1 (Condition Summary) not found in generated HTML")
    if not t2_found:
        raise ValueError("Table 2 (Pairwise Contrasts) not found in generated HTML")
    if not t3_found:
        raise ValueError("Table 3 (H1 Feasibility) not found in generated HTML")

    return {
        "total_tables": len(tables),
        "table1_rows": t1_rows,
        "table2_rows": t2_rows,
        "table3_rows": t3_rows,
        "all_tables_verified": True,
    }


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    import hashlib
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def inspect_pdf_pages(pdf_path: Path) -> Dict[str, Any]:
    """Render PDF pages to PNG and extract text for inspection."""
    PAGE_INSPECT_DIR.mkdir(parents=True, exist_ok=True)

    # Clean old pagination images before rendering to prevent stale page count
    for old_p in PAGE_INSPECT_DIR.glob("page-*.png"):
        try:
            old_p.unlink()
        except OSError:
            pass

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

    if raw_tex_leaks:
        raise RuntimeError(f"Raw TeX leaks detected in compiled PDF: {raw_tex_leaks}")

    return {
        "total_pages": len(pages),
        "page_images": [str(p.name) for p in pages],
        "extracted_char_count": len(res),
        "raw_tex_leaks": raw_tex_leaks,
        "math_clean": len(raw_tex_leaks) == 0,
        "inspection_executor": "Antigravity AI Agent (Automated rasterization & regex analysis)",
        "human_verified": False,
    }


def get_tool_versions() -> Dict[str, str]:
    """Extract versions of build toolchain."""
    tools = {"python": sys.version.split()[0]}
    try:
        tools["node"] = subprocess.check_output(["node", "-v"], text=True).strip()
    except Exception:
        tools["node"] = "unavailable"
    try:
        tools["pandoc"] = subprocess.check_output(["pandoc", "-v"], text=True).splitlines()[0].strip()
    except Exception:
        tools["pandoc"] = "unavailable"
    try:
        tools["weasyprint"] = subprocess.check_output(["weasyprint", "--version"], text=True).strip()
    except Exception:
        tools["weasyprint"] = "unavailable"
    try:
        tools["pdftoppm"] = subprocess.check_output(["pdftoppm", "-v"], stderr=subprocess.STDOUT, text=True).splitlines()[0].strip()
    except Exception:
        tools["pdftoppm"] = "unavailable"
    return tools


def build_pdf() -> Dict[str, Any]:
    """Execute complete PDF generation pipeline."""
    import json
    from datetime import datetime, timezone

    print(f"Building paper PDF from {DRAFT_MD}...")

    # Capture source git state prior to any build actions
    try:
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        source_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        source_status_raw = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True).strip()
        source_dirty = bool(source_status_raw)
        source_status_lines = [line.strip() for line in source_status_raw.splitlines() if line.strip()]
    except Exception:
        source_commit, source_branch, source_dirty, source_status_lines = "unknown", "unknown", False, []

    # Record source inputs hashes before build
    input_files = [
        DRAFT_MD,
        REFERENCES_BIB,
        STYLE_CSS,
        TABLES_DIR / "table1_condition_summary.md",
        TABLES_DIR / "table2_pairwise_contrasts.md",
        TABLES_DIR / "table3_h1_feasibility.md",
        PAPER_DIR / "figures" / "trajectories_map.png",
    ]
    source_input_hashes = {p.name: compute_file_sha256(p) for p in input_files if p.exists()}

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

    # 3. Pre-render math into inline SVGs via MathJax-full
    render_math_to_svg(OUTPUT_HTML)

    # 4. Strictly validate all tables in HTML
    table_validation = validate_html_tables(OUTPUT_HTML)
    print(f"[TABLE VALIDATION] Verified tables: {table_validation}")

    # 5. Run WeasyPrint to generate PDF
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

    # 6. Inspect generated PDF
    inspection = inspect_pdf_pages(OUTPUT_PDF)
    print(f"\n[PDF INSPECTION] Total Pages: {inspection['total_pages']}, Math Clean: {inspection['math_clean']}")

    # 7. Capture post-build workspace state and generated artifact hashes
    try:
        post_status_raw = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True).strip()
        post_dirty = bool(post_status_raw)
        post_changed_files = [line.strip() for line in post_status_raw.splitlines() if line.strip()]
    except Exception:
        post_dirty, post_changed_files = False, []

    artifact_files = [
        OUTPUT_PDF,
        OUTPUT_HTML,
        PAPER_DIR / "figures" / "trajectories_map.png",
        PAPER_DIR / "figures" / "trajectories_map.pdf",
        TABLES_DIR / "table1_condition_summary.md",
        TABLES_DIR / "table1_condition_summary.tex",
        TABLES_DIR / "table2_pairwise_contrasts.md",
        TABLES_DIR / "table2_pairwise_contrasts.tex",
        TABLES_DIR / "table3_h1_feasibility.md",
        TABLES_DIR / "table3_h1_feasibility.tex",
    ]
    generated_artifact_hashes = {p.name: compute_file_sha256(p) for p in artifact_files if p.exists()}

    build_report = {
        "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pre_build_git": {
            "source_commit": source_commit,
            "source_branch": source_branch,
            "source_dirty": source_dirty,
            "uncommitted_pre_build_changes": source_status_lines,
        },
        "post_build_workspace": {
            "post_build_dirty": post_dirty,
            "changed_files": post_changed_files,
        },
        "tool_versions": get_tool_versions(),
        "source_input_hashes": source_input_hashes,
        "generated_artifact_hashes": generated_artifact_hashes,
        "table_validation": table_validation,
        "math_rendering": {
            "engine": "mathjax-full (SVG vector)",
            "math_clean": inspection["math_clean"],
            "raw_tex_leaks": inspection["raw_tex_leaks"],
        },
        "pdf_output": {
            "path": str(OUTPUT_PDF),
            "file_size_bytes": OUTPUT_PDF.stat().st_size,
            "sha256": compute_file_sha256(OUTPUT_PDF),
            "total_pages": inspection["total_pages"],
            "page_images": inspection["page_images"],
        },
        "inspection": {
            "executor": inspection.get("inspection_executor", "Antigravity AI Agent (Automated rasterization & regex analysis)"),
            "human_verified": False,
            "note": "Automated rasterization and text inspection executed by AI Agent; not certified as human visual examination.",
        },
        "build_status": "SUCCESS",
    }

    report_path = PAPER_DIR / "build_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(build_report, f, indent=2)

    print(f"[SUCCESS] Build report saved to {report_path}")
    print(f"[SUCCESS] Successfully compiled {OUTPUT_PDF} ({OUTPUT_PDF.stat().st_size / 1024:.1f} KB, {inspection['total_pages']} pages)")
    return build_report


def main():
    parser = argparse.ArgumentParser(description="Build FailMem Paper PDF")
    args = parser.parse_args()
    try:
        build_pdf()
    except Exception as e:
        print(f"\n[ERROR] Paper build failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
