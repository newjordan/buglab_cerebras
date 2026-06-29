# Research Notes

Date: 2026-06-28

## Event

- Cerebras x Google Gemma 4: $5000 Hackathon
- Virtual
- Sunday, June 28, 2026 12:00 PM CDT to Monday, June 29, 2026 12:00 PM CDT
- Hackathon-specific tokens/model access are not available before the start, so model availability before 12:00 PM CDT is only a baseline account check.

## Confirmed Setup Details

- Cerebras exposes an OpenAI-compatible API at `https://api.cerebras.ai/v1`.
- The Python `openai` SDK can target Cerebras by setting `base_url` and using `CEREBRAS_API_KEY`.
- The visible Cerebras model catalog currently lists `gpt-oss-120b` as a production model. It also references `gemma-4-31b` as coming soon/preview, so this project keeps the model configurable.
- The provided baseline Cerebras key currently lists `gpt-oss-120b` and `zai-glm-4.7`. It does not list a Gemma-named model before the hackathon token window.
- A live `gpt-oss-120b` smoke test completed successfully in 747 ms round trip.

Sources:

- https://inference-docs.cerebras.ai/quickstart
- https://inference-docs.cerebras.ai/models/overview

## Idea Candidates To Discuss

These are placeholders until we confirm the actual judging criteria and model access.

1. Fast local workflow copilot: a desktop-friendly app that turns messy notes, files, or issue text into structured action plans and command snippets, with latency shown as a product feature.
2. Live debate/referee tool: stream in two competing claims and have the model produce fact-check prompts, contradictions, and follow-up questions in real time.
3. Rapid prompt-to-prototype assistant: given a hackathon idea, generate an implementation plan, file scaffold, and test checklist, then iterate through user feedback.
4. Interview simulator: low-latency roleplay with strict scoring rubrics for sales, support, or technical interviews.
5. Incident triage console: paste logs/errors and get a concise likely cause, blast radius, and next commands.

## Open Questions

- What is the exact hackathon prompt/challenge statement?
- Is the intended required model specifically Gemma 4, or is Cerebras inference the required platform?
- Which models are enabled once the hackathon token is issued?
- Do judges prefer a web demo, CLI demo, or deployed app?
