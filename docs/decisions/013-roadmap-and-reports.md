# 013 — Roadmap Planner (DBR) and Report Writer

**Status:** accepted · 2026-11-05 (build plan step 13)

**Roadmap** (`reporting/roadmap.py`, deterministic). Work is sequenced in waves:
- **0 measure:** if the constraint's own numbers aren't measured, instrument it first (G11);
  coverage gaps (G5) are also listed here.
- **1 exploit:** in this order: fix-process-first items, policy changes, non-AI fixes, then
  exploit-now opportunities.
- **2 subordinate:** rope, batch reduction, gated upstream systems.
- **3 elevate:** each item carries the start condition "when wave-1 results are in the results
  ledger" (G10).
- **Backlog:** defer, R&D and do-not-pursue items, each with its reason.

**DBR design** by constraint type:
- **physical:** drum = the resource; buffer = 1 week (green/yellow/red by thirds); rope =
  WIP-from-release limit = drum throughput × buffer weeks.
- **policy:** change the rule first; meanwhile make the queue in front of the decision visible
  and capped.
- **market:** drum = demand; keep protective capacity; make delivery promises reliable.

The roadmap also lists KPIs with baselines from the data and re-baseline triggers:
- constraint utilization below 80% for 4 weeks
- the largest queue moves elsewhere
- demand changes by more than ±20%
- the predicted next constraint goes above 85%
- after each policy change: audit inherited rules for inertia

**Reports** (`reporting/writer.py`, Jinja templates in `templates/`) render in German or English.
Every document is stamped DRAFT, requiring human review before client delivery (§16). Each file
renders only when its inputs exist; with no confirmed constraint, the package is diagnosis-only:
1. executive summary
2. constraint report: load/capacity, heat table, constraint and tests
3. goal tree with a mermaid diagram
4. roadmap and DBR
5. policy audit
6. opportunity map
7. value report and value workbook (xlsx)
8. risk register (with the not-legal-advice note)
9. simulation scenarios
10. JSON export

**Known gap:** headings, actions and plain-language summaries are localized, but the diagnosis
detail lines (heat-table rationale, constraint descriptions, demand-vs-capacity note) are still
English. Localizing the heat table and analyst text is a follow-up.

The constraint analyst and `run_case` now take `lang`.
