from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.reporting import write_json
from buglab.sectors import SectorBenchmarkConfig
from buglab.sectors import load_manifest
from buglab.sectors import run_sector_benchmark
from buglab.sectors import safe_slug
from buglab.sectors import signal_matches_expected_class
from buglab.truth import SCHEMA_VERSION as TRUTH_SCHEMA_VERSION
from buglab.truth import confidence_for_status
from buglab.truth import write_truth_ledger


@dataclass(frozen=True)
class TruthHarnessConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    manifest: str | Path | None = None
    fixture_root: str | Path = ".buglab/truth_harness/fixtures"
    run_name: str = "truth_harness"
    force_fixture_pack: bool = False


def run_truth_harness(config: TruthHarnessConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    config = config or TruthHarnessConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    manifest_path = resolve_or_create_manifest(config, repo)
    sector_result = run_sector_benchmark(
        SectorBenchmarkConfig(
            manifest=manifest_path,
            repo=repo,
            output=output_root,
            loops=1,
            profiles=["truth"],
            max_clicks=0,
            run_name=config.run_name,
        )
    )
    manifest = load_manifest(manifest_path, repo)
    fixture_rows = summarize_fixture_rows(manifest, sector_result.get("rows", []))
    fix_summary = summarize_fix_counterparts(fixture_rows, manifest)
    summary = summarize_truth_harness(fixture_rows, fix_summary, round((time.perf_counter() - started) * 1000))
    run_id = f"{config.run_name}_{time.strftime('%Y%m%d_%H%M%S')}"

    csv_path = output_root / f"{config.run_name}_truth_harness.csv"
    json_path = output_root / f"{config.run_name}_truth_harness.json"
    truth_path = output_root / f"{config.run_name}_truth_ledger.json"
    write_harness_csv(csv_path, fixture_rows)
    truth_entries = build_truth_entries(run_id, fixture_rows, fix_summary, manifest_path, sector_result)
    truth_ledger = write_truth_ledger(truth_path, truth_entries, run_id=run_id, summary=summary)
    payload = {
        "schema_version": "buglab.truth_harness.v1",
        "run_id": run_id,
        "repo": str(repo),
        "manifest_path": str(manifest_path),
        "generated_fixture_pack": config.manifest is None,
        "summary": summary,
        "fixtures": fixture_rows,
        "fix_summary": fix_summary,
        "sector_result": {
            "summary": sector_result.get("summary", {}),
            "csv_path": sector_result.get("csv_path", ""),
            "json_path": sector_result.get("json_path", ""),
        },
        "truth_ledger": truth_ledger,
        "truth_ledger_path": str(truth_path),
        "truth_ledger_jsonl_path": str(truth_path.with_suffix(".jsonl")),
    }
    write_json(json_path, payload)
    return {
        "run_id": run_id,
        "summary": summary,
        "manifest_path": str(manifest_path),
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "truth_ledger_path": str(truth_path),
        "truth_ledger_jsonl_path": str(truth_path.with_suffix(".jsonl")),
        "fixtures": fixture_rows,
        "fix_summary": fix_summary,
    }


def resolve_or_create_manifest(config: TruthHarnessConfig, repo: Path) -> Path:
    if config.manifest is not None:
        manifest_path = Path(config.manifest)
        return manifest_path if manifest_path.is_absolute() else (repo / manifest_path).resolve()
    fixture_root = Path(config.fixture_root)
    if not fixture_root.is_absolute():
        fixture_root = repo / fixture_root
    return create_default_fixture_pack(repo, fixture_root, force=config.force_fixture_pack)


def create_default_fixture_pack(repo: Path, fixture_root: Path, *, force: bool = False) -> Path:
    fixture_root.mkdir(parents=True, exist_ok=True)
    data_path = fixture_root / "leads.csv"
    buggy_path = fixture_root / "customer_export_buggy.py"
    fixed_path = fixture_root / "customer_export_fixed.py"
    manifest_path = fixture_root / "manifest.json"

    write_if_missing(data_path, DEFAULT_LEADS_CSV, force=force)
    write_if_missing(buggy_path, BUGGY_EXPORTER_SOURCE, force=force)
    write_if_missing(fixed_path, FIXED_EXPORTER_SOURCE, force=force)

    output_dir = repo / ".buglab" / "truth_harness" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    rel_data = relpath(data_path, repo)
    rel_buggy = relpath(buggy_path, repo)
    rel_fixed = relpath(fixed_path, repo)
    manifest = {
        "sector": "truth_harness",
        "version": 1,
        "runner": "command",
        "description": "Minimal generated known-bug fixture pack for BugLab truth calibration.",
        "fixtures": [
            {
                "id": "customer_export_buggy",
                "target_path": rel_buggy,
                "data_paths": [rel_data],
                "expected_bug_classes": ["bad_csv_parsing", "schema_mismatch", "silent_data_loss"],
                "expected_minimum_bugs": 3,
                "unique_key": "lead_id",
                "expected_output_fields": ["lead_id", "email", "company"],
                "forbidden_output_fields": ["id", "email_address", "org"],
                "renamed_output_fields": {
                    "lead_id": "id",
                    "email": "email_address",
                    "company": "org",
                },
                "suggested_command": (
                    f"python {rel_buggy} --input {rel_data} "
                    f"--output {relpath(output_dir / 'customer_export_buggy.json', repo)}"
                ),
            },
            {
                "id": "customer_export_fixed",
                "target_path": rel_fixed,
                "data_paths": [rel_data],
                "expected_bug_classes": [],
                "expected_minimum_bugs": 0,
                "truth_role": "fixed",
                "fixes_fixture": "customer_export_buggy",
                "expected_exit_code": 0,
                "suggested_command": (
                    f"python {rel_fixed} --input {rel_data} "
                    f"--output {relpath(output_dir / 'customer_export_fixed.json', repo)}"
                ),
            },
        ],
    }
    if force or not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def write_if_missing(path: Path, text: str, *, force: bool) -> None:
    if force or not path.exists():
        path.write_text(text, encoding="utf-8")


def relpath(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return str(path.resolve())


def summarize_fixture_rows(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixtures = {str(fixture.get("id", "")): fixture for fixture in manifest.get("fixtures", []) if isinstance(fixture, dict)}
    by_fixture: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_fixture[str(row.get("fixture_id", ""))].append(row)

    summaries = []
    for fixture_id, fixture in fixtures.items():
        candidates = by_fixture.get(fixture_id, [])
        best = max(candidates, key=lambda item: float(item.get("coverage_score", 0))) if candidates else {}
        expected_classes = [str(item) for item in fixture.get("expected_bug_classes", [])]
        expected_bugs = int(fixture.get("expected_minimum_bugs", fixture.get("expected_min_bugs", len(expected_classes) or 1)))
        signals = parse_notes(str(best.get("notes", "")))
        matched = sorted({expected for expected in expected_classes if any(signal_matches_expected_class(signal, expected) for signal in signals)})
        true_positives = min(expected_bugs, len(matched) if expected_classes else int(best.get("found_bugs", 0) or 0))
        misses = max(0, expected_bugs - true_positives)
        unmatched_signals = [
            signal
            for signal in signals
            if not any(signal_matches_expected_class(signal, expected) for expected in expected_classes)
        ]
        false_positives = len(unmatched_signals) if expected_bugs else len(signals)
        found_bugs = true_positives + false_positives
        status = "passed" if misses == 0 and false_positives == 0 else "failed"
        summaries.append(
            {
                "fixture_id": fixture_id,
                "truth_role": fixture.get("truth_role", "buggy" if expected_bugs else "clean"),
                "fixes_fixture": fixture.get("fixes_fixture", ""),
                "expected_bugs": expected_bugs,
                "expected_bug_classes": expected_classes,
                "found_bugs": found_bugs,
                "true_positives": true_positives,
                "misses": misses,
                "false_positives": false_positives,
                "total_signals": len(signals),
                "matched_classes": matched,
                "unmatched_signals": unmatched_signals,
                "signals": signals,
                "coverage_score": float(best.get("coverage_score", 0) or 0),
                "expected_class_recall": float(best.get("expected_class_recall", 0) or 0),
                "run_id": best.get("run_id", ""),
                "output_dir": best.get("output_dir", ""),
                "status": status,
            }
        )
    return summaries


def parse_notes(value: str) -> list[str]:
    return [part for part in value.split(";") if part]


def summarize_fix_counterparts(fixture_rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(row["fixture_id"]): row for row in fixture_rows}
    pairs = []
    for fixture in manifest.get("fixtures", []):
        if not isinstance(fixture, dict) or not fixture.get("fixes_fixture"):
            continue
        before = by_id.get(str(fixture["fixes_fixture"]))
        after = by_id.get(str(fixture.get("id", "")))
        if not before or not after:
            continue
        before_found = int(before.get("true_positives", 0)) + int(before.get("false_positives", 0))
        after_found = int(after.get("found_bugs", 0))
        pairs.append(
            {
                "before_fixture": before["fixture_id"],
                "after_fixture": after["fixture_id"],
                "before_found_bugs": before_found,
                "after_found_bugs": after_found,
                "fix_success": before_found > 0 and after_found == 0,
            }
        )
    return {
        "supported": bool(pairs),
        "pairs": pairs,
        "before_found_bugs": sum(int(pair["before_found_bugs"]) for pair in pairs),
        "after_found_bugs": sum(int(pair["after_found_bugs"]) for pair in pairs),
        "fix_successes": sum(1 for pair in pairs if pair["fix_success"]),
        "fix_attempts": len(pairs),
        "fix_success_rate": round(sum(1 for pair in pairs if pair["fix_success"]) / len(pairs), 3) if pairs else None,
    }


def summarize_truth_harness(fixture_rows: list[dict[str, Any]], fix_summary: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    expected = sum(int(row["expected_bugs"]) for row in fixture_rows)
    true_positives = sum(int(row["true_positives"]) for row in fixture_rows)
    misses = sum(int(row["misses"]) for row in fixture_rows)
    false_positives = sum(int(row["false_positives"]) for row in fixture_rows)
    found = true_positives + false_positives
    precision = round(true_positives / found, 4) if found else None
    recall = round(true_positives / expected, 4) if expected else None
    confidence = confidence_score(expected, true_positives, misses, false_positives, fix_summary)
    return {
        "fixtures": len(fixture_rows),
        "expected_bugs": expected,
        "found_bugs": found,
        "true_positives": true_positives,
        "true_positive": true_positives,
        "misses": misses,
        "false_negative": misses,
        "false_positives": false_positives,
        "false_positive": false_positives,
        "precision": precision,
        "recall": recall,
        "confidence_score": confidence,
        "fix_supported": bool(fix_summary.get("supported")),
        "before_found_bugs": fix_summary.get("before_found_bugs") if fix_summary.get("supported") else None,
        "after_found_bugs": fix_summary.get("after_found_bugs") if fix_summary.get("supported") else None,
        "fix_success_rate": fix_summary.get("fix_success_rate"),
        "elapsed_ms": elapsed_ms,
        "status": "passed" if misses == 0 and false_positives == 0 else "failed",
    }


def confidence_score(
    expected: int,
    true_positives: int,
    misses: int,
    false_positives: int,
    fix_summary: dict[str, Any],
) -> float:
    if expected <= 0:
        base = 0.5 if false_positives else 0.8
    else:
        base = true_positives / expected
    penalty = min(0.4, 0.12 * misses + 0.08 * false_positives)
    fix_bonus = 0.05 if fix_summary.get("supported") and fix_summary.get("fix_success_rate") == 1 else 0.0
    return round(max(0.0, min(1.0, base - penalty + fix_bonus)), 3)


def write_harness_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "fixture_id",
        "truth_role",
        "expected_bugs",
        "found_bugs",
        "true_positives",
        "misses",
        "false_positives",
        "coverage_score",
        "expected_class_recall",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def build_truth_entries(
    run_id: str,
    fixture_rows: list[dict[str, Any]],
    fix_summary: dict[str, Any],
    manifest_path: Path,
    sector_result: dict[str, Any],
) -> list[dict[str, Any]]:
    entries = []
    for row in fixture_rows:
        status = "confirmed" if row["misses"] == 0 and row["expected_bugs"] else "clean"
        outcome = "true_positive" if row["expected_bugs"] and row["misses"] == 0 else "true_negative"
        if row["misses"]:
            status = "false_negative"
            outcome = "false_negative"
        elif row["false_positives"]:
            status = "false_positive"
            outcome = "false_positive"
        entries.append(
            {
                "schema_version": TRUTH_SCHEMA_VERSION,
                "finding_id": f"TRUTH-{safe_slug(str(row['fixture_id'])).upper()}",
                "run_id": run_id,
                "target": str(manifest_path),
                "phase": "find",
                "status": status,
                "outcome": outcome,
                "confidence": confidence_for_status(status),
                "claim": f"{row['fixture_id']} expected {row['expected_bugs']} bug(s), found {row['found_bugs']}.",
                "severity": "calibration",
                "category": "truth_harness",
                "evidence": {
                    "signals": row.get("signals", []),
                    "matched_classes": row.get("matched_classes", []),
                    "unmatched_signals": row.get("unmatched_signals", []),
                    "artifact": sector_result.get("json_path", ""),
                },
                "oracle": {
                    "type": "known fixture pack",
                    "verdict": "scored",
                    "expected_bugs": row["expected_bugs"],
                    "misses": row["misses"],
                    "false_positives": row["false_positives"],
                },
                "metrics": {"elapsed_ms": 0, "tokens": 0},
            }
        )
    if fix_summary.get("supported"):
        fixed = int(fix_summary.get("fix_successes", 0))
        attempts = int(fix_summary.get("fix_attempts", 0))
        status = "fixed" if attempts and fixed == attempts else "suspected"
        entries.append(
            {
                "schema_version": TRUTH_SCHEMA_VERSION,
                "finding_id": "TRUTH-FIX-CHECK",
                "run_id": run_id,
                "target": str(manifest_path),
                "phase": "fix",
                "status": status,
                "outcome": "fix_success" if status == "fixed" else "fix_incomplete",
                "confidence": 0.98 if status == "fixed" else 0.65,
                "claim": f"Fixed counterpart cleared {fixed}/{attempts} known-bug fixture pair(s).",
                "severity": "calibration",
                "category": "truth_harness_fix",
                "evidence": {"pairs": fix_summary.get("pairs", [])},
                "oracle": {"type": "before-after fixed counterpart", "verdict": "scored"},
                "metrics": {"elapsed_ms": 0, "tokens": 0},
            }
        )
    return entries


DEFAULT_LEADS_CSV = """lead_id,email,company
L-001,one@example.com,"Acme, Inc"
L-002,two@example.com,Beacon
L-002,two-duplicate@example.com,Beacon Duplicate
L-003,three@example.com,Cascade
"""


BUGGY_EXPORTER_SOURCE = '''from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    lines = Path(args.input).read_text(encoding="utf-8").splitlines()
    headers = lines[0].split(",")
    records = {}
    for line in lines[1:]:
        values = line.split(",")
        row = dict(zip(headers, values))
        records[row["lead_id"]] = {
            "id": row.get("lead_id", ""),
            "email_address": row.get("email", ""),
            "org": row.get("company", ""),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(list(records.values()), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


FIXED_EXPORTER_SOURCE = '''from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with Path(args.input).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            [
                {
                    "lead_id": row.get("lead_id", ""),
                    "email": row.get("email", ""),
                    "company": row.get("company", ""),
                }
                for row in rows
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
