# Field Agent B: CLI/Data Notes

Scope: `targets/sectors/cli_data`.

## 2026-06-28 Smoke

- Sector smoke command: `python -m buglab.cli sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --name fieldB_cli_data_smoke`
- Sector result before manifest contract updates: pass, `4/4` fixtures detected, `21` total bug signals, `1.0` detection rate, `1.0` expected-class recall.
- Repair smoke command: `python -m buglab.cli repair-sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --profiles balanced --name fieldB_cli_data_repair --max-clicks 8`
- Repair result before manifest contract updates: fail, exit `1`, `21 -> 3` bug signals, `4/4` fixtures improved, `1/4` fully cleared.

## Contract Updates

- `event_export` now declares `occurred_at` as the output timestamp field, matching the expected repaired schema instead of the intentionally broken `timestamp` alias.
- `inventory_sync` now declares the output fields produced by the fixture and repair template: `sku`, `warehouse`, `region`, and `quantity`.

## 2026-06-28 Post-Update Smoke

- Sector smoke command: `python -m buglab.cli sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --name fieldB_cli_data_smoke_after`
- Sector result: pass, `4/4` fixtures detected, `20` total bug signals, `1.0` detection rate, `1.0` expected-class recall.
- Repair smoke command: `python -m buglab.cli repair-sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --profiles balanced --name fieldB_cli_data_repair_after --max-clicks 8`
- Repair result: fail, exit `1`, `20 -> 1` bug signals, `4/4` fixtures improved, `3/4` fully cleared, `0.95` repair effectiveness.
- Main-thread detector follow-up: `bad_csv_parsing:quoted_delimiter_requires_csv_reader` is now artifact-aware and is retained only when the output loses rows or fails to preserve quoted-comma values.
- Verified repair result after detector follow-up: `20 -> 0`, `4/4` fixtures fully cleared, `1.0` repair effectiveness.

## Remaining Optimization

The CLI/data repair path now fully clears the current fixture pack. The next optimization should broaden data-pipeline coverage to delimiter variants, duplicate keys, empty files, and malformed JSONL/CSV exports.
