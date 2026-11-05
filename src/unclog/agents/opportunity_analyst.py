"""Opportunity Analyst (brief §8.4): opportunity seeds -> designed, scored Opportunity records.

Code decides: position on the flow, proven-first (library match, else R&D), process health,
ownership, code-owned scores, priority label, and the review-load check (G8: review at the
constraint costs throughput; review that pushes a resource past 85% creates a new constraint).
The model supplies design judgement per seed; structural problems go back to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from ..build.library import Match, Pattern, by_id, load_library, match
from ..flow.graph import FlowGraph
from ..llm import LLMClient
from ..schemas.common import Evidence
from ..schemas.design import (
    AIRole,
    ConstraintLink,
    GoalNode,
    Opportunity,
    Position,
    Priority,
    Risk,
    ScoreItem,
    Scores,
)
from ..schemas.diagnosis import Constraint, ConstraintType, Policy
from ..schemas.engagement import ProcessHealth
from ..scoring.opportunity import LINK_RELEVANCE, PROVEN_SCORE, priority_for, rank_score
from .base import AgentRun, load_prompt, run_structured

REVIEW_UTIL_LIMIT = 0.85


class JScore(BaseModel):
    score: int = Field(ge=1, le=5)
    justification: str


class JRisk(BaseModel):
    description: str
    category: Literal["data", "integration", "compliance", "change", "model", "security"]
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    mitigation: str | None = None


class JScores(BaseModel):
    throughput_impact: JScore
    feasibility: JScore
    data_readiness: JScore
    risk: JScore
    effort: JScore
    strategic_fit: JScore


class Judgement(BaseModel):
    seed_id: str
    pattern_id: str | None = None
    title: str
    ai_role: Literal["assist", "automate", "augment", "decide", "gate", "monitor"]
    human_in_loop_design: str
    release_gate_design: str | None = None
    items_per_week: float = Field(ge=0)
    review_minutes_per_item: float = Field(ge=0)
    reviewer_resource_id: str | None = None
    output_verification: str
    cost_of_error: Literal["low", "medium", "high"]
    simpler_non_ai_fix: str | None = None
    client_owner_role: str | None = None
    tech_approach: str
    build_vs_buy: Literal["build", "buy", "configure"]
    risks: list[JRisk] = Field(default_factory=list)
    scores: JScores


class AnalystOutput(BaseModel):
    judgements: list[Judgement]
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


@dataclass
class Seed:
    node: GoalNode
    position: Position
    candidates: list[Match]


@dataclass
class OpportunityAnalysis:
    opportunities: list[Opportunity]
    risks: list[Risk]
    findings: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def ranked(self) -> list[Opportunity]:
        return sorted(self.opportunities, key=lambda o: -rank_score(o))


def position_for(link: ConstraintLink, ctype: ConstraintType) -> Position:
    if link is ConstraintLink.off_constraint:
        return Position.off_flow
    if ctype is ConstraintType.market:
        return Position.market
    if link in (ConstraintLink.protects, ConstraintLink.gates_flow):
        return Position.upstream
    return Position.policy if ctype is ConstraintType.policy else Position.at_constraint


def make_seeds(
    seeds: list[GoalNode], constraint: Constraint, library: tuple[Pattern, ...] | None = None
) -> list[Seed]:
    return [
        Seed(s, position_for(s.constraint_link, constraint.type), match(s, constraint, library))
        for s in seeds
    ]


def _constraint_resources(
    constraint: Constraint, graph: FlowGraph | None, policies: list[Policy]
) -> set[str]:
    if constraint.resource_id:
        return {constraint.resource_id}
    if graph is None:
        return set()
    pol = next((p for p in policies if p.id == constraint.policy_id), None)
    nodes = pol.affects_node_ids if pol else []
    return {
        r for n in nodes if n in {x.id for x in graph.nodes} for r in graph.node(n).resource_ids
    }


def _process_ok(
    constraint: Constraint, policies: list[Policy], health: dict[str, ProcessHealth]
) -> tuple[bool, str | None]:
    keys = [constraint.domain_id]
    pol = next((p for p in policies if p.id == constraint.policy_id), None)
    if pol:
        keys += pol.affects_node_ids
    if constraint.resource_id:
        keys.append(constraint.resource_id)
    known = {k: health[k] for k in keys if k in health}
    if any(h is ProcessHealth.broken for h in known.values()):
        return False, None
    if not known:
        return True, (
            f"process health at {constraint.domain_id} not yet assessed; confirm the "
            "process is sound before building (brief §9.8)"
        )
    return True, None


def assemble(
    out: AnalystOutput,
    seeds: list[Seed],
    constraint: Constraint,
    graph: FlowGraph | None,
    policies: list[Policy],
    process_health: dict[str, ProcessHealth],
    library: tuple[Pattern, ...] | None = None,
) -> OpportunityAnalysis:
    by_seed = {s.node.id: s for s in seeds}
    problems: list[str] = []
    seen: set[str] = set()
    for j in out.judgements:
        s = by_seed.get(j.seed_id)
        if s is None:
            problems.append(f"{j.seed_id}: not a seed id")
            continue
        if j.seed_id in seen:
            problems.append(f"{j.seed_id}: judged twice")
        seen.add(j.seed_id)
        if j.pattern_id and j.pattern_id not in {m.pattern.id for m in s.candidates}:
            problems.append(
                f"{j.seed_id}: pattern {j.pattern_id!r} is not among its candidates "
                f"{[m.pattern.id for m in s.candidates]} (use null if none fits)"
            )
        if s.position is Position.upstream and not (j.release_gate_design or "").strip():
            problems.append(
                f"{j.seed_id}: works before the constraint; release_gate_design is "
                "required so output does not flood it"
            )
        if (
            graph is not None
            and j.reviewer_resource_id
            and j.reviewer_resource_id not in {r.id for r in graph.resources}
        ):
            problems.append(
                f"{j.seed_id}: reviewer_resource_id {j.reviewer_resource_id!r} is "
                "not a resource in the flow"
            )
    missing = set(by_seed) - seen
    if missing:
        problems.append(f"missing judgements for seeds {sorted(missing)}")
    if problems:
        raise ValueError("; ".join(problems))

    lib = library or load_library()
    loads = graph.resource_loads() if graph is not None else {}
    constraint_res = _constraint_resources(constraint, graph, policies)
    proc_ok, proc_note = _process_ok(constraint, policies, process_health)
    evidence: list[Evidence] = list(constraint.evidence)
    analysis = OpportunityAnalysis([], [], [], list(out.open_questions))
    if proc_note:
        analysis.open_questions.append(proc_note)
    extra_review: dict[str, float] = {}

    for j in out.judgements:
        s = by_seed[j.seed_id]
        pattern = by_id(j.pattern_id, lib) if j.pattern_id else None
        proven = bool(pattern and pattern.proven)
        relevance = LINK_RELEVANCE[s.node.constraint_link]
        owner = (j.client_owner_role or "").strip() or None
        scores = Scores(
            constraint_relevance=ScoreItem(
                score=relevance, justification=f"goal-tree link {s.node.constraint_link.value}"
            ),
            proven_ness=ScoreItem(
                score=PROVEN_SCORE[pattern.proven_status if pattern else None],
                justification=f"library: {pattern.proven_status}"
                if pattern
                else "no library pattern (novel)",
            ),
            ownership_clarity=ScoreItem(
                score=4 if owner else 1,
                justification=f"owner: {owner}" if owner else "no client owner named",
            ),
            **{
                k: ScoreItem(
                    score=getattr(j.scores, k).score,
                    justification=getattr(j.scores, k).justification,
                )
                for k in JScores.model_fields
            },
        )
        review_h = j.items_per_week * j.review_minutes_per_item / 60
        side_effects: list[str] = []
        prio, reason = priority_for(
            process_health_ok=proc_ok,
            constraint_link=s.node.constraint_link,
            rd=not proven,
            has_owner=owner is not None,
            focus_step=s.node.focus_step,
            constraint_relevance=relevance,
        )
        if j.reviewer_resource_id and review_h > 0 and j.reviewer_resource_id in loads:
            rl = loads[j.reviewer_resource_id]
            extra_review[j.reviewer_resource_id] = (
                extra_review.get(j.reviewer_resource_id, 0.0) + review_h
            )
            after = (rl.load_h + extra_review[j.reviewer_resource_id]) / rl.capacity_h
            if j.reviewer_resource_id in constraint_res:
                side_effects.append(
                    f"review adds {review_h:.1f} h/week at the constraint "
                    f"({j.reviewer_resource_id}); net effect must be positive"
                )
            if after >= REVIEW_UTIL_LIMIT:
                side_effects.append(
                    f"review pushes {j.reviewer_resource_id} to {after:.0%}: "
                    "creates a new constraint (G8)"
                )
                if prio not in (Priority.fix_process_first, Priority.do_not_pursue):
                    prio, reason = (
                        Priority.defer,
                        (
                            "review load would overload the reviewer; resize review or pick "
                            "another reviewer (G8)"
                        ),
                    )
                analysis.findings.append(f"G8 {j.seed_id}: {side_effects[-1]}")
        risk_ids = []
        for i, r in enumerate(j.risks, 1):
            rid = f"risk-{j.seed_id}-{i}"
            analysis.risks.append(
                Risk(
                    id=rid,
                    description=r.description,
                    category=r.category,
                    likelihood=r.likelihood,
                    impact=r.impact,
                    mitigation=r.mitigation,
                    assumption=True,
                    confidence=out.confidence,
                )
            )
            risk_ids.append(rid)
        if pattern and pattern.external_effect:
            side_effects.append("external effect: create as draft/paused until approved (G13)")
        assumptions = [reason]
        if j.simpler_non_ai_fix:
            assumptions.append(f"simpler non-AI fix to try first: {j.simpler_non_ai_fix}")
        if proc_note:
            assumptions.append(proc_note)
        grounding = {"evidence": evidence} if evidence else {"assumption": True}
        analysis.opportunities.append(
            Opportunity(
                id=f"opp-{j.seed_id}",
                goal_node_ids=[j.seed_id],
                title=j.title,
                pattern=pattern.id if pattern else None,
                ai_role=AIRole(j.ai_role),
                position=s.position,
                focus_step=s.node.focus_step,
                constraint_id=constraint.id,
                constraint_link=s.node.constraint_link,
                proven=proven,
                proof_refs=[pattern.ref, *pattern.references] if proven else [],
                rd_label=not proven,
                process_health_ok=proc_ok,
                client_owner=owner,
                wip_side_effects="; ".join(side_effects) or None,
                release_gate_required=s.position is Position.upstream,
                release_gate_design=j.release_gate_design,
                human_in_loop_design=j.human_in_loop_design,
                review_load_h_per_week=round(review_h, 2),
                reviewer_resource_id=j.reviewer_resource_id,
                tech_approach=j.tech_approach,
                build_vs_buy=j.build_vs_buy,
                risk_ids=risk_ids,
                scores=scores,
                priority=prio,
                assumptions=assumptions,
                confidence=round(min(out.confidence, constraint.confidence or 1.0), 2),
                **grounding,
            )
        )
    return analysis


def analyse_opportunities(
    llm: LLMClient,
    seeds: list[GoalNode],
    constraint: Constraint,
    graph: FlowGraph | None = None,
    policies: list[Policy] = (),
    process_health: dict[str, ProcessHealth] | None = None,
    lang: Literal["de", "en"] = "de",
    prompt_version: int | None = None,
) -> AgentRun[OpportunityAnalysis]:
    lib = load_library()
    ss = make_seeds(seeds, constraint, lib)
    prompt = load_prompt("opportunity_analyst", prompt_version)
    lines = [
        f"Engagement language: {lang}.",
        f"Constraint ({constraint.type.value}, {constraint.domain_id}): {constraint.description}",
    ]
    if graph is not None:
        loads = graph.resource_loads()
        lines.append(
            "Resources: "
            + "; ".join(f"{r.id} ({r.name}) {loads[r.id].utilization:.0%}" for r in graph.resources)
        )
    lines.append("Seeds:")
    for s in ss:
        cands = (
            ", ".join(
                f"{m.pattern.id} [{m.pattern.proven_status}]: {m.pattern.name[lang]}"
                for m in s.candidates
            )
            or "none (novel)"
        )
        lines.append(
            f"- {s.node.id} [{s.node.tag.value}, {s.node.focus_step.value}, "
            f"position {s.position.value}]: {s.node.statement} | candidates: {cands}"
        )
    return run_structured(
        llm,
        prompt,
        "\n".join(lines),
        AnalystOutput,
        lambda o: assemble(o, ss, constraint, graph, list(policies), process_health or {}, lib),
    )


def to_markdown(a: OpportunityAnalysis, lang: Literal["de", "en"] = "de") -> str:
    """AI Opportunity Map (brief §15.6): ranked, with position, step, proof, owner and priority."""
    h = {
        "en": (
            "Opportunity",
            "Position",
            "Step",
            "Proven",
            "Owner",
            "Review h/wk",
            "Score",
            "Priority",
            "Findings",
            "Open questions",
            "R&D",
        ),
        "de": (
            "Chance",
            "Position",
            "Schritt",
            "Bewährt",
            "Verantwortlich",
            "Prüfung h/Wo",
            "Score",
            "Priorität",
            "Befunde",
            "Offene Fragen",
            "F&E",
        ),
    }[lang]
    out = [f"| {' | '.join(h[:8])} |", "|" + "---|" * 8]
    for o in a.ranked():
        proven = o.pattern if o.proven else h[10]
        out.append(
            f"| {o.title} | {o.position.value} | {o.focus_step.value} | {proven} | "
            f"{o.client_owner or '–'} | {o.review_load_h_per_week or 0:g} | "
            f"{rank_score(o):.2f} | {o.priority.value} |"
        )
    if a.findings:
        out += ["", f"**{h[8]}:**", *[f"- {f}" for f in a.findings]]
    if a.open_questions:
        out += ["", f"**{h[9]}:**", *[f"- {q}" for q in a.open_questions]]
    return "\n".join(out)
