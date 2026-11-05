# Back-end domain playbooks

Back-end domains are first-class (brief §4.2). Per domain: what to measure, how to confirm,
cheap exploits, then the AI patterns from the library. Exploit before elevate; challenge rules
before automating around them.

## Fulfillment & delivery
- **Measure:** orders in vs delivered per week, backlog, lead time (median/p90), on-time rate;
  status-history export.
- **Confirm:** queue before the resource; relief test; expediting ("working Saturdays").
- **Exploit:** release by due date; complete kits before work starts; protect the constraint
  from interruptions.
- **Subordinate:** rope (WIP limit at release); honest delivery dates for held orders.
- **AI:** order pre-check (quality gate), throughput sequencing, buffer alerts.

## Operations & production
- **Measure:** utilization and queues per team/machine; setup/changeover times.
- **Exploit:** cut changeovers at the constraint; offload non-constraint tasks.
- **AI:** scheduling suggestions to the drum; anomaly alerts. Rules engines often suffice.

## Customer support & success
- **Measure:** tickets per week, first response, resolution, backlog, reopen rate.
- **Confirm:** helpdesk log waits; absence test ("when X is on holiday…").
- **Exploit:** triage rules; macros; stop KPIs that reward closing over solving.
- **AI:** ticket triage and reply drafting (agent approves).

## Finance & admin
- **Measure:** work-done → invoice lag, DSO, close cycle, approval waits.
- **Exploit:** invoice on completion, not in weekly batches; approval thresholds.
- **AI:** document pre-fill, reconciliation suggestions. GoBD: no unreviewed postings.

## HR & recruiting
- **Measure:** time to hire for critical roles, onboarding time.
- **Caution:** EU AI Act high-risk area and works-council co-determination (see
  `../regulations/eu-de.md`). Default to non-AI process fixes.

## Procurement & supply chain
- **Measure:** stockouts, supplier lead-time variance, expedite freight.
- **Exploit:** buffer stock only in front of the constraint; fixed reorder points.

## Product & engineering
- **Measure:** review/QA queue, release frequency, WIP per developer.
- **Exploit:** WIP limits; smaller batches (smaller pull requests); review rota.
- **AI:** review assistants. Watch the flooding trap: AI code drafts can pile up at review.

## IT, data & tooling
- **Measure:** hours of manual data movement, integration failures, reporting latency.
- **AI / non-AI:** data-sync jobs and scheduled reports. Plain scripts are often enough.

## Legal, risk & compliance
- **Measure:** review queue length and wait.
- **Exploit:** standard clauses and thresholds; prepare complete packages before review.

## Management & decision-making
- **Measure:** decisions waiting on the owner or a key person; approval wait times.
- **Typical constraint:** a sign-off rule or a single decision-maker (policy constraint).
- **Exploit:** raise thresholds, approve daily, delegate in tiers. Decision briefs make each
  decision take minutes.
