from __future__ import annotations

import csv
import html
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.reporting import write_json
from buglab.swarm import DEFAULT_FIELD_MANIFESTS
from buglab.swarm import SwarmRunConfig
from buglab.swarm import run_swarm
from buglab.sectors import safe_slug


@dataclass(frozen=True)
class SwarmAblationConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    fields: list[str] | None = None
    manifests: list[str] | None = None
    profile_sets: list[str] | None = None
    loops: int = 1
    repeats: int = 1
    max_clicks: int = 16
    run_name: str = "swarm_ablation"
    repair: bool = False
    build_report_index: bool = True


def run_swarm_ablation(config: SwarmAblationConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    if config is None:
        config = SwarmAblationConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    variants = variant_specs(config.fields, config.manifests)
    profile_sets = config.profile_sets or ["balanced", "business", "edge", "balanced,business,edge"]
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()

    for field, fields, manifests in variants:
        for profile_set in profile_sets:
            profiles = parse_profile_set(profile_set)
            for repeat in range(1, max(1, config.repeats) + 1):
                variant_id = variant_name(config.run_name, field, profiles, repeat)
                result = run_swarm(
                    SwarmRunConfig(
                        repo=repo,
                        output=output_root,
                        fields=fields,
                        manifests=manifests,
                        loops=config.loops,
                        profiles=profiles,
                        max_clicks=config.max_clicks,
                        run_name=variant_id,
                        repair=config.repair,
                        build_report_index=False,
                    )
                )
                rows.append(ablation_row(field, profiles, repeat, config, variant_id, result))

    rows = annotate_pareto(rows)
    summary = summarize_ablation_rows(rows, round((time.perf_counter() - started) * 1000))
    csv_path = output_root / f"{config.run_name}_ablation_summary.csv"
    json_path = output_root / f"{config.run_name}_ablation_summary.json"
    html_path = output_root / f"{config.run_name}_ablation_summary.html"
    write_ablation_csv(csv_path, rows)
    payload = {
        "schema_version": "buglab.swarm_ablation.v1",
        "repo": str(repo),
        "output_root": str(output_root),
        "summary": summary,
        "rows": rows,
    }
    write_json(json_path, payload)
    html_path.write_text(render_ablation_html(payload), encoding="utf-8")

    index = None
    if config.build_report_index:
        from buglab.api import build_index

        index = build_index(repo=repo, output=output_root)
    return {
        "summary": summary,
        "rows": rows,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "index": index,
    }


def parse_profile_set(value: str) -> list[str]:
    profiles = [item.strip() for item in value.split(",") if item.strip()]
    return profiles or ["balanced"]


def variant_specs(fields: list[str] | None, manifests: list[str] | None) -> list[tuple[str, list[str] | None, list[str] | None]]:
    specs: list[tuple[str, list[str] | None, list[str] | None]] = []
    selected_fields = fields or ([] if manifests else list(DEFAULT_FIELD_MANIFESTS))
    for field in selected_fields:
        if field not in DEFAULT_FIELD_MANIFESTS:
            raise ValueError(f"Unknown field '{field}'. Known fields: {', '.join(DEFAULT_FIELD_MANIFESTS)}")
        specs.append((field, [field], None))
    for manifest in manifests or []:
        manifest_path = Path(manifest)
        label_source = manifest_path.parent.name if manifest_path.stem == "manifest" else manifest_path.stem
        label = f"manifest_{safe_slug(label_source)}"
        specs.append((label, None, [manifest]))
    if not specs:
        specs.append(("all_fields", None, None))
    return specs


def variant_name(run_name: str, field: str, profiles: list[str], repeat: int) -> str:
    return f"{run_name}_{safe_slug(field)}_{safe_slug('_'.join(profiles))}_r{repeat:02d}"


def ablation_row(
    field: str,
    profiles: list[str],
    repeat: int,
    config: SwarmAblationConfig,
    variant_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    summary = result.get("summary", {})
    fixtures = int(summary.get("fixtures", 0))
    unique_signals = int(summary.get("total_unique_signals", 0))
    elapsed_ms = int(summary.get("elapsed_ms", 0))
    sector_pass_rate = float(summary.get("sector_pass_rate", 0))
    class_recall = float(summary.get("avg_expected_class_recall", 0))
    repair_attempts = int(summary.get("repair_attempts", 0))
    repair_pass_rate = float(summary.get("repair_pass_rate", 0))
    signal_density = min(1.0, unique_signals / max(1, fixtures * 5))
    if repair_attempts:
        quality_score = (sector_pass_rate * 0.32) + (class_recall * 0.32) + (signal_density * 0.16) + (repair_pass_rate * 0.20)
    else:
        quality_score = (sector_pass_rate * 0.42) + (class_recall * 0.42) + (signal_density * 0.16)
    cost_seconds = max(0.001, elapsed_ms / 1000)
    efficiency_score = quality_score / cost_seconds
    return {
        "variant_id": variant_id,
        "field": field,
        "profiles": ",".join(profiles),
        "repeat": repeat,
        "loops": config.loops,
        "repair": str(bool(config.repair)).lower(),
        "status": "passed" if sector_pass_rate >= 1 else "failed",
        "sectors": int(summary.get("sectors", 0)),
        "fixtures": fixtures,
        "runs": int(summary.get("runs", 0)),
        "passed_sectors": int(summary.get("passed_sectors", 0)),
        "sector_pass_rate": round(sector_pass_rate, 4),
        "avg_expected_class_recall": round(class_recall, 4),
        "total_unique_signals": unique_signals,
        "signal_density": round(signal_density, 4),
        "repair_attempts": repair_attempts,
        "repair_pass_rate": round(repair_pass_rate, 4),
        "elapsed_ms": elapsed_ms,
        "quality_score": round(quality_score, 4),
        "efficiency_score": round(efficiency_score, 6),
        "pareto_keep": "",
        "csv_path": result.get("csv_path", ""),
        "json_path": result.get("json_path", ""),
        "html_path": result.get("html_path", ""),
    }


def annotate_pareto(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        dominated = False
        for other in rows:
            if other is row:
                continue
            at_least_as_good = (
                float(other["quality_score"]) >= float(row["quality_score"])
                and float(other["avg_expected_class_recall"]) >= float(row["avg_expected_class_recall"])
                and int(other["total_unique_signals"]) >= int(row["total_unique_signals"])
                and int(other["elapsed_ms"]) <= int(row["elapsed_ms"])
            )
            strictly_better = (
                float(other["quality_score"]) > float(row["quality_score"])
                or float(other["avg_expected_class_recall"]) > float(row["avg_expected_class_recall"])
                or int(other["total_unique_signals"]) > int(row["total_unique_signals"])
                or int(other["elapsed_ms"]) < int(row["elapsed_ms"])
            )
            if at_least_as_good and strictly_better:
                dominated = True
                break
        row["pareto_keep"] = "no" if dominated else "yes"
    if rows and not any(row["pareto_keep"] == "yes" for row in rows):
        best = max(rows, key=lambda item: float(item["efficiency_score"]))
        best["pareto_keep"] = "yes"
    return rows


def summarize_ablation_rows(rows: list[dict[str, Any]], elapsed_ms: int) -> dict[str, Any]:
    if not rows:
        return {
            "variants": 0,
            "pareto_variants": 0,
            "elapsed_ms": elapsed_ms,
        }
    best_quality = max(rows, key=lambda item: float(item["quality_score"]))
    best_efficiency = max(rows, key=lambda item: float(item["efficiency_score"]))
    return {
        "variants": len(rows),
        "fields": len({row["field"] for row in rows}),
        "profile_sets": len({row["profiles"] for row in rows}),
        "pareto_variants": sum(1 for row in rows if row["pareto_keep"] == "yes"),
        "passed_variants": sum(1 for row in rows if row["status"] == "passed"),
        "avg_quality_score": round(sum(float(row["quality_score"]) for row in rows) / len(rows), 4),
        "avg_efficiency_score": round(sum(float(row["efficiency_score"]) for row in rows) / len(rows), 6),
        "total_unique_signals": sum(int(row["total_unique_signals"]) for row in rows),
        "best_quality_variant": best_quality["variant_id"],
        "best_quality_score": best_quality["quality_score"],
        "best_efficiency_variant": best_efficiency["variant_id"],
        "best_efficiency_score": best_efficiency["efficiency_score"],
        "elapsed_ms": elapsed_ms,
    }


def write_ablation_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def render_ablation_html(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    rows = payload.get("rows", [])
    chart_payload = json.dumps(rows)
    table = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['pareto_keep']))}</td>"
        f"<td>{html.escape(str(row['field']))}</td>"
        f"<td>{html.escape(str(row['profiles']))}</td>"
        f"<td>{html.escape(str(row['sector_pass_rate']))}</td>"
        f"<td>{html.escape(str(row['avg_expected_class_recall']))}</td>"
        f"<td>{html.escape(str(row['total_unique_signals']))}</td>"
        f"<td>{html.escape(str(row['elapsed_ms']))}</td>"
        f"<td>{html.escape(str(row['quality_score']))}</td>"
        f"<td>{html.escape(str(row['efficiency_score']))}</td>"
        f"<td>{artifact_link(row.get('html_path', ''))}</td>"
        "</tr>"
        for row in sorted(rows, key=lambda item: (item["pareto_keep"] != "yes", -float(item["quality_score"])))
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BugLab Swarm Ablation</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f8fafc; color: #111827; }}
      main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 16px 0 24px; }}
      .metric, table, .chart {{ background: white; border: 1px solid #d6dbe3; border-radius: 8px; }}
      .metric {{ padding: 12px; }}
      .metric strong {{ display: block; font-size: 24px; }}
      .chart {{ height: 380px; margin: 16px 0 28px; }}
      table {{ width: 100%; border-collapse: collapse; overflow: hidden; margin: 16px 0 28px; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #eef2f7; }}
      a {{ color: #2563eb; }}
    </style>
  </head>
  <body>
    <main>
      <h1>BugLab Swarm Ablation</h1>
      <p>Technique variants ranked by detection quality, expected-class recall, unique-signal yield, and runtime cost.</p>
      <section class="metrics">
        <div class="metric"><strong>{summary.get('variants', 0)}</strong>Variants</div>
        <div class="metric"><strong>{summary.get('pareto_variants', 0)}</strong>Pareto Keep</div>
        <div class="metric"><strong>{summary.get('total_unique_signals', 0)}</strong>Unique Signals</div>
        <div class="metric"><strong>{summary.get('avg_quality_score', 0)}</strong>Avg Quality</div>
        <div class="metric"><strong>{summary.get('avg_efficiency_score', 0)}</strong>Avg Efficiency</div>
      </section>
      <section id="quality" class="chart"></section>
      <section id="efficiency" class="chart"></section>
      <table>
        <thead><tr><th>Pareto</th><th>Field</th><th>Profiles</th><th>Pass</th><th>Class Recall</th><th>Signals</th><th>ms</th><th>Quality</th><th>Efficiency</th><th>Report</th></tr></thead>
        <tbody>{table or '<tr><td colspan="10">No variants.</td></tr>'}</tbody>
      </table>
    </main>
    <script>
      const rows = {chart_payload};
      function drawBar(id, metric, title) {{
        const el = document.getElementById(id);
        if (!window.echarts || !el) return;
        const ordered = [...rows].sort((a, b) => Number(b[metric]) - Number(a[metric])).slice(0, 20);
        const chart = echarts.init(el);
        chart.setOption({{
          title: {{ text: title, left: 12, top: 10 }},
          tooltip: {{ trigger: 'axis' }},
          grid: {{ left: 220, right: 40, top: 60, bottom: 30 }},
          xAxis: {{ type: 'value' }},
          yAxis: {{ type: 'category', data: ordered.map(r => `${{r.field}} | ${{r.profiles}}`).reverse(), axisLabel: {{ interval: 0 }} }},
          series: [{{
            type: 'bar',
            data: ordered.map(r => Number(r[metric])).reverse(),
            itemStyle: {{ color: '#2563eb' }}
          }}]
        }});
        window.addEventListener('resize', () => chart.resize());
      }}
      drawBar('quality', 'quality_score', 'Quality Score');
      drawBar('efficiency', 'efficiency_score', 'Efficiency Score');
    </script>
  </body>
</html>
"""


def artifact_link(path: str) -> str:
    if not path:
        return ""
    escaped = html.escape(path)
    return f"<a href='{escaped}'>{html.escape(Path(path).name)}</a>"
