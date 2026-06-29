# Gemma Autoswarm Micro R&D Lab Plan

Date: 2026-06-28

## Thesis

Use Gemma/Cerebras speed to run many small expert loops instead of betting on one strong model pass. The product can come later; first we measure which swarm topology actually improves website generation, refactoring, and verification.

Working assumption for DELI:

- Define: make the target and scoring rubric concrete.
- Execute: run specialist workers on narrow tasks.
- Look: verify with objective checks and visual/browser evidence.
- Iterate: route failures back to the right specialist.

If your DELI acronym means something different, we can rename it, but this loop is the right KISS operating pattern.

## R&D Goal

Find the Pareto knee between:

- quality
- iteration count
- latency
- token/API use
- pass rate
- stability across repeated runs

We are not optimizing for a fancy architecture yet. We are optimizing for a repeatable swarm process that produces visibly better web demos under hackathon time pressure.

## Experiment Tracks

### Track A: Concept Image To Website

Input:

- AI-generated concept image of a complex website, likely a trading terminal or market analytics dashboard.

Target:

- Generate a working website that visually matches the concept image and behaves like a credible app surface.

Workers:

- Visual Analyst: extracts layout, hierarchy, colors, density, and component inventory from the concept image.
- UI Architect: converts visual analysis into page structure and responsive layout.
- Frontend Builder: implements HTML/CSS/JS.
- Visual QA: compares screenshot against concept and lists concrete deltas.
- Repair Worker: fixes only the largest visual mismatches.

Verification:

- Desktop screenshot.
- Mobile screenshot.
- Manual visual score from 1-5 until automated image similarity is added.
- Layout failure count: overflow, overlap, clipped text, blank areas.

Primary metric:

- Visual match score per iteration minute.

### Track B: Speed Optimization Fleet

Input:

- A deliberately bloated website or app surface.

Target:

- Improve load, render, and interaction speed while preserving appearance and behavior.

Workers:

- Performance Profiler: identifies likely bottlenecks.
- Bundle/Asset Optimizer: removes waste, compresses, defers, lazy-loads.
- Render Optimizer: fixes layout thrash, heavy DOM, expensive paint, blocking JS.
- Regression QA: compares before/after screenshots and task behavior.
- Benchmark Judge: records objective metrics.

Verification:

- Build success.
- Before/after local benchmark.
- Screenshot diff or visual pass.
- Interaction smoke test.

Primary metric:

- Performance improvement with zero visual/function regression.

### Track C: Browser Playthrough And Debug Reliability

Input:

- A generated or refactored web app with known user tasks.

Target:

- Make the app robust through automated playthrough, bug reproduction, and targeted repair loops.

Workers:

- Task Designer: defines realistic user paths.
- Browser Runner: executes tasks and captures failures.
- Bug Triage: groups failures by root cause.
- Fix Worker: patches the smallest likely cause.
- Regression Runner: reruns the exact failed path plus a smoke set.

Verification:

- Task completion rate.
- Number of reproduced failures fixed.
- New regression count.
- Screenshot evidence for final pass.

Primary metric:

- Pass rate improvement per loop, with regression count held near zero.

## Swarm Topologies To Test

## Research Persona Layer

When `research_mode` is enabled, use the Belbin-inspired research team defined in `docs/persona_framework.md`.

This gives the research swarm explicit behavioral coverage:

- Research Lead
- Hypothesis Generator
- Source Scout
- Evidence Skeptic
- Domain Expert
- Protocol Builder
- Audit QA
- Deadline Driver
- Integrator

Guardrail: research personas propose and critique; builders implement; verifiers certify.

### Solo Baseline

One agent does the full task in one pass.

Purpose:

- Establish whether swarm overhead is worth it.

### Manager + Specialists

One manager assigns tasks to role-specific workers, then routes verifier feedback.

Purpose:

- Best default for complex workflows where output must be integrated.

### Tournament

Several workers independently solve the same subtask. A judge picks the best result or merges the top two.

Purpose:

- Useful when generation variance is high.

### Critic Loop

Builder produces output, critic lists flaws, builder fixes.

Purpose:

- Cheap, simple loop. Good baseline for DELI.

### Frontier Sweep

Run many narrow variants with controlled prompt, role, or topology changes, then keep only winners.

Purpose:

- Find the Pareto knee fast.

## Initial Ablation Axes

- Topology: solo, manager-specialist, tournament, critic-loop, frontier-sweep.
- Worker count: 1, 2, 3, 5, 8.
- Loop count: 1, 2, 4, 8.
- Verification: none, text-only, screenshot, browser-playthrough, benchmark, combined.
- Memory: none, run-local notes, persistent failure log.
- Research: none, single researcher, researcher plus judge.
- Repair style: broad rewrite, targeted patch, verifier-guided patch.
- Acceptance gate: manager judgment, objective metric, verifier consensus, human score.

## Minimum Data Per Run

- Run ID.
- Track.
- Target.
- Model.
- Topology.
- Worker count.
- Loop count.
- Verification type.
- Starting score.
- Final score.
- Latency.
- Failure count.
- Regression count.
- Notes.

## Decision Rule

A topology is promising only if it beats solo baseline on at least two of:

- higher final score
- fewer unresolved failures
- fewer total loops
- lower time to acceptable result
- better stability across repeated runs

The winner for the hackathon product should be the simplest topology that repeatedly works. Complexity is allowed only when the ablation table proves it buys quality.

## Product Candidates After R&D

1. Speed/refactor fleet for websites: paste repo or URL, get a measured optimization plan and patches.
2. Visual-to-site builder: concept image to working web surface with visual QA loops.
3. Autonomous browser QA lab: generated test tasks, playthrough failures, and self-repair.

Current bias:

- Product should probably become the speed/refactor fleet, because it gives objective before/after metrics and a clear judging story.
- The visual-to-site and browser QA tracks become internal demo evidence and optional features.
