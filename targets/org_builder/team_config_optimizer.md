# Team Config Optimizer Target

Build a data-first org builder for agentic website R&D.

Core question:

Given a target class, what is the smallest team layout that produces the best measured result?

Target classes:

- visual_to_site: concept image to working website
- speed_fleet: website speed/refactor optimization
- playthrough_debug: browser task reliability and repair
- org_builder: choosing the team configuration itself

Candidate layouts to test:

- solo generalist
- builder plus critic
- manager plus specialists
- tournament
- frontier sweep
- Belbin-inspired research team with strict builder/verifier separation

Required output:

- candidate org layout
- ablation row
- expected failure mode
- metric set
- Pareto chart position
- next test

Scoring:

- final score up
- pass rate up
- failure count down
- regression count down
- total seconds down
- worker count down when scores are tied

Do not pick a team because it sounds elegant. Pick the team that wins the table.

