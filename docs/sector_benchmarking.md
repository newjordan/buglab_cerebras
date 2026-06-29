# Sector Benchmarking

BugLab sectors are small fixture packs with explicit expected bug classes. They let the bug-hunting swarm optimize technique against ground truth instead of only counting raw findings.

## Manifest Shape

```json
{
  "schema_version": "buglab.sector.v1",
  "sector": "foundation_html",
  "name": "Foundation HTML Interaction",
  "runner": "browser",
  "fixtures": [
    {
      "id": "broken_controls",
      "target": "targets/sectors/foundation_html/broken_controls.html",
      "expected_bug_classes": ["pageerror", "requestfailed"],
      "expected_min_bugs": 4
    }
  ]
}
```

Browser fixtures run through the Playwright bug hunter and score whether each loop found at least `expected_min_bugs`. Command fixtures run a declared shell command and score exit/output/error expectations.

## Baseline Run

```powershell
buglab sector --repo . --manifest targets\sectors\foundation_html\manifest.json --loops 3 --name foundation_html
buglab index --repo .
```

The sector summary records fixture-level detection rate, average coverage score, profile rankings, bug counts, elapsed time, and links to standardized per-run reports.

## Optimization Target

The current Pareto question is not "which run finds the most issues." It is:

- maximum expected-fixture detection rate
- minimum duplicate/noise findings
- minimum elapsed time per fixture
- best cross-sector transfer without sector-specific overfitting
- clearest evidence package for reproduction and fix verification
