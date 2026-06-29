# Generic Bug Hunter R&D Track

This is the product spine.

The system accepts arbitrary interactive software, plays it like a synthetic QA team, takes screenshots, captures runtime failures, routes evidence through specialist agents, and produces reproducible bug reports plus fix verification.

## Agent Layout

| Agent | Evidence Owned |
| --- | --- |
| Explorer | Control discovery, click paths, URL changes. |
| Runtime Sentinel | Console errors, page errors, request failures. |
| Form Agent | Input filling, submit paths, validation state. |
| Visual Inspector | Screenshots, overflow, blank states, broken layout. |
| Reproduction Writer | Minimal steps, selectors, expected/actual state. |
| Fixer | Targeted patch hypothesis. |
| Regression Verifier | Same crawl before/after fix, bug-count delta. |

## Current Local Commands

```powershell
python scripts\generic_bug_hunt.py --target targets\playthrough_debug\buggy_dashboard.html --name bughunt_buggy
python scripts\generic_bug_hunt.py --target targets\playthrough_debug\fixed_dashboard.html --name bughunt_fixed
python scripts\replicate_browser_benchmarks.py --repeats 10
python scripts\build_pareto_report.py
```

## Evidence Contract

Every bug candidate must include:

- selector
- action type
- screenshot path
- failure signal
- responsible agent labels
- reproduction state
- before/after verification when a fix exists

## Pareto Question

Which org layout finds the most verified bugs per minute with the fewest false positives and the simplest fix loop?

