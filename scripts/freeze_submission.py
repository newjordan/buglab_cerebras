from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from build_submission_package import build_package
from build_submission_package import render_markdown
from eval_status import build_status
from validate_submission_package import validate_package


ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = Path(os.getenv("BUGLAB_BENCH_ROOT", str(ROOT / ".buglab" / "benchmarks")))
DEFAULT_EXTERNAL_ROOT = BENCH_ROOT / "buglab-runs"
DEFAULT_TRACKED_MD = ROOT / ".buglab" / "submission" / "submission_package.md"
DEFAULT_TRACKED_JSON = ROOT / ".buglab" / "submission" / "submission_results.json"
DEFAULT_LIVE_MD = DEFAULT_EXTERNAL_ROOT / "live_submission_package.md"
DEFAULT_LIVE_JSON = DEFAULT_EXTERNAL_ROOT / "live_submission_results.json"
DEFAULT_FREEZE_JSON = ROOT / ".buglab" / "submission" / "submission_freeze.json"
DELTA_METRICS = [
    "unique_oracle_cases",
    "stable_oracle_cases",
    "unstable_oracle_cases",
    "marked_entries",
    "suspected_entries",
    "incomplete_evidence_packets",
    "replay_checked",
    "replay_reproduced",
    "replay_not_reproduced",
    "unique_replay_claims",
    "unique_replay_reproduced",
    "unique_replay_not_reproduced",
    "promotion_queue_candidates",
    "rejected_case_results",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze a truth-validated BugLab submission package into tracked and live artifacts."
    )
    parser.add_argument("--repo", default=str(ROOT), help="BugLab repository root.")
    parser.add_argument(
        "--external-root",
        action="append",
        default=[str(DEFAULT_EXTERNAL_ROOT)],
        help="External benchmark/eval artifact root to scan. Repeatable.",
    )
    parser.add_argument("--tracked-output", default=str(DEFAULT_TRACKED_MD))
    parser.add_argument("--tracked-json", default=str(DEFAULT_TRACKED_JSON))
    parser.add_argument("--live-output", default=str(DEFAULT_LIVE_MD))
    parser.add_argument("--live-json", default=str(DEFAULT_LIVE_JSON))
    parser.add_argument("--freeze-json", default=str(DEFAULT_FREEZE_JSON))
    parser.add_argument("--stale-minutes", type=int, default=15)
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="Fail when eval_status would not pass against the frozen package.",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    freeze_json = Path(args.freeze_json).resolve()
    previous_freeze = read_json(freeze_json)
    scan_roots = [repo / ".buglab"]
    scan_roots.extend(Path(item).resolve() for item in args.external_root)
    package = build_package(repo, scan_roots)
    validation = validate_package(package)
    package["submission_checks"]["package_validation_passes"] = validation["ok"]
    package["validation"] = validation

    tracked_md = Path(args.tracked_output).resolve()
    tracked_json = Path(args.tracked_json).resolve()
    live_md = Path(args.live_output).resolve()
    live_json = Path(args.live_json).resolve()
    write_package(package, tracked_md, tracked_json)
    copy_or_write_package(package, tracked_md, tracked_json, live_md, live_json)

    status = build_status(package, tracked_json, stale_minutes=args.stale_minutes)
    tracked_hashes = {
        "package_sha256": sha256_file(tracked_md),
        "json_sha256": sha256_file(tracked_json),
    }
    live_hashes_after_write = {
        "package_sha256": sha256_file(live_md),
        "json_sha256": sha256_file(live_json),
    }
    live_mirror_matches_snapshot = (
        tracked_hashes["package_sha256"] == live_hashes_after_write["package_sha256"]
        and tracked_hashes["json_sha256"] == live_hashes_after_write["json_sha256"]
    )
    artifact_hashes = {
        "tracked_package_sha256": tracked_hashes["package_sha256"],
        "tracked_json_sha256": tracked_hashes["json_sha256"],
        "live_package_sha256": live_hashes_after_write["package_sha256"],
        "live_json_sha256": live_hashes_after_write["json_sha256"],
    }
    delta = build_delta(
        previous_freeze,
        validation.get("summary", {}),
        current_updated_at=str(package.get("updated_at_utc", "")),
        current_hash=tracked_hashes["json_sha256"],
    )
    freeze = {
        "schema_version": "buglab.submission_freeze.v1",
        "ok": validation["ok"] and (status["ok"] or not args.require_live),
        "tracked_package": str(tracked_md),
        "tracked_json": str(tracked_json),
        "live_package": str(live_md),
        "live_json": str(live_json),
        "artifact_hashes": artifact_hashes,
        "tracked_snapshot_hashes": tracked_hashes,
        "live_hashes_after_write": live_hashes_after_write,
        "live_mirror_attempted": True,
        "live_mirror_matches_snapshot_at_hash_time": live_mirror_matches_snapshot,
        "live_heartbeat_note": "The live package is a moving heartbeat and may advance immediately after this freeze while eval runners continue.",
        "scan_roots": [str(path) for path in scan_roots],
        "package_updated_at_utc": package.get("updated_at_utc", ""),
        "require_live": args.require_live,
        "validation_ok": validation["ok"],
        "validation_failures": validation.get("failures", []),
        "validation_warnings": validation.get("warnings", []),
        "eval_status_ok": status["ok"],
        "eval_status": status,
        "summary": validation.get("summary", {}),
        "delta_since_previous_freeze": delta,
    }
    freeze_json.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(freeze_json, json.dumps(freeze, indent=2, sort_keys=True))

    print(
        json.dumps(
            {
                "ok": freeze["ok"],
                "validation_ok": freeze["validation_ok"],
                "eval_status_ok": freeze["eval_status_ok"],
                "live_mirror_matches_snapshot_at_hash_time": freeze["live_mirror_matches_snapshot_at_hash_time"],
                "tracked_json": str(tracked_json),
                "live_json": str(live_json),
                "freeze_json": str(freeze_json),
                "summary": freeze["summary"],
                "delta_changed_metrics": freeze["delta_since_previous_freeze"].get("changed_metrics", {}),
                "delta_interpretation": freeze["delta_since_previous_freeze"].get("interpretation", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if freeze["ok"] else 1


def write_package(package: dict[str, Any], markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(markdown_path, render_markdown(package))
    atomic_write_text(json_path, json.dumps(package, indent=2))


def copy_or_write_package(
    package: dict[str, Any],
    source_markdown: Path,
    source_json: Path,
    markdown_path: Path,
    json_path: Path,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    if same_path(source_markdown, markdown_path):
        atomic_write_text(markdown_path, render_markdown(package))
    else:
        shutil.copyfile(source_markdown, markdown_path)
    if same_path(source_json, json_path):
        atomic_write_text(json_path, json.dumps(package, indent=2))
    else:
        shutil.copyfile(source_json, json_path)


def atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_delta(
    previous_freeze: dict[str, Any],
    current_summary: Any,
    *,
    current_updated_at: str,
    current_hash: str,
) -> dict[str, Any]:
    previous_summary = previous_freeze.get("summary", {}) if isinstance(previous_freeze.get("summary", {}), dict) else {}
    summary = current_summary if isinstance(current_summary, dict) else {}
    previous_hashes = (
        previous_freeze.get("tracked_snapshot_hashes", {})
        if isinstance(previous_freeze.get("tracked_snapshot_hashes", {}), dict)
        else {}
    )
    previous_hash = str(
        previous_hashes.get("json_sha256")
        or (previous_freeze.get("artifact_hashes", {}) if isinstance(previous_freeze.get("artifact_hashes", {}), dict) else {}).get(
            "tracked_json_sha256",
            "",
        )
    )
    metrics = []
    changed_metrics: dict[str, float | int] = {}
    for key in DELTA_METRICS:
        before = numeric(previous_summary.get(key))
        after = numeric(summary.get(key))
        if before is None and after is None:
            continue
        before = before or 0
        after = after or 0
        delta = after - before
        row = {"name": key, "previous": normalize_number(before), "current": normalize_number(after), "delta": normalize_number(delta)}
        metrics.append(row)
        if delta:
            changed_metrics[key] = normalize_number(delta)

    return {
        "previous_freeze_found": bool(previous_freeze),
        "previous_package_updated_at_utc": str(previous_freeze.get("package_updated_at_utc", "")),
        "current_package_updated_at_utc": current_updated_at,
        "previous_tracked_json_sha256": previous_hash,
        "current_tracked_json_sha256": current_hash,
        "tracked_json_changed": bool(previous_hash and previous_hash != current_hash),
        "changed_metrics": changed_metrics,
        "metrics": metrics,
        "interpretation": delta_interpretation(changed_metrics),
    }


def numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def normalize_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def delta_interpretation(changed_metrics: dict[str, float | int]) -> list[str]:
    if not changed_metrics:
        return ["no_scored_metric_change_since_previous_freeze"]
    notes = []
    if changed_metrics.get("unique_oracle_cases"):
        notes.append("oracle_accuracy_case_count_changed")
    if changed_metrics.get("marked_entries"):
        notes.append("marked_evidence_volume_changed")
    if changed_metrics.get("replay_reproduced") or changed_metrics.get("unique_replay_reproduced"):
        notes.append("replay_reproduced_evidence_changed")
    if changed_metrics.get("suspected_entries"):
        notes.append("unverified_suspected_leads_changed")
    if changed_metrics.get("incomplete_evidence_packets"):
        notes.append("evidence_completeness_changed")
    return notes or ["non_headline_metric_changed"]


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


if __name__ == "__main__":
    raise SystemExit(main())
