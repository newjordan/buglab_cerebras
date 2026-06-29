# Unit Tests Sector

This sector covers code-test defects that show up in common business repos: failing assertions, unhandled exceptions, skipped critical checks, contract mismatches, and missing test coverage.

The generic repo audit now emits one aggregate unittest discovery row plus per-file `unittest_file` rows for up to 40 discovered Python test files. Per-file rows isolate failing assertions, unhandled exceptions, skipped tests, static skip decorators, missing test functions, files without assertions, and placeholder coverage notes.

Manifest: `targets/sectors/unit_tests/manifest.json`

| Fixture | Target | Expected classes | Minimum |
| --- | --- | --- | ---: |
| Billing rules tests | `targets/sectors/unit_tests/fixtures/test_billing_rules.py` | failing assertion, skipped critical test | 2 |
| Inventory contract tests | `targets/sectors/unit_tests/fixtures/test_inventory_contract.py` | unhandled exception, contract mismatch | 2 |
| Authorization coverage tests | `targets/sectors/unit_tests/fixtures/test_authorization_coverage.py` | failing assertion, missing test coverage | 2 |

Run:

```powershell
buglab sector --repo . --manifest targets\sectors\unit_tests\manifest.json --loops 1 --name unit_test_check
```

Repo audit smoke:

```powershell
python -m buglab.cli hunt --repo . --no-browser --no-docs --loops 1 --profiles balanced --max-clicks 1 --name tests_config_signal_smoke
```

Expected generic audit coverage on these fixtures: 4 test rows, 4 failed test rows, and isolated per-file signals for assertion failure, runtime exception, runtime skip, and static skip decorator detection.
