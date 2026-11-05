# 004 — Flow math and domain heat table

**Status:** accepted · 2026-11-05 (build plan step 4)

**Units.** Arrivals are calendar rates normalized to per week. Service and setup times are work
hours (1 day = 8 h, 1 week = 40 h). Resource capacity is work hours per week. Capacity given per
month is converted at 12/52.

**Demand.** Offered load per node solves `λ = λ0 + Pᵀλ`. RACE conversions are edge probabilities,
rework loops are allowed, and unrouted probability leaves the system. `load = λ × service (+ setup
per batch)` and `utilization = load / capacity` (brief §8.2). A node without tasks splits its
service time across its resources by headcount. This is static analysis: dynamics are left to
simulation (step 6). Queue waits use the Sakasegawa G/G/c approximation with Poisson-like
arrivals, as an indicator only. Observed waits come from data, or from Little's law when only a
queue length is known.

**Domain ids.** `FlowNode.domain_id` and `StageMetric.domain_id` use `DomainName` values
(`RACE-A`, `fulfillment`, …).

**Heat table.** Three independent signal kinds: capacity, queue, conversion vs benchmark. Score
per domain = Σ over signal kinds of weight × (1 + severity) + prior, where weight is 1.0 for
measured signals and 0.5 for estimates. Priors are 0.15 for RACE and 0.04 for back-end, so they
can only break ties: any signal outranks any prior. This keeps the RACE prior from overriding
evidence (brief §4.3), which §18 checks by comparing accuracy on RACE vs back-end cases.

**Verdicts.** The heat table only outputs `candidate`, `clear` or `not_assessed`. `constraint` is
assigned by the Constraint Analyst after confirmation tests (step 5, G4). `clear` needs a sourced
metric or sourced flow data. Unsourced guesses leave a domain `not_assessed`.

**Both-direction check.** Busiest resource ≥ 100% → `capacity_limited`; if it serves a back-end
domain, the note warns that more demand only lengthens the queue (flooding trap). Busiest < 80% →
`market_limited`, and it reports the demand headroom. In between → `inconclusive`, pending
simulation.

Thresholds (85% utilization, 25% benchmark gap, 24 h wait) are defaults in `HeatConfig`; tune
them against synthetic and real cases.
