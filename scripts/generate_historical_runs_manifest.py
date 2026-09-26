#!/usr/bin/env python3
"""
Historical Runs Manifest Generator:
Scans existing runs/ directory from baseline commit f9b067b (created 2026-09-15),
computes SHA256 hashes of all metrics, predictions, events, and summary files,
and records their exact content and status in reports/evidence/r0/historical_runs_manifest.json.
"""

import os
import json
import hashlib

def sha256_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def main():
    runs_dir = "runs"
    manifest = {
        "description": "Inventory of historical mock runs created on 2026-09-15 (local, uncommitted in Git due to .gitignore)",
        "source_baseline_commit": "f9b067b4c321e3304db6f71abc116497bf767aab",
        "p3_summary_file": {},
        "runs": {}
    }
    
    summary_path = os.path.join(runs_dir, "p3_final_summary.json")
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_content = json.load(f)
        manifest["p3_summary_file"] = {
            "path": summary_path,
            "sha256": sha256_file(summary_path),
            "content": summary_content
        }
        
    for entry in sorted(os.listdir(runs_dir)):
        run_path = os.path.join(runs_dir, entry)
        if os.path.isdir(run_path) and entry.startswith("final_"):
            files = {}
            for fname in sorted(os.listdir(run_path)):
                fpath = os.path.join(run_path, fname)
                if os.path.isfile(fpath):
                    files[fname] = {
                        "size_bytes": os.path.getsize(fpath),
                        "sha256": sha256_file(fpath)
                    }
                    if fname == "metrics.json":
                        with open(fpath, "r", encoding="utf-8") as f:
                            files[fname]["metrics"] = json.load(f)
            manifest["runs"][entry] = {
                "run_dir": run_path,
                "files": files
            }
            
    out_file = "reports/evidence/r0/historical_runs_manifest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        
    print(f"Historical runs manifest generated with {len(manifest['runs'])} runs at {out_file}")

if __name__ == "__main__":
    main()
