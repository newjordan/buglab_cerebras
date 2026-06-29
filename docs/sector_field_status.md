# Sector Field Status

Current goal: isolate bug-hunting techniques that transfer across software fields, while preserving per-sector evidence and a comparable Pareto table.

## Implemented Sectors

| Sector | Fixtures | Runner | Latest detection | Technique notes |
| --- | ---: | --- | ---: | --- |
| HTML interaction | 4 | Browser/Playwright | 1.0 | Strict class-aware run: 35 raw signals, 22 unique signals, 0.938 expected-class recall. Runtime request-failure specificity is the current detector gap. |
| API workflows | 4 | Browser/Playwright | 1.0 | Strict class-aware run: 17 raw signals, 14 unique signals, 1.0 expected-class recall after HTTP/status/storage synonym matching. |
| CLI/data pipelines | 4 | Command/artifact probe | 1.0 | Strict class-aware run: 13 raw signals, 13 unique signals, 1.0 expected-class recall across exit, file, CSV, schema, row-loss, timestamp, and join failures. |
| Docs/link integrity | 3 | Markdown docs probe | 1.0 | Strict class-aware run: 9 raw signals, 9 unique signals, 1.0 expected-class recall across dead links, missing anchors/assets, placeholders, and required release terms. |
| Unit tests | 3 | Test command probe | 1.0 | Strict class-aware run: 9 raw signals, 9 unique signals, 1.0 expected-class recall across failing assertions, exceptions, skipped critical tests, contract mismatches, and missing coverage. |
| Config/IaC | 3 | Command/config probe | 1.0 | Strict class-aware run: 10 raw signals, 10 unique signals, 1.0 expected-class recall across malformed JSON, env drift, missing references, and risky infra defaults. |
| Security/auth | 4 | Command/static probe | 1.0 | Strict class-aware run: 8 raw signals, 8 unique signals, 1.0 expected-class recall across hardcoded secrets, permissive CORS, insecure cookies, weak JWT validation, debug auth bypasses, and missing rate limits. |
| Package health | 4 | Command/static probe | 1.0 | Strict class-aware run: 15 raw signals, 15 unique signals, 1.0 expected-class recall across dependency drift, missing lockfiles, engine mismatch, deprecated scripts, lifecycle risk, and stale Python runtime constraints. |
| Foundation HTML | 1 | Browser/Playwright | 1.0 | Dry calibration fixture for page-level layout scanning and report schema. |

## Foundation Modules

- `buglab.hunter`: browser crawler, screenshots, page/runtime events, semantic state checks, layout scanning, storage persistence checks, standardized reports.
- `buglab.sectors`: manifest-driven sector runner, loop execution, expected-coverage scoring, expected-class recall, duplicate-aware unique signal scoring, browser/command/docs/tests adapters, aggregate sector reports.
- `buglab.repair`: non-destructive repair-and-verify runner for browser/API fixtures and CLI/data Python fixtures, with before/after scoring and standardized repair reports.
- `buglab.reporting`: shared `buglab.report.v1` manifest, evidence, findings, metrics, and HTML report rendering.
- `buglab.audit`: one-command repo audit across browser, docs, tests, and config sectors with a standardized aggregate report.
- `buglab.cli`: installable commands: `hunt`, `audit`, `run`, `loops`, `sector`, `repair-sector`, and `index`.

## Current Pareto

The current knee is not a single swarm persona. It is a field-aware runner:

- Browser fields: `balanced` and `business` tie on detection; use `balanced` first because it has no observed coverage loss and keeps the profile surface smaller.
- API/workflow pages: use browser crawl plus signal-aware scoring and storage checks.
- CLI/data: do not use screenshots. Use command probes plus generated-artifact inspection.
- Docs/release content: use deterministic markdown link/anchor/image/placeholder probes.
- Unit tests: use deterministic test command probes plus assertion/error/skip/coverage parsing.
- Config/IaC: use deterministic stdlib command probes for malformed config, env contract drift, missing references, and risky deployment defaults.
- Security/auth: use deterministic static probes for auth-sensitive risk classes that should block release before runtime testing.
- Package health: use deterministic static probes for dependency/build hygiene without registry access, package installs, or runtime side effects.

Snapshot table: `data/sector_pareto_snapshot.csv`.

Strict class-aware snapshot:

| Sector | Raw signals | Unique signals | Expected-class recall | Latest artifact |
| --- | ---: | ---: | ---: | --- |
| HTML interaction | 35 | 22 | 0.938 | `.buglab/runs/class_score_html2_html_interaction_sector_summary.csv` |
| API workflows | 17 | 14 | 1.0 | `.buglab/runs/class_score_api2_api_workflows_sector_summary.csv` |
| CLI/data | 13 | 13 | 1.0 | `.buglab/runs/class_score_cli_cli_data_sector_summary.csv` |
| Docs/link integrity | 9 | 9 | 1.0 | `.buglab/runs/docs_link_check_docs_link_integrity_sector_summary.csv` |
| Unit tests | 9 | 9 | 1.0 | `.buglab/runs/unit_test_check2_unit_tests_sector_summary.csv` |
| Config/IaC | 10 | 10 | 1.0 | `.buglab/runs/config_iac_verify_config_iac_sector_summary.csv` |
| Security/auth | 8 | 8 | 1.0 | `.buglab/runs/security_auth_verify2_security_auth_sector_summary.csv` |
| Package health | 15 | 15 | 1.0 | `.buglab/runs/package_health_verify2_package_health_sector_summary.csv` |

Latest promoted repo-quality field run:

| Command | Sectors | Fixtures | Unique signals | Expected-class recall | Report |
| --- | ---: | ---: | ---: | ---: | --- |
| `python -m buglab swarm --repo . --field repo_quality --loops 1 --profiles balanced --name repo_quality_with_new_sectors --no-index` | 5 | 17 | 51 | 1.0 | `.buglab/runs/repo_quality_with_new_sectors_swarm_summary.html` |

Latest repo audit smoke:

| Command | Targets | Failed targets | Signals | Report |
| --- | ---: | ---: | ---: | --- |
| `buglab audit --repo . --no-browser --loops 1 --profiles balanced --name audit_smoke --no-index` | 161 | 6 | 11 | `.buglab/runs/audit_smoke_20260628_152206/report.html` |

Repair snapshot: `data/repair_pareto_snapshot.csv`.

Run index: `.buglab/runs/index.html`.

## Repair Verification

Repair is now implemented and verified across browser/API and CLI/data sectors. The current `auto_sector_patch` strategy patches scratch copies only, then reruns the same sector oracle.

Latest result:

| Sector | Strategy | Before signals | After signals | Effectiveness | Fully cleared |
| --- | --- | ---: | ---: | ---: | ---: |
| HTML interaction | `auto_sector_patch` | 35 | 0 | 1.0 | 4/4 |
| API workflows | `auto_sector_patch` | 17 | 0 | 1.0 | 4/4 |
| CLI/data | `auto_sector_patch` | 13 | 0 | 1.0 | 4/4 |

## Next Isolation Targets

1. Add dynamic rediscovery and route preflight for HTML so request-failure classes are detected directly instead of through secondary browser errors.
2. Add API-specific fetch/XHR instrumentation and storage value diffs, not just console text and storage key counts.
3. Add CLI/data mutation probes: shuffled rows, missing optional fields, malformed CSV, unknown join keys, and per-input missing-file probes.
4. Add business metadata to repo-audit rows so runs can be grouped by product workflow and risk tag.
5. Generalize command/docs/tests/config repair beyond fixture templates with a safer source-to-source patch plan.
