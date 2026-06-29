from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BugHuntWorkflowConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/runs"
    targets: list[str] | None = None
    loops: int = 1
    profiles: list[str] | None = None
    max_clicks: int = 12
    run_name: str = "bughunt"
    include_browser: bool = True
    include_docs: bool = True
    include_tests: bool = True
    include_config: bool = True
    run_doctor: bool = True
    check_browser: bool = True
    build_pareto: bool = True
    build_report_index: bool = True
    pareto_top: int = 20


def bughunt_repo(config: BugHuntWorkflowConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    if config is None:
        config = BugHuntWorkflowConfig(**kwargs)
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y%m%d_%H%M%S")

    doctor = None
    if config.run_doctor:
        from buglab.doctor import DoctorConfig
        from buglab.doctor import doctor_repo

        doctor = doctor_repo(
            DoctorConfig(
                repo=repo,
                output=output_root,
                targets=config.targets,
                check_browser=config.check_browser and config.include_browser,
                write_report=True,
            )
        )

    from buglab.audit import RepoAuditConfig
    from buglab.audit import audit_repo

    audit = audit_repo(
        RepoAuditConfig(
            repo=repo,
            targets=config.targets,
            output=output_root,
            loops=config.loops,
            profiles=config.profiles or ["balanced"],
            max_clicks=config.max_clicks,
            run_name=config.run_name,
            include_browser=config.include_browser,
            include_docs=config.include_docs,
            include_tests=config.include_tests,
            include_config=config.include_config,
            build_report_index=False,
        )
    )

    from buglab.cases import list_case_queue

    cases = list_case_queue(repo=repo, output=output_root, run_id=audit["run_id"])

    pareto = None
    if config.build_pareto:
        from buglab.pareto import build_findings_pareto

        pareto = build_findings_pareto(repo=repo, output=output_root, top=config.pareto_top)

    index = None
    if config.build_report_index:
        from buglab.api import build_index

        index = build_index(repo=repo, output=output_root)

    summary = workflow_summary(doctor, audit, cases, pareto, index)
    path = output_root / f"{config.run_name}_{started}_workflow.json"
    payload = {
        "schema_version": "buglab.workflow.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(repo),
        "output": str(output_root),
        "workflow_path": str(path),
        "summary": summary,
        "doctor": doctor,
        "audit": audit_reference(audit),
        "cases": {
            "total_cases": cases.get("total_cases", 0),
            "run_id": cases.get("run_id", ""),
            "filters": cases.get("filters", {}),
            "case_index_path": audit.get("case_index_path", ""),
        },
        "pareto": pareto_reference(pareto),
        "index": index,
        "next_actions": next_actions(repo, summary, audit, cases, pareto, index),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def workflow_summary(
    doctor: dict[str, Any] | None,
    audit: dict[str, Any],
    cases: dict[str, Any],
    pareto: dict[str, Any] | None,
    index: dict[str, Any] | None,
) -> dict[str, Any]:
    audit_summary = audit.get("summary", {})
    pareto_summary = pareto.get("summary", {}) if pareto else {}
    return {
        "doctor_status": (doctor or {}).get("summary", {}).get("status", "skipped"),
        "audit_run_id": audit.get("run_id", ""),
        "audit_targets": int(audit_summary.get("targets", 0)),
        "failed_targets": int(audit_summary.get("failed_targets", 0)),
        "total_signals": int(audit_summary.get("total_signals", 0)),
        "case_count": int(cases.get("total_cases", 0)),
        "pareto_findings": int(pareto_summary.get("findings", 0)),
        "index_path": (index or {}).get("index_path", ""),
    }


def audit_reference(audit: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "run_id",
        "summary",
        "csv_path",
        "json_path",
        "findings_csv_path",
        "findings_jsonl_path",
        "case_index_path",
        "report_path",
    ]
    return {key: audit.get(key) for key in keys}


def pareto_reference(pareto: dict[str, Any] | None) -> dict[str, Any] | None:
    if not pareto:
        return None
    return {
        "summary": pareto.get("summary", {}),
        "csv_path": pareto.get("csv_path", ""),
        "json_path": pareto.get("json_path", ""),
        "html_path": pareto.get("html_path", ""),
    }


def next_actions(
    repo: Path,
    summary: dict[str, Any],
    audit: dict[str, Any],
    cases: dict[str, Any],
    pareto: dict[str, Any] | None,
    index: dict[str, Any] | None,
) -> list[str]:
    actions = []
    if summary["doctor_status"] == "failed":
        actions.append("Open the doctor report and fix failed install/runtime checks.")
    if summary["case_count"]:
        actions.append(f"Run `buglab cases --repo {repo} --run {audit.get('run_id', 'latest')}` to list repair-ready cases.")
    if pareto:
        actions.append(f"Open Pareto report: {pareto.get('html_path', '')}")
    if index:
        actions.append(f"Open run index: {index.get('index_path', '')}")
    return actions
