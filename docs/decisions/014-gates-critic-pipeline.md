# 014 — Quality gates, Critic and the resumable pipeline

**Status:** accepted · 2026-11-05 (build plan step 14)

**Gates G1–G17** (`qa/gates.py`). Each gate returns pass, fail or n/a (not applicable yet).
Schemas already make invalid records impossible; the gates add cross-artifact checks:
- G2: evidence-coverage share
- G4: design work only with a confirmed constraint, and opportunities linked to it
- G7: claimed savings must be in the mirage ledger
- G8: upstream release gates and review overload
- G9: ΔT ≠ 0 only with a SimRun
- G10: elevate needs a start condition; local-efficiency KPIs need replacements
- G11: no build before a baseline exists
- G12: owner, process health and R&D rules
- G13–G15: draft safety, eval and handover for deployed systems
- G16: a specificity heuristic that rejects generic phrases like "use AI" or "Effizienz steigern"
  and requires numbers and named objects
- G17: measured metrics must trace to engagement sources; overlapping gains must be de-duplicated

**Blocking per phase** (`orchestrator/pipeline.py`, `PHASE_GATES`):

| Phase | Blocking gates |
|---|---|
| diagnose | G1, G3 |
| goal factoring | G1, G4 |
| opportunities | G1, G6, G8, G12 |
| plan | G7, G9, G10 |

At report time all gates run and are written to `10-quality-gates.md`.

**Critic** (`qa/critic.py`) emits Findings: local optima, domain coverage, mirages, ownership and
proven-first. If the Critic blocks after the opportunity phase, the phase re-runs once; a second
block escalates to a human (§16). Other escalations:
- an agent fails its checks after retries
- confidence below 0.5 on an item
- regulated domains (hr, finance, legal)
- blocked feasibility

**Resumability.** LLM phases checkpoint to `clients/<id>/pipeline/<phase>.json`, keyed by a hash
of their inputs: constraint, language, prompt version, seeds. A resumed run makes no model calls
unless the inputs changed.

**Bug found and fixed.** Evidence IDs came from a global counter, so identical diagnoses had
different IDs on each run. That broke checkpoint keys and violated "reproducible, no hidden global
state". IDs are now content hashes.

**End state.** The pipeline stops at `awaiting_review`: deliverables are drafts. Build and
deploy (phases 9–10) need a human go-live decision.
