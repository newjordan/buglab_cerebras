# Config/IaC Sector

This sector covers dependency-free configuration and infrastructure-as-code defects that show up before application code runs: malformed JSON, environment contract drift, missing referenced files, unpinned images/actions, and risky compose/workflow defaults.

The generic repo audit scans JSON, env examples/templates, Compose/workflow/Docker-style YAML, Dockerfiles, TOML, INI, and CFG files without requiring Docker or YAML packages. It emits normalized `config` rows for parse errors, env contract drift, risky env values, floating images/actions/runners, missing env files, missing healthchecks, privileged host ports, and short literal secrets.

Manifest: `targets/sectors/config_iac/manifest.json`

| Fixture | Target | Expected classes | Minimum |
| --- | --- | --- | ---: |
| Broken JSON config | `targets/sectors/config_iac/fixtures/app_config.bad.json` | bad exit code, schema mismatch | 2 |
| Env/example mismatch | `targets/sectors/config_iac/fixtures/.env` | bad exit code, schema mismatch | 2 |
| Compose/workflow misconfig | `targets/sectors/config_iac/fixtures/compose-workflow.yml` | bad exit code, schema mismatch, missing file handling | 3 |

Run:

```powershell
python -m buglab.cli sector --repo . --manifest targets\sectors\config_iac\manifest.json --loops 1 --name config_iac_probe
```

Each fixture uses a Python stdlib probe under `targets/sectors/config_iac/probes/`, so the pack does not need Docker, YAML libraries, or external package installation.

Repo audit smoke:

```powershell
python -m buglab.cli hunt --repo . --no-browser --no-docs --loops 1 --profiles balanced --max-clicks 1 --name tests_config_signal_smoke
```

Expected generic audit coverage on these fixtures: JSON parse failure, env key drift, `DEBUG=true`, short placeholder secrets, unpinned `:latest` images, floating `ubuntu-latest`, missing healthchecks, and privileged host port `80`.
