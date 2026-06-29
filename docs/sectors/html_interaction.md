# HTML Interaction Sector

This sector contains standalone HTML fixture pages for browser interaction bug hunting. The fixtures are intentionally broken and should not be used as reference implementations for product UI.

Manifest: `targets/sectors/html_interaction/manifest.json`

## Fixture Pack

| Fixture | Target | Expected bug classes | Expected minimum bugs |
| --- | --- | --- | --- |
| Click Through Shop | `targets/sectors/html_interaction/click_through_shop/index.html` | click-through failure, missing link target, broken checkout state, console error | 3 |
| Broken Controls | `targets/sectors/html_interaction/broken_controls/index.html` | broken form control, disabled primary action, semantic no-state-change, invalid success path | 3 |
| Runtime Console | `targets/sectors/html_interaction/runtime_console/index.html` | console error, page exception, fetch scheme error, failed load state | 3 |
| Modal Menu | `targets/sectors/html_interaction/modal_menu/index.html` | modal bug, menu visibility issue, focus/close failure, layout occlusion, missing menu links | 3 |

## Expected Bugs

The browser hunter emits stable static interaction signals before click replay when the DOM already proves a control is broken:

- `disabled_primary_action` for disabled action controls with submit/save/load/connect/etc. intent.
- `button_like_anchor_missing_href` for anchors acting as buttons without a navigable `href`.
- `navigation_error_page:*` when a click lands Chromium on an error document after a failed navigation.

### Click Through Shop

- `#add-dock` reports an add failure instead of adding a cart row.
- `#add-labels` emits a console error and never mutates the cart.
- `#checkout` only changes the URL hash and never enters a complete checkout state.
- `#help-link` is a button-like link without a real destination and emits a console error.
- `#details-link` points at a missing local page.
- Missing or placeholder link targets should produce direct interaction/navigation signals in addition to runtime errors.

### Broken Controls

- `#save-request` receives valid synthetic form values but displays invalid/undefined-route copy.
- `#submit-request` is the primary submit action but is disabled.
- The disabled submit action should be reported directly as `disabled_primary_action`, not only as a timeout.
- `#load-plans` marks the list busy without rendering any plans.
- `#plan` changes produce a failure message instead of a calculated price.

### Runtime Console

- `#connect` throws an uncaught page exception.
- `#refresh-feed` emits a console error and reports a failed refresh.
- `#load-chart` attempts a local-file fetch that Chromium rejects, then leaves the chart empty.
- The feed and chart loaded states do not render usable collection content.

### Modal Menu

- `#load-menu` opens a drawer that is clipped to 72px tall and hides most links.
- The menu shade remains active and can occlude content.
- `#open-modal` opens a clipped dialog and reports a focus failure.
- Modal save/close actions report failed states rather than closing or saving.
- `#reports-link` is a button-like link without a route.

## Suggested Commands

Run one fixture through the installable CLI:

```powershell
buglab run --repo . --target targets\sectors\html_interaction\runtime_console\index.html --name html_interaction_runtime --max-clicks 10
```

Run all fixtures manually by replacing the target path with each entry in the manifest.
