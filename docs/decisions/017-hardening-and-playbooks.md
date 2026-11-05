# 017 — Hardening and playbooks

**Status:** accepted · 2026-11-05 (build plan step 17)

**Encryption at rest.** Raw uploads are encrypted with a per-client Fernet key from
`UNCLOG_KEY_<CLIENT>` or `$UNCLOG_KEYS_DIR/<client>.key` (0600, outside the repo; `unclog keygen`
never prints the key). `UNCLOG_REQUIRE_ENCRYPTION=1` makes a missing key an error. Derived sources
are PII-scrubbed at ingestion and stay unencrypted for now; encrypt them too if a client requires
it.

**Audit.** Every write was already audited. Now reads of raw files and sources are audited too,
and so is every model call (agent, model, tokens, cost, cache hit, request hash; never content),
through the `LLMClient.on_call` hook. CLI commands that work on a client use it automatically.

**Retention.** `clients/<id>/policy.json` (`raw_days`, `derived_days`). `unclog retention` is a
dry run by default; `--apply` deletes old raw uploads, pipeline checkpoints, system run outputs
and decided outbox items. Kept: audit log, review log, results ledger, deliverables. Deleting a
whole client is `delete_client` (step 3).

**Cost budgets.** On top of per-run budgets, `EngagementBudget` persists spend per client in
`costs.jsonl` and enforces `max_usd` from the policy across runs.

**Secrets.** `unclog security-scan` checks a tree for keys, credential assignments, private
keys and `.env` files. CI runs it on the repo and fails on findings; test fixtures are marked
`secret-scan: allow` or built at runtime. CI also runs `unclog eval-cases`.

**Fixed along the way:** a qa ↔ orchestrator import cycle (type-only imports now).

**Playbooks** (qualitative, no invented numbers):
- `knowledge/toc/core.md` (`novel` vs `later-TOC` tags)
- `knowledge/race/playbook.md` and an *empty* `benchmarks.md` register with sourcing rules
  (benchmarks are an open owner decision)
- `knowledge/backend/playbooks.md` (all ten back-end domains)
- `knowledge/industries/README.md` (hypotheses, not benchmarks)
- `knowledge/regulations/eu-de.md` (GDPR, EU AI Act, BetrVG, UWG, GoBD, §203 StGB; not legal
  advice)
