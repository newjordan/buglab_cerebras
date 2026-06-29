from __future__ import annotations

import argparse
import json
import sys

from buglab.api import BugHuntConfig
from buglab.api import audit_repo
from buglab.api import benchmark_bugsinpy
from buglab.api import build_index
from buglab.api import build_pareto
from buglab.api import calibrate_findings
from buglab.api import bughunt_repo
from buglab.api import bug_hunt
from buglab.api import doctor_repo
from buglab.api import init_project
from buglab.api import list_cases
from buglab.api import run_ablation
from buglab.api import run_medic
from buglab.api import repair_sector_manifest
from buglab.api import run_quality
from buglab.api import run_matrix
from buglab.api import run_loops
from buglab.api import scan_repo
from buglab.api import run_swarm
from buglab.api import run_truth_harness
from buglab.cases import render_case_queue_text
from buglab.doctor import render_doctor_text
from buglab.sectors import SectorBenchmarkConfig
from buglab.sectors import run_sector_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="buglab", description="Installable bug-hunting swarm CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a portable .buglab/config.json for this repo.")
    init.add_argument("--repo", default=".", help="Repository/root folder to initialize.")
    init.add_argument("--config", default=".buglab/config.json", help="Config path, relative to --repo unless absolute.")
    init.add_argument("--target", action="append", dest="targets", help="Target URL or path. Can be passed multiple times.")
    init.add_argument("--output", default=".buglab/runs")
    init.add_argument("--loops", type=int, default=3)
    init.add_argument("--profiles", default="balanced,business,edge")
    init.add_argument("--max-clicks", type=int, default=30)
    init.add_argument("--force", action="store_true", help="Overwrite an existing config.")

    run = subparsers.add_parser("run", help="Run one bug hunt.")
    add_common_args(run)
    run.add_argument("--profile", default="balanced", choices=["balanced", "business", "edge"])
    run.add_argument("--name", default="buglab")

    loops = subparsers.add_parser("loops", help="Run repeated bug-hunt loops and record data.")
    add_common_args(loops)
    loops.add_argument("--loops", type=int, default=3)
    loops.add_argument("--profiles", default="balanced,business,edge")
    loops.add_argument("--name", default="buglab_loop")

    matrix = subparsers.add_parser("matrix", help="Run configured targets and profiles from .buglab/config.json.")
    matrix.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    matrix.add_argument("--config", default=".buglab/config.json", help="Config path, relative to --repo unless absolute.")
    matrix.add_argument("--output", default=None, help="Override config output directory.")
    matrix.add_argument("--loops", type=int, default=None, help="Override config loop count.")
    matrix.add_argument("--profiles", default=None, help="Override config profiles as a comma-separated list.")
    matrix.add_argument("--max-clicks", type=int, default=None, help="Override config max clicks.")
    matrix.add_argument("--target-id", action="append", dest="target_ids", help="Only run a configured target id. Can be passed multiple times.")
    matrix.add_argument("--name", default="buglab_matrix")
    matrix.add_argument("--no-index", action="store_true", help="Skip rebuilding .buglab/runs/index.html.")

    scan = subparsers.add_parser("scan", help="One-command repo bug hunt: init/discover targets, run matrix, and index reports.")
    scan.add_argument("--repo", default=".", help="Repository/root folder to scan.")
    scan.add_argument("--config", default=".buglab/config.json", help="Config path, relative to --repo unless absolute.")
    scan.add_argument("--target", action="append", dest="targets", help="Target URL or path. Can be passed multiple times.")
    scan.add_argument("--output", default=None, help="Override output directory.")
    scan.add_argument("--loops", type=int, default=3)
    scan.add_argument("--profiles", default="balanced,business,edge")
    scan.add_argument("--max-clicks", type=int, default=30)
    scan.add_argument("--target-id", action="append", dest="target_ids", help="Only run a configured target id. Can be passed multiple times.")
    scan.add_argument("--name", default="buglab_scan")
    scan.add_argument("--force-init", action="store_true", help="Regenerate .buglab/config.json before running.")
    scan.add_argument("--no-index", action="store_true", help="Skip rebuilding .buglab/runs/index.html.")

    audit = subparsers.add_parser("audit", help="One-command multi-sector repo bug hunt with a standardized aggregate report.")
    add_audit_args(audit)

    hunt = subparsers.add_parser("hunt", help="Alias for audit: connect a repo and run a multi-sector bug hunt.")
    add_audit_args(hunt)

    workflow = subparsers.add_parser("bughunt", help="Full any-repo workflow: doctor, hunt, cases, Pareto, and index.")
    add_workflow_args(workflow)

    doctor = subparsers.add_parser("doctor", help="Preflight an arbitrary repo before running BugLab.")
    doctor.add_argument("--repo", default=".", help="Repository/root folder to check.")
    doctor.add_argument("--target", action="append", dest="targets", help="Browser target URL or path. Can be passed multiple times.")
    doctor.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    doctor.add_argument("--skip-browser", action="store_true", help="Skip Playwright Chromium launch check.")
    doctor.add_argument("--no-report", action="store_true", help="Do not write a doctor JSON report.")
    doctor.add_argument("--format", choices=["text", "json"], default="text")

    cases = subparsers.add_parser("cases", help="List per-finding BugLab repro case bundles for repair agents.")
    cases.add_argument("--repo", default=".", help="Repository/root folder with .buglab runs.")
    cases.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    cases.add_argument("--run", dest="run_id", default="latest", help="Audit run id, or latest.")
    cases.add_argument("--sector", default=None, help="Filter by sector, for example browser or config.")
    cases.add_argument("--severity", default=None, help="Filter by severity, for example high or medium.")
    cases.add_argument("--format", choices=["text", "json"], default="text")

    pareto = subparsers.add_parser("pareto", help="Build a findings Pareto CSV/JSON/HTML report from repo-audit runs.")
    pareto.add_argument("--repo", default=".", help="Repository/root folder with .buglab runs.")
    pareto.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    pareto.add_argument("--top", type=int, default=20, help="Number of ranked rows to keep per dimension.")

    calibrate = subparsers.add_parser("calibrate", help="Score bug-hunt findings against a truth ledger and report precision/recall.")
    calibrate.add_argument("--repo", default=".", help="Repository/root folder containing the calibration ledger.")
    calibrate.add_argument("--output", default=".buglab/runs", help="Output directory with repo-audit runs, relative to --repo unless absolute.")
    calibrate.add_argument("--ledger", default=".buglab/calibration/truth_ledger.json", help="Truth ledger JSON path, relative to --repo unless absolute.")
    calibrate.add_argument("--top", type=int, default=20, help="Number of signal families to keep per calibration dimension.")

    bugsinpy = subparsers.add_parser("benchmark-bugsinpy", help="Run paired buggy/fixed BugsInPy truth scoring.")
    bugsinpy.add_argument("--bugsinpy-root", required=True, help="Path to the BugsInPy checkout.")
    bugsinpy.add_argument("--case", action="append", dest="cases", help="Case in project:bug_id format. Can be passed multiple times.")
    bugsinpy.add_argument("--case-file", default=None, help="CSV or JSON file with project and bug_id fields.")
    bugsinpy.add_argument("--output", default=".buglab/benchmarks/bugsinpy", help="Benchmark report output directory.")
    bugsinpy.add_argument("--workspace", default=".buglab/benchmarks/bugsinpy/workspaces", help="Checkout workspace directory.")
    bugsinpy.add_argument("--name", default="bugsinpy", help="Run name prefix.")
    bugsinpy.add_argument("--timeout-seconds", type=int, default=180)
    bugsinpy.add_argument("--dry-run", action="store_true", help="Write the planned checkout/test/audit commands without running them.")

    truth_harness = subparsers.add_parser("truth-harness", help="Run a minimal known-bug fixture pack and report calibration metrics.")
    truth_harness.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    truth_harness.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    truth_harness.add_argument("--manifest", default=None, help="Use an existing sector-style fixture manifest instead of generating one.")
    truth_harness.add_argument("--fixture-root", default=".buglab/truth_harness/fixtures", help="Generated fixture pack directory, relative to --repo unless absolute.")
    truth_harness.add_argument("--name", default="truth_harness", help="Run name prefix.")
    truth_harness.add_argument("--force-fixture-pack", action="store_true", help="Overwrite the generated fixture pack files.")

    quality = subparsers.add_parser("quality", help="Run deterministic quality gates and write reproducible command artifacts.")
    quality.add_argument("--repo", default=".", help="Repository/root folder to check.")
    quality.add_argument("--output", default=".buglab/quality", help="Output directory, relative to --repo unless absolute.")
    quality.add_argument("--name", default="quality", help="Run name prefix.")
    quality.add_argument("--profile", choices=["auto", "buglab", "node", "generic"], default="auto")
    quality.add_argument("--timeout-seconds", type=int, default=180)
    quality.add_argument("--include-audit", action="store_true", help="Also run npm audit when checking Node repos.")

    medic = subparsers.add_parser("medic", help="Diagnose broken gates and choose the next self-repair/tooling move.")
    medic.add_argument("--repo", default=".", help="Repository/root folder to diagnose.")
    medic.add_argument("--output", default=".buglab/medic", help="Output directory, relative to --repo unless absolute.")
    medic.add_argument("--name", default="medic", help="Run name prefix.")
    medic.add_argument("--quality-report", default=None, help="Existing quality_report.json to diagnose.")
    medic.add_argument("--tool-runs", default=None, help="Directory of external tool artifacts such as jest-output.txt or npm-audit.json.")
    medic.add_argument("--run-quality", action="store_true", help="Run a fresh quality gate before medic diagnosis.")
    medic.add_argument("--profile", choices=["auto", "buglab", "node", "generic"], default="auto")

    tui = subparsers.add_parser("tui", help="Run the terminal BugLab dashboard with Dotmax-style braille primitives.")
    tui.add_argument("--repo", default=".", help="Repository/root folder to visualize.")
    tui.add_argument("--mode", choices=["find", "fix", "find_fix"], default="find", help="Display mode.")
    tui.add_argument("--frames", type=int, default=96, help="Animation frames. Use 0 to run until Ctrl+C.")
    tui.add_argument("--delay", type=float, default=0.055, help="Seconds between frames.")
    tui.add_argument("--no-clear", action="store_true", help="Render one frame without clearing the terminal.")
    tui.add_argument("--overwatch-assets", default=None, help="Path to a Fleet Overwatch checkout to reuse terminal motifs.")
    tui.add_argument("--no-overwatch-assets", action="store_true", help="Disable automatic Overwatch asset discovery.")

    swarm = subparsers.add_parser("swarm", help="Run a multi-field bug-hunt swarm and write a cross-sector report.")
    swarm.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    swarm.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    swarm.add_argument("--field", action="append", dest="fields", help="Field to run: browser_api, cli_data, or repo_quality. Defaults to all when no --manifest is provided.")
    swarm.add_argument("--manifest", action="append", dest="manifests", help="Custom sector manifest path. If no --field is set, only custom manifests run.")
    swarm.add_argument("--loops", type=int, default=1)
    swarm.add_argument("--profiles", default="balanced")
    swarm.add_argument("--max-clicks", type=int, default=16)
    swarm.add_argument("--name", default="buglab_swarm")
    swarm.add_argument("--repair", action="store_true", help="Run supported non-destructive repair verification after detection.")
    swarm.add_argument("--no-index", action="store_true", help="Skip rebuilding .buglab/runs/index.html.")

    ablate = subparsers.add_parser("ablate", help="Run swarm technique variants and rank the Pareto frontier.")
    ablate.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    ablate.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    ablate.add_argument("--field", action="append", dest="fields", help="Field to test: browser_api, cli_data, or repo_quality. Defaults to all.")
    ablate.add_argument("--manifest", action="append", dest="manifests", help="Custom sector manifest path to test as its own ablation variant.")
    ablate.add_argument(
        "--profile-set",
        action="append",
        dest="profile_sets",
        help="Comma-separated profile set to test, for example balanced or balanced,business,edge. Can be repeated.",
    )
    ablate.add_argument("--loops", type=int, default=1)
    ablate.add_argument("--repeats", type=int, default=1)
    ablate.add_argument("--max-clicks", type=int, default=16)
    ablate.add_argument("--name", default="swarm_ablation")
    ablate.add_argument("--repair", action="store_true", help="Include supported non-destructive repair verification in each variant.")
    ablate.add_argument("--no-index", action="store_true", help="Skip rebuilding .buglab/runs/index.html.")

    index = subparsers.add_parser("index", help="Build an HTML index for standardized run reports.")
    index.add_argument("--repo", default=".", help="Repository/root folder to index.")
    index.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")

    sector = subparsers.add_parser("sector", help="Run a sector manifest and score expected bug coverage.")
    sector.add_argument("--manifest", required=True, help="Sector manifest JSON path.")
    sector.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    sector.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    sector.add_argument("--loops", type=int, default=3)
    sector.add_argument("--profiles", default="balanced,business,edge")
    sector.add_argument("--max-clicks", type=int, default=30)
    sector.add_argument("--name", default="sector")

    repair = subparsers.add_parser("repair-sector", help="Run find/repair/verify on supported fixtures in a sector manifest.")
    repair.add_argument("--manifest", required=True, help="Sector manifest JSON path.")
    repair.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    repair.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    repair.add_argument("--loops", type=int, default=1)
    repair.add_argument("--profiles", default="balanced")
    repair.add_argument("--max-clicks", type=int, default=30)
    repair.add_argument("--name", default="repair")

    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="URL or path relative to --repo.")
    parser.add_argument("--repo", default=".", help="Repository/root folder to run from.")
    parser.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    parser.add_argument("--max-clicks", type=int, default=30)
    parser.add_argument("--mobile", action="store_true")


def add_audit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="Repository/root folder to audit.")
    parser.add_argument("--target", action="append", dest="targets", help="Browser target URL or path. Can be passed multiple times.")
    parser.add_argument("--output", default=".buglab/runs", help="Output directory, relative to --repo unless absolute.")
    parser.add_argument("--loops", type=int, default=1)
    parser.add_argument("--profiles", default="balanced")
    parser.add_argument("--max-clicks", type=int, default=12)
    parser.add_argument("--name", default="buglab_audit")
    parser.add_argument("--no-browser", action="store_true", help="Skip browser/Playwright audit.")
    parser.add_argument("--no-docs", action="store_true", help="Skip Markdown docs/link audit.")
    parser.add_argument("--no-tests", action="store_true", help="Skip Python unittest audit.")
    parser.add_argument("--no-config", action="store_true", help="Skip JSON/env config audit.")
    parser.add_argument("--no-index", action="store_true", help="Skip rebuilding .buglab/runs/index.html.")
    parser.add_argument("--exit-policy", choices=["warn", "bugs"], default="warn", help="Use bugs to exit non-zero when signals are found.")


def add_workflow_args(parser: argparse.ArgumentParser) -> None:
    add_audit_args(parser)
    parser.add_argument("--no-doctor", action="store_true", help="Skip preflight doctor checks.")
    parser.add_argument("--skip-browser-check", action="store_true", help="Skip doctor Playwright launch check.")
    parser.add_argument("--no-pareto", action="store_true", help="Skip findings Pareto report generation.")
    parser.add_argument("--pareto-top", type=int, default=20, help="Number of Pareto rows to keep per dimension.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        result = init_project(
            repo=args.repo,
            config_path=args.config,
            targets=args.targets,
            output=args.output,
            loops=args.loops,
            profiles=parse_csv(args.profiles),
            max_clicks=args.max_clicks,
            force=args.force,
        )
        print(json.dumps({"config_path": result["config_path"], "created": result["created"], "targets": result["config"].get("targets", [])}, indent=2))
        return 0
    if args.command == "run":
        result = bug_hunt(
            BugHuntConfig(
                target=args.target,
                repo=args.repo,
                output=args.output,
                run_name=args.name,
                max_clicks=args.max_clicks,
                mobile=args.mobile,
                profile=args.profile,
            )
        )
        print(json.dumps({"run_id": result.run_id, "output_dir": result.output_dir, "bug_candidate_count": result.bug_candidate_count}, indent=2))
        return 1 if result.bug_candidate_count else 0
    if args.command == "loops":
        result = run_loops(
            target=args.target,
            repo=args.repo,
            output=args.output,
            loops=args.loops,
            profiles=[item.strip() for item in args.profiles.split(",") if item.strip()],
            max_clicks=args.max_clicks,
            mobile=args.mobile,
            run_name=args.name,
        )
        print(json.dumps(result["summary"], indent=2))
        print(result["csv_path"])
        return 0
    if args.command == "matrix":
        result = run_matrix(
            repo=args.repo,
            config_path=args.config,
            output=args.output,
            loops=args.loops,
            profiles=parse_csv(args.profiles) if args.profiles else None,
            max_clicks=args.max_clicks,
            run_name=args.name,
            target_ids=args.target_ids,
            build_report_index=not args.no_index,
        )
        print(json.dumps(result["summary"], indent=2))
        print(result["csv_path"])
        if result.get("index"):
            print(result["index"]["index_path"])
        return 0
    if args.command == "scan":
        result = scan_repo(
            repo=args.repo,
            config_path=args.config,
            targets=args.targets,
            output=args.output,
            loops=args.loops,
            profiles=parse_csv(args.profiles),
            max_clicks=args.max_clicks,
            run_name=args.name,
            force_init=args.force_init,
            target_ids=args.target_ids,
            build_report_index=not args.no_index,
        )
        print(
            json.dumps(
                {
                    "config_path": result["config_path"],
                    "config_created": result["config_created"],
                    "summary": result["summary"],
                    "csv_path": result["csv_path"],
                    "json_path": result["json_path"],
                    "index_path": result["index"]["index_path"] if result.get("index") else None,
                },
                indent=2,
            )
        )
        return 0
    if args.command in {"audit", "hunt"}:
        result = audit_repo(
            repo=args.repo,
            targets=args.targets,
            output=args.output,
            loops=args.loops,
            profiles=parse_csv(args.profiles),
            max_clicks=args.max_clicks,
            run_name=args.name,
            include_browser=not args.no_browser,
            include_docs=not args.no_docs,
            include_tests=not args.no_tests,
            include_config=not args.no_config,
            build_report_index=not args.no_index,
        )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "summary": result["summary"],
                    "csv_path": result["csv_path"],
                    "json_path": result["json_path"],
                    "findings_csv_path": result["findings_csv_path"],
                    "findings_jsonl_path": result["findings_jsonl_path"],
                    "case_index_path": result["case_index_path"],
                    "report_path": result["report_path"],
                    "index_path": result["index"]["index_path"] if result.get("index") else None,
                },
                indent=2,
            )
        )
        return 1 if args.exit_policy == "bugs" and result["summary"].get("total_signals", 0) else 0
    if args.command == "bughunt":
        result = bughunt_repo(
            repo=args.repo,
            output=args.output,
            targets=args.targets,
            loops=args.loops,
            profiles=parse_csv(args.profiles),
            max_clicks=args.max_clicks,
            run_name=args.name,
            include_browser=not args.no_browser,
            include_docs=not args.no_docs,
            include_tests=not args.no_tests,
            include_config=not args.no_config,
            run_doctor=not args.no_doctor,
            check_browser=not args.skip_browser_check,
            build_pareto=not args.no_pareto,
            build_report_index=not args.no_index,
            pareto_top=args.pareto_top,
        )
        print(
            json.dumps(
                {
                    "summary": result["summary"],
                    "workflow_path": result["workflow_path"],
                    "audit": result["audit"],
                    "cases": result["cases"],
                    "pareto": result["pareto"],
                    "index": result["index"],
                },
                indent=2,
            )
        )
        return 1 if args.exit_policy == "bugs" and result["summary"].get("total_signals", 0) else 0
    if args.command == "doctor":
        result = doctor_repo(
            repo=args.repo,
            output=args.output,
            targets=args.targets,
            check_browser=not args.skip_browser,
            write_report=not args.no_report,
        )
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(render_doctor_text(result), end="")
        return 1 if result["summary"].get("status") == "failed" else 0
    if args.command == "cases":
        result = list_cases(
            repo=args.repo,
            output=args.output,
            run_id=args.run_id,
            sector=args.sector,
            severity=args.severity,
        )
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(render_case_queue_text(result), end="")
        return 0
    if args.command == "pareto":
        result = build_pareto(repo=args.repo, output=args.output, top=args.top)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "calibrate":
        result = calibrate_findings(repo=args.repo, output=args.output, ledger=args.ledger, top=args.top)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "benchmark-bugsinpy":
        result = benchmark_bugsinpy(
            bugsinpy_root=args.bugsinpy_root,
            output=args.output,
            workspace=args.workspace,
            cases=args.cases,
            case_file=args.case_file,
            run_name=args.name,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["summary"].get("false_positive", 0) == 0 and result["summary"].get("false_negative", 0) == 0 else 1
    if args.command == "truth-harness":
        result = run_truth_harness(
            repo=args.repo,
            output=args.output,
            manifest=args.manifest,
            fixture_root=args.fixture_root,
            run_name=args.name,
            force_fixture_pack=args.force_fixture_pack,
        )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "summary": result["summary"],
                    "manifest_path": result["manifest_path"],
                    "json_path": result["json_path"],
                    "csv_path": result["csv_path"],
                    "truth_ledger_path": result["truth_ledger_path"],
                },
                indent=2,
            )
        )
        return 0 if result["summary"].get("status") == "passed" else 1
    if args.command == "quality":
        result = run_quality(
            repo=args.repo,
            output=args.output,
            run_name=args.name,
            profile=args.profile,
            timeout_seconds=args.timeout_seconds,
            include_audit=args.include_audit,
        )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "summary": result["summary"],
                    "json_path": result["json_path"],
                    "markdown_path": result["markdown_path"],
                },
                indent=2,
            )
        )
        return 0 if result["summary"].get("status") == "passed" else 1
    if args.command == "medic":
        result = run_medic(
            repo=args.repo,
            output=args.output,
            run_name=args.name,
            quality_report=args.quality_report,
            tool_runs=args.tool_runs,
            run_quality=args.run_quality,
            profile=args.profile,
        )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "summary": result["summary"],
                    "json_path": result["json_path"],
                    "markdown_path": result["markdown_path"],
                    "recommendations": result["recommendations"],
                },
                indent=2,
            )
        )
        return 0 if result["summary"].get("status") == "clear" else 1
    if args.command == "tui":
        from buglab.tui import TuiConfig
        from buglab.tui import run_tui

        return run_tui(
            TuiConfig(
                repo=args.repo,
                mode=args.mode,
                frames=args.frames,
                delay=args.delay,
                no_clear=args.no_clear,
                overwatch_assets=args.overwatch_assets,
                no_overwatch_assets=args.no_overwatch_assets,
            )
        )
    if args.command == "swarm":
        result = run_swarm(
            repo=args.repo,
            output=args.output,
            fields=args.fields,
            manifests=args.manifests,
            loops=args.loops,
            profiles=parse_csv(args.profiles),
            max_clicks=args.max_clicks,
            run_name=args.name,
            repair=args.repair,
            build_report_index=not args.no_index,
        )
        print(
            json.dumps(
                {
                    "summary": result["summary"],
                    "csv_path": result["csv_path"],
                    "json_path": result["json_path"],
                    "html_path": result["html_path"],
                    "index_path": result["index"]["index_path"] if result.get("index") else None,
                },
                indent=2,
            )
        )
        return 0 if result["summary"].get("sector_pass_rate", 0) >= 1 else 1
    if args.command == "ablate":
        result = run_ablation(
            repo=args.repo,
            output=args.output,
            fields=args.fields,
            manifests=args.manifests,
            profile_sets=args.profile_sets,
            loops=args.loops,
            repeats=args.repeats,
            max_clicks=args.max_clicks,
            run_name=args.name,
            repair=args.repair,
            build_report_index=not args.no_index,
        )
        print(
            json.dumps(
                {
                    "summary": result["summary"],
                    "csv_path": result["csv_path"],
                    "json_path": result["json_path"],
                    "html_path": result["html_path"],
                    "index_path": result["index"]["index_path"] if result.get("index") else None,
                },
                indent=2,
            )
        )
        return 0 if result["summary"].get("pareto_variants", 0) else 1
    if args.command == "index":
        result = build_index(repo=args.repo, output=args.output)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "sector":
        result = run_sector_benchmark(
            SectorBenchmarkConfig(
                manifest=args.manifest,
                repo=args.repo,
                output=args.output,
                loops=args.loops,
                profiles=[item.strip() for item in args.profiles.split(",") if item.strip()],
                max_clicks=args.max_clicks,
                run_name=args.name,
            )
        )
        print(json.dumps(result["summary"], indent=2))
        print(result["csv_path"])
        return 0 if result["summary"].get("detection_rate", 0) >= 1 else 1
    if args.command == "repair-sector":
        result = repair_sector_manifest(
            manifest=args.manifest,
            repo=args.repo,
            output=args.output,
            loops=args.loops,
            profiles=[item.strip() for item in args.profiles.split(",") if item.strip()],
            max_clicks=args.max_clicks,
            run_name=args.name,
        )
        print(json.dumps(result["summary"], indent=2))
        print(result["csv_path"])
        return 0 if result["summary"].get("total_after_found_bugs", 1) == 0 else 1
    return 2


def hunt_main(argv: list[str] | None = None) -> int:
    return main(["bughunt", *(argv or sys.argv[1:])])


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    sys.exit(main())
