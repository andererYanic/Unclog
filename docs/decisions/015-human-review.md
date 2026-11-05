# 015 — Human review workflow

**Status:** accepted · 2026-11-05 (build plan step 15)

`unclog review <client> <action> <target>` (`orchestrator/review.py`). Every action goes to
`clients/<id>/reviews/review.jsonl` and the client audit log. Only named humans can record
reviews; "agent", "system" and "claude" are refused.

- **approve / request-changes** on a deliverable file. An approval stores the file's SHA-256; if
  the file changes afterwards (edited by hand or regenerated), the approval is *stale*. A change
  request needs a note.
- **comment** on a file or artifact, optionally with a line number.
- **status** of a package: approved, stale, changes requested or unreviewed, with comment counts.
- **release** writes `RELEASE.json` (reviewer, time, file hashes), only if every deliverable is
  approved at its current content. This is the §16 gate before client delivery.
- **rerun** a checkpointed phase. It drops that phase's checkpoint and all downstream ones, so the
  next pipeline run recomputes them.
- **go-live** for a packaged system. It re-runs G15 (handover) and, for AI systems, G14 against
  the given eval report; any failure refuses go-live with the reasons. On success the approval
  reference goes onto the `DeployedSystem` record (applied by the deployment agent's identity, so
  artifact ownership stays intact) and into `GO_LIVE.json`. External actions **stay drafts**
  unless the reviewer explicitly passes `--allow-live`.

A web UI (TypeScript, brief §17) can be built on these same functions later.
