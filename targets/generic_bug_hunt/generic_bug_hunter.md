# Generic Bug Hunter Target

Build and test a system that can inspect arbitrary interactive software, discover likely user actions, play through the surface, capture screenshots, label failures, and verify fixes.

## Required Capabilities

- Accept a local HTML file or URL.
- Discover visible controls: links, buttons, forms, inputs, selects, role buttons, onclick elements.
- Exercise each path in isolation where possible.
- Fill forms with safe synthetic values.
- Capture baseline and post-action screenshots.
- Collect console errors, page errors, request failures, URL changes, suspicious text, and task pass/fail deltas.
- Assign evidence to specialist agents: explorer, runtime sentinel, visual inspector, form agent, interaction agent, repair agent, regression verifier.
- Produce a bug report with reproduction steps, selectors, screenshots, severity, likely cause, and fix hypothesis.
- Re-run the same checks against a fixed candidate and compute bug-count delta.

## Metrics

| Metric | Definition |
| --- | --- |
| control_discovery_count | Number of visible controls detected. |
| click_path_coverage | Exercised controls / discovered controls. |
| screenshot_evidence_count | Baseline plus post-action screenshots. |
| bug_candidate_count | Actions with at least one failure signal. |
| verified_fix_delta | Bug candidates before fix minus bug candidates after fix. |
| false_positive_review_count | Bug candidates that require human review. |

## DELI Loop

1. Define target and allowed action budget.
2. Execute generic browser crawl with screenshots and event capture.
3. Look at agent-labeled bug candidates and Pareto rank by impact/cost.
4. Iterate with a targeted fix, then replay the exact same crawl.

## Product Hypothesis

The simplest compelling product is a "find and fix bugs" R&D lab: drop in software, let the system play it, inspect evidence, produce bug reports, patch candidates, and prove the fix with before/after charts.

