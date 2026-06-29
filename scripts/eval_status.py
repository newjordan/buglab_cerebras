from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = Path(os.getenv("BUGLAB_BENCH_ROOT", str(ROOT / ".buglab" / "benchmarks")))
DEFAULT_PACKAGE = ROOT / ".buglab" / "submission" / "submission_results.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Show BugLab evidence/eval status.")
    parser.add_argument("--package", default=str(DEFAULT_PACKAGE), help="Path to live or snapshotted submission_results.json")
    parser.add_argument("--json", action="store_true", help="Print machine-readable status JSON")
    parser.add_argument("--stale-minutes", type=int, default=15, help="Warn if the package has not updated recently")
    args = parser.parse_args()

    package_path = Path(args.package)
    package = read_json(package_path)
    status = build_status(package, package_path, stale_minutes=args.stale_minutes)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print_human(status)
    return 0 if status["ok"] else 1


def build_status(package: dict[str, Any], package_path: Path, *, stale_minutes: int) -> dict[str, Any]:
    summary = package.get("eval_log_summary", {}) if isinstance(package.get("eval_log_summary", {}), dict) else {}
    oracle = package.get("oracle_totals", {}) if isinstance(package.get("oracle_totals", {}), dict) else {}
    oracle_projects = accepted_oracle_projects(oracle, "oracle_project_names", "selected_cases")
    stable_oracle_projects = accepted_oracle_projects(oracle, "stable_project_names", "stable_cases")
    marked = package.get("marked_evidence", {}) if isinstance(package.get("marked_evidence", {}), dict) else {}
    evidence = package.get("evidence_completeness", {}) if isinstance(package.get("evidence_completeness", {}), dict) else {}
    replay = package.get("real_repo_replay", {}) if isinstance(package.get("real_repo_replay", {}), dict) else {}
    replay_unique = (
        package.get("real_repo_replay_unique", {})
        if isinstance(package.get("real_repo_replay_unique", {}), dict)
        else {}
    )
    validation = package.get("validation", {}) if isinstance(package.get("validation", {}), dict) else {}
    latest_events = package.get("latest_eval_events", []) if isinstance(package.get("latest_eval_events", []), list) else []
    updated_at = str(package.get("updated_at_utc", ""))
    age_minutes = package_age_minutes(updated_at)
    runners = list_truth_eval_runners()
    watchdogs = list_truth_eval_watchdogs()
    stale = age_minutes is None or age_minutes > stale_minutes
    ok = bool(package) and validation.get("ok") is True and bool(runners) and not stale
    return {
        "ok": ok,
        "package": str(package_path),
        "updated_at_utc": updated_at,
        "package_age_minutes": age_minutes,
        "stale": stale,
        "validation": {
            "ok": validation.get("ok"),
            "checks": len(validation.get("checks", [])) if isinstance(validation.get("checks", []), list) else 0,
            "warnings": validation.get("warnings", []) if isinstance(validation.get("warnings", []), list) else [],
            "failures": validation.get("failures", []) if isinstance(validation.get("failures", []), list) else [],
        },
        "summary": {
            "events": summary.get("events", 0),
            "completed": summary.get("completed", 0),
            "failed": summary.get("failed", 0),
            "bugsinpy": summary.get("bugsinpy", 0),
            "real_repo_audit": summary.get("real_repo_audit", 0),
            "oracle_cases": oracle.get("unique_cases", 0),
            "stable_oracle_cases": oracle.get("stable_unique_cases", 0),
            "unstable_oracle_cases": oracle.get("unstable_cases", oracle.get("disagreements", 0)),
            "oracle_projects": len(oracle_projects),
            "oracle_project_names": oracle_projects,
            "stable_oracle_projects": len(stable_oracle_projects),
            "stable_oracle_project_names": stable_oracle_projects,
            "true_positive": oracle.get("true_positive", 0),
            "false_positive": oracle.get("false_positive", 0),
            "false_negative": oracle.get("false_negative", 0),
            "true_negative": oracle.get("true_negative", 0),
            "stable_true_positive": oracle.get("stable_true_positive", 0),
            "stable_false_positive": oracle.get("stable_false_positive", 0),
            "stable_false_negative": oracle.get("stable_false_negative", 0),
            "stable_true_negative": oracle.get("stable_true_negative", 0),
            "rejected": oracle.get("rejected_case_results", 0),
            "precision": oracle.get("precision"),
            "precision_wilson_lower_95": oracle.get("precision_wilson_lower_95"),
            "recall": oracle.get("recall"),
            "recall_wilson_lower_95": oracle.get("recall_wilson_lower_95"),
            "f1": oracle.get("f1"),
            "stable_precision": oracle.get("stable_precision"),
            "stable_precision_wilson_lower_95": oracle.get("stable_precision_wilson_lower_95"),
            "stable_recall": oracle.get("stable_recall"),
            "stable_recall_wilson_lower_95": oracle.get("stable_recall_wilson_lower_95"),
            "stable_f1": oracle.get("stable_f1"),
            "marked_entries": marked.get("entries", 0),
            "suspected": marked.get("suspected", 0),
            "invalid_oracle": marked.get("invalid_oracle", 0),
            "evidence_complete_entries": evidence.get("complete_entries", 0),
            "evidence_incomplete_entries": evidence.get("incomplete_entries", 0),
            "evidence_completion_rate": evidence.get("completion_rate"),
            "evidence_missing_reproduction": evidence.get("missing_reproduction", 0),
            "evidence_missing_observation": evidence.get("missing_observation", 0),
            "replay_checked": replay.get("checked", 0),
            "replay_reproduced": replay.get("reproduced", 0),
            "replay_partially_reproduced": replay.get("partially_reproduced", 0),
            "replay_not_reproduced": replay.get("not_reproduced", 0),
            "replay_unsupported": replay.get("unsupported", 0),
            "replay_errors": replay.get("error", 0),
            "replay_unsupported_signals": replay.get("unsupported_signals", 0),
            "replay_reproduction_rate": replay.get("replay_reproduction_rate"),
            "replay_triage": replay.get("triage", {}) if isinstance(replay.get("triage", {}), dict) else {},
            "unique_replay_packet_checked": replay_unique.get("packet_checked", 0),
            "unique_replay_claims": replay_unique.get("unique_claims", 0),
            "unique_replay_duplicate_packets_collapsed": replay_unique.get("duplicate_packets_collapsed", 0),
            "unique_replay_reproduced": replay_unique.get("unique_reproduced", 0),
            "unique_replay_partially_reproduced": replay_unique.get("unique_partially_reproduced", 0),
            "unique_replay_not_reproduced": replay_unique.get("unique_not_reproduced", 0),
            "unique_replay_unsupported": replay_unique.get("unique_unsupported", 0),
            "unique_replay_errors": replay_unique.get("unique_error", 0),
            "unique_replay_reproduction_rate": replay_unique.get("unique_replay_reproduction_rate"),
            "unique_replay_triage": (
                replay_unique.get("triage", {}) if isinstance(replay_unique.get("triage", {}), dict) else {}
            ),
        },
        "runners": runners,
        "watchdogs": watchdogs,
        "latest_events": latest_events[:6],
    }


def list_truth_eval_runners() -> list[dict[str, Any]]:
    return list_truth_eval_processes({"eval_runner", "discovery"})


def list_truth_eval_watchdogs() -> list[dict[str, Any]]:
    return list_truth_eval_processes({"watchdog"})


def list_truth_eval_processes(roles: set[str]) -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return []
    runners: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            rendered = " ".join(str(part) for part in cmdline)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        role = eval_process_role(cmdline)
        if role not in roles:
            continue
        runners.append(
            {
                "pid": proc.info.get("pid"),
                "name": proc.info.get("name"),
                "role": role,
                "started_at_utc": utc_from_timestamp(float(proc.info.get("create_time") or 0)),
                "cmdline": rendered,
            }
        )
    return sorted(runners, key=lambda item: str(item.get("started_at_utc", "")))


def eval_process_role(cmdline: list[Any]) -> str:
    names = {Path(str(part).replace("\\", "/")).name for part in cmdline}
    if "truth_eval_runner.py" in names:
        return "eval_runner"
    if "discover_bugsinpy_cases.py" in names:
        return "discovery"
    if "truth_eval_watchdog.py" in names:
        return "watchdog"
    return ""


def package_age_minutes(updated_at: str) -> float | None:
    if not updated_at:
        return None
    try:
        updated = datetime.fromisoformat(updated_at.removesuffix("Z")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - updated).total_seconds() / 60, 2)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def print_human(status: dict[str, Any]) -> None:
    validation = status["validation"]
    summary = status["summary"]
    print(f"BugLab eval status: {'PASS' if status['ok'] else 'CHECK'}")
    print(f"updated_at_utc: {status['updated_at_utc']} ({status['package_age_minutes']} min old)")
    print(f"validation: {validation['ok']} checks={validation['checks']} failures={len(validation['failures'])}")
    print(
        "events={events} completed={completed} failed={failed} bugsinpy={bugsinpy} real_repo={real_repo_audit}".format(
            **summary
        )
    )
    print(
        "oracle_cases={oracle_cases} oracle_projects={oracle_projects} TP={true_positive} FP={false_positive} FN={false_negative} TN={true_negative} rejected={rejected} precision={precision} recall={recall} f1={f1}".format(
            **summary
        )
    )
    print(
        "stable_oracle_cases={stable_oracle_cases} unstable_oracle_cases={unstable_oracle_cases} stable_projects={stable_oracle_projects} stable_TP={stable_true_positive} stable_FP={stable_false_positive} stable_FN={stable_false_negative} stable_TN={stable_true_negative} stable_precision={stable_precision} stable_recall={stable_recall} stable_f1={stable_f1}".format(
            **summary
        )
    )
    print(
        "confidence_lower_95 precision={precision_wilson_lower_95} recall={recall_wilson_lower_95} stable_precision={stable_precision_wilson_lower_95} stable_recall={stable_recall_wilson_lower_95}".format(
            **summary
        )
    )
    if summary.get("oracle_project_names"):
        print("oracle_project_names=" + ",".join(summary["oracle_project_names"]))
    if summary.get("stable_oracle_project_names"):
        print("stable_oracle_project_names=" + ",".join(summary["stable_oracle_project_names"]))
    print(
        "marked_entries={marked_entries} suspected={suspected} invalid_oracle={invalid_oracle}".format(
            **summary
        )
    )
    print(
        "evidence_packets complete={evidence_complete_entries} incomplete={evidence_incomplete_entries} completion_rate={evidence_completion_rate} missing_repro={evidence_missing_reproduction} missing_observation={evidence_missing_observation}".format(
            **summary
        )
    )
    print(
        "real_repo_replay checked={replay_checked} reproduced={replay_reproduced} partial={replay_partially_reproduced} not_reproduced={replay_not_reproduced} unsupported={replay_unsupported} errors={replay_errors} unsupported_signals={replay_unsupported_signals} replay_rate={replay_reproduction_rate}".format(
            **summary
        )
    )
    triage = summary.get("replay_triage", {})
    if isinstance(triage, dict) and triage:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(triage.items(), key=lambda item: int(item[1] or 0), reverse=True))
        print(f"real_repo_replay_triage {rendered}")
    print(
        "unique_replay_claims claims={unique_replay_claims} reproduced={unique_replay_reproduced} partial={unique_replay_partially_reproduced} not_reproduced={unique_replay_not_reproduced} unsupported={unique_replay_unsupported} errors={unique_replay_errors} collapsed_packets={unique_replay_duplicate_packets_collapsed} replay_rate={unique_replay_reproduction_rate}".format(
            **summary
        )
    )
    unique_triage = summary.get("unique_replay_triage", {})
    if isinstance(unique_triage, dict) and unique_triage:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(unique_triage.items(), key=lambda item: int(item[1] or 0), reverse=True))
        print(f"unique_replay_triage {rendered}")
    print(f"runners={len(status['runners'])}")
    for runner in status["runners"]:
        print(f"- pid={runner['pid']} role={runner.get('role', 'runner')} started={runner['started_at_utc']} {runner['cmdline']}")
    watchdogs = status.get("watchdogs", [])
    print(f"watchdogs={len(watchdogs)}")
    for watchdog in watchdogs:
        print(f"- pid={watchdog['pid']} role={watchdog.get('role', 'watchdog')} started={watchdog['started_at_utc']} {watchdog['cmdline']}")
    print("latest:")
    for event in status["latest_events"]:
        print(f"- {event.get('started_at_utc', '')} {event.get('kind', '')} {event.get('target_name', event.get('target', ''))}: {event.get('summary', '')}")
    for warning in validation.get("warnings", []):
        print(f"warning: {warning}")
    for failure in validation.get("failures", []):
        print(f"failure: {failure}")


def utc_from_timestamp(value: float) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def accepted_oracle_projects(oracle: dict[str, Any], names_key: str, cases_key: str) -> list[str]:
    explicit_names = oracle.get(names_key, []) if isinstance(oracle, dict) else []
    if isinstance(explicit_names, list):
        names = sorted({str(name) for name in explicit_names if str(name)}, key=str.lower)
        if names:
            return names
    projects = set()
    selected = oracle.get(cases_key, []) if isinstance(oracle, dict) else []
    for item in selected if isinstance(selected, list) else []:
        case = str(item.get("case", ""))
        if ":" in case:
            projects.add(case.split(":", 1)[0])
    return sorted(projects, key=str.lower)


if __name__ == "__main__":
    raise SystemExit(main())
