from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def list_case_queue(
    *,
    repo: str | Path = ".",
    output: str | Path = ".buglab/runs",
    run_id: str = "latest",
    sector: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    output_root = (repo_path / output).resolve() if not Path(output).is_absolute() else Path(output).resolve()
    index_path = resolve_case_index(output_root, run_id)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    cases = [hydrate_case(item) for item in payload.get("cases", [])]
    if sector:
        cases = [item for item in cases if item.get("sector") == sector]
    if severity:
        cases = [item for item in cases if item.get("severity") == severity]
    return {
        "schema_version": "buglab.case_queue.v1",
        "repo": str(repo_path),
        "run_id": index_path.parent.parent.name,
        "index_path": str(index_path),
        "total_cases": len(cases),
        "filters": {"sector": sector or "", "severity": severity or ""},
        "cases": cases,
    }


def resolve_case_index(output_root: Path, run_id: str) -> Path:
    if run_id != "latest":
        path = output_root / run_id / "cases" / "index.json"
        if not path.exists():
            raise FileNotFoundError(f"case index not found: {path}")
        return path
    candidates = [path for path in output_root.glob("*/cases/index.json") if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"no BugLab case indexes found under {output_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def hydrate_case(item: dict[str, Any]) -> dict[str, Any]:
    record = dict(item)
    case_json = Path(str(record.get("case_json_path", "")))
    if case_json.exists():
        try:
            payload = json.loads(case_json.read_text(encoding="utf-8"))
            finding = payload.get("finding", {})
            if isinstance(finding, dict):
                record.update(
                    {
                        "status": finding.get("status", record.get("status", "")),
                        "signal_count": finding.get("signal_count", record.get("signal_count", 0)),
                        "signals": finding.get("signals", record.get("signals", [])),
                        "reproduction_steps": finding.get("reproduction_steps", record.get("reproduction_steps", [])),
                        "expected": finding.get("expected", ""),
                        "actual": finding.get("actual", ""),
                        "fix_hypothesis": finding.get("fix_hypothesis", ""),
                    }
                )
        except (json.JSONDecodeError, OSError):
            record["load_error"] = f"could_not_read_case_json:{case_json}"
    return record


def render_case_queue_text(queue: dict[str, Any]) -> str:
    lines = [
        f"Case queue: {queue['run_id']}",
        f"Index: {queue['index_path']}",
        f"Cases: {queue['total_cases']}",
        "",
    ]
    for item in queue.get("cases", []):
        lines.append(
            f"{item.get('finding_id', '')} [{item.get('severity', '')}] "
            f"{item.get('sector', '')} {item.get('target', '')}"
        )
        lines.append(f"  case: {item.get('case_path', '')}")
        signals = item.get("signals", [])
        if signals:
            lines.append(f"  signals: {', '.join(str(signal) for signal in signals)}")
    return "\n".join(lines).rstrip() + "\n"
