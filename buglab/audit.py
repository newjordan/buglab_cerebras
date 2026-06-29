from __future__ import annotations

import csv
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.ignore import should_skip_common_path
from buglab.project import discover_targets
from buglab.api import run_loops
from buglab.reporting import Finding
from buglab.reporting import ReportBuilder
from buglab.reporting import write_json
from buglab.sectors import docs_signals
from buglab.sectors import safe_slug
from buglab.sectors import test_signals


@dataclass(frozen=True)
class RepoAuditConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    run_name: str = "buglab_audit"
    targets: list[str] | None = None
    loops: int = 1
    profiles: list[str] | None = None
    max_clicks: int = 12
    include_browser: bool = True
    include_docs: bool = True
    include_tests: bool = True
    include_config: bool = True
    build_report_index: bool = True
    force_init: bool = True


def audit_repo(config: RepoAuditConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    config = config or RepoAuditConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    run_id = f"{config.run_name}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    artifacts: dict[str, str] = {}

    if config.include_browser:
        rows.extend(run_browser_audit(config, repo, output_root, artifacts))
    if config.include_docs:
        rows.extend(run_docs_audit(repo))
    if config.include_tests:
        rows.extend(run_tests_audit(repo))
    if config.include_config:
        rows.extend(run_config_audit(repo))

    summary = summarize_audit_rows(rows)
    csv_path = out_dir / "repo_audit_rows.csv"
    json_path = out_dir / "repo_audit.json"
    findings_csv_path = out_dir / "findings.csv"
    findings_jsonl_path = out_dir / "findings.jsonl"
    finding_records = audit_finding_records(rows)
    case_index_path = write_case_bundles(out_dir, repo, finding_records)
    write_rows(csv_path, rows)
    write_findings_csv(findings_csv_path, finding_records)
    write_findings_jsonl(findings_jsonl_path, finding_records)
    write_json(
        json_path,
        {
            "schema_version": "buglab.repo_audit.v1",
            "run_id": run_id,
            "repo": str(repo),
            "summary": summary,
            "rows": rows,
            "findings": finding_records,
            "artifacts": artifacts,
        },
    )
    manifest = write_audit_report(
        run_id=run_id,
        repo=repo,
        out_dir=out_dir,
        csv_path=csv_path,
        json_path=json_path,
        findings_csv_path=findings_csv_path,
        findings_jsonl_path=findings_jsonl_path,
        case_index_path=case_index_path,
        rows=rows,
        finding_records=finding_records,
        summary=summary,
        artifacts=artifacts,
    )
    index_result = None
    if config.build_report_index:
        from buglab.api import build_index

        index_result = build_index(repo=repo, output=output_root)

    return {
        "run_id": run_id,
        "output_dir": str(out_dir),
        "summary": summary,
        "rows": rows,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "findings_csv_path": str(findings_csv_path),
        "findings_jsonl_path": str(findings_jsonl_path),
        "case_index_path": str(case_index_path),
        "report_path": str(out_dir / "report.html"),
        "manifest": manifest,
        "index": index_result,
    }


def run_browser_audit(
    config: RepoAuditConfig,
    repo: Path,
    output_root: Path,
    artifacts: dict[str, str],
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    targets = config.targets or discover_targets(repo)
    existing_targets = [target for target in targets if target.startswith(("http://", "https://")) or (repo / target).exists()]
    if not existing_targets:
        return [
            audit_row(
                sector="browser",
                runner="playwright",
                target=";".join(targets),
                status="skipped",
                signals=["no_browser_entrypoint_found"],
                elapsed_ms=elapsed_ms(started),
            )
        ]
    rows: list[dict[str, Any]] = []
    for target in existing_targets:
        target_started = time.perf_counter()
        try:
            result = run_loops(
                target=target,
                repo=repo,
                output=output_root,
                loops=config.loops,
                profiles=config.profiles or ["balanced"],
                max_clicks=config.max_clicks,
                run_name=f"{config.run_name}_browser_{safe_slug(target)}",
            )
        except Exception as exc:
            rows.append(
                audit_row(
                    sector="browser",
                    runner="playwright",
                    target=target,
                    status="failed",
                    signals=[f"browser_scan_error:{type(exc).__name__}:{exc}"],
                    elapsed_ms=elapsed_ms(target_started),
                )
            )
            continue
        artifacts[f"browser_{safe_slug(target)}_csv"] = result["csv_path"]
        artifacts[f"browser_{safe_slug(target)}_json"] = result["json_path"]
        summary = result.get("summary", {})
        signals = browser_signals(summary)
        rows.append(
            audit_row(
                sector="browser",
                runner="playwright",
                target=target,
                status="failed" if signals else "passed",
                signals=signals,
                elapsed_ms=elapsed_ms(target_started),
                artifact=result["json_path"],
            )
        )
    if not rows:
        rows.append(
            audit_row(
                sector="browser",
                runner="playwright",
                target=";".join(existing_targets),
                status="skipped",
                signals=["no_browser_targets_ran"],
                elapsed_ms=elapsed_ms(started),
            )
        )
    return rows


def browser_signals(summary: dict[str, Any]) -> list[str]:
    signals = []
    bug_candidates = int(summary.get("total_bug_candidates", 0))
    failure_signals = int(summary.get("total_failure_signals", 0))
    if bug_candidates:
        signals.append(f"browser_bug_candidates:{bug_candidates}")
    if failure_signals:
        signals.append(f"browser_failure_signals:{failure_signals}")
    return signals


def run_docs_audit(repo: Path) -> list[dict[str, Any]]:
    rows = []
    for path in discover_files(repo, ["*.md", "*.markdown"], limit=80):
        started = time.perf_counter()
        rel = path.relative_to(repo).as_posix()
        signals = docs_signals(
            {
                "id": safe_slug(rel),
                "target_path": rel,
                "placeholder_patterns": ["TODO", "TBD", "FIXME", "{{", "lorem ipsum"],
            },
            repo,
        )
        rows.append(
            audit_row(
                sector="docs",
                runner="docs",
                target=rel,
                status="failed" if signals else "passed",
                signals=signals,
                elapsed_ms=elapsed_ms(started),
            )
        )
    if not rows:
        rows.append(audit_row(sector="docs", runner="docs", target="", status="skipped", signals=["no_markdown_docs_found"]))
    return rows


def run_tests_audit(repo: Path) -> list[dict[str, Any]]:
    test_files = discover_files(repo, ["test*.py", "*_test.py", "*_tests.py"], limit=200)
    if not test_files:
        return [audit_row(sector="tests", runner="unittest", target="", status="skipped", signals=["no_python_test_files_found"])]
    started = time.perf_counter()
    start_dir = "tests" if (repo / "tests").is_dir() else "."
    command = f"python -m unittest discover -s {start_dir} -p test*.py"
    try:
        proc = subprocess.run(command, cwd=repo, shell=True, capture_output=True, text=True, timeout=30)
        signals = test_signals(
            proc,
            {
                "expected_bug_classes": [
                    "failing_assertion",
                    "unhandled_exception",
                    "skipped_critical_test",
                ],
                "required_output_patterns": [],
            },
        )
        signals = normalize_test_signals(f"{proc.stdout}\n{proc.stderr}", signals)
        if proc.returncode != 0 and not signals:
            signals.append(f"test_command_failed:{proc.returncode}")
        ran_count = parsed_unittest_count(f"{proc.stdout}\n{proc.stderr}")
        if test_files and ran_count == 0:
            signals.append(f"no_tests_discovered:files={len(test_files)}")
        elif ran_count and ran_count < len(test_files):
            signals.append(f"unittest_discovery_shortfall:ran={ran_count}:files={len(test_files)}")
    except subprocess.TimeoutExpired:
        signals = ["test_timeout:30s"]
    rows = [
        audit_row(
            sector="tests",
            runner="unittest",
            target=f"{len(test_files)} python test files",
            command=command,
            status="failed" if signals else "passed",
            signals=signals,
            elapsed_ms=elapsed_ms(started),
        )
    ]
    rows.extend(run_test_file_audit(repo, test_files[:40]))
    if len(test_files) > 40:
        rows.append(
            audit_row(
                sector="tests",
                runner="test_static",
                target=f"{len(test_files) - 40} python test files",
                status="skipped",
                signals=["per_file_test_probe_limit_reached:40"],
            )
        )
    return rows


def run_test_file_audit(repo: Path, test_files: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in test_files:
        started = time.perf_counter()
        rel = path.relative_to(repo).as_posix()
        command = f"python -m unittest {rel}"
        try:
            proc = subprocess.run(command, cwd=repo, shell=True, capture_output=True, text=True, timeout=10)
            signals = test_signals(
                proc,
                {
                    "expected_bug_classes": [
                        "failing_assertion",
                        "unhandled_exception",
                        "skipped_critical_test",
                        "missing_test_coverage",
                    ],
                    "min_test_count": 1,
                    "required_output_patterns": [],
                },
            )
            signals = normalize_test_signals(f"{proc.stdout}\n{proc.stderr}", signals)
            signals.extend(static_test_file_signals(path))
            if proc.returncode != 0 and not signals:
                signals.append(f"test_command_failed:{proc.returncode}")
        except subprocess.TimeoutExpired:
            signals = ["test_file_timeout:10s"]
        except UnicodeDecodeError as exc:
            signals = [f"test_file_decode_error:{exc}"]
        rows.append(
            audit_row(
                sector="tests",
                runner="unittest_file",
                target=rel,
                command=command,
                status="failed" if signals else "passed",
                signals=sorted(set(signals)),
                elapsed_ms=elapsed_ms(started),
            )
        )
    return rows


def static_test_file_signals(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    signals: list[str] = []
    test_defs = re.findall(r"^\s*def\s+(test\w*)\s*\(", text, flags=re.MULTILINE)
    if not test_defs:
        signals.append("missing_test_coverage:no_test_functions")
    if re.search(r"@\s*(?:unittest\.)?skip(?:If|Unless)?\b|pytest\.mark\.skip", text):
        signals.append("skipped_critical_test:static_skip_decorator")
    if test_defs and not re.search(r"\bassert\b|self\.assert\w+\(", text):
        signals.append("missing_test_coverage:no_assertions")
    if re.search(r"\b(?:TODO|FIXME|TBD)\b", text):
        signals.append("missing_test_coverage:test_placeholder")
    return signals


def normalize_test_signals(output: str, signals: list[str]) -> list[str]:
    lowered = output.lower()
    normalized = list(signals)
    if "failing_assertion:test_failure" in normalized and "assertionerror" not in lowered and not re.search(r"(^|\n)FAIL:", output):
        normalized.remove("failing_assertion:test_failure")
    return sorted(set(normalized))


def run_config_audit(repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in discover_files(repo, ["*.json"], limit=120):
        if ".buglab/" in path.relative_to(repo).as_posix():
            continue
        started = time.perf_counter()
        rel = path.relative_to(repo).as_posix()
        signals = []
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            signals.append(f"json_decode_error:{exc}")
        except json.JSONDecodeError as exc:
            signals.append(f"invalid_json:line={exc.lineno}:column={exc.colno}")
        rows.append(
            audit_row(
                sector="config",
                runner="json",
                target=rel,
                status="failed" if signals else "passed",
                signals=signals,
                elapsed_ms=elapsed_ms(started),
            )
        )
    rows.extend(env_example_rows(repo))
    rows.extend(config_text_rows(repo))
    if not rows:
        rows.append(audit_row(sector="config", runner="config", target="", status="skipped", signals=["no_config_files_found"]))
    return rows


def env_example_rows(repo: Path) -> list[dict[str, Any]]:
    examples = sorted(
        {
            path
            for pattern in [".env.example", ".env.sample", ".env.template", "*.env.example", "*.env.sample", "*.env.template"]
            for path in repo.rglob(pattern)
            if path.is_file() and not should_skip_path(path.relative_to(repo).as_posix())
        },
        key=lambda item: item.as_posix(),
    )
    if not examples:
        return []
    rows = []
    for example in examples[:40]:
        started = time.perf_counter()
        rel = example.relative_to(repo).as_posix()
        example_keys = env_keys(example)
        signals = env_value_signals(example, "example", allow_placeholders=True)
        if not example_keys:
            signals.append("env_example_empty")
        rows.append(
            audit_row(
                sector="config",
                runner="env",
                target=rel,
                status="failed" if signals else "passed",
                signals=sorted(set(signals)),
                elapsed_ms=elapsed_ms(started),
            )
        )
    if len(examples) > 40:
        rows.append(
            audit_row(
                sector="config",
                runner="env",
                target=f"{len(examples) - 40} env example files",
                status="skipped",
                signals=["env_example_probe_limit_reached:40"],
            )
        )
    return rows


def env_actual_path(example: Path) -> Path:
    name = example.name
    for suffix in [".example", ".sample", ".template"]:
        if name.endswith(suffix):
            return example.with_name(name[: -len(suffix)])
    if name.startswith(".env."):
        return example.with_name(".env")
    return example.with_name(".env")


def env_keys(path: Path) -> set[str]:
    keys = set()
    if not path.exists():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def env_value_signals(path: Path, label: str, *, allow_placeholders: bool = False) -> list[str]:
    signals: list[str] = []
    values = env_values(path)
    for key, value in values.items():
        upper_key = key.upper()
        lower_value = value.strip().strip("\"'").lower()
        if not allow_placeholders and (
            not value.strip() or lower_value in {"changeme", "change_me", "todo", "tbd", "example", "placeholder"}
        ):
            signals.append(f"env_placeholder_value:{label}:{key}")
        if upper_key in {"DEBUG", "FLASK_DEBUG", "DJANGO_DEBUG"} and lower_value == "true":
            signals.append(f"env_debug_enabled:{label}:{key}")
        if (
            not allow_placeholders
            and any(token in upper_key for token in ["SECRET", "TOKEN", "PASSWORD", "API_KEY"])
            and len(value.strip().strip("\"'")) < 12
        ):
            signals.append(f"env_secret_too_short:{label}:{key}")
    return signals


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def config_text_rows(repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    patterns = ["*.yml", "*.yaml", "Dockerfile", "docker-compose*.yml", "docker-compose*.yaml", "*.toml", "*.ini", "*.cfg"]
    for path in discover_files(repo, patterns, limit=160):
        rel = path.relative_to(repo).as_posix()
        if ".buglab/" in rel:
            continue
        started = time.perf_counter()
        signals = config_text_signals(path)
        if not signals:
            continue
        rows.append(
            audit_row(
                sector="config",
                runner="config_text",
                target=rel,
                status="failed",
                signals=signals,
                elapsed_ms=elapsed_ms(started),
            )
        )
    return rows


def config_text_signals(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [f"config_decode_error:{exc}"]
    lower_name = path.name.lower()
    lower_path = path.as_posix().lower()
    signals: list[str] = []
    latest_images = re.findall(r"(?im)^\s*image:\s*[^\s#]+:latest\b", text)
    if latest_images:
        signals.append(f"iac_unpinned_latest_image:{len(latest_images)}")
    if re.search(r"(?im)^\s*FROM\s+\S+:latest\b", text):
        signals.append("iac_unpinned_dockerfile_base:latest")
    floating_actions = re.findall(r"(?im)^\s*uses:\s*[^@\s]+@(main|master|HEAD)\b", text)
    if floating_actions:
        signals.append(f"iac_unpinned_workflow_action:{len(floating_actions)}")
    if "env_file:" in text:
        missing = missing_env_files(path, text)
        if missing:
            signals.append(f"iac_missing_env_file:{','.join(missing[:6])}")
    if is_compose_like(lower_name, lower_path):
        if "healthcheck:" not in text and re.search(r"(?im)^\s*services:\s*$", text):
            signals.append("iac_missing_healthcheck")
        if re.search(r'(?im)^\s*-\s*["\']?80:', text):
            signals.append("iac_privileged_host_port:80")
    if re.search(r"(?im)^\s*(password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^'\"\s#]{1,11}\s*$", text):
        signals.append("config_secret_literal_too_short")
    return sorted(set(signals))


def missing_env_files(path: Path, text: str) -> list[str]:
    candidates: set[str] = set()
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("env_file:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if ".env" in value:
                candidates.add(value)
        elif stripped.startswith("-") and ".env" in stripped:
            candidates.add(stripped[1:].strip().strip("\"'"))
    candidates = sorted(candidates)
    return [candidate for candidate in candidates if not (path.parent / candidate).exists()]


def is_compose_like(name: str, rel: str) -> bool:
    return "compose" in name or "docker-compose" in name or "/compose" in rel


def parsed_unittest_count(output: str) -> int:
    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    if not match:
        return 0
    return int(match.group(1))


def discover_files(repo: Path, patterns: list[str], *, limit: int) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        for path in repo.rglob(pattern):
            rel = path.relative_to(repo).as_posix()
            if should_skip_path(rel) or not path.is_file():
                continue
            found.append(path)
            if len(found) >= limit:
                return sorted(set(found), key=lambda item: item.as_posix())
    return sorted(set(found), key=lambda item: item.as_posix())


def should_skip_path(rel: str) -> bool:
    return should_skip_common_path(rel, skip_sector_fixtures=True)


def audit_row(
    *,
    sector: str,
    runner: str,
    target: str,
    status: str,
    signals: list[str],
    elapsed_ms: int = 0,
    command: str = "",
    artifact: str = "",
) -> dict[str, Any]:
    return {
        "sector": sector,
        "runner": runner,
        "target": target,
        "status": status,
        "signal_count": 0 if status == "skipped" else len(signals),
        "signals": json.dumps(signals, sort_keys=True),
        "command": command,
        "elapsed_ms": elapsed_ms,
        "artifact": artifact,
    }


def summarize_audit_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_sector: dict[str, dict[str, int]] = {}
    for row in rows:
        sector = str(row["sector"])
        item = by_sector.setdefault(sector, {"targets": 0, "failed": 0, "signals": 0, "skipped": 0})
        item["targets"] += 1
        if row["status"] != "skipped":
            item["signals"] += int(row["signal_count"])
        if row["status"] == "failed":
            item["failed"] += 1
        if row["status"] == "skipped":
            item["skipped"] += 1
    return {
        "targets": len(rows),
        "failed_targets": sum(1 for row in rows if row["status"] == "failed"),
        "skipped_targets": sum(1 for row in rows if row["status"] == "skipped"),
        "total_signals": sum(int(row["signal_count"]) for row in rows if row["status"] != "skipped"),
        "sectors": by_sector,
    }


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def audit_finding_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for index, row in enumerate(rows, start=1):
        if row["status"] != "failed":
            continue
        signals = json.loads(str(row["signals"]))
        sector = str(row["sector"])
        record = {
            "finding_id": f"AUDIT-{index:03d}",
            "severity": severity_for_sector(sector),
            "status": "open",
            "category": f"{sector}_agent",
            "sector": sector,
            "runner": row.get("runner", ""),
            "target": row.get("target", ""),
            "signal_count": row.get("signal_count", 0),
            "signals": signals,
            "command": row.get("command", ""),
            "artifact": row.get("artifact", ""),
            "case_path": "",
            "case_json_path": "",
            "reproduction_steps": reproduction_steps(row),
            "expected": "The target should pass its sector-specific bug hunt without failure signals.",
            "actual": "; ".join(signals),
            "fix_hypothesis": fix_hypothesis(sector),
        }
        records.append(record)
    return records


def write_findings_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "finding_id",
        "severity",
        "status",
        "category",
        "sector",
        "runner",
        "target",
        "signal_count",
        "signals",
        "command",
        "artifact",
        "case_path",
        "case_json_path",
        "reproduction_steps",
        "expected",
        "actual",
        "fix_hypothesis",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["signals"] = json.dumps(row.get("signals", []), sort_keys=True)
            row["reproduction_steps"] = json.dumps(row.get("reproduction_steps", []))
            writer.writerow(row)


def write_findings_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def write_case_bundles(out_dir: Path, repo: Path, records: list[dict[str, Any]]) -> Path:
    cases_dir = out_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    for record in records:
        finding_id = str(record["finding_id"])
        stem = safe_slug(finding_id)
        json_path = cases_dir / f"{stem}.json"
        markdown_path = cases_dir / f"{stem}.md"
        record["case_path"] = str(markdown_path)
        record["case_json_path"] = str(json_path)
        payload = {
            "schema_version": "buglab.case.v1",
            "finding": record,
            "repo": str(repo),
        }
        write_json(json_path, payload)
        markdown_path.write_text(render_case_markdown(record, repo), encoding="utf-8")
        index.append(
            {
                "finding_id": finding_id,
                "severity": record["severity"],
                "sector": record["sector"],
                "target": record["target"],
                "case_path": str(markdown_path),
                "case_json_path": str(json_path),
            }
        )
    index_path = cases_dir / "index.json"
    write_json(index_path, {"schema_version": "buglab.case_index.v1", "repo": str(repo), "cases": index})
    return index_path


def render_case_markdown(record: dict[str, Any], repo: Path) -> str:
    signals = "\n".join(f"- {signal}" for signal in record.get("signals", [])) or "- none"
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(record.get("reproduction_steps", []), start=1)) or "1. Review the listed audit signals."
    command = str(record.get("command") or "")
    command_block = f"\n## Command\n\n```powershell\n{command}\n```\n" if command else ""
    artifact = str(record.get("artifact") or "")
    artifact_line = f"\nArtifact: `{artifact}`\n" if artifact else ""
    return f"""# {record['finding_id']}: {record['sector']} Bug Hunt Case

Repo: `{repo}`
Target: `{record.get('target', '')}`
Runner: `{record.get('runner', '')}`
Severity: `{record.get('severity', '')}`
Status: `{record.get('status', '')}`{artifact_line}
## Signals

{signals}

## Reproduction

{steps}
{command_block}
## Expected

{record.get('expected', '')}

## Actual

{record.get('actual', '')}

## Fix Hypothesis

{record.get('fix_hypothesis', '')}
"""


def write_audit_report(
    *,
    run_id: str,
    repo: Path,
    out_dir: Path,
    csv_path: Path,
    json_path: Path,
    findings_csv_path: Path,
    findings_jsonl_path: Path,
    case_index_path: Path,
    rows: list[dict[str, Any]],
    finding_records: list[dict[str, Any]],
    summary: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.repo_audit",
        target=str(repo),
        output_dir=out_dir,
        base_dir=repo,
        status="failed" if summary["failed_targets"] else "passed",
        title="BugLab Repo Audit",
        summary=f"{summary['total_signals']} signals across {summary['targets']} audited targets.",
    )
    for key in ["targets", "failed_targets", "skipped_targets", "total_signals"]:
        builder.metric(key, summary[key])
    for sector, values in summary["sectors"].items():
        builder.metric(f"{sector}_signals", values["signals"])
        builder.metric(f"{sector}_failed_targets", values["failed"])
    builder.artifact("repo_audit_rows", csv_path, kind="csv")
    builder.artifact("repo_audit_json", json_path, kind="json")
    builder.artifact("normalized_findings_csv", findings_csv_path, kind="csv")
    builder.artifact("normalized_findings_jsonl", findings_jsonl_path, kind="jsonl")
    builder.artifact("case_index", case_index_path, kind="json")
    for name, path in artifacts.items():
        builder.artifact(name, path, kind=Path(path).suffix.lstrip(".") or "file")
    rows_by_key = {(str(row.get("sector")), str(row.get("runner")), str(row.get("target"))): row for row in rows}
    for record in finding_records:
        signals = [str(signal) for signal in record["signals"]]
        row = rows_by_key.get((str(record["sector"]), str(record["runner"]), str(record["target"])), {})
        builder.finding(
            Finding(
                id=str(record["finding_id"]),
                title=f"{record['sector']} audit found signals in {record['target'] or record['runner']}",
                severity=str(record["severity"]),
                status=str(record["status"]),
                category=str(record["category"]),
                signals=signals,
                evidence_ids=[],
                reproduction_steps=[f"Open BugLab case `{record['case_path']}`."] + [str(step) for step in record["reproduction_steps"]],
                command=str(record.get("command", "")),
                artifact=str(record.get("artifact", "")),
                expected=str(record["expected"]),
                actual=str(record["actual"]),
                fix_hypothesis=str(record["fix_hypothesis"]),
            )
        )
    return builder.write()


def reproduction_steps(row: dict[str, Any]) -> list[str]:
    if row.get("command"):
        return [f"Run `{row['command']}` from the repo root.", "Inspect stdout, stderr, and generated BugLab reports."]
    if row.get("artifact"):
        return [f"Open artifact `{row['artifact']}`.", "Inspect the linked run reports."]
    if row.get("target"):
        return [f"Inspect `{row['target']}` from the repo root.", "Review the listed audit signals."]
    return ["Review the listed audit signals."]


def severity_for_sector(sector: str) -> str:
    return {"browser": "high", "tests": "high", "config": "medium", "docs": "medium"}.get(sector, "medium")


def fix_hypothesis(sector: str) -> str:
    return {
        "browser": "Repair broken controls, runtime errors, bad state transitions, or visual interaction failures.",
        "tests": "Fix failing assertions, unhandled exceptions, skipped critical checks, or missing test coverage.",
        "config": "Repair parse errors, missing env keys, or mismatched local configuration contracts.",
        "docs": "Repair local links, anchors, image paths, placeholders, or release-critical copy.",
    }.get(sector, "Inspect the sector output and add a focused detector or repair path.")


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
