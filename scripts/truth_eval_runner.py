from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH_ROOT = Path(os.getenv("BUGLAB_BENCH_ROOT", str(ROOT / ".buglab" / "benchmarks")))
DEFAULT_BUGSINPY_ROOT = DEFAULT_BENCH_ROOT / "BugsInPy"
DEFAULT_OUTPUT_ROOT = DEFAULT_BENCH_ROOT / "buglab-runs" / "truth-evals"
DEFAULT_WORKSPACE_ROOT = DEFAULT_BENCH_ROOT / "workspaces" / "truth-evals"
DEFAULT_SUBMISSION_OUTPUT = DEFAULT_BENCH_ROOT / "buglab-runs" / "live_submission_package.md"
DEFAULT_SUBMISSION_JSON = DEFAULT_BENCH_ROOT / "buglab-runs" / "live_submission_results.json"
DEFAULT_PY38 = Path(os.getenv("BUGLAB_BUGSINPY_PYTHON", sys.executable))
DEFAULT_REAL_REPOS = [item.strip() for item in os.getenv("BUGLAB_DEFAULT_REPOS", "").split(",") if item.strip()]
DEFAULT_CASES = ["tqdm:1", "tqdm:2", "tqdm:3", "tqdm:4", "tqdm:5", "tqdm:6"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run truth-first BugLab evals and refresh the submission package after each valid artifact.")
    parser.add_argument("--bugsinpy-root", default=str(os.environ.get("BUGLAB_BUGSINPY_ROOT", DEFAULT_BUGSINPY_ROOT)))
    parser.add_argument("--case", action="append", dest="cases", help="BugsInPy project:bug_id. Defaults to a tqdm smoke/expansion slice.")
    parser.add_argument("--skip-bugsinpy", action="store_true")
    parser.add_argument("--include-default-repos", action="store_true", help="Audit repo names listed in BUGLAB_DEFAULT_REPOS.")
    parser.add_argument("--repo-name", action="append", dest="repo_names", help="Real repo folder name to locate and audit.")
    parser.add_argument("--repo-path", action="append", dest="repo_paths", help="Explicit real repo path to audit.")
    parser.add_argument("--repo-search-root", action="append", default=[str(Path.home() / "Documents"), str(Path.home() / "Desktop")])
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    parser.add_argument("--python38", default=str(os.environ.get("BUGLAB_BUGSINPY_PYTHON", DEFAULT_PY38)))
    parser.add_argument("--shim-dir", default=str(os.environ.get("BUGLAB_BUGSINPY_SHIM_DIR", DEFAULT_BENCH_ROOT / "python-shims")))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-clicks", type=int, default=6)
    parser.add_argument("--duration-hours", type=float, default=0, help="Keep rotating evals until this wall-clock duration has elapsed. 0 means one pass.")
    parser.add_argument("--max-cycles", type=int, default=1, help="Safety cap for rotations. Use a high value with --duration-hours for overnight runs.")
    parser.add_argument("--submission-output", default=str(DEFAULT_SUBMISSION_OUTPUT))
    parser.add_argument("--submission-json", default=str(DEFAULT_SUBMISSION_JSON))
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "truth_eval_log.jsonl"
    deadline = time.time() + args.duration_hours * 3600 if args.duration_hours > 0 else None

    cases = args.cases or DEFAULT_CASES
    repo_paths = resolve_repo_targets(args)
    cycle = 0
    while True:
        cycle += 1
        if not args.skip_bugsinpy:
            for case in cases:
                if deadline and time.time() >= deadline:
                    break
                event = run_bugsinpy_case(case, args, output_root, workspace_root)
                append_event(log_path, event)
                refresh_submission(args, output_root)
        for repo_path in repo_paths:
            if deadline and time.time() >= deadline:
                break
            event = run_real_repo_audit(repo_path, args, output_root)
            append_event(log_path, event)
            refresh_submission(args, output_root)
        if deadline and time.time() < deadline and cycle < args.max_cycles:
            continue
        break

    refresh_submission(args, output_root)
    print(json.dumps({"log_path": str(log_path), "output_root": str(output_root), "cycles": cycle}, indent=2))
    return 0


def run_bugsinpy_case(case: str, args: argparse.Namespace, output_root: Path, workspace_root: Path) -> dict[str, Any]:
    from buglab.api import benchmark_bugsinpy

    project, bug_id = case.split(":", 1)
    event = base_event("bugsinpy", case)
    env_backup = {key: os.environ.get(key) for key in ["BUGLAB_BUGSINPY_PYTHON", "BUGLAB_BUGSINPY_SHIM_DIR"]}
    os.environ["BUGLAB_BUGSINPY_PYTHON"] = str(Path(args.python38).resolve())
    os.environ["BUGLAB_BUGSINPY_SHIM_DIR"] = str(Path(args.shim_dir).resolve())
    try:
        result = benchmark_bugsinpy(
            bugsinpy_root=args.bugsinpy_root,
            output=output_root / "bugsinpy",
            workspace=workspace_root / "bugsinpy",
            cases=[case],
            run_name=f"truth_{safe_slug(project)}_{safe_slug(bug_id)}",
            timeout_seconds=args.timeout_seconds,
        )
        event.update({"status": "completed", "result": result})
    except Exception as exc:
        event.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return event


def run_real_repo_audit(repo: Path, args: argparse.Namespace, output_root: Path) -> dict[str, Any]:
    from buglab.api import audit_repo

    event = base_event("real_repo_audit", str(repo))
    try:
        result = audit_repo(
            repo=repo,
            output=output_root / "real_repos" / safe_slug(repo.name),
            loops=1,
            profiles=["balanced"],
            max_clicks=args.max_clicks,
            run_name=f"real_{safe_slug(repo.name)}",
            include_browser=True,
            include_docs=True,
            include_tests=True,
            include_config=True,
            build_report_index=True,
        )
        event.update({"status": "completed", "result": result})
    except Exception as exc:
        event.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return event


def refresh_submission(args: argparse.Namespace, output_root: Path) -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_submission_package.py"),
        "--repo",
        str(ROOT),
        "--external-root",
        str(output_root),
        "--output",
        args.submission_output,
        "--json-output",
        args.submission_json,
    ]
    subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True, timeout=60)


def resolve_repo_targets(args: argparse.Namespace) -> list[Path]:
    paths = [Path(item).resolve() for item in args.repo_paths or []]
    names = list(args.repo_names or [])
    if args.include_default_repos:
        names.extend(DEFAULT_REAL_REPOS)
    for name in names:
        found = find_repo_by_name(name, [Path(item).resolve() for item in args.repo_search_root])
        if found:
            paths.append(found)
    unique = []
    seen = set()
    for path in paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        unique.append(path)
    return unique


def find_repo_by_name(name: str, roots: list[Path]) -> Path | None:
    lowered = name.lower()
    ignored = {".git", ".venv", "env", "node_modules", "dist", "build", "__pycache__"}
    for root in roots:
        if not root.exists():
            continue
        direct = root / name
        if direct.exists():
            return direct.resolve()
        for current, dirs, _files in os.walk(root):
            dirs[:] = [item for item in dirs if item not in ignored]
            current_path = Path(current)
            if current_path.name.lower() == lowered and (current_path / ".git").exists():
                return current_path.resolve()
    return None


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def base_event(kind: str, target: str) -> dict[str, Any]:
    return {"kind": kind, "target": target, "started_at_utc": utc_now(), "status": "started"}


def safe_slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_") or "target"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
