# 011 — Eval harness, hill-climbing and the G14 gate

**Status:** accepted · 2026-11-05 (build plan step 11)

- **N-run harness** (`evals/harness.py`). Every case runs N ≥ 10 times. Per case it reports the
  mean, variance, worst run, spread and failure modes. A crash or escalation scores 0; it is not
  skipped. Reports are JSON files under `evals/results/<agent>/` and round-trip for later rating
  and comparison.
- **Uncached.** Eval clients run without the response cache (`make_llm(cache=False)`); with it,
  every replicate would get the same answer. `--model` overrides the default model, for re-runs
  when a new model ships.
- **Graders.** Code-based per agent (`evals/agents.py`):
  - transcript extractor: recall of expected numbers, quote acceptance, policy kinds, invented
    numbers
  - goal factoring: live-action count, non-AI fix, AI seed, required coverage, forbidden live
    actions

  An optional model-as-judge rubric grader (`--judge`) handles what code can't check, e.g. "at
  least one non-obvious branch".
- **Hill-climb rule** (`eval-compare`). Accept only if the mean improves and no case's worst run
  degrades; the case sets must match. Every decision is appended to
  `evals/results/hillclimb.jsonl` with what changed.
- **G14 gate.** Each case needs ≥ `min_runs_per_case` runs and a worst run at or above the floor,
  and the suite mean must reach the threshold. `eval-agent` exits non-zero on failure.
- **Human ratings** (`eval-rate`). Rate sample outputs 1–10 in the terminal; the average is the
  human baseline score (brief §9.5).
- **Agent eval cases** live in `evals/agents/<agent>/*.json`: two transcript cases (DE kitchen
  installer, EN SaaS with a forbidden-number trap) and two goal-factoring cases (owner sign-off
  policy, workshop overload with "more ads" forbidden). They grow with real engagements.

**Not done yet:** no live baseline exists, because there is no API key in this environment. The
first live `eval-agent` run per agent becomes the baseline, and later prompt or model changes are
compared against it.
