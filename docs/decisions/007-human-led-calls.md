# 007 — Human-led client calls, agent-assisted; German and English

**Status:** accepted · 2026-11-05 (owner decision; answers the "delivery" question in 000)

A human consultant runs the client calls. The agents assist around each call:

- **Before:** `call_prep` builds a call plan from the bilingual first-call script
  (`knowledge/race/first_call_script.json`) and adds targeted follow-ups from what is already known
  (domains not yet assessed, constraint candidates, policies to challenge). It is deterministic: no
  model call, no cost.
- **After:** `transcript_extractor` (LLM) turns the transcript into structured facts: goal, unit of
  throughput, stage numbers, flow steps, rules and probe answers, each with a verbatim quote and
  locator. Every quote is then checked by code against the transcript. Facts whose quote can't be
  found are rejected, and numbers missing from their quote are flagged. Interview numbers are
  stored as estimates (`measured=false`) sourced to the transcript.
- **Then:** `flow_modeler` (LLM) drafts the market→cash flow from the extracted steps and table
  summaries. Code builds and validates the graph; validation errors go back to the model (capped
  retries). Unsupported numbers become assumptions with a confidence. `flow.from_eventlog` builds
  a measured flow fragment from event logs without any model.

All agent output is a draft for the consultant to review (brief §16). Questions and summaries come
in the engagement language (`Engagement.language`: `de` or `en`). Quotes always stay verbatim in
the language spoken.

Who attends the weekly team sync is still open (000).
