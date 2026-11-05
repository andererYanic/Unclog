# RACE playbook: Reach, Acquire, Convert, Expand

Use with the first-call script (`first_call_script.json`). RACE is a *prior*: the front stages
are scanned first, but measured back-end evidence outranks a RACE guess (brief §4.3).

| Stage | Ask (with numbers) | Signals of a constraint | Typical non-AI exploit | Proven AI patterns (library) |
|---|---|---|---|---|
| **R** Reach | visitors/impressions per week, spend, channels, creative volume | low volume vs history; one channel only; stale creative | stop paused/losing channels; refresh offer | ad-creative variant factory (paused ads) |
| **A** Acquire | leads per week, median first response, booked rate | many leads but slow first reply; leads worked in batches | respond continuously; one owner per lead | speed-to-lead responder (drafts) |
| **C** Convert | close rate, cycle length, follow-up latency, show rate | quotes wait for approval; no follow-up; long cycles | follow-up cadence; approval thresholds | follow-up sequences, decision brief, call script overlay |
| **E** Expand | churn, repeat/upsell rate, referrals | silent churn; no reason codes | exit interviews; renewal calendar | report generator, ticket triage (support-driven churn) |

## Traps
- **A lead flood answered in days.** The constraint is response speed (often a batching
  policy), not lead generation. An ad system would make it worse.
- **"We need more sales" while delivery is overloaded.** It's a back-end constraint. More
  demand only lengthens the queue (flooding trap); the demand-vs-capacity check catches this.
- **A weak RACE metric that is a symptom.** Slow quotes caused by an owner's sign-off rule are
  a policy constraint in management, not a sales problem.

## Benchmarks
Benchmarks are an open owner decision (§20); see `benchmarks.md`. Until then, compare a stage
with its own history and with sourced figures entered per engagement (`benchmark_source_id`).
