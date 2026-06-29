from __future__ import annotations

import csv
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from buglab.api import run_loops
from buglab.reporting import Finding
from buglab.reporting import ReportBuilder
from buglab.reporting import write_json


@dataclass(frozen=True)
class SectorBenchmarkConfig:
    manifest: str | Path
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    loops: int = 3
    profiles: list[str] | None = None
    max_clicks: int = 30
    run_name: str = "sector"


def load_manifest(path: str | Path, repo: str | Path = ".") -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    manifest_path = Path(path)
    if not manifest_path.is_absolute():
        manifest_path = repo_path / manifest_path
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["_manifest_path"] = str(manifest_path)
    return payload


def run_sector_benchmark(config: SectorBenchmarkConfig) -> dict[str, Any]:
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    manifest = load_manifest(config.manifest, repo)
    fixtures = manifest.get("fixtures", [])
    rows: list[dict[str, Any]] = []

    for fixture in fixtures:
        runner = fixture.get("runner", manifest.get("runner", "browser"))
        if ("command" in fixture or "suggested_command" in fixture) and "runner" not in fixture and "runner" not in manifest:
            runner = "command"
        if runner == "browser":
            rows.extend(run_browser_fixture(config, repo, output_root, manifest, fixture))
        elif runner == "command":
            rows.append(run_command_fixture(config, repo, output_root, manifest, fixture))
        elif runner == "docs":
            rows.append(run_docs_fixture(config, repo, output_root, manifest, fixture))
        elif runner == "tests":
            rows.append(run_tests_fixture(config, repo, output_root, manifest, fixture))
        else:
            rows.append(skipped_row(manifest, fixture, f"unknown_runner:{runner}"))

    summary = summarize_sector_rows(rows)
    output_root.mkdir(parents=True, exist_ok=True)
    slug = safe_slug(manifest.get("sector", "sector"))
    csv_path = output_root / f"{config.run_name}_{slug}_sector_summary.csv"
    json_path = output_root / f"{config.run_name}_{slug}_sector_summary.json"
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    write_json(json_path, {"manifest": manifest, "summary": summary, "rows": rows})
    write_sector_report(manifest, summary, rows, output_root, repo, config.run_name)
    return {"summary": summary, "rows": rows, "csv_path": str(csv_path), "json_path": str(json_path)}


def run_browser_fixture(
    config: SectorBenchmarkConfig,
    repo: Path,
    output_root: Path,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
) -> list[dict[str, Any]]:
    target = fixture_target(fixture)
    result = run_loops(
        target=target,
        repo=repo,
        output=output_root,
        loops=config.loops,
        profiles=config.profiles,
        max_clicks=config.max_clicks,
        run_name=f"{config.run_name}_{safe_slug(fixture.get('id', Path(target).stem))}",
    )
    rows = []
    expected_min = expected_min_bugs(fixture)
    expected_classes = expected_bug_classes(fixture)
    for row in result["rows"]:
        found = max(int(row["bug_candidate_count"]), int(row.get("failure_signal_count", row["bug_candidate_count"])))
        signals = parse_row_signals(row)
        scoring = score_signals(signals, expected_classes, expected_min)
        rows.append(
            {
                "sector": manifest.get("sector", ""),
                "fixture_id": fixture.get("id", target),
                "runner": "browser",
                "loop": row["loop"],
                "profile": row["profile"],
                "target": target,
                "command": "",
                "expected_min_bugs": expected_min,
                "expected_bug_classes": "|".join(expected_classes),
                "found_bugs": found,
                "unique_signal_count": scoring["unique_signal_count"],
                "duplicate_signal_ratio": scoring["duplicate_signal_ratio"],
                "expected_class_hits": scoring["expected_class_hits"],
                "expected_class_total": scoring["expected_class_total"],
                "expected_class_recall": scoring["expected_class_recall"],
                "detected_expected": scoring["detected_expected"],
                "coverage_score": scoring["coverage_score"],
                "elapsed_ms": row["elapsed_ms"],
                "run_id": row["run_id"],
                "output_dir": row["output_dir"],
                "notes": ";".join(scoring["matched_classes"]),
            }
        )
    return rows


def run_command_fixture(
    config: SectorBenchmarkConfig,
    repo: Path,
    output_root: Path,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    command = fixture_command(fixture)
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=repo, shell=True, capture_output=True, text=True, timeout=int(fixture.get("timeout_sec", 10)))
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    signals = command_signals(proc, fixture, repo, command)
    expected_min = expected_min_bugs(fixture)
    expected_classes = expected_bug_classes(fixture)
    found = len(signals)
    scoring = score_signals(signals, expected_classes, expected_min)
    run_id = f"{config.run_name}_{safe_slug(fixture.get('id', 'command'))}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        out_dir / "command_report.json",
        {
            "fixture": fixture,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "signals": signals,
            "elapsed_ms": elapsed_ms,
        },
    )
    write_command_report(manifest, fixture, signals, proc, out_dir, repo, run_id, elapsed_ms)
    return {
        "sector": manifest.get("sector", ""),
        "fixture_id": fixture.get("id", command),
        "runner": "command",
        "loop": 1,
        "profile": "command",
        "target": fixture_target(fixture),
        "command": command,
        "expected_min_bugs": expected_min,
        "expected_bug_classes": "|".join(expected_classes),
        "found_bugs": found,
        "unique_signal_count": scoring["unique_signal_count"],
        "duplicate_signal_ratio": scoring["duplicate_signal_ratio"],
        "expected_class_hits": scoring["expected_class_hits"],
        "expected_class_total": scoring["expected_class_total"],
        "expected_class_recall": scoring["expected_class_recall"],
        "detected_expected": scoring["detected_expected"],
        "coverage_score": scoring["coverage_score"],
        "elapsed_ms": elapsed_ms,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "notes": ";".join(signals),
    }


def run_docs_fixture(
    config: SectorBenchmarkConfig,
    repo: Path,
    output_root: Path,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    target = fixture_target(fixture)
    started = time.perf_counter()
    signals = docs_signals(fixture, repo)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    expected_min = expected_min_bugs(fixture)
    expected_classes = expected_bug_classes(fixture)
    found = len(signals)
    scoring = score_signals(signals, expected_classes, expected_min)
    run_id = f"{config.run_name}_{safe_slug(fixture.get('id', 'docs'))}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        out_dir / "docs_report.json",
        {
            "fixture": fixture,
            "target": target,
            "signals": signals,
            "elapsed_ms": elapsed_ms,
        },
    )
    write_docs_report(manifest, fixture, signals, out_dir, repo, run_id, elapsed_ms)
    return {
        "sector": manifest.get("sector", ""),
        "fixture_id": fixture.get("id", target),
        "runner": "docs",
        "loop": 1,
        "profile": "docs",
        "target": target,
        "command": "",
        "expected_min_bugs": expected_min,
        "expected_bug_classes": "|".join(expected_classes),
        "found_bugs": found,
        "unique_signal_count": scoring["unique_signal_count"],
        "duplicate_signal_ratio": scoring["duplicate_signal_ratio"],
        "expected_class_hits": scoring["expected_class_hits"],
        "expected_class_total": scoring["expected_class_total"],
        "expected_class_recall": scoring["expected_class_recall"],
        "detected_expected": scoring["detected_expected"],
        "coverage_score": scoring["coverage_score"],
        "elapsed_ms": elapsed_ms,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "notes": ";".join(signals),
    }


def run_tests_fixture(
    config: SectorBenchmarkConfig,
    repo: Path,
    output_root: Path,
    manifest: dict[str, Any],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    command = fixture_command(fixture)
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=repo, shell=True, capture_output=True, text=True, timeout=int(fixture.get("timeout_sec", 10)))
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    signals = test_signals(proc, fixture)
    expected_min = expected_min_bugs(fixture)
    expected_classes = expected_bug_classes(fixture)
    found = len(signals)
    scoring = score_signals(signals, expected_classes, expected_min)
    run_id = f"{config.run_name}_{safe_slug(fixture.get('id', 'tests'))}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        out_dir / "test_report.json",
        {
            "fixture": fixture,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "signals": signals,
            "elapsed_ms": elapsed_ms,
        },
    )
    write_tests_report(manifest, fixture, signals, proc, out_dir, repo, run_id, elapsed_ms)
    return {
        "sector": manifest.get("sector", ""),
        "fixture_id": fixture.get("id", command),
        "runner": "tests",
        "loop": 1,
        "profile": "tests",
        "target": fixture_target(fixture),
        "command": command,
        "expected_min_bugs": expected_min,
        "expected_bug_classes": "|".join(expected_classes),
        "found_bugs": found,
        "unique_signal_count": scoring["unique_signal_count"],
        "duplicate_signal_ratio": scoring["duplicate_signal_ratio"],
        "expected_class_hits": scoring["expected_class_hits"],
        "expected_class_total": scoring["expected_class_total"],
        "expected_class_recall": scoring["expected_class_recall"],
        "detected_expected": scoring["detected_expected"],
        "coverage_score": scoring["coverage_score"],
        "elapsed_ms": elapsed_ms,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "notes": ";".join(signals),
    }


def command_signals(proc: subprocess.CompletedProcess[str], fixture: dict[str, Any], repo: Path, command: str) -> list[str]:
    signals: list[str] = []
    expected_classes = set(fixture.get("expected_bug_classes", []))
    expected_exit = fixture.get("expected_exit_code")
    if expected_exit is not None and proc.returncode != int(expected_exit):
        signals.append(f"exit_code:{proc.returncode}:expected:{expected_exit}")
    if "bad_exit_code" in expected_classes and proc.returncode != 0:
        signals.append(f"bad_exit_code:nonzero_success_path:{proc.returncode}")
    if fixture.get("expect_stderr") and not proc.stderr.strip():
        signals.append("missing_stderr")
    for pattern in fixture.get("required_stdout", []):
        if pattern not in proc.stdout:
            signals.append(f"missing_stdout:{pattern}")
    for pattern in fixture.get("forbidden_stdout", []):
        if pattern in proc.stdout:
            signals.append(f"forbidden_stdout:{pattern}")
    for pattern in fixture.get("required_stderr", []):
        if pattern not in proc.stderr:
            signals.append(f"missing_stderr:{pattern}")
    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    if "schema_mismatch" in expected_classes and any(token in combined for token in ["keyerror", "traceback", "schema", "missing column"]):
        signals.append("schema_mismatch:runtime_signal")
    if "missing_file_handling" in expected_classes:
        if any(token in combined for token in ["no such file", "filenotfounderror", "not found"]):
            signals.append("missing_file_handling:runtime_signal")
        signals.extend(missing_file_probe(fixture, repo, command))
    if "silent_data_loss" in expected_classes:
        if any(token in combined for token in ["dropped", "skipped", "duplicate", "loss"]):
            signals.append("silent_data_loss:output_signal")
        signals.extend(artifact_loss_signals(fixture, repo, command))
        if proc.returncode != 0 and output_path_from_command(command, repo) and not output_path_from_command(command, repo).exists():
            signals.append("silent_data_loss:output_missing_after_failure")
    if "bad_csv_parsing" in expected_classes:
        signals.extend(csv_parsing_signals(fixture, repo, command))
    if "schema_mismatch" in expected_classes:
        signals.extend(artifact_schema_signals(fixture, repo, command))
    if "flaky_timestamp_order_assumption" in expected_classes:
        signals.extend(timestamp_order_signals(fixture, repo, command))
    if proc.returncode != 0:
        signals.append(f"nonzero_exit:{proc.returncode}")
    return sorted(set(signals))


def test_signals(proc: subprocess.CompletedProcess[str], fixture: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    expected_classes = set(fixture.get("expected_bug_classes", []))
    combined = f"{proc.stdout}\n{proc.stderr}"
    lower = combined.lower()
    if proc.returncode != 0:
        signals.append(f"nonzero_test_exit:{proc.returncode}")
    if "failing_assertion" in expected_classes and any(token in lower for token in ["assertionerror", "fail:", "failed"]):
        signals.append("failing_assertion:test_failure")
    has_unittest_error = bool(re.search(r"(^|\n)ERROR:", combined))
    has_runtime_exception = any(token in lower for token in ["keyerror", "typeerror", "valueerror"])
    if "unhandled_exception" in expected_classes and (has_unittest_error or has_runtime_exception):
        signals.append("unhandled_exception:test_error")
    if "skipped_critical_test" in expected_classes and any(token in lower for token in ["skipped=", "skipped", "skiptest"]):
        signals.append("skipped_critical_test:skip_signal")
    if "contract_mismatch" in expected_classes and any(token in lower for token in ["keyerror", "contract", "missing required", "schema"]):
        signals.append("contract_mismatch:test_output")
    minimum_tests = fixture.get("min_test_count")
    if "missing_test_coverage" in expected_classes and minimum_tests is not None:
        ran = parsed_unittest_count(combined)
        if ran < int(minimum_tests):
            signals.append(f"missing_test_coverage:ran={ran}:expected_min={minimum_tests}")
    for pattern in fixture.get("required_output_patterns", []):
        if str(pattern).lower() not in lower:
            signals.append(f"missing_test_output:{pattern}")
    return sorted(set(signals))


def parsed_unittest_count(output: str) -> int:
    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    if not match:
        return 0
    return int(match.group(1))


def docs_signals(fixture: dict[str, Any], repo: Path) -> list[str]:
    target_path = resolve_repo_path(repo, fixture_target(fixture))
    if not target_path.exists():
        return [f"missing_doc_target:{target_path}"]
    text = target_path.read_text(encoding="utf-8")
    signals: list[str] = []
    prose_text = markdown_prose_text(text)
    links = markdown_links(prose_text)
    headings = markdown_heading_anchors(text)
    for label, href, is_image in links:
        if should_ignore_href(href):
            continue
        target_ref, fragment = split_href(href)
        linked_path = target_path if not target_ref else (target_path.parent / target_ref).resolve()
        signal_prefix = "missing_image_asset" if is_image else "missing_local_link"
        if target_ref and not linked_path.exists():
            signals.append(f"{signal_prefix}:{href}:label={label[:40]}")
            continue
        if fragment:
            anchor_source = text if linked_path == target_path else read_text_if_exists(linked_path)
            anchor_set = headings if linked_path == target_path else markdown_heading_anchors(anchor_source)
            if fragment.lower() not in anchor_set:
                signals.append(f"missing_anchor:{href}:label={label[:40]}")
    placeholder_patterns = fixture.get("placeholder_patterns", ["TODO", "TBD", "FIXME", "lorem ipsum", "{{"])
    lower_text = prose_text.lower()
    for pattern in placeholder_patterns:
        if str(pattern).lower() in lower_text:
            signals.append(f"unresolved_placeholder:{pattern}")
    required_terms = [str(term) for term in fixture.get("required_terms", [])]
    for term in required_terms:
        if term.lower() not in lower_text:
            signals.append(f"missing_required_term:{term}")
    return sorted(set(signals))


def markdown_links(text: str) -> list[tuple[str, str, bool]]:
    links: list[tuple[str, str, bool]] = []
    pattern = re.compile(r"(!?)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
    for match in pattern.finditer(text):
        links.append((match.group(2), match.group(3), bool(match.group(1))))
    return links


def markdown_prose_text(text: str) -> str:
    without_fences = re.sub(r"(?ms)^```.*?^```", "", text)
    without_inline_code = re.sub(r"`[^`\n]+`", "", without_fences)
    return without_inline_code


def markdown_heading_anchors(text: str) -> set[str]:
    anchors = set()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = re.sub(r"`([^`]+)`", r"\1", match.group(1))
        heading = re.sub(r"[^a-zA-Z0-9 _-]+", "", heading).strip().lower()
        anchors.add(re.sub(r"\s+", "-", heading))
    return anchors


def should_ignore_href(href: str) -> bool:
    value = href.strip().lower()
    return value.startswith(("http://", "https://", "mailto:", "tel:", "data:"))


def split_href(href: str) -> tuple[str, str]:
    if "#" not in href:
        return href, ""
    target, fragment = href.split("#", 1)
    return target, fragment.strip().lower()


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def resolve_repo_path(repo: Path, target: str) -> Path:
    path = Path(target)
    return path if path.is_absolute() else (repo / path).resolve()


def fixture_target(fixture: dict[str, Any]) -> str:
    return str(fixture.get("target", fixture.get("target_path", "")))


def fixture_command(fixture: dict[str, Any]) -> str:
    return str(fixture.get("command", fixture.get("suggested_command", "")))


def expected_min_bugs(fixture: dict[str, Any]) -> int:
    return int(fixture.get("expected_min_bugs", fixture.get("expected_minimum_bugs", 1)))


def expected_bug_classes(fixture: dict[str, Any]) -> list[str]:
    return [str(item) for item in fixture.get("expected_bug_classes", [])]


def parse_row_signals(row: dict[str, Any]) -> list[str]:
    raw = row.get("failure_signals", "[]")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if not raw:
        return []
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        return [part for part in str(raw).split(";") if part]
    if isinstance(payload, list):
        return [str(item) for item in payload]
    return []


def score_signals(signals: list[str], expected_classes: list[str], expected_min: int) -> dict[str, Any]:
    unique_signals = sorted({normalize_signal(signal) for signal in signals if signal})
    matched_classes = [
        expected_class
        for expected_class in expected_classes
        if any(signal_matches_expected_class(signal, expected_class) for signal in signals)
    ]
    expected_total = len(expected_classes)
    expected_hits = len(matched_classes)
    class_recall = round(expected_hits / expected_total, 3) if expected_total else 0.0
    duplicate_ratio = round(1 - (len(unique_signals) / max(1, len(signals))), 3) if signals else 0.0
    unique_floor = min(expected_min, expected_total or expected_min)
    detected = len(unique_signals) >= expected_min
    if expected_total:
        detected = detected and expected_hits >= unique_floor
    signal_score = min(len(unique_signals) / max(1, expected_min), 1.0)
    coverage_score = signal_score if not expected_total else min(signal_score, class_recall)
    return {
        "unique_signal_count": len(unique_signals),
        "duplicate_signal_ratio": duplicate_ratio,
        "expected_class_hits": expected_hits,
        "expected_class_total": expected_total,
        "expected_class_recall": class_recall,
        "matched_classes": matched_classes,
        "detected_expected": int(detected),
        "coverage_score": round(coverage_score, 3),
    }


def normalize_signal(signal: str) -> str:
    value = str(signal).lower()
    value = value.replace("console.error", "console error")
    value = value.replace("pageerror", "page exception")
    value = value.replace("requestfailed", "request failure")
    value = value.replace("localstorage", "local storage")
    value = re.sub(r"\b\d+(?:\.\d+)?\b", "n", value)
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def signal_matches_expected_class(signal: str, expected_class: str) -> bool:
    signal_text = normalized_match_text(signal)
    expected_text = normalized_match_text(expected_class)
    if expected_text in signal_text:
        return True
    expected_tokens = set(expected_text.split())
    signal_tokens = set(signal_text.split())
    if not expected_tokens:
        return False
    if expected_tokens <= signal_tokens:
        return True
    overlap = expected_tokens & signal_tokens
    return len(overlap) >= min(2, len(expected_tokens))


def normalized_match_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9.]+", " ", str(value).lower())
    replacements = {
        "console.error": "console error",
        "pageerror": "page exception",
        "requestfailed": "request failure",
        "localstorage": "local storage",
        "nonzero": "bad exit code nonzero",
        "filenotfounderror": "missing file handling file not found",
        "no such file": "missing file handling",
        "not found": "missing file handling",
        "quoted comma": "bad csv parsing quoted comma",
        "missing output fields": "schema mismatch missing output fields",
        "input rows": "silent data loss input rows output rows",
        "output missing": "silent data loss output missing",
        "mixed timestamp formats": "flaky timestamp order assumption mixed timestamp formats",
        "semantic no state change": "semantic no state change broken checkout state broken form control",
        "semantic submit no success state": "invalid success path broken checkout state",
        "no destination": "missing link target missing menu links",
        "no route": "missing link target missing menu links",
        "missing details html": "missing link target request failure",
        "chrome error": "missing link target failed load state",
        "access is denied for this document": "failed load state missing link target",
        "text flag could not": "broken form control failed load state",
        "text flag undefined": "broken form control invalid success path",
        "state persisted after error": "local storage invalid state localstorage state duplication optimistic ui rollback",
        "text flag invalid": "form validation bypass invalid success path",
        "text flag failed": "wrong status handling missing empty or retry state failed fetch or mocked endpoint error modal bug",
        "http 503": "wrong status handling missing empty or retry state failed fetch or mocked endpoint error",
        "returned 409": "wrong status handling",
        "returned 422": "wrong status handling form validation bypass",
        "no loaded state": "missing empty or retry state",
        "semantic refresh no loaded state": "missing empty or retry state wrong status handling",
        "click timeout": "click through failure focus close failure menu visibility issue disabled primary action",
        "offscreen interactive": "layout occlusion menu visibility issue",
        "clipped text": "layout occlusion",
        "playwright error": "broken form control click through failure",
        "malformed": "malformed json",
        "parse": "malformed json uncaught parse exception",
        "duplicate": "localstorage state duplication silent data loss",
        "rollback": "optimistic ui rollback",
        "rolled back": "optimistic ui rollback",
        "test failure": "failing assertion",
        "assertionerror": "failing assertion",
        "nonzero test exit": "failing assertion unhandled exception",
        "test error": "unhandled exception",
        "keyerror": "unhandled exception contract mismatch",
        "skip signal": "skipped critical test",
        "skipped": "skipped critical test",
        "ran": "missing test coverage",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def output_path_from_command(command: str, repo: Path) -> Path | None:
    parts = shlex.split(command, posix=False)
    for flag in ["--output", "-o"]:
        if flag in parts:
            index = parts.index(flag)
            if index + 1 < len(parts):
                path = Path(parts[index + 1].strip("\"'"))
                return path if path.is_absolute() else repo / path
    return None


def primary_input_path(fixture: dict[str, Any], repo: Path) -> Path | None:
    paths = fixture.get("data_paths", [])
    if not paths:
        return None
    path = Path(paths[0])
    return path if path.is_absolute() else repo / path


def csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def output_record_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return len(payload)
        if isinstance(payload, dict):
            for key in ["records", "events", "items", "rows"]:
                if isinstance(payload.get(key), list):
                    return len(payload[key])
        return 1
    if path.suffix.lower() == ".csv":
        return csv_row_count(path)
    return 0


def output_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv_rows(path)]
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            for key in ["records", "events", "items", "rows"]:
                rows = payload.get(key)
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
    return []


def artifact_loss_signals(fixture: dict[str, Any], repo: Path, command: str) -> list[str]:
    input_path = primary_input_path(fixture, repo)
    output_path = output_path_from_command(command, repo)
    if not input_path or not output_path or not output_path.exists():
        return []
    input_records = csv_rows(input_path)
    input_rows = len(input_records)
    output_rows = output_record_count(output_path)
    signals: list[str] = []
    if input_rows and output_rows < input_rows:
        signals.append(f"silent_data_loss:input_rows={input_rows}:output_rows={output_rows}")
    unique_key = str(fixture.get("unique_key", "") or fixture.get("primary_key", ""))
    if unique_key:
        key_values = [row.get(unique_key, "") for row in input_records if row.get(unique_key, "")]
        duplicate_count = len(key_values) - len(set(key_values))
        if duplicate_count > 0 and output_rows < input_rows:
            signals.append(f"silent_data_loss:duplicate_key_overwrite:key={unique_key}:duplicates={duplicate_count}")
    return signals


def csv_parsing_signals(fixture: dict[str, Any], repo: Path, command: str) -> list[str]:
    input_path = primary_input_path(fixture, repo)
    output_path = output_path_from_command(command, repo)
    if not input_path or not input_path.exists() or not output_path or not output_path.exists():
        return []
    signals: list[str] = []
    raw_lines = input_path.read_text(encoding="utf-8").splitlines()
    has_quoted_comma = any("\"," in line or ",\"" in line for line in raw_lines[1:])
    with input_path.open(newline="", encoding="utf-8") as handle:
        parsed_rows = list(csv.reader(handle))
    if parsed_rows:
        header_width = len(parsed_rows[0])
        malformed_rows = [index for index, row in enumerate(parsed_rows[1:], start=2) if len(row) != header_width]
        if malformed_rows:
            signals.append(f"bad_csv_parsing:malformed_row_widths={','.join(map(str, malformed_rows[:5]))}")
    naive_width_mismatches = [
        index
        for index, line in enumerate(raw_lines[1:], start=2)
        if has_quoted_comma and len(next(csv.reader([line]))) != len(line.split(","))
    ]
    output_lost_quoted_rows = has_quoted_comma and output_record_count(output_path) < csv_row_count(input_path)
    output_lost_quoted_values = has_quoted_comma and not quoted_comma_values_preserved(input_path, output_path)
    if naive_width_mismatches and (output_lost_quoted_rows or output_lost_quoted_values):
        signals.append(f"bad_csv_parsing:quoted_delimiter_requires_csv_reader:rows={','.join(map(str, naive_width_mismatches[:5]))}")
    if output_lost_quoted_rows:
        signals.append("bad_csv_parsing:quoted_comma_row_loss")
    return signals


def quoted_comma_values_preserved(input_path: Path, output_path: Path) -> bool:
    input_values = []
    with input_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            input_values.extend(str(value) for value in row.values() if "," in str(value))
    if not input_values:
        return True
    output_values = {
        str(value)
        for record in output_records(output_path)
        for value in record.values()
    }
    return all(value in output_values for value in input_values)


def artifact_schema_signals(fixture: dict[str, Any], repo: Path, command: str) -> list[str]:
    input_path = primary_input_path(fixture, repo)
    output_path = output_path_from_command(command, repo)
    if not input_path or not output_path or not output_path.exists():
        return []
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        input_fields = set(reader.fieldnames or [])
    records = output_records(output_path)
    if not records:
        return []
    output_fields = set(records[0].keys())
    expected_fields = set(str(field) for field in fixture.get("expected_output_fields", []))
    required_fields = expected_fields or input_fields
    missing = sorted(required_fields - output_fields)
    signals: list[str] = []
    if missing:
        signals.append(f"schema_mismatch:missing_output_fields={','.join(missing[:4])}")
    forbidden_fields = set(str(field) for field in fixture.get("forbidden_output_fields", []))
    unexpected = sorted(output_fields & forbidden_fields)
    if unexpected:
        signals.append(f"schema_mismatch:unexpected_output_fields={','.join(unexpected[:4])}")
    renamed_fields = [
        f"{source}->{dest}"
        for source, dest in fixture.get("renamed_output_fields", {}).items()
        if source in required_fields and source not in output_fields and dest in output_fields
    ]
    if renamed_fields:
        signals.append(f"schema_mismatch:renamed_fields={','.join(renamed_fields[:4])}")
    return signals


def timestamp_order_signals(fixture: dict[str, Any], repo: Path, command: str) -> list[str]:
    input_path = primary_input_path(fixture, repo)
    if not input_path or not input_path.exists():
        return []
    rows = csv_rows(input_path)
    timestamp_field = str(fixture.get("timestamp_field", "occurred_at"))
    timestamp_values = [row.get(timestamp_field, "") for row in rows if row.get(timestamp_field)]
    signals: list[str] = []
    if any("/" in value for value in timestamp_values) and any("T" in value for value in timestamp_values):
        signals.append("flaky_timestamp_order_assumption:mixed_timestamp_formats")
    output_path = output_path_from_command(command, repo)
    key_field = str(fixture.get("unique_key", "") or fixture.get("primary_key", ""))
    output_timestamp_field = str(fixture.get("output_timestamp_field", timestamp_field))
    output_key_field = str(fixture.get("output_key_field", key_field))
    if output_path and output_path.exists() and key_field and output_key_field:
        source_by_key = {row.get(key_field, ""): row for row in rows if row.get(key_field, "") and row.get(timestamp_field, "")}
        output_records_by_key = [
            record for record in output_records(output_path) if record.get(output_key_field, "") in source_by_key
        ]
        if output_records_by_key and len(output_records_by_key) == len(source_by_key):
            output_order = [str(record.get(output_key_field, "")) for record in output_records_by_key]
            chronological_order = [
                key
                for key, _row in sorted(
                    source_by_key.items(),
                    key=lambda item: parsed_timestamp_sort_key(str(item[1].get(timestamp_field, ""))),
                )
            ]
            if output_order != chronological_order:
                signals.append("flaky_timestamp_order_assumption:output_order_not_chronological")
        if output_records_by_key and output_timestamp_field != timestamp_field:
            signals.append(f"flaky_timestamp_order_assumption:renamed_timestamp_field={output_timestamp_field}")
    return signals


def parsed_timestamp_sort_key(value: str) -> tuple[int, float | str]:
    parsed = parse_cli_timestamp(value)
    if parsed is None:
        return (1, value)
    return (0, parsed.timestamp())


def parse_cli_timestamp(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        pass
    for pattern in ("%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def missing_file_probe(fixture: dict[str, Any], repo: Path, command: str) -> list[str]:
    input_path = primary_input_path(fixture, repo)
    if not input_path:
        return []
    output_path = output_path_from_command(command, repo)
    missing_path = input_path.with_name(input_path.name + ".missing")
    mutated = command.replace(str(input_path).replace("\\", "/"), str(missing_path).replace("\\", "/"))
    mutated = mutated.replace(str(input_path), str(missing_path))
    for raw_path in fixture.get("data_paths", []):
        raw_missing = str(Path(raw_path).with_name(Path(raw_path).name + ".missing"))
        mutated = mutated.replace(str(raw_path).replace("\\", "/"), raw_missing.replace("\\", "/"))
        mutated = mutated.replace(str(raw_path), raw_missing)
    if output_path:
        probe_output = output_path.with_name(output_path.stem + "_missing_probe" + output_path.suffix)
        mutated = mutated.replace(str(output_path).replace("\\", "/"), str(probe_output).replace("\\", "/"))
        mutated = mutated.replace(str(output_path), str(probe_output))
    proc = subprocess.run(mutated, cwd=repo, shell=True, capture_output=True, text=True, timeout=int(fixture.get("timeout_sec", 10)))
    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    if proc.returncode == 0:
        return ["missing_file_handling:unexpected_success"]
    if any(token in combined for token in ["filenotfounderror", "no such file", "not found"]):
        return ["missing_file_handling:runtime_signal"]
    return []


def skipped_row(manifest: dict[str, Any], fixture: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "sector": manifest.get("sector", ""),
        "fixture_id": fixture.get("id", ""),
        "runner": fixture.get("runner", ""),
        "loop": 0,
        "profile": "",
        "target": fixture_target(fixture),
        "command": fixture_command(fixture),
        "expected_min_bugs": expected_min_bugs(fixture),
        "expected_bug_classes": "|".join(fixture.get("expected_bug_classes", [])),
        "found_bugs": 0,
        "unique_signal_count": 0,
        "duplicate_signal_ratio": 0,
        "expected_class_hits": 0,
        "expected_class_total": len(fixture.get("expected_bug_classes", [])),
        "expected_class_recall": 0,
        "detected_expected": 0,
        "coverage_score": 0,
        "elapsed_ms": 0,
        "run_id": "",
        "output_dir": "",
        "notes": reason,
    }


def summarize_sector_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"fixtures": 0, "runs": 0, "detection_rate": 0, "avg_coverage_score": 0}
    fixture_ids = sorted({row["fixture_id"] for row in rows})
    detected_by_fixture = {
        fixture_id: max(int(row["detected_expected"]) for row in rows if row["fixture_id"] == fixture_id)
        for fixture_id in fixture_ids
    }
    coverage_scores = [float(row["coverage_score"]) for row in rows]
    found = [int(row["found_bugs"]) for row in rows]
    unique_signals = [int(row.get("unique_signal_count", row["found_bugs"])) for row in rows]
    class_recalls = [float(row.get("expected_class_recall", 0)) for row in rows if int(row.get("expected_class_total", 0))]
    return {
        "fixtures": len(fixture_ids),
        "runs": len(rows),
        "fixtures_detected": sum(detected_by_fixture.values()),
        "detection_rate": round(sum(detected_by_fixture.values()) / max(1, len(fixture_ids)), 3),
        "avg_coverage_score": round(sum(coverage_scores) / len(coverage_scores), 3),
        "total_found_bugs": sum(found),
        "avg_found_bugs": round(sum(found) / len(found), 2),
        "total_unique_signals": sum(unique_signals),
        "avg_unique_signals": round(sum(unique_signals) / len(unique_signals), 2),
        "avg_expected_class_recall": round(sum(class_recalls) / len(class_recalls), 3) if class_recalls else 0,
        "best_profiles": best_profiles(rows),
    }


def best_profiles(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    profiles = sorted({row["profile"] for row in rows if row["profile"]})
    return sorted(
        ((profile, round(sum(float(row["coverage_score"]) for row in rows if row["profile"] == profile) / max(1, len([row for row in rows if row["profile"] == profile])), 3)) for profile in profiles),
        key=lambda item: item[1],
        reverse=True,
    )


def write_sector_report(
    manifest: dict[str, Any],
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    output_root: Path,
    repo: Path,
    run_name: str,
) -> None:
    run_id = f"{run_name}_{safe_slug(manifest.get('sector', 'sector'))}_aggregate"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sector_rows.csv"
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.sector_benchmark",
        target=manifest.get("sector", "sector"),
        output_dir=out_dir,
        base_dir=repo,
        status="failed" if summary.get("detection_rate", 0) < 1 else "passed",
        title=f"BugLab Sector Benchmark: {manifest.get('name', manifest.get('sector', 'sector'))}",
        summary=f"{summary.get('fixtures_detected', 0)} of {summary.get('fixtures', 0)} fixtures reached expected detection coverage.",
    )
    for key, value in summary.items():
        if key == "best_profiles":
            continue
        builder.metric(key, value)
    builder.artifact("sector_rows", csv_path, kind="csv")
    for row in rows:
        if int(row["detected_expected"]):
            continue
        builder.finding(
            Finding(
                id=f"MISS-{safe_slug(row['fixture_id']).upper()}",
                title=f"Expected bug fixture was under-detected: {row['fixture_id']}",
                severity="high",
                status="open",
                category="technique_gap",
                signals=[row.get("notes", "") or f"found_bugs={row['found_bugs']} expected_min={row['expected_min_bugs']}"],
                evidence_ids=[],
                reproduction_steps=[
                    f"Run sector manifest {manifest.get('_manifest_path', '')}.",
                    f"Inspect fixture {row['fixture_id']}.",
                ],
                expected="The sector harness should detect at least the manifest's expected minimum bug count.",
                actual=f"Detected {row['found_bugs']} bug candidates.",
                fix_hypothesis="Add or tune a sector-specific detector, profile, or tool adapter.",
            )
        )
    builder.write()


def write_command_report(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    signals: list[str],
    proc: subprocess.CompletedProcess[str],
    out_dir: Path,
    repo: Path,
    run_id: str,
    elapsed_ms: int,
) -> None:
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.command_probe",
        target=fixture_command(fixture) or fixture.get("id", ""),
        output_dir=out_dir,
        base_dir=repo,
        status="failed" if signals else "passed",
        title=f"BugLab Command Probe: {fixture.get('id', 'command')}",
        summary=f"Command exited {proc.returncode} with {len(signals)} bug signals.",
    )
    builder.metric("bug_candidate_count", len(signals))
    builder.metric("elapsed_ms", elapsed_ms, unit="ms")
    builder.metric("exit_code", proc.returncode)
    builder.artifact("raw_command_report", out_dir / "command_report.json", kind="json")
    if signals:
        builder.finding(
            Finding(
                id="CMD-001",
                title=f"{fixture.get('id', 'command')} produced command failure signals",
                severity="medium",
                status="open",
                category="command_agent",
                signals=signals,
                evidence_ids=[],
                reproduction_steps=[f"Run `{fixture_command(fixture)}` from repo root."],
                expected="Command behavior should match declared fixture expectations.",
                actual="; ".join(signals),
                fix_hypothesis="Inspect CLI exit handling, output contract, parser, or data validation branch.",
            )
        )
    builder.write()


def write_docs_report(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    signals: list[str],
    out_dir: Path,
    repo: Path,
    run_id: str,
    elapsed_ms: int,
) -> None:
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.docs_probe",
        target=fixture_target(fixture) or fixture.get("id", ""),
        output_dir=out_dir,
        base_dir=repo,
        status="failed" if signals else "passed",
        title=f"BugLab Docs Probe: {fixture.get('id', 'docs')}",
        summary=f"Docs probe found {len(signals)} content/link integrity signals.",
    )
    builder.metric("bug_candidate_count", len(signals))
    builder.metric("failure_signal_count", len(signals))
    builder.metric("elapsed_ms", elapsed_ms, unit="ms")
    builder.artifact("raw_docs_report", out_dir / "docs_report.json", kind="json")
    if signals:
        builder.finding(
            Finding(
                id="DOCS-001",
                title=f"{fixture.get('id', 'docs')} produced documentation integrity signals",
                severity="medium",
                status="open",
                category="docs_agent",
                signals=signals,
                evidence_ids=[],
                reproduction_steps=[f"Inspect `{fixture_target(fixture)}` and referenced local links/images."],
                expected="Documentation links, anchors, images, and release-critical copy should resolve locally.",
                actual="; ".join(signals),
                fix_hypothesis="Repair local paths, add missing anchors/assets, or replace unresolved placeholders.",
            )
        )
    builder.write()


def write_tests_report(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    signals: list[str],
    proc: subprocess.CompletedProcess[str],
    out_dir: Path,
    repo: Path,
    run_id: str,
    elapsed_ms: int,
) -> None:
    builder = ReportBuilder(
        run_id=run_id,
        tool="buglab.tests_probe",
        target=fixture_command(fixture) or fixture.get("id", ""),
        output_dir=out_dir,
        base_dir=repo,
        status="failed" if signals else "passed",
        title=f"BugLab Tests Probe: {fixture.get('id', 'tests')}",
        summary=f"Test command exited {proc.returncode} with {len(signals)} test failure signals.",
    )
    builder.metric("bug_candidate_count", len(signals))
    builder.metric("failure_signal_count", len(signals))
    builder.metric("elapsed_ms", elapsed_ms, unit="ms")
    builder.metric("exit_code", proc.returncode)
    builder.artifact("raw_test_report", out_dir / "test_report.json", kind="json")
    if signals:
        builder.finding(
            Finding(
                id="TEST-001",
                title=f"{fixture.get('id', 'tests')} produced test failure signals",
                severity="medium",
                status="open",
                category="tests_agent",
                signals=signals,
                evidence_ids=[],
                reproduction_steps=[f"Run `{fixture_command(fixture)}` from repo root."],
                expected="Unit tests should pass, cover required checks, and fail clearly on contract defects.",
                actual="; ".join(signals),
                fix_hypothesis="Inspect failing assertions, skipped critical tests, exception traces, or incomplete coverage.",
            )
        )
    builder.write()


def safe_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "item"
