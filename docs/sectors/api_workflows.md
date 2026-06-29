# API Workflow Sector

This fixture pack covers API-like browser workflows where the visible bug is usually not a layout defect. Each page is self-contained, uses deterministic mocked responses, and can be opened as a local file or passed to the BugLab CLI.

## Fixtures

| Fixture | Target | Expected bug classes | Expected minimum bugs |
| --- | --- | --- | --- |
| Fetch status console | `targets/sectors/api_workflows/fetch_status_console.html` | failed mocked endpoint, wrong status handling, missing empty or retry state | 2 |
| Malformed JSON importer | `targets/sectors/api_workflows/malformed_json_importer.html` | malformed JSON, uncaught parse exception, stale success state | 2 |
| Optimistic queue | `targets/sectors/api_workflows/optimistic_queue.html` | optimistic UI rollback, mocked endpoint rejection, localStorage duplication | 2 |
| Payment form state | `targets/sectors/api_workflows/payment_form_state.html` | validation bypass, wrong status handling, invalid localStorage state | 2 |

## Expected Bugs

### Fetch Status Console

- `Refresh Orders` receives a mocked HTTP 503 response, emits a console failure, and leaves the order list empty without a useful retry or empty state.
- `Ship Selected Order` receives a mocked HTTP 409 response but still marks the order shipped, creating a wrong status handling bug.

### Malformed JSON Importer

- `Load Profile JSON` parses malformed API JSON without a guard, causing an uncaught `JSON.parse` exception.
- `Save Imported Profile` catches malformed JSON but leaves stale import state in a save-ready workflow.

### Optimistic Queue

- `Add Comment` writes an optimistic localStorage item before the mocked API rejects it, then fails to roll the item back.
- `Sync Queue` duplicates pending localStorage entries when sync fails.

### Payment Form State

- The validation branch uses `email_invalid && amount_invalid`, so a single invalid field can still call the mocked charge API.
- A mocked HTTP 422 response leaves an invalid submitted draft in localStorage instead of reverting to editable form state.

## Manifest

The machine-readable fixture manifest is at `targets/sectors/api_workflows/manifest.json`, with a CSV copy at `targets/sectors/api_workflows/manifest.csv`.

Suggested smoke command:

```powershell
buglab run --repo . --target targets/sectors/api_workflows/fetch_status_console.html --name api_workflow_fetch_status --max-clicks 6
```
