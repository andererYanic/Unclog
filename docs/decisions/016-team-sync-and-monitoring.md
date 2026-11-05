# 016 — Weekly team sync (privacy-gated) and monitoring

**Status:** accepted · 2026-11-05 (build plan step 16). Who attends the sync is still open (000);
the automation doesn't depend on it.

**Team sync** (`sync/team_sync.py`):
- **Privacy gate.** No consent/works-agreement reference → no log mining (`PrivacyError`). The
  salt must be client-specific and ≥16 characters (taken from an environment variable, never
  stored). Pods under 5 people are refused; merge them first.
- **Pseudonymization.** IDs *and names inside log text* become `p-<hash>`. A test caught names
  leaking through the text, and that is fixed. Logs are PII-scrubbed and wrapped as untrusted
  data. Only the top performers' logs for a task go to the model.
- **Ranking** of last week's outcomes per task is deterministic. The pod report gives the spread
  (min–max, n) only. Individual rankings and top-performer IDs appear only with
  `share_individual_ranking` (explicit client policy).
- **Skill update.** The model extracts the implicit SOP. Code replaces the skill's procedure
  section, adds tips and pitfalls, scrubs the output again, bumps the minor version, and writes a
  unified diff and release notes. These are **proposals**: a human approves them before they are
  pushed to the team.

**Monitoring** (`monitoring/`):
- **Results ledger:** baseline vs current per metric, leading/lagging, lag note and attribution
  caveat (in DE/EN). Shows the % change with ✓/✗ by metric direction.
- **Buffer management:** penetration of each order into the time buffer; zones green (<⅓),
  yellow (<⅔), red and late. The red list is the expedite list and its causes are the
  improvement backlog.
- **Constraint-shift alerts** follow the roadmap's re-baseline triggers:
  - constraint below 80% for 4 weeks (action)
  - largest queue moved elsewhere
  - demand ±20%
  - predicted next constraint above 85% (action)
  - throughput dropped while the constraint has slack (starving)

CLI: `ledger`, `buffers`, `monitor` (exits non-zero on an action alert, so it fits cron or CI),
`sync`.
