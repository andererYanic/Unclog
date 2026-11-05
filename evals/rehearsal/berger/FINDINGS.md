# Dress rehearsal: Schreinerei Holzwerk Berger GmbH (fictional)

**Date:** 2026-11-05 · **Run:** `python evals/rehearsal/run_berger.py` · **Output:**
`evals/rehearsal/berger/output/` (German deliverables, drafts)

**Setup.** A realistic German SMB: a German call transcript, an order-status export with `;`
separators and German dates, and a work instruction. All real commands ran:
- `ingest`
- `extract-call`
- `flow-from-log --save`
- a manual flow fragment
- `assemble-case`
- `pipeline` with value model and simulation

The AI steps used fixed answers (no API key yet), but the quote verification ran for real.

**Diagnosis result.** The constraint is the owner, who does every measuring appointment
(Aufmaß) himself, not the lack of enquiries the owner believed. More Google Ads would *reduce*
sales: in the simulation, sales fall from 3.0 to 2.8 orders/week because more customers give up
while waiting. The cheap, non-AI move (the workshop lead takes on measuring appointments) is
worth far more than the AI preparation tool. That is the TOC point the system should make.

## Gaps the rehearsal found, all fixed

| # | Found | Fix |
|---|---|---|
| 1 | German exports (`vorgang_id;status;zeitpunkt;bearbeiter`) were not recognized as event logs | German column names for case, activity, time and person |
| 2 | Lost enquiries looked like waiting ones: 100% conversion and an inflated queue | Cases idle longer than 2× the p90 wait of their next step count as lost |
| 3 | The arrival rate was diluted by the log's tail (9.9 instead of 13/week): constraint missed | Arrivals counted over the window in which cases started |
| 4 | The rope limit was based on finished orders, not jobs through the constraint (4 vs ~9) | `drum_rate()`: items/week through the constraint's own steps |
| 5 | The plan's value showed a loss: only the AI tool was valued; the non-AI lever was invisible | Non-AI actions can be valued the same way (AI role `none`) |
| 6 | Relief gave no throughput gain: queues never cost a sale in the simulation | Node `patience_h`: customers waiting longer give up (simulation) |
| 7 | Guessed owner capacity (9/week) didn't match the data (6.4/week) | `assemble-case` warns when modelled capacity exceeds measured completions at a queued step |
| 8 | English leftovers in German reports (risks, value notes, KPI units, IDs instead of names) | Localized; resource names instead of IDs in sentences, goals and the drum |
| 9 | low/base/high values not in order (simulation noise) | The value model flags it and asks for more replications |

## Still open
- The owner's estimate (about 20 waiting) vs the data (46 waiting): the report shows both, the
  data wins, and the call plan should ask about it.
- Patience (3 weeks) is a stated assumption from the call; measure it from lost enquiries once
  real data exists.
- `RACE-R` and `RACE-E` have no data (G5): honest gaps for the follow-up call.
