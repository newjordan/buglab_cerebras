from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKIP_DIRS = {
    ".buglab",
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "lcov-report",
    "node_modules",
    "playwright-report",
    "__pycache__",
}

CODE_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}

QUALITY_PRINCIPLES = [
    "Run deterministic gates before agent claims.",
    "Keep stdout, stderr, exit code, elapsed time, and command cwd as artifacts.",
    "Separate tool/environment failures from project correctness failures.",
    "Prefer the smallest reproducible check that proves the bug or repair.",
]


@dataclass(frozen=True)
class QualityConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/quality"
    run_name: str = "quality"
    profile: str = "auto"
    timeout_seconds: int = 180
    include_audit: bool = False


@dataclass(frozen=True)
class CommandSpec:
    check_id: str
    label: str
    command: list[str]
    cwd: Path
    timeout_seconds: int
    required: bool = True
    reason: str = ""


def run_quality_gate(config: QualityConfig) -> dict[str, Any]:
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    run_id = f"{safe_slug(config.run_name)}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    artifacts_dir = out_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    profile = resolve_profile(repo, config.profile)
    command_specs = build_command_specs(repo, profile, config.timeout_seconds, config.include_audit)
    command_results = [run_command(spec, artifacts_dir) for spec in command_specs]
    hygiene = scan_repo_hygiene(repo)
    loc = count_source_lines(repo)
    summary = summarize_quality(command_results, hygiene)

    payload: dict[str, Any] = {
        "schema_version": "buglab.quality.v1",
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "repo": str(repo),
        "output_dir": str(out_dir),
        "profile": profile,
        "principles": QUALITY_PRINCIPLES,
        "summary": summary,
        "loc": loc,
        "commands": command_results,
        "hygiene": hygiene,
    }
    json_path = out_dir / "quality_report.json"
    md_path = out_dir / "quality_report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_quality_markdown(payload), encoding="utf-8")
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    return payload


def resolve_profile(repo: Path, profile: str) -> str:
    if profile != "auto":
        return profile
    if (repo / "buglab").is_dir() and (repo / "app" / "server.py").is_file():
        return "buglab"
    if (repo / "package.json").is_file():
        return "node"
    return "generic"


def build_command_specs(repo: Path, profile: str, timeout_seconds: int, include_audit: bool) -> list[CommandSpec]:
    specs: list[CommandSpec] = []
    specs.append(
        CommandSpec(
            check_id="git_diff_check",
            label="Git whitespace/conflict-marker check",
            command=["git", "diff", "--check"],
            cwd=repo,
            timeout_seconds=min(timeout_seconds, 60),
            required=False,
            reason="Catches trailing whitespace and conflict markers before commits.",
        )
    )
    if profile == "buglab":
        py_files = [str(path.relative_to(repo)) for path in collect_files(repo, {".py"}, roots=["app", "buglab"])]
        if py_files:
            specs.append(
                CommandSpec(
                    check_id="python_compile",
                    label="Python syntax compile",
                    command=[sys.executable, "-m", "py_compile", *py_files],
                    cwd=repo,
                    timeout_seconds=timeout_seconds,
                    reason="Fast parser-level safety gate for BugLab internals.",
                )
            )
        app_js = repo / "app" / "static" / "app.js"
        if app_js.is_file():
            specs.append(
                CommandSpec(
                    check_id="node_check_app",
                    label="Frontend JavaScript syntax check",
                    command=["node", "--check", str(app_js.relative_to(repo))],
                    cwd=repo,
                    timeout_seconds=min(timeout_seconds, 60),
                    reason="Fast browser-bundle syntax gate.",
                )
            )
    if profile == "node":
        specs.extend(build_node_specs(repo, timeout_seconds, include_audit))
    return specs


def build_node_specs(repo: Path, timeout_seconds: int, include_audit: bool) -> list[CommandSpec]:
    package_path = repo / "package.json"
    if not package_path.is_file():
        return []
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [
            CommandSpec(
                check_id="package_json_parse",
                label="package.json parse",
                command=["node", "-e", "JSON.parse(require('fs').readFileSync('package.json','utf8'))"],
                cwd=repo,
                timeout_seconds=30,
            )
        ]
    scripts = package.get("scripts", {})
    specs: list[CommandSpec] = []
    if not (repo / "node_modules").is_dir():
        specs.append(
            CommandSpec(
                check_id="node_modules_probe",
                label="Dependency install probe",
                command=["node", "-e", "process.exit(require('fs').existsSync('node_modules') ? 0 : 2)"],
                cwd=repo,
                timeout_seconds=30,
                required=False,
                reason="Signals that npm scripts may be dependency-blocked without installing anything.",
            )
        )
    for script_name, check_id, label in [
        ("typecheck", "npm_typecheck", "TypeScript typecheck"),
        ("lint", "npm_lint", "Lint"),
        ("test", "npm_test", "Tests"),
        ("build", "npm_build", "Build"),
    ]:
        if script_name not in scripts:
            continue
        command = npm_command(["run", script_name])
        if script_name == "test":
            command.extend(["--", "--watchAll=false", "--cacheDirectory=.jest-cache"])
        specs.append(
            CommandSpec(
                check_id=check_id,
                label=label,
                command=command,
                cwd=repo,
                timeout_seconds=timeout_seconds,
                reason=f"Runs package script `{script_name}` as a quality gate.",
            )
        )
    if include_audit:
        specs.append(
            CommandSpec(
                check_id="npm_audit",
                label="npm audit",
                command=npm_command(["audit", "--json"]),
                cwd=repo,
                timeout_seconds=timeout_seconds,
                required=False,
                reason="Optional network-backed dependency vulnerability gate.",
            )
        )
    return specs


def npm_command(args: list[str]) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", "npm", *args]
    return ["npm", *args]


def run_command(spec: CommandSpec, artifacts_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    stdout_path = artifacts_dir / f"{spec.check_id}.stdout.txt"
    stderr_path = artifacts_dir / f"{spec.check_id}.stderr.txt"
    status = "failed"
    exit_code: int | None = None
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            spec.command,
            cwd=spec.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_seconds,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        status = "passed" if proc.returncode == 0 else "failed"
    except FileNotFoundError as exc:
        status = "skipped" if not spec.required else "failed"
        stderr = str(exc)
    except subprocess.TimeoutExpired as exc:
        status = "failed"
        timed_out = True
        stdout = decode_timeout_payload(exc.stdout)
        stderr = decode_timeout_payload(exc.stderr) or f"timed out after {spec.timeout_seconds}s"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "id": spec.check_id,
        "label": spec.label,
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "elapsed_ms": elapsed_ms,
        "required": spec.required,
        "reason": spec.reason,
        "cwd": str(spec.cwd),
        "command": command_display(spec.command),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_tail": tail(stdout),
        "stderr_tail": tail(stderr),
        "signals": classify_command_output(spec.check_id, stdout, stderr, exit_code, timed_out),
    }


def classify_command_output(check_id: str, stdout: str, stderr: str, exit_code: int | None, timed_out: bool) -> list[str]:
    text = f"{stdout}\n{stderr}".lower()
    signals: list[str] = []
    if timed_out:
        signals.append("timeout")
    if exit_code not in (None, 0):
        signals.append("nonzero_exit")
    if "htmlcanvaselement.prototype.getcontext" in text or "not implemented: htmlcanvaselement" in text:
        signals.append("jsdom_canvas_missing")
    if "eperm" in text or "permission denied" in text:
        signals.append("permission_or_cache_error")
    if "cannot find module" in text or "module not found" in text:
        signals.append("missing_dependency")
    if "failed to compile" in text:
        signals.append("compile_failure")
    if "vulnerabilities" in text and ("critical" in text or "high" in text):
        signals.append("dependency_vulnerabilities")
    if check_id == "git_diff_check" and exit_code not in (None, 0):
        signals.append("diff_hygiene")
    return sorted(set(signals))


def scan_repo_hygiene(repo: Path) -> dict[str, Any]:
    leftovers: list[dict[str, str]] = []
    for path in walk_files(repo):
        if path.suffix.lower() in {".rej", ".orig", ".original", ".fix"}:
            leftovers.append({"path": str(path), "kind": path.suffix.lower().lstrip(".")})
    return {
        "patch_leftover_count": len(leftovers),
        "patch_leftovers": leftovers[:200],
        "truncated": len(leftovers) > 200,
    }


def count_source_lines(repo: Path) -> dict[str, Any]:
    files = 0
    lines = 0
    by_extension: dict[str, dict[str, int]] = {}
    for path in walk_files(repo):
        ext = path.suffix.lower()
        if ext not in CODE_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        line_count = text.count("\n") + (1 if text else 0)
        files += 1
        lines += line_count
        bucket = by_extension.setdefault(ext or "(none)", {"files": 0, "lines": 0})
        bucket["files"] += 1
        bucket["lines"] += line_count
    return {"files": files, "lines": lines, "by_extension": by_extension}


def summarize_quality(commands: list[dict[str, Any]], hygiene: dict[str, Any]) -> dict[str, Any]:
    failed = [item for item in commands if item["status"] == "failed"]
    skipped = [item for item in commands if item["status"] == "skipped"]
    status = "failed" if failed or hygiene.get("patch_leftover_count", 0) else "passed"
    signals: dict[str, int] = {}
    for command in commands:
        for signal in command.get("signals", []):
            signals[signal] = signals.get(signal, 0) + 1
    if hygiene.get("patch_leftover_count", 0):
        signals["patch_leftovers"] = int(hygiene["patch_leftover_count"])
    return {
        "status": status,
        "checks": len(commands),
        "passed": sum(1 for item in commands if item["status"] == "passed"),
        "failed": len(failed),
        "skipped": len(skipped),
        "patch_leftover_count": int(hygiene.get("patch_leftover_count", 0)),
        "signals": signals,
    }


def render_quality_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"# BugLab Quality Gate: {payload['run_id']}",
        "",
        f"- Repo: `{payload['repo']}`",
        f"- Profile: `{payload['profile']}`",
        f"- Status: `{summary['status']}`",
        f"- Checks: {summary['checks']} ({summary['passed']} passed, {summary['failed']} failed, {summary['skipped']} skipped)",
        f"- Source lines: {payload['loc']['lines']} across {payload['loc']['files']} files",
        f"- Patch leftovers: {summary['patch_leftover_count']}",
        "",
        "## Checks",
        "",
        "| Check | Status | Exit | Signals |",
        "| --- | --- | ---: | --- |",
    ]
    for command in payload["commands"]:
        signals = ", ".join(command.get("signals", [])) or "-"
        lines.append(f"| {command['label']} | `{command['status']}` | {command.get('exit_code')} | {signals} |")
    if payload["hygiene"].get("patch_leftovers"):
        lines.extend(["", "## Patch Leftovers", ""])
        for item in payload["hygiene"]["patch_leftovers"][:30]:
            lines.append(f"- `{item['path']}`")
    lines.append("")
    return "\n".join(lines)


def collect_files(repo: Path, extensions: set[str], roots: list[str] | None = None) -> list[Path]:
    files: list[Path] = []
    search_roots = [repo / root for root in roots] if roots else [repo]
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions and not is_skipped(path, repo):
                files.append(path)
    return sorted(files)


def walk_files(repo: Path):
    for path in repo.rglob("*"):
        if path.is_file() and not is_skipped(path, repo):
            yield path


def is_skipped(path: Path, repo: Path) -> bool:
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in rel.parts)


def command_display(command: list[str]) -> str:
    return " ".join(quote_arg(part) for part in command)


def quote_arg(part: str) -> str:
    if not part or any(char.isspace() for char in part):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def tail(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def decode_timeout_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


def safe_slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value]
    slug = "".join(chars).strip("_")
    return slug or "quality"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
