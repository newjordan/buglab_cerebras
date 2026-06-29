# Reporting Standard

All bug-lab tools should emit the same artifacts in their run folder:

- `report_manifest.json`
- `report.html`
- raw tool-specific JSON, when useful
- screenshots or other evidence files

## Manifest Contract

The manifest schema version is `buglab.report.v1`.

Machine-readable schema: `config/report_schema.v1.json`.

Required top-level fields:

| Field | Purpose |
| --- | --- |
| schema_version | Versioned contract for readers and dashboards. |
| run_id | Stable run folder identifier. |
| tool | Tool that produced the run. |
| target | URL, file, or system under test. |
| status | `passed`, `failed`, or `needs_review`. |
| metrics | Named numeric/text measurements with units. |
| evidence | Screenshots, logs, traces, states, and event captures. |
| findings | Reproducible issues linked to evidence IDs. |
| artifacts | Machine-readable links to files created by the run. |

## Evidence Record

Evidence records are typed and linkable:

| Field | Purpose |
| --- | --- |
| id | Stable evidence identifier inside the run. |
| kind | `screenshot`, `log`, `state`, `trace`, `json`, or similar. |
| path | Relative path to the artifact. |
| condition | State under which evidence was captured. |
| selector | DOM selector or target object when applicable. |
| action | User/tool action that created the evidence. |
| viewport | Browser dimensions for screenshot evidence. |
| metadata | Tool-specific structured details. |

## Finding Record

Findings are the unit the product should optimize:

- severity
- status
- category
- selector
- signals
- evidence_ids
- reproduction_steps
- expected
- actual
- fix_hypothesis

## Commands

```powershell
python scripts\generic_bug_hunt.py --target targets\playthrough_debug\buggy_dashboard.html --name generic_buggy_standard
python scripts\browser_verify.py --target targets\playthrough_debug\fixed_dashboard.html --tasks targets\playthrough_debug\tasks.json --name browser_verify_standard
python scripts\build_report_index.py
buglab pareto --repo .
buglab swarm --repo . --loops 1 --profiles balanced
buglab ablate --repo . --loops 1 --field browser_api --field cli_data --profile-set balanced --profile-set edge
buglab index --repo .
```

The legacy script index is written to `reports\run_index.html`.

The installable `buglab index` command writes `.buglab\runs\index.html`. It lists both standardized per-run manifests and aggregate R&D summaries:

- `*_loop_summary.json`
- `*_matrix_summary.json`
- `*_sector_summary.json`
- `*_swarm_summary.json`
- `*_ablation_summary.json`
- `*_workflow.json`
- `doctor_*.json`
- `<audit_run>\repo_audit.json`
- `<audit_run>\findings.csv`
- `<audit_run>\findings.jsonl`
- `<audit_run>\cases\index.json`
- `findings_pareto.csv/json/html`

Aggregate rows link to the JSON artifact and matching CSV artifact when present, so Pareto and ablation reviews can start from one local HTML file.

Repo audit runs also emit normalized finding exports. `findings.csv` is spreadsheet-friendly; `findings.jsonl` is ingestion-friendly and keeps list fields such as `signals` and `reproduction_steps` as arrays.
Each failed audit target also gets a case bundle under `cases\` with a markdown repro file and JSON payload for automated repair loops.
`buglab pareto` aggregates every audit `findings.jsonl` into ranked sectors, severities, runs, signal families, and sector-signal pairs. The generated HTML uses Apache ECharts when available and keeps table output for offline review.
`buglab swarm` aggregates field-level sector runs into `<name>_swarm_summary.csv/json/html`, preserving the field, sector, detection rate, expected-class recall, unique signal count, best profile ranking, and optional repair-verification outcome.
`buglab ablate` runs swarm technique variants and emits `<name>_ablation_summary.csv/json/html`, preserving variant profile sets, field, quality score, efficiency score, and Pareto frontier membership.
`buglab doctor` emits `doctor_<timestamp>.json` so install/runtime readiness can be inspected alongside hunt, sector, swarm, and Pareto evidence.
`buglab bughunt` emits `<name>_<timestamp>_workflow.json`, linking doctor, audit, cases, Pareto, and index artifacts for a single attach-and-run workflow.
