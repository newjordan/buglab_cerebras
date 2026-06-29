from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from swarm_common import ROOT
from swarm_common import write_json


SCHEMA_VERSION = "buglab.report.v1"


def rel(path: str | Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def make_manifest(
    *,
    run_id: str,
    tool: str,
    target: str,
    output_dir: Path,
    status: str = "unknown",
    title: str = "",
    summary: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "tool": tool,
        "target": target.replace("\\", "/"),
        "title": title or f"{tool}: {target}",
        "status": status,
        "summary": summary,
        "created_at_utc": utc_now(),
        "output_dir": rel(output_dir),
        "metrics": {},
        "evidence": [],
        "findings": [],
        "artifacts": {},
    }


def add_metric(manifest: dict[str, Any], name: str, value: Any, *, unit: str = "", description: str = "") -> None:
    manifest["metrics"][name] = {
        "value": value,
        "unit": unit,
        "description": description,
    }


def add_artifact(manifest: dict[str, Any], name: str, path: str | Path, *, kind: str = "file") -> None:
    manifest["artifacts"][name] = {
        "kind": kind,
        "path": rel(path),
    }


def add_evidence(
    manifest: dict[str, Any],
    *,
    evidence_id: str,
    kind: str,
    path: str | Path | None = None,
    label: str = "",
    description: str = "",
    condition: str = "",
    selector: str = "",
    action: str = "",
    viewport: dict[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "id": evidence_id,
        "kind": kind,
        "label": label,
        "description": description,
        "condition": condition,
        "selector": selector,
        "action": action,
        "path": rel(path) if path else "",
        "viewport": viewport or {},
        "metadata": metadata or {},
    }
    manifest["evidence"].append(record)
    return record


def add_finding(
    manifest: dict[str, Any],
    *,
    finding_id: str,
    title: str,
    severity: str,
    status: str,
    category: str,
    signals: list[str],
    evidence_ids: list[str],
    selector: str = "",
    reproduction_steps: list[str] | None = None,
    expected: str = "",
    actual: str = "",
    fix_hypothesis: str = "",
) -> None:
    manifest["findings"].append(
        {
            "id": finding_id,
            "title": title,
            "severity": severity,
            "status": status,
            "category": category,
            "selector": selector,
            "signals": signals,
            "evidence_ids": evidence_ids,
            "reproduction_steps": reproduction_steps or [],
            "expected": expected,
            "actual": actual,
            "fix_hypothesis": fix_hypothesis,
        }
    )


def severity_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in manifest.get("findings", []):
        severity = finding.get("severity", "unknown")
        counts[severity] = counts.get(severity, 0) + 1
    return dict(sorted(counts.items()))


def render_html(manifest: dict[str, Any]) -> str:
    evidence_by_id = {item["id"]: item for item in manifest.get("evidence", [])}
    metrics_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(item.get('value', '')))}</td>"
        f"<td>{html.escape(item.get('unit', ''))}</td><td>{html.escape(item.get('description', ''))}</td></tr>"
        for name, item in manifest.get("metrics", {}).items()
    )
    finding_cards = []
    for finding in manifest.get("findings", []):
        linked = [evidence_by_id[eid] for eid in finding.get("evidence_ids", []) if eid in evidence_by_id]
        thumbs = "".join(
            f"<figure><img src='{html.escape(Path(item['path']).name)}' alt='{html.escape(item.get('label') or item['id'])}'>"
            f"<figcaption>{html.escape(item.get('label') or item['id'])}</figcaption></figure>"
            for item in linked
            if item.get("kind") == "screenshot" and item.get("path")
        )
        steps = "".join(f"<li>{html.escape(step)}</li>" for step in finding.get("reproduction_steps", []))
        signals = "".join(f"<li>{html.escape(signal)}</li>" for signal in finding.get("signals", []))
        finding_cards.append(
            f"""
            <section class="finding {html.escape(finding.get('severity', ''))}">
              <h3>{html.escape(finding.get('id', ''))}: {html.escape(finding.get('title', ''))}</h3>
              <p><strong>Severity:</strong> {html.escape(finding.get('severity', ''))}
              <strong>Status:</strong> {html.escape(finding.get('status', ''))}
              <strong>Category:</strong> {html.escape(finding.get('category', ''))}</p>
              <p><strong>Selector:</strong> <code>{html.escape(finding.get('selector', ''))}</code></p>
              <p><strong>Expected:</strong> {html.escape(finding.get('expected', ''))}</p>
              <p><strong>Actual:</strong> {html.escape(finding.get('actual', ''))}</p>
              <p><strong>Fix hypothesis:</strong> {html.escape(finding.get('fix_hypothesis', ''))}</p>
              <h4>Signals</h4><ul>{signals}</ul>
              <h4>Reproduction</h4><ol>{steps}</ol>
              <div class="thumbs">{thumbs}</div>
            </section>
            """
        )
    evidence_rows = "".join(
        f"<tr><td>{html.escape(item.get('id', ''))}</td><td>{html.escape(item.get('kind', ''))}</td>"
        f"<td>{html.escape(item.get('condition', ''))}</td><td>{html.escape(item.get('selector', ''))}</td>"
        f"<td>{html.escape(item.get('path', ''))}</td></tr>"
        for item in manifest.get("evidence", [])
    )
    counts_json = json.dumps(severity_counts(manifest))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(manifest.get('title', 'Bug Lab Report'))}</title>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f8fafc; color: #111827; }}
      main {{ width: min(1200px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      h1 {{ margin-bottom: 4px; }}
      .meta, table, .finding {{ background: white; border: 1px solid #d6dbe3; border-radius: 8px; }}
      .meta {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 12px; margin: 16px 0; }}
      .meta div {{ min-width: 0; }}
      code {{ background: #eef2f7; padding: 2px 4px; border-radius: 4px; }}
      table {{ width: 100%; border-collapse: collapse; margin: 16px 0; overflow: hidden; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #eef2f7; }}
      .finding {{ padding: 14px; margin: 14px 0; }}
      .finding.high {{ border-left: 6px solid #dc2626; }}
      .finding.medium {{ border-left: 6px solid #f59e0b; }}
      .finding.low {{ border-left: 6px solid #2563eb; }}
      .thumbs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
      figure {{ margin: 0; }}
      img {{ width: 100%; border: 1px solid #d1d5db; border-radius: 6px; background: white; }}
      figcaption {{ font-size: 12px; color: #4b5563; }}
      @media (max-width: 800px) {{ .meta {{ grid-template-columns: 1fr; }} }}
    </style>
  </head>
  <body>
    <main>
      <h1>{html.escape(manifest.get('title', 'Bug Lab Report'))}</h1>
      <p>{html.escape(manifest.get('summary', ''))}</p>
      <section class="meta">
        <div><strong>Run</strong><br>{html.escape(manifest.get('run_id', ''))}</div>
        <div><strong>Tool</strong><br>{html.escape(manifest.get('tool', ''))}</div>
        <div><strong>Status</strong><br>{html.escape(manifest.get('status', ''))}</div>
        <div><strong>Severity Counts</strong><br><code>{html.escape(counts_json)}</code></div>
      </section>
      <h2>Metrics</h2>
      <table><thead><tr><th>Name</th><th>Value</th><th>Unit</th><th>Description</th></tr></thead><tbody>{metrics_rows}</tbody></table>
      <h2>Findings</h2>
      {''.join(finding_cards) or '<p>No findings.</p>'}
      <h2>Evidence Manifest</h2>
      <table><thead><tr><th>ID</th><th>Kind</th><th>Condition</th><th>Selector</th><th>Path</th></tr></thead><tbody>{evidence_rows}</tbody></table>
    </main>
  </body>
</html>
"""


def write_standard_report(manifest: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "report_manifest.json"
    html_path = output_dir / "report.html"
    add_artifact(manifest, "standard_html_report", html_path, kind="html")
    add_artifact(manifest, "standard_manifest", manifest_path, kind="json")
    write_json(manifest_path, manifest)
    html_path.write_text(render_html(manifest), encoding="utf-8")
    return manifest
