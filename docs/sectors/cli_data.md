# CLI/Data Sector

This sector adds dependency-free Python CLI and data-processing fixtures for bug hunters that need targets beyond browser UI flows.

## Fixture Pack

| Fixture | Command | Expected bug classes | Minimum bugs |
| --- | --- | --- | --- |
| `invoice_rollup.py` | `python targets/sectors/cli_data/fixtures/invoice_rollup.py --input targets/sectors/cli_data/data/invoices.csv --output tmp/cli_data/invoice_totals.csv` | bad exit codes, missing file handling | 2 |
| `lead_importer.py` | `python targets/sectors/cli_data/fixtures/lead_importer.py --input targets/sectors/cli_data/data/leads.csv --output tmp/cli_data/leads.json` | bad CSV parsing, schema mismatch, silent data loss | 3 |
| `event_export.py` | `python targets/sectors/cli_data/fixtures/event_export.py --input targets/sectors/cli_data/data/events.csv --output tmp/cli_data/events.json` | flaky timestamp/order assumptions, silent data loss, schema mismatch | 3 |
| `inventory_sync.py` | `python targets/sectors/cli_data/fixtures/inventory_sync.py --items targets/sectors/cli_data/data/inventory_items.csv --warehouses targets/sectors/cli_data/data/warehouses.csv --output tmp/cli_data/inventory.csv` | schema mismatch, silent data loss, missing file handling | 3 |

The machine-readable fixture list lives at `targets/sectors/cli_data/manifest.json`.

The manifest also carries detector metadata for output contracts: expected fields, forbidden renamed fields, duplicate/primary keys, and timestamp fields. These metadata keys let the command runner score data workflow bugs from produced CSV/JSON artifacts instead of relying only on process exit code or stderr text.

## Expected Bugs

### `invoice_rollup.py`

- Returns exit code `1` after a successful rollup, which makes a correct data output look failed to automation.
- Returns exit code `0` when the input file is missing, writes an empty output, and only prints a warning.

### `lead_importer.py`

- Parses CSV by calling `split(",")`, so quoted commas such as `"Lovelace, Inc."` are treated as extra columns.
- Silently drops rows whose cell count does not match the naive header split.
- Emits JSON fields `id` and `email_address` even though the input contract and likely downstream schema expect `lead_id` and `email`.

### `event_export.py`

- Sorts timestamps as raw strings, mixing ISO and US date formats into an order that can differ from chronological time.
- Deduplicates events with `{event_id: row}`, silently keeping the last duplicate and losing prior rows.
- Emits `timestamp`, `user`, and `type` fields instead of preserving `occurred_at`, `user_id`, and `event_type`.

### `inventory_sync.py`

- Builds warehouse metadata with `row["id"]` even though the CSV header is `warehouse_id`, causing a `KeyError`.
- If the key bug is fixed naively, unknown warehouses such as `W-999` are silently dropped instead of reported.
- Missing item or warehouse files are not handled with a clear CLI error contract.

## Current BugLab Coverage

`buglab sector` includes a command/artifact runner for this fixture pack. It runs each `suggested_command`, captures exit code/stdout/stderr/wall time, inspects generated CSV/JSON artifacts, runs missing-file probes, and writes the standard BugLab report schema.

Current CLI/data probes cover:

- data loss from output row-count drops and duplicate-key overwrite.
- schema drift from missing expected fields, forbidden output aliases, and explicit renamed fields.
- CSV parsing hazards from quoted delimiters that naive `split(",")` parsing cannot preserve.
- timestamp workflow bugs from mixed timestamp formats, renamed timestamp fields, and output order that differs from parsed chronological order.

Latest detection snapshot:

```powershell
python -m buglab.cli sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --name cli_data_detector_tuned2
```

Result: `4/4` fixtures detected, `21` total bug signals, `21` unique signals, `1.0` detection rate, `1.0` average expected-class recall.

## Repair Verification

`buglab repair-sector` repairs this sector non-destructively. It copies Python scripts and input data into `.buglab/repair`, rewrites commands to scratch paths, applies data-contract repair templates, and reruns the same command probes.

```powershell
buglab repair-sector --repo . --manifest targets\sectors\cli_data\manifest.json --loops 1 --profiles balanced --name repair2_cli_data --max-clicks 8
```

Result: `13 -> 0` bug signals, `4/4` fixtures fully cleared, `1.0` repair effectiveness.
