from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from buglab.api import build_index
from buglab.api import run_loops

PROJECT_SCHEMA_VERSION = "buglab.project.v1"
DEFAULT_CONFIG_PATH = ".buglab/config.json"


def init_project_config(
    *,
    repo: str | Path = ".",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    targets: list[str] | None = None,
    output: str = ".buglab/runs",
    loops: int = 3,
    profiles: list[str] | None = None,
    max_clicks: int = 30,
    force: bool = False,
) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    path = resolve_config_path(repo_path, config_path)
    if path.exists() and not force:
        return {"config_path": str(path), "created": False, "config": load_project_config(repo=repo_path, config_path=path)}

    selected_targets = targets or discover_targets(repo_path)
    config = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "output": output,
        "default_loops": loops,
        "default_profiles": profiles or ["balanced", "business", "edge"],
        "max_clicks": max_clicks,
        "targets": [
            {
                "id": target_id_from_path(target),
                "target": normalize_target_for_config(target),
                "kind": "browser",
                "mobile": False,
            }
            for target in selected_targets
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return {"config_path": str(path), "created": True, "config": config}


def run_project_matrix(
    *,
    repo: str | Path = ".",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output: str | Path | None = None,
    loops: int | None = None,
    profiles: list[str] | None = None,
    max_clicks: int | None = None,
    run_name: str = "buglab_matrix",
    target_ids: list[str] | None = None,
    build_report_index: bool = True,
) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    config = load_project_config(repo=repo_path, config_path=config_path)
    output_value = output or config.get("output", ".buglab/runs")
    output_root = (repo_path / output_value).resolve() if not Path(output_value).is_absolute() else Path(output_value).resolve()
    loop_count = int(loops if loops is not None else config.get("default_loops", 3))
    profile_list = profiles or list(config.get("default_profiles", ["balanced", "business", "edge"]))
    click_count = int(max_clicks if max_clicks is not None else config.get("max_clicks", 30))
    selected = select_targets(config, target_ids)

    matrix_rows: list[dict[str, Any]] = []
    target_results = []
    started = time.strftime("%Y%m%d_%H%M%S")
    for target in selected:
        target_id = str(target["id"])
        target_run_name = f"{run_name}_{safe_slug(target_id)}"
        result = run_loops(
            target=str(target["target"]),
            repo=repo_path,
            output=output_root,
            loops=loop_count,
            profiles=profile_list,
            max_clicks=click_count,
            mobile=bool(target.get("mobile", False)),
            run_name=target_run_name,
        )
        target_results.append(
            {
                "target_id": target_id,
                "target": target["target"],
                "summary": result["summary"],
                "csv_path": result["csv_path"],
                "json_path": result["json_path"],
            }
        )
        for row in result["rows"]:
            matrix_rows.append(
                {
                    "target_id": target_id,
                    "target": target["target"],
                    "loop": row["loop"],
                    "profile": row["profile"],
                    "run_id": row["run_id"],
                    "output_dir": row["output_dir"],
                    "controls_discovered": row["controls_discovered"],
                    "controls_exercised": row["controls_exercised"],
                    "bug_candidate_count": row["bug_candidate_count"],
                    "failure_signal_count": row["failure_signal_count"],
                    "failure_signals": row.get("failure_signals", "[]"),
                    "elapsed_ms": row["elapsed_ms"],
                    "agent_counts": row["agent_counts"],
                }
            )

    summary = summarize_matrix_rows(matrix_rows, selected)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / f"{run_name}_{started}_matrix_summary.csv"
    json_path = output_root / f"{run_name}_{started}_matrix_summary.json"
    write_rows(csv_path, matrix_rows)
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "buglab.matrix.v1",
                "config_path": str(resolve_config_path(repo_path, config_path)),
                "summary": summary,
                "targets": target_results,
                "rows": matrix_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    index_result = build_index(repo=repo_path, output=output_root) if build_report_index else None
    return {
        "summary": summary,
        "rows": matrix_rows,
        "targets": target_results,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "index": index_result,
    }


def scan_repo(
    *,
    repo: str | Path = ".",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
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
    repo_path = Path(repo).resolve()
    config_file = resolve_config_path(repo_path, config_path)
    should_initialize = force_init or targets is not None or not config_file.exists()
    if should_initialize:
        init_result = init_project_config(
            repo=repo_path,
            config_path=config_file,
            targets=targets,
            output=str(output or ".buglab/runs"),
            loops=loops,
            profiles=profiles,
            max_clicks=max_clicks,
            force=True,
        )
    else:
        init_result = {
            "config_path": str(config_file),
            "created": False,
            "config": load_project_config(repo=repo_path, config_path=config_file),
        }
    matrix = run_project_matrix(
        repo=repo_path,
        config_path=config_file,
        output=output,
        loops=loops,
        profiles=profiles,
        max_clicks=max_clicks,
        run_name=run_name,
        target_ids=target_ids,
        build_report_index=build_report_index,
    )
    return {
        "config_path": init_result["config_path"],
        "config_created": bool(init_result["created"]),
        "config": init_result["config"],
        "summary": matrix["summary"],
        "rows": matrix["rows"],
        "targets": matrix["targets"],
        "csv_path": matrix["csv_path"],
        "json_path": matrix["json_path"],
        "index": matrix["index"],
    }


def load_project_config(*, repo: str | Path = ".", config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    repo_path = Path(repo).resolve()
    path = resolve_config_path(repo_path, config_path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported BugLab project config schema: {config.get('schema_version')}")
    if not isinstance(config.get("targets"), list) or not config["targets"]:
        raise ValueError("BugLab project config must contain at least one target.")
    return config


def discover_targets(repo: Path) -> list[str]:
    candidates = [
        "index.html",
        "dist/index.html",
        "build/index.html",
        "public/index.html",
        "docs/index.html",
        "src/index.html",
    ]
    found = [candidate for candidate in candidates if (repo / candidate).exists()]
    discovered = [
        path.relative_to(repo).as_posix()
        for path in sorted(repo.rglob("*.html"), key=lambda item: item.as_posix())
        if path.is_file() and not should_skip_target(path.relative_to(repo).as_posix())
    ]
    for target in discovered:
        if target not in found:
            found.append(target)
    return found or ["index.html"]


def should_skip_target(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    if normalized.startswith("codexlab/runs/"):
        return True
    parts = set(normalized.split("/"))
    return bool(
        parts
        & {
            ".git",
            ".buglab",
            ".venv",
            "venv",
            "node_modules",
            "vendor",
            "__pycache__",
            "tmp",
            "dist",
            "build",
            "coverage",
            "coverage-hooks",
            "lcov-report",
            "playwright-report",
            "test-results",
            "storybook-static",
        }
    )


def select_targets(config: dict[str, Any], target_ids: list[str] | None) -> list[dict[str, Any]]:
    targets = list(config.get("targets", []))
    if not target_ids:
        return targets
    wanted = set(target_ids)
    selected = [target for target in targets if str(target.get("id")) in wanted]
    missing = sorted(wanted - {str(target.get("id")) for target in selected})
    if missing:
        raise ValueError(f"Unknown BugLab target id(s): {', '.join(missing)}")
    return selected


def resolve_config_path(repo: Path, config_path: str | Path) -> Path:
    path = Path(config_path)
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def normalize_target_for_config(target: str) -> str:
    return target.replace("\\", "/")


def target_id_from_path(target: str) -> str:
    if target.startswith("http://") or target.startswith("https://"):
        return safe_slug(target.split("//", 1)[1])
    path = Path(target)
    stem = path.stem or path.name or "target"
    parent = path.parent.name
    return safe_slug(f"{parent}_{stem}" if parent else stem)


def safe_slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value]
    slug = "_".join("".join(chars).split("_"))
    return slug.strip("_") or "target"


def summarize_matrix_rows(rows: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "targets": len(targets),
            "runs": 0,
            "total_bug_candidates": 0,
            "total_failure_signals": 0,
            "avg_elapsed_ms": 0,
            "best_profiles": [],
            "target_bug_totals": [],
        }
    bug_total_by_profile: dict[str, int] = {}
    bug_total_by_target: dict[str, int] = {}
    elapsed = []
    for row in rows:
        profile = str(row["profile"])
        target_id = str(row["target_id"])
        bug_count = int(row["bug_candidate_count"])
        bug_total_by_profile[profile] = bug_total_by_profile.get(profile, 0) + bug_count
        bug_total_by_target[target_id] = bug_total_by_target.get(target_id, 0) + bug_count
        elapsed.append(int(row["elapsed_ms"]))
    return {
        "targets": len(targets),
        "runs": len(rows),
        "total_bug_candidates": sum(int(row["bug_candidate_count"]) for row in rows),
        "total_failure_signals": sum(int(row["failure_signal_count"]) for row in rows),
        "avg_elapsed_ms": round(sum(elapsed) / len(elapsed), 2),
        "best_profiles": sorted(bug_total_by_profile.items(), key=lambda item: item[1], reverse=True),
        "target_bug_totals": sorted(bug_total_by_target.items(), key=lambda item: item[1], reverse=True),
    }


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
