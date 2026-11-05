# 010 — Value model (T/I/OE) and feasibility

**Status:** accepted · 2026-11-05 (build plan step 10)

**Formula** (per month, deterministic code): ΔProfit = ΔT − ΔOE_realized − ΔI carrying −
run cost − amortized build.

- **Effects are explicit inputs.** Each one is a capacity, service-time, conversion, demand or
  batch change with low/base/high levels and a basis (assumption, pilot or measured). They start
  as consultant assumptions and are replaced by pilot measurements. The report says so while any
  effect is still an assumption.
- **ΔT only from simulation.** Baseline and effect runs use the same seed. A difference within
  2 standard errors of replication variance counts as zero, with a note. So a non-constraint
  speed-up can't be shown as value through noise (NCX-10, G9).
- **ΔOE only with a realization path,** weighted by its probability. Claimed savings or released
  hours without one go to the mirage ledger at zero (G7).
- **ΔI** comes from simulated WIP change × inventory value, at the annual carrying rate.
- **Costs:** licences, inference per item, review labour (always costed; conservative) and build
  amortized over N months.
- **Portfolio.** All effects are simulated together. If the joint ΔT differs from the sum of
  parts, the report says the gains overlap on shared constraint capacity and that the joint
  figure is the one to use.
- **Adoption ramp** (linear) for first-year value, plus a lag note: leading indicators move
  first, money later.

**Feasibility** is a deterministic checklist that produces risks. Flags are analysis, not legal
advice, and are labelled as such. It covers:
- **Compliance:** GDPR for personal data; EU AI Act high-risk and works-council rights for
  employment uses; UWG §7 for outreach; GoBD for bookkeeping; health data (blocked pending
  expert review).
- **Safety:** external effects must be draft/paused (G13).
- **Data access:** only file uploads exist today (decision 003).
- **Ownership** (G12) and **process health** (§9.8).
- **Review capacity** (G8) and post-constraint error risk.

**No guarantees.** The model reports low/base/high ranges only. Performance pricing or guarantees
need a statistical model of achievable uplift and legal review first. That's the open commercial
question in 000.
