from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from browser_verify import file_url
from browser_verify import run_tasks
from swarm_common import ROOT
from swarm_common import read_json


BENCHMARKS = [
    {
        "run_id": "E001",
        "track": "speed_fleet",
        "candidate": "baseline",
        "target": "targets/speed_fleet/bloated_dashboard.html",
        "tasks": "",
        "notes": "Bloated dashboard baseline measured by Playwright replicates.",
    },
    {
        "run_id": "E002",
        "track": "speed_fleet",
        "candidate": "optimized",
        "target": "targets/speed_fleet/optimized_dashboard.html",
        "tasks": "",
        "notes": "DocumentFragment plus fast cached formatter candidate.",
    },
    {
        "run_id": "E003",
        "track": "playthrough_debug",
        "candidate": "buggy",
        "target": "targets/playthrough_debug/buggy_dashboard.html",
        "tasks": "targets/playthrough_debug/tasks.json",
        "notes": "Buggy fixture baseline measured by Playwright task replicates.",
    },
    {
        "run_id": "E004",
        "track": "playthrough_debug",
        "candidate": "fixed",
        "target": "targets/playthrough_debug/fixed_dashboard.html",
        "tasks": "targets/playthrough_debug/tasks.json",
        "notes": "Fixed dashboard candidate measured by Playwright task replicates.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repeated browser benchmarks and write summary CSVs.")
    parser.add_argument("--repeats", type=int, default=10)
    return parser.parse_args()


def metric_summary(values: list[float | None]) -> tuple[str, str]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return "", ""
    mean = statistics.fmean(clean)
    std = statistics.pstdev(clean) if len(clean) > 1 else 0.0
    return f"{mean:.2f}", f"{std:.2f}"


def measure_once(page, target: Path, tasks_path: str) -> dict[str, Any]:
    page.goto(file_url(target), wait_until="load")
    metrics = page.evaluate(
        """() => {
          const nav = performance.getEntriesByType('navigation')[0];
          const fixtureReadyMs = window.__fixtureReadyAt && window.__fixtureStart
            ? Math.round(window.__fixtureReadyAt - window.__fixtureStart)
            : null;
          return {
            domContentLoadedMs: Math.round(nav.domContentLoadedEventEnd),
            loadMs: Math.round(nav.loadEventEnd),
            fixtureReadyMs,
            nodeCount: document.querySelectorAll('*').length
          };
        }"""
    )
    task_results = run_tasks(page, read_json(ROOT / tasks_path)) if tasks_path else []
    pass_count = sum(1 for item in task_results if item["ok"])
    pass_rate = round((pass_count / len(task_results)) * 100, 1) if task_results else None
    return {
        **metrics,
        "passRatePct": pass_rate,
        "failureCount": sum(len(item["failures"]) for item in task_results),
    }


def main() -> int:
    args = parse_args()
    temp_dir = ROOT / "tmp" / "playwright"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)

    replicate_rows = []
    summary_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        for bench in BENCHMARKS:
            measurements = []
            for index in range(args.repeats):
                measurement = measure_once(page, ROOT / bench["target"], bench["tasks"])
                measurements.append(measurement)
                replicate_rows.append(
                    {
                        **bench,
                        "replicate": index + 1,
                        "fixture_ready_ms": measurement["fixtureReadyMs"],
                        "dom_content_loaded_ms": measurement["domContentLoadedMs"],
                        "load_ms": measurement["loadMs"],
                        "node_count": measurement["nodeCount"],
                        "pass_rate_pct": measurement["passRatePct"],
                        "failure_count": measurement["failureCount"],
                    }
                )
            fixture_mean, fixture_std = metric_summary([m["fixtureReadyMs"] for m in measurements])
            dcl_mean, dcl_std = metric_summary([m["domContentLoadedMs"] for m in measurements])
            load_mean, load_std = metric_summary([m["loadMs"] for m in measurements])
            pass_mean, pass_std = metric_summary([m["passRatePct"] for m in measurements])
            failure_mean, failure_std = metric_summary([m["failureCount"] for m in measurements])
            summary_rows.append(
                {
                    **bench,
                    "fixture_ready_ms": fixture_mean,
                    "fixture_ready_ms_std": fixture_std,
                    "dom_content_loaded_ms": dcl_mean,
                    "dom_content_loaded_ms_std": dcl_std,
                    "load_ms": load_mean,
                    "load_ms_std": load_std,
                    "node_count": measurements[-1]["nodeCount"],
                    "pass_rate_pct": pass_mean,
                    "pass_rate_pct_std": pass_std,
                    "failure_count": failure_mean,
                    "failure_count_std": failure_std,
                }
            )
        browser.close()

    data_dir = ROOT / "data"
    replicate_path = data_dir / "browser_replicates.csv"
    summary_path = data_dir / "browser_benchmarks.csv"
    with replicate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(replicate_rows[0].keys()))
        writer.writeheader()
        writer.writerows(replicate_rows)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    for row in summary_rows:
        print(
            f"{row['run_id']} {row['candidate']} ready={row['fixture_ready_ms']}±{row['fixture_ready_ms_std']} "
            f"pass={row['pass_rate_pct']}±{row['pass_rate_pct_std']} failures={row['failure_count']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
