from __future__ import annotations

import csv
import html
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.reporting import write_json
from buglab.sectors import SectorBenchmarkConfig
from buglab.sectors import load_manifest
from buglab.sectors import run_sector_benchmark
from buglab.sectors import safe_slug
from buglab.truth import SCHEMA_VERSION as TRUTH_SCHEMA_VERSION
from buglab.truth import confidence_for_status
from buglab.truth import write_truth_ledger


DEFAULT_FIELD_MANIFESTS: dict[str, list[str]] = {
    "browser_api": [
        "targets/sectors/html_interaction/manifest.json",
        "targets/sectors/api_workflows/manifest.json",
    ],
    "cli_data": [
        "targets/sectors/cli_data/manifest.json",
    ],
    "repo_quality": [
        "targets/sectors/docs_link_integrity/manifest.json",
        "targets/sectors/unit_tests/manifest.json",
        "targets/sectors/config_iac/manifest.json",
        "targets/sectors/security_auth/manifest.json",
        "targets/sectors/package_health/manifest.json",
    ],
}

REPAIR_SUPPORTED_SECTORS = {"html_interaction", "api_workflows", "cli_data"}


@dataclass(frozen=True)
class SwarmRunConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    fields: list[str] | None = None
    manifests: list[str] | None = None
    loops: int = 1
    profiles: list[str] | None = None
    max_clicks: int = 16
    run_name: str = "buglab_swarm"
    repair: bool = False
    build_report_index: bool = True


def run_swarm(config: SwarmRunConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    if config is None:
        config = SwarmRunConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    selected = resolve_field_manifests(config.fields, config.manifests)
    rows: list[dict[str, Any]] = []
    repair_rows: list[dict[str, Any]] = []
    started = time.perf_counter()

    for field, manifest_path in selected:
        validate_manifest_exists(repo, manifest_path)
        manifest = load_manifest(manifest_path, repo)
        sector = str(manifest.get("sector", safe_slug(Path(manifest_path).stem)))
        sector_result = run_sector_benchmark(
            SectorBenchmarkConfig(
                manifest=manifest_path,
                repo=repo,
                output=output_root,
                loops=config.loops,
                profiles=config.profiles,
                max_clicks=config.max_clicks,
                run_name=f"{config.run_name}_{safe_slug(field)}",
            )
        )
        rows.append(sector_row(field, sector, manifest_path, sector_result))
        if config.repair:
            repair_rows.append(repair_row(field, sector, manifest_path, repo, output_root, config))

    summary = summarize_swarm_rows(rows, repair_rows, round((time.perf_counter() - started) * 1000))
    csv_path = output_root / f"{config.run_name}_swarm_summary.csv"
    json_path = output_root / f"{config.run_name}_swarm_summary.json"
    html_path = output_root / f"{config.run_name}_swarm_summary.html"
    truth_path = output_root / f"{config.run_name}_truth_ledger.json"
    truth_entries = build_swarm_truth_entries(config.run_name, rows, repair_rows)
    truth_ledger = write_truth_ledger(truth_path, truth_entries, run_id=config.run_name)
    write_swarm_csv(csv_path, rows)
    write_json(
        json_path,
        {
            "summary": summary,
            "rows": rows,
            "repair_rows": repair_rows,
            "truth_ledger": truth_ledger,
            "truth_ledger_path": str(truth_path),
            "truth_ledger_jsonl_path": str(truth_path.with_suffix(".jsonl")),
        },
    )
    html_path.write_text(render_swarm_html(summary, rows, repair_rows), encoding="utf-8")
    index = None
    if config.build_report_index:
        from buglab.api import build_index

        index = build_index(repo=repo, output=output_root)
    return {
        "summary": summary,
        "rows": rows,
        "repair_rows": repair_rows,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "truth_ledger_path": str(truth_path),
        "truth_ledger_jsonl_path": str(truth_path.with_suffix(".jsonl")),
        "index": index,
    }


def resolve_field_manifests(fields: list[str] | None, manifests: list[str] | None) -> list[tuple[str, str]]:
    selected_fields = fields if fields is not None else ([] if manifests else list(DEFAULT_FIELD_MANIFESTS))
    selected: list[tuple[str, str]] = []
    for field in selected_fields:
        if field not in DEFAULT_FIELD_MANIFESTS:
            raise ValueError(f"Unknown field '{field}'. Known fields: {', '.join(DEFAULT_FIELD_MANIFESTS)}")
        selected.extend((field, manifest) for manifest in DEFAULT_FIELD_MANIFESTS[field])
    for manifest in manifests or []:
        selected.append(("custom", manifest))
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for item in selected:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def validate_manifest_exists(repo: Path, manifest: str) -> None:
    path = Path(manifest)
    if not path.is_absolute():
        path = repo / path
    if path.exists():
        return
    raise FileNotFoundError(
        f"Sector manifest not found: {path}. "
        "Default BugLab fields require this repository's targets/sectors fixture packs. "
        "For arbitrary repositories use `buglab hunt --repo <repo>`, or pass custom `buglab swarm --manifest` files."
    )


def sector_row(field: str, sector: str, manifest_path: str, result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary", {})
    return {
        "field": field,
        "sector": sector,
        "manifest": manifest_path,
        "technique": "sector_detect",
        "status": "passed" if float(summary.get("detection_rate", 0)) >= 1 else "failed",
        "fixtures": int(summary.get("fixtures", 0)),
        "runs": int(summary.get("runs", 0)),
        "fixtures_detected": int(summary.get("fixtures_detected", 0)),
        "detection_rate": float(summary.get("detection_rate", 0)),
        "avg_coverage_score": float(summary.get("avg_coverage_score", 0)),
        "avg_expected_class_recall": float(summary.get("avg_expected_class_recall", 0)),
        "total_found_bugs": int(summary.get("total_found_bugs", 0)),
        "total_unique_signals": int(summary.get("total_unique_signals", 0)),
        "best_profiles": json.dumps(summary.get("best_profiles", [])),
        "csv_path": result.get("csv_path", ""),
        "json_path": result.get("json_path", ""),
        "notes": "",
    }


def repair_row(
    field: str,
    sector: str,
    manifest_path: str,
    repo: Path,
    output_root: Path,
    config: SwarmRunConfig,
) -> dict[str, Any]:
    if sector not in REPAIR_SUPPORTED_SECTORS:
        return {
            "field": field,
            "sector": sector,
            "manifest": manifest_path,
            "technique": "repair_verify",
            "status": "skipped",
            "before": "",
            "after": "",
            "repair_success_rate": "",
            "csv_path": "",
            "json_path": "",
            "notes": "repair_not_supported_for_sector",
        }
    from buglab.repair import RepairSectorConfig
    from buglab.repair import repair_sector

    result = repair_sector(
        RepairSectorConfig(
            manifest=manifest_path,
            repo=repo,
            output=output_root,
            loops=1,
            profiles=config.profiles or ["balanced"],
            max_clicks=config.max_clicks,
            run_name=f"{config.run_name}_{safe_slug(field)}_repair",
        )
    )
    summary = result.get("summary", {})
    after = int(summary.get("total_after_found_bugs", 0))
    before = int(summary.get("total_before_found_bugs", 0))
    repair_success_rate = float(summary.get("repair_success_rate", summary.get("repair_effectiveness", 0)))
    if not repair_success_rate and before:
        repair_success_rate = max(0, before - after) / before
    return {
        "field": field,
        "sector": sector,
        "manifest": manifest_path,
        "technique": "repair_verify",
        "status": "passed" if after == 0 else "failed",
        "before": before,
        "after": after,
        "repair_success_rate": round(repair_success_rate, 3),
        "csv_path": result.get("csv_path", ""),
        "json_path": result.get("json_path", ""),
        "notes": "",
    }


def summarize_swarm_rows(rows: list[dict[str, Any]], repair_rows: list[dict[str, Any]], elapsed_ms: int) -> dict[str, Any]:
    fields = sorted({row["field"] for row in rows})
    sectors = sorted({row["sector"] for row in rows})
    passed = sum(1 for row in rows if row["status"] == "passed")
    repair_attempts = [row for row in repair_rows if row["status"] != "skipped"]
    repaired = sum(1 for row in repair_attempts if row["status"] == "passed")
    by_field: dict[str, dict[str, Any]] = {}
    for field in fields:
        field_rows = [row for row in rows if row["field"] == field]
        by_field[field] = {
            "sectors": len(field_rows),
            "passed_sectors": sum(1 for row in field_rows if row["status"] == "passed"),
            "fixtures": sum(int(row["fixtures"]) for row in field_rows),
            "runs": sum(int(row["runs"]) for row in field_rows),
            "total_found_bugs": sum(int(row["total_found_bugs"]) for row in field_rows),
            "total_unique_signals": sum(int(row["total_unique_signals"]) for row in field_rows),
            "avg_expected_class_recall": weighted_avg(field_rows, "avg_expected_class_recall", "fixtures"),
        }
    return {
        "fields": len(fields),
        "sectors": len(sectors),
        "sector_runs": len(rows),
        "passed_sectors": passed,
        "sector_pass_rate": round(passed / max(1, len(rows)), 3),
        "fixtures": sum(int(row["fixtures"]) for row in rows),
        "runs": sum(int(row["runs"]) for row in rows),
        "total_found_bugs": sum(int(row["total_found_bugs"]) for row in rows),
        "total_unique_signals": sum(int(row["total_unique_signals"]) for row in rows),
        "avg_expected_class_recall": weighted_avg(rows, "avg_expected_class_recall", "fixtures"),
        "repair_attempts": len(repair_attempts),
        "repair_passed": repaired,
        "repair_pass_rate": round(repaired / max(1, len(repair_attempts)), 3) if repair_attempts else 0,
        "elapsed_ms": elapsed_ms,
        "by_field": by_field,
    }


def build_swarm_truth_entries(run_id: str, rows: list[dict[str, Any]], repair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for row in rows:
        fixtures = int(row.get("fixtures", 0) or 0)
        detected = int(row.get("fixtures_detected", 0) or 0)
        missed = max(0, fixtures - detected)
        if fixtures and detected >= fixtures:
            status = "confirmed"
            outcome = "fixture_coverage_complete"
        elif detected > 0:
            status = "suspected"
            outcome = "fixture_coverage_partial"
        elif fixtures:
            status = "false_negative"
            outcome = "fixture_coverage_missed"
        else:
            status = "clean"
            outcome = "no_expected_fixtures"
        entries.append(
            {
                "schema_version": TRUTH_SCHEMA_VERSION,
                "finding_id": f"SWARM-{safe_slug(str(row.get('field', 'field')))}-{safe_slug(str(row.get('sector', 'sector')))}",
                "run_id": run_id,
                "target": str(row.get("manifest", "")),
                "phase": "find",
                "status": status,
                "outcome": outcome,
                "confidence": confidence_for_status(status) if status != "suspected" else 0.72,
                "claim": f"{row.get('sector', 'sector')} detected {detected}/{fixtures} expected fixtures.",
                "severity": "calibration",
                "category": str(row.get("sector", "sector")),
                "evidence": {
                    "reproduction_steps": [
                        f"Run the sector manifest `{row.get('manifest', '')}`.",
                        "Compare detected fixture classes against the manifest expected bug taxonomy.",
                        "Open the sector JSON artifact for individual fixture rows.",
                    ],
                    "signals": [
                        f"fixtures_detected={detected}",
                        f"fixtures={fixtures}",
                        f"missed_fixtures={missed}",
                        f"avg_expected_class_recall={row.get('avg_expected_class_recall', 0)}",
                    ],
                    "artifact": row.get("json_path", ""),
                },
                "oracle": {
                    "type": "sector manifest expected fixture coverage",
                    "verdict": "scored" if fixtures else "no_oracle",
                    "fixtures": fixtures,
                    "fixtures_detected": detected,
                    "missed_fixtures": missed,
                    "note": "Sector fixtures are controlled calibration targets, not broad real-world benchmark proof.",
                },
                "metrics": {
                    "elapsed_ms": 0,
                    "tokens": 0,
                },
            }
        )
    for row in repair_rows:
        if row.get("status") == "skipped":
            continue
        before = int(row.get("before", 0) or 0)
        after = int(row.get("after", 0) or 0)
        fixed = max(0, before - after)
        status = "fixed" if before and after == 0 else "suspected"
        entries.append(
            {
                "schema_version": TRUTH_SCHEMA_VERSION,
                "finding_id": f"REPAIR-{safe_slug(str(row.get('field', 'field')))}-{safe_slug(str(row.get('sector', 'sector')))}",
                "run_id": run_id,
                "target": str(row.get("manifest", "")),
                "phase": "fix",
                "status": status,
                "outcome": "repair_verified" if status == "fixed" else "repair_incomplete",
                "confidence": confidence_for_status(status),
                "claim": f"{row.get('sector', 'sector')} repair cleared {fixed}/{before} detected signals.",
                "severity": "repair",
                "category": str(row.get("sector", "sector")),
                "evidence": {
                    "reproduction_steps": [
                        f"Run repair verification for `{row.get('manifest', '')}`.",
                        "Compare before/after detected signal counts.",
                        "Open the repair JSON artifact for fixture-level repair evidence.",
                    ],
                    "signals": [
                        f"before={before}",
                        f"after={after}",
                        f"fixed={fixed}",
                        f"repair_success_rate={row.get('repair_success_rate', '')}",
                    ],
                    "artifact": row.get("json_path", ""),
                },
                "oracle": {
                    "type": "repair before/after verification",
                    "verdict": "scored",
                    "before": before,
                    "after": after,
                    "note": "Repair evidence requires post-fix verification; zero remaining signals is counted as fixed.",
                },
                "metrics": {
                    "elapsed_ms": 0,
                    "tokens": 0,
                },
            }
        )
    return entries


def weighted_avg(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float:
    total_weight = sum(max(1, int(row.get(weight_key, 0))) for row in rows)
    if not rows or total_weight == 0:
        return 0
    total = sum(float(row.get(value_key, 0)) * max(1, int(row.get(weight_key, 0))) for row in rows)
    return round(total / total_weight, 3)


def write_swarm_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def render_swarm_html(summary: dict[str, Any], rows: list[dict[str, Any]], repair_rows: list[dict[str, Any]]) -> str:
    field_rows = []
    for field, values in summary.get("by_field", {}).items():
        field_rows.append(
            "<tr>"
            f"<td>{html.escape(str(field))}</td>"
            f"<td>{values.get('sectors', 0)}</td>"
            f"<td>{values.get('passed_sectors', 0)}</td>"
            f"<td>{values.get('fixtures', 0)}</td>"
            f"<td>{values.get('total_unique_signals', 0)}</td>"
            f"<td>{values.get('avg_expected_class_recall', 0)}</td>"
            "</tr>"
        )
    sector_rows = []
    for row in rows:
        sector_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['field']))}</td>"
            f"<td>{html.escape(str(row['sector']))}</td>"
            f"<td>{html.escape(str(row['status']))}</td>"
            f"<td>{row['fixtures_detected']}/{row['fixtures']}</td>"
            f"<td>{row['avg_expected_class_recall']}</td>"
            f"<td>{row['total_unique_signals']}</td>"
            f"<td>{artifact_link(row.get('json_path', ''))}</td>"
            "</tr>"
        )
    repair_html = ""
    if repair_rows:
        repair_cells = []
        for row in repair_rows:
            repair_cells.append(
                "<tr>"
                f"<td>{html.escape(str(row['field']))}</td>"
                f"<td>{html.escape(str(row['sector']))}</td>"
                f"<td>{html.escape(str(row['status']))}</td>"
                f"<td>{html.escape(str(row.get('before', '')))}</td>"
                f"<td>{html.escape(str(row.get('after', '')))}</td>"
                f"<td>{html.escape(str(row.get('notes', '')))}</td>"
                "</tr>"
            )
        repair_html = (
            "<h2>Repair Verification</h2><table><thead><tr><th>Field</th><th>Sector</th><th>Status</th>"
            "<th>Before</th><th>After</th><th>Notes</th></tr></thead>"
            f"<tbody>{''.join(repair_cells)}</tbody></table>"
        )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BugLab Swarm Field Report</title>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f8fafc; color: #111827; }}
      main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d6dbe3; margin: 16px 0 28px; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #eef2f7; }}
      .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 16px 0 24px; }}
      .metric {{ background: white; border: 1px solid #d6dbe3; padding: 10px; }}
      .metric b {{ display: block; font-size: 22px; }}
      a {{ color: #2563eb; }}
    </style>
  </head>
  <body>
    <main>
      <h1>BugLab Swarm Field Report</h1>
      <div class="metrics">
        <div class="metric"><span>Fields</span><b>{summary.get('fields', 0)}</b></div>
        <div class="metric"><span>Sectors</span><b>{summary.get('sectors', 0)}</b></div>
        <div class="metric"><span>Pass Rate</span><b>{summary.get('sector_pass_rate', 0)}</b></div>
        <div class="metric"><span>Unique Signals</span><b>{summary.get('total_unique_signals', 0)}</b></div>
      </div>
      <h2>Field Summary</h2>
      <table>
        <thead><tr><th>Field</th><th>Sectors</th><th>Passed</th><th>Fixtures</th><th>Unique Signals</th><th>Class Recall</th></tr></thead>
        <tbody>{''.join(field_rows)}</tbody>
      </table>
      <h2>Sector Runs</h2>
      <table>
        <thead><tr><th>Field</th><th>Sector</th><th>Status</th><th>Detected</th><th>Class Recall</th><th>Unique Signals</th><th>JSON</th></tr></thead>
        <tbody>{''.join(sector_rows)}</tbody>
      </table>
      {repair_html}
    </main>
  </body>
</html>
"""


def artifact_link(path: str) -> str:
    if not path:
        return ""
    escaped = html.escape(path)
    return f"<a href='{escaped}'>{html.escape(Path(path).name)}</a>"
