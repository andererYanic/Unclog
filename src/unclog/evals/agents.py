"""Systems under test and deterministic graders for Unclog's own agents (brief §9.5, §18)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from ..agents.base import AgentEscalation
from ..agents.goal_factoring import factor_goal
from ..agents.transcript_extractor import VerifiedCall, extract_call
from ..goalfactor import GoalTree
from ..ingestion import ingest_bytes
from ..llm import LLMClient
from ..schemas.design import ActionTag
from .cases import load_case
from .harness import AgentCase, Grade, System
from .runner import run_case

RUBRICS = {
    "transcript_extractor": (
        "Every fact is stated in the transcript and quoted verbatim; numbers, units and domains "
        "are right; estimates are marked; nothing is invented; open questions are useful."
    ),
    "goal_factoring": (
        "Actions are concrete, owner-assignable and doable in days; they act on, protect or gate "
        "the constraint; cheap non-AI fixes come first; at least one branch is non-obvious; "
        "nothing off-constraint is presented as a live action."
    ),
}


# ---- transcript extractor -----------------------------------------------------------------
def extractor_system(llm_factory: Callable[[], LLMClient]) -> System:
    llm = llm_factory()

    def run(case: AgentCase, i: int) -> VerifiedCall:
        r = ingest_bytes(case.input["transcript"].encode(), case.input.get("filename", "c.vtt"))
        return extract_call(llm, r.chunks, r.source.id, lang=case.input.get("lang", "de")).result

    def render(v: VerifiedCall) -> str:
        lines = [f"[{m.domain_id}] {m.name} = {m.value:g} {m.unit}" for m in v.metrics]
        lines += [f"policy {p.kind.value}: {p.statement}" for p in v.policies]
        lines += [f"rejected {r.kind}: {r.item.get('quote')}" for r in v.rejected]
        return "\n".join(lines)

    return System("transcript_extractor", run, lambda: llm.cost.total_usd, render)


def grade_extraction(case: AgentCase, v: VerifiedCall) -> Grade:
    exp = case.expect
    failures: list[str] = []
    wanted = exp.get("metrics", [])
    found = 0
    for w in wanted:
        tol = w.get("tolerance", 0.0)
        if any(
            m.domain_id == w["domain"] and abs(m.value - w["value"]) <= tol + 1e-9
            for m in v.metrics
        ):
            found += 1
        else:
            failures.append(f"missed {w['domain']}={w['value']}")
    recall = found / len(wanted) if wanted else 1.0
    forbidden = exp.get("forbidden_values", [])
    halluc = [m for m in v.metrics if m.value in forbidden]
    failures += [f"invented {m.name}={m.value:g}" for m in halluc]
    kinds = {p.kind.value for p in v.policies}
    missing_pol = [k for k in exp.get("policy_kinds", []) if k not in kinds]
    failures += [f"missed policy {k}" for k in missing_pol]
    pol_score = 1 - len(missing_pol) / max(1, len(exp.get("policy_kinds", [])))
    score = 10 * (
        0.5 * recall + 0.2 * v.acceptance_rate + 0.15 * pol_score + 0.15 * (0.0 if halluc else 1.0)
    )
    return Grade(round(score, 3), tuple(failures))


# ---- goal factoring -----------------------------------------------------------------------
def goal_factoring_system(llm_factory: Callable[[], LLMClient], cases_root: Path) -> System:
    llm = llm_factory()

    def run(case: AgentCase, i: int) -> GoalTree:
        c = load_case(cases_root / case.input["case"])
        res = run_case(c)
        b = res.report.binding
        if b is None:
            raise AgentEscalation("no confirmed constraint in diagnosis case")
        return factor_goal(
            llm,
            b,
            c.graph(),
            c.metrics,
            res.report.policy_audit.policies,
            lang=case.input.get("lang", "de"),
        ).result

    return System("goal_factoring", run, lambda: llm.cost.total_usd, lambda t: t.to_markdown("en"))


def grade_goal_tree(case: AgentCase, t: GoalTree) -> Grade:
    exp = case.expect
    live = t.base_actions(live_only=True)
    text = [a.statement.lower() for a in live]
    checks: dict[str, bool] = {
        "enough live actions": len(live) >= exp.get("min_live", 3),
        "non-AI fix present": any(a.tag is ActionTag.non_ai for a in live),
        "AI seed present": bool(t.opportunity_seeds()) if exp.get("needs_ai_seed", True) else True,
    }
    for group in exp.get("must_cover", []):
        checks[f"covers {group[0]}"] = any(re.search(g.lower(), s) for g in group for s in text)
    for bad in exp.get("forbidden_live", []):
        checks[f"no live '{bad}'"] = not any(bad.lower() in s for s in text)
    failures = tuple(k for k, ok in checks.items() if not ok)
    return Grade(round(10 * sum(checks.values()) / len(checks), 3), failures)


SYSTEMS = {
    "transcript_extractor": (extractor_system, [grade_extraction]),
    "goal_factoring": (goal_factoring_system, [grade_goal_tree]),
}
