from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "buglab.truth_ledger.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def write_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


def write_truth_ledger(path: Path, entries: list[dict[str, Any]], *, run_id: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger_summary = summary or summarize_truth_entries(entries)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "summary": ledger_summary,
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_jsonl(path.with_suffix(".jsonl"), entries)
    return payload


def summarize_truth_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = count_by(entries, "status")
    outcomes = count_by(entries, "outcome")
    tp = outcomes.get("true_positive", 0)
    fp = outcomes.get("false_positive", 0)
    fn = outcomes.get("false_negative", 0)
    tn = outcomes.get("true_negative", 0)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    confirmed = statuses.get("confirmed", 0) + statuses.get("fixed", 0)
    tokens = sum(safe_int(entry.get("metrics", {}).get("tokens", 0)) for entry in entries)
    elapsed_ms = sum(safe_int(entry.get("metrics", {}).get("elapsed_ms", 0)) for entry in entries)
    return {
        "entries": len(entries),
        "confirmed": confirmed,
        "suspected": statuses.get("suspected", 0),
        "fixed": statuses.get("fixed", 0),
        "clean": statuses.get("clean", 0),
        "false_positive": fp or statuses.get("false_positive", 0),
        "false_negative": fn or statuses.get("false_negative", 0),
        "true_positive": tp,
        "true_negative": tn,
        "invalid_oracle": statuses.get("invalid_oracle", 0),
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "tokens": tokens,
        "elapsed_ms": elapsed_ms,
        "tokens_per_confirmed": round(tokens / confirmed, 2) if confirmed and tokens else None,
    }


def count_by(entries: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        value = str(entry.get(key, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def outcome_to_truth_status(outcome: str) -> str:
    return {
        "true_positive": "confirmed",
        "true_negative": "clean",
        "false_positive": "false_positive",
        "false_negative": "false_negative",
        "invalid_oracle": "invalid_oracle",
        "planned": "planned",
    }.get(outcome, "suspected")


def confidence_for_status(status: str) -> float:
    return {
        "confirmed": 0.99,
        "fixed": 0.98,
        "clean": 0.96,
        "false_positive": 0.95,
        "false_negative": 0.95,
        "invalid_oracle": 0.0,
        "planned": 0.0,
    }.get(status, 0.55)


def synthesize_report_truth_ledger(manifest: dict[str, Any]) -> dict[str, Any]:
    entries = []
    run_id = str(manifest.get("run_id", ""))
    metrics = {
        name: item.get("value")
        for name, item in manifest.get("metrics", {}).items()
        if isinstance(item, dict) and "value" in item
    }
    evidence_by_id = {str(item.get("id")): item for item in manifest.get("evidence", []) if isinstance(item, dict)}
    for finding in manifest.get("findings", []):
        if not isinstance(finding, dict):
            continue
        status = "fixed" if str(finding.get("status", "")).lower() in {"fixed", "resolved", "closed"} else "suspected"
        evidence_ids = [str(item) for item in finding.get("evidence_ids", [])]
        entries.append(
            {
                "schema_version": SCHEMA_VERSION,
                "finding_id": str(finding.get("id", "")),
                "run_id": run_id,
                "target": str(manifest.get("target", "")),
                "phase": "find",
                "status": status,
                "outcome": "unscored",
                "confidence": confidence_for_status(status),
                "claim": str(finding.get("title", "")),
                "severity": str(finding.get("severity", "unknown")),
                "category": str(finding.get("category", "")),
                "evidence": {
                    "command": str(finding.get("command", "")),
                    "reproduction_steps": finding.get("reproduction_steps", []) or [],
                    "signals": finding.get("signals", []) or [],
                    "selector": finding.get("selector", ""),
                    "artifact": str(finding.get("artifact", "")),
                    "expected": str(finding.get("expected", "")),
                    "actual": str(finding.get("actual", "")),
                    "evidence_ids": evidence_ids,
                    "artifacts": [evidence_by_id[item] for item in evidence_ids if item in evidence_by_id],
                },
                "oracle": {
                    "type": "none",
                    "verdict": "unverified",
                    "note": "No benchmark oracle was attached; treat this as a bug claim that still needs reproduction.",
                },
                "metrics": {
                    "elapsed_ms": safe_int(metrics.get("elapsed_ms", 0)),
                    "tokens": safe_int(metrics.get("estimated_tokens", 0) or metrics.get("tokens", 0)),
                },
            }
        )
    return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "summary": summarize_truth_entries(entries), "entries": entries}
