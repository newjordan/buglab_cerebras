from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXTERNAL_ROOT = Path(os.getenv("BUGLAB_REPLAY_ROOT", str(ROOT / ".buglab")))
SCHEMA_VERSION = "buglab.evidence_replay.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay real-repo BugLab evidence packets without mixing them into oracle accuracy.")
    parser.add_argument("--root", action="append", default=[], help="Root to scan for repo-audit case indexes.")
    parser.add_argument("--max-cases", type=int, default=80, help="Maximum case packets to replay across all scanned roots.")
    parser.add_argument("--timeout-seconds", type=int, default=20, help="Timeout for allowlisted command replays.")
    parser.add_argument("--write-empty", action="store_true", help="Write empty replay reports for audit runs with zero cases.")
    args = parser.parse_args()

    roots = [Path(item).resolve() for item in args.root] or [DEFAULT_EXTERNAL_ROOT]
    reports = replay_roots(roots, max_cases=args.max_cases, timeout_seconds=args.timeout_seconds, write_empty=args.write_empty)
    aggregate = aggregate_reports(reports)
    print(json.dumps({"schema_version": SCHEMA_VERSION, "reports": len(reports), "summary": aggregate}, indent=2))
    return 0


def replay_roots(roots: list[Path], *, max_cases: int, timeout_seconds: int, write_empty: bool) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    remaining = max_cases
    for index_path in collect_case_indexes(roots):
        if remaining <= 0:
            break
        report = replay_case_index(index_path, max_cases=remaining, timeout_seconds=timeout_seconds, write_empty=write_empty)
        if not report:
            continue
        reports.append(report)
        remaining -= int(report.get("summary", {}).get("checked", 0) or 0)
    return reports


def collect_case_indexes(roots: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    indexes: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("cases/index.json"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            indexes.append(path)
    return sorted(indexes, key=lambda path: path.stat().st_mtime, reverse=True)


def replay_case_index(index_path: Path, *, max_cases: int, timeout_seconds: int, write_empty: bool) -> dict[str, Any] | None:
    index = read_json(index_path)
    cases = index.get("cases", []) if isinstance(index.get("cases", []), list) else []
    if not cases and not write_empty:
        return None
    repo = Path(str(index.get("repo", ""))).resolve()
    run_dir = index_path.parent.parent
    manifest = read_json(run_dir / "report_manifest.json")
    run_id = str(manifest.get("run_id") or run_dir.name)
    results: list[dict[str, Any]] = []
    for item in cases[:max_cases]:
        if not isinstance(item, dict):
            continue
        case_path = Path(str(item.get("case_json_path") or ""))
        case_payload = read_json(case_path)
        finding = case_payload.get("finding", {}) if isinstance(case_payload.get("finding", {}), dict) else {}
        results.append(replay_finding(repo, run_id, finding, case_path, timeout_seconds=timeout_seconds))
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "repo": str(repo),
        "source_case_index": str(index_path),
        "source_manifest": str(run_dir / "report_manifest.json"),
        "created_at_utc": utc_now(),
        "summary": summarize_results(results),
        "results": results,
        "note": (
            "Replay verification checks whether a suspected real-repo claim still reproduces from its case packet. "
            "It is not benchmark ground truth and is kept separate from BugsInPy precision/recall."
        ),
    }
    output_path = run_dir / "evidence_replay.json"
    output_jsonl = run_dir / "evidence_replay.jsonl"
    write_json(output_path, report)
    output_jsonl.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in results), encoding="utf-8")
    return {**report, "path": str(output_path), "jsonl_path": str(output_jsonl)}


def replay_finding(repo: Path, run_id: str, finding: dict[str, Any], case_path: Path, *, timeout_seconds: int) -> dict[str, Any]:
    started = time.perf_counter()
    signals = [str(item) for item in finding.get("signals", []) if str(item)]
    command = str(finding.get("command") or "").strip()
    target = str(finding.get("target") or "").strip()
    artifact = str(finding.get("artifact") or "").strip()
    result: dict[str, Any] = {
        "run_id": run_id,
        "finding_id": str(finding.get("finding_id") or ""),
        "sector": str(finding.get("sector") or ""),
        "target": target,
        "case_json_path": str(case_path),
        "signals": signals,
        "command": command,
        "artifact": artifact,
        "method": "unsupported",
        "verdict": "unsupported",
        "matched_signals": [],
        "missing_signals": signals,
        "unsupported_signals": [],
        "elapsed_ms": 0,
        "reason": "",
        "triage_class": "",
        "triage_action": "",
    }
    try:
        if command and is_safe_command(command):
            replay = replay_command(repo, command, timeout_seconds=timeout_seconds)
            matched = match_command_signals(signals, replay)
            matched.extend(match_static_context_signals(repo, target, [signal for signal in signals if signal not in matched]))
            matched = sorted(set(matched))
            result.update(
                {
                    "method": "command_replay",
                    "exit_code": replay.get("exit_code"),
                    "timed_out": replay.get("timed_out", False),
                    "stdout_tail": replay.get("stdout_tail", ""),
                    "stderr_tail": replay.get("stderr_tail", ""),
                    "matched_signals": matched,
                    "missing_signals": [signal for signal in signals if signal not in matched],
                    "verdict": verdict_for_matches(signals, matched),
                    "reason": "allowlisted command replay",
                }
            )
        else:
            static = replay_static_signals(repo, target, signals, artifact)
            result.update(static)
    except Exception as exc:  # pragma: no cover - defensive for arbitrary target repos
        result.update({"method": "error", "verdict": "error", "reason": f"{type(exc).__name__}: {exc}"})
    result.update(triage_result(result))
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def is_safe_command(command: str) -> bool:
    normalized = " ".join(command.strip().split()).lower()
    return normalized.startswith("python -m unittest ") or normalized == "python -m unittest discover" or normalized.startswith(
        "python -m unittest discover "
    )


def replay_command(repo: Path, command: str, *, timeout_seconds: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=repo, shell=True, capture_output=True, text=True, timeout=timeout_seconds)
        return {
            "exit_code": proc.returncode,
            "timed_out": False,
            "stdout_tail": tail(proc.stdout),
            "stderr_tail": tail(proc.stderr),
            "combined": f"{proc.stdout}\n{proc.stderr}",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "timed_out": True,
            "stdout_tail": tail(str(exc.stdout or "")),
            "stderr_tail": tail(str(exc.stderr or "")),
            "combined": f"{exc.stdout or ''}\n{exc.stderr or ''}",
        }


def replay_static_signals(repo: Path, target: str, signals: list[str], artifact: str = "") -> dict[str, Any]:
    target_path = (repo / target).resolve() if target else repo
    if target and not is_within(target_path, repo):
        return unsupported("target escaped repo root")
    if target and not target_path.exists():
        matched = [signal for signal in signals if signal.startswith(("missing_file", "missing_image_asset"))]
        return static_result(signals, matched, "target path missing", target_path)
    if target_path.is_file():
        text = target_path.read_text(encoding="utf-8", errors="replace")
        matched: list[str] = []
        unsupported_signals: list[str] = []
        for signal in signals:
            replayed = static_signal_matches(signal, text, target_path, repo, artifact)
            if replayed is True:
                matched.append(signal)
            elif replayed is None:
                unsupported_signals.append(signal)
        return static_result(signals, matched, "static file signal replay", target_path, unsupported_signals)
    return unsupported("no safe command and no concrete file target")


def static_signal_matches(signal: str, text: str, target_path: Path, repo: Path, artifact: str = "") -> bool | None:
    if signal.startswith("unresolved_placeholder:"):
        pattern = signal.split(":", 1)[1]
        return bool(pattern and pattern in text)
    if signal.startswith("missing_required_term:"):
        term = signal.split(":", 1)[1]
        return bool(term and term not in text)
    if signal.startswith("missing_anchor:"):
        anchor = signal.split(":", 2)[1]
        return not markdown_anchor_exists(text, anchor)
    if signal.startswith("missing_image_asset:"):
        href = signal.split(":", 2)[1]
        candidate = (target_path.parent / href).resolve()
        return is_within(candidate, repo) and not candidate.exists()
    if signal.startswith("missing_local_link:"):
        href = signal.split(":", 1)[1].split(":label=", 1)[0]
        target_ref = href.split("#", 1)[0]
        if not target_ref:
            return False
        candidate = (target_path.parent / target_ref).resolve()
        return is_within(candidate, repo) and not candidate.exists()
    if signal == "missing_test_coverage:no_test_functions":
        return not bool(re.search(r"^\s*def\s+test\w*\s*\(", text, flags=re.MULTILINE))
    if signal == "missing_test_coverage:no_assertions":
        return bool(re.search(r"^\s*def\s+test\w*\s*\(", text, flags=re.MULTILINE)) and not bool(
            re.search(r"\bassert\b|self\.assert\w+\(", text)
        )
    if signal == "missing_test_coverage:test_placeholder":
        return bool(re.search(r"\b(?:TODO|FIXME|TBD)\b", text))
    if signal.startswith("browser_bug_candidates:"):
        return browser_artifact_signal_matches(signal, artifact)
    if signal.startswith("iac_unpinned_dockerfile_base:latest"):
        return bool(re.search(r"(?im)^FROM\s+\S+:latest\b", text))
    if signal.startswith("iac_unpinned_workflow_action:"):
        return "@master" in text or "@main" in text
    if signal.startswith("iac_unpinned_latest_image:"):
        return ":latest" in text
    if signal.startswith("iac_missing_healthcheck"):
        return "healthcheck" not in text.lower()
    if signal.startswith("env_debug_enabled:"):
        return bool(re.search(r"(?im)\b(debug|flask_debug|django_debug)\s*=\s*(1|true|yes|on)\b", text))
    if signal.startswith("env_placeholder_value:"):
        return bool(re.search(r"(?i)(changeme|change_me|todo|example|placeholder|your_)", text))
    if signal.startswith("env_secret_too_short:"):
        return bool(re.search(r"(?im)(secret|token|key|password)\s*=\s*.{0,7}$", text))
    if signal.startswith("config_secret_literal_too_short"):
        return bool(re.search(r"(?im)(secret|token|key|password).{0,12}[:=]\s*['\"]?.{1,7}['\"]?", text))
    return signal in text


def match_command_signals(signals: list[str], replay: dict[str, Any]) -> list[str]:
    combined = str(replay.get("combined") or "")
    return [signal for signal in signals if command_signal_matches(signal, replay, combined)]


def command_signal_matches(signal: str, replay: dict[str, Any], combined: str) -> bool:
    lowered = combined.lower()
    if signal.startswith("nonzero_test_exit:") or signal.startswith("test_command_failed:"):
        return replay.get("exit_code") not in {0, None}
    if signal.startswith("no_tests_discovered:"):
        return "ran 0 tests" in lowered or "no tests ran" in lowered
    if signal.startswith("missing_test_coverage:ran="):
        match = re.search(r"missing_test_coverage:ran=(\d+):expected_min=(\d+)", signal)
        if not match:
            return False
        ran = parsed_unittest_count(combined)
        return ran < int(match.group(2))
    if signal.startswith("test_timeout:") or signal.startswith("test_file_timeout:"):
        return bool(replay.get("timed_out"))
    if signal.startswith("failing_assertion:"):
        return "assertionerror" in lowered or "\nfail:" in lowered or "failed" in lowered
    if signal.startswith("unhandled_exception:"):
        return "traceback" in lowered or "\nerror:" in lowered
    if signal.startswith("missing_test_output:"):
        pattern = signal.split(":", 1)[1]
        return bool(pattern and pattern not in combined)
    return signal in combined


def match_static_context_signals(repo: Path, target: str, signals: list[str]) -> list[str]:
    if not target:
        return []
    target_path = (repo / target).resolve()
    if not is_within(target_path, repo) or not target_path.is_file():
        return []
    text = target_path.read_text(encoding="utf-8", errors="replace")
    return [signal for signal in signals if static_signal_matches(signal, text, target_path, repo) is True]


def browser_artifact_signal_matches(signal: str, artifact: str) -> bool | None:
    match = re.match(r"browser_bug_candidates:(\d+)", signal)
    if not match:
        return None
    if not artifact:
        return None
    artifact_path = Path(artifact)
    if not artifact_path.exists():
        return None
    payload = read_json(artifact_path)
    if not payload:
        return None
    expected = int(match.group(1))
    summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
    candidates = [
        int(summary.get("total_bug_candidates") or 0),
        int(summary.get("max_bug_candidates") or 0),
    ]
    rows = payload.get("rows", []) if isinstance(payload.get("rows", []), list) else []
    candidates.extend(int(row.get("bug_candidate_count") or 0) for row in rows if isinstance(row, dict))
    return max(candidates or [0]) >= expected


def static_result(
    signals: list[str],
    matched: list[str],
    reason: str,
    target_path: Path,
    unsupported_signals: list[str] | None = None,
) -> dict[str, Any]:
    unsupported_signals = unsupported_signals or []
    replayable_signals = [signal for signal in signals if signal not in unsupported_signals]
    return {
        "method": "static_signal_replay",
        "verdict": verdict_for_matches(replayable_signals, matched),
        "matched_signals": matched,
        "missing_signals": [signal for signal in replayable_signals if signal not in matched],
        "unsupported_signals": unsupported_signals,
        "reason": reason,
        "resolved_target": str(target_path),
    }


def unsupported(reason: str) -> dict[str, Any]:
    return {
        "method": "unsupported",
        "verdict": "unsupported",
        "matched_signals": [],
        "missing_signals": [],
        "unsupported_signals": [],
        "reason": reason,
    }


def verdict_for_matches(signals: list[str], matched: list[str]) -> str:
    if not signals:
        return "unsupported"
    if len(matched) == len(signals):
        return "reproduced"
    if matched:
        return "partially_reproduced"
    return "not_reproduced"


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "checked": len(results),
        "reproduced": 0,
        "partially_reproduced": 0,
        "not_reproduced": 0,
        "unsupported": 0,
        "error": 0,
        "command_replay": 0,
        "static_signal_replay": 0,
        "unsupported_signals": 0,
    }
    triage: dict[str, int] = {}
    for result in results:
        verdict = str(result.get("verdict") or "unsupported")
        method = str(result.get("method") or "unsupported")
        if verdict in counts:
            counts[verdict] += 1
        if method in counts:
            counts[method] += 1
        counts["unsupported_signals"] += len(result.get("unsupported_signals", []) or [])
        triage_class = str(result.get("triage_class") or "unclassified")
        triage[triage_class] = triage.get(triage_class, 0) + 1
    denominator = counts["reproduced"] + counts["partially_reproduced"] + counts["not_reproduced"]
    counts["replay_reproduction_rate"] = ((counts["reproduced"] + counts["partially_reproduced"]) / denominator) if denominator else None
    counts["triage"] = triage
    return counts


def aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "reports": len(reports),
        "checked": 0,
        "reproduced": 0,
        "partially_reproduced": 0,
        "not_reproduced": 0,
        "unsupported": 0,
        "error": 0,
        "command_replay": 0,
        "static_signal_replay": 0,
        "unsupported_signals": 0,
    }
    triage: dict[str, int] = {}
    for report in reports:
        summary = report.get("summary", {}) if isinstance(report.get("summary", {}), dict) else {}
        for key in list(totals):
            if key == "reports":
                continue
            totals[key] += int(summary.get(key) or 0)
        for key, value in (summary.get("triage", {}) if isinstance(summary.get("triage", {}), dict) else {}).items():
            triage[str(key)] = triage.get(str(key), 0) + int(value or 0)
    denominator = totals["reproduced"] + totals["partially_reproduced"] + totals["not_reproduced"]
    totals["replay_reproduction_rate"] = ((totals["reproduced"] + totals["partially_reproduced"]) / denominator) if denominator else None
    totals["triage"] = triage
    return totals


def triage_result(result: dict[str, Any]) -> dict[str, str]:
    verdict = str(result.get("verdict") or "unsupported")
    method = str(result.get("method") or "unsupported")
    signals = [str(signal) for signal in result.get("signals", []) if str(signal)]
    if verdict == "reproduced":
        return {"triage_class": "reproduced", "triage_action": "Use as replayed supporting evidence."}
    if verdict == "partially_reproduced":
        return {"triage_class": "partial_reproduction", "triage_action": "Inspect missing signals before using this as strong evidence."}
    if verdict == "error":
        return {"triage_class": "replay_error", "triage_action": "Fix the replay harness before scoring this packet."}
    if verdict == "unsupported":
        return {"triage_class": "unsupported_replay", "triage_action": "Add a deterministic replay primitive or keep this out of accuracy claims."}
    if any(signal.startswith("browser_bug_candidates:") for signal in signals) and result.get("artifact"):
        return {
            "triage_class": "artifact_contradicts_signal",
            "triage_action": "Treat as stale or false-positive evidence until a browser replay reproduces it.",
        }
    if method == "command_replay":
        return {
            "triage_class": "command_output_changed",
            "triage_action": "Rerun the audit on the current checkout and compare command output.",
        }
    if method == "static_signal_replay":
        return {
            "triage_class": "signal_absent_on_current_checkout",
            "triage_action": "Treat as fixed, stale, or false positive until re-audited.",
        }
    return {"triage_class": "unclassified", "triage_action": "Inspect manually before using as evidence."}


def parsed_unittest_count(output: str) -> int:
    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    if not match:
        return 0
    return int(match.group(1))


def markdown_anchor_exists(text: str, anchor: str) -> bool:
    normalized = anchor.lstrip("#").lower()
    if not normalized:
        return False
    headings = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.append(slugify_heading(match.group(1)))
    return normalized in headings or anchor in text


def slugify_heading(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"\s+", "-", value)
    return value.strip("-")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def tail(value: str, *, limit: int = 4000) -> str:
    return value[-limit:]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
