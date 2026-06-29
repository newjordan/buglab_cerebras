from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swarm_common import ROOT


RUNS_DIR = ROOT / "runs"
REPORTS_DIR = ROOT / "reports"
INDEX_PATH = REPORTS_DIR / "run_index.html"


def load_manifests() -> list[dict[str, Any]]:
    manifests = []
    for path in RUNS_DIR.glob("*/report_manifest.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        item["_manifest_path"] = path
        item["_report_path"] = path.parent / "report.html"
        manifests.append(item)
    return sorted(manifests, key=lambda item: item.get("created_at_utc", ""), reverse=True)


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def render(manifests: list[dict[str, Any]]) -> str:
    rows = []
    for manifest in manifests:
        findings = manifest.get("findings", [])
        metrics = manifest.get("metrics", {})
        report_path = manifest.get("_report_path")
        link = rel(report_path) if isinstance(report_path, Path) and report_path.exists() else ""
        rows.append(
            "<tr>"
            f"<td><a href='../{esc(link)}'>{esc(manifest.get('run_id', ''))}</a></td>"
            f"<td>{esc(manifest.get('tool', ''))}</td>"
            f"<td>{esc(manifest.get('target', ''))}</td>"
            f"<td>{esc(manifest.get('status', ''))}</td>"
            f"<td>{len(findings)}</td>"
            f"<td>{len(manifest.get('evidence', []))}</td>"
            f"<td>{esc(', '.join(metrics.keys()))}</td>"
            f"<td>{esc(manifest.get('created_at_utc', ''))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Bug Lab Run Index</title>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f8fafc; color: #111827; }}
      main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d6dbe3; border-radius: 8px; overflow: hidden; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #eef2f7; }}
      a {{ color: #2563eb; }}
    </style>
  </head>
  <body>
    <main>
      <h1>Bug Lab Run Index</h1>
      <p>Dynamic index of standardized run manifests. Each row links to a per-run evidence report.</p>
      <table>
        <thead><tr><th>Run</th><th>Tool</th><th>Target</th><th>Status</th><th>Findings</th><th>Evidence</th><th>Metrics</th><th>Created</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </main>
  </body>
</html>
"""


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifests = load_manifests()
    INDEX_PATH.write_text(render(manifests), encoding="utf-8")
    print(INDEX_PATH)
    print(f"standardized_runs={len(manifests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
