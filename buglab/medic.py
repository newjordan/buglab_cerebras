from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.quality import QualityConfig
from buglab.quality import run_quality_gate
from buglab.quality import safe_slug
from buglab.quality import scan_repo_hygiene


MEDIC_AGENT = {
    "name": "Medic",
    "role": "tool and agent optimization",
    "mandate": "Keep the bug-hunt loop honest by separating real product bugs from broken tools, flaky environments, and incomplete repair verification.",
    "loop": [
        "read quality artifacts",
        "classify the failure family",
        "choose the smallest next repair",
        "rerun the proving gate",
        "escalate only when the same failure repeats",
    ],
}


@dataclass(frozen=True)
class MedicConfig:
    repo: str | Path = "."
    output: str | Path = ".buglab/medic"
    run_name: str = "medic"
    quality_report: str | Path | None = None
    tool_runs: str | Path | None = None
    run_quality: bool = False
    profile: str = "auto"


def run_medic(config: MedicConfig) -> dict[str, Any]:
    repo = Path(config.repo).resolve()
    output_root = (repo / config.output).resolve() if not Path(config.output).is_absolute() else Path(config.output).resolve()
    run_id = f"{safe_slug(config.run_name)}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    quality = load_or_run_quality(repo, config, out_dir)
    tool_artifacts = load_tool_artifacts(config.tool_runs)
    diagnoses = []
    diagnoses.extend(diagnose_quality(quality))
    diagnoses.extend(diagnose_tool_artifacts(tool_artifacts))
    diagnoses.extend(diagnose_hygiene(repo))
    diagnoses = dedupe_diagnoses(diagnoses)
    recommendations = build_recommendations(diagnoses)
    summary = summarize_medic(diagnoses)

    payload: dict[str, Any] = {
        "schema_version": "buglab.medic.v1",
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "repo": str(repo),
        "output_dir": str(out_dir),
        "agent": MEDIC_AGENT,
        "summary": summary,
        "quality_report": quality_reference(quality),
        "tool_artifacts": tool_artifacts["summary"],
        "diagnoses": diagnoses,
        "recommendations": recommendations,
    }
    json_path = out_dir / "medic_report.json"
    md_path = out_dir / "medic_report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_medic_markdown(payload), encoding="utf-8")
    payload["json_path"] = str(json_path)
    payload["markdown_path"] = str(md_path)
    return payload


def load_or_run_quality(repo: Path, config: MedicConfig, out_dir: Path) -> dict[str, Any] | None:
    if config.quality_report:
        path = Path(config.quality_report)
        if not path.is_absolute():
            path = repo / path
        return json.loads(path.read_text(encoding="utf-8"))
    if config.run_quality:
        return run_quality_gate(
            QualityConfig(
                repo=repo,
                output=out_dir / "quality",
                run_name=f"{config.run_name}_quality",
                profile=config.profile,
            )
        )
    return None


def load_tool_artifacts(tool_runs: str | Path | None) -> dict[str, Any]:
    if not tool_runs:
        return {"summary": {"path": "", "files": 0}, "files": []}
    root = Path(tool_runs).resolve()
    files: list[dict[str, Any]] = []
    if not root.exists():
        return {"summary": {"path": str(root), "files": 0, "missing": True}, "files": []}
    for path in sorted(root.glob("*")):
        if not path.is_file():
            continue
        item: dict[str, Any] = {"path": str(path), "name": path.name, "suffix": path.suffix.lower()}
        if path.suffix.lower() == ".json":
            try:
                item["json"] = json.loads(read_text_flexible(path))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                item["parse_error"] = True
        else:
            try:
                text = read_text_flexible(path)
                item["text_probe"] = text[:200000] + "\n...\n" + text[-20000:]
                item["text_tail"] = text[-5000:]
            except OSError:
                item["read_error"] = True
        files.append(item)
    return {"summary": {"path": str(root), "files": len(files)}, "files": files}


def diagnose_quality(quality: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not quality:
        return []
    diagnoses: list[dict[str, Any]] = []
    for command in quality.get("commands", []):
        if command.get("status") != "failed":
            continue
        text = f"{command.get('stdout_tail', '')}\n{command.get('stderr_tail', '')}"
        diagnoses.extend(diagnose_text(text, source=command.get("label", command.get("id", "quality")), command=command))
        if "diff_hygiene" in command.get("signals", []):
            diagnoses.append(
                diagnosis(
                    "repo_hygiene",
                    "medium",
                    "Git diff hygiene gate failed.",
                    "Inspect git diff --check output for whitespace errors, conflict markers, or malformed patch state before repair claims.",
                    {"command": command.get("command", ""), "stdout_tail": command.get("stdout_tail", ""), "stderr_tail": command.get("stderr_tail", "")},
                )
            )
    if quality.get("summary", {}).get("patch_leftover_count", 0):
        diagnoses.append(
            diagnosis(
                "repo_hygiene",
                "medium",
                "Patch leftovers found in repository.",
                "Review .rej/.orig/.original/.fix files and either remove generated leftovers or convert them into tracked evidence.",
                {"count": quality["summary"]["patch_leftover_count"]},
            )
        )
    return diagnoses


def diagnose_tool_artifacts(tool_artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    diagnoses: list[dict[str, Any]] = []
    for item in tool_artifacts.get("files", []):
        name = str(item.get("name", ""))
        if name == "npm-audit.json" and isinstance(item.get("json"), dict):
            diagnoses.extend(diagnose_npm_audit(item["json"], item["path"]))
            continue
        text = str(item.get("text_probe") or item.get("text_tail", ""))
        if text:
            diagnoses.extend(diagnose_text(text, source=name, command=None))
    return diagnoses


def diagnose_hygiene(repo: Path) -> list[dict[str, Any]]:
    hygiene = scan_repo_hygiene(repo)
    if not hygiene.get("patch_leftover_count"):
        return []
    return [
        diagnosis(
            "repo_hygiene",
            "medium",
            "Patch/reject/original backup files are present.",
            "Treat these as a failed repair cleanup signal before claiming a clean fix.",
            {"count": hygiene["patch_leftover_count"], "examples": hygiene.get("patch_leftovers", [])[:10]},
        )
    ]


def diagnose_text(text: str, *, source: str, command: dict[str, Any] | None) -> list[dict[str, Any]]:
    lowered = text.lower()
    details: dict[str, Any] = {"source": source}
    if command:
        details["command"] = command.get("command", "")
        details["exit_code"] = command.get("exit_code")
    diagnoses: list[dict[str, Any]] = []
    if "htmlcanvaselement.prototype.getcontext" in lowered or "not implemented: htmlcanvaselement" in lowered:
        diagnoses.append(
            diagnosis(
                "test_environment",
                "high",
                "Jest/jsdom canvas is not mocked.",
                "Add a Jest setup file that mocks HTMLCanvasElement.getContext, or configure a canvas implementation, then rerun tests.",
                details,
            )
        )
    if "eperm" in lowered or "permission denied" in lowered:
        diagnoses.append(
            diagnosis(
                "environment",
                "medium",
                "Tool cache or filesystem permission failure.",
                "Rerun with a repo-local cache directory and avoid global temp/cache writes.",
                details,
            )
        )
    if "cannot find module" in lowered or "module not found" in lowered:
        diagnoses.append(
            diagnosis(
                "dependency",
                "high",
                "Missing dependency blocks the proving gate.",
                "Install dependencies or repair package resolution before treating downstream test failures as product bugs.",
                details,
            )
        )
    if "failed to compile" in lowered or "syntaxerror" in lowered:
        diagnoses.append(
            diagnosis(
                "project_failure",
                "high",
                "Compile or syntax failure in project code.",
                "Fix the compile error first; it is a high-confidence product defect signal.",
                details,
            )
        )
    if "react-dom/test-utils" in lowered and "act" in lowered:
        diagnoses.append(
            diagnosis(
                "test_quality",
                "low",
                "React test warnings are noisy enough to hide real failures.",
                "Modernize act imports and flush async updates so the test gate produces cleaner signal.",
                details,
            )
        )
    if "vulnerabilities" in lowered and ("critical" in lowered or "high" in lowered):
        diagnoses.append(
            diagnosis(
                "security",
                "high",
                "Dependency audit reports high or critical vulnerabilities.",
                "Triage vulnerable package paths and prefer explicit upgrades over blind audit-fix churn.",
                details,
            )
        )
    return diagnoses


def diagnose_npm_audit(payload: dict[str, Any], path: str) -> list[dict[str, Any]]:
    metadata = payload.get("metadata", {}).get("vulnerabilities", {})
    high = int(metadata.get("high", 0) or 0)
    critical = int(metadata.get("critical", 0) or 0)
    if high == 0 and critical == 0:
        return []
    advisories = []
    for name, vuln in list(payload.get("vulnerabilities", {}).items())[:20]:
        severity = vuln.get("severity", "")
        if severity in {"high", "critical"}:
            advisories.append({"package": name, "severity": severity, "title": vuln.get("title", "")})
    return [
        diagnosis(
            "security",
            "critical" if critical else "high",
            f"npm audit reports {critical} critical and {high} high vulnerabilities.",
            "Prioritize direct dependency upgrades and inspect breaking-change risk before applying automated fixes.",
            {"path": path, "metadata": metadata, "top_advisories": advisories},
        )
    ]


def diagnosis(category: str, severity: str, title: str, action: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "recommended_action": action,
        "details": details,
    }


def dedupe_diagnoses(diagnoses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    seen_categories: set[str] = set()
    unique = []
    for item in diagnoses:
        if item["category"] == "repo_hygiene" and item["category"] in seen_categories:
            continue
        key = (item["category"], item["severity"], item["title"])
        if key in seen:
            continue
        seen.add(key)
        seen_categories.add(item["category"])
        unique.append(item)
    return unique


def build_recommendations(diagnoses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not diagnoses:
        return [
            {
                "priority": 1,
                "track": "rerun",
                "action": "No blocking medic signals found. Run the next bug-hunt loop against a truth target.",
            }
        ]
    priority_order = {"critical": 1, "high": 2, "medium": 3, "low": 4}
    sorted_items = sorted(diagnoses, key=lambda item: priority_order.get(item["severity"], 5))
    recommendations = []
    for index, item in enumerate(sorted_items[:8], start=1):
        recommendations.append(
            {
                "priority": index,
                "track": item["category"],
                "severity": item["severity"],
                "action": item["recommended_action"],
                "source": item["title"],
            }
        )
    return recommendations


def summarize_medic(diagnoses: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for item in diagnoses:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        by_severity[item["severity"]] = by_severity.get(item["severity"], 0) + 1
    status = "action_required" if diagnoses else "clear"
    return {
        "status": status,
        "diagnosis_count": len(diagnoses),
        "by_category": by_category,
        "by_severity": by_severity,
    }


def quality_reference(quality: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quality:
        return None
    return {
        "run_id": quality.get("run_id"),
        "json_path": quality.get("json_path"),
        "markdown_path": quality.get("markdown_path"),
        "summary": quality.get("summary"),
    }


def render_medic_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"# BugLab Medic Report: {payload['run_id']}",
        "",
        f"- Repo: `{payload['repo']}`",
        f"- Status: `{summary['status']}`",
        f"- Diagnoses: {summary['diagnosis_count']}",
        "",
        "## Agent",
        "",
        f"**{payload['agent']['name']}** - {payload['agent']['mandate']}",
        "",
        "## Recommendations",
        "",
    ]
    for item in payload["recommendations"]:
        lines.append(f"{item['priority']}. [{item['track']}] {item['action']}")
    if payload["diagnoses"]:
        lines.extend(["", "## Diagnoses", ""])
        for item in payload["diagnoses"]:
            lines.append(f"- `{item['severity']}` `{item['category']}` {item['title']}")
    lines.append("")
    return "\n".join(lines)


def read_text_flexible(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
