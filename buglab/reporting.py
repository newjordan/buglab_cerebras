from __future__ import annotations

import html
import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from buglab.truth import synthesize_report_truth_ledger
from buglab.truth import write_truth_ledger


SCHEMA_VERSION = "buglab.report.v1"


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    path: str = ""
    label: str = ""
    description: str = ""
    condition: str = ""
    selector: str = ""
    action: str = ""
    viewport: dict[str, int] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class Finding:
    id: str
    title: str
    severity: str
    status: str
    category: str
    signals: list[str]
    evidence_ids: list[str]
    selector: str = ""
    reproduction_steps: list[str] | None = None
    command: str = ""
    artifact: str = ""
    expected: str = ""
    actual: str = ""
    fix_hypothesis: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def normalize_path(path: str | Path, base_dir: Path) -> str:
    path_obj = Path(path)
    try:
        return path_obj.resolve().relative_to(base_dir.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class ReportBuilder:
    def __init__(
        self,
        *,
        run_id: str,
        tool: str,
        target: str,
        output_dir: Path,
        base_dir: Path,
        title: str = "",
        summary: str = "",
        status: str = "unknown",
    ) -> None:
        self.output_dir = output_dir
        self.base_dir = base_dir
        self.manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "tool": tool,
            "target": target.replace("\\", "/"),
            "title": title or f"{tool}: {target}",
            "status": status,
            "summary": summary,
            "created_at_utc": utc_now(),
            "output_dir": normalize_path(output_dir, base_dir),
            "metrics": {},
            "evidence": [],
            "findings": [],
            "truth_ledger": {},
            "artifacts": {},
        }
        self.truth_entries: list[dict[str, Any]] = []

    def metric(self, name: str, value: Any, *, unit: str = "", description: str = "") -> None:
        self.manifest["metrics"][name] = {"value": value, "unit": unit, "description": description}

    def artifact(self, name: str, path: str | Path, *, kind: str = "file") -> None:
        self.manifest["artifacts"][name] = {"kind": kind, "path": normalize_path(path, self.base_dir)}

    def evidence(self, evidence: Evidence) -> None:
        item = asdict(evidence)
        item["path"] = normalize_path(item["path"], self.base_dir) if item["path"] else ""
        item["viewport"] = item["viewport"] or {}
        item["metadata"] = item["metadata"] or {}
        self.manifest["evidence"].append(item)

    def finding(self, finding: Finding) -> None:
        item = asdict(finding)
        item["reproduction_steps"] = item["reproduction_steps"] or []
        self.manifest["findings"].append(item)

    def truth_entry(self, entry: dict[str, Any]) -> None:
        self.truth_entries.append(entry)

    def write(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.output_dir / "report_manifest.json"
        html_path = self.output_dir / "report.html"
        truth_path = self.output_dir / "truth_ledger.json"
        self.artifact("standard_html_report", html_path, kind="html")
        self.artifact("standard_manifest", manifest_path, kind="json")
        self.artifact("truth_ledger", truth_path, kind="json")
        self.artifact("truth_ledger_jsonl", truth_path.with_suffix(".jsonl"), kind="jsonl")
        if self.truth_entries:
            truth_payload = write_truth_ledger(truth_path, self.truth_entries, run_id=str(self.manifest["run_id"]))
        else:
            synthesized = synthesize_report_truth_ledger(self.manifest)
            truth_payload = write_truth_ledger(
                truth_path,
                synthesized["entries"],
                run_id=str(self.manifest["run_id"]),
                summary=synthesized["summary"],
            )
        self.manifest["truth_ledger"] = truth_payload
        write_json(manifest_path, self.manifest)
        html_path.write_text(render_html(self.manifest, self.output_dir), encoding="utf-8")
        return self.manifest


def severity_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in manifest.get("findings", []):
        severity = finding.get("severity", "unknown")
        counts[severity] = counts.get(severity, 0) + 1
    return dict(sorted(counts.items()))


def render_html(manifest: dict[str, Any], output_dir: Path) -> str:
    evidence_by_id = {item["id"]: item for item in manifest.get("evidence", [])}
    truth = manifest.get("truth_ledger", {}) if isinstance(manifest.get("truth_ledger", {}), dict) else {}
    truth_summary = truth.get("summary", {}) if isinstance(truth.get("summary", {}), dict) else {}
    truth_entries = truth.get("entries", []) if isinstance(truth.get("entries", []), list) else []
    metrics_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(item.get('value', '')))}</td>"
        f"<td>{html.escape(item.get('unit', ''))}</td><td>{html.escape(item.get('description', ''))}</td></tr>"
        for name, item in manifest.get("metrics", {}).items()
    )
    truth_metric_cards = "".join(
        f"<div class='truth-metric'><strong>{html.escape(str(truth_summary.get(key, 'n/a')))}</strong><span>{html.escape(label)}</span></div>"
        for key, label in [
            ("confirmed", "confirmed"),
            ("suspected", "suspected"),
            ("false_positive", "false positive"),
            ("false_negative", "false negative"),
            ("precision", "precision"),
            ("recall", "recall"),
        ]
    )
    truth_cards = []
    for entry in truth_entries[:24]:
        evidence = entry.get("evidence", {}) if isinstance(entry.get("evidence", {}), dict) else {}
        oracle = entry.get("oracle", {}) if isinstance(entry.get("oracle", {}), dict) else {}
        steps = evidence.get("reproduction_steps", []) if isinstance(evidence.get("reproduction_steps", []), list) else []
        signals = evidence.get("signals", []) if isinstance(evidence.get("signals", []), list) else []
        step_items = "".join(f"<li>{html.escape(str(step))}</li>" for step in steps[:6])
        signal_items = "".join(f"<li>{html.escape(str(signal))}</li>" for signal in signals[:6])
        truth_cards.append(
            f"""
            <section class="truth-card {html.escape(str(entry.get('status', '')))}">
              <div class="truth-card-top">
                <strong>{html.escape(str(entry.get('finding_id', '')))}</strong>
                <span>{html.escape(str(entry.get('status', 'unknown')))}</span>
              </div>
              <h3>{html.escape(str(entry.get('claim', '')))}</h3>
              <p><strong>Outcome:</strong> {html.escape(str(entry.get('outcome', 'unscored')))}
              <strong>Confidence:</strong> {html.escape(str(entry.get('confidence', '')))}</p>
              <p><strong>Oracle:</strong> {html.escape(str(oracle.get('type', 'none')))}
              / {html.escape(str(oracle.get('verdict', 'unverified')))}</p>
              <h4>Reproduction</h4><ol>{step_items or '<li>No reproduction steps attached.</li>'}</ol>
              <h4>Signals</h4><ul>{signal_items or '<li>No signals attached.</li>'}</ul>
            </section>
            """
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
      .meta, table, .finding {{ background: white; border: 1px solid #d6dbe3; border-radius: 8px; }}
      .meta {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 12px; margin: 16px 0; }}
      code {{ background: #eef2f7; padding: 2px 4px; border-radius: 4px; }}
      table {{ width: 100%; border-collapse: collapse; margin: 16px 0; overflow: hidden; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #eef2f7; }}
      .finding {{ padding: 14px; margin: 14px 0; }}
      .finding.critical, .finding.high {{ border-left: 6px solid #dc2626; }}
      .finding.medium {{ border-left: 6px solid #f59e0b; }}
      .finding.low, .finding.info {{ border-left: 6px solid #2563eb; }}
      .truth-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin: 16px 0; }}
      .truth-metric {{ background: #08130a; color: #d9ffe0; border-top: 3px solid #16a34a; padding: 10px; }}
      .truth-metric strong {{ display: block; font-size: 24px; }}
      .truth-metric span {{ color: #86efac; font-size: 12px; text-transform: uppercase; }}
      .truth-card {{ background: white; border: 1px solid #d6dbe3; border-left: 6px solid #6b7280; border-radius: 8px; padding: 14px; margin: 12px 0; }}
      .truth-card.confirmed, .truth-card.fixed {{ border-left-color: #16a34a; }}
      .truth-card.false_positive, .truth-card.false_negative {{ border-left-color: #dc2626; }}
      .truth-card.clean {{ border-left-color: #2563eb; }}
      .truth-card-top {{ display: flex; justify-content: space-between; gap: 12px; color: #166534; text-transform: uppercase; font-size: 12px; }}
      .thumbs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
      figure {{ margin: 0; }}
      img {{ width: 100%; border: 1px solid #d1d5db; border-radius: 6px; background: white; }}
      figcaption {{ font-size: 12px; color: #4b5563; }}
      @media (max-width: 800px) {{ .meta, .truth-grid {{ grid-template-columns: 1fr; }} }}
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
      <h2>Truth Ledger</h2>
      <section class="truth-grid">{truth_metric_cards}</section>
      {''.join(truth_cards) or '<p>No truth ledger entries.</p>'}
      <h2>Findings</h2>
      {''.join(finding_cards) or '<p>No findings.</p>'}
      <h2>Evidence Manifest</h2>
      <table><thead><tr><th>ID</th><th>Kind</th><th>Condition</th><th>Selector</th><th>Path</th></tr></thead><tbody>{evidence_rows}</tbody></table>
    </main>
  </body>
</html>
"""
