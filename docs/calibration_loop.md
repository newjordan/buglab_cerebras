# BugLab Calibration Loop

BugLab separates activity from accuracy. Tokens, agents, LOC, and elapsed time are cost telemetry. Accuracy comes from an oracle-scored benchmark or a verified replay.

## Loop

```text
Run hunt
-> write evidence packets
-> score only oracle-backed cases
-> quarantine unverified suspected findings
-> inspect false-positive signal families
-> adjust detector policy or prompts
-> rerun the same benchmark slice
```

## Local Calibration

```powershell
python -m buglab.cli calibrate --repo . --output .buglab\portfolio-runs --ledger .buglab\calibration\truth_ledger.json
```

Outputs:

- `.buglab\portfolio-runs\calibration_report.json`
- `.buglab\portfolio-runs\calibration_report.csv`
- `.buglab\portfolio-runs\calibration_report.html`

The ledger is intentionally generated locally. It is not shipped as a preloaded prior.

## External Ground Truth: BugsInPy

BugsInPy is the preferred calibration path when ground truth is available. BugLab treats each case as a paired experiment:

- checkout `version=0` as the known buggy positive case
- checkout `version=1` as the known fixed negative case
- run the BugsInPy test oracle on both versions
- run BugLab's audit on both versions
- score true positives, false positives, false negatives, true negatives, precision, recall, and F1

Dry-run first:

```powershell
python -m buglab.cli benchmark-bugsinpy --bugsinpy-root C:\path\to\BugsInPy --case scrapy:1 --dry-run
```

Run a paired benchmark:

```powershell
python -m buglab.cli benchmark-bugsinpy --bugsinpy-root C:\path\to\BugsInPy --case scrapy:1 --case pandas:1 --timeout-seconds 240
```

Outputs:

- `.buglab\benchmarks\bugsinpy\<run>\bugsinpy_benchmark.json`
- `.buglab\benchmarks\bugsinpy\<run>\bugsinpy_benchmark.csv`
- `.buglab\benchmarks\bugsinpy\<run>\bugsinpy_benchmark.html`

## Submission Package

Build a fresh package from generated local evidence:

```powershell
python scripts\build_submission_package.py --external-root .buglab\runs
```

Freeze a local checkpoint:

```powershell
python scripts\freeze_submission.py --require-live
```

Outputs are ignored by git:

- `.buglab\submission\submission_package.md`
- `.buglab\submission\submission_results.json`
- `.buglab\submission\submission_freeze.json`

A clean clone has no historical package. The package exists only after the user runs BugLab or an eval pipeline.
