from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from swarm_common import ROOT
from swarm_common import now_stamp
from swarm_common import read_json
from swarm_common import write_json
from reporting import add_artifact
from reporting import add_evidence
from reporting import add_finding
from reporting import add_metric
from reporting import make_manifest
from reporting import write_standard_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser verification for local fixtures.")
    parser.add_argument("--target", required=True, help="HTML file relative to repo root.")
    parser.add_argument("--tasks", help="Optional task JSON file relative to repo root.")
    parser.add_argument("--name", default="browser_verify")
    return parser.parse_args()


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def run_tasks(page, tasks: list[dict[str, object]]) -> list[dict[str, object]]:
    results = []
    for task in tasks:
        ok = True
        failures = []
        for step in task["steps"]:
            action = step["action"]
            selector = step["selector"]
            try:
                if action == "click":
                    page.click(selector)
                elif action == "fill":
                    page.fill(selector, step["value"])
                elif action == "expect_count_at_least":
                    count = page.locator(selector).count()
                    if count < int(step["count"]):
                        ok = False
                        failures.append(f"{selector} count {count} < {step['count']}")
                elif action == "expect_text_contains":
                    text = page.locator(selector).inner_text(timeout=1000).lower()
                    if str(step["value"]).lower() not in text:
                        ok = False
                        failures.append(f"{selector} text did not contain {step['value']!r}: {text!r}")
                else:
                    ok = False
                    failures.append(f"Unknown action: {action}")
            except PlaywrightTimeoutError as exc:
                ok = False
                failures.append(f"Timeout on {action} {selector}: {exc}")
        results.append({"id": task["id"], "ok": ok, "failures": failures})
    return results


def main() -> int:
    args = parse_args()
    target = ROOT / args.target
    if not target.exists():
        raise FileNotFoundError(target)
    run_id = f"{args.name}_{now_stamp()}"
    out_dir = ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = ROOT / "tmp" / "playwright"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.goto(file_url(target), wait_until="load")
        metrics = page.evaluate(
            """() => {
              const nav = performance.getEntriesByType('navigation')[0];
              const body = document.body.getBoundingClientRect();
              const overflowX = document.documentElement.scrollWidth > window.innerWidth;
              const overflowY = document.documentElement.scrollHeight > window.innerHeight;
              const fixtureReadyMs = window.__fixtureReadyAt && window.__fixtureStart
                ? Math.round(window.__fixtureReadyAt - window.__fixtureStart)
                : null;
              return {
                domContentLoadedMs: Math.round(nav.domContentLoadedEventEnd),
                loadMs: Math.round(nav.loadEventEnd),
                fixtureReadyMs,
                nodeCount: document.querySelectorAll('*').length,
                bodyWidth: Math.round(body.width),
                bodyHeight: Math.round(body.height),
                overflowX,
                overflowY
              };
            }"""
        )
        screenshot = out_dir / "desktop.png"
        page.screenshot(path=str(screenshot), full_page=True)

        task_results = []
        if args.tasks:
            task_results = run_tasks(page, read_json(ROOT / args.tasks))

        browser.close()

    pass_count = sum(1 for item in task_results if item["ok"])
    pass_rate = round((pass_count / len(task_results)) * 100, 1) if task_results else None
    report = {
        "target": args.target,
        "screenshot": str(screenshot),
        "metrics": metrics,
        "tasks": task_results,
        "pass_rate_pct": pass_rate,
        "failure_count": sum(len(item["failures"]) for item in task_results),
    }
    raw_report_path = out_dir / "report.json"
    write_json(raw_report_path, report)
    write_buglab_report(report, run_id, out_dir, raw_report_path)
    print(json.dumps(report, indent=2))
    return 0 if report["failure_count"] == 0 else 1


def write_buglab_report(report: dict[str, object], run_id: str, out_dir: Path, raw_report_path: Path) -> None:
    failure_count = int(report["failure_count"])
    status = "failed" if failure_count else "passed"
    manifest = make_manifest(
        run_id=run_id,
        tool="browser_verify",
        target=str(report["target"]),
        output_dir=out_dir,
        status=status,
        title=f"Browser Verify: {report['target']}",
        summary=f"Browser verification completed with {failure_count} failures.",
    )
    metrics = report["metrics"]
    if isinstance(metrics, dict):
        for name, value in metrics.items():
            unit = "ms" if name.lower().endswith("ms") else ""
            add_metric(manifest, name, value, unit=unit, description="Browser-captured page metric.")
    add_metric(manifest, "failure_count", failure_count, description="Total scripted assertion failures.")
    add_metric(manifest, "pass_rate_pct", report.get("pass_rate_pct"), unit="pct", description="Task pass rate when tasks are present.")
    add_artifact(manifest, "raw_tool_report", raw_report_path, kind="json")
    screenshot_path = str(report["screenshot"])
    add_evidence(
        manifest,
        evidence_id="desktop_screenshot",
        kind="screenshot",
        path=screenshot_path,
        label="Desktop Screenshot",
        description="Full-page screenshot after load and scripted tasks.",
        condition="after_verification",
        viewport={"width": 1440, "height": 980},
        metadata={"metrics": metrics},
    )
    tasks = report.get("tasks", [])
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict) or task.get("ok"):
                continue
            failures = [str(item) for item in task.get("failures", [])]
            add_finding(
                manifest,
                finding_id=f"TASK-{task.get('id', 'unknown')}",
                title=f"Task failed: {task.get('id', 'unknown')}",
                severity="medium",
                status="open",
                category="scripted_playthrough",
                signals=failures,
                evidence_ids=["desktop_screenshot"],
                reproduction_steps=[
                    f"Open {report['target']}.",
                    f"Run scripted task `{task.get('id', 'unknown')}`.",
                    "Inspect assertion failures and screenshot.",
                ],
                expected="All scripted assertions should pass.",
                actual="; ".join(failures),
                fix_hypothesis="Patch the UI handler/state so the scripted assertion observes the expected DOM state.",
            )
    write_standard_report(manifest, out_dir)


if __name__ == "__main__":
    sys.exit(main())
