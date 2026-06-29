# Portable Project Config

BugLab can be attached to another repository with a local `.buglab/config.json`. The config records target pages, loop count, profiles, max click budget, and output location.

Generated configs, reports, screenshots, summaries, and case bundles stay inside the target repo's ignored `.buglab/` directory.

## Bootstrap

Fast path:

```powershell
buglab bughunt --repo C:\path\to\repo --loops 1 --profiles balanced
```

`bughunt` runs the complete attach-and-audit workflow without requiring project configuration: preflight doctor, multi-sector repo audit, case-bundle listing, Pareto generation, and HTML index rebuild.

Browser-matrix path:

```powershell
buglab scan --repo C:\path\to\repo --loops 3 --profiles balanced,business,edge
```

`scan` creates or reuses `.buglab/config.json`, runs the configured matrix, writes CSV/JSON summaries, emits standardized per-run reports, and rebuilds the HTML index.

Initialize explicitly:

```powershell
buglab init --repo C:\path\to\repo
buglab init --repo C:\path\to\repo --target dist\index.html --target http://127.0.0.1:3000 --force
```

If no target is supplied, BugLab looks for common HTML entry points such as `index.html`, `dist/index.html`, `build/index.html`, `public/index.html`, and `docs/index.html`.

## Matrix Run

```powershell
buglab matrix --repo C:\path\to\repo
buglab matrix --repo C:\path\to\repo --target-id index --loops 6 --profiles balanced,business,edge
```

## Config Shape

```json
{
  "schema_version": "buglab.project.v1",
  "output": ".buglab/runs",
  "default_loops": 3,
  "default_profiles": ["balanced", "business", "edge"],
  "max_clicks": 30,
  "targets": [
    {
      "id": "index",
      "target": "index.html",
      "kind": "browser",
      "mobile": false
    }
  ]
}
```

## Clean Output Contract

BugLab does not require committed report history. A fresh run writes:

- `.buglab/config.json`
- `.buglab/runs/index.html`
- `.buglab/runs/<run_id>/report.html`
- `.buglab/runs/<run_id>/report.json`
- `.buglab/runs/<run_id>/cases/index.json`
- `.buglab/runs/<run_id>/findings.csv`
- `.buglab/runs/<run_id>/findings.jsonl`

These paths are operational artifacts, not source artifacts.
