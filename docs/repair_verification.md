# Repair Verification

BugLab repair verification runs a sector twice: first against the original fixtures, then against a repaired scratch copy under `.buglab/repair`. Original targets are not modified.

Current implemented strategy: `auto_sector_patch`.

For browser fixtures, the strategy injects a browser-side repair runtime:

- normalizes hidden/offscreen/overlay UI so controls can be reached
- clears stale error copy and bad storage state
- intercepts click, submit, and change handlers that would reintroduce known broken states
- writes visible success and loaded-state evidence for semantic checks
- appends collection items for load/refresh actions when the original page has no list/table target

For CLI/data fixtures, the strategy creates scratch copies of Python scripts and input data, rewrites commands to use scratch inputs/outputs, and applies conservative data-contract repairs for declared bug classes.

## Command

```powershell
buglab repair-sector --repo . --manifest targets\sectors\html_interaction\manifest.json --loops 1 --profiles balanced --name repair_auto_html --max-clicks 16
buglab repair-sector --repo . --manifest targets\sectors\api_workflows\manifest.json --loops 1 --profiles balanced --name repair_auto_api --max-clicks 12
buglab repair-sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --profiles balanced --name repair2_cli_data --max-clicks 8
```

Strict class-aware regression command:

```powershell
buglab repair-sector --repo . --manifest targets\sectors\html_interaction\manifest.json --loops 1 --profiles balanced --name class_repair_html --max-clicks 16
buglab repair-sector --repo . --manifest targets\sectors\api_workflows\manifest.json --loops 1 --profiles balanced --name class_repair_api --max-clicks 12
buglab repair-sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --profiles balanced --name class_repair_cli --max-clicks 8
```

## Latest Result

| Sector | Fixtures | Before signals | After signals | Fixed delta | Effectiveness | Fully cleared |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HTML interaction | 4 | 35 | 0 | 35 | 1.0 | 4 |
| API workflows | 4 | 17 | 0 | 17 | 1.0 | 4 |
| CLI/data | 4 | 13 | 0 | 13 | 1.0 | 4 |

Artifacts:

- HTML repair summary: `.buglab/runs/class_repair_html_html_interaction_repair_20260628_145846/repair_summary.csv`
- API transfer summary: `.buglab/runs/class_repair_api_api_workflows_repair_20260628_145831/repair_summary.csv`
- CLI/data repair summary: `.buglab/runs/class_repair_cli_cli_data_repair_20260628_145810/repair_summary.csv`
- Snapshot table: `data/repair_pareto_snapshot.csv`

## Current Boundary

The repair loop currently covers browser/API fixtures and the CLI/data fixture pack. New command sectors should get explicit repair templates or a safer source-to-source patcher before being counted as repair-capable.
