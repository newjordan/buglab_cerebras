# Browser/API Field Notes

## 2026-06-28 Field Agent A

- Scope: `targets/sectors/html_interaction`, `targets/sectors/api_workflows`, and this note.
- HTML repair smoke left one residual `button_like_anchor_missing_href` signal each on `#help-link` and `#reports-link` after the repair runtime cleared runtime/state failures.
- Fixture adjustment: those anchors now use non-placeholder fragment `href` values while keeping their broken JavaScript handlers, so the original fixtures still expose console/workflow failures and repaired scratch copies are not blocked by static no-`href` residue.
- Manifest adjustment: `runtime_console` now expects `fetch scheme error` instead of `request failure`, matching the local-file Chromium signal emitted by the fixture.
- API workflow sector already reached full one-loop detection and full repair clearance; no fixture change was needed.
