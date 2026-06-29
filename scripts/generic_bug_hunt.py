from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from swarm_common import ROOT
from swarm_common import now_stamp
from swarm_common import write_json
from reporting import add_artifact
from reporting import add_evidence
from reporting import add_finding
from reporting import add_metric
from reporting import make_manifest
from reporting import write_standard_report


ERROR_TEXT = re.compile(r"\b(error|failed|could not|exception|undefined|null|invalid)\b", re.I)
CLICK_SELECTOR = "a[href], button, input, select, textarea, [role=button], [onclick]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic click-through bug hunter for web software.")
    parser.add_argument("--target", required=True, help="URL or local path relative to repo root.")
    parser.add_argument("--name", default="generic_bug_hunt")
    parser.add_argument("--max-clicks", type=int, default=30)
    parser.add_argument("--mobile", action="store_true")
    return parser.parse_args()


def target_url(target: str) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    return (ROOT / target).resolve().as_uri()


def setup_temp() -> None:
    temp_dir = ROOT / "tmp" / "playwright"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)


def discover_controls(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        f"""() => {{
          function selectorFor(el) {{
            if (el.id) return `#${{CSS.escape(el.id)}}`;
            const parts = [];
            let node = el;
            while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 5) {{
              let part = node.nodeName.toLowerCase();
              if (node.classList && node.classList.length) {{
                part += '.' + [...node.classList].slice(0, 2).map(c => CSS.escape(c)).join('.');
              }}
              const parent = node.parentElement;
              if (parent) {{
                const siblings = [...parent.children].filter(child => child.nodeName === node.nodeName);
                if (siblings.length > 1) part += `:nth-of-type(${{siblings.indexOf(node) + 1}})`;
              }}
              parts.unshift(part);
              node = parent;
            }}
            return parts.join(' > ');
          }}

          return [...document.querySelectorAll('{CLICK_SELECTOR}')].filter(el => {{
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }}).map((el, index) => ({{
            index,
            selector: selectorFor(el),
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            name: el.getAttribute('name') || '',
            role: el.getAttribute('role') || '',
            text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 100),
            label: (el.labels && el.labels[0] ? el.labels[0].innerText : '').trim().slice(0, 100),
            href: el.getAttribute('href') || ''
          }}));
        }}"""
    )


def synthetic_value(control_hint: str, input_type: str) -> str:
    hint = control_hint.lower()
    if input_type in {"number", "range"} or any(token in hint for token in ["amount", "price", "qty", "quantity", "threshold", "limit"]):
        return "130"
    if any(token in hint for token in ["email", "mail"]):
        return "qa@example.com"
    if any(token in hint for token in ["date"]):
        return "2026-06-28"
    return "NVDA"


def prime_forms(page: Page) -> None:
    fields = page.locator("input:not([type=hidden]):not([type=button]):not([type=submit]), textarea")
    for index in range(min(fields.count(), 12)):
        field = fields.nth(index)
        try:
            input_type = (field.get_attribute("type") or "text").lower()
            hint = " ".join(
                part or ""
                for part in [
                    field.get_attribute("id"),
                    field.get_attribute("name"),
                    field.get_attribute("aria-label"),
                    field.get_attribute("placeholder"),
                ]
            )
            value = synthetic_value(hint, input_type)
            field.fill(value, timeout=500)
        except PlaywrightError:
            continue


def text_flags(page: Page) -> list[str]:
    try:
        body_text = page.locator("body").inner_text(timeout=1000)
    except PlaywrightError:
        return ["body_text_unreadable"]
    flags = sorted({match.group(0).lower() for match in ERROR_TEXT.finditer(body_text)})
    return [f"text_flag:{flag}" for flag in flags[:8]]


def agent_labels(failures: list[str], action: dict[str, Any]) -> list[str]:
    labels = []
    if any("console" in failure or "pageerror" in failure for failure in failures):
        labels.append("runtime_agent")
    if any("click_timeout" in failure or "navigation" in failure for failure in failures):
        labels.append("interaction_agent")
    if any("text_flag" in failure for failure in failures):
        labels.append("copy_state_agent")
    if action.get("tag") in {"input", "textarea", "select"}:
        labels.append("form_agent")
    if not labels:
        labels.append("smoke_agent")
    return labels


def normalized_body(page: Page) -> str:
    return re.sub(r"\s+", " ", page.locator("body").inner_text(timeout=1000)).strip().lower()


def state_metrics(page: Page) -> dict[str, int]:
    return page.evaluate(
        """() => ({
          listItems: document.querySelectorAll('li').length,
          tableRows: document.querySelectorAll('tbody tr, table tr').length,
          cards: document.querySelectorAll('[class*=card], [class*=row], article').length,
          disabledControls: document.querySelectorAll('button:disabled, input:disabled, select:disabled, textarea:disabled').length
        })"""
    )


def semantic_state_failures(
    control: dict[str, Any],
    before_text: str,
    after_text: str,
    before_url: str,
    after_url: str,
    before_metrics: dict[str, int],
    after_metrics: dict[str, int],
) -> list[str]:
    label = " ".join(str(control.get(key, "")) for key in ["text", "label", "selector"]).lower()
    if not any(token in label for token in ["refresh", "save", "submit", "add", "create", "load", "connect"]):
        return []
    changed = before_text != after_text or before_url != after_url
    if not changed:
        return ["semantic_no_state_change"]
    if "refresh" in label:
        collection_before = before_metrics["listItems"] + before_metrics["tableRows"] + before_metrics["cards"]
        collection_after = after_metrics["listItems"] + after_metrics["tableRows"] + after_metrics["cards"]
        has_collection = collection_after > collection_before
        if not has_collection:
            return ["semantic_refresh_no_loaded_state"]
    if any(token in label for token in ["save", "submit", "add", "create"]) and not re.search(
        r"\b(saved|created|added|success|complete)\b", after_text
    ):
        return ["semantic_submit_no_success_state"]
    return []


def hunt(args: argparse.Namespace) -> dict[str, Any]:
    setup_temp()
    run_id = f"{args.name}_{now_stamp()}"
    out_dir = ROOT / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    url = target_url(args.target)
    viewport = {"width": 390, "height": 844} if args.mobile else {"width": 1440, "height": 980}
    event_log: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport)
        page.on("console", lambda msg: event_log.append({"kind": f"console.{msg.type}", "text": msg.text}))
        page.on("pageerror", lambda exc: event_log.append({"kind": "pageerror", "text": str(exc)}))
        page.on("requestfailed", lambda req: event_log.append({"kind": "requestfailed", "text": req.url}))

        page.goto(url, wait_until="load")
        baseline_events = len(event_log)
        baseline_screenshot = out_dir / "baseline.png"
        page.screenshot(path=str(baseline_screenshot), full_page=True)
        controls = discover_controls(page)
        actions = []

        for control in controls[: args.max_clicks]:
            before_event_count = len(event_log)
            failures: list[str] = []
            screenshot = out_dir / f"action_{control['index']:03d}.png"
            final_url = url
            body_chars = 0

            try:
                page.goto(url, wait_until="load")
                prime_forms(page)
                before_text = normalized_body(page)
                before_url = page.url
                before_metrics = state_metrics(page)
                locator = page.locator(control["selector"]).first
                if control["tag"] == "select":
                    options = locator.locator("option")
                    if options.count() > 1:
                        value = options.nth(1).get_attribute("value") or options.nth(1).inner_text()
                        locator.select_option(value, timeout=1000)
                    else:
                        locator.click(timeout=1000)
                elif control["tag"] in {"input", "textarea"} and control["type"] not in {"button", "submit", "checkbox", "radio"}:
                    locator.fill(
                        synthetic_value(" ".join(str(control.get(key, "")) for key in ["selector", "name", "label", "text"]), control["type"]),
                        timeout=1000,
                    )
                else:
                    locator.click(timeout=1500)
                page.wait_for_timeout(150)
                final_url = page.url
                page.screenshot(path=str(screenshot), full_page=True)
                after_text = normalized_body(page)
                after_metrics = state_metrics(page)
                body_chars = len(after_text)
                failures.extend(text_flags(page))
                failures.extend(
                    semantic_state_failures(
                        control,
                        before_text,
                        after_text,
                        before_url,
                        final_url,
                        before_metrics,
                        after_metrics,
                    )
                )
            except PlaywrightTimeoutError as exc:
                failures.append(f"click_timeout:{control['selector']}")
                failures.append(str(exc).splitlines()[0])
            except PlaywrightError as exc:
                failures.append(f"playwright_error:{type(exc).__name__}:{str(exc).splitlines()[0]}")

            new_events = event_log[before_event_count:]
            for event in new_events:
                if event["kind"] in {"pageerror", "requestfailed", "console.error"}:
                    failures.append(f"{event['kind']}:{event['text'][:160]}")

            actions.append(
                {
                    "control": control,
                    "ok": len(failures) == 0,
                    "agent_labels": agent_labels(failures, control),
                    "failures": failures,
                    "screenshot": str(screenshot) if screenshot.exists() else "",
                    "final_url": final_url,
                    "body_chars": body_chars,
                }
            )

        browser.close()

    bug_candidates = [action for action in actions if not action["ok"]]
    report = {
        "target": args.target,
        "url": url,
        "viewport": viewport,
        "baseline_screenshot": str(baseline_screenshot),
        "controls_discovered": len(controls),
        "controls_exercised": len(actions),
        "baseline_event_count": baseline_events,
        "bug_candidate_count": len(bug_candidates),
        "agent_counts": agent_counts(actions),
        "actions": actions,
    }
    raw_report_path = out_dir / "report.json"
    bug_md_path = out_dir / "bugs.md"
    write_json(raw_report_path, report)
    bug_md_path.write_text(render_markdown(report), encoding="utf-8")
    write_buglab_report(report, run_id, out_dir, raw_report_path, bug_md_path)
    print(json.dumps({key: report[key] for key in [
        "target",
        "controls_discovered",
        "controls_exercised",
        "bug_candidate_count",
        "agent_counts",
    ]}, indent=2))
    print(out_dir)
    return report


def write_buglab_report(
    report: dict[str, Any],
    run_id: str,
    out_dir: Path,
    raw_report_path: Path,
    bug_md_path: Path,
) -> None:
    status = "failed" if report["bug_candidate_count"] else "passed"
    manifest = make_manifest(
        run_id=run_id,
        tool="generic_bug_hunt",
        target=report["target"],
        output_dir=out_dir,
        status=status,
        title=f"Generic Bug Hunt: {report['target']}",
        summary=(
            f"Exercised {report['controls_exercised']} of {report['controls_discovered']} controls; "
            f"found {report['bug_candidate_count']} bug candidates."
        ),
    )
    add_metric(manifest, "controls_discovered", report["controls_discovered"], description="Visible controls found.")
    add_metric(manifest, "controls_exercised", report["controls_exercised"], description="Controls clicked or filled.")
    coverage = round((report["controls_exercised"] / max(1, report["controls_discovered"])) * 100, 2)
    add_metric(manifest, "click_path_coverage_pct", coverage, unit="pct", description="Exercised controls / discovered controls.")
    add_metric(manifest, "bug_candidate_count", report["bug_candidate_count"], description="Actions with failure signals.")
    add_metric(manifest, "baseline_event_count", report["baseline_event_count"], description="Events emitted before actions.")
    add_artifact(manifest, "raw_tool_report", raw_report_path, kind="json")
    add_artifact(manifest, "bug_markdown", bug_md_path, kind="markdown")

    viewport = report.get("viewport", {})
    add_evidence(
        manifest,
        evidence_id="baseline_screenshot",
        kind="screenshot",
        path=report["baseline_screenshot"],
        label="Baseline Screenshot",
        description="Initial state before control exploration.",
        condition="baseline",
        viewport=viewport,
    )
    for action in report["actions"]:
        control = action["control"]
        evidence_id = f"action_{control['index']:03d}_screenshot"
        if action.get("screenshot"):
            add_evidence(
                manifest,
                evidence_id=evidence_id,
                kind="screenshot",
                path=action["screenshot"],
                label=f"Action {control['index']}: {control.get('text') or control['selector']}",
                description="Post-action screenshot.",
                condition="after_action",
                selector=control["selector"],
                action=f"{control['tag']}:{control.get('text') or control['selector']}",
                viewport=viewport,
                metadata={
                    "ok": action["ok"],
                    "final_url": action["final_url"],
                    "body_chars": action["body_chars"],
                    "agent_labels": action["agent_labels"],
                },
            )
        if not action["ok"]:
            add_finding(
                manifest,
                finding_id=f"BUG-{control['index']:03d}",
                title=f"{control.get('text') or control['selector']} produced failure signals",
                severity="medium",
                status="open",
                category=";".join(action["agent_labels"]),
                selector=control["selector"],
                signals=action["failures"],
                evidence_ids=["baseline_screenshot", evidence_id],
                reproduction_steps=[
                    f"Open {report['target']}.",
                    "Prime visible forms with synthetic valid values.",
                    f"Activate `{control['selector']}`.",
                    "Compare failure signals and screenshot evidence.",
                ],
                expected="The action should produce a valid loaded, saved, navigated, or unchanged-safe state.",
                actual="; ".join(action["failures"]),
                fix_hypothesis="Inspect the handler for missing state update, incorrect success/error branch, or unhandled runtime condition.",
            )
    write_standard_report(manifest, out_dir)


def agent_counts(actions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for action in actions:
        for label in action["agent_labels"]:
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Generic Bug Hunt: {report['target']}",
        "",
        f"- Controls discovered: {report['controls_discovered']}",
        f"- Controls exercised: {report['controls_exercised']}",
        f"- Bug candidates: {report['bug_candidate_count']}",
        f"- Baseline screenshot: `{report['baseline_screenshot']}`",
        "",
        "## Agent Counts",
        "",
    ]
    for agent, count in report["agent_counts"].items():
        lines.append(f"- {agent}: {count}")
    lines.extend(["", "## Bug Candidates", ""])
    for action in report["actions"]:
        if action["ok"]:
            continue
        control = action["control"]
        lines.extend(
            [
                f"### {control['index']} {control['tag']} `{control['selector']}`",
                "",
                f"- Text: {control.get('text') or '(none)'}",
                f"- Agents: {', '.join(action['agent_labels'])}",
                f"- Screenshot: `{action['screenshot']}`",
                f"- Final URL: `{action['final_url']}`",
                "- Failures:",
            ]
        )
        for failure in action["failures"]:
            lines.append(f"  - {failure}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = hunt(parse_args())
    return 1 if report["bug_candidate_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
