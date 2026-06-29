from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from validate_submission_package import validate_package


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".buglab" / "submission" / "submission_package.md"
DEFAULT_JSON = ROOT / ".buglab" / "submission" / "submission_results.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the BugLab submission package from marked evidence artifacts.")
    parser.add_argument("--repo", default=str(ROOT), help="BugLab repo root.")
    parser.add_argument("--external-root", action="append", default=[], help="Extra root to scan for benchmark/eval artifacts.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown package path.")
    parser.add_argument("--json-output", default=str(DEFAULT_JSON), help="Machine-readable package summary path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    scan_roots = [repo / ".buglab"]
    scan_roots.extend(Path(item).resolve() for item in args.external_root)
    package = build_package(repo, scan_roots)
    output = Path(args.output).resolve()
    json_output = Path(args.json_output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, render_markdown(package))
    atomic_write_text(json_output, json.dumps(package, indent=2))
    print(json.dumps({"output": str(output), "json_output": str(json_output), "benchmarks": len(package["benchmarks"])}, indent=2))
    return 0


def atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def build_package(repo: Path, scan_roots: list[Path]) -> dict[str, Any]:
    benchmarks = sorted(collect_benchmarks(scan_roots), key=lambda item: item["updated_at"], reverse=True)
    ledgers = sorted(collect_truth_ledgers(scan_roots), key=lambda item: item["updated_at"], reverse=True)
    best = best_valid_benchmark(benchmarks)
    oracle_totals = aggregate_oracle_evidence(benchmarks)
    marked_evidence = aggregate_marked_evidence(ledgers)
    evidence_completeness = aggregate_evidence_completeness(ledgers)
    promotion_queue = collect_promotion_queue(ledgers)
    reported_promotion_queue = promotion_queue[:50]
    replay_reports = sorted(collect_replay_reports(scan_roots), key=lambda item: item["updated_at"], reverse=True)
    replay_summary = aggregate_replay_reports(replay_reports)
    replay_unique_summary = aggregate_unique_replay_claims(scan_roots)
    replay_triage_samples = collect_replay_triage_samples(scan_roots)
    replay_misses = collect_replay_miss_dossiers(scan_roots)
    calibration_ledger = build_calibration_ledger(
        oracle_totals,
        marked_evidence,
        replay_unique_summary,
        replay_misses,
    )
    promotion_triage_pack = build_promotion_triage_pack(reported_promotion_queue)
    eval_events = collect_eval_events(scan_roots)
    package = {
        "schema_version": "buglab.submission_package.v1",
        "updated_at_utc": utc_now(),
        "repo": str(repo),
        "claim": "BugLab is a truth-calibrated recursive bug hunter: every bug claim is carried as an evidence packet, and benchmark accuracy is only claimed when an oracle scores it.",
        "demo_path": "Open http://127.0.0.1:8765/, run Find Bugs or Find + Fix, then inspect the Evidence tab and Agent Copy handoff.",
        "best_benchmark": best,
        "oracle_totals": oracle_totals,
        "marked_evidence": marked_evidence,
        "evidence_completeness": evidence_completeness,
        "promotion_queue": reported_promotion_queue,
        "promotion_triage_pack": promotion_triage_pack,
        "real_repo_replay": replay_summary,
        "real_repo_replay_unique": replay_unique_summary,
        "real_repo_replay_misses": replay_misses[:50],
        "calibration_ledger": calibration_ledger,
        "latest_replay_reports": replay_reports[:12],
        "replay_triage_samples": replay_triage_samples[:16],
        "eval_log_summary": summarize_eval_events(eval_events),
        "latest_eval_events": eval_events[:12],
        "benchmarks": benchmarks[:12],
        "truth_ledgers": ledgers[:20],
        "submission_checks": {
            "no_activity_proxy_claim": True,
            "oracle_scored_accuracy_only": True,
            "suspected_findings_marked_unverified": True,
            "duplicate_benchmark_cases_deduped": True,
            "stable_metrics_disclose_disagreements": True,
            "confidence_bounds_reported": True,
            "evidence_completeness_audited": True,
            "promotion_queue_reported": True,
            "promotion_triage_pack_reported": True,
            "real_repo_replay_verification_reported": True,
            "calibration_ledger_reported": True,
            "jsonl_truth_ledger_written": any(item.get("jsonl_path") for item in ledgers),
        },
        "limitations": [
            "BugsInPy precision/recall is valid only for rows with valid benchmark oracle infrastructure.",
            "Real-world repo audits produce suspected or repair-verified evidence, not ground-truth accuracy.",
            "Token telemetry is provider-tracked only when usage exists; otherwise UI reports local estimated processing budget.",
        ],
    }
    validation = validate_package(package)
    package["submission_checks"]["package_validation_passes"] = validation["ok"]
    package["validation"] = validation
    return package


def collect_benchmarks(scan_roots: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("bugsinpy_benchmark.json"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            payload = read_json(path)
            if not payload:
                continue
            summary = payload.get("summary", {})
            truth = payload.get("truth_ledger", {}).get("summary", {}) if isinstance(payload.get("truth_ledger", {}), dict) else {}
            case_results = extract_case_results(payload)
            rejected_case_results = sum(1 for item in case_results if not item.get("differential_oracle_valid"))
            rows.append(
                {
                    "kind": "bugsinpy",
                    "path": str(path),
                    "html_path": str(path.with_suffix(".html")) if path.with_suffix(".html").exists() else "",
                    "truth_ledger_path": payload.get("truth_ledger_path", ""),
                    "updated_at": path.stat().st_mtime,
                    "updated_at_utc": utc_from_timestamp(path.stat().st_mtime),
                    "run_id": payload.get("run_id", path.parent.name),
                    "cases": summary.get("cases", 0),
                    "valid_differential_pairs": summary.get("valid_differential_pairs", 0),
                    "runnable_rows": summary.get("runnable_rows", 0),
                    "invalid_oracle_rows": summary.get("invalid_oracle_rows", 0),
                    "true_positive": summary.get("true_positive", 0),
                    "false_positive": summary.get("false_positive", 0),
                    "false_negative": summary.get("false_negative", 0),
                    "true_negative": summary.get("true_negative", 0),
                    "precision": summary.get("precision"),
                    "recall": summary.get("recall"),
                    "f1": summary.get("f1"),
                    "confirmed": truth.get("confirmed", 0),
                    "fixed": truth.get("fixed", 0),
                    "case_results": case_results,
                    "rejected_case_results": rejected_case_results,
                }
            )
    return rows


def collect_truth_ledgers(scan_roots: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("truth_ledger.json"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            payload = read_json(path)
            if not payload:
                continue
            summary = normalized_ledger_summary(path, payload)
            entry_count = int(summary.get("entries", len(payload.get("entries", []))) or 0)
            if entry_count <= 0:
                continue
            evidence_completeness = audit_ledger_evidence(path, payload)
            rows.append(
                {
                    "path": str(path),
                    "jsonl_path": str(path.with_suffix(".jsonl")) if path.with_suffix(".jsonl").exists() else "",
                    "updated_at": path.stat().st_mtime,
                    "updated_at_utc": utc_from_timestamp(path.stat().st_mtime),
                    "run_id": payload.get("run_id", path.parent.name),
                    "entries": entry_count,
                    "confirmed": summary.get("confirmed", 0),
                    "suspected": summary.get("suspected", 0),
                    "fixed": summary.get("fixed", 0),
                    "false_positive": summary.get("false_positive", 0),
                    "false_negative": summary.get("false_negative", 0),
                    "invalid_oracle": summary.get("invalid_oracle", 0),
                    "derived_from_benchmark": summary.get("derived_from_benchmark", False),
                    "precision": summary.get("precision"),
                    "recall": summary.get("recall"),
                    "f1": summary.get("f1"),
                    "evidence_completeness": evidence_completeness,
                    "evidence_complete_entries": evidence_completeness.get("complete_entries", 0),
                    "evidence_incomplete_entries": evidence_completeness.get("incomplete_entries", 0),
                    "evidence_completion_rate": evidence_completeness.get("completion_rate"),
                }
            )
    return rows


def collect_eval_events(scan_roots: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("truth_eval_log.jsonl"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event = summarize_eval_event(payload)
                event["source_log"] = str(path)
                event["line"] = index
                events.append(event)
    return sorted(events, key=lambda item: (item.get("started_at_utc", ""), item.get("line", 0)), reverse=True)


def collect_replay_reports(scan_roots: list[Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("evidence_replay.json"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            payload = read_json(path)
            if not payload:
                continue
            summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
            checked = int(summary.get("checked") or 0)
            reports.append(
                {
                    "path": str(path),
                    "jsonl_path": str(path.with_suffix(".jsonl")) if path.with_suffix(".jsonl").exists() else "",
                    "updated_at": path.stat().st_mtime,
                    "updated_at_utc": utc_from_timestamp(path.stat().st_mtime),
                    "run_id": str(payload.get("run_id", path.parent.name)),
                    "repo": str(payload.get("repo", "")),
                    "checked": checked,
                    "reproduced": int(summary.get("reproduced") or 0),
                    "partially_reproduced": int(summary.get("partially_reproduced") or 0),
                    "not_reproduced": int(summary.get("not_reproduced") or 0),
                    "unsupported": int(summary.get("unsupported") or 0),
                    "error": int(summary.get("error") or 0),
                    "command_replay": int(summary.get("command_replay") or 0),
                    "static_signal_replay": int(summary.get("static_signal_replay") or 0),
                    "unsupported_signals": int(summary.get("unsupported_signals") or 0),
                    "replay_reproduction_rate": summary.get("replay_reproduction_rate"),
                    "triage": normalized_replay_triage(summary, checked),
                }
            )
    return reports


def aggregate_replay_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {
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
        "triage": {},
        "replay_reproduction_rate": None,
        "note": "Real-repo replay checks suspected evidence packets. It is reported separately from benchmark oracle accuracy.",
    }
    for report in reports:
        for key in [
            "checked",
            "reproduced",
            "partially_reproduced",
            "not_reproduced",
            "unsupported",
            "error",
            "command_replay",
            "static_signal_replay",
            "unsupported_signals",
        ]:
            totals[key] += int(report.get(key) or 0)
        triage = report.get("triage", {}) if isinstance(report.get("triage", {}), dict) else {}
        for key, value in triage.items():
            totals["triage"][str(key)] = int(totals["triage"].get(str(key), 0)) + int(value or 0)
    denominator = totals["reproduced"] + totals["partially_reproduced"] + totals["not_reproduced"]
    totals["replay_reproduction_rate"] = (
        (totals["reproduced"] + totals["partially_reproduced"]) / denominator
        if denominator
        else None
    )
    return totals


def aggregate_unique_replay_claims(scan_roots: list[Path]) -> dict[str, Any]:
    claims, packet_count = collect_unique_replay_claim_rows(scan_roots)
    totals: dict[str, Any] = {
        "packet_checked": packet_count,
        "unique_claims": len(claims),
        "duplicate_packets_collapsed": max(0, packet_count - len(claims)),
        "unique_reproduced": 0,
        "unique_partially_reproduced": 0,
        "unique_not_reproduced": 0,
        "unique_unsupported": 0,
        "unique_error": 0,
        "unique_unsupported_signals": 0,
        "unique_replay_reproduction_rate": None,
        "triage": {},
        "note": "Unique claim view dedupes repeated eval-loop observations by repo, sector, target, command, and replay signals.",
    }
    for claim in claims:
        verdict = str(claim.get("verdict", ""))
        if verdict == "reproduced":
            totals["unique_reproduced"] += 1
        elif verdict == "partially_reproduced":
            totals["unique_partially_reproduced"] += 1
        elif verdict == "unsupported":
            totals["unique_unsupported"] += 1
        elif verdict == "error":
            totals["unique_error"] += 1
        else:
            totals["unique_not_reproduced"] += 1
        totals["unique_unsupported_signals"] += int(claim.get("unsupported_signals") or 0)
        triage_class = str(claim.get("triage_class") or "unclassified")
        totals["triage"][triage_class] = int(totals["triage"].get(triage_class, 0)) + 1
    denominator = (
        totals["unique_reproduced"]
        + totals["unique_partially_reproduced"]
        + totals["unique_not_reproduced"]
    )
    totals["unique_replay_reproduction_rate"] = (
        (totals["unique_reproduced"] + totals["unique_partially_reproduced"]) / denominator
        if denominator
        else None
    )
    return totals


def collect_replay_triage_samples(scan_roots: list[Path]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for claim in collect_unique_replay_claim_rows(scan_roots)[0]:
        triage_class = str(claim.get("triage_class") or "")
        verdict = str(claim.get("verdict") or "")
        if verdict == "reproduced" or triage_class == "reproduced":
            continue
        samples.append(
            {
                "run_id": str(claim.get("run_id", "")),
                "repo": str(claim.get("repo_name", "")),
                "finding_id": str(claim.get("finding_id", "")),
                "sector": str(claim.get("sector", "")),
                "target": str(claim.get("target", "")),
                "verdict": verdict,
                "triage_class": triage_class or "unclassified",
                "triage_action": str(claim.get("triage_action", "")),
                "missing_signals": [str(item) for item in (claim.get("missing_signals", []) or [])][:4],
                "artifact": str(claim.get("artifact", "")),
                "case_json_path": str(claim.get("case_json_path", "")),
                "report_path": str(claim.get("report_path", "")),
                "packets": int(claim.get("packets") or 0),
            }
        )
    priority = {"artifact_contradicts_signal": 0, "signal_absent_on_current_checkout": 1}
    return sorted(samples, key=lambda item: (priority.get(str(item.get("triage_class")), 9), item.get("repo", ""), item.get("target", "")))


def collect_replay_miss_dossiers(scan_roots: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for claim in collect_unique_replay_claim_rows(scan_roots)[0]:
        verdict = str(claim.get("verdict") or "")
        triage_class = str(claim.get("triage_class") or "")
        if verdict in {"reproduced", "partially_reproduced"} or triage_class in {"reproduced", "partial_reproduction"}:
            continue
        rows.append(
            {
                "repo": str(claim.get("repo_name", "")),
                "repo_path": str(claim.get("repo", "")),
                "finding_id": str(claim.get("finding_id", "")),
                "sector": str(claim.get("sector", "")),
                "target": str(claim.get("target", "")),
                "command": str(claim.get("command", "")),
                "verdict": verdict or "not_reproduced",
                "triage_class": triage_class or "unclassified",
                "triage_action": str(claim.get("triage_action", "")),
                "signals": [str(item) for item in (claim.get("signals", []) or [])][:8],
                "missing_signals": [str(item) for item in (claim.get("missing_signals", []) or [])][:8],
                "unsupported_signals": int(claim.get("unsupported_signals") or 0),
                "packets_collapsed": int(claim.get("packets") or 0),
                "case_json_path": str(claim.get("case_json_path", "")),
                "report_path": str(claim.get("report_path", "")),
                "artifact": str(claim.get("artifact", "")),
                "policy": "excluded_from_accuracy_until_reproduced",
            }
        )
    priority = {
        "artifact_contradicts_signal": 0,
        "command_output_changed": 1,
        "signal_absent_on_current_checkout": 2,
        "unsupported_replay": 3,
        "replay_error": 4,
    }
    return sorted(
        rows,
        key=lambda item: (
            priority.get(str(item.get("triage_class")), 9),
            -int(item.get("packets_collapsed") or 0),
            str(item.get("repo", "")),
            str(item.get("target", "")),
        ),
    )


def collect_unique_replay_claim_rows(scan_roots: list[Path]) -> tuple[list[dict[str, Any]], int]:
    selected: dict[str, dict[str, Any]] = {}
    packet_counts: dict[str, int] = {}
    reports = sorted(collect_raw_replay_reports(scan_roots), key=lambda item: item["updated_at"], reverse=True)
    for report in reports:
        payload = report["payload"]
        results = payload.get("results", []) if isinstance(payload.get("results", []), list) else []
        repo = str(payload.get("repo", ""))
        for result in results:
            if not isinstance(result, dict):
                continue
            signature = replay_claim_signature(repo, result)
            packet_counts[signature] = int(packet_counts.get(signature, 0)) + 1
            if signature in selected:
                continue
            selected[signature] = {
                "signature": signature,
                "run_id": str(payload.get("run_id", "")),
                "repo": repo,
                "repo_name": compact_target(repo),
                "finding_id": str(result.get("finding_id", "")),
                "sector": str(result.get("sector", "")),
                "target": str(result.get("target", "")),
                "command": str(result.get("command", "")),
                "signals": [str(item) for item in (result.get("signals", []) or [])],
                "verdict": canonical_replay_verdict(result),
                "triage_class": replay_result_triage_class(result),
                "triage_action": str(result.get("triage_action", "")),
                "missing_signals": [str(item) for item in (result.get("missing_signals", []) or [])],
                "unsupported_signals": len(result.get("unsupported_signals", []) or []),
                "artifact": str(result.get("artifact", "")),
                "case_json_path": str(result.get("case_json_path", "")),
                "report_path": str(report["path"]),
                "updated_at": report["updated_at"],
            }
    for signature, row in selected.items():
        row["packets"] = int(packet_counts.get(signature, 0))
    return list(selected.values()), sum(packet_counts.values())


def replay_claim_signature(repo: str, result: dict[str, Any]) -> str:
    signals = sorted(str(item) for item in (result.get("signals", []) or []) if str(item))
    if not signals:
        signals = sorted(str(item) for item in (result.get("missing_signals", []) or []) if str(item))
    claim_text = str(result.get("claim", "") or result.get("message", ""))
    parts = [
        repo,
        str(result.get("sector", "")),
        str(result.get("target", "")),
        str(result.get("command", "")),
        "\x1f".join(signals),
        claim_text,
    ]
    return "\x1e".join(parts)


def canonical_replay_verdict(result: dict[str, Any]) -> str:
    verdict = str(result.get("verdict") or "").strip()
    if verdict in {"reproduced", "partially_reproduced", "not_reproduced", "unsupported", "error"}:
        return verdict
    triage_class = str(result.get("triage_class") or "").strip()
    if triage_class == "reproduced":
        return "reproduced"
    if triage_class == "partial_reproduction":
        return "partially_reproduced"
    if triage_class in {"unsupported_replay", "unsupported_signal"}:
        return "unsupported"
    if triage_class == "replay_error":
        return "error"
    return "not_reproduced"


def replay_result_triage_class(result: dict[str, Any]) -> str:
    triage_class = str(result.get("triage_class") or "").strip()
    if triage_class:
        return triage_class
    verdict = canonical_replay_verdict(result)
    if verdict == "reproduced":
        return "reproduced"
    if verdict == "partially_reproduced":
        return "partial_reproduction"
    if verdict == "unsupported":
        return "unsupported_replay"
    if verdict == "error":
        return "replay_error"
    return "unclassified"


def collect_raw_replay_reports(scan_roots: list[Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("evidence_replay.json"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            payload = read_json(path)
            if payload:
                reports.append({"path": str(path), "updated_at": path.stat().st_mtime, "payload": payload})
    return reports


def normalized_replay_triage(summary: dict[str, Any], checked: int) -> dict[str, int]:
    raw = summary.get("triage", {}) if isinstance(summary.get("triage", {}), dict) else {}
    triage = {str(key): int(value or 0) for key, value in raw.items()}
    known = sum(triage.values())
    if checked > known:
        triage["legacy_unclassified"] = triage.get("legacy_unclassified", 0) + checked - known
    return triage


def summarize_eval_event(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result", {}) if isinstance(payload.get("result", {}), dict) else {}
    summary = result.get("summary", {}) if isinstance(result.get("summary", {}), dict) else {}
    kind = str(payload.get("kind", ""))
    event = {
        "kind": kind,
        "status": str(payload.get("status", "")),
        "target": str(payload.get("target", "")),
        "target_name": compact_target(payload.get("target", "")),
        "started_at_utc": str(payload.get("started_at_utc", "")),
        "run_id": str(result.get("run_id", "")),
        "artifact": str(result.get("html_path") or result.get("report_path") or result.get("json_path") or ""),
        "summary": "",
    }
    if kind == "bugsinpy":
        event["summary"] = (
            f"pairs={summary.get('valid_differential_pairs', 0)} "
            f"TP={summary.get('true_positive', 0)} FP={summary.get('false_positive', 0)} "
            f"FN={summary.get('false_negative', 0)} TN={summary.get('true_negative', 0)}"
        )
    elif kind == "real_repo_audit":
        event["summary"] = (
            f"targets={summary.get('targets', 0)} failed={summary.get('failed_targets', 0)} "
            f"signals={summary.get('total_signals', 0)}"
        )
    elif kind == "discovery_idle":
        event["summary"] = (
            f"probed={summary.get('probed', 0)} valid={summary.get('valid', 0)} "
            f"reason={summary.get('reason', '')}"
        )
    else:
        event["summary"] = str(payload.get("error") or summary or "")
    return event


def summarize_eval_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {"events": len(events), "completed": 0, "failed": 0, "bugsinpy": 0, "real_repo_audit": 0}
    latest_by_kind: dict[str, dict[str, Any]] = {}
    for event in events:
        status = str(event.get("status", ""))
        kind = str(event.get("kind", ""))
        if status == "completed":
            totals["completed"] += 1
        elif status == "failed":
            totals["failed"] += 1
        if kind in {"bugsinpy", "real_repo_audit"}:
            totals[kind] += 1
        latest_by_kind.setdefault(kind, event)
    totals["latest_by_kind"] = latest_by_kind
    return totals


def compact_target(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    normalized = text.replace("\\", "/").rstrip("/")
    if ":" in normalized and "/" not in normalized:
        return normalized
    return normalized.rsplit("/", 1)[-1] or normalized


def normalized_ledger_summary(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {})
    benchmark_path = path.parent / "bugsinpy_benchmark.json"
    benchmark = read_json(benchmark_path) if benchmark_path.exists() else {}
    rows = benchmark.get("rows", []) if benchmark else []
    if not isinstance(rows, list) or not rows:
        return summary

    grouped: dict[str, list[dict[str, Any]]] = {}
    invalid_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("outcome") in {"planned"}:
            continue
        project = str(row.get("project") or "").strip()
        bug_id = str(row.get("bug_id") or "").strip()
        if not project or not bug_id:
            continue
        if row.get("outcome") == "invalid_oracle":
            invalid_rows += 1
        grouped.setdefault(f"{project}:{bug_id}", []).append(row)

    counts = {"true_positive": 0, "false_positive": 0, "false_negative": 0, "true_negative": 0}
    rejected_rows = 0
    for case_rows in grouped.values():
        runnable = [row for row in case_rows if row.get("outcome") not in {"planned", "invalid_oracle"}]
        versions = {str(row.get("version") or "") for row in runnable}
        if not {"buggy", "fixed"}.issubset(versions):
            continue
        buggy = next((row for row in runnable if str(row.get("version") or "") == "buggy"), {})
        fixed = next((row for row in runnable if str(row.get("version") or "") == "fixed"), {})
        if not (buggy.get("benchmark_test_failed") is True and fixed.get("benchmark_test_failed") is False):
            rejected_rows += len(runnable)
            continue
        for row in runnable:
            outcome = str(row.get("outcome") or "")
            if outcome in counts:
                counts[outcome] += 1

    tp = counts["true_positive"]
    fp = counts["false_positive"]
    fn = counts["false_negative"]
    tn = counts["true_negative"]
    return {
        "entries": len([row for row in rows if isinstance(row, dict) and row.get("outcome") != "planned"]),
        "confirmed": tp + tn,
        "suspected": 0,
        "fixed": tn,
        "false_positive": fp,
        "false_negative": fn,
        "invalid_oracle": invalid_rows + rejected_rows,
        "precision": precision(tp, fp),
        "recall": recall(tp, fn),
        "f1": f1_score(tp, fp, fn),
        "derived_from_benchmark": True,
    }


def best_valid_benchmark(benchmarks: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [item for item in benchmarks if int(item.get("valid_differential_pairs") or 0) > 0]
    if not valid:
        return {}
    return sorted(
        valid,
        key=lambda item: (
            float(item.get("f1") or 0),
            int(item.get("valid_differential_pairs") or 0),
            -int(item.get("false_positive") or 0),
            -int(item.get("false_negative") or 0),
        ),
        reverse=True,
    )[0]


def extract_case_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        return []
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        project = str(row.get("project") or "").strip()
        bug_id = str(row.get("bug_id") or "").strip()
        if not project or not bug_id:
            continue
        by_case.setdefault(f"{project}:{bug_id}", []).append(row)

    results: list[dict[str, Any]] = []
    for case_key, case_rows in sorted(by_case.items()):
        runnable = [row for row in case_rows if row.get("outcome") not in {"planned", "invalid_oracle"}]
        versions = {str(row.get("version") or "") for row in runnable}
        if not {"buggy", "fixed"}.issubset(versions):
            continue
        buggy = next((row for row in runnable if str(row.get("version") or "") == "buggy"), {})
        fixed = next((row for row in runnable if str(row.get("version") or "") == "fixed"), {})
        differential_oracle_valid = buggy.get("benchmark_test_failed") is True and fixed.get("benchmark_test_failed") is False
        outcomes = summarize_outcomes(runnable)
        results.append(
            {
                "case": case_key,
                **outcomes,
                "differential_oracle_valid": differential_oracle_valid,
                "oracle_issue": "" if differential_oracle_valid else oracle_issue_for_pair(buggy, fixed),
                "precision": precision(outcomes["true_positive"], outcomes["false_positive"]),
                "recall": recall(outcomes["true_positive"], outcomes["false_negative"]),
                "f1": f1_score(outcomes["true_positive"], outcomes["false_positive"], outcomes["false_negative"]),
            }
        )
    return results


def aggregate_oracle_evidence(benchmarks: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    total_case_results = 0
    rejected_case_results: list[dict[str, Any]] = []
    for benchmark in benchmarks:
        for result in benchmark.get("case_results", []):
            if not isinstance(result, dict):
                continue
            case_key = str(result.get("case") or "")
            if not case_key:
                continue
            total_case_results += 1
            merged = dict(result)
            merged["run_id"] = benchmark.get("run_id", "")
            merged["updated_at"] = benchmark.get("updated_at", 0)
            merged["artifact"] = benchmark.get("html_path") or benchmark.get("path")
            if not merged.get("differential_oracle_valid"):
                rejected_case_results.append(merged)
                continue
            by_case.setdefault(case_key, []).append(merged)

    selected: list[dict[str, Any]] = []
    stable_selected: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for case_key, attempts in sorted(by_case.items()):
        attempts = sorted(attempts, key=lambda item: item.get("updated_at", 0), reverse=True)
        selected.append(attempts[0])
        signatures = {outcome_signature(item) for item in attempts}
        if len(signatures) > 1:
            disagreements.append({"case": case_key, "attempts": len(attempts), "signatures": sorted(signatures)})
        else:
            stable_selected.append(attempts[0])

    totals = summarize_outcomes(selected)
    stable_totals = summarize_outcomes(stable_selected)
    accepted_case_results = total_case_results - len(rejected_case_results)
    totals.update(
        {
            "unique_cases": len(selected),
            "stable_unique_cases": len(stable_selected),
            "unstable_cases": len(disagreements),
            "case_results_seen": total_case_results,
            "accepted_case_results": accepted_case_results,
            "duplicate_case_results_removed": max(0, accepted_case_results - len(selected)),
            "rejected_case_results": len(rejected_case_results),
            "disagreements": len(disagreements),
            "precision": precision(totals["true_positive"], totals["false_positive"]),
            "recall": recall(totals["true_positive"], totals["false_negative"]),
            "f1": f1_score(totals["true_positive"], totals["false_positive"], totals["false_negative"]),
            "precision_trials": totals["true_positive"] + totals["false_positive"],
            "recall_trials": totals["true_positive"] + totals["false_negative"],
            "precision_wilson_lower_95": wilson_lower_bound(
                totals["true_positive"],
                totals["true_positive"] + totals["false_positive"],
            ),
            "recall_wilson_lower_95": wilson_lower_bound(
                totals["true_positive"],
                totals["true_positive"] + totals["false_negative"],
            ),
            "stable_true_positive": stable_totals["true_positive"],
            "stable_false_positive": stable_totals["false_positive"],
            "stable_false_negative": stable_totals["false_negative"],
            "stable_true_negative": stable_totals["true_negative"],
            "stable_precision": precision(stable_totals["true_positive"], stable_totals["false_positive"]),
            "stable_recall": recall(stable_totals["true_positive"], stable_totals["false_negative"]),
            "stable_f1": f1_score(stable_totals["true_positive"], stable_totals["false_positive"], stable_totals["false_negative"]),
            "stable_precision_trials": stable_totals["true_positive"] + stable_totals["false_positive"],
            "stable_recall_trials": stable_totals["true_positive"] + stable_totals["false_negative"],
            "stable_precision_wilson_lower_95": wilson_lower_bound(
                stable_totals["true_positive"],
                stable_totals["true_positive"] + stable_totals["false_positive"],
            ),
            "stable_recall_wilson_lower_95": wilson_lower_bound(
                stable_totals["true_positive"],
                stable_totals["true_positive"] + stable_totals["false_negative"],
            ),
            "oracle_project_names": project_names_from_cases(selected),
            "stable_project_names": project_names_from_cases(stable_selected),
            "selected_cases": selected[:20],
            "stable_cases": stable_selected[:20],
            "disagreement_cases": disagreements[:20],
            "rejected_cases": sorted(rejected_case_results, key=lambda item: item.get("updated_at", 0), reverse=True)[:20],
        }
    )
    return totals


def oracle_issue_for_pair(buggy: dict[str, Any], fixed: dict[str, Any]) -> str:
    issues = []
    if buggy.get("benchmark_test_failed") is not True:
        issues.append("buggy_checkout_did_not_trigger")
    if fixed.get("benchmark_test_failed") is not False:
        issues.append("fixed_checkout_did_not_clear")
    return ",".join(issues) or "non_differential_pair"


def aggregate_marked_evidence(ledgers: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "ledgers": len(ledgers),
        "entries": 0,
        "confirmed": 0,
        "suspected": 0,
        "fixed": 0,
        "false_positive": 0,
        "false_negative": 0,
        "invalid_oracle": 0,
        "scored_ledgers": 0,
        "unverified_ledgers": 0,
        "benchmark_derived_ledgers": 0,
    }
    for ledger in ledgers:
        totals["entries"] += int(ledger.get("entries") or 0)
        totals["confirmed"] += int(ledger.get("confirmed") or 0)
        totals["suspected"] += int(ledger.get("suspected") or 0)
        totals["fixed"] += int(ledger.get("fixed") or 0)
        totals["false_positive"] += int(ledger.get("false_positive") or 0)
        totals["false_negative"] += int(ledger.get("false_negative") or 0)
        totals["invalid_oracle"] += int(ledger.get("invalid_oracle") or 0)
        if ledger.get("derived_from_benchmark"):
            totals["benchmark_derived_ledgers"] += 1
        if ledger.get("precision") is None and ledger.get("recall") is None and int(ledger.get("suspected") or 0) > 0:
            totals["unverified_ledgers"] += 1
        else:
            totals["scored_ledgers"] += 1
    return totals


def collect_promotion_queue(ledgers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for ledger in sorted(ledgers, key=lambda item: float(item.get("updated_at", 0)), reverse=True):
        path = Path(str(ledger.get("path", "")))
        payload = read_json(path)
        entries = payload.get("entries", []) if isinstance(payload.get("entries", []), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", "")).strip().lower()
            outcome = str(entry.get("outcome", "")).strip().lower()
            oracle = entry.get("oracle", {}) if isinstance(entry.get("oracle", {}), dict) else {}
            oracle_verdict = str(oracle.get("verdict", "")).strip().lower()
            if status != "suspected" and outcome not in {"unscored", "repair_incomplete"}:
                continue
            if oracle_verdict and oracle_verdict not in {"none", "unverified", "no_oracle"}:
                continue
            evidence = entry.get("evidence", {}) if isinstance(entry.get("evidence", {}), dict) else {}
            signals = [str(item) for item in evidence.get("signals", []) if str(item).strip()]
            steps = [str(item) for item in evidence.get("reproduction_steps", []) if str(item).strip()]
            signature = promotion_signature(entry, signals)
            row = selected.get(signature)
            if row is None:
                row = {
                    "rank": 0,
                    "run_id": str(entry.get("run_id") or ledger.get("run_id") or payload.get("run_id") or ""),
                    "repo": repo_name_from_ledger_path(path),
                    "finding_id": str(entry.get("finding_id", "")),
                    "category": str(entry.get("category", "")),
                    "severity": str(entry.get("severity", "")),
                    "target": str(entry.get("target", "")),
                    "claim": str(entry.get("claim", "")),
                    "signals": signals[:6],
                    "signal_count": len(signals),
                    "reproduction_steps": steps[:4],
                    "ledger_path": str(path),
                    "artifact": str(evidence.get("artifact", "")),
                    "first_seen_utc": utc_from_timestamp(float(ledger.get("updated_at", path.stat().st_mtime))),
                    "last_seen_utc": utc_from_timestamp(float(ledger.get("updated_at", path.stat().st_mtime))),
                    "packets_seen": 0,
                    "promotion_action": promotion_action_for(entry, signals),
                    "promotion_policy": "excluded_from_accuracy_until_oracle_or_replay_promoted",
                }
                selected[signature] = row
            row["packets_seen"] = int(row.get("packets_seen") or 0) + 1
            row["last_seen_utc"] = max(str(row.get("last_seen_utc", "")), utc_from_timestamp(float(ledger.get("updated_at", path.stat().st_mtime))))
            if len(row.get("signals", [])) < 6:
                merged_signals = list(dict.fromkeys([*row.get("signals", []), *signals]))
                row["signals"] = merged_signals[:6]
                row["signal_count"] = max(int(row.get("signal_count") or 0), len(merged_signals))
    ranked = sorted(selected.values(), key=promotion_sort_key)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def promotion_signature(entry: dict[str, Any], signals: list[str]) -> str:
    return "\n".join(
        [
            str(entry.get("target", "")),
            str(entry.get("category", "")),
            str(entry.get("claim", "")),
            "\n".join(signals[:4]),
        ]
    )


def repo_name_from_ledger_path(path: Path) -> str:
    parts = path.parts
    if "real_repos" in parts:
        index = parts.index("real_repos")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def promotion_action_for(entry: dict[str, Any], signals: list[str]) -> str:
    category = str(entry.get("category", "")).lower()
    signal_text = " ".join(signals).lower()
    if "browser" in category or "visual" in category or "browser_bug_candidates" in signal_text:
        return "Run browser replay with screenshots, DOM snapshot, and click path proof."
    if "test" in category or "traceback" in signal_text or "failed" in signal_text:
        return "Create a minimal failing test or command oracle before scoring accuracy."
    if "config" in category or "secret" in signal_text or "missing" in signal_text:
        return "Run static replay and one targeted runtime command to confirm impact."
    if "docs" in category or "todo" in signal_text or "placeholder" in signal_text:
        return "Run static replay on the file, then classify as stale docs lead or actionable docs bug."
    return "Replay the listed reproduction steps and promote only if the signal reproduces."


def promotion_sort_key(row: dict[str, Any]) -> tuple[int, int, int, str, str]:
    severity_order = {"critical": 0, "high": 1, "benchmark": 1, "medium": 2, "low": 3, "info": 4}
    action = str(row.get("promotion_action", "")).lower()
    action_priority = 0 if "minimal failing test" in action else 1 if "browser replay" in action else 2
    return (
        severity_order.get(str(row.get("severity", "")).lower(), 5),
        action_priority,
        -int(row.get("packets_seen") or 0),
        str(row.get("repo", "")),
        str(row.get("finding_id", "")),
    )


def build_promotion_triage_pack(queue: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    moves: list[dict[str, Any]] = []
    for row in queue:
        action_id = promotion_action_id(str(row.get("promotion_action", "")))
        bucket = buckets.setdefault(
            action_id,
            {
                "id": action_id,
                "label": promotion_action_label(action_id),
                "count": 0,
                "packets_seen": 0,
                "promotion_action": str(row.get("promotion_action", "")),
                "accuracy_policy": "excluded_from_accuracy_until_oracle_or_replay_promoted",
            },
        )
        bucket["count"] += 1
        bucket["packets_seen"] += int(row.get("packets_seen") or 0)

    for row in queue[:12]:
        evidence_paths = [str(path) for path in [row.get("ledger_path"), row.get("artifact")] if str(path or "").strip()]
        moves.append(
            {
                "rank": int(row.get("rank") or 0),
                "repo": str(row.get("repo", "")),
                "finding_id": str(row.get("finding_id", "")),
                "severity": str(row.get("severity", "")),
                "category": str(row.get("category", "")),
                "target": str(row.get("target", "")),
                "claim": str(row.get("claim", "")),
                "packets_seen": int(row.get("packets_seen") or 0),
                "promotion_action": str(row.get("promotion_action", "")),
                "verification_command": promotion_verification_command(row),
                "evidence_paths": evidence_paths[:4],
                "accuracy_policy": str(
                    row.get("promotion_policy", "excluded_from_accuracy_until_oracle_or_replay_promoted")
                ),
            }
        )

    return {
        "policy": (
            "Suspected leads remain excluded from accuracy until promoted by benchmark oracle, "
            "replay reproduction, or rejected as stale/false positive."
        ),
        "candidate_count": len(queue),
        "top_candidate_count": len(moves),
        "action_buckets": sorted(buckets.values(), key=lambda item: (-int(item["count"]), str(item["label"]))),
        "top_moves": moves,
        "done_definition": [
            "Promote to oracle-scored only when a benchmark or minimal failing test gives a deterministic pass/fail oracle.",
            "Promote to replay-verified when command, static, browser, or screenshot replay reproduces the packet signal.",
            "Reject or quarantine when replay contradicts the packet or the signal is absent on the current checkout.",
        ],
    }


def promotion_action_id(action: str) -> str:
    normalized = action.lower()
    if "minimal failing test" in normalized:
        return "minimal_test_oracle"
    if "browser replay" in normalized:
        return "browser_replay"
    if "static replay" in normalized and "docs" in normalized:
        return "docs_static_replay"
    if "static replay" in normalized:
        return "static_runtime_replay"
    return "manual_replay"


def promotion_action_label(action_id: str) -> str:
    labels = {
        "minimal_test_oracle": "Minimal test oracle",
        "browser_replay": "Browser replay",
        "docs_static_replay": "Docs/static replay",
        "static_runtime_replay": "Static/runtime replay",
        "manual_replay": "Manual replay",
    }
    return labels.get(action_id, action_id.replace("_", " ").title())


def promotion_verification_command(row: dict[str, Any]) -> str:
    command = extract_run_command(row.get("reproduction_steps"))
    if command:
        return command
    ledger_path = str(row.get("ledger_path", "")).strip()
    if ledger_path:
        ledger_parent = str(Path(ledger_path).parent)
        return f'python scripts\\verify_real_repo_evidence.py --root "{ledger_parent}" --max-cases 20'
    return "python scripts\\verify_real_repo_evidence.py --max-cases 20"


def extract_run_command(steps: Any) -> str:
    if not isinstance(steps, list):
        return ""
    for step in steps:
        text = str(step).strip()
        if text.lower().startswith("run "):
            command = first_backticked_value(text)
            if command:
                return command
    return ""


def first_backticked_value(text: str) -> str:
    start = text.find("`")
    if start < 0:
        return ""
    end = text.find("`", start + 1)
    if end < 0:
        return ""
    return text[start + 1 : end].strip()


def build_calibration_ledger(
    oracle_totals: dict[str, Any],
    marked_evidence: dict[str, Any],
    replay_unique: dict[str, Any],
    replay_misses: list[dict[str, Any]],
) -> dict[str, Any]:
    oracle_cases = int(oracle_totals.get("unique_cases") or 0)
    stable_cases = int(oracle_totals.get("stable_unique_cases") or 0)
    replay_verified = int(replay_unique.get("unique_reproduced") or 0) + int(
        replay_unique.get("unique_partially_reproduced") or 0
    )
    replay_quarantined = (
        int(replay_unique.get("unique_not_reproduced") or 0)
        + int(replay_unique.get("unique_unsupported") or 0)
        + int(replay_unique.get("unique_error") or 0)
    )
    suspected = int(marked_evidence.get("suspected") or 0)
    return {
        "accuracy_basis": "oracle_scored_accuracy",
        "policy": (
            "Precision and recall are computed only from benchmark cases with a valid differential oracle. "
            "Replay-verified real-repo claims prove reproducibility, not ground-truth accuracy. "
            "Quarantined replay misses and suspected leads are excluded from accuracy until an oracle or replay promotes them."
        ),
        "accuracy_case_count": oracle_cases,
        "stable_accuracy_case_count": stable_cases,
        "non_oracle_evidence_count": replay_verified + replay_quarantined + suspected,
        "quarantined_count": replay_quarantined,
        "unverified_suspected_count": suspected,
        "buckets": [
            {
                "id": "oracle_scored_accuracy",
                "label": "Oracle-scored accuracy",
                "count": oracle_cases,
                "stable_count": stable_cases,
                "contributes_to_accuracy": True,
                "confidence": "benchmark_differential_oracle",
                "policy": "included_in_precision_recall",
                "precision": oracle_totals.get("precision"),
                "precision_wilson_lower_95": oracle_totals.get("precision_wilson_lower_95"),
                "recall": oracle_totals.get("recall"),
                "recall_wilson_lower_95": oracle_totals.get("recall_wilson_lower_95"),
                "f1": oracle_totals.get("f1"),
            },
            {
                "id": "replay_verified_real_repo",
                "label": "Replay-verified real repo claims",
                "count": replay_verified,
                "contributes_to_accuracy": False,
                "confidence": "reproduced_evidence_packet",
                "policy": "reported_as_reproducibility_not_accuracy",
                "replay_rate": replay_unique.get("unique_replay_reproduction_rate"),
            },
            {
                "id": "quarantined_replay_misses",
                "label": "Quarantined replay misses",
                "count": replay_quarantined,
                "dossier_count": len(replay_misses),
                "contributes_to_accuracy": False,
                "confidence": "not_reproduced_or_unsupported",
                "policy": "excluded_from_accuracy_until_reproduced",
            },
            {
                "id": "unverified_suspected_leads",
                "label": "Unverified suspected leads",
                "count": suspected,
                "contributes_to_accuracy": False,
                "confidence": "unverified_evidence_packet",
                "policy": "excluded_from_accuracy_until_oracle_scored",
            },
        ],
    }


def aggregate_evidence_completeness(ledgers: list[dict[str, Any]]) -> dict[str, Any]:
    missing_keys = [
        "missing_identity",
        "missing_claim",
        "missing_status",
        "missing_outcome",
        "missing_evidence",
        "missing_reproduction",
        "missing_observation",
    ]
    totals: dict[str, Any] = {
        "ledgers": len(ledgers),
        "entries": 0,
        "complete_entries": 0,
        "incomplete_entries": 0,
        "completion_rate": None,
        "sample_incomplete": [],
        "strict_requirement": (
            "Each truth entry needs identity, claim, status, outcome, an evidence object, "
            "a reproduction vector, and at least one observation signal, artifact, or oracle verdict."
        ),
    }
    for key in missing_keys:
        totals[key] = 0

    sample_incomplete: list[dict[str, Any]] = []
    for ledger in ledgers:
        completeness = ledger.get("evidence_completeness", {})
        if not isinstance(completeness, dict):
            continue
        totals["entries"] += int(completeness.get("entries") or 0)
        totals["complete_entries"] += int(completeness.get("complete_entries") or 0)
        totals["incomplete_entries"] += int(completeness.get("incomplete_entries") or 0)
        for key in missing_keys:
            totals[key] += int(completeness.get(key) or 0)
        for item in completeness.get("sample_incomplete", []):
            if isinstance(item, dict) and len(sample_incomplete) < 20:
                sample_incomplete.append(item)

    entries = int(totals["entries"] or 0)
    totals["completion_rate"] = (totals["complete_entries"] / entries) if entries else None
    totals["sample_incomplete"] = sample_incomplete
    return totals


def audit_ledger_evidence(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries", [])
    entries = entries if isinstance(entries, list) else []
    totals: dict[str, Any] = {
        "entries": 0,
        "complete_entries": 0,
        "incomplete_entries": 0,
        "completion_rate": None,
        "sample_incomplete": [],
        "missing_identity": 0,
        "missing_claim": 0,
        "missing_status": 0,
        "missing_outcome": 0,
        "missing_evidence": 0,
        "missing_reproduction": 0,
        "missing_observation": 0,
    }
    sample_incomplete: list[dict[str, Any]] = []
    run_id = str(payload.get("run_id", path.parent.name))
    for index, raw_entry in enumerate(entries, start=1):
        totals["entries"] += 1
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        missing = evidence_packet_missing(entry)
        if missing:
            totals["incomplete_entries"] += 1
            for key in missing:
                totals[key] = int(totals.get(key, 0)) + 1
            if len(sample_incomplete) < 10:
                sample_incomplete.append(
                    {
                        "ledger_path": str(path),
                        "run_id": run_id,
                        "index": index,
                        "finding_id": str(entry.get("finding_id") or entry.get("id") or ""),
                        "status": str(entry.get("status") or ""),
                        "outcome": str(entry.get("outcome") or ""),
                        "missing": missing,
                    }
                )
        else:
            totals["complete_entries"] += 1
    entries_count = int(totals["entries"] or 0)
    totals["completion_rate"] = (totals["complete_entries"] / entries_count) if entries_count else None
    totals["sample_incomplete"] = sample_incomplete
    return totals


def evidence_packet_missing(entry: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not has_text(entry.get("finding_id") or entry.get("id")):
        missing.append("missing_identity")
    if not has_text(entry.get("claim")):
        missing.append("missing_claim")
    if not has_text(entry.get("status")):
        missing.append("missing_status")
    if not has_text(entry.get("outcome")):
        missing.append("missing_outcome")

    evidence = entry.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        missing.append("missing_evidence")
        missing.append("missing_reproduction")
        missing.append("missing_observation")
        return missing

    if not has_reproduction_vector(evidence):
        missing.append("missing_reproduction")
    if not has_observation(entry, evidence):
        missing.append("missing_observation")
    return missing


def has_reproduction_vector(evidence: dict[str, Any]) -> bool:
    command_keys = [
        "command",
        "checkout_command",
        "compile_command",
        "test_command",
        "run_command",
    ]
    return any(has_text(evidence.get(key)) for key in command_keys) or has_non_empty_list(evidence.get("reproduction_steps"))


def has_observation(entry: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if has_non_empty_list(evidence.get("signals")):
        return True
    if has_artifact_reference(evidence):
        return True
    if any(has_text(evidence.get(key)) for key in ["stdout_tail", "stderr_tail", "failure_tail", "actual"]):
        return True
    oracle = entry.get("oracle")
    if isinstance(oracle, dict):
        verdict = str(oracle.get("verdict") or "").strip().lower()
        if verdict and verdict not in {"none", "unverified", "no_oracle"}:
            return True
    return False


def has_artifact_reference(evidence: dict[str, Any]) -> bool:
    for key in ["artifact", "artifact_path", "screenshot", "workspace"]:
        if has_text(evidence.get(key)):
            return True
    artifacts = evidence.get("artifacts")
    if isinstance(artifacts, list):
        return any(bool(item) for item in artifacts)
    if isinstance(artifacts, dict):
        return bool(artifacts)
    return False


def has_non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and any(has_text(item) for item in value)


def has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def summarize_outcomes(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"true_positive": 0, "false_positive": 0, "false_negative": 0, "true_negative": 0}
    for row in rows:
        outcome = str(row.get("outcome") or "")
        if outcome in counts:
            counts[outcome] += 1
        else:
            for key in counts:
                counts[key] += int(row.get(key) or 0)
    return counts


def outcome_signature(item: dict[str, Any]) -> str:
    return ",".join(str(int(item.get(key) or 0)) for key in ["true_positive", "false_positive", "false_negative", "true_negative"])


def project_names_from_cases(items: list[dict[str, Any]]) -> list[str]:
    projects = set()
    for item in items:
        case = str(item.get("case", ""))
        if ":" in case:
            projects.add(case.split(":", 1)[0])
    return sorted(projects, key=str.lower)


def precision(tp: int, fp: int) -> float | None:
    denominator = tp + fp
    return None if denominator == 0 else tp / denominator


def recall(tp: int, fn: int) -> float | None:
    denominator = tp + fn
    return None if denominator == 0 else tp / denominator


def f1_score(tp: int, fp: int, fn: int) -> float | None:
    p = precision(tp, fp)
    r = recall(tp, fn)
    if p is None or r is None or p + r == 0:
        return None
    return 2 * p * r / (p + r)


def wilson_lower_bound(successes: int, trials: int, z: float = 1.96) -> float | None:
    if trials <= 0:
        return None
    p = successes / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    center = p + z2 / (2 * trials)
    margin = z * ((p * (1 - p) + z2 / (4 * trials)) / trials) ** 0.5
    return max(0.0, (center - margin) / denominator)


def render_markdown(package: dict[str, Any]) -> str:
    best = package.get("best_benchmark") or {}
    oracle_totals = package.get("oracle_totals") or {}
    marked_evidence = package.get("marked_evidence") or {}
    evidence_completeness = package.get("evidence_completeness") or {}
    real_repo_replay = package.get("real_repo_replay") or {}
    real_repo_replay_unique = package.get("real_repo_replay_unique") or {}
    real_repo_replay_misses = package.get("real_repo_replay_misses") or []
    calibration_ledger = package.get("calibration_ledger") or {}
    promotion_queue = package.get("promotion_queue") or []
    promotion_triage_pack = package.get("promotion_triage_pack") or {}
    latest_replay_reports = package.get("latest_replay_reports") or []
    replay_triage_samples = package.get("replay_triage_samples") or []
    eval_summary = package.get("eval_log_summary") or {}
    latest_events = package.get("latest_eval_events") or []
    validation = package.get("validation") or {}
    lines = [
        "# BugLab Submission Package",
        "",
        f"Updated: `{package['updated_at_utc']}`",
        "",
        "## Claim",
        "",
        package["claim"],
        "",
        "## Demo Path",
        "",
        package["demo_path"],
        "",
        "## Calibration Ledger",
        "",
        str(calibration_ledger.get("policy", "")),
        "",
        "| Bucket | Count | Accuracy? | Confidence | Policy |",
        "| --- | ---: | --- | --- | --- |",
    ]
    calibration_buckets = calibration_ledger.get("buckets", [])
    if isinstance(calibration_buckets, list) and calibration_buckets:
        for bucket in calibration_buckets:
            if not isinstance(bucket, dict):
                continue
            accuracy = "yes" if bucket.get("contributes_to_accuracy") is True else "no"
            lines.append(
                f"| {bucket.get('label', bucket.get('id', ''))} | {bucket.get('count', 0)} | "
                f"`{accuracy}` | `{bucket.get('confidence', '')}` | `{bucket.get('policy', '')}` |"
            )
    else:
        lines.append("| none | 0 | `no` | n/a | n/a |")
    lines.extend(
        [
            "",
            (
                f"Accuracy basis: `{calibration_ledger.get('accuracy_basis', 'oracle_scored_accuracy')}`. "
                f"Accuracy cases: `{calibration_ledger.get('accuracy_case_count', 0)}`. "
                f"Non-oracle evidence entries: `{calibration_ledger.get('non_oracle_evidence_count', 0)}`. "
                f"Quarantined replay misses: `{calibration_ledger.get('quarantined_count', 0)}`. "
                f"Unverified suspected leads: `{calibration_ledger.get('unverified_suspected_count', 0)}`."
            ),
            "",
            "### Promotion Triage Pack",
            "",
            str(promotion_triage_pack.get("policy", "")),
            "",
            (
                f"Candidates: `{promotion_triage_pack.get('candidate_count', 0)}`. "
                f"Top moves: `{promotion_triage_pack.get('top_candidate_count', 0)}`."
            ),
            "",
            "| Action Lane | Candidates | Packets | Promotion Action | Policy |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    action_buckets = promotion_triage_pack.get("action_buckets", [])
    if isinstance(action_buckets, list) and action_buckets:
        for bucket in action_buckets:
            if not isinstance(bucket, dict):
                continue
            lines.append(
                f"| {bucket.get('label', bucket.get('id', ''))} | {bucket.get('count', 0)} | "
                f"{bucket.get('packets_seen', 0)} | {bucket.get('promotion_action', '')} | "
                f"`{bucket.get('accuracy_policy', '')}` |"
            )
    else:
        lines.append("| none | 0 | 0 | No candidates. | n/a |")
    lines.extend(
        [
            "",
            "| Rank | Repo | Finding | Target | Verify With | Evidence |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    top_moves = promotion_triage_pack.get("top_moves", [])
    if isinstance(top_moves, list) and top_moves:
        for move in top_moves[:8]:
            if not isinstance(move, dict):
                continue
            evidence_paths = ", ".join(f"`{path}`" for path in move.get("evidence_paths", [])[:2])
            lines.append(
                f"| {move.get('rank', 0)} | `{move.get('repo', '')}` | `{move.get('finding_id', '')}` | "
                f"`{move.get('target', '')}` | `{move.get('verification_command', '')}` | "
                f"{evidence_paths or 'n/a'} |"
            )
    else:
        lines.append("| 0 | n/a | n/a | n/a | n/a | n/a |")
    lines.extend(
        [
            "",
            "### Promotion Queue",
            "",
            "These are unverified leads ranked for the next replay/oracle pass. They remain excluded from accuracy until promoted by reproduction or benchmark oracle evidence.",
            "",
            "| Rank | Repo | Finding | Severity | Category | Packets | Signals | Promotion Action | Policy |",
            "| ---: | --- | --- | --- | --- | ---: | --- | --- | --- |",
        ]
    )
    if isinstance(promotion_queue, list) and promotion_queue:
        for item in promotion_queue[:12]:
            if not isinstance(item, dict):
                continue
            signals = ", ".join(f"`{signal}`" for signal in item.get("signals", [])[:3])
            lines.append(
                f"| {item.get('rank', 0)} | `{item.get('repo', '')}` | `{item.get('finding_id', '')}` | "
                f"`{item.get('severity', '')}` | `{item.get('category', '')}` | {item.get('packets_seen', 0)} | "
                f"{signals or 'n/a'} | {item.get('promotion_action', '')} | `{item.get('promotion_policy', '')}` |"
            )
    else:
        lines.append("| 0 | n/a | n/a | n/a | n/a | 0 | n/a | No unverified promotion candidates found. | n/a |")
    lines.extend(
        [
        "",
        "## Eval Pipeline Log",
        "",
        "| Events | Completed | Failed | BugsInPy | Real Repo Audits |",
        "| ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {eval_summary.get('events', 0)} | {eval_summary.get('completed', 0)} | "
            f"{eval_summary.get('failed', 0)} | {eval_summary.get('bugsinpy', 0)} | "
            f"{eval_summary.get('real_repo_audit', 0)} |"
        ),
        "",
        "| Started | Kind | Target | Status | Summary | Artifact |",
        "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for event in latest_events[:8]:
        artifact = event.get("artifact", "")
        lines.append(
            f"| `{event.get('started_at_utc', '')}` | `{event.get('kind', '')}` | `{event.get('target_name', '')}` | "
            f"`{event.get('status', '')}` | {event.get('summary', '')} | `{artifact}` |"
        )
    if not latest_events:
        lines.append("| n/a | n/a | n/a | n/a | n/a |  |")
    lines.extend(
        [
            "",
        "## Best Valid Oracle Benchmark",
        "",
        ]
    )
    if best:
        lines.extend(
            [
                "| Run | Valid Pairs | TP | FP | FN | TN | Precision | Recall | F1 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| `{best['run_id']}` | {best['valid_differential_pairs']} | {best['true_positive']} | "
                    f"{best['false_positive']} | {best['false_negative']} | {best['true_negative']} | "
                    f"{fmt(best['precision'])} | {fmt(best['recall'])} | {fmt(best['f1'])} |"
                ),
                "",
                f"Report: `{best.get('html_path') or best.get('path')}`",
                f"Truth ledger: `{best.get('truth_ledger_path', '')}`",
            ]
        )
    else:
        lines.append("No valid oracle benchmark has been collected yet.")
    lines.extend(["", "## Accumulated Oracle Evidence", ""])
    if int(oracle_totals.get("unique_cases") or 0) > 0:
        lines.extend(
            [
                "| Unique Cases | Stable Cases | Unstable Cases | Case Results Seen | Rejected | Duplicates Removed | TP | FP | FN | TN | Precision | Precision 95% LB | Recall | Recall 95% LB | F1 |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| {oracle_totals['unique_cases']} | {oracle_totals.get('stable_unique_cases', 0)} | "
                    f"{oracle_totals.get('unstable_cases', oracle_totals.get('disagreements', 0))} | "
                    f"{oracle_totals['case_results_seen']} | {oracle_totals['rejected_case_results']} | "
                    f"{oracle_totals['duplicate_case_results_removed']} | {oracle_totals['true_positive']} | "
                    f"{oracle_totals['false_positive']} | {oracle_totals['false_negative']} | {oracle_totals['true_negative']} | "
                    f"{fmt(oracle_totals['precision'])} | {fmt(oracle_totals.get('precision_wilson_lower_95'))} | "
                    f"{fmt(oracle_totals['recall'])} | {fmt(oracle_totals.get('recall_wilson_lower_95'))} | "
                    f"{fmt(oracle_totals['f1'])} |"
                ),
                "",
                "Duplicate benchmark cases are counted once using the newest valid oracle result for that case. Stable cases are the stricter subset with one repeated outcome signature. Lower bounds are Wilson 95% confidence lower bounds, so small perfect samples cannot masquerade as high-certainty accuracy.",
            ]
        )
        lines.extend(["", "## Stable Oracle Slice", ""])
        lines.extend(
            [
                "| Stable Cases | Stable Projects | TP | FP | FN | TN | Stable Precision | Precision 95% LB | Stable Recall | Recall 95% LB | Stable F1 |",
                "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| {oracle_totals.get('stable_unique_cases', 0)} | "
                    f"`{', '.join(oracle_totals.get('stable_project_names', [])) or 'none'}` | "
                    f"{oracle_totals.get('stable_true_positive', 0)} | {oracle_totals.get('stable_false_positive', 0)} | "
                    f"{oracle_totals.get('stable_false_negative', 0)} | {oracle_totals.get('stable_true_negative', 0)} | "
                    f"{fmt(oracle_totals.get('stable_precision'))} | {fmt(oracle_totals.get('stable_precision_wilson_lower_95'))} | "
                    f"{fmt(oracle_totals.get('stable_recall'))} | {fmt(oracle_totals.get('stable_recall_wilson_lower_95'))} | "
                    f"{fmt(oracle_totals.get('stable_f1'))} |"
                ),
                "",
                "Stable metrics exclude oracle cases whose repeated attempts produced different `TP,FP,FN,TN` signatures.",
            ]
        )
        lines.extend(["", "## Oracle Case Ledger", ""])
        lines.extend(
            [
                "| Case | Selected Run | TP | FP | FN | TN | Precision | Recall | F1 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in oracle_totals.get("selected_cases", [])[:12]:
            lines.append(
                f"| `{item.get('case', '')}` | `{item.get('run_id', '')}` | {item.get('true_positive', 0)} | "
                f"{item.get('false_positive', 0)} | {item.get('false_negative', 0)} | {item.get('true_negative', 0)} | "
                f"{fmt(item.get('precision'))} | {fmt(item.get('recall'))} | {fmt(item.get('f1'))} |"
            )
        disagreement_cases = oracle_totals.get("disagreement_cases", [])
        if disagreement_cases:
            lines.extend(["", "## Oracle Disagreements", ""])
            lines.extend(
                [
                    "| Case | Attempts | Outcome Signatures |",
                    "| --- | ---: | --- |",
                ]
            )
            for item in disagreement_cases[:10]:
                signatures = ", ".join(f"`{signature}`" for signature in item.get("signatures", []))
                lines.append(f"| `{item.get('case', '')}` | {item.get('attempts', 0)} | {signatures} |")
            lines.extend(
                [
                    "",
                    "Outcome signatures are `TP,FP,FN,TN`. Disagreements stay visible instead of being averaged away.",
                ]
            )
        rejected_cases = oracle_totals.get("rejected_cases", [])
        if rejected_cases:
            lines.extend(["", "## Rejected Oracle Cases", ""])
            lines.extend(
                [
                    "| Case | Run | Issue | TP | FP | FN | TN |",
                    "| --- | --- | --- | ---: | ---: | ---: | ---: |",
                ]
            )
            for item in rejected_cases[:10]:
                lines.append(
                    f"| `{item.get('case', '')}` | `{item.get('run_id', '')}` | `{item.get('oracle_issue', '')}` | "
                    f"{item.get('true_positive', 0)} | {item.get('false_positive', 0)} | "
                    f"{item.get('false_negative', 0)} | {item.get('true_negative', 0)} |"
                )
            lines.extend(
                [
                    "",
                    "Rejected cases are not used for accuracy because the benchmark did not show a clean buggy-fails/fixed-passes differential.",
                ]
            )
    else:
        lines.append("No accumulated valid oracle evidence has been collected yet.")
    lines.extend(["", "## Marked Evidence Totals", ""])
    lines.extend(
        [
            "| Ledgers | Entries | Confirmed | Suspected | Fixed | FP | FN | Invalid Oracle | Scored Ledgers | Unverified Ledgers | Benchmark-Derived |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {marked_evidence.get('ledgers', 0)} | {marked_evidence.get('entries', 0)} | "
                f"{marked_evidence.get('confirmed', 0)} | {marked_evidence.get('suspected', 0)} | "
                f"{marked_evidence.get('fixed', 0)} | {marked_evidence.get('false_positive', 0)} | "
                f"{marked_evidence.get('false_negative', 0)} | {marked_evidence.get('invalid_oracle', 0)} | "
                f"{marked_evidence.get('scored_ledgers', 0)} | {marked_evidence.get('unverified_ledgers', 0)} | "
                f"{marked_evidence.get('benchmark_derived_ledgers', 0)} |"
            ),
            "",
            "Suspected entries are real evidence packets, but not benchmark accuracy until an oracle verifies them.",
        ]
    )
    lines.extend(["", "## Evidence Packet Completeness", ""])
    lines.extend(
        [
            "| Entries | Complete | Incomplete | Complete Rate | Missing Claim | Missing Repro | Missing Observation |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {evidence_completeness.get('entries', 0)} | "
                f"{evidence_completeness.get('complete_entries', 0)} | "
                f"{evidence_completeness.get('incomplete_entries', 0)} | "
                f"{fmt(evidence_completeness.get('completion_rate'))} | "
                f"{evidence_completeness.get('missing_claim', 0)} | "
                f"{evidence_completeness.get('missing_reproduction', 0)} | "
                f"{evidence_completeness.get('missing_observation', 0)} |"
            ),
            "",
            str(evidence_completeness.get("strict_requirement", "")),
        ]
    )
    sample_incomplete = evidence_completeness.get("sample_incomplete", [])
    if isinstance(sample_incomplete, list) and sample_incomplete:
        lines.extend(["", "| Run | Finding | Missing | Ledger |", "| --- | --- | --- | --- |"])
        for item in sample_incomplete[:8]:
            if not isinstance(item, dict):
                continue
            missing = ", ".join(f"`{name}`" for name in item.get("missing", []))
            lines.append(
                f"| `{item.get('run_id', '')}` | `{item.get('finding_id', '')}` | {missing} | `{item.get('ledger_path', '')}` |"
            )
    lines.extend(["", "## Real Repo Replay Verification", ""])
    lines.extend(
        [
            "| View | Reports | Checked / Claims | Reproduced | Partial | Not Reproduced | Unsupported | Errors | Unsupported Signals | Replay Rate | Duplicate Packets Collapsed |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| Packet-level | {real_repo_replay.get('reports', 0)} | {real_repo_replay.get('checked', 0)} | "
                f"{real_repo_replay.get('reproduced', 0)} | {real_repo_replay.get('partially_reproduced', 0)} | "
                f"{real_repo_replay.get('not_reproduced', 0)} | {real_repo_replay.get('unsupported', 0)} | "
                f"{real_repo_replay.get('error', 0)} | {real_repo_replay.get('unsupported_signals', 0)} | "
                f"{fmt(real_repo_replay.get('replay_reproduction_rate'))} | n/a |"
            ),
            (
                f"| Unique claim | n/a | {real_repo_replay_unique.get('unique_claims', 0)} | "
                f"{real_repo_replay_unique.get('unique_reproduced', 0)} | "
                f"{real_repo_replay_unique.get('unique_partially_reproduced', 0)} | "
                f"{real_repo_replay_unique.get('unique_not_reproduced', 0)} | "
                f"{real_repo_replay_unique.get('unique_unsupported', 0)} | "
                f"{real_repo_replay_unique.get('unique_error', 0)} | "
                f"{real_repo_replay_unique.get('unique_unsupported_signals', 0)} | "
                f"{fmt(real_repo_replay_unique.get('unique_replay_reproduction_rate'))} | "
                f"{real_repo_replay_unique.get('duplicate_packets_collapsed', 0)} |"
            ),
            "",
            str(real_repo_replay.get("note", "")),
            str(real_repo_replay_unique.get("note", "")),
        ]
    )
    replay_triage = real_repo_replay.get("triage", {}) if isinstance(real_repo_replay.get("triage", {}), dict) else {}
    if replay_triage:
        lines.extend(["", "| Triage Class | Packets |", "| --- | ---: |"])
        for key, value in sorted(replay_triage.items(), key=lambda item: int(item[1] or 0), reverse=True):
            lines.append(f"| `{key}` | {int(value or 0)} |")
    unique_replay_triage = (
        real_repo_replay_unique.get("triage", {})
        if isinstance(real_repo_replay_unique.get("triage", {}), dict)
        else {}
    )
    if unique_replay_triage:
        lines.extend(["", "| Unique Triage Class | Claims |", "| --- | ---: |"])
        for key, value in sorted(unique_replay_triage.items(), key=lambda item: int(item[1] or 0), reverse=True):
            lines.append(f"| `{key}` | {int(value or 0)} |")
    if isinstance(real_repo_replay_misses, list) and real_repo_replay_misses:
        lines.extend(
            [
                "",
                "### Unique Replay Miss Dossiers",
                "",
                "These claims are quarantined from accuracy claims until a replay reproduces them. Packet counts show repeated observations collapsed into one claim.",
                "",
                "| Class | Repo | Finding | Target | Packets | Missing Signals | Policy |",
                "| --- | --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for item in real_repo_replay_misses[:12]:
            if not isinstance(item, dict):
                continue
            missing = ", ".join(f"`{signal}`" for signal in item.get("missing_signals", [])[:3])
            lines.append(
                f"| `{item.get('triage_class', '')}` | `{item.get('repo', '')}` | `{item.get('finding_id', '')}` | "
                f"`{item.get('target', '')}` | {item.get('packets_collapsed', 0)} | {missing or 'n/a'} | "
                f"`{item.get('policy', '')}` |"
            )
    if isinstance(replay_triage_samples, list) and replay_triage_samples:
        lines.extend(
            [
                "",
                "### Replay Triage Samples",
                "",
                "| Class | Repo | Finding | Target | Packets | Missing Signals | Action |",
                "| --- | --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for item in replay_triage_samples[:10]:
            if not isinstance(item, dict):
                continue
            missing = ", ".join(f"`{signal}`" for signal in item.get("missing_signals", [])[:3])
            lines.append(
                f"| `{item.get('triage_class', '')}` | `{item.get('repo', '')}` | `{item.get('finding_id', '')}` | "
                f"`{item.get('target', '')}` | {item.get('packets', 0)} | {missing or 'n/a'} | "
                f"{item.get('triage_action', '')} |"
            )
    if isinstance(latest_replay_reports, list) and latest_replay_reports:
        lines.extend(["", "| Run | Checked | Reproduced | Partial | Not Reproduced | Unsupported | Artifact |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"])
        for item in latest_replay_reports[:8]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| `{item.get('run_id', '')}` | {item.get('checked', 0)} | {item.get('reproduced', 0)} | "
                f"{item.get('partially_reproduced', 0)} | {item.get('not_reproduced', 0)} | "
                f"{item.get('unsupported', 0)} | `{item.get('path', '')}` |"
            )
    lines.extend(["", "## Recent Benchmarks", "", "| Run | Cases | Valid Pairs | Rejected Pairs | Invalid Rows | Precision | Recall | F1 | Artifact |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
    for item in package["benchmarks"][:10]:
        artifact = item.get("html_path") or item.get("path")
        valid_pairs = int(item.get("valid_differential_pairs") or 0)
        lines.append(
            f"| `{item['run_id']}` | {item['cases']} | {item['valid_differential_pairs']} | "
            f"{item.get('rejected_case_results', 0)} | {item['invalid_oracle_rows']} | "
            f"{fmt(item['precision']) if valid_pairs else 'n/a'} | {fmt(item['recall']) if valid_pairs else 'n/a'} | "
            f"{fmt(item['f1']) if valid_pairs else 'n/a'} | `{artifact}` |"
        )
    if not package["benchmarks"]:
        lines.append("| none | 0 | 0 | 0 | 0 | n/a | n/a | n/a |  |")
    lines.extend(["", "## Recent Truth Ledgers", "", "| Run | Entries | Confirmed | Suspected | Fixed | FP | FN | Invalid Oracle | Artifact |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"])
    for item in package["truth_ledgers"][:10]:
        lines.append(
            f"| `{item['run_id']}` | {item['entries']} | {item['confirmed']} | {item['suspected']} | {item['fixed']} | "
            f"{item['false_positive']} | {item['false_negative']} | {item.get('invalid_oracle', 0)} | `{item['path']}` |"
        )
    if not package["truth_ledgers"]:
        lines.append("| none | 0 | 0 | 0 | 0 | 0 | 0 | 0 |  |")
    lines.extend(["", "## Submission Checks", ""])
    for key, value in package["submission_checks"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Submission Validation", ""])
    lines.append(f"- `status`: `{'PASS' if validation.get('ok') else 'FAIL'}`")
    lines.append(f"- `checks`: `{len(validation.get('checks', []))}`")
    warnings = validation.get("warnings", []) if isinstance(validation.get("warnings", []), list) else []
    failures = validation.get("failures", []) if isinstance(validation.get("failures", []), list) else []
    if warnings:
        lines.append("- `warnings`:")
        lines.extend(f"  - {item}" for item in warnings[:8])
    if failures:
        lines.append("- `failures`:")
        lines.extend(f"  - {item}" for item in failures[:8])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in package["limitations"])
    lines.append("")
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def fmt(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def utc_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
