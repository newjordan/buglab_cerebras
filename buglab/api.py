from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.hunter import HunterOptions
from buglab.hunter import bug_hunt_once


@dataclass(frozen=True)
class BugHuntConfig:
    target: str
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    run_name: str = "buglab"
    max_clicks: int = 30
    mobile: bool = False
    profile: str = "balanced"
    timeout_ms: int = 1500


@dataclass(frozen=True)
class BugLabResult:
    run_id: str
    output_dir: str
    report: dict[str, Any]

    @property
    def bug_candidate_count(self) -> int:
        return int(self.report.get("bug_candidate_count", 0))

    @property
    def controls_exercised(self) -> int:
        return int(self.report.get("controls_exercised", 0))


def bug_hunt(config: BugHuntConfig | str, **kwargs: Any) -> BugLabResult:
    if isinstance(config, str):
        config = BugHuntConfig(target=config, **kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    result = bug_hunt_once(
        HunterOptions(
            target=config.target,
            output_root=output_root,
            base_dir=repo,
            run_name=config.run_name,
            max_clicks=config.max_clicks,
            mobile=config.mobile,
            profile=config.profile,
            timeout_ms=config.timeout_ms,
        )
    )
    return BugLabResult(run_id=result["run_id"], output_dir=result["output_dir"], report=result["report"])


def run_loops(
    *,
    target: str,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    loops: int = 3,
    profiles: list[str] | None = None,
    max_clicks: int = 30,
    mobile: bool = False,
    run_name: str = "buglab_loop",
) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    output_root = (repo_path / output).resolve() if not Path(output).is_absolute() else Path(output).resolve()
    profiles = profiles or ["balanced", "business", "edge"]
    rows = []
    for loop_index in range(loops):
        profile = profiles[loop_index % len(profiles)]
        result = bug_hunt(
            BugHuntConfig(
                target=target,
                repo=repo_path,
                output=output_root,
                run_name=f"{run_name}_{loop_index + 1:02d}",
                max_clicks=max_clicks,
                mobile=mobile,
                profile=profile,
            )
        )
        row = {
            "loop": loop_index + 1,
            "profile": profile,
            "run_id": result.run_id,
            "output_dir": result.output_dir,
            "controls_discovered": result.report.get("controls_discovered", 0),
            "controls_exercised": result.report.get("controls_exercised", 0),
            "bug_candidate_count": result.report.get("bug_candidate_count", 0),
            "failure_signal_count": result.report.get("failure_signal_count", result.report.get("bug_candidate_count", 0)),
            "failure_signals": json.dumps(flatten_failure_signals(result.report), sort_keys=True),
            "elapsed_ms": result.report.get("elapsed_ms", 0),
            "agent_counts": json.dumps(result.report.get("agent_counts", {}), sort_keys=True),
        }
        rows.append(row)
    summary = summarize_rows(rows)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / f"{run_name}_loop_summary.csv"
    json_path = output_root / f"{run_name}_loop_summary.json"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return {"summary": summary, "rows": rows, "csv_path": str(csv_path), "json_path": str(json_path)}


def flatten_failure_signals(report: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    for issue in report.get("page_issues", []):
        signal = issue.get("signal")
        if signal:
            signals.append(str(signal))
    for action in report.get("actions", []):
        for signal in action.get("failures", []):
            signals.append(str(signal))
    return signals


def build_index(*, repo: str | Path = ".", output: str | Path = ".buglab/runs") -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    output_root = (repo_path / output).resolve() if not Path(output).is_absolute() else Path(output).resolve()
    manifests = []
    for path in output_root.glob("*/report_manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        manifest["_manifest_path"] = str(path)
        manifest["_report_path"] = str(path.parent / "report.html")
        manifests.append(manifest)
    manifests.sort(key=lambda item: item.get("created_at_utc", ""), reverse=True)
    aggregates = collect_aggregate_summaries(output_root)
    index_path = output_root / "index.html"
    index_path.write_text(render_index(manifests, aggregates, output_root), encoding="utf-8")
    return {"index_path": str(index_path), "standardized_runs": len(manifests), "aggregate_summaries": len(aggregates)}


def repair_sector_manifest(
    *,
    manifest: str | Path,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    loops: int = 1,
    profiles: list[str] | None = None,
    max_clicks: int = 30,
    run_name: str = "repair",
) -> dict[str, Any]:
    from buglab.repair import RepairSectorConfig
    from buglab.repair import repair_sector

    return repair_sector(
        RepairSectorConfig(
            manifest=manifest,
            repo=repo,
            output=output,
            loops=loops,
            profiles=profiles,
            max_clicks=max_clicks,
            run_name=run_name,
        )
    )


def init_project(
    *,
    repo: str | Path = ".",
    config_path: str | Path = ".buglab/config.json",
    targets: list[str] | None = None,
    output: str = ".buglab/runs",
    loops: int = 3,
    profiles: list[str] | None = None,
    max_clicks: int = 30,
    force: bool = False,
) -> dict[str, Any]:
    from buglab.project import init_project_config

    return init_project_config(
        repo=repo,
        config_path=config_path,
        targets=targets,
        output=output,
        loops=loops,
        profiles=profiles,
        max_clicks=max_clicks,
        force=force,
    )


def run_matrix(
    *,
    repo: str | Path = ".",
    config_path: str | Path = ".buglab/config.json",
    output: str | Path | None = None,
    loops: int | None = None,
    profiles: list[str] | None = None,
    max_clicks: int | None = None,
    run_name: str = "buglab_matrix",
    target_ids: list[str] | None = None,
    build_report_index: bool = True,
) -> dict[str, Any]:
    from buglab.project import run_project_matrix

    return run_project_matrix(
        repo=repo,
        config_path=config_path,
        output=output,
        loops=loops,
        profiles=profiles,
        max_clicks=max_clicks,
        run_name=run_name,
        target_ids=target_ids,
        build_report_index=build_report_index,
    )


def scan_repo(
    *,
    repo: str | Path = ".",
    config_path: str | Path = ".buglab/config.json",
    targets: list[str] | None = None,
    output: str | Path | None = None,
    loops: int = 3,
    profiles: list[str] | None = None,
    max_clicks: int = 30,
    run_name: str = "buglab_scan",
    force_init: bool = False,
    target_ids: list[str] | None = None,
    build_report_index: bool = True,
) -> dict[str, Any]:
    from buglab.project import scan_repo as scan_project_repo

    return scan_project_repo(
        repo=repo,
        config_path=config_path,
        targets=targets,
        output=output,
        loops=loops,
        profiles=profiles,
        max_clicks=max_clicks,
        run_name=run_name,
        force_init=force_init,
        target_ids=target_ids,
        build_report_index=build_report_index,
    )


def audit_repo(**kwargs: Any) -> dict[str, Any]:
    from buglab.audit import RepoAuditConfig
    from buglab.audit import audit_repo as run_repo_audit

    return run_repo_audit(RepoAuditConfig(**kwargs))


def list_cases(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    run_id: str = "latest",
    sector: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    from buglab.cases import list_case_queue

    return list_case_queue(repo=repo, output=output, run_id=run_id, sector=sector, severity=severity)


def build_pareto(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    top: int = 20,
) -> dict[str, Any]:
    from buglab.pareto import build_findings_pareto

    return build_findings_pareto(repo=repo, output=output, top=top)


def calibrate_findings(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    ledger: str | Path = ".buglab/calibration/truth_ledger.json",
    top: int = 20,
) -> dict[str, Any]:
    from buglab.calibration import CalibrationConfig
    from buglab.calibration import calibrate_findings as run_calibration

    return run_calibration(CalibrationConfig(repo=repo, output=output, ledger=ledger, top=top))


def benchmark_bugsinpy(
    *,
    bugsinpy_root: str | Path,
    output: str | Path = ".buglab/benchmarks/bugsinpy",
    workspace: str | Path = ".buglab/benchmarks/bugsinpy/workspaces",
    cases: list[str] | None = None,
    case_file: str | Path | None = None,
    run_name: str = "bugsinpy",
    timeout_seconds: int = 180,
    dry_run: bool = False,
    keep_workspaces: bool = True,
) -> dict[str, Any]:
    from buglab.benchmarks import BugsInPyBenchmarkConfig
    from buglab.benchmarks import run_bugsinpy_benchmark

    return run_bugsinpy_benchmark(
        BugsInPyBenchmarkConfig(
            bugsinpy_root=bugsinpy_root,
            output=output,
            workspace=workspace,
            cases=cases,
            case_file=case_file,
            run_name=run_name,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run,
            keep_workspaces=keep_workspaces,
        )
    )


def run_truth_harness(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    manifest: str | Path | None = None,
    fixture_root: str | Path = ".buglab/truth_harness/fixtures",
    run_name: str = "truth_harness",
    force_fixture_pack: bool = False,
) -> dict[str, Any]:
    from buglab.truth_harness import TruthHarnessConfig
    from buglab.truth_harness import run_truth_harness as run_harness

    return run_harness(
        TruthHarnessConfig(
            repo=repo,
            output=output,
            manifest=manifest,
            fixture_root=fixture_root,
            run_name=run_name,
            force_fixture_pack=force_fixture_pack,
        )
    )


def run_quality(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/quality",
    run_name: str = "quality",
    profile: str = "auto",
    timeout_seconds: int = 180,
    include_audit: bool = False,
) -> dict[str, Any]:
    from buglab.quality import QualityConfig
    from buglab.quality import run_quality_gate

    return run_quality_gate(
        QualityConfig(
            repo=repo,
            output=output,
            run_name=run_name,
            profile=profile,
            timeout_seconds=timeout_seconds,
            include_audit=include_audit,
        )
    )


def run_medic(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/medic",
    run_name: str = "medic",
    quality_report: str | Path | None = None,
    tool_runs: str | Path | None = None,
    run_quality: bool = False,
    profile: str = "auto",
) -> dict[str, Any]:
    from buglab.medic import MedicConfig
    from buglab.medic import run_medic as run_medic_agent

    return run_medic_agent(
        MedicConfig(
            repo=repo,
            output=output,
            run_name=run_name,
            quality_report=quality_report,
            tool_runs=tool_runs,
            run_quality=run_quality,
            profile=profile,
        )
    )


def doctor_repo(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    targets: list[str] | None = None,
    check_browser: bool = True,
    write_report: bool = True,
) -> dict[str, Any]:
    from buglab.doctor import DoctorConfig
    from buglab.doctor import doctor_repo as run_doctor

    return run_doctor(
        DoctorConfig(
            repo=repo,
            output=output,
            targets=targets,
            check_browser=check_browser,
            write_report=write_report,
        )
    )


def bughunt_repo(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    targets: list[str] | None = None,
    loops: int = 1,
    profiles: list[str] | None = None,
    max_clicks: int = 12,
    run_name: str = "bughunt",
    include_browser: bool = True,
    include_docs: bool = True,
    include_tests: bool = True,
    include_config: bool = True,
    run_doctor: bool = True,
    check_browser: bool = True,
    build_pareto: bool = True,
    build_report_index: bool = True,
    pareto_top: int = 20,
) -> dict[str, Any]:
    from buglab.workflow import BugHuntWorkflowConfig
    from buglab.workflow import bughunt_repo as run_workflow

    return run_workflow(
        BugHuntWorkflowConfig(
            repo=repo,
            output=output,
            targets=targets,
            loops=loops,
            profiles=profiles,
            max_clicks=max_clicks,
            run_name=run_name,
            include_browser=include_browser,
            include_docs=include_docs,
            include_tests=include_tests,
            include_config=include_config,
            run_doctor=run_doctor,
            check_browser=check_browser,
            build_pareto=build_pareto,
            build_report_index=build_report_index,
            pareto_top=pareto_top,
        )
    )


def run_swarm(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    fields: list[str] | None = None,
    manifests: list[str] | None = None,
    loops: int = 1,
    profiles: list[str] | None = None,
    max_clicks: int = 16,
    run_name: str = "buglab_swarm",
    repair: bool = False,
    build_report_index: bool = True,
) -> dict[str, Any]:
    from buglab.swarm import SwarmRunConfig
    from buglab.swarm import run_swarm as run_field_swarm

    return run_field_swarm(
        SwarmRunConfig(
            repo=repo,
            output=output,
            fields=fields,
            manifests=manifests,
            loops=loops,
            profiles=profiles,
            max_clicks=max_clicks,
            run_name=run_name,
            repair=repair,
            build_report_index=build_report_index,
        )
    )


def run_ablation(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    fields: list[str] | None = None,
    manifests: list[str] | None = None,
    profile_sets: list[str] | None = None,
    loops: int = 1,
    repeats: int = 1,
    max_clicks: int = 16,
    run_name: str = "swarm_ablation",
    repair: bool = False,
    build_report_index: bool = True,
) -> dict[str, Any]:
    from buglab.ablation import SwarmAblationConfig
    from buglab.ablation import run_swarm_ablation

    return run_swarm_ablation(
        SwarmAblationConfig(
            repo=repo,
            output=output,
            fields=fields,
            manifests=manifests,
            profile_sets=profile_sets,
            loops=loops,
            repeats=repeats,
            max_clicks=max_clicks,
            run_name=run_name,
            repair=repair,
            build_report_index=build_report_index,
        )
    )


def collect_aggregate_summaries(output_root: Path) -> list[dict[str, Any]]:
    candidates: list[tuple[Path, str]] = []
    for suffix, kind in [
        ("*_matrix_summary.json", "matrix"),
        ("*_loop_summary.json", "loop"),
        ("*_sector_summary.json", "sector"),
        ("*_swarm_summary.json", "swarm"),
        ("*_ablation_summary.json", "ablation"),
        ("*_workflow.json", "workflow"),
        ("findings_pareto.json", "pareto"),
        ("doctor_*.json", "doctor"),
    ]:
        candidates.extend((path, kind) for path in output_root.glob(suffix))
    candidates.extend((path, "audit") for path in output_root.glob("*/repo_audit.json"))

    aggregates = []
    for path, kind in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        if not isinstance(summary, dict):
            summary = {}
        csv_path = path.with_suffix(".csv")
        if kind == "audit":
            csv_path = path.parent / "repo_audit_rows.csv"
        aggregates.append(
            {
                "kind": kind,
                "name": aggregate_name(path, payload, kind),
                "json_path": str(path),
                "csv_path": str(csv_path) if csv_path.exists() else "",
                "status": aggregate_status(kind, summary),
                "summary": summary,
                "updated_at": path.stat().st_mtime,
            }
        )
    aggregates.sort(key=lambda item: float(item["updated_at"]), reverse=True)
    return aggregates


def aggregate_name(path: Path, payload: Any, kind: str) -> str:
    if isinstance(payload, dict) and payload.get("run_id"):
        return str(payload["run_id"])
    return path.stem.replace(f"_{kind}_summary", "")


def aggregate_status(kind: str, summary: dict[str, Any]) -> str:
    if kind == "sector":
        return "failed" if float(summary.get("detection_rate", 0)) < 1 else "passed"
    if kind == "audit":
        return "failed" if int(summary.get("failed_targets", 0)) else "passed"
    if kind == "pareto":
        return "failed" if int(summary.get("findings", 0)) else "passed"
    if kind == "swarm":
        return "failed" if float(summary.get("sector_pass_rate", 0)) < 1 else "passed"
    if kind == "ablation":
        return "failed" if int(summary.get("pareto_variants", 0)) == 0 else "passed"
    if kind == "doctor":
        return "failed" if summary.get("status") == "failed" else "passed"
    if kind == "workflow":
        return "failed" if int(summary.get("failed_targets", 0)) else "passed"
    if kind in {"matrix", "loop"}:
        return "failed" if int(summary.get("total_bug_candidates", 0)) else "passed"
    return "unknown"


def render_index(manifests: list[dict[str, Any]], aggregates: list[dict[str, Any]], output_root: Path) -> str:
    aggregate_rows = []
    for aggregate in aggregates:
        json_href = relative_href(Path(aggregate["json_path"]), output_root)
        csv_path = str(aggregate.get("csv_path") or "")
        csv_href = relative_href(Path(csv_path), output_root) if csv_path else ""
        links = f"<a href='{html.escape(json_href)}'>json</a>"
        if csv_href:
            links += f" | <a href='{html.escape(csv_href)}'>csv</a>"
        aggregate_rows.append(
            "<tr>"
            f"<td>{html.escape(str(aggregate['kind']))}</td>"
            f"<td>{html.escape(str(aggregate['name']))}</td>"
            f"<td>{html.escape(str(aggregate['status']))}</td>"
            f"<td>{html.escape(compact_summary(aggregate.get('summary', {})))}</td>"
            f"<td>{links}</td>"
            "</tr>"
        )
    rows = []
    for manifest in manifests:
        report_path = Path(manifest["_report_path"])
        href = relative_href(report_path, output_root)
        metrics = ", ".join(manifest.get("metrics", {}).keys())
        rows.append(
            "<tr>"
            f"<td><a href='{html.escape(href)}'>{html.escape(manifest.get('run_id', ''))}</a></td>"
            f"<td>{html.escape(manifest.get('tool', ''))}</td>"
            f"<td>{html.escape(manifest.get('target', ''))}</td>"
            f"<td>{html.escape(manifest.get('status', ''))}</td>"
            f"<td>{len(manifest.get('findings', []))}</td>"
            f"<td>{len(manifest.get('evidence', []))}</td>"
            f"<td>{html.escape(metrics)}</td>"
            f"<td>{html.escape(manifest.get('created_at_utc', ''))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BugLab Run Index</title>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; background: #f8fafc; color: #111827; }}
      main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }}
      table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d6dbe3; border-radius: 8px; overflow: hidden; margin: 16px 0 28px; }}
      th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; vertical-align: top; }}
      th {{ background: #eef2f7; }}
      a {{ color: #2563eb; }}
      code {{ background: #eef2f7; padding: 2px 4px; border-radius: 4px; }}
    </style>
  </head>
  <body>
    <main>
      <h1>BugLab Run Index</h1>
      <p>Dynamic index of aggregate experiment summaries and standardized manifests under this repo.</p>
      <h2>Aggregate Summaries</h2>
      <table>
        <thead><tr><th>Type</th><th>Name</th><th>Status</th><th>Summary Metrics</th><th>Artifacts</th></tr></thead>
        <tbody>{''.join(aggregate_rows) or '<tr><td colspan="5">No aggregate summaries found.</td></tr>'}</tbody>
      </table>
      <h2>Standardized Runs</h2>
      <table>
        <thead><tr><th>Run</th><th>Tool</th><th>Target</th><th>Status</th><th>Findings</th><th>Evidence</th><th>Metrics</th><th>Created</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </main>
  </body>
</html>
"""


def relative_href(path: Path, output_root: Path) -> str:
    try:
        return path.resolve().relative_to(output_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def compact_summary(summary: dict[str, Any]) -> str:
    priority = [
        "targets",
        "runs",
        "fixtures",
        "fixtures_detected",
        "failed_targets",
        "total_signals",
        "detection_rate",
        "avg_coverage_score",
        "avg_expected_class_recall",
        "total_bug_candidates",
        "total_failure_signals",
        "total_found_bugs",
        "total_unique_signals",
        "sector_pass_rate",
        "variants",
        "pareto_variants",
        "avg_expected_class_recall",
        "repair_pass_rate",
        "case_count",
        "doctor_status",
        "status",
        "warnings",
        "failed",
    ]
    parts = []
    for key in priority:
        if key in summary:
            parts.append(f"{key}={summary[key]}")
    if not parts:
        for key, value in list(summary.items())[:6]:
            if isinstance(value, (str, int, float, bool)):
                parts.append(f"{key}={value}")
    return "; ".join(parts)


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    bug_counts = [int(row["bug_candidate_count"]) for row in rows]
    elapsed = [int(row["elapsed_ms"]) for row in rows]
    return {
        "runs": len(rows),
        "total_bug_candidates": sum(bug_counts),
        "max_bug_candidates": max(bug_counts),
        "min_bug_candidates": min(bug_counts),
        "avg_bug_candidates": round(sum(bug_counts) / len(bug_counts), 2),
        "avg_elapsed_ms": round(sum(elapsed) / len(elapsed), 2),
        "best_profiles": sorted(
            {
                row["profile"]: max(int(candidate["bug_candidate_count"]) for candidate in rows if candidate["profile"] == row["profile"])
                for row in rows
            }.items(),
            key=lambda item: item[1],
            reverse=True,
        ),
    }
