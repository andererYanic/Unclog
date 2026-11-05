# 005 — Constraint confirmation and the G4 gate

**Status:** accepted · 2026-11-05 (build plan step 5)

**Independent evidence = families, not types.** A load calculation built on an event log isn't
independent of that log. Evidence types are grouped into families: **data** (logs, exports,
measured queues), **model** (load/capacity, simulation), **testimony** (interviews, expedite and
absence reports), **document** (SOPs, policies) and **reference** (benchmarks; never counted for
confirmation). A constraint is `confirmed` only with ≥2 families, ≥1 passed confirmation test and
the demand-vs-capacity check done. This is enforced in the `Constraint` schema.

**Hypothesis typing** (in order): *physical* if a resource serving the domain is ≥85% utilized;
*policy* if a batch or approval policy affects the domain's nodes; *market* if capacity is ample
(busiest resource <80%) and the domain is a RACE stage. Anything else is reported as *unresolved*,
together with the discovery action that would resolve it.

**Market constraints need more:**
- No measured internal queue may exist anywhere. A market constraint leaves capacity idle with
  nothing waiting, so an internal queue contradicts it.
- The stage must be located by measured data. The model can only show the constraint is outside
  the company; an estimate can't say which RACE stage it is.
- The queue test is replaced by an idle-capacity test.

**Tests:**
- **relief:** +10% capacity (physical) or +10% demand (market) must raise effective throughput.
- **starvation:** downstream resources must have slack.
- **queue:** a wait or queue in front of the candidate must be the longest, or close to it. It uses
  flow-node data and event logs mapped to nodes.
- **expedite / absence:** keyword hits in interviews and documents that also mention the candidate.

A test that can't run returns nothing: a missing quote is no evidence against a candidate.
Relief and starvation use static flow math for now; simulation replaces it in step 6.

**Policies:** found structurally (batch_size > 1 plus a wait ≥ 24 h) and in text (EN/DE keyword
patterns for batching, approvals, KPIs, local-efficiency measures). Text corroborates structure
when it mentions the node's domain. KPIs that reward local efficiency are flagged with
throughput-world replacements. These are deterministic first passes; the Policy Auditor agent
(step 7) refines them.

**G4 in practice:** if nothing is confirmed, `work_mode = "discovery_only"` and the report lists
only instrumentation and data-collection actions.

**Eval:** `unclog eval-cases` runs every case in `evals/cases/`. It reports binding accuracy split
by RACE vs back-end and fails if the gap is above 15% or any check fails. Current set: 6 cases,
covering the §18 traps for a back-end problem dressed as marketing, a hidden policy, a market
constraint after capacity is fixed, conflicting interview vs log data, no tracking, and a RACE
bottleneck with a back-end temptation. The traps for broken processes, unowned systems and
reviewer flooding belong to opportunity design (steps 8–10) and are added there.
