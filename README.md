# Unclog

We find the one thing holding a business back, then build the AI systems that remove it.
Source of truth: [`UNCLOG-MASTER-BRIEF.md`](UNCLOG-MASTER-BRIEF.md). Decisions: [`docs/decisions/`](docs/decisions/).

```bash
uv venv && uv pip install -e ".[dev,llm,ingest]"
pytest && ruff check .
unclog-export-schemas schemas/   # JSON Schema for every core entity
unclog ingest <client_id> <upload_folder>   # ingest client files into clients/<client_id>/
unclog sources <client_id>
```

## Status (build plan §19)
- [x] 1. Scaffold, CI, `llm/` wrapper (retries, structured outputs + validation retry, prompt + response caching, cost tracking, budgets)
- [x] 2. Schemas (§13) with evidence enforcement and invariants for G4, G5, G12, G13, G14 and privacy
- [x] 3. Per-client store (versioned, agent-owned artifacts, audit log, delete command); file ingestion (csv/tsv, xlsx, pdf, docx, txt/md, vtt/srt, json, eml) with PII scrubbing and event-log detection; connector interface with file uploads as route 1 (decision 003)
- [x] 4. Flow graph (offered load incl. funnels/rework, load/capacity, wait estimates, what-if scaling), event-log statistics, RACE + back-end heat table with both-direction check and G5 coverage; 3 synthetic cases in `evals/cases/` (decision 004)
- [ ] 5–17. See brief
