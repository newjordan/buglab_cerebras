# Repo Quality Field Notes

## Field Agent C - 2026-06-28

Owned sectors checked:

- `targets/sectors/docs_link_integrity`
- `targets/sectors/unit_tests`
- `targets/sectors/config_iac`

Smoke results:

| Sector | Command | Result |
| --- | --- | --- |
| Docs/link integrity | `python -m buglab.cli sector --repo . --manifest targets\sectors\docs_link_integrity\manifest.json --loops 1 --name field_c_docs_link` | Passed sector coverage: 3/3 fixtures detected, 9 unique signals, 1.0 expected-class recall |
| Unit tests | `python -m buglab.cli sector --repo . --manifest targets\sectors\unit_tests\manifest.json --loops 1 --name field_c_unit_tests` | Passed sector coverage: 3/3 fixtures detected, 9 unique signals, 1.0 expected-class recall |
| Config/IaC | `python -m buglab.cli sector --repo . --manifest targets\sectors\config_iac\manifest.json --loops 1 --name field_c_config_iac` | Passed sector coverage: 3/3 fixtures detected, 10 unique signals, 1.0 expected-class recall |

Fixture probes matched the intended failures:

- `test_billing_rules.py`: 1 assertion failure and 1 skipped test.
- `test_inventory_contract.py`: 1 `KeyError` test error.
- `test_authorization_coverage.py`: 1 assertion failure and coverage shortfall.
- `check_json_config.py`: malformed JSON schema mismatch.
- `check_env_contract.py`: missing keys, extra keys, production debug, and sqlite production database signals.
- `check_compose_workflow.py`: latest images, missing env file, missing healthcheck, floating workflow action/runner, and privileged host port signals.

Repair smoke was not run for these sectors. The current `repair-sector` implementation safely repairs browser HTML and command fixtures whose target is a Python script; these repo-quality manifests are docs/test/config probe targets, so running repair would create an empty or misleading repaired manifest instead of a meaningful verification.

Recommended next optimization: add first-class scratch repair templates for repo-quality fields, starting with docs/link autofixes and config fixture copies. Unit-test repair should remain source-to-source and fixture-scoped so it never patches shared core modules during benchmark repair.
