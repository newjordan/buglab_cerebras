# Challenge Statement

BugLab is being built for the Cerebras x Google Gemma 4 hackathon as a data-first bug hunting and repair-evaluation system.

## Raw Prompt

Build a project using Gemma 4 on Cerebras infrastructure during the 24-hour virtual hackathon window. The project direction for this repository is a rapid recursive bug hunter that can inspect software, exercise interactive surfaces, collect evidence, report bugs, and separate bug finding from bug fixing.

## Constraints

- Keep the repository private until the submission is ready.
- Use Gemma/Cerebras as the core model path when challenge credentials are available.
- Produce reproducible evidence: reports, screenshots, command outputs, quality gates, and benchmark artifacts.
- Optimize for bug-finding accuracy over activity metrics.
- Treat repair as a separate mode from detection, with verification before claiming a fix.

## Judging Criteria

The official scoring rubric is not captured in this repository yet. Current project-facing criteria are:

- Demonstrable Gemma/Cerebras usage.
- A working product path: find bugs, optionally find and fix, then produce a clear report.
- Evidence that BugLab can be calibrated against known-bug targets such as BugsInPy or controlled sector fixtures.
- Clear visual storytelling for the live swarm and final report.
- Honest measurement of false positives, false negatives, and repair verification.

## Required Model Or Platform

- Cerebras inference for Gemma 4 when hackathon credentials are available.
- Local deterministic tooling for audits, reports, benchmarks, and verification.
