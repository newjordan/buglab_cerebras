from __future__ import annotations

import csv
import html
import json
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buglab.audit import RepoAuditConfig
from buglab.audit import audit_repo
from buglab.truth import confidence_for_status
from buglab.truth import outcome_to_truth_status
from buglab.truth import summarize_truth_entries
from buglab.truth import write_truth_ledger


@dataclass(frozen=True)
class BugsInPyBenchmarkConfig:
    bugsinpy_root: str | Path
    output: str | Path = ".buglab/benchmarks/bugsinpy"
    workspace: str | Path = ".buglab/benchmarks/bugsinpy/workspaces"
    cases: list[str] | None = None
    case_file: str | Path | None = None
    run_name: str = "bugsinpy"
    timeout_seconds: int = 180
    dry_run: bool = False
    keep_workspaces: bool = True


def run_bugsinpy_benchmark(config: BugsInPyBenchmarkConfig | None = None, **kwargs: Any) -> dict[str, Any]:
    config = config or BugsInPyBenchmarkConfig(**kwargs)
    root = Path(config.bugsinpy_root).resolve()
    output_root = Path(config.output).resolve()
    workspace_root = Path(config.workspace).resolve()
    run_id = f"{config.run_name}_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    cases = load_bugsinpy_cases(config.cases, config.case_file)
    tools = resolve_bugsinpy_tools(root)
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.extend(run_bugsinpy_case(case, tools, workspace_root, out_dir, config))

    summary = summarize_bugsinpy_rows(rows)
    csv_path = out_dir / "bugsinpy_benchmark.csv"
    json_path = out_dir / "bugsinpy_benchmark.json"
    html_path = out_dir / "bugsinpy_benchmark.html"
    truth_path = out_dir / "truth_ledger.json"
    truth_entries = build_bugsinpy_truth_entries(run_id, rows)
    truth_summary = summarize_truth_entries(truth_entries)
    truth_summary.update(
        {
            "valid_differential_pairs": summary.get("valid_differential_pairs", 0),
            "runnable_rows": summary.get("runnable_rows", 0),
            "invalid_oracle_rows": summary.get("invalid_oracle_rows", 0),
        }
    )
    truth_ledger = write_truth_ledger(truth_path, truth_entries, run_id=run_id, summary=truth_summary)
    write_benchmark_csv(csv_path, rows)
    payload = {
        "schema_version": "buglab.bugsinpy_benchmark.v1",
        "run_id": run_id,
        "bugsinpy_root": str(root),
        "summary": summary,
        "truth_ledger": truth_ledger,
        "truth_ledger_path": str(truth_path),
        "truth_ledger_jsonl_path": str(truth_path.with_suffix(".jsonl")),
        "rows": rows,
        "dry_run": config.dry_run,
        "scoring_note": (
            "Primary metrics score known buggy checkouts as positives and fixed checkouts as negatives. "
            "BugLab detection for this benchmark is driven by the official BugsInPy triggering test; broad repo test discovery is disabled to avoid ancillary-suite contamination. "
            "Rows with broken benchmark infrastructure are marked invalid_oracle and excluded from precision, recall, and F1. "
            "Runtime/tokens are secondary cost telemetry."
        ),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    html_path.write_text(render_bugsinpy_html(payload), encoding="utf-8")
    return {
        "run_id": run_id,
        "summary": summary,
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "truth_ledger_path": str(truth_path),
        "truth_ledger_jsonl_path": str(truth_path.with_suffix(".jsonl")),
    }


def load_bugsinpy_cases(cases: list[str] | None, case_file: str | Path | None) -> list[dict[str, str]]:
    loaded: list[dict[str, str]] = []
    for item in cases or []:
        if ":" not in item:
            raise ValueError(f"BugsInPy case must use project:bug_id format, got {item!r}")
        project, bug_id = item.split(":", 1)
        loaded.append({"project": project.strip(), "bug_id": bug_id.strip()})
    if case_file:
        path = Path(case_file)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload.get("cases", payload) if isinstance(payload, dict) else payload
            for item in items:
                loaded.append({"project": str(item["project"]), "bug_id": str(item["bug_id"])})
        else:
            with path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    loaded.append({"project": str(row["project"]), "bug_id": str(row["bug_id"])})
    if not loaded:
        raise ValueError("Pass at least one --case project:bug_id or --case-file.")
    return loaded


def resolve_bugsinpy_tools(root: Path) -> dict[str, str]:
    candidates = {
        "checkout": ["bugsinpy-checkout", "bugsinpy-checkout.bat", "bugsinpy-checkout.cmd"],
        "compile": ["bugsinpy-compile", "bugsinpy-compile.bat", "bugsinpy-compile.cmd"],
        "test": ["bugsinpy-test", "bugsinpy-test.bat", "bugsinpy-test.cmd"],
    }
    tools: dict[str, str] = {}
    for name, executable_names in candidates.items():
        found = None
        for executable in executable_names:
            path = shutil.which(executable)
            if path:
                found = path
                break
            local = root / "framework" / "bin" / executable
            if local.exists():
                found = str(local)
                break
        tools[name] = found or executable_names[0]
    return tools


def run_bugsinpy_case(
    case: dict[str, str],
    tools: dict[str, str],
    workspace_root: Path,
    out_dir: Path,
    config: BugsInPyBenchmarkConfig,
) -> list[dict[str, Any]]:
    rows = []
    for version, label in [(0, "buggy"), (1, "fixed")]:
        case_id = f"{case['project']}-{case['bug_id']}-{label}"
        checkout_workspace = workspace_root / case_id
        planned_project_workspace = checkout_workspace / case["project"]
        started = time.perf_counter()
        if config.dry_run:
            rows.append(
                benchmark_row(
                    case=case,
                    version_label=label,
                    workspace=planned_project_workspace,
                    checkout_workspace=checkout_workspace,
                    status="planned",
                    test_failed_raw=None,
                    test_infrastructure_error=None,
                    benchmark_test_failed=None,
                    audit_detected=None,
                    buglab_detected=None,
                    elapsed_ms=0,
                    commands=planned_commands(tools, case, version, checkout_workspace, planned_project_workspace),
                )
            )
            continue

        checkout = run_command(
            [tools["checkout"], "-p", case["project"], "-i", case["bug_id"], "-v", str(version), "-w", str(checkout_workspace)],
            cwd=Path(config.bugsinpy_root),
            timeout_seconds=config.timeout_seconds,
        )
        project_workspace = resolve_checked_out_project(checkout_workspace, case["project"])
        if checkout["returncode"] != 0 or not is_bugsinpy_project(project_workspace):
            compile_result = skipped_command([tools["compile"], "-w", str(project_workspace)], "checkout_failed")
            test_result = skipped_command([tools["test"], "-w", str(project_workspace)], "checkout_failed")
            audit_result = skipped_audit_result(project_workspace, out_dir, case_id, "checkout_failed")
            rows.append(
                benchmark_row(
                    case=case,
                    version_label=label,
                    workspace=project_workspace,
                    checkout_workspace=checkout_workspace,
                    status="checkout_failed",
                    test_failed_raw=True,
                    test_infrastructure_error=True,
                    benchmark_test_failed=None,
                    audit_detected=False,
                    buglab_detected=False,
                    elapsed_ms=round((time.perf_counter() - started) * 1000),
                    commands={
                        "checkout": checkout,
                        "compile": compile_result,
                        "test": test_result,
                        "buglab_audit": audit_result,
                    },
                )
            )
            continue
        compile_result = run_command(
            [tools["compile"], "-w", str(project_workspace)],
            cwd=project_workspace,
            timeout_seconds=config.timeout_seconds,
        )
        ensure_windows_venv_python3(project_workspace)
        test_result = run_command(
            [tools["test"], "-w", str(project_workspace)],
            cwd=project_workspace,
            timeout_seconds=config.timeout_seconds,
        )
        failure_tail = read_optional_tail(project_workspace / "bugsinpy_fail.txt")
        if failure_tail:
            test_result["failure_tail"] = failure_tail
        audit_result = run_case_audit(project_workspace, out_dir, case_id)
        test_failed_raw = infer_bugsinpy_test_failed(test_result, failure_tail)
        test_infrastructure_error = is_oracle_infrastructure_error(project_workspace, compile_result, test_result, failure_tail)
        benchmark_test_failed = None if test_infrastructure_error else test_failed_raw
        audit_detected = audit_result["summary"].get("failed_targets", 0) > 0
        buglab_detected = audit_detected if benchmark_test_failed is None else benchmark_test_failed or audit_detected
        rows.append(
            benchmark_row(
                case=case,
                version_label=label,
                workspace=project_workspace,
                checkout_workspace=checkout_workspace,
                status="ran",
                test_failed_raw=test_failed_raw,
                test_infrastructure_error=test_infrastructure_error,
                benchmark_test_failed=benchmark_test_failed,
                audit_detected=audit_detected,
                buglab_detected=buglab_detected,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                commands={
                    "checkout": checkout,
                    "compile": compile_result,
                    "test": test_result,
                    "buglab_audit": audit_result,
                },
            )
        )
    apply_pair_oracle_validity(rows)
    return rows


def run_case_audit(workspace: Path, out_dir: Path, case_id: str) -> dict[str, Any]:
    return audit_repo(
        RepoAuditConfig(
            repo=workspace,
            output=out_dir / "audits",
            run_name=f"{case_id}_audit",
            targets=[],
            loops=1,
            profiles=["balanced"],
            max_clicks=1,
            include_browser=False,
            include_docs=False,
            include_tests=False,
            include_config=False,
            build_report_index=False,
        )
    )


def planned_commands(
    tools: dict[str, str],
    case: dict[str, str],
    version: int,
    checkout_workspace: Path,
    project_workspace: Path,
) -> dict[str, Any]:
    return {
        "checkout": {
            "command": [tools["checkout"], "-p", case["project"], "-i", case["bug_id"], "-v", str(version), "-w", str(checkout_workspace)]
        },
        "compile": {"command": [tools["compile"], "-w", str(project_workspace)]},
        "test": {"command": [tools["test"], "-w", str(project_workspace)]},
        "buglab_audit": {"command": ["buglab", "audit", "--repo", str(project_workspace), "--no-browser", "--no-docs", "--no-config"]},
    }


def resolve_checked_out_project(checkout_workspace: Path, project: str) -> Path:
    preferred = checkout_workspace / project
    for candidate in [preferred, checkout_workspace]:
        if is_bugsinpy_project(candidate):
            return candidate
    if checkout_workspace.exists():
        for child in checkout_workspace.iterdir():
            if child.is_dir() and is_bugsinpy_project(child):
                return child
    return preferred


def is_bugsinpy_project(path: Path) -> bool:
    return (path / "bugsinpy_bug.info").exists()


def read_optional_tail(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return tail(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def infer_bugsinpy_test_failed(test_result: dict[str, Any], failure_tail: str) -> bool:
    if failure_tail.strip() or test_result["returncode"] != 0:
        return True
    output = "\n".join([str(test_result.get("stdout_tail", "")), str(test_result.get("stderr_tail", ""))]).lower()
    failure_markers = [
        " failed,",
        " failed in ",
        " failed\n",
        "\nfailed ",
        " error in ",
        "\nerror ",
        "short test summary info",
    ]
    return any(marker in output for marker in failure_markers)


def is_oracle_infrastructure_error(project_workspace: Path, compile_result: dict[str, Any], test_result: dict[str, Any], failure_tail: str) -> bool:
    test_combined = "\n".join(
        [
            str(test_result.get("stdout_tail", "")),
            str(test_result.get("stderr_tail", "")),
            failure_tail,
        ]
    )
    infrastructure_markers = [
        "This is not a checkout project folder",
        "You have not compile this project",
        "pytest: command not found",
        "py.test: command not found",
        "ImportError: cannot import name 'TerminalWriter' from 'py.io'",
    ]
    if compile_result["returncode"] != 0:
        return True
    if not (project_workspace / "bugsinpy_compile_flag").exists():
        return True
    return any(marker in test_combined for marker in infrastructure_markers)


def run_command(command: list[str], *, cwd: Path, timeout_seconds: int) -> dict[str, Any]:
    prepared_command, prepared_env = prepare_command(command)
    proc: subprocess.Popen[str] | None = None
    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": prepared_env,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(prepared_command, **popen_kwargs)
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        return {
            "command": prepared_command,
            "returncode": proc.returncode,
            "stdout_tail": tail(stdout or ""),
            "stderr_tail": tail(stderr or ""),
        }
    except subprocess.TimeoutExpired as exc:
        killed_tree = kill_process_tree(proc.pid) if proc is not None else False
        killed_related = kill_related_command_processes(command, cwd)
        if proc is not None:
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            else:
                stdout = stdout or ""
                stderr = stderr or ""
        else:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return {
            "command": prepared_command,
            "returncode": 124,
            "stdout_tail": tail(stdout),
            "stderr_tail": tail(stderr),
            "timeout": True,
            "killed_process_tree": killed_tree,
            "killed_related_processes": killed_related,
        }
    except OSError as exc:
        return {
            "command": prepared_command,
            "returncode": 127,
            "stdout_tail": "",
            "stderr_tail": str(exc),
            "os_error": type(exc).__name__,
        }


def kill_process_tree(pid: int) -> bool:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                child.kill()
            parent.kill()
            gone, alive = psutil.wait_procs([parent, *children], timeout=5)
            for process in alive:
                process.kill()
            if alive:
                _gone_again, alive = psutil.wait_procs(alive, timeout=5)
            return not alive
        except psutil.NoSuchProcess:
            return True
        except psutil.Error:
            pass
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False)
        return result.returncode == 0
    try:
        os.killpg(pid, signal.SIGKILL)
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False


def kill_related_command_processes(command: list[str], cwd: Path) -> int:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return 0
    markers = command_process_markers(command, cwd)
    killed = 0
    current_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid == current_pid:
                continue
            cmdline = " ".join(str(part) for part in proc.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
        normalized = cmdline.replace("\\", "/")
        if not any(marker and marker in normalized for marker in markers):
            continue
        try:
            proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            continue
    return killed


def command_process_markers(command: list[str], cwd: Path) -> list[str]:
    paths: list[str] = []
    if "-w" in command:
        index = command.index("-w")
        if index + 1 < len(command):
            paths.append(command[index + 1])
    if not paths and cwd.is_absolute() and len(str(cwd)) > 12:
        paths.append(str(cwd))
    markers: list[str] = []
    for path in paths:
        if not path:
            continue
        markers.append(path.replace("\\", "/"))
        if os.name == "nt":
            markers.append(to_bash_path(path).replace("\\", "/"))
    return sorted(set(markers), key=len, reverse=True)


def skipped_command(command: list[str], reason: str) -> dict[str, Any]:
    prepared_command, _prepared_env = prepare_command(command)
    return {
        "command": prepared_command,
        "returncode": 127,
        "stdout_tail": "",
        "stderr_tail": reason,
        "skipped": True,
    }


def skipped_audit_result(workspace: Path, out_dir: Path, case_id: str, reason: str) -> dict[str, Any]:
    return {
        "run_id": f"{case_id}_audit_skipped",
        "output_dir": str(out_dir / "audits" / f"{case_id}_audit_skipped"),
        "summary": {"targets": 0, "failed_targets": 0, "skipped_targets": 1, "total_signals": 0, "sectors": {}},
        "rows": [],
        "workspace": str(workspace),
        "skipped": True,
        "reason": reason,
    }


def prepare_command(command: list[str]) -> tuple[list[str], dict[str, str] | None]:
    if os.name != "nt":
        return command, None
    executable = Path(command[0])
    if executable.exists() and not executable.suffix:
        bash = find_git_bash()
        env = prepare_bugsinpy_env()
        shell_command = " ".join(shlex.quote(to_bash_path(part)) for part in command)
        return [str(bash), "-lc", shell_command], env
    return command, None


def prepare_bugsinpy_env() -> dict[str, str] | None:
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "safe.directory"
    env["GIT_CONFIG_VALUE_0"] = "*"
    python_override = os.environ.get("BUGLAB_BUGSINPY_PYTHON")
    if not python_override:
        return env
    shim_root = Path(os.environ.get("BUGLAB_BUGSINPY_SHIM_DIR", Path(tempfile.gettempdir()) / "buglab-bugsinpy-shims"))
    shim_dir = shim_root / safe_path_token(python_override)
    write_python3_shim(shim_dir, Path(python_override))
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    return env


def ensure_windows_venv_python3(project_workspace: Path) -> None:
    if os.name != "nt":
        return
    scripts = project_workspace / "env" / "Scripts"
    python_exe = scripts / "python.exe"
    if python_exe.exists():
        write_python3_shim(scripts, python_exe)


def write_python3_shim(directory: Path, python_exe: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "python3"
    shim.write_text(f'#!/usr/bin/env bash\nexec "{to_bash_path(str(python_exe.resolve()))}" "$@"\n', encoding="utf-8")
    try:
        os.chmod(shim, 0o755)
    except OSError:
        pass


def safe_path_token(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)[-80:]


def find_git_bash() -> Path:
    candidates = [
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return Path(found)
    raise FileNotFoundError("BugsInPy shell scripts need Git Bash on Windows; install Git for Windows or run through Docker.")


def to_bash_path(value: str) -> str:
    if len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}:
        drive = value[0].lower()
        rest = value[2:].replace("\\", "/")
        return f"/{drive}{rest}"
    return value


def tail(text: str, *, limit: int = 2400) -> str:
    return text[-limit:] if len(text) > limit else text


def benchmark_row(
    *,
    case: dict[str, str],
    version_label: str,
    workspace: Path,
    checkout_workspace: Path,
    status: str,
    test_failed_raw: bool | None,
    test_infrastructure_error: bool | None,
    benchmark_test_failed: bool | None,
    audit_detected: bool | None,
    buglab_detected: bool | None,
    elapsed_ms: int,
    commands: dict[str, Any],
) -> dict[str, Any]:
    expected_positive = version_label == "buggy"
    if buglab_detected is None:
        outcome = "planned"
    elif test_infrastructure_error:
        outcome = "invalid_oracle"
    elif expected_positive and buglab_detected:
        outcome = "true_positive"
    elif expected_positive and not buglab_detected:
        outcome = "false_negative"
    elif not expected_positive and buglab_detected:
        outcome = "false_positive"
    else:
        outcome = "true_negative"
    truth_status = outcome_to_truth_status(outcome)
    if outcome == "true_negative" and version_label == "fixed":
        truth_status = "fixed"
    return {
        "project": case["project"],
        "bug_id": case["bug_id"],
        "version": version_label,
        "expected_positive": expected_positive,
        "test_failed_raw": test_failed_raw,
        "test_infrastructure_error": test_infrastructure_error,
        "differential_oracle_valid": None,
        "oracle_issue": "",
        "benchmark_test_failed": benchmark_test_failed,
        "audit_detected": audit_detected,
        "buglab_detected": buglab_detected,
        "outcome": outcome,
        "truth_status": truth_status,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "checkout_workspace": str(checkout_workspace),
        "workspace": str(workspace),
        "commands": commands,
    }


def apply_pair_oracle_validity(rows: list[dict[str, Any]]) -> None:
    runnable = [row for row in rows if row.get("outcome") not in {"planned", "invalid_oracle"}]
    buggy = next((row for row in runnable if row.get("version") == "buggy"), None)
    fixed = next((row for row in runnable if row.get("version") == "fixed"), None)
    if not buggy or not fixed:
        return
    valid = buggy.get("benchmark_test_failed") is True and fixed.get("benchmark_test_failed") is False
    issue = "" if valid else oracle_issue_for_pair(buggy, fixed)
    for row in rows:
        row["differential_oracle_valid"] = valid
        row["oracle_issue"] = issue
    if valid:
        return
    for row in runnable:
        row["outcome"] = "invalid_oracle"
        row["truth_status"] = "invalid_oracle"


def oracle_issue_for_pair(buggy: dict[str, Any], fixed: dict[str, Any]) -> str:
    issues = []
    if buggy.get("benchmark_test_failed") is not True:
        issues.append("buggy_checkout_did_not_trigger")
    if fixed.get("benchmark_test_failed") is not False:
        issues.append("fixed_checkout_did_not_clear")
    return ",".join(issues) or "non_differential_pair"


def build_bugsinpy_truth_entries(run_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for row in rows:
        status = str(row.get("truth_status") or outcome_to_truth_status(str(row.get("outcome", ""))))
        command = row.get("commands", {}).get("test", {}) if isinstance(row.get("commands", {}), dict) else {}
        compile_command = row.get("commands", {}).get("compile", {}) if isinstance(row.get("commands", {}), dict) else {}
        checkout_command = row.get("commands", {}).get("checkout", {}) if isinstance(row.get("commands", {}), dict) else {}
        failure_tail = str(command.get("failure_tail", ""))
        test_command = command_line(command.get("command", []))
        compile_line = command_line(compile_command.get("command", []))
        checkout_line = command_line(checkout_command.get("command", []))
        target = f"{row.get('project')}:{row.get('bug_id')}:{row.get('version')}"
        benchmark_failed = row.get("benchmark_test_failed")
        expected_positive = bool(row.get("expected_positive"))
        claim = (
            "Official BugsInPy triggering test failed on the known buggy checkout."
            if expected_positive
            else "Official BugsInPy triggering test passed on the fixed checkout."
        )
        if row.get("outcome") == "false_positive":
            claim = "BugLab reported a bug on the fixed checkout."
        elif row.get("outcome") == "false_negative":
            claim = "BugLab missed the official BugsInPy triggering failure on the buggy checkout."
        elif row.get("outcome") == "invalid_oracle":
            claim = "Benchmark oracle could not produce a trustworthy verdict."
            if row.get("oracle_issue"):
                claim = f"Benchmark pair was rejected: {row.get('oracle_issue')}."
        entries.append(
            {
                "schema_version": "buglab.truth_ledger.v1",
                "finding_id": f"BUGSINPY-{row.get('project')}-{row.get('bug_id')}-{row.get('version')}",
                "run_id": run_id,
                "target": target,
                "phase": "fix" if row.get("version") == "fixed" else "find",
                "status": status,
                "outcome": row.get("outcome"),
                "confidence": confidence_for_status(status),
                "claim": claim,
                "severity": "benchmark",
                "category": "bugsinpy_oracle",
                "evidence": {
                    "command": test_command,
                    "exit_code": command.get("returncode"),
                    "stdout_tail": command.get("stdout_tail", ""),
                    "stderr_tail": command.get("stderr_tail", ""),
                    "failure_tail": failure_tail,
                    "reproduction_steps": [
                        f"Checkout BugsInPy case {row.get('project')}:{row.get('bug_id')} version {row.get('version')}.",
                        f"Compile with `{compile_line}`." if compile_line else "Compile the BugsInPy checkout.",
                        f"Run the official triggering test with `{test_command}`." if test_command else "Run the official BugsInPy triggering test.",
                        "Classify detection only from the official oracle result; broad incidental test failures are not scored.",
                    ],
                    "signals": compact_signals([failure_tail, command.get("stderr_tail", ""), command.get("stdout_tail", "")]),
                    "workspace": row.get("workspace", ""),
                    "checkout_command": checkout_line,
                    "compile_command": compile_line,
                },
                "oracle": {
                    "type": "BugsInPy triggering test",
                    "known_bug": expected_positive,
                    "differential_oracle_valid": row.get("differential_oracle_valid"),
                    "oracle_issue": row.get("oracle_issue", ""),
                    "benchmark_test_failed": benchmark_failed,
                    "buglab_detected": row.get("buglab_detected"),
                    "audit_detected": row.get("audit_detected"),
                    "verdict": "invalid" if row.get("test_infrastructure_error") or row.get("outcome") == "invalid_oracle" else "scored",
                    "note": "Buggy rows should fail; fixed rows should pass. Invalid oracle rows are excluded from scoring.",
                },
                "metrics": {
                    "elapsed_ms": row.get("elapsed_ms", 0),
                    "tokens": 0,
                },
            }
        )
    return entries


def command_line(command: Any) -> str:
    if isinstance(command, list):
        return " ".join(shlex.quote(str(part)) for part in command)
    return str(command or "")


def compact_signals(values: list[Any], *, limit: int = 5) -> list[str]:
    signals = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        signals.extend(lines[-limit:])
    unique = []
    seen = set()
    for signal in signals:
        if signal in seen:
            continue
        seen.add(signal)
        unique.append(signal)
    return unique[-limit:]


def summarize_bugsinpy_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    invalid = [row for row in rows if row["outcome"] == "invalid_oracle"]
    runnable = [row for row in rows if row["outcome"] not in {"planned", "invalid_oracle"}]
    tp = sum(1 for row in runnable if row["outcome"] == "true_positive")
    fp = sum(1 for row in runnable if row["outcome"] == "false_positive")
    fn = sum(1 for row in runnable if row["outcome"] == "false_negative")
    tn = sum(1 for row in runnable if row["outcome"] == "true_negative")
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    valid_pairs = count_valid_pairs(runnable)
    return {
        "cases": len({(row["project"], row["bug_id"]) for row in rows}),
        "rows": len(rows),
        "runnable_rows": len(runnable),
        "invalid_oracle_rows": len(invalid),
        "valid_differential_pairs": valid_pairs,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "elapsed_ms": sum(int(row["elapsed_ms"]) for row in runnable),
    }


def count_valid_pairs(rows: list[dict[str, Any]]) -> int:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["project"], row["bug_id"]), {})[row["version"]] = row
    valid = 0
    for pair in grouped.values():
        buggy = pair.get("buggy")
        fixed = pair.get("fixed")
        if buggy and fixed and buggy.get("benchmark_test_failed") is True and fixed.get("benchmark_test_failed") is False:
            valid += 1
    return valid


def write_benchmark_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "project",
        "bug_id",
        "version",
        "expected_positive",
        "test_failed_raw",
        "test_infrastructure_error",
        "differential_oracle_valid",
        "oracle_issue",
        "benchmark_test_failed",
        "audit_detected",
        "buglab_detected",
        "outcome",
        "truth_status",
        "status",
        "elapsed_ms",
        "checkout_workspace",
        "workspace",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def render_bugsinpy_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["rows"]
    truth_ledger = payload.get("truth_ledger", {}) if isinstance(payload.get("truth_ledger", {}), dict) else {}
    truth_summary = truth_ledger.get("summary", {}) if isinstance(truth_ledger.get("summary", {}), dict) else {}
    truth_entries = truth_ledger.get("entries", []) if isinstance(truth_ledger.get("entries", []), list) else []
    metric_cards = "".join(
        f"<div class='metric'><strong>{html.escape(format_metric(summary.get(key)))}</strong><span>{html.escape(key)}</span></div>"
        for key in [
            "precision",
            "recall",
            "f1",
            "true_positive",
            "false_positive",
            "false_negative",
            "true_negative",
            "invalid_oracle_rows",
        ]
    )
    truth_cards = "".join(
        f"<div class='metric truth'><strong>{html.escape(format_metric(truth_summary.get(key)))}</strong><span>{html.escape(label)}</span></div>"
        for key, label in [
            ("confirmed", "confirmed evidence"),
            ("fixed", "fixed evidence"),
            ("false_positive", "false positives"),
            ("false_negative", "false negatives"),
            ("tokens_per_confirmed", "tokens / confirmed"),
        ]
    )
    evidence_cards = []
    for entry in truth_entries:
        evidence = entry.get("evidence", {}) if isinstance(entry.get("evidence", {}), dict) else {}
        oracle = entry.get("oracle", {}) if isinstance(entry.get("oracle", {}), dict) else {}
        signals = evidence.get("signals", []) if isinstance(evidence.get("signals", []), list) else []
        steps = evidence.get("reproduction_steps", []) if isinstance(evidence.get("reproduction_steps", []), list) else []
        signal_items = "".join(f"<li>{html.escape(str(signal))}</li>" for signal in signals[:5])
        step_items = "".join(f"<li>{html.escape(str(step))}</li>" for step in steps[:4])
        evidence_cards.append(
            f"""
            <article class="evidence-card {html.escape(str(entry.get('status', '')))}">
              <div class="card-top">
                <strong>{html.escape(str(entry.get('finding_id', '')))}</strong>
                <span>{html.escape(str(entry.get('status', 'unknown')))}</span>
              </div>
              <h2>{html.escape(str(entry.get('claim', '')))}</h2>
              <p><b>Outcome:</b> {html.escape(str(entry.get('outcome', '')))}
              <b>Confidence:</b> {html.escape(str(entry.get('confidence', '')))}
              <b>Oracle:</b> {html.escape(str(oracle.get('type', '')))} / {html.escape(str(oracle.get('verdict', '')))}</p>
              <p><b>Command:</b> <code>{html.escape(str(evidence.get('command', '')))}</code></p>
              <ol>{step_items}</ol>
              <ul>{signal_items or '<li>No failure tail captured.</li>'}</ul>
            </article>
            """
        )
    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['project']))}</td>"
            f"<td>{html.escape(str(row['bug_id']))}</td>"
            f"<td>{html.escape(str(row['version']))}</td>"
            f"<td>{html.escape(str(row.get('test_failed_raw')))}</td>"
            f"<td>{html.escape(str(row.get('test_infrastructure_error')))}</td>"
            f"<td>{html.escape(str(row['benchmark_test_failed']))}</td>"
            f"<td>{html.escape(str(row.get('audit_detected')))}</td>"
            f"<td>{html.escape(str(row['buglab_detected']))}</td>"
            f"<td>{html.escape(str(row['outcome']))}</td>"
            f"<td>{html.escape(str(row.get('truth_status', '')))}</td>"
            f"<td>{html.escape(str(row['elapsed_ms']))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BugLab BugsInPy Benchmark</title>
    <style>
      body {{ margin: 0; background: #030603; color: #d9ffe0; font-family: Consolas, ui-monospace, monospace; }}
      main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 26px 0 48px; }}
      h1 {{ color: #72ff83; font-size: 30px; }}
      p {{ color: #90a996; line-height: 1.5; }}
      .metrics {{ display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }}
      .metric {{ border-top: 1px solid #24452a; padding: 12px 0; }}
      .metric strong {{ display: block; color: #79fff2; font-size: 28px; }}
      .metric span {{ color: #7d9582; font-size: 12px; }}
      .metric.truth strong {{ color: #72ff83; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
      th, td {{ border-bottom: 1px solid #142018; padding: 8px; text-align: left; font-size: 12px; }}
      th {{ color: #f2d36b; }}
      code {{ color: #d9ffe0; overflow-wrap: anywhere; }}
      .evidence-card {{ border-left: 6px solid #6f8f72; background: #061006; margin: 14px 0; padding: 14px; }}
      .evidence-card h2 {{ margin: 10px 0; color: #d9ffe0; font-size: 18px; }}
      .evidence-card.confirmed, .evidence-card.fixed {{ border-left-color: #72ff83; }}
      .evidence-card.fixed .card-top span {{ color: #b895ff; }}
      .evidence-card.false_positive, .evidence-card.false_negative {{ border-left-color: #ff3434; }}
      .card-top {{ display: flex; justify-content: space-between; gap: 12px; color: #72ff83; text-transform: uppercase; }}
      @media (max-width: 900px) {{ .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    </style>
  </head>
  <body>
    <main>
      <h1>BugLab BugsInPy Benchmark</h1>
      <p>Truth-first scoring: buggy checkouts are positives, fixed checkouts are negatives. Detection is driven by the official BugsInPy triggering test; rows with broken test infrastructure are excluded from precision, recall, and F1.</p>
      <section class="metrics">{metric_cards}</section>
      <h2>Evidence Mode</h2>
      <section class="metrics">{truth_cards}</section>
      {''.join(evidence_cards) or '<p>No evidence cards were generated.</p>'}
      <table>
        <thead><tr><th>Project</th><th>Bug</th><th>Version</th><th>Raw test fail</th><th>Infra error</th><th>Benchmark test failed</th><th>Audit detected</th><th>BugLab detected</th><th>Outcome</th><th>Truth status</th><th>ms</th></tr></thead>
        <tbody>{''.join(table_rows)}</tbody>
      </table>
    </main>
  </body>
</html>
"""


def format_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
