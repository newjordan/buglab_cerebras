# Blastoff Protocol

Use this when the challenge prompt, Gemma model, or hackathon token is released.

## Zero Minute Checklist

1. Paste the challenge statement into `docs/challenge_statement.md`.
2. Put the new token in `.env` as `CEREBRAS_API_KEY`.
3. Set the released model in `.env` as `CEREBRAS_MODEL`.
4. Run preflight:

```powershell
python scripts\blastoff.py
```

5. If preflight passes, start baseline ablations:

```powershell
python scripts\run_ablation.py --run-id A001
python scripts\run_ablation.py --run-id B001
python scripts\run_ablation.py --run-id C001
```

6. Then run the first frontier batch:

```powershell
python scripts\run_matrix.py --limit 6
```

## Verification Commands

Speed fixture browser metrics:

```powershell
python scripts\browser_verify.py --target targets\speed_fleet\bloated_dashboard.html --name speed_fixture_verify
```

Playthrough fixture task failure baseline:

```powershell
python scripts\browser_verify.py --target targets\playthrough_debug\buggy_dashboard.html --tasks targets\playthrough_debug\tasks.json --name playthrough_fixture_verify
```

Pareto summary:

```powershell
python scripts\score_runs.py
python scripts\build_pareto_report.py
```

Open `reports\pareto_dashboard.html` for the Apache ECharts dashboard.

## Science Rules

- Solo baselines run first.
- Do not compare swarm variants until the solo row exists.
- Every claimed improvement needs either a screenshot, browser task result, benchmark metric, or explicit failure count reduction.
- Every run batch ends with `python scripts\score_runs.py` and `python scripts\build_pareto_report.py`.
- Use Apache ECharts dashboards for charted evidence.
- Keep failed runs. Failed runs are data.
- Prefer the lowest-complexity topology that wins repeatedly.
- When a run looks good, repeat it once before building a product around it.
