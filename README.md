# Unclog

We find the one thing holding a business back, then build the AI systems that remove it.
Source of truth: [`UNCLOG-MASTER-BRIEF.md`](UNCLOG-MASTER-BRIEF.md). Decisions: [`docs/decisions/`](docs/decisions/).

```bash
uv venv && uv pip install -e ".[dev,llm,ingest]"
pytest && ruff check .
unclog-export-schemas schemas/   # JSON Schema for every core entity
unclog ingest <client_id> <upload_folder>   # ingest client files into clients/<client_id>/
unclog sources <client_id>
unclog eval-cases               # diagnose all synthetic cases; accuracy split RACE vs back-end
unclog simulate evals/cases/backend_fulfillment_flood --gate design   # what-if scenarios
unclog call-plan --lang de [--case <dir>]         # bilingual first-call plan (+ tailored follow-ups)
unclog extract-call <client_id> <source_id>       # transcript -> verified facts + review sheet (needs API access)
unclog flow-from-log <client_id> <source_id> --domain fulfillment   # measured flow from an event log
unclog goal-tree --case <dir> --lang de [--mermaid]   # goal-factor the confirmed constraint (needs API access)
unclog opportunities --case <dir> --lang de          # goal tree + AI opportunity map (needs API access)
unclog eval-agent goal_factoring --n 10 [--judge] [--model M]   # N-run eval + G14 gate (needs API access)
unclog eval-compare <baseline.json> <candidate.json> --change "prompt v2"   # hill-climb decision
unclog eval-rate <report.json>                    # human ratings 1-10
unclog package <client> <system> --template decision-brief --opportunity opp-x --owner "..."   # client-owned bundle
unclog run-system <client> <system> --input record.json   # one run; external actions land as drafts
unclog outbox <client> list|show|approve|reject [id]      # human approval of drafts (G13)
```

## Status (build plan §19)
- [x] 1. Scaffold, CI, `llm/` wrapper (retries, structured outputs + validation retry, prompt + response caching, cost tracking, budgets)
- [x] 2. Schemas (§13) with evidence enforcement and invariants for G4, G5, G12, G13, G14 and privacy
- [x] 3. Per-client store (versioned, agent-owned artifacts, audit log, delete command); file ingestion (csv/tsv, xlsx, pdf, docx, txt/md, vtt/srt, json, eml) with PII scrubbing and event-log detection; connector interface with file uploads as route 1 (decision 003)
- [x] 4. Flow graph (offered load incl. funnels/rework, load/capacity, wait estimates, what-if scaling), event-log statistics, RACE + back-end heat table with both-direction check and G5 coverage; 3 synthetic cases in `evals/cases/` (decision 004)
- [x] 5. Constraint identification: physical/policy/market hypotheses, confirmation tests (relief, starvation, queue, expedite, absence), evidence families, policy & KPI audit, G4 discovery-only mode, next-constraint prediction; 6 synthetic cases at 100% (decision 005)
- [x] 6. Simulation: event-driven DES + Monte Carlo (validated vs M/M/1 and static load), batching, Drum-Buffer-Rope gate, customer vs in-shop lead time, standard focusing-step scenarios, simulation-backed relief test (decision 006)
- [x] 7. Agents for human-led calls (decision 007): bilingual first-call script and tailored call plan; transcript extractor with verbatim-quote verification; flow modeler with graph validation and retries; measured flow from event logs
- [x] 8. Goal factoring: root goal computed from data, focusing-step skeletons, tree validation, TOC pruning, ranking, opportunity seeds; agent with retries (decision 008)
- [x] 9. Technique library v1 (17 patterns, honest proven status, no invented uplift); Opportunity Analyst with code-owned position, proven-first, process health, ownership, scoring, priority and review-load (G8) checks (decision 009)
- [x] 10. Value model: T/I/OE with simulated ΔT (noise-tested), realization-path ΔOE, mirage ledger, carrying cost, run/build costs, portfolio de-duplication, adoption ramp; feasibility checklist with compliance flags (decision 010)
- [x] 11. Eval harness: N-run distributions (mean, variance, worst case, failure modes), code graders + optional LLM judge, hill-climb rule (mean up, worst case not down) with decision log, G14 gate, human rating CLI, model override (decision 011)
- [x] 12. Build & deploy (provisional defaults, decision 012): 3 proven-pattern templates (decision brief, speed-to-lead drafts, release gate without AI), draft outbox with approval and audit, platform-neutral packaging (SKILL.md, routine, runbook, rollback, handover), G13/G15 checks incl. secret and infrastructure scan
- [ ] 13–17. See brief
