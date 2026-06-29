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
BENCH_ROOT = Path(os.getenv("BUGLAB_BENCH_ROOT", str(ROOT / ".buglab" / "benchmarks")))
DEFAULT_BUGSINPY_ROOT = BENCH_ROOT / "BugsInPy"
DEFAULT_OUTPUT_ROOT = BENCH_ROOT / "buglab-runs" / "truth-evals-discovery"
DEFAULT_WORKSPACE_ROOT = BENCH_ROOT / "workspaces" / "truth-evals-discovery"
DEFAULT_SUBMISSION_OUTPUT = BENCH_ROOT / "buglab-runs" / "live_submission_package.md"
DEFAULT_SUBMISSION_JSON = BENCH_ROOT / "buglab-runs" / "live_submission_results.json"
DEFAULT_PY38 = Path(os.getenv("BUGLAB_BUGSINPY_PYTHON", sys.executable))


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe BugsInPy cases and promote only valid differential oracle cases.")
    parser.add_argument("--bugsinpy-root", default=str(os.environ.get("BUGLAB_BUGSINPY_ROOT", DEFAULT_BUGSINPY_ROOT)))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--workspace-root", default=str(DEFAULT_WORKSPACE_ROOT))
    parser.add_argument("--python38", default=str(os.environ.get("BUGLAB_BUGSINPY_PYTHON", DEFAULT_PY38)))
    parser.add_argument("--shim-dir", default=str(os.environ.get("BUGLAB_BUGSINPY_SHIM_DIR", BENCH_ROOT / "python-shims")))
    parser.add_argument("--project", action="append", dest="projects", help="Restrict discovery to one or more project names.")
    parser.add_argument(
        "--skip-project",
        action="append",
        default=["tqdm", "cookiecutter"],
        help="Skip project names. Defaults to tqdm because it is already covered and cookiecutter because its tox suite wedges on this Windows runner.",
    )
    parser.add_argument("--case", action="append", dest="cases", help="Explicit project:bug_id case to probe before discovered cases.")
    parser.add_argument("--max-cases", type=int, default=25)
    parser.add_argument("--max-valid", type=int, default=5)
    parser.add_argument("--duration-hours", type=float, default=0)
    parser.add_argument("--idle-heartbeat-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--submission-output", default=str(DEFAULT_SUBMISSION_OUTPUT))
    parser.add_argument("--submission-json", default=str(DEFAULT_SUBMISSION_JSON))
    args = parser.parse_args()

    bugsinpy_root = Path(args.bugsinpy_root).resolve()
    output_root = Path(args.output_root).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "truth_eval_log.jsonl"
    attempt_path = output_root / "discovery_attempts.jsonl"
    candidates = ordered_candidates(bugsinpy_root, args)
    seen_cases = load_seen_cases(ROOT / ".buglab" / "submission" / "submission_results.json", BENCH_ROOT / "buglab-runs", attempt_path)
    deadline = time.time() + args.duration_hours * 3600 if args.duration_hours > 0 else None
    probed = 0
    valid = 0

    for case in candidates:
        if probed >= args.max_cases or valid >= args.max_valid:
            break
        if deadline and time.time() >= deadline:
            break
        if case in seen_cases:
            continue
        probed += 1
        append_event(attempt_path, {"case": case, "started_at_utc": utc_now(), "status": "attempted"})
        event = probe_case(case, args, output_root, workspace_root)
        append_event(log_path, event)
        if event.get("valid_differential_pairs", 0) > 0:
            valid += 1
        refresh_submission(args, output_root)

    refresh_submission(args, output_root)
    idle_until_deadline(args, log_path, output_root, probed, valid, deadline)
    print(json.dumps({"log_path": str(log_path), "probed": probed, "valid": valid, "output_root": str(output_root)}, indent=2))
    return 0


def idle_until_deadline(
    args: argparse.Namespace,
    log_path: Path,
    output_root: Path,
    probed: int,
    valid: int,
    deadline: float | None,
) -> None:
    if deadline is None:
        return
    reason = "max_valid_reached" if valid >= args.max_valid else "max_cases_reached" if probed >= args.max_cases else "no_new_candidates"
    heartbeat_seconds = max(30, int(args.idle_heartbeat_seconds))
    while time.time() < deadline:
        append_event(
            log_path,
            {
                "kind": "discovery_idle",
                "mode": "discovery",
                "target": output_root.name,
                "started_at_utc": utc_now(),
                "status": "running",
                "result": {"summary": {"probed": probed, "valid": valid, "reason": reason}},
            },
        )
        refresh_submission(args, output_root)
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(heartbeat_seconds, remaining))


def ordered_candidates(bugsinpy_root: Path, args: argparse.Namespace) -> list[str]:
    explicit = list(args.cases or [])
    projects_root = bugsinpy_root / "projects"
    allowed = {item.lower() for item in args.projects or []}
    skipped = {item.lower() for item in args.skip_project or []}
    discovered: list[tuple[int, str, int]] = []
    for project_dir in projects_root.iterdir() if projects_root.exists() else []:
        if not project_dir.is_dir():
            continue
        project = project_dir.name
        lowered = project.lower()
        if allowed and lowered not in allowed:
            continue
        if lowered in skipped:
            continue
        bugs_dir = project_dir / "bugs"
        bug_ids = sorted((child.name for child in bugs_dir.iterdir() if child.is_dir() and child.name.isdigit()), key=lambda value: int(value))
        project_weight = len(bug_ids)
        for bug_id in bug_ids:
            discovered.append((project_weight, project, int(bug_id)))
    discovered.sort(key=lambda item: (item[0], item[1].lower(), item[2]))
    ordered = explicit + [f"{project}:{bug_id}" for _weight, project, bug_id in discovered]
    unique = []
    seen = set()
    for case in ordered:
        normalized = case.strip()
        if ":" not in normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def load_seen_cases(path: Path, artifact_root: Path, attempt_path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    oracle = payload.get("oracle_totals", {}) if isinstance(payload, dict) else {}
    cases = set()
    for key in ["selected_cases", "rejected_cases"]:
        for item in oracle.get(key, []) if isinstance(oracle, dict) else []:
            case = str(item.get("case", ""))
            if case:
                cases.add(case)
    if artifact_root.exists():
        for benchmark_path in artifact_root.rglob("bugsinpy_benchmark.json"):
            benchmark = read_json(benchmark_path)
            rows = benchmark.get("rows", []) if isinstance(benchmark, dict) else []
            for row in rows if isinstance(rows, list) else []:
                project = str(row.get("project", ""))
                bug_id = str(row.get("bug_id", ""))
                if project and bug_id:
                    cases.add(f"{project}:{bug_id}")
    if attempt_path.exists():
        for line in attempt_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                attempt = json.loads(line)
            except json.JSONDecodeError:
                continue
            case = str(attempt.get("case", ""))
            if case:
                cases.add(case)
    return cases


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def probe_case(case: str, args: argparse.Namespace, output_root: Path, workspace_root: Path) -> dict[str, Any]:
    from buglab.api import benchmark_bugsinpy

    project, bug_id = case.split(":", 1)
    event: dict[str, Any] = {
        "kind": "bugsinpy",
        "mode": "discovery",
        "target": case,
        "started_at_utc": utc_now(),
        "status": "started",
    }
    backup = {key: os.environ.get(key) for key in ["BUGLAB_BUGSINPY_PYTHON", "BUGLAB_BUGSINPY_SHIM_DIR"]}
    os.environ["BUGLAB_BUGSINPY_PYTHON"] = str(Path(args.python38).resolve())
    os.environ["BUGLAB_BUGSINPY_SHIM_DIR"] = str(Path(args.shim_dir).resolve())
    try:
        result = benchmark_bugsinpy(
            bugsinpy_root=args.bugsinpy_root,
            output=output_root / "bugsinpy",
            workspace=workspace_root / "bugsinpy",
            cases=[case],
            run_name=f"discover_{safe_slug(project)}_{safe_slug(bug_id)}",
            timeout_seconds=args.timeout_seconds,
        )
        summary = result.get("summary", {}) if isinstance(result.get("summary", {}), dict) else {}
        event.update(
            {
                "status": "completed",
                "result": result,
                "valid_differential_pairs": summary.get("valid_differential_pairs", 0),
                "invalid_oracle_rows": summary.get("invalid_oracle_rows", 0),
                "true_positive": summary.get("true_positive", 0),
                "false_positive": summary.get("false_positive", 0),
                "false_negative": summary.get("false_negative", 0),
                "true_negative": summary.get("true_negative", 0),
            }
        )
    except Exception as exc:
        event.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
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


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def safe_slug(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_") or "target"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
