# 018 — Assembling a real client into a runnable case

**Status:** accepted · 2026-11-05

Synthetic cases are hand-written JSON. Real clients produce their material piece by piece in the
client store. `unclog assemble-case <client> --title ...` combines those pieces into
`clients/<id>/case/case.json`, which `unclog pipeline --case clients/<id>/case --client-id <id>`
then runs.

- **Sources** are referenced by id (`store_sources`). The pipeline reads the scrubbed store copies
  (`run_case(..., store=...)`), so encrypted raw uploads are never decrypted to disk.
- **Goal and unit of throughput** come from call extractions (`reviews/*-extraction.json`).
  T/I/OE definitions are marked "to confirm with the client".
- **Metrics** are the StageMetric records from `extract-call`.
- **Flow** is merged from fragments in `clients/<id>/flow/*.json`:
  - `flow-from-log ... --save` writes measured fragments (nodes, edges, activity→node map, and
    the domain of that event log)
  - the consultant adds a manual fragment for who does the work and how long it takes
  - later fragments override fields of nodes with the same id
- **Gaps are reported, never invented:** no goal (G3), event logs without a fragment, no flow, no
  resources, no metrics.

Typical sequence for a new client:
1. `ingest`
2. `extract-call` per transcript
3. `flow-from-log --save` per event log
4. a manual fragment with resources and service times
5. `assemble-case`
6. `pipeline`
