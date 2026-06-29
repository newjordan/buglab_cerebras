# Ablation Table Schema

Generated ablation tables are written under `.buglab/` during local runs and are not committed.

## Score Conventions

Use 0-5 when subjective:

- 0: no meaningful output
- 1: runs but mostly wrong
- 2: partial and brittle
- 3: acceptable prototype
- 4: strong demo-quality result
- 5: polished and robust

Use concrete units when objective:

- latency_ms
- total_seconds
- benchmark_before
- benchmark_after
- pass_rate_pct
- failure_count
- regression_count

## Required Fields

- run_id: stable identifier, for example `A001`.
- timestamp_local: local time for the run.
- track: `visual_to_site`, `speed_fleet`, or `playthrough_debug`.
- target_name: short target label.
- model: model ID used.
- topology: solo, manager_specialist, tournament, critic_loop, frontier_sweep.
- worker_count: total active workers.
- loop_count: total DELI iterations.
- verifier_stack: checks used, separated by `+`.
- research_mode: none, single_researcher, researcher_judge.
- memory_mode: none, run_notes, failure_log.
- repair_style: none, broad_rewrite, targeted_patch, verifier_guided_patch.
- start_score: score before loops.
- final_score: score after loops.
- latency_ms: model/API latency for core generation, if captured.
- total_seconds: wall-clock run time.
- pass_rate_pct: task pass rate when relevant.
- failure_count: unresolved failures after final loop.
- regression_count: new failures introduced.
- pareto_keep: yes/no/maybe.
- notes: short plain-language observation.

## Early Run Plan

1. Establish solo baselines for all three tracks.
2. Test critic loop with 2 and 4 loops.
3. Test manager + specialists with 3 and 5 workers.
4. Test tournament only where output variance is high.
5. Compare against solo on score improvement per minute.

## Live Swarm Ablations

Use `buglab ablate` when the target is the current bug-hunting network itself rather than a one-off demo artifact.

```powershell
buglab ablate --repo . --loops 1 --field browser_api --field cli_data --profile-set balanced --profile-set edge --name swarm_ablation_smoke
buglab ablate --repo . --manifest targets\sectors\unit_tests\manifest.json --profile-set balanced --name unit_manifest_ablation
```

Outputs:

- `.buglab/runs/<name>_ablation_summary.csv`
- `.buglab/runs/<name>_ablation_summary.json`
- `.buglab/runs/<name>_ablation_summary.html`

The generated rows are the live technique ledger:

- variant_id
- field
- profiles
- repeat
- loops
- repair
- status
- sectors
- fixtures
- runs
- passed_sectors
- sector_pass_rate
- avg_expected_class_recall
- total_unique_signals
- signal_density
- repair_attempts
- repair_pass_rate
- elapsed_ms
- quality_score
- efficiency_score
- pareto_keep
- csv_path
- json_path
- html_path

`quality_score` weights expected bug coverage, class recall, unique signal density, and repair verification when enabled. `efficiency_score` divides quality by elapsed seconds. `pareto_keep` marks variants that are not dominated by another variant with equal or better quality/recall/signal yield and lower runtime.
