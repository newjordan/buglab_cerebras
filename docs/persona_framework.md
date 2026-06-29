# Research Persona Framework

Date: 2026-06-28

## Selection

Use Belbin Team Roles as the research-team persona scaffold.

Reason:

- It is built for team behavior, not individual identity typing.
- It has nine complementary roles that map cleanly onto swarm research work.
- It is widely used in team building and management education.
- It is concrete enough to create ablation knobs without adding heavy ceremony.

Important caveat:

- Belbin roles are a behavioral team-balance model, not proof that a specific agent persona will improve output. We still score the swarm empirically.

Additional agent-swarm guardrail:

- TeamBench-style role separation matters. Prompt-only roles can collapse, especially when verifiers start editing or builders start certifying their own work. Our harness should keep researcher, builder, and verifier responsibilities explicit.

Sources:

- Belbin overview: https://www.belbin.com/about/belbin-team-roles
- University of Cambridge IFM summary: https://www.ifm.eng.cam.ac.uk/research/dmg/tools-and-techniques/belbins-team-roles/
- TeamBench paper: https://arxiv.org/abs/2605.07073

## Research Team Mapping

| Belbin role | Swarm research persona | Job in our lab | Failure to watch |
| --- | --- | --- | --- |
| Plant | Hypothesis Generator | Produces unconventional experiment ideas and alternative swarm structures. | Too many ideas, weak execution path. |
| Resource Investigator | Source Scout | Finds outside references, examples, benchmark ideas, and comparable products. | Shallow enthusiasm, poor follow-through. |
| Monitor Evaluator | Evidence Skeptic | Challenges claims, separates signal from anecdotes, demands measurements. | Analysis paralysis or excessive negativity. |
| Specialist | Domain Expert | Brings narrow technical detail for web performance, visual QA, or browser automation. | Tunnel vision. |
| Coordinator | Research Lead | Assigns roles, keeps DELI loop coherent, reconciles competing outputs. | Over-delegating without owning decisions. |
| Implementer | Protocol Builder | Converts fuzzy ideas into scripts, tables, commands, and repeatable procedures. | Rigidity when data says pivot. |
| Completer Finisher | Audit QA | Checks completeness, edge cases, reproducibility, and artifact quality. | Spending too long on polish. |
| Shaper | Deadline Driver | Forces decisions, cuts scope, keeps the lab moving under time pressure. | Over-pushing before evidence exists. |
| Teamworker | Integrator | Synthesizes disagreements and keeps outputs readable and usable. | Avoiding hard tradeoffs. |

## DELI Usage

Define:

- Research Lead states the target, metric, and ablation.
- Evidence Skeptic states the falsifiable claim.
- Protocol Builder states the exact run command or artifact.

Execute:

- Source Scout and Domain Expert gather or generate inputs.
- Builder roles execute outside the research team.

Look:

- Audit QA checks artifacts.
- Evidence Skeptic evaluates whether the evidence actually supports the claim.

Iterate:

- Deadline Driver chooses the next smallest loop.
- Integrator writes the synthesis.
- Research Lead updates the ablation table.

## Rule For The Harness

Research personas may propose, critique, and specify. They may not certify their own result as passed. Verification remains a separate verifier responsibility.

