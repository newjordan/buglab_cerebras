from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any


def build_findings_pareto(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    top: int = 20,
) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    output_root = (repo_path / output).resolve() if not Path(output).is_absolute() else Path(output).resolve()
    records = collect_findings(output_root)
    summary = summarize_findings(records, top=top)
    csv_path = output_root / "findings_pareto.csv"
    json_path = output_root / "findings_pareto.json"
    html_path = output_root / "findings_pareto.html"
    output_root.mkdir(parents=True, exist_ok=True)
    write_pareto_csv(csv_path, summary)
    payload = {
        "schema_version": "buglab.findings_pareto.v1",
        "repo": str(repo_path),
        "output_root": str(output_root),
        "summary": summary,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path.write_text(render_pareto_html(payload), encoding="utf-8")
    return {
        "summary": summary,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "html_path": str(html_path),
    }


def collect_findings(output_root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(output_root.glob("*/findings.jsonl")):
        run_id = path.parent.name
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                findings.append(
                    {
                        "run_id": run_id,
                        "finding_id": f"{run_id}:{line_number}",
                        "severity": "unknown",
                        "sector": "unknown",
                        "signals": [f"invalid_findings_jsonl:line={line_number}"],
                    }
                )
                continue
            if isinstance(record, dict):
                hydrated = dict(record)
                hydrated["run_id"] = run_id
                findings.append(hydrated)
    return findings


def summarize_findings(records: list[dict[str, Any]], *, top: int) -> dict[str, Any]:
    signal_counts: Counter[str] = Counter()
    sector_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    run_counts: Counter[str] = Counter()
    sector_signal_counts: Counter[str] = Counter()
    case_paths = []
    for record in records:
        sector = str(record.get("sector") or "unknown")
        severity = str(record.get("severity") or "unknown")
        run_id = str(record.get("run_id") or "unknown")
        sector_counts[sector] += 1
        severity_counts[severity] += 1
        run_counts[run_id] += 1
        if record.get("case_path"):
            case_paths.append(str(record["case_path"]))
        for signal in record_signals(record):
            family = signal_family(signal)
            signal_counts[family] += 1
            sector_signal_counts[f"{sector}:{family}"] += 1
    return {
        "runs": len(run_counts),
        "findings": len(records),
        "case_paths": len(case_paths),
        "sectors": ranked_counts(sector_counts, top=top),
        "severities": ranked_counts(severity_counts, top=top),
        "runs_ranked": ranked_counts(run_counts, top=top),
        "signals": pareto_rows(signal_counts, top=top),
        "sector_signals": pareto_rows(sector_signal_counts, top=top),
    }


def record_signals(record: dict[str, Any]) -> list[str]:
    signals = record.get("signals", [])
    if isinstance(signals, str):
        try:
            parsed = json.loads(signals)
        except json.JSONDecodeError:
            return [signals]
        signals = parsed
    if not isinstance(signals, list):
        return []
    return [str(signal) for signal in signals if str(signal)]


def signal_family(signal: str) -> str:
    family = signal.split(":", 1)[0]
    return family.strip() or "unknown"


def ranked_counts(counter: Counter[str], *, top: int) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(top)]


def pareto_rows(counter: Counter[str], *, top: int) -> list[dict[str, Any]]:
    total = sum(counter.values())
    cumulative = 0
    rows = []
    for name, count in counter.most_common(top):
        cumulative += count
        cumulative_pct = round(cumulative / total, 4) if total else 0
        rows.append(
            {
                "name": name,
                "count": count,
                "pct": round(count / total, 4) if total else 0,
                "cumulative_pct": cumulative_pct,
                "pareto_keep": "yes" if cumulative_pct <= 0.8 else "maybe" if cumulative_pct <= 0.9 else "no",
            }
        )
    return rows


def write_pareto_csv(path: Path, summary: dict[str, Any]) -> None:
    fieldnames = ["kind", "name", "count", "pct", "cumulative_pct", "pareto_keep"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for kind in ["sectors", "severities", "runs_ranked"]:
            for row in summary.get(kind, []):
                writer.writerow(
                    {
                        "kind": kind,
                        "name": row["name"],
                        "count": row["count"],
                        "pct": "",
                        "cumulative_pct": "",
                        "pareto_keep": "",
                    }
                )
        for kind in ["signals", "sector_signals"]:
            for row in summary.get(kind, []):
                writer.writerow({"kind": kind, **row})


def render_pareto_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    chart_payload = json.dumps(summary)
    signal_rows = table_rows(summary.get("signals", []), include_pct=True)
    sector_rows = table_rows(summary.get("sectors", []), include_pct=False)
    sector_signal_rows = table_rows(summary.get("sector_signals", []), include_pct=True)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BugLab Findings Pareto</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f8fafc; color: #111827; }}
      main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
      .metric, table, .chart {{ background: white; border: 1px solid #d6dbe3; border-radius: 8px; }}
      .metric {{ padding: 12px; }}
      .metric strong {{ display: block; font-size: 24px; }}
      .chart {{ height: 360px; margin: 16px 0 28px; }}
      table {{ width: 100%; border-collapse: collapse; overflow: hidden; margin: 16px 0 28px; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; }}
      th {{ background: #eef2f7; }}
      @media (max-width: 800px) {{ .metrics {{ grid-template-columns: 1fr 1fr; }} }}
    </style>
  </head>
  <body>
    <main>
      <h1>BugLab Findings Pareto</h1>
      <p>Ranked bug-hunt signal concentration across normalized repo-audit findings.</p>
      <section class="metrics">
        <div class="metric"><strong>{summary.get('runs', 0)}</strong>Runs</div>
        <div class="metric"><strong>{summary.get('findings', 0)}</strong>Findings</div>
        <div class="metric"><strong>{summary.get('case_paths', 0)}</strong>Case Bundles</div>
        <div class="metric"><strong>{len(summary.get('signals', []))}</strong>Signal Families</div>
      </section>
      <section id="signals" class="chart"></section>
      <section id="sectorSignals" class="chart"></section>
      <h2>Top Signal Families</h2>
      <table><thead><tr><th>Name</th><th>Count</th><th>Share</th><th>Cumulative</th><th>Pareto</th></tr></thead><tbody>{signal_rows}</tbody></table>
      <h2>Sectors</h2>
      <table><thead><tr><th>Name</th><th>Count</th></tr></thead><tbody>{sector_rows}</tbody></table>
      <h2>Sector x Signal</h2>
      <table><thead><tr><th>Name</th><th>Count</th><th>Share</th><th>Cumulative</th><th>Pareto</th></tr></thead><tbody>{sector_signal_rows}</tbody></table>
    </main>
    <script>
      const data = {chart_payload};
      function draw(id, rows, title) {{
        const el = document.getElementById(id);
        if (!window.echarts || !el) return;
        const chart = echarts.init(el);
        chart.setOption({{
          title: {{ text: title, left: 12, top: 10 }},
          tooltip: {{ trigger: 'axis' }},
          grid: {{ left: 120, right: 50, top: 60, bottom: 30 }},
          xAxis: [
            {{ type: 'value', name: 'count' }},
            {{ type: 'value', name: 'cumulative %', min: 0, max: 100, position: 'top' }}
          ],
          yAxis: {{ type: 'category', data: rows.map(r => r.name).reverse(), axisLabel: {{ interval: 0 }} }},
          series: [
            {{ type: 'bar', name: 'count', data: rows.map(r => r.count).reverse(), itemStyle: {{ color: '#2563eb' }} }},
            {{ type: 'line', name: 'cumulative %', xAxisIndex: 1, data: rows.map(r => Math.round((r.cumulative_pct || 0) * 100)).reverse(), itemStyle: {{ color: '#dc2626' }} }}
          ]
        }});
        window.addEventListener('resize', () => chart.resize());
      }}
      draw('signals', data.signals || [], 'Signal Family Pareto');
      draw('sectorSignals', data.sector_signals || [], 'Sector x Signal Pareto');
    </script>
  </body>
</html>
"""


def table_rows(rows: list[dict[str, Any]], *, include_pct: bool) -> str:
    if not rows:
        colspan = 5 if include_pct else 2
        return f"<tr><td colspan='{colspan}'>No rows.</td></tr>"
    rendered = []
    for row in rows:
        if include_pct:
            rendered.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('name', '')))}</td>"
                f"<td>{html.escape(str(row.get('count', '')))}</td>"
                f"<td>{float(row.get('pct', 0)):.1%}</td>"
                f"<td>{float(row.get('cumulative_pct', 0)):.1%}</td>"
                f"<td>{html.escape(str(row.get('pareto_keep', '')))}</td>"
                "</tr>"
            )
        else:
            rendered.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('name', '')))}</td>"
                f"<td>{html.escape(str(row.get('count', '')))}</td>"
                "</tr>"
            )
    return "".join(rendered)
