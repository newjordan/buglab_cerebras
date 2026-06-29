# Org Builder Track

The org builder is the intro layer for the system.

It asks:

- What is the target?
- Which team layouts should compete?
- Which metrics decide the winner?
- Which team is on the Pareto frontier?
- What is the next smallest ablation?

## DELI Flow

Define:

- target class
- candidate org layouts
- metrics
- control baseline

Execute:

- run baseline
- run candidate layouts
- capture artifacts
- update ablation table

Look:

- chart score versus time
- chart score versus worker count
- label failures and regressions
- identify dominated layouts

Iterate:

- remove dominated layouts
- split ambiguous winners into narrower tests
- repeat winning layout once before productizing

## Science-Only Output Rule

Every recommendation must include:

- table row IDs
- metric movement
- chart reference
- failure/regression notes
- next ablation

No product story until the data identifies a repeatable winner.

## Charting

Use Apache ECharts for generated dashboards.

Current generated report:

```powershell
python scripts\build_pareto_report.py
```

Output:

- `reports\pareto_dashboard.html`

Required chart views:

- score versus total seconds
- score versus worker count
- average score by topology
- failures and regressions by run

Any recommendation without a chart or table reference is incomplete.
