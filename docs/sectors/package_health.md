# Package Health Sector

This sector covers dependency and build-health defects that appear in generic business repositories before application logic is exercised: floating package ranges, missing lockfiles, runtime engine drift, deprecated package scripts, risky lifecycle hooks, stale Python runtime support, and CI build drift.

Manifest: `targets/sectors/package_health/manifest.json`

## Fixtures

| Fixture | Target | Expected classes | Minimum |
| --- | --- | --- | ---: |
| Node dependency drift | `targets/sectors/package_health/fixtures/node_dependency_drift/package.json` | unpinned dependency, missing lockfile | 2 |
| Node script risk | `targets/sectors/package_health/fixtures/node_script_risk/package.json` | engine mismatch, deprecated script, insecure lifecycle script | 3 |
| Python requires stale | `targets/sectors/package_health/fixtures/python_requires_stale/pyproject.toml` | stale Python requires, unpinned dependency, missing lockfile | 3 |
| CI build drift | `targets/sectors/package_health/fixtures/ci_build_drift/.github/workflows/build.yml` | unpinned dependency, deprecated script, engine mismatch | 3 |

## Signals

The fixture pack uses one stdlib probe, `targets/sectors/package_health/probes/check_package_health.py`, through the existing command runner. The probe inspects local fixture files only; it does not install packages, access registries, run package managers, or require Node.

Expected signal classes:

- `unpinned_dependency`: floating npm ranges such as `^`, `~`, `latest`, unpinned Python dependencies, or unpinned workflow action refs.
- `missing_lockfile`: dependencies exist without a recognized npm, pnpm, yarn, bun, Poetry, Pipenv, uv, or requirements lockfile.
- `engine_mismatch`: package or workflow Node versions disagree with `.nvmrc`.
- `deprecated_script`: legacy npm lifecycle/build patterns such as `prepublish` or `npm install` in CI.
- `insecure_lifecycle_script`: install-time scripts that fetch or pipe remote shell code.
- `stale_python_requires`: `requires-python` allows old Python runtimes no longer suitable for many maintained business services.

## Run

```powershell
python -m buglab sector --repo . --manifest targets\sectors\package_health\manifest.json --loops 1 --name package_health_verify
```

The command should produce deterministic command-runner rows for all four fixtures without network access or external dependencies.
