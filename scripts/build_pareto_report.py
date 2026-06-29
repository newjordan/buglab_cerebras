from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from swarm_common import ABLATION_CSV
from swarm_common import ROOT


REPORT_DIR = ROOT / "reports"
REPORT_PATH = REPORT_DIR / "pareto_dashboard.html"
ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"
BROWSER_BENCHMARK_CSV = ROOT / "data" / "browser_benchmarks.csv"
GENERIC_BUG_HUNT_CSV = ROOT / "data" / "generic_bug_hunt_results.csv"


def as_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def score(row: dict[str, str]) -> float:
    return round(
        as_float(row.get("final_score", "")) * 20
        + as_float(row.get("pass_rate_pct", ""))
        - as_float(row.get("failure_count", "")) * 10
        - as_float(row.get("regression_count", "")) * 15
        - as_float(row.get("total_seconds", "")) * 0.05,
        3,
    )


def load_rows() -> list[dict[str, object]]:
    with ABLATION_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = []
    for row in rows:
        item: dict[str, object] = dict(row)
        item["score"] = score(row)
        item["worker_count_num"] = as_float(row.get("worker_count", ""))
        item["loop_count_num"] = as_float(row.get("loop_count", ""))
        item["total_seconds_num"] = as_float(row.get("total_seconds", ""))
        item["failure_count_num"] = as_float(row.get("failure_count", ""))
        item["regression_count_num"] = as_float(row.get("regression_count", ""))
        payload.append(item)
    return payload


def load_browser_rows() -> list[dict[str, object]]:
    if not BROWSER_BENCHMARK_CSV.exists():
        return []
    with BROWSER_BENCHMARK_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = []
    for row in rows:
        item: dict[str, object] = dict(row)
        item["fixture_ready_ms_num"] = as_float(row.get("fixture_ready_ms", ""))
        item["dom_content_loaded_ms_num"] = as_float(row.get("dom_content_loaded_ms", ""))
        item["load_ms_num"] = as_float(row.get("load_ms", ""))
        item["node_count_num"] = as_float(row.get("node_count", ""))
        item["pass_rate_pct_num"] = as_float(row.get("pass_rate_pct", ""))
        item["failure_count_num"] = as_float(row.get("failure_count", ""))
        payload.append(item)
    return payload


def load_generic_bug_rows() -> list[dict[str, object]]:
    if not GENERIC_BUG_HUNT_CSV.exists():
        return []
    with GENERIC_BUG_HUNT_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = []
    for row in rows:
        item: dict[str, object] = dict(row)
        item["controls_discovered_num"] = as_float(row.get("controls_discovered", ""))
        item["controls_exercised_num"] = as_float(row.get("controls_exercised", ""))
        item["click_path_coverage_pct_num"] = as_float(row.get("click_path_coverage_pct", ""))
        item["bug_candidate_count_num"] = as_float(row.get("bug_candidate_count", ""))
        item["fix_verified_delta_num"] = as_float(row.get("fix_verified_delta", ""))
        item["screenshot_count_num"] = as_float(row.get("screenshot_count", ""))
        payload.append(item)
    return payload


def html(
    payload: list[dict[str, object]],
    browser_payload: list[dict[str, object]],
    bug_payload: list[dict[str, object]],
) -> str:
    data_json = json.dumps(payload)
    browser_json = json.dumps(browser_payload)
    bug_json = json.dumps(bug_payload)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Autoswarm Pareto Dashboard</title>
    <script src="{ECHARTS_URL}"></script>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f7f7f4; color: #171717; }}
      main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 40px; }}
      h1 {{ margin: 0 0 6px; font-size: 32px; }}
      p {{ color: #555; }}
      .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
      .chart {{ height: 420px; border: 1px solid #ddd8cc; border-radius: 8px; background: #fff; }}
      table {{ width: 100%; margin-top: 16px; border-collapse: collapse; background: #fff; border: 1px solid #ddd8cc; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #ece8dd; text-align: left; font-size: 13px; }}
      th {{ background: #f0eee8; }}
      @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    </style>
  </head>
  <body>
    <main>
      <h1>Autoswarm Pareto Dashboard</h1>
      <p>Science view only: score, time, worker count, failures, regressions, and frontier candidates.</p>
      <div class="grid">
        <section id="scoreTime" class="chart"></section>
        <section id="scoreWorkers" class="chart"></section>
        <section id="trackBars" class="chart"></section>
        <section id="failures" class="chart"></section>
        <section id="browserSpeed" class="chart"></section>
        <section id="browserPass" class="chart"></section>
        <section id="bugCandidates" class="chart"></section>
        <section id="bugCoverage" class="chart"></section>
      </div>
      <table id="rows"></table>
      <table id="browserRows"></table>
      <table id="bugRows"></table>
    </main>
    <script>
      const rows = {data_json};
      const browserRows = {browser_json};
      const bugRows = {bug_json};
      const tracks = [...new Set(rows.map(r => r.track))];
      const colors = ['#0f766e', '#b45309', '#2563eb', '#7c3aed', '#be123c'];
      const byTrack = Object.fromEntries(tracks.map((t, i) => [t, {{ color: colors[i % colors.length] }}]));

      function scatterData(xKey) {{
        return tracks.map(track => ({{
          name: track,
          type: 'scatter',
          symbolSize: 12,
          data: rows.filter(r => r.track === track).map(r => [
            Number(r[xKey] || 0),
            Number(r.score || 0),
            r.run_id,
            r.topology,
            r.notes
          ])
        }}));
      }}

      function chart(id, option) {{
        const instance = echarts.init(document.getElementById(id));
        instance.setOption(option);
        window.addEventListener('resize', () => instance.resize());
      }}

      chart('scoreTime', {{
        title: {{ text: 'Pareto: Score vs Time' }},
        tooltip: {{ formatter: p => `${{p.data[2]}} ${{p.seriesName}}<br>topology=${{p.data[3]}}<br>time=${{p.data[0]}}s score=${{p.data[1]}}` }},
        xAxis: {{ name: 'total_seconds', type: 'value' }},
        yAxis: {{ name: 'score', type: 'value' }},
        legend: {{ top: 28 }},
        series: scatterData('total_seconds_num')
      }});

      chart('scoreWorkers', {{
        title: {{ text: 'Org Cost: Score vs Workers' }},
        tooltip: {{ formatter: p => `${{p.data[2]}} ${{p.seriesName}}<br>workers=${{p.data[0]}} score=${{p.data[1]}}` }},
        xAxis: {{ name: 'worker_count', type: 'value' }},
        yAxis: {{ name: 'score', type: 'value' }},
        legend: {{ top: 28 }},
        series: scatterData('worker_count_num')
      }});

      const topologies = [...new Set(rows.map(r => r.topology))];
      chart('trackBars', {{
        title: {{ text: 'Average Score By Topology' }},
        tooltip: {{}},
        xAxis: {{ type: 'category', data: topologies, axisLabel: {{ rotate: 25 }} }},
        yAxis: {{ type: 'value' }},
        series: [{{
          type: 'bar',
          data: topologies.map(t => {{
            const items = rows.filter(r => r.topology === t);
            return items.reduce((sum, r) => sum + Number(r.score || 0), 0) / Math.max(1, items.length);
          }})
        }}]
      }});

      chart('failures', {{
        title: {{ text: 'Failures And Regressions' }},
        tooltip: {{}},
        legend: {{ top: 28 }},
        xAxis: {{ type: 'category', data: rows.map(r => r.run_id) }},
        yAxis: {{ type: 'value' }},
        series: [
          {{ name: 'failures', type: 'bar', data: rows.map(r => Number(r.failure_count_num || 0)) }},
          {{ name: 'regressions', type: 'bar', data: rows.map(r => Number(r.regression_count_num || 0)) }}
        ]
      }});

      const speedRows = browserRows.filter(r => r.track === 'speed_fleet');
      chart('browserSpeed', {{
        title: {{ text: 'Browser Metric: Fixture Ready Time' }},
        tooltip: {{ formatter: p => `${{p.name}}<br>${{p.value}} ms` }},
        xAxis: {{ type: 'category', data: speedRows.map(r => r.candidate) }},
        yAxis: {{ name: 'ms', type: 'value' }},
        series: [{{
          type: 'bar',
          data: speedRows.map(r => Number(r.fixture_ready_ms_num || 0)),
          itemStyle: {{ color: '#0f766e' }}
        }}]
      }});

      const playRows = browserRows.filter(r => r.track === 'playthrough_debug');
      chart('browserPass', {{
        title: {{ text: 'Browser Metric: Playthrough Pass Rate' }},
        tooltip: {{ formatter: p => `${{p.name}}<br>${{p.value}}%` }},
        xAxis: {{ type: 'category', data: playRows.map(r => r.candidate) }},
        yAxis: {{ name: 'pass_rate_pct', type: 'value', max: 100 }},
        series: [{{
          type: 'bar',
          data: playRows.map(r => Number(r.pass_rate_pct_num || 0)),
          itemStyle: {{ color: '#2563eb' }}
        }}]
      }});

      chart('bugCandidates', {{
        title: {{ text: 'Generic Bug Hunt: Candidate Bugs' }},
        tooltip: {{ formatter: p => `${{p.name}}<br>${{p.value}} bug candidates` }},
        xAxis: {{ type: 'category', data: bugRows.map(r => r.candidate) }},
        yAxis: {{ name: 'bug_candidate_count', type: 'value' }},
        series: [{{
          type: 'bar',
          data: bugRows.map(r => Number(r.bug_candidate_count_num || 0)),
          itemStyle: {{ color: '#be123c' }}
        }}]
      }});

      chart('bugCoverage', {{
        title: {{ text: 'Generic Bug Hunt: Click Coverage' }},
        tooltip: {{ formatter: p => `${{p.name}}<br>${{p.value}}% coverage` }},
        xAxis: {{ type: 'category', data: bugRows.map(r => r.candidate) }},
        yAxis: {{ name: 'click_path_coverage_pct', type: 'value', max: 100 }},
        series: [{{
          type: 'bar',
          data: bugRows.map(r => Number(r.click_path_coverage_pct_num || 0)),
          itemStyle: {{ color: '#7c3aed' }}
        }}]
      }});

      document.getElementById('rows').innerHTML = `
        <thead><tr><th>Run</th><th>Track</th><th>Topology</th><th>Workers</th><th>Score</th><th>Time</th><th>Keep</th><th>Notes</th></tr></thead>
        <tbody>${{rows.map(r => `<tr><td>${{r.run_id}}</td><td>${{r.track}}</td><td>${{r.topology}}</td><td>${{r.worker_count}}</td><td>${{r.score}}</td><td>${{r.total_seconds || ''}}</td><td>${{r.pareto_keep}}</td><td>${{r.notes}}</td></tr>`).join('')}}</tbody>
      `;
      document.getElementById('browserRows').innerHTML = `
        <thead><tr><th>Run</th><th>Track</th><th>Candidate</th><th>Ready ms</th><th>DCL ms</th><th>Load ms</th><th>Pass %</th><th>Failures</th><th>Notes</th></tr></thead>
        <tbody>${{browserRows.map(r => `<tr><td>${{r.run_id}}</td><td>${{r.track}}</td><td>${{r.candidate}}</td><td>${{r.fixture_ready_ms || ''}}</td><td>${{r.dom_content_loaded_ms}}</td><td>${{r.load_ms}}</td><td>${{r.pass_rate_pct || ''}}</td><td>${{r.failure_count}}</td><td>${{r.notes}}</td></tr>`).join('')}}</tbody>
      `;
      document.getElementById('bugRows').innerHTML = `
        <thead><tr><th>Run</th><th>Target</th><th>Candidate</th><th>Controls</th><th>Exercised</th><th>Coverage %</th><th>Bugs</th><th>Fix Delta</th><th>Screenshots</th><th>Notes</th></tr></thead>
        <tbody>${{bugRows.map(r => `<tr><td>${{r.run_id}}</td><td>${{r.target}}</td><td>${{r.candidate}}</td><td>${{r.controls_discovered}}</td><td>${{r.controls_exercised}}</td><td>${{r.click_path_coverage_pct}}</td><td>${{r.bug_candidate_count}}</td><td>${{r.fix_verified_delta || ''}}</td><td>${{r.screenshot_count}}</td><td>${{r.notes}}</td></tr>`).join('')}}</tbody>
      `;
    </script>
  </body>
</html>
"""


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html(load_rows(), load_browser_rows(), load_generic_bug_rows()), encoding="utf-8")
    print(REPORT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
