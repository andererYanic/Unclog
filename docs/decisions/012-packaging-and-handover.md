# 012 — System packaging, draft outbox and handover (PROVISIONAL)

**Status:** provisional · 2026-11-05 (build plan step 12). This was taken as a default because the
§20 questions on hosting/runner platform and "implement & operate vs. hand over" are still open.
Overrule it at any time.

**Default: hand over, platform-neutral.** Each built system is packaged in the client's workspace
(`clients/<id>/systems/<system>/v<N>/`) as:
- `SKILL.md`: the SOP as a skill (frontmatter `name`, `description`), readable by people and agents
- `routine.json`: schedule (cron) or trigger, connectors, environment, credential *names*
- `runbook.md`, `rollback.md`, `handover.md` (G15 checklist), `config.json`
- a `DeployedSystem` record in the client store

Any runner can execute this: a scheduled agent in the client's AI workspace for skill-based
systems, or plain cron / CI for procedural ones. Once you choose a runner platform, adapters are
added here.

**Credentials** are referenced only by environment-variable name, held in the client's own
vault/accounts. The package must contain no secrets and no paths into our infrastructure; the G15
check scans for both.

**Draft outbox (G13).** Templates never perform external actions directly. They emit
`WriteAction(draft=True)` with a change summary into the client's outbox. A human approves an
item (recorded with approver and timestamp) before any connector executes it; rejected items are
kept with a reason.

**Templates v1** (proven patterns from the library):
- `decision-brief`: LLM; no external effect
- `speed-to-lead-responder`: LLM; external effect → drafts only
- `release-gate-wip-limit`: deterministic, no AI; deployed as a plain script

**Go-live** needs a passing G14 eval report and G15 handover (runbook, rollback, client-owned
accounts, trained owner, re-runnable without us). Until then the system is packaged with status
`not_live`.
