# Docs Link Integrity Sector

This sector covers business documentation defects that commonly break launches: dead local links, missing anchors, missing image assets, unresolved placeholders, and required release terms.

Manifest: `targets/sectors/docs_link_integrity/manifest.json`

| Fixture | Target | Expected classes | Minimum |
| --- | --- | --- | ---: |
| Onboarding runbook | `targets/sectors/docs_link_integrity/onboarding.md` | missing local link, missing anchor, unresolved placeholder | 3 |
| API reference docs | `targets/sectors/docs_link_integrity/api_reference.md` | missing anchor, missing image asset, unresolved placeholder | 3 |
| Release notes docs | `targets/sectors/docs_link_integrity/release_notes.md` | missing local link, missing required term, unresolved placeholder | 3 |

Run:

```powershell
buglab sector --repo . --manifest targets\sectors\docs_link_integrity\manifest.json --loops 1 --name docs_link_check
```
