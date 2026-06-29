# Installable BugLab API

BugLab can run as a local package from any repository. It accepts a URL or a file path relative to the target repo, plays the software, records screenshots, emits standardized reports, and can run repeated profile loops for technique data.

## Install

From this repository:

```powershell
pip install -e .
python -m playwright install chromium
```

From another repo on the same machine, install by path:

```powershell
pip install -e C:\path\to\buglab
python -m playwright install chromium
python -m buglab bughunt --repo C:\path\to\repo --loops 1 --profiles balanced
```

## CLI

One-command workflow for any repo:

```powershell
buglab bughunt --repo C:\path\to\repo --loops 1 --profiles balanced
bughunt --repo C:\path\to\repo --loops 1 --profiles balanced
```

This runs `doctor`, repo audit, case-bundle listing, findings Pareto generation, and index rebuild in one pass. It writes `<name>_<timestamp>_workflow.json` under `.buglab\runs` with links to the doctor report, audit report, case index, Pareto report, and HTML index.

Preflight any repo before spending time on a hunt:

```powershell
buglab doctor --repo C:\path\to\repo
buglab doctor --repo C:\path\to\repo --format json
```

This checks repo readability, `.buglab\runs` writability, target discovery, docs/tests/config inventory, package import metadata, and Playwright Chromium launch readiness. It writes `doctor_<timestamp>.json` under `.buglab\runs` unless `--no-report` is passed.

Default multi-sector bug hunt for any repo:

```powershell
buglab hunt --repo C:\path\to\repo --loops 1 --profiles balanced
```

If Python installs console scripts outside `PATH`, use the module entrypoint from any repo:

```powershell
python -m buglab hunt --repo C:\path\to\repo --loops 1 --profiles balanced
```

This runs the repo audit layer across browser entrypoints, Markdown docs/link integrity, Python unittest signals, and JSON/env config checks. It writes one aggregate `buglab.report.v1` report plus `repo_audit_rows.csv` and `repo_audit.json`.

One-command scan for another repo:

```powershell
buglab scan --repo C:\path\to\repo --loops 3 --profiles balanced,business,edge
```

This discovers common browser targets when no config exists, writes `.buglab/config.json`, runs the matrix, and rebuilds `.buglab/runs/index.html`.

Initialize BugLab in another repo:

```powershell
buglab init --repo C:\path\to\repo
```

Run every configured target/profile loop from `.buglab/config.json`:

```powershell
buglab matrix --repo C:\path\to\repo
```

Run one hunt:

```powershell
buglab run --repo C:\path\to\repo --target path\to\page.html --max-clicks 30
```

Run against a local dev server:

```powershell
buglab run --repo C:\path\to\repo --target http://127.0.0.1:3000 --profile business
```

Run loops and record data:

```powershell
buglab loops --repo C:\path\to\repo --target http://127.0.0.1:3000 --loops 9 --profiles balanced,business,edge
```

Build an index of standardized reports:

```powershell
buglab index --repo C:\path\to\repo
```

The index includes aggregate loop, matrix, sector, and repo-audit summaries above the per-run evidence reports.

List repair-ready case bundles from the latest repo audit:

```powershell
buglab cases --repo C:\path\to\repo
buglab cases --repo C:\path\to\repo --sector browser --format json
```

Build a data-first Pareto report over all normalized audit findings:

```powershell
buglab pareto --repo C:\path\to\repo
```

This writes `findings_pareto.csv`, `findings_pareto.json`, and `findings_pareto.html` under `.buglab\runs`. The HTML report includes Apache ECharts views for signal-family and sector-by-signal concentration, plus table fallbacks for CSV-first review.

Run the field swarm across sector fixture packs. In this repository, the default fields are browser/API, CLI/data, and repo-quality. Repo-quality currently covers docs/link integrity, unit tests, config/IaC, security/auth, and package health. In another repository, pass one or more custom `buglab.sector.v1` manifests:

```powershell
buglab swarm --repo . --loops 1 --profiles balanced
buglab swarm --repo C:\path\to\repo --manifest path\to\sector_manifest.json --repair
```

This writes `<name>_swarm_summary.csv`, `<name>_swarm_summary.json`, and `<name>_swarm_summary.html` under `.buglab\runs`. The report records field, sector, detection rate, expected-class recall, unique signal count, best profiles, and optional non-destructive repair verification for supported sectors.

Run swarm ablations when the question is which profile/team layout is strongest for the current bug-hunt domain:

```powershell
buglab ablate --repo . --loops 1 --field browser_api --field cli_data --profile-set balanced --profile-set edge --name swarm_ablation_smoke
buglab ablate --repo . --loops 1 --profile-set balanced --profile-set business --profile-set edge --profile-set balanced,business,edge
buglab ablate --repo . --manifest targets\sectors\unit_tests\manifest.json --profile-set balanced
```

This writes `<name>_ablation_summary.csv`, `<name>_ablation_summary.json`, and `<name>_ablation_summary.html`. The HTML report uses Apache ECharts and ranks variants by detection quality, expected-class recall, unique-signal yield, runtime cost, and Pareto frontier membership.

CI-style exit behavior:

```powershell
buglab hunt --repo C:\path\to\repo --exit-policy bugs
```

By default, `hunt` exits `0` even when it finds bug signals so exploratory R&D loops keep running. Use `--exit-policy bugs` to return `1` when any sector reports signals.

Default output:

```text
.buglab/runs/
  <run_id>/
    report_manifest.json
    report.html
    report.json
    bugs.md
    baseline.png
    action_*.png
  <loop_name>_loop_summary.csv
  <loop_name>_loop_summary.json
  <matrix_name>_<timestamp>_matrix_summary.csv
  <matrix_name>_<timestamp>_matrix_summary.json
  <sector_name>_sector_summary.csv/json
  <ablation_name>_ablation_summary.csv/json/html
  <audit_run_id>/repo_audit_rows.csv
  <audit_run_id>/repo_audit.json
  <audit_run_id>/findings.csv
  <audit_run_id>/findings.jsonl
  <audit_run_id>/cases/index.json
  findings_pareto.csv/json/html
  <swarm_name>_swarm_summary.csv/json/html
  <workflow_name>_<timestamp>_workflow.json
  doctor_<timestamp>.json
  index.html
```

## Python API

```python
from buglab import BugHuntConfig, audit_repo, bughunt_repo, build_pareto, bug_hunt, doctor_repo, init_project, list_cases, run_ablation, run_loops, run_matrix, run_swarm, scan_repo

workflow = bughunt_repo(repo=r"C:\path\to\repo", loops=1, profiles=["balanced"])
print(workflow["summary"])
print(workflow["workflow_path"])

audit = audit_repo(repo=r"C:\path\to\repo", loops=1, profiles=["balanced"])
print(audit["summary"])
print(audit["report_path"])

cases = list_cases(repo=r"C:\path\to\repo", run_id="latest", sector="browser")
print(cases["total_cases"])
print(cases["cases"][0]["case_path"])

pareto = build_pareto(repo=r"C:\path\to\repo")
print(pareto["html_path"])
print(pareto["summary"]["signals"][:3])

swarm = run_swarm(repo=r"C:\path\to\repo", fields=["browser_api", "cli_data"], repair=True)
print(swarm["summary"])
print(swarm["html_path"])

ablation = run_ablation(
    repo=r"C:\path\to\buglab",
    fields=["browser_api", "cli_data"],
    manifests=[r"targets\sectors\unit_tests\manifest.json"],
    profile_sets=["balanced", "edge"],
)
print(ablation["summary"]["best_quality_variant"])
print(ablation["html_path"])

scan = scan_repo(repo=r"C:\path\to\repo", loops=3, profiles=["balanced", "business", "edge"])
print(scan["summary"])
print(scan["index"]["index_path"])

init_project(repo=r"C:\path\to\repo")

matrix_result = run_matrix(repo=r"C:\path\to\repo")
print(matrix_result["csv_path"])

result = bug_hunt(BugHuntConfig(
    repo=r"C:\path\to\repo",
    target="dist/index.html",
    max_clicks=40,
    profile="business",
))

print(result.bug_candidate_count)
print(result.output_dir)

loop_result = run_loops(
    repo=r"C:\path\to\repo",
    target="http://127.0.0.1:3000",
    loops=6,
    profiles=["balanced", "business", "edge"],
)
print(loop_result["csv_path"])
```

## Profiles

| Profile | Purpose |
| --- | --- |
| balanced | Valid synthetic values and ordinary control exploration. |
| business | Business-like values for SaaS/ops workflows. |
| edge | Invalid, empty, or boundary values to expose validation paths. |

## Standard Outputs

Every run emits `buglab.report.v1`, documented in `docs/reporting_standard.md`.

`buglab hunt` emits an aggregate repo audit:

```text
.buglab/runs/
  <audit_run_id>/
    report_manifest.json
    report.html
    repo_audit_rows.csv
    repo_audit.json
    findings.csv
    findings.jsonl
    cases/
      index.json
      audit_*.md
      audit_*.json
```

The audit row schema is:

| Field | Meaning |
| --- | --- |
| sector | `browser`, `docs`, `tests`, or `config`. |
| runner | Tool adapter used for the check. |
| target | File, URL, command group, or target set. |
| status | `passed`, `failed`, or `skipped`. |
| signal_count | Number of normalized bug signals. |
| signals | JSON array of normalized signals. |
| command | Reproduction command when applicable. |
| elapsed_ms | Wall time for the sector check. |
| artifact | Linked aggregate artifact when applicable. |

The normalized findings exports are designed for dashboards, Pareto analysis, and CI ingestion. `findings.csv` stores one row per failed target with JSON-encoded `signals` and `reproduction_steps`; `findings.jsonl` stores the same records with `signals` and `reproduction_steps` as arrays. Failed findings also include `case_path` and `case_json_path` fields that point to markdown and JSON repro bundles under `cases\`.

Loop summaries record:

- loop number
- profile
- run id
- output directory
- controls discovered/exercised
- bug candidate count
- failure signal count
- raw failure signals as JSON
- elapsed milliseconds
- agent counts

These data files are the basis for continued ablation and Pareto analysis across business domains.

Portable project config: `docs/portable_project_config.md`.
