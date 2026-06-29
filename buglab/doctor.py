from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.ignore import should_skip_common_path


@dataclass(frozen=True)
class DoctorConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    targets: list[str] | None = None
    check_browser: bool = True
    write_report: bool = True


def doctor_repo(config: DoctorConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    if config is None:
        config = DoctorConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    checks: list[dict[str, Any]] = []

    checks.append(check_repo(repo))
    checks.append(check_output(output_root))
    checks.append(check_package())
    target_check = check_targets(repo, config.targets)
    checks.append(target_check)
    checks.append(check_inventory(repo))
    if config.check_browser:
        checks.append(check_playwright_browser(repo))
    else:
        checks.append(check("playwright_chromium", "skipped", "Browser launch check skipped."))

    summary = summarize_checks(checks)
    payload = {
        "schema_version": "buglab.doctor.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(repo),
        "output": str(output_root),
        "summary": summary,
        "checks": checks,
        "next_command": suggested_next_command(repo, target_check),
    }
    report_path = ""
    if config.write_report:
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            report_path = str(output_root / f"doctor_{time.strftime('%Y%m%d_%H%M%S')}.json")
            payload["report_path"] = report_path
            Path(report_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            checks.append(check("doctor_report", "failed", f"Could not write doctor report: {exc}"))
            payload["summary"] = summarize_checks(checks)
            report_path = ""
    payload["report_path"] = report_path
    return payload


def check_repo(repo: Path) -> dict[str, Any]:
    if not repo.exists():
        return check("repo", "failed", f"Repository path does not exist: {repo}")
    if not repo.is_dir():
        return check("repo", "failed", f"Repository path is not a directory: {repo}")
    try:
        next(repo.iterdir(), None)
    except OSError as exc:
        return check("repo", "failed", f"Repository path is not readable: {exc}")
    return check("repo", "passed", "Repository path exists and is readable.", {"path": str(repo)})


def check_output(output_root: Path) -> dict[str, Any]:
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / ".buglab_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return check("output", "failed", f"Output directory is not writable: {exc}", {"path": str(output_root)})
    return check("output", "passed", "Output directory is writable.", {"path": str(output_root)})


def check_package() -> dict[str, Any]:
    try:
        version = importlib.metadata.version("buglab-swarm")
    except importlib.metadata.PackageNotFoundError:
        version = "editable_or_uninstalled"
    return check(
        "package",
        "passed",
        "BugLab package import is available.",
        {
            "distribution": "buglab-swarm",
            "version": version,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    )


def check_targets(repo: Path, targets: list[str] | None) -> dict[str, Any]:
    selected = targets or discover_targets(repo)
    existing = []
    missing = []
    for target in selected:
        if target.startswith(("http://", "https://", "file://")):
            existing.append(target)
        elif (repo / target).exists():
            existing.append(target)
        else:
            missing.append(target)
    status = "passed" if existing else "warning"
    message = f"{len(existing)} browser target(s) ready."
    if missing:
        message += f" {len(missing)} discovered/supplied target(s) do not exist."
    return check(
        "targets",
        status,
        message,
        {"targets": selected, "existing": existing, "missing": missing},
    )


def check_inventory(repo: Path) -> dict[str, Any]:
    docs = count_files(repo, ["*.md", "*.markdown"], limit=200)
    tests = count_files(repo, ["test*.py", "*_test.py", "*_tests.py"], limit=300)
    configs = count_files(repo, ["*.json", "*.env", ".env.*", "*.yml", "*.yaml", "Dockerfile", "*.toml", "*.ini", "*.cfg"], limit=400)
    status = "passed" if any([docs, tests, configs]) else "warning"
    return check(
        "repo_inventory",
        status,
        "Repo inventory collected for non-browser audit sectors.",
        {"markdown_docs": docs, "python_tests": tests, "config_files": configs},
    )


def check_playwright_browser(repo: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return check("playwright_chromium", "failed", f"Playwright import failed: {exc}")
    try:
        temp_dir = repo / ".buglab" / "tmp" / "playwright"
        temp_dir.mkdir(parents=True, exist_ok=True)
        os.environ["TMP"] = str(temp_dir)
        os.environ["TEMP"] = str(temp_dir)
        os.environ["TMPDIR"] = str(temp_dir)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            version = browser.version
            browser.close()
    except Exception as exc:
        return check(
            "playwright_chromium",
            "failed",
            f"Chromium launch failed: {exc}. Run `python -m playwright install chromium`.",
        )
    return check("playwright_chromium", "passed", "Playwright Chromium launched successfully.", {"version": version})


def discover_targets(repo: Path) -> list[str]:
    candidates = [
        "index.html",
        "dist/index.html",
        "build/index.html",
        "public/index.html",
        "docs/index.html",
        "src/index.html",
    ]
    found = [candidate for candidate in candidates if (repo / candidate).exists()]
    return found or ["index.html"]


def count_files(repo: Path, patterns: list[str], *, limit: int) -> int:
    count = 0
    for pattern in patterns:
        for path in repo.rglob(pattern):
            try:
                rel = path.relative_to(repo).as_posix()
            except ValueError:
                continue
            if path.is_file() and not should_skip_path(rel):
                count += 1
                if count >= limit:
                    return count
    return count


def should_skip_path(rel: str) -> bool:
    return should_skip_common_path(rel)


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = sum(1 for item in checks if item["status"] == "failed")
    warnings = sum(1 for item in checks if item["status"] == "warning")
    passed = sum(1 for item in checks if item["status"] == "passed")
    skipped = sum(1 for item in checks if item["status"] == "skipped")
    if failed:
        status = "failed"
    elif warnings:
        status = "warning"
    else:
        status = "passed"
    return {
        "status": status,
        "passed": passed,
        "warnings": warnings,
        "failed": failed,
        "skipped": skipped,
        "total": len(checks),
    }


def suggested_next_command(repo: Path, target_check: dict[str, Any]) -> str:
    existing = target_check.get("details", {}).get("existing", [])
    if existing:
        target = str(existing[0])
        return f"buglab hunt --repo {repo} --target {target} --loops 1 --profiles balanced"
    return f"buglab hunt --repo {repo} --no-browser --loops 1 --profiles balanced"


def check(name: str, status: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "details": details or {},
    }


def render_doctor_text(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"BugLab doctor: {summary['status']}",
        f"Repo: {payload['repo']}",
        f"Report: {payload.get('report_path') or '(not written)'}",
        "",
    ]
    for item in payload.get("checks", []):
        lines.append(f"[{item['status']}] {item['name']}: {item['message']}")
    lines.extend(["", f"Next: {payload['next_command']}"])
    return "\n".join(lines) + "\n"
