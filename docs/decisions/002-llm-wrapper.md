# 002 — `llm/` wrapper defaults

**Status:** accepted · 2026-11-05

- **Single entry point:** agents call `unclog.llm.LLMClient`; only `llm/backends.py` imports the SDK.
- **Default model:** `claude-opus-5-5`, adaptive thinking, `effort="high"` set explicitly (the model
  defaults to `medium`). Routing per agent comes later through `LLMRequest.model`/`effort`.
- **Structured outputs:** JSON schema through `output_config.format`, built from the Pydantic model,
  then validated locally. On failure it retries with the validation error appended (default 2
  retries), then raises `StructuredOutputError` so a human gets it (brief §17).
- **Refusals:** server-side `fallbacks="default"` (beta `server-side-fallback-2026-07-01`). A refusal
  that still comes back raises.
- **Caching:** automatic prompt caching (`cache_control` ephemeral) and a content-addressed response
  cache (`DiskCache`) that also serves as the replay log for deterministic re-runs.
- **Cost:** a static price table in `llm/pricing.py`. `CostTracker` keeps cost per agent and enforces
  a per-run budget (`BudgetExceeded`). Cost is priced by the requested model; a server-side fallback
  may bill at a different rate. Revisit when we have real usage data.
- **Tests:** `FakeBackend` keeps all tests and offline evals off the network.
