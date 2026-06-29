from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = Path(os.getenv("BUGLAB_BENCH_ROOT", str(ROOT / ".buglab" / "benchmarks")))
PYTHON = sys.executable
DEFAULT_SUBMISSION_OUTPUT = BENCH_ROOT / "buglab-runs" / "live_submission_package.md"
DEFAULT_SUBMISSION_JSON = BENCH_ROOT / "buglab-runs" / "live_submission_results.json"


@dataclass(frozen=True)
class EvalLane:
    name: str
    output_root: Path
    workspace_root: Path
    command: list[str]
    match_tokens: tuple[str, ...]

    @property
    def log_path(self) -> Path:
        return self.output_root / "truth_eval_log.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep BugLab truth eval lanes alive and fresh.")
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--stale-minutes", type=int, default=15)
    parser.add_argument("--duration-hours", type=float, default=8)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log", default=str(BENCH_ROOT / "buglab-runs" / "truth_eval_watchdog.jsonl"))
    parser.add_argument("--no-refresh-submission", action="store_true")
    parser.add_argument("--submission-output", default=str(DEFAULT_SUBMISSION_OUTPUT))
    parser.add_argument("--submission-json", default=str(DEFAULT_SUBMISSION_JSON))
    parser.add_argument("--status-json", default=str(BENCH_ROOT / "buglab-runs" / "truth_eval_watchdog_status.json"))
    args = parser.parse_args()

    deadline = time.time() + args.duration_hours * 3600 if args.duration_hours > 0 and not args.once else None
    lanes = default_lanes()
    while True:
        runners = list_runners()
        lane_results = []
        for lane in lanes:
            lane_results.append(
                ensure_lane(
                    lane,
                    runners,
                    stale_minutes=args.stale_minutes,
                    dry_run=args.dry_run,
                    watchdog_log=Path(args.log),
                )
            )
        package_status: dict[str, Any] = {"refresh_enabled": False}
        if not args.no_refresh_submission:
            package_status = refresh_submission_package(args)
            record(Path(args.log), {"event": "submission_refresh", **package_status})
        write_status(Path(args.status_json), lane_results, package_status, runners)
        if args.once or (deadline and time.time() >= deadline):
            break
        time.sleep(max(10, args.interval_seconds))
    return 0


def default_lanes() -> list[EvalLane]:
    main_output = BENCH_ROOT / "buglab-runs" / "truth-evals"
    main_workspace = BENCH_ROOT / "workspaces" / "truth-evals"
    calibration_output = BENCH_ROOT / "buglab-runs" / "truth-evals-calibration"
    calibration_workspace = BENCH_ROOT / "workspaces" / "truth-evals-calibration"
    crossproject_output = BENCH_ROOT / "buglab-runs" / "truth-evals-crossproject"
    crossproject_workspace = BENCH_ROOT / "workspaces" / "truth-evals-crossproject"
    discovery_output = BENCH_ROOT / "buglab-runs" / "truth-evals-discovery"
    discovery_workspace = BENCH_ROOT / "workspaces" / "truth-evals-discovery"
    discovery_web_output = BENCH_ROOT / "buglab-runs" / "truth-evals-discovery-web"
    discovery_web_workspace = BENCH_ROOT / "workspaces" / "truth-evals-discovery-web"
    discovery_tools_output = BENCH_ROOT / "buglab-runs" / "truth-evals-discovery-tools"
    discovery_tools_workspace = BENCH_ROOT / "workspaces" / "truth-evals-discovery-tools"
    return [
        EvalLane(
            name="main",
            output_root=main_output,
            workspace_root=main_workspace,
            command=[
                PYTHON,
                "scripts/truth_eval_runner.py",
                "--case",
                "tqdm:4",
                "--case",
                "tqdm:5",
                "--case",
                "tqdm:6",
                "--case",
                "tqdm:7",
                "--duration-hours",
                "8",
                "--max-cycles",
                "999",
                "--timeout-seconds",
                "300",
                "--max-clicks",
                "4",
            ],
            match_tokens=("truth_eval_runner.py", "tqdm:4"),
        ),
        EvalLane(
            name="calibration",
            output_root=calibration_output,
            workspace_root=calibration_workspace,
            command=[
                PYTHON,
                "scripts/truth_eval_runner.py",
                "--case",
                "tqdm:1",
                "--case",
                "tqdm:2",
                "--case",
                "tqdm:3",
                "--output-root",
                str(calibration_output),
                "--workspace-root",
                str(calibration_workspace),
                "--duration-hours",
                "8",
                "--max-cycles",
                "999",
                "--timeout-seconds",
                "300",
                "--max-clicks",
                "4",
            ],
            match_tokens=("truth_eval_runner.py", str(calibration_output)),
        ),
        EvalLane(
            name="crossproject",
            output_root=crossproject_output,
            workspace_root=crossproject_workspace,
            command=[
                PYTHON,
                "scripts/truth_eval_runner.py",
                "--case",
                "httpie:5",
                "--case",
                "tqdm:1",
                "--case",
                "tqdm:4",
                "--output-root",
                str(crossproject_output),
                "--workspace-root",
                str(crossproject_workspace),
                "--duration-hours",
                "8",
                "--max-cycles",
                "999",
                "--timeout-seconds",
                "300",
                "--max-clicks",
                "4",
            ],
            match_tokens=("truth_eval_runner.py", str(crossproject_output)),
        ),
        EvalLane(
            name="discovery",
            output_root=discovery_output,
            workspace_root=discovery_workspace,
            command=[
                PYTHON,
                "scripts/discover_bugsinpy_cases.py",
                "--max-cases",
                "35",
                "--max-valid",
                "5",
                "--duration-hours",
                "8",
                "--timeout-seconds",
                "180",
                "--output-root",
                str(discovery_output),
                "--workspace-root",
                str(discovery_workspace),
            ],
            match_tokens=("discover_bugsinpy_cases.py", str(discovery_output)),
        ),
        EvalLane(
            name="discovery-web",
            output_root=discovery_web_output,
            workspace_root=discovery_web_workspace,
            command=[
                PYTHON,
                "scripts/discover_bugsinpy_cases.py",
                "--project",
                "fastapi",
                "--project",
                "tornado",
                "--project",
                "sanic",
                "--max-cases",
                "18",
                "--max-valid",
                "3",
                "--duration-hours",
                "8",
                "--timeout-seconds",
                "180",
                "--output-root",
                str(discovery_web_output),
                "--workspace-root",
                str(discovery_web_workspace),
            ],
            match_tokens=("discover_bugsinpy_cases.py", str(discovery_web_output)),
        ),
        EvalLane(
            name="discovery-tools",
            output_root=discovery_tools_output,
            workspace_root=discovery_tools_workspace,
            command=[
                PYTHON,
                "scripts/discover_bugsinpy_cases.py",
                "--project",
                "black",
                "--project",
                "thefuck",
                "--project",
                "youtube-dl",
                "--project",
                "luigi",
                "--project",
                "scrapy",
                "--max-cases",
                "22",
                "--max-valid",
                "3",
                "--duration-hours",
                "8",
                "--timeout-seconds",
                "180",
                "--output-root",
                str(discovery_tools_output),
                "--workspace-root",
                str(discovery_tools_workspace),
            ],
            match_tokens=("discover_bugsinpy_cases.py", str(discovery_tools_output)),
        ),
    ]


def ensure_lane(
    lane: EvalLane,
    runners: list[dict[str, Any]],
    *,
    stale_minutes: int,
    dry_run: bool,
    watchdog_log: Path,
) -> dict[str, Any]:
    matching = [runner for runner in runners if runner_matches_lane(runner, lane)]
    age_minutes = file_age_minutes(lane.log_path)
    runner_age_minutes = youngest_runner_age_minutes(matching)
    warming_up = bool(matching) and age_minutes is None and runner_age_minutes is not None and runner_age_minutes <= stale_minutes
    stale = age_minutes is None or age_minutes > stale_minutes
    if matching and (not stale or warming_up):
        payload = {
            "event": "lane_ok",
            "lane": lane.name,
            "log_age_minutes": age_minutes,
            "runner_age_minutes": runner_age_minutes,
            "runner_pids": [item["pid"] for item in matching],
        }
        record(watchdog_log, payload)
        return payload

    reason = "missing_runner" if not matching else "stale_log"
    killed = 0
    if matching and not dry_run:
        for runner in matching:
            killed += kill_process_tree(int(runner["pid"]))
        killed += kill_workspace_processes(lane.workspace_root)
    payload = {
        "event": "lane_restart",
        "lane": lane.name,
        "reason": reason,
        "log_age_minutes": age_minutes,
        "runner_age_minutes": runner_age_minutes,
        "runner_pids": [item["pid"] for item in matching],
        "killed_processes": killed,
        "command": lane.command,
        "dry_run": dry_run,
    }
    record(watchdog_log, payload)
    spawned_pid = None
    if not dry_run:
        spawned_pid = start_lane(lane)
        payload["spawned_pid"] = spawned_pid
        record(
            watchdog_log,
            {
                "event": "lane_started",
                "lane": lane.name,
                "pid": spawned_pid,
                "command": lane.command,
            },
        )
    return payload


def refresh_submission_package(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    command = [
        PYTHON,
        str(ROOT / "scripts" / "build_submission_package.py"),
        "--repo",
        str(ROOT),
        "--external-root",
        str(BENCH_ROOT / "buglab-runs"),
        "--output",
        str(Path(args.submission_output).resolve()),
        "--json-output",
        str(Path(args.submission_json).resolve()),
    ]
    try:
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90, check=False)
        returncode = proc.returncode
        stderr = (proc.stderr or "").strip()[-1000:]
    except subprocess.TimeoutExpired as exc:
        return {
            "refresh_enabled": True,
            "returncode": -1,
            "elapsed_seconds": round(time.time() - started, 2),
            "error": f"timeout after {exc.timeout}s",
            "package_json": str(Path(args.submission_json).resolve()),
        }
    package_path = Path(args.submission_json).resolve()
    package = read_json(package_path)
    validation = package.get("validation", {}) if isinstance(package.get("validation", {}), dict) else {}
    oracle = package.get("oracle_totals", {}) if isinstance(package.get("oracle_totals", {}), dict) else {}
    replay = package.get("real_repo_replay", {}) if isinstance(package.get("real_repo_replay", {}), dict) else {}
    replay_unique = (
        package.get("real_repo_replay_unique", {})
        if isinstance(package.get("real_repo_replay_unique", {}), dict)
        else {}
    )
    evidence = package.get("evidence_completeness", {}) if isinstance(package.get("evidence_completeness", {}), dict) else {}
    return {
        "refresh_enabled": True,
        "returncode": returncode,
        "elapsed_seconds": round(time.time() - started, 2),
        "package_json": str(package_path),
        "package_updated_at_utc": str(package.get("updated_at_utc", "")),
        "validation_ok": validation.get("ok"),
        "validation_failures": len(validation.get("failures", [])) if isinstance(validation.get("failures", []), list) else 0,
        "oracle_cases": oracle.get("unique_cases", 0),
        "stable_oracle_cases": oracle.get("stable_unique_cases", 0),
        "evidence_complete_entries": evidence.get("complete_entries", 0),
        "evidence_incomplete_entries": evidence.get("incomplete_entries", 0),
        "replay_checked": replay.get("checked", 0),
        "replay_reproduced": replay.get("reproduced", 0),
        "unique_replay_claims": replay_unique.get("unique_claims", 0),
        "unique_replay_reproduced": replay_unique.get("unique_reproduced", 0),
        "unique_replay_not_reproduced": replay_unique.get("unique_not_reproduced", 0),
        "stderr_tail": stderr,
    }


def write_status(
    path: Path,
    lane_results: list[dict[str, Any]],
    package_status: dict[str, Any],
    runners: list[dict[str, Any]],
) -> None:
    payload = {
        "updated_at_utc": utc_now(),
        "runner_count": len(runners),
        "lanes": lane_results,
        "package": package_status,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def start_lane(lane: EvalLane) -> int:
    lane.output_root.mkdir(parents=True, exist_ok=True)
    lane.workspace_root.mkdir(parents=True, exist_ok=True)
    log_file = lane.output_root / "runner-watchdog.log"
    handle = log_file.open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        lane.command,
        cwd=ROOT,
        stdout=handle,
        stderr=handle,
        text=True,
        creationflags=creationflags,
    )
    handle.close()
    return int(proc.pid)


def list_runners() -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return []
    runners: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            argv = proc.info.get("cmdline") or []
            cmdline = " ".join(str(part) for part in argv)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
        if not is_truth_runner_argv(argv):
            continue
        runners.append(
            {
                "pid": proc.info["pid"],
                "argv": [str(part) for part in argv],
                "cmdline": cmdline,
                "create_time": proc.info.get("create_time"),
            }
        )
    return runners


def is_truth_runner_argv(cmdline: list[Any]) -> bool:
    runner_names = {"truth_eval_runner.py", "discover_bugsinpy_cases.py"}
    return any(Path(str(part).replace("\\", "/")).name in runner_names for part in cmdline)


def runner_matches_lane(runner: dict[str, Any], lane: EvalLane) -> bool:
    argv = [str(part) for part in runner.get("argv", []) if str(part)]
    output_root = option_value(argv, "--output-root")
    if output_root:
        return same_resolved_path(Path(output_root), lane.output_root)
    normalized = normalize_path_text(str(runner.get("cmdline", "")))
    return all(normalize_path_text(token) in normalized for token in lane.match_tokens)


def option_value(argv: list[str], flag: str) -> str | None:
    for index, value in enumerate(argv):
        if value == flag and index + 1 < len(argv):
            return argv[index + 1]
    return None


def same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return normalize_path_text(str(left)) == normalize_path_text(str(right))


def file_age_minutes(path: Path) -> float | None:
    try:
        modified = path.stat().st_mtime
    except OSError:
        return None
    return round((time.time() - modified) / 60, 2)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def youngest_runner_age_minutes(runners: list[dict[str, Any]]) -> float | None:
    ages = []
    now = time.time()
    for runner in runners:
        try:
            created = float(runner.get("create_time") or 0)
        except (TypeError, ValueError):
            continue
        if created > 0:
            ages.append((now - created) / 60)
    if not ages:
        return None
    return round(min(ages), 2)


def kill_process_tree(pid: int) -> int:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return 0
    killed = 0
    try:
        parent = psutil.Process(pid)
        processes = [*parent.children(recursive=True), parent]
        for process in processes:
            try:
                process.kill()
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                continue
        psutil.wait_procs(processes, timeout=5)
    except psutil.NoSuchProcess:
        return killed
    except psutil.Error:
        return killed
    return killed


def kill_workspace_processes(workspace_root: Path) -> int:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return 0
    marker = normalize_path_text(str(workspace_root))
    if len(marker) < 20:
        return 0
    killed = 0
    current_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            cmdline = normalize_path_text(" ".join(str(part) for part in proc.info.get("cmdline") or []))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
        if pid == current_pid or marker not in cmdline:
            continue
        try:
            proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
    return killed


def normalize_path_text(value: str) -> str:
    return value.replace("\\", "/").lower()


def record(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at_utc": utc_now(), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    raise SystemExit(main())
