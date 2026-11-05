# Unclog

We find the one thing holding a business back, then build the AI systems that remove it.
Source of truth: [`UNCLOG-MASTER-BRIEF.md`](UNCLOG-MASTER-BRIEF.md). Decisions: [`docs/decisions/`](docs/decisions/).

```bash
uv venv && uv pip install -e ".[dev,llm]"
pytest && ruff check .
unclog-export-schemas schemas/   # JSON Schema for every core entity
```

## Status (build plan §19)
- [x] 1. Scaffold, CI, `llm/` wrapper (retries, structured outputs + validation retry, prompt + response caching, cost tracking, budgets)
- [x] 2. Schemas (§13) with evidence enforcement and invariants for G4, G5, G12, G13, G14 and privacy
- [ ] 3. Store and ingestion; connector skeleton
- [ ] 4–17. See brief
