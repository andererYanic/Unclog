# 006 — Simulation engine

**Status:** accepted · 2026-11-05 (build plan step 6)

**Own event-driven simulator on NumPy, not SimPy.** About 300 lines, no extra dependency, fully
deterministic per seed. Validated against M/M/1 theory and against the static load/capacity model.

**Modelling choices:**
- **Time.** Calendar hours.
- **Arrivals.** Poisson (rate per unit) or sampled inter-arrival times.
- **Routing.** Edge probabilities route items; probability not routed is lost, and sinks count as
  completions.
- **Availability.** A resource with `count` people working H h/week becomes `round(count)`
  servers whose service times are stretched by `168 / H`. Simulated utilization then equals
  static load/capacity; waits come from variability and dependency.
- **Pools.** A node with several resources uses one pooled server group. A resource used alone at
  one node and pooled at another gets independent capacity there. This is an approximation;
  revisit when a real client flow needs it.
- **Batches.** Count-based: items are held until a full batch exists. Real batches are often
  time-based (e.g. Monday and Thursday); add calendar batching when a case needs it.
- **Tasks.** A node's tasks add their service times, plus setup divided by batch size.
- **Rope.** A gate at a node caps WIP from that node onward; the excess waits in a release backlog.
  Its size follows Drum-Buffer-Rope: limit = constraint-limited throughput × buffer weeks.
- **Two lead times.** *Customer* lead time runs from arrival and includes the backlog. *In-shop*
  lead time runs from release. A rope moves waiting from the shop floor to the backlog, so only
  the second one shows its effect.

**Monte Carlo.** R replications with seeds `seed+i`. Results report the mean and the 5th–95th
percentile band across replications. `SimResult.to_simrun()` produces the `SimRun` schema record.

**Standard scenarios:** baseline; exploit (remove a batch); elevate (+25% at the constraint);
demand +30% without a rope (the flooding counterfactual and RACE-vs-back-end what-if); and demand
+30% with a rope (subordinate).

**G9 hook.** `identify(..., sim_replications=N)` runs the relief test by simulation. It passes only
if the relief scenario's 5th percentile beats the baseline mean. The evidence type is `simulation`.

**Known limits:**
- Business effects aren't modelled. For example, faster lead response raising the booking rate
  is a conversion assumption that the Value Modeler (step 10) adds explicitly, not something the
  queueing model produces.
- Short runs with few completions give noisy end-to-end lead times; assert on the direct effect
  instead (e.g. the queue at the node).
