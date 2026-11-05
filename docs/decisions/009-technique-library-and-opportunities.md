# 009 — Technique library v1 and the Opportunity Analyst

**Status:** accepted · 2026-11-05 (build plan step 9)

**Library** (`knowledge/techniques/library.json`, 17 patterns). Each pattern lists its TOC role,
AI role, applicable domains and constraint types, EN/DE keywords, typical inputs/outputs/systems
and whether it has external effect. Proven status says where the claim comes from:
- `established`: TOC literature or long-standing practice
- `field-reported`: the brief's practitioner source; anecdotal
- `emerging`

`typical_uplift` is deliberately empty. No validated, sourced numbers exist yet, and we don't
invent them (brief preamble). The Industry Knowledge Agent fills this in later, with sources.

**Matching** is deterministic and explainable. Score components: focusing step ↔ TOC role,
domain, constraint type, tag ↔ AI role, and keyword hits. A domain-specific pattern is excluded
outside its domain (an ad factory doesn't help an approval constraint). No match ≥ 5 → the action
is novel → R&D label.

**Split of work.** Code decides:
- **Position:** from the goal-tree link and constraint type. protects/gates_flow → upstream, which
  forces a release-gate design.
- **Proven-first:** pattern match, else `rd_label`.
- **Process health:** broken → `fix-process-first`. Unknown → open question; never silently
  assumed sound.
- **Ownership:** no named client owner → `defer` (G12).
- **Code-owned scores:** constraint relevance, proven-ness, ownership.
- **Weighted score and rank:** rank = weighted score × confidence.
- **Priority labels.**
- **Review-load check (G8):** review time at the constraint is flagged. Review that pushes any
  resource to ≥85% is a new constraint → `defer` plus a G8 finding.

The model gives design judgement per seed: human-in-loop design, release gate, review volume,
risks, and the remaining scores with justifications. Malformed judgements go back to it.

**Value (ΔT/ΔI/ΔOE)** stays empty here and comes from the Value Modeler (step 10).
