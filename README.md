# BugLab

Local bug-hunting toolkit. Point it at a project folder and it writes a report from deterministic checks: browser interaction when Playwright Chromium is installed, Markdown links, Python unittest discovery, and configuration/text probes. A small web console runs those hunts and can call Cerebras for an optional chat request.

Hunts do not download model weights. Model calls happen only when something invokes the chat API with `CEREBRAS_API_KEY` set.

## Requirements

- Python 3.11 or newer
- Optional, for browser hunts: Playwright's Chromium build, installed with `python -m playwright install chromium`
- Optional, for `POST /api/chat`: a Cerebras API key in an untracked `.env` file

## Setup

From a checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

On Windows PowerShell, create the virtualenv the same way and activate it with `.\.venv\Scripts\Activate.ps1`. Copy the example env file with `Copy-Item .env.example .env`.

`.env` is listed in `.gitignore`. The example file has empty key fields and a default model name of `gpt-oss-120b`.

Runtime dependencies also live in `requirements.txt` (`openai`, `python-dotenv`, `httpx`, `playwright`). The install above is the supported setup because it installs the `buglab`, `bughunt`, and `buglab-server` commands and the `pytest` extra. `requirements.txt` alone does not install the test extra.

## Web console

```bash
python -m app.server
```

`buglab-server` is the same entry point after installation. The process listens on `127.0.0.1:8765` unless `BUGLAB_HOST` or `BUGLAB_PORT` is set.

Open `http://127.0.0.1:8765/`.

- **Find Bugs** asks for a local project path, then runs the full workflow (doctor, multi-sector audit, case index, Pareto summary, report index).
- **Describe Issue** sends the note you type. For text-like attachments up to 48,000 bytes, the page also sends a clipped excerpt. Paths in that text that exist inside the selected project and end in `.html` or `.htm` become the browser targets. Docs, tests, and config checks still cover the project.
- **Find + Fix** runs the same hunt, then a repair pass. If the selected project contains all three bundled sector manifests (`targets/sectors/html_interaction/manifest.json`, `targets/sectors/api_workflows/manifest.json`, and `targets/sectors/cli_data/manifest.json`), repair runs through those manifests. Otherwise BugLab writes a fix queue and may patch HTML files in the selected project with `apply_safe_interaction_patch`. Use a copy of the tree when you need the sources left unchanged. A fix is marked passed only when a later verification sweep reports fewer signals.

The page shows a one-line summary on stderr-equivalent status text in the window, category charts when Apache ECharts loads, and an agent handoff you can copy. Token speed shown during the animation is labeled as an estimate. The report omits tokens per second when the hunt summary has no elapsed time.

`POST /api/chat` is separate from Find Bugs. It calls the configured Cerebras base URL with the server's API key and returns the model text. It is not used by the hunt buttons.

## CLI

JSON results go to stdout. A one-line summary goes to stderr, except `doctor` and `cases`, which print text to stdout. `buglab --help` lists every command.

```bash
buglab doctor --repo . --skip-browser
buglab hunt --repo . --no-browser
buglab bughunt --repo . --no-browser
buglab cases --repo .
buglab pareto --repo .
buglab tui --repo . --frames 1 --no-clear
```

`hunt` and `audit` are the same multi-sector audit. Useful flags:

- `--no-browser`, `--no-docs`, `--no-tests`, `--no-config` skip a sector
- `--exit-policy bugs` returns a non-zero status when any signal is recorded. The default `warn` prints the report and returns 0
- `--target path/or/url` can be repeated for browser targets

Other commands:

| Command | What it does |
| --- | --- |
| `init` | Writes `.buglab/config.json`. With no `--target`, HTML files found in the repo are stored. An empty repo gets an empty target list. |
| `run` | One Playwright hunt against `--target`. Exits non-zero when bug candidates are recorded. |
| `loops` | Repeats `run` across profiles. |
| `matrix` | Runs the targets in `.buglab/config.json`. |
| `scan` | Initializes config when needed, then runs the matrix. |
| `bughunt` | Doctor, audit, case list, Pareto file, and report index. `bughunt` with no subcommand is the installed shortcut for this. |
| `doctor` | Checks that the repo and output directory are usable, counts docs/tests/config files, and optionally launches Chromium. |
| `cases` | Lists finding bundles from the latest audit, or from `--run`. |
| `pareto` | Ranks findings already written under the output directory. |
| `calibrate` | Scores findings against a truth ledger JSON file. |
| `benchmark-bugsinpy` | Plans or runs paired BugsInPy checkouts. It needs a local BugsInPy tree passed with `--bugsinpy-root`. |
| `quality` | Runs local gates such as `git diff --check` and `py_compile` and writes a quality report. |
| `medic` | Reads a quality report and recommends a next step. |
| `tui` | Draws a braille dashboard. Line counts come from the files it reads. The moving token rate is labeled estimated. |
| `swarm` | Runs the browser/API, CLI/data, and repo-quality field manifests. |
| `ablate` | Compares swarm profile variants. |
| `index` | Rebuilds `.buglab/runs/index.html` from report manifests. |
| `sector` | Scores one sector manifest. |
| `repair-sector` | Runs find, repair, and verify for a supported manifest. |

Browser commands need Chromium. `doctor` tells you to run `python -m playwright install chromium` when launch fails.

Generated reports, configs, and case files go under `.buglab/` relative to the selected repo unless you pass an absolute `--output`. That directory is gitignored.

## What an audit checks

- **Browser.** Playwright opens each existing HTML target or URL, records console and request failures, and flags disabled actions, placeholder links, layout clipping, and a few submit/refresh state mismatches.
- **Docs.** Local Markdown links, heading anchors, and placeholder text such as `TODO` outside fenced code.
- **Tests.** `python -m unittest discover` plus a per-file run, using argument lists rather than a shell. Static notes cover missing tests, missing assertions, and skip decorators.
- **Config.** JSON parse errors, `.env` example key drift, debug flags, short secret-like values, unpinned `:latest` images, and floating GitHub Actions refs.

`buglab hunt` on this repository skips `targets/sectors/` on purpose, so the bundled broken fixtures are not reported as defects in BugLab itself. Run `buglab sector --manifest targets/sectors/<sector>/manifest.json` when you want those fixtures scored.

## Tests

```bash
python -m pytest
```

GitHub Actions workflow `.github/workflows/ci.yml` runs that suite on Python 3.11, 3.12, and 3.13. It installs `.[dev]` and does not download Chromium or model weights. The suite in this tree is 23 tests; a local `python -m pytest` run passed all 23.

## Fixtures and secrets

`targets/sectors/` contains intentional bugs for sector scoring, including `targets/sectors/config_iac/fixtures/.env`. That file is a synthetic contract fixture (`API_TOKEN=short`, `DEBUG=true`). It is not a credential. Do not put real keys in the tree. Keep them in `.env`.

## License

This repository does not include a project license file. That is unchanged. Vendored Apache ECharts in `app/static/vendor/echarts.min.js` stays under the Apache License 2.0. The in-app info dialog credits ECharts, Ponytail, and the DELI AutoResearch framework.

## Attributions

- Cerebras and Google Gemma: optional inference platform and model family for the chat API.
- Apache ECharts: charting in the web console and generated HTML reports.
- Ponytail by Dietrich Gebert: repair and find-loop inspiration.
- DELI / AutoResearch by Victor Chen: research-loop inspiration.
- BugsInPy: optional benchmark input for `benchmark-bugsinpy`.

Project names and trademarks belong to their respective owners. Attribution does not imply endorsement.
