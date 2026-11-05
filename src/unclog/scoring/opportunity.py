"""Deterministic opportunity scoring and priority labels (brief §8.5, §8.7).

Code-owned dimensions: constraint relevance (from the goal-tree link), proven-ness (library
status), ownership clarity (named client owner). Judgement dimensions (throughput impact,
feasibility, data readiness, risk, effort, strategic fit) come with justifications from the
Opportunity Analyst. Rank = weighted score (1-5) × confidence.
"""

from __future__ import annotations

from ..schemas.design import ConstraintLink, Opportunity, Priority, Scores
from ..schemas.diagnosis import FocusStep

WEIGHTS = {
    "constraint_relevance": 3.0,
    "throughput_impact": 2.0,
    "feasibility": 1.5,
    "data_readiness": 1.0,
    "risk": 1.0,
    "effort": 1.0,
    "proven_ness": 1.5,
    "ownership_clarity": 1.5,
    "strategic_fit": 0.5,
}

LINK_RELEVANCE = {
    ConstraintLink.acts_on: 5,
    ConstraintLink.protects: 4,
    ConstraintLink.gates_flow: 4,
    ConstraintLink.off_constraint: 1,
}
PROVEN_SCORE = {"established": 5, "field-reported": 4, "emerging": 2, None: 1}


def weighted_score(scores: Scores) -> float:
    total = sum(WEIGHTS.values())
    return round(sum(getattr(scores, k).score * w for k, w in WEIGHTS.items()) / total, 3)


def rank_score(opp: Opportunity) -> float:
    if opp.scores is None:
        return 0.0
    return round(weighted_score(opp.scores) * (opp.confidence or 0.5), 3)


def priority_for(
    *,
    process_health_ok: bool,
    constraint_link: ConstraintLink,
    rd: bool,
    has_owner: bool,
    focus_step: FocusStep,
    constraint_relevance: int,
    has_realization_path: bool = False,
) -> tuple[Priority, str]:
    """Label + reason. Order matters: process health and constraint link come first."""
    if not process_health_ok:
        return (
            Priority.fix_process_first,
            "underlying process is broken: fix it before automating (brief §9.8)",
        )
    if constraint_link is ConstraintLink.off_constraint or (
        constraint_relevance <= 1 and not has_realization_path
    ):
        return Priority.defer, "not at, protecting or gating the constraint (NCX-10, §2.4)"
    if rd:
        return Priority.strategic_bet, "no proven pattern: R&D, scoped separately (§9.3)"
    if not has_owner:
        return Priority.defer, "no named client owner: nobody would run it after handover (G12)"
    return {
        FocusStep.exploit: (Priority.exploit_now, "exploit the constraint first (§8.7)"),
        FocusStep.subordinate: (Priority.subordinate, "subordinate flow to the constraint"),
        FocusStep.elevate: (Priority.elevate, "elevate only after exploit/subordinate results"),
    }.get(focus_step, (Priority.defer, "unclear focusing step"))
