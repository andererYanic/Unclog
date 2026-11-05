# 008 — Goal factoring

**Status:** accepted · 2026-11-05 (build plan step 8)

**Split of work.** Code computes the root goal from the confirmed constraint and the data:
- physical: throughput through the resource → demand, or +25% if demand is unknown
- policy: wait at the affected node → the stage benchmark, else 24 h
- market: the worst-gap stage metric → its benchmark

Code also provides a skeleton of options per constraint type (exploit, subordinate, elevate, plus
a policy branch), validates the tree, prunes and ranks. The Goal Factoring agent
(`prompts/goal_factoring/v1.md`) proposes options and base actions under the skeleton. Every
problem in a draft goes back to the model in one round trip (capped retries, then escalation).

**Rules (in `GoalTree`):**
- One root; everything traces to it.
- Live base actions sit at depth ≥2, are doable in ≤10 days, and carry a tag, a constraint link
  and a focusing step.
- At least 3 live actions.
- At least one `non_ai` fix ("no AI" is a valid answer).
- At least one exploit action (exploit before elevate).
- For policy constraints, the policy branch must keep a live action: challenge the rule before
  automating around it.

**Pruning.** `off_constraint` actions are pruned (value zero, NCX-10). Options left with no live
action are pruned too. Pruned items stay in the tree so the report can say why an attractive
idea isn't pursued.

**Ranking.** By focusing step (exploit → subordinate → elevate), then link (acts on → protects →
gates flow), then effort. AI-doable and AI-assisted live actions are the *opportunity seeds* for
step 9.

**Not checked by code:** "at least one non-obvious branch" (brief §7) needs judgment. It is in the
prompt and becomes an eval-rubric item in step 11.
