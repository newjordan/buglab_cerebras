from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from buglab.reporting import Evidence
from buglab.reporting import Finding
from buglab.reporting import ReportBuilder
from buglab.reporting import write_json


ERROR_TEXT = re.compile(r"\b(error|failed|could not|exception|undefined|null|invalid|forbidden|denied)\b", re.I)
CLICK_SELECTOR = "a[href], button, input, select, textarea, [role=button], [onclick]"
ACTION_LABEL_RE = re.compile(r"\b(add|apply|checkout|close|connect|continue|create|load|next|open|refresh|save|send|submit|update)\b", re.I)
PLACEHOLDER_HREFS = {"", "#", "javascript:void(0)", "javascript:;"}


@dataclass(frozen=True)
class HunterOptions:
    target: str
    output_root: Path
    base_dir: Path
    run_name: str = "buglab"
    max_clicks: int = 30
    mobile: bool = False
    profile: str = "balanced"
    timeout_ms: int = 1500


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def setup_temp(base_dir: Path) -> None:
    temp_dir = base_dir / ".buglab" / "tmp" / "playwright"
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp_dir)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)


def target_url(target: str, base_dir: Path) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    return (base_dir / target).resolve().as_uri()


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
            value: el.value || el.getAttribute('value') || '',
            min: el.getAttribute('min') || '',
            max: el.getAttribute('max') || '',
            role: el.getAttribute('role') || '',
            text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 100),
            label: (el.labels && el.labels[0] ? el.labels[0].innerText : '').trim().slice(0, 100),
            href: el.getAttribute('href') || '',
            disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
            onclick: el.getAttribute('onclick') || ''
          }}));
        }}"""
    )


def scan_page_issues(page: Page) -> list[dict[str, Any]]:
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

          const issues = [];
          const viewportWidth = window.innerWidth;
          const viewportHeight = window.innerHeight;
          const documentElement = document.documentElement;
          const scrollHeight = Math.max(
            documentElement.scrollHeight,
            document.body ? document.body.scrollHeight : 0
          );
          const scrollWidth = Math.max(
            documentElement.scrollWidth,
            document.body ? document.body.scrollWidth : 0
          );
          const canReachBelowFold = scrollHeight > viewportHeight + 8;
          const canReachRightOfFold = scrollWidth > viewportWidth + 8;
          for (const el of document.querySelectorAll('{CLICK_SELECTOR}')) {{
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const offscreenLeft = rect.right < 0;
            const offscreenAbove = rect.bottom < 0;
            const offscreenRight = rect.left > viewportWidth && !canReachRightOfFold;
            const offscreenBelow = rect.top > viewportHeight && !canReachBelowFold;
            const offscreen = offscreenLeft || offscreenAbove || offscreenRight || offscreenBelow;
            if (rect.width > 0 && rect.height > 0 && offscreen) {{
              issues.push({{
                category: 'layout_agent',
                selector: selectorFor(el),
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
                signal: `offscreen_interactive:rect=${{Math.round(rect.left)}},${{Math.round(rect.top)}},${{Math.round(rect.width)}},${{Math.round(rect.height)}}`
              }});
            }}
          }}
          for (const el of document.querySelectorAll('p, div, span, td, th, label, button, a')) {{
            const text = (el.innerText || '').trim();
            if (text.length < 24) continue;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const clippedX = el.scrollWidth > el.clientWidth + 2 && ['hidden', 'clip'].includes(style.overflowX);
            const clippedY = el.scrollHeight > el.clientHeight + 2 && ['hidden', 'clip'].includes(style.overflowY);
            if (clippedX || clippedY) {{
              issues.push({{
                category: 'layout_agent',
                selector: selectorFor(el),
                text: text.slice(0, 120),
                signal: `clipped_text:scroll=${{el.scrollWidth}}x${{el.scrollHeight}}:client=${{el.clientWidth}}x${{el.clientHeight}}`
              }});
            }}
          }}
          return issues.slice(0, 50).map((issue, index) => ({{...issue, id: `PAGE-${{String(index + 1).padStart(3, '0')}}`}}));
        }}"""
    )


def synthetic_value(control_hint: str, input_type: str, profile: str) -> str:
    hint = control_hint.lower()
    if input_type == "color":
        return "#22c55e"
    if input_type == "date":
        return "2026-06-28"
    if input_type == "datetime-local":
        return "2026-06-28T19:30"
    if input_type == "month":
        return "2026-06"
    if input_type == "time":
        return "19:30"
    if input_type == "week":
        return "2026-W27"
    if profile == "edge":
        if any(token in hint for token in ["email", "mail"]):
            return "not-an-email"
        if input_type in {"number", "range"} or any(token in hint for token in ["amount", "price", "qty", "quantity", "threshold", "limit"]):
            return "-1"
        return ""
    if profile == "business":
        if any(token in hint for token in ["email", "mail"]):
            return "ops@example.com"
        if any(token in hint for token in ["name", "company"]):
            return "Acme Ops"
    if input_type in {"number", "range"} or any(token in hint for token in ["amount", "price", "qty", "quantity", "threshold", "limit"]):
        return "130"
    if any(token in hint for token in ["email", "mail"]):
        return "qa@example.com"
    if any(token in hint for token in ["date"]):
        return "2026-06-28"
    return "NVDA"


def synthetic_control_value(control: dict[str, Any], profile: str) -> str:
    input_type = str(control.get("type", "")).lower()
    current_value = str(control.get("value") or control.get("text") or "").strip()
    if input_type == "range" and current_value:
        return current_value
    if input_type == "number":
        min_value = str(control.get("min", "")).strip()
        max_value = str(control.get("max", "")).strip()
        if min_value:
            return min_value
        if max_value:
            return max_value
    return synthetic_value(
        " ".join(str(control.get(key, "")) for key in ["selector", "name", "label", "text"]),
        input_type,
        profile,
    )


def is_external_link_control(control: dict[str, Any]) -> bool:
    href = str(control.get("href", "")).strip()
    if not href.startswith(("http://", "https://")):
        return False
    parsed = urlparse(href)
    return bool(parsed.scheme and parsed.netloc)


def prime_forms(page: Page, profile: str) -> None:
    fields = page.locator("input:not([type=hidden]):not([type=button]):not([type=submit]), textarea")
    for index in range(min(fields.count(), 16)):
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
            field.fill(synthetic_value(hint, input_type, profile), timeout=500)
        except PlaywrightError:
            continue


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


def browser_storage_metrics(page: Page) -> dict[str, int]:
    try:
        return page.evaluate(
            """() => ({
              localStorageKeys: window.localStorage ? window.localStorage.length : 0,
              sessionStorageKeys: window.sessionStorage ? window.sessionStorage.length : 0
            })"""
        )
    except PlaywrightError:
        return {"localStorageKeys": 0, "sessionStorageKeys": 0}


def safe_screenshot(page: Page, path: Path) -> None:
    try:
        page.screenshot(path=str(path), full_page=True)
    except PlaywrightError:
        return


def static_control_failures(control: dict[str, Any]) -> list[str]:
    label = " ".join(str(control.get(key, "")) for key in ["text", "label", "selector"]).strip()
    href = str(control.get("href", "")).strip().lower()
    role = str(control.get("role", "")).lower()
    tag = str(control.get("tag", "")).lower()
    failures: list[str] = []

    if control.get("disabled") and ACTION_LABEL_RE.search(label):
        failures.append("disabled_primary_action")
    if tag == "a" and href in PLACEHOLDER_HREFS:
        if role == "button" or control.get("onclick"):
            failures.append("button_like_anchor_missing_href")
        elif ACTION_LABEL_RE.search(label):
            failures.append("anchor_placeholder_href")
    return failures


def text_flags(page: Page) -> list[str]:
    try:
        body_text = page.locator("body").inner_text(timeout=1000)
    except PlaywrightError:
        return ["body_text_unreadable"]
    flags = sorted({match.group(0).lower() for match in ERROR_TEXT.finditer(body_text)})
    return [f"text_flag:{flag}" for flag in flags[:8]]


def semantic_state_failures(
    control: dict[str, Any],
    before_text: str,
    after_text: str,
    before_url: str,
    after_url: str,
    before_metrics: dict[str, int],
    after_metrics: dict[str, int],
    after_storage: dict[str, int],
) -> list[str]:
    label = " ".join(str(control.get(key, "")) for key in ["text", "label", "selector"]).lower()
    if not any(token in label for token in ["refresh", "save", "submit", "add", "create", "load", "connect", "checkout"]):
        return []
    changed = before_text != after_text or before_url != after_url
    if not changed:
        return ["semantic_no_state_change"]
    if "refresh" in label or "load" in label:
        collection_before = before_metrics["listItems"] + before_metrics["tableRows"] + before_metrics["cards"]
        collection_after = after_metrics["listItems"] + after_metrics["tableRows"] + after_metrics["cards"]
        if collection_after <= collection_before:
            return ["semantic_refresh_no_loaded_state"]
    if any(token in label for token in ["save", "submit", "add", "create", "checkout"]) and not re.search(
        r"\b(saved|created|added|success|complete|submitted|confirmed)\b", after_text
    ):
        failures = ["semantic_submit_no_success_state"]
        if re.search(r"\b(error|failed|invalid|rejected|denied)\b", after_text) and (
            after_storage.get("localStorageKeys", 0) or after_storage.get("sessionStorageKeys", 0)
        ):
            failures.append("state_persisted_after_error")
        return failures
    if re.search(r"\b(error|failed|invalid|rejected|denied)\b", after_text) and (
        after_storage.get("localStorageKeys", 0) or after_storage.get("sessionStorageKeys", 0)
    ):
        return ["state_persisted_after_error"]
    return []


def agent_labels(failures: list[str], control: dict[str, Any]) -> list[str]:
    labels = []
    if any("console" in failure or "pageerror" in failure or "requestfailed" in failure for failure in failures):
        labels.append("runtime_agent")
    if any(
        "click_timeout" in failure
        or "navigation" in failure
        or "disabled_primary_action" in failure
        or "anchor_" in failure
        or "button_like_anchor" in failure
        for failure in failures
    ):
        labels.append("interaction_agent")
    if any("text_flag" in failure or "semantic_" in failure for failure in failures):
        labels.append("copy_state_agent")
    if control.get("tag") in {"input", "textarea", "select"}:
        labels.append("form_agent")
    if not labels:
        labels.append("smoke_agent")
    return labels


def bug_hunt_once(options: HunterOptions) -> dict[str, Any]:
    setup_temp(options.base_dir)
    run_id = f"{options.run_name}_{options.profile}_{now_stamp()}"
    out_dir = options.output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    url = target_url(options.target, options.base_dir)
    viewport = {"width": 390, "height": 844} if options.mobile else {"width": 1440, "height": 980}
    event_log: list[dict[str, str]] = []
    started = time.perf_counter()

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
        page_issues = scan_page_issues(page)
        controls = discover_controls(page)
        actions = []

        for control in controls[: options.max_clicks]:
            before_event_count = len(event_log)
            failures: list[str] = []
            screenshot = out_dir / f"action_{control['index']:03d}.png"
            final_url = url
            body_chars = 0
            try:
                page.goto(url, wait_until="load")
                prime_forms(page, options.profile)
                before_text = normalized_body(page)
                before_url = page.url
                before_metrics = state_metrics(page)
                before_event_count = len(event_log)
                locator = page.locator(control["selector"]).first
                failures.extend(static_control_failures(control))
                skipped_interaction = bool(control.get("disabled"))
                if control.get("disabled"):
                    safe_screenshot(page, screenshot)
                    after_text = normalized_body(page)
                    body_chars = len(after_text)
                elif control["tag"] == "select":
                    options_locator = locator.locator("option")
                    if options_locator.count() > 1:
                        value = options_locator.nth(1).get_attribute("value") or options_locator.nth(1).inner_text()
                        locator.select_option(value, timeout=options.timeout_ms)
                    else:
                        locator.click(timeout=options.timeout_ms)
                elif control["tag"] in {"input", "textarea"} and control["type"] not in {"button", "submit", "checkbox", "radio"}:
                    locator.fill(
                        synthetic_control_value(control, options.profile),
                        timeout=options.timeout_ms,
                    )
                else:
                    locator.click(timeout=options.timeout_ms)
                page.wait_for_timeout(150)
                final_url = page.url
                safe_screenshot(page, screenshot)
                if final_url.startswith("chrome-error://") and not is_external_link_control(control):
                    failures.append(f"navigation_error_page:{final_url}")
                after_text = normalized_body(page)
                after_metrics = state_metrics(page)
                after_storage = browser_storage_metrics(page)
                body_chars = len(after_text)
                failures.extend(text_flags(page))
                if not skipped_interaction:
                    failures.extend(
                        semantic_state_failures(
                            control, before_text, after_text, before_url, final_url, before_metrics, after_metrics, after_storage
                        )
                    )
            except PlaywrightTimeoutError as exc:
                failures.append(f"click_timeout:{control['selector']}")
                failures.append(str(exc).splitlines()[0])
                safe_screenshot(page, screenshot)
            except PlaywrightError as exc:
                failures.append(f"playwright_error:{type(exc).__name__}:{str(exc).splitlines()[0]}")
                safe_screenshot(page, screenshot)

            for event in event_log[before_event_count:]:
                if event["kind"] in {"pageerror", "requestfailed", "console.error"}:
                    if event["kind"] == "requestfailed" and is_external_link_control(control):
                        continue
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

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    bug_candidates = [action for action in actions if not action["ok"]]
    failure_signal_count = sum(len(action["failures"]) for action in actions) + len(page_issues)
    report = {
        "target": options.target,
        "url": url,
        "profile": options.profile,
        "viewport": viewport,
        "baseline_screenshot": str(baseline_screenshot),
        "page_issues": page_issues,
        "page_issue_count": len(page_issues),
        "controls_discovered": len(controls),
        "controls_exercised": len(actions),
        "baseline_event_count": baseline_events,
        "bug_candidate_count": len(bug_candidates) + len(page_issues),
        "failure_signal_count": failure_signal_count,
        "elapsed_ms": elapsed_ms,
        "agent_counts": count_agents(actions, page_issues),
        "actions": actions,
    }
    write_json(out_dir / "report.json", report)
    write_markdown_report(report, out_dir / "bugs.md")
    write_standard_report(report, run_id, out_dir, options.base_dir)
    return {"run_id": run_id, "output_dir": str(out_dir), "report": report}


def write_standard_report(report: dict[str, Any], run_id: str, out_dir: Path, base_dir: Path) -> None:
    status = "failed" if report["bug_candidate_count"] else "passed"
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.bug_hunt",
        target=report["target"],
        output_dir=out_dir,
        base_dir=base_dir,
        status=status,
        title=f"BugLab Hunt: {report['target']}",
        summary=(
            f"Profile {report['profile']} exercised {report['controls_exercised']} of "
            f"{report['controls_discovered']} controls and found {report['bug_candidate_count']} bug candidates."
        ),
    )
    builder.metric("controls_discovered", report["controls_discovered"])
    builder.metric("controls_exercised", report["controls_exercised"])
    builder.metric("page_issue_count", report.get("page_issue_count", 0))
    builder.metric("click_path_coverage_pct", round((report["controls_exercised"] / max(1, report["controls_discovered"])) * 100, 2), unit="pct")
    builder.metric("bug_candidate_count", report["bug_candidate_count"])
    builder.metric("failure_signal_count", report.get("failure_signal_count", report["bug_candidate_count"]))
    builder.metric("elapsed_ms", report["elapsed_ms"], unit="ms")
    builder.artifact("raw_tool_report", out_dir / "report.json", kind="json")
    builder.artifact("bug_markdown", out_dir / "bugs.md", kind="markdown")
    builder.evidence(
        Evidence(
            id="baseline_screenshot",
            kind="screenshot",
            path=report["baseline_screenshot"],
            label="Baseline Screenshot",
            condition="baseline",
            viewport=report["viewport"],
        )
    )
    for action in report["actions"]:
        control = action["control"]
        evidence_id = f"action_{control['index']:03d}_screenshot"
        if action.get("screenshot"):
            builder.evidence(
                Evidence(
                    id=evidence_id,
                    kind="screenshot",
                    path=action["screenshot"],
                    label=f"Action {control['index']}: {control.get('text') or control['selector']}",
                    condition="after_action",
                    selector=control["selector"],
                    action=f"{control['tag']}:{control.get('text') or control['selector']}",
                    viewport=report["viewport"],
                    metadata={"ok": action["ok"], "final_url": action["final_url"], "agent_labels": action["agent_labels"]},
                )
            )
        if not action["ok"]:
            builder.finding(
                Finding(
                    id=f"BUG-{control['index']:03d}",
                    title=f"{control.get('text') or control['selector']} produced failure signals",
                    severity="medium",
                    status="open",
                    category=";".join(action["agent_labels"]),
                    selector=control["selector"],
                    signals=action["failures"],
                    evidence_ids=["baseline_screenshot", evidence_id],
                    reproduction_steps=[
                        f"Open {report['target']}.",
                        f"Use BugLab profile `{report['profile']}`.",
                        f"Activate `{control['selector']}`.",
                        "Inspect linked screenshot evidence and signals.",
                    ],
                    expected="The action should produce a valid loaded, saved, navigated, or unchanged-safe state.",
                    actual="; ".join(action["failures"]),
                    fix_hypothesis="Inspect handler/state update, validation branch, or runtime event attached to this control.",
                )
            )
    for issue in report.get("page_issues", []):
        builder.finding(
            Finding(
                id=issue["id"],
                title=f"Page-level visual issue: {issue.get('text') or issue['selector']}",
                severity="medium",
                status="open",
                category=issue.get("category", "layout_agent"),
                selector=issue["selector"],
                signals=[issue["signal"]],
                evidence_ids=["baseline_screenshot"],
                reproduction_steps=[
                    f"Open {report['target']}.",
                    f"Inspect `{issue['selector']}` in the baseline screenshot and DOM.",
                ],
                expected="Visible text and interactive elements should be readable and reachable in the viewport.",
                actual=issue["signal"],
                fix_hypothesis="Inspect responsive layout, overflow, positioning, or visibility styles.",
            )
        )
    builder.write()


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"# BugLab Hunt: {report['target']}",
        "",
        f"- Profile: `{report['profile']}`",
        f"- Controls discovered: {report['controls_discovered']}",
        f"- Controls exercised: {report['controls_exercised']}",
        f"- Bug candidates: {report['bug_candidate_count']}",
        f"- Page issues: {report.get('page_issue_count', 0)}",
        f"- Elapsed ms: {report['elapsed_ms']}",
        "",
    ]
    for issue in report.get("page_issues", []):
        lines.extend(
            [
                f"## {issue['id']}: {issue.get('text') or issue['selector']}",
                "",
                f"- Selector: `{issue['selector']}`",
                "- Agents: layout_agent",
                "- Screenshot: baseline",
                "- Signals:",
                f"  - {issue['signal']}",
                "",
            ]
        )
    for action in report["actions"]:
        if action["ok"]:
            continue
        control = action["control"]
        lines.extend(
            [
                f"## BUG-{control['index']:03d}: {control.get('text') or control['selector']}",
                "",
                f"- Selector: `{control['selector']}`",
                f"- Agents: {', '.join(action['agent_labels'])}",
                f"- Screenshot: `{action['screenshot']}`",
                "- Signals:",
            ]
        )
        for failure in action["failures"]:
            lines.append(f"  - {failure}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def count_agents(actions: list[dict[str, Any]], page_issues: list[dict[str, Any]] | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in page_issues or []:
        label = issue.get("category", "layout_agent")
        counts[label] = counts.get(label, 0) + 1
    for action in actions:
        for label in action["agent_labels"]:
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))
