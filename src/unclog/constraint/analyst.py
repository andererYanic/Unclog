"""Constraint identification (Five Focusing Steps, Step 1; brief §8.2, gate G4).

Pipeline: heat-table candidates -> typed hypotheses (physical / policy / market) -> signal
evidence -> confirmation tests -> status. A hypothesis is ``confirmed`` only with >=2 independent
evidence families, a passed test and the both-direction check. If nothing is confirmed, the
report allows **discovery actions only** (instrumentation, data collection): no AI use cases are
ranked on guesswork.

Typing rules:
- **physical**: a resource serving the domain is at or above the utilization threshold.
- **policy**: a batch/approval policy affects the domain's nodes (structural or textual).
- **market**: the both-direction check says capacity is ample, the domain is a RACE stage, and no
  internal queue contradicts it (a market constraint leaves capacity idle and nothing waits).
Anything else stays *unresolved*, with the discovery action that would resolve it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domains.heat import DirectionVerdict, HeatTable, SignalKind
from ..flow.eventlog_stats import EventLogStats
from ..flow.graph import FlowGraph
from ..schemas.common import Evidence, EvidenceFamily, EvidenceType, Source
from ..schemas.diagnosis import (
    REQUIRED_DOMAINS,
    Constraint,
    ConstraintStatus,
    ConstraintType,
    DomainName,
    DomainVerdict,
    PolicyKind,
)
from .confirm import (
    ALL_TESTS,
    DERIVED_SOURCE,
    WAIT_THRESHOLD_H,
    Candidate,
    TestContext,
    _eid,
    candidate_terms,
)
from .policy_audit import PolicyAudit, TextItem, audit

DOMAIN_METRIC_HINTS: dict[DomainName, str] = {
    DomainName.race_r: "visitors/impressions per week, ad spend, creative volume",
    DomainName.race_a: "leads per week, speed-to-lead (median first response), booked rate",
    DomainName.race_c: "close rate, sales-cycle length, follow-up latency, show rate",
    DomainName.race_e: "churn, repeat/upsell rate, LTV",
    DomainName.fulfillment: "orders in vs delivered per week, backlog, lead time, on-time rate",
    DomainName.ops: "utilization and queues per team/machine",
    DomainName.support: "ticket backlog, first-response and resolution time",
    DomainName.finance: "invoice lag, DSO, close cycle, approval waits",
    DomainName.hr: "time to hire, open critical roles, onboarding time",
    DomainName.procurement: "stockouts, supplier lead-time variance",
    DomainName.product: "release queue, review/QA wait",
    DomainName.it: "manual data-movement hours, integration failures, reporting latency",
    DomainName.legal: "review queue length and wait",
    DomainName.mgmt: "decisions waiting on the owner/key person, approval wait times",
}


@dataclass(frozen=True)
class Unresolved:
    domain: DomainName
    reason: str
    actions: tuple[str, ...]


@dataclass(frozen=True)
class NextConstraint:
    kind: str  # physical | market
    resource_id: str | None
    description: str


@dataclass
class ConstraintReport:
    binding: Constraint | None
    confirmed: list[Constraint]
    candidates: list[Constraint]  # tested but not confirmed
    unresolved: list[Unresolved]
    discovery_actions: list[str]
    next_constraint: NextConstraint | None
    policy_audit: PolicyAudit
    direction: DirectionVerdict
    derived_sources: list[Source] = field(default_factory=list)

    @property
    def work_mode(self) -> str:
        """G4: without a confirmed constraint only discovery work is allowed."""
        return "full" if self.binding is not None else "discovery_only"


# ---- evidence from heat signals -----------------------------------------------------------
def _signal_evidence(row, graph: FlowGraph | None, metrics_by_id) -> list[Evidence]:
    out: list[Evidence] = []
    for s in row.signals:
        if (
            s.kind is SignalKind.capacity
            and graph is not None
            and s.refs
            and s.refs[0] in {r.id for r in graph.resources}
        ):
            out.append(
                Evidence(
                    id=_eid("cap"),
                    source_id=DERIVED_SOURCE.id,
                    type=EvidenceType.load_capacity_calc,
                    note=s.detail,
                )
            )
        elif s.kind is SignalKind.capacity:  # event-log backlog growth
            out.append(
                Evidence(
                    id=_eid("cap"), source_id=s.refs[0], type=EvidenceType.log_data, note=s.detail
                )
            )
        elif (
            s.kind is SignalKind.queue
            and graph is not None
            and s.refs
            and s.refs[0] in {n.id for n in graph.nodes}
        ):
            node = graph.node(s.refs[0])
            src = next((e.source_id for e in node.evidence), None)
            if src and not node.assumption and s.measured:
                out.append(
                    Evidence(
                        id=_eid("q"),
                        source_id=src,
                        type=EvidenceType.queue_observation,
                        note=s.detail,
                    )
                )
        elif s.kind is SignalKind.queue:  # event log
            out.append(
                Evidence(
                    id=_eid("q"),
                    source_id=s.refs[0],
                    type=EvidenceType.log_data,
                    locator=f"activity {s.refs[1]}" if len(s.refs) > 1 else None,
                    note=s.detail,
                )
            )
        elif s.kind is SignalKind.conversion:
            m = metrics_by_id.get(s.refs[0]) if s.refs else None
            if m is not None and m.source_id:
                out.append(
                    Evidence(
                        id=_eid("conv"),
                        source_id=m.source_id,
                        type=EvidenceType.log_data if m.measured else EvidenceType.interview_claim,
                        locator=f"metric {m.id}",
                        note=s.detail,
                    )
                )
    return out


def _families(ev: list[Evidence]) -> set[EvidenceFamily]:
    from ..schemas.common import EVIDENCE_FAMILY

    fams = {EVIDENCE_FAMILY[e.type] for e in ev}
    fams.discard(EvidenceFamily.reference)
    return fams


# ---- hypothesis generation ------------------------------------------------------------------
def _hypotheses(
    heat: HeatTable, graph: FlowGraph | None, pa: PolicyAudit, util_threshold: float
) -> tuple[list[Candidate], list[Unresolved]]:
    cands: list[Candidate] = []
    unresolved: list[Unresolved] = []
    seen_resources: set[str] = set()
    seen_policies: set[str] = set()
    metrics_by_id = {m.id: m for r in heat.rows for m in r.metrics}
    internal_queues = _internal_queue_domains(heat)

    for row in heat.candidates():
        made = False
        sig_ev = _signal_evidence(row, graph, metrics_by_id)
        # physical
        if graph is not None:
            loads = graph.resource_loads()
            for node in graph.nodes:
                if node.domain_id != row.domain.value:
                    continue
                for rid in node.resource_ids:
                    if rid in seen_resources or loads[rid].utilization < util_threshold:
                        continue
                    seen_resources.add(rid)
                    res = next(r for r in graph.resources if r.id == rid)
                    nodes = set(loads[rid].node_ids)
                    cands.append(
                        Candidate(
                            domain=row.domain,
                            type=ConstraintType.physical,
                            target=rid,
                            node_ids=nodes,
                            terms=candidate_terms(
                                row.domain, res.name, rid, *(graph.node(n).name for n in nodes)
                            ),
                            heat_score=row.score,
                            description=f"{res.name} ({rid}) at {loads[rid].utilization:.0%} of "
                            f"capacity in {row.domain.value}",
                            evidence=list(sig_ev),
                        )
                    )
                    made = True
        # policy
        for p in pa.flow_capping():
            if p.id in seen_policies or p.domain_id != row.domain.value:
                continue
            if p.kind not in (PolicyKind.batch_rule, PolicyKind.approval):
                continue
            seen_policies.add(p.id)
            nodes = set(p.affects_node_ids)
            names = [graph.node(n).name for n in nodes] if graph is not None else []
            cands.append(
                Candidate(
                    domain=row.domain,
                    type=ConstraintType.policy,
                    target=p.id,
                    node_ids=nodes,
                    terms=candidate_terms(row.domain, *names),
                    heat_score=row.score,
                    description=f"Policy: {p.statement}",
                    evidence=[*sig_ev, *p.evidence],
                )
            )
            made = True
        # market
        if (
            not made
            and row.domain.is_race
            and heat.direction.verdict is DirectionVerdict.market_limited
        ):
            contradicting = sorted(d.value for d in internal_queues - {row.domain})
            nodes = (
                {n.id for n in graph.nodes if n.domain_id == row.domain.value} if graph else set()
            )
            c = Candidate(
                domain=row.domain,
                type=ConstraintType.market,
                target=f"{row.domain.value} stage",
                node_ids=nodes,
                terms=candidate_terms(row.domain),
                heat_score=row.score,
                description=f"Market: demand/conversion at {row.domain.value} limits throughput "
                "while capacity is ample",
                evidence=list(sig_ev),
            )
            if contradicting:
                c.notes.append(
                    "internal queues at "
                    + ", ".join(contradicting)
                    + " contradict a market constraint"
                )
            cands.append(c)
            made = True
        if not made:
            unresolved.append(_explain_unresolved(row, heat))
    return cands, unresolved


def _internal_queue_domains(heat: HeatTable) -> set[DomainName]:
    return {
        r.domain
        for r in heat.rows
        if any(s.kind is SignalKind.queue and s.measured for s in r.signals)
    }


def _explain_unresolved(row, heat: HeatTable) -> Unresolved:
    kinds = {s.kind for s in row.signals}
    actions = []
    if not row.has_flow_data:
        actions.append(
            f"Map the {row.domain.value} stage in the flow (volumes, service times, "
            "who does the work) so load/capacity can be computed"
        )
    if SignalKind.queue not in kinds:
        actions.append(
            f"Export timestamps/status history for {row.domain.value} to measure where work waits"
        )
    if all(not s.measured for s in row.signals):
        actions.append(
            f"Replace estimates for {row.domain.value} with measured data "
            f"({DOMAIN_METRIC_HINTS.get(row.domain, 'stage metrics')})"
        )
    if heat.direction.verdict is DirectionVerdict.capacity_limited and row.domain.is_race:
        reason = (
            f"{row.domain.value} looks weak, but the system is capacity-limited at "
            f"{heat.direction.bottleneck_resource}: more demand would only queue up there"
        )
    elif kinds == {SignalKind.conversion} and not row.domain.is_race:
        reason = (
            f"{row.domain.value} metric is off-benchmark but no resource/queue explains "
            "it; may be a symptom of a constraint elsewhere"
        )
    else:
        reason = f"signals at {row.domain.value} do not yet point to a resource, policy or market"
    return Unresolved(row.domain, reason, tuple(actions))


# ---- status ---------------------------------------------------------------------------------
def _to_constraint(c: Candidate, direction_checked: bool) -> Constraint:
    fams = _families(c.evidence)
    passed = [t for t in c.tests if t.passed]
    contradicted = bool(c.notes) and c.type is ConstraintType.market
    if c.type is ConstraintType.market and EvidenceFamily.data not in fams:
        # The model only shows capacity is ample (constraint is "outside"); locating it at a
        # specific RACE stage needs measured data on that stage, not an estimate.
        c.notes.append("stage located only by estimates; needs measured stage data")
        contradicted = True
    confirmed = len(fams) >= 2 and bool(passed) and direction_checked and not contradicted
    conf = (
        min(0.95, 0.6 + 0.1 * (len(fams) - 2) + 0.05 * len(passed))
        if confirmed
        else min(0.45, 0.15 + 0.1 * len(fams) + 0.05 * len(passed))
    )
    kw: dict = {}
    if c.type is ConstraintType.physical:
        kw["resource_id"] = c.target
    elif c.type is ConstraintType.policy:
        kw["policy_id"] = c.target
    elif c.type is ConstraintType.market:
        kw["market_segment"] = c.target
    queue_notes = [t.note for t in c.tests if t.kind.value == "queue" and t.passed]
    grounding = {"evidence": c.evidence} if c.evidence else {"assumption": True}
    return Constraint(
        id=f"con-{c.domain.value}-{c.target}".replace(" ", "-")[:120],
        type=c.type,
        domain_id=c.domain.value,
        description=c.description + ("" if not c.notes else f" [{'; '.join(c.notes)}]"),
        load_capacity_ratio=None,
        queue_evidence=queue_notes[0] if queue_notes else None,
        status=ConstraintStatus.confirmed if confirmed else ConstraintStatus.candidate,
        tests_run=c.tests,
        demand_vs_capacity_checked=direction_checked,
        confidence=round(conf, 2),
        **grounding,
        **kw,
    )


def _predict_next(
    graph: FlowGraph | None, binding: Constraint | None, util_threshold: float
) -> NextConstraint | None:
    if graph is None or binding is None:
        return None
    g = graph
    if binding.type is ConstraintType.physical and binding.resource_id:
        u = g.resource_loads()[binding.resource_id].utilization
        g = g.with_capacity_scale(binding.resource_id, max(1.0, u / util_threshold * 1.0001))
    others = [
        r
        for r in g.resource_loads().values()
        if r.load_h > 0 and r.resource_id != binding.resource_id
    ]
    b = max(others, key=lambda r: r.utilization) if others else None
    head = g.demand_headroom()
    if binding.type is ConstraintType.market and b is not None:
        return NextConstraint(
            "physical",
            b.resource_id,
            f"If demand grows ~{head:.0%}, {b.resource_id} saturates first.",
        )
    if b is not None and b.utilization >= 0.8:
        return NextConstraint(
            "physical",
            b.resource_id,
            f"After relief, {b.resource_id} is the busiest other resource at "
            f"{b.utilization:.0%}; watch its queue.",
        )
    return NextConstraint(
        "market",
        None,
        "After relief, capacity is ample: expect the market (RACE) to become "
        f"the constraint (~{head:.0%} demand headroom). Re-run Step 1.",
    )


def _discovery_actions(
    heat: HeatTable, cands: list[Constraint], unresolved: list[Unresolved], graph: FlowGraph | None
) -> list[str]:
    acts: list[str] = []
    if graph is None:
        acts.append(
            "Map one unit of throughput from market to cash with weekly volumes per "
            "stage, who does the work, and how long it takes (brief §8.1)"
        )
    for r in heat.rows:
        if r.domain in REQUIRED_DOMAINS and r.verdict is DomainVerdict.not_assessed:
            acts.append(
                f"Get a sourced metric for {r.domain.value}: {DOMAIN_METRIC_HINTS[r.domain]}"
            )
    for c in cands:
        if c.status is ConstraintStatus.confirmed:
            continue
        fams = c.confirming_families()
        if EvidenceFamily.data not in fams:
            acts.append(
                f"{c.id}: export timestamps or queue counts to measure the wait in front of it"
            )
        if EvidenceFamily.testimony not in fams and c.type is ConstraintType.physical:
            acts.append(
                f"{c.id}: ask 'If {c.resource_id} took a day off, what would stop?' "
                "and 'What do you expedite?'"
            )
        if EvidenceFamily.model not in fams and c.type is not ConstraintType.policy:
            acts.append(f"{c.id}: add volumes and service times to compute load vs capacity")
    for u in unresolved:
        acts += [f"{u.domain.value}: {a}" for a in u.actions]
    return list(dict.fromkeys(acts))


def identify(
    heat: HeatTable,
    graph: FlowGraph | None = None,
    event_logs: list[tuple[str, EventLogStats, str]] = (),
    texts: list[TextItem] = (),
    activity_nodes: dict[str, str] | None = None,
    sim_replications: int = 0,
) -> ConstraintReport:
    """``sim_replications > 0`` runs the relief test as a simulation (G9-grade evidence)."""
    texts = list(texts) + _quotes_from_graph(graph)
    pa = audit(graph, texts)
    cfg = heat.config
    cands, unresolved = _hypotheses(heat, graph, pa, cfg.util_candidate)
    ctx = TestContext(
        graph, list(event_logs), activity_nodes or {}, texts, sim_replications=sim_replications
    )
    for c in cands:
        for test in ALL_TESTS:
            res = test(c, ctx)
            if res is not None:
                t, ev = res
                c.tests.append(t)
                c.evidence += ev
    direction_checked = heat.direction.verdict is not DirectionVerdict.no_flow_data
    constraints = [_to_constraint(c, direction_checked) for c in cands]
    score = {id(k): c.heat_score for k, c in zip(constraints, cands, strict=True)}
    confirmed = sorted(
        (k for k in constraints if k.status is ConstraintStatus.confirmed),
        key=lambda k: (-score[id(k)], -(k.confidence or 0)),
    )
    pending = [k for k in constraints if k.status is not ConstraintStatus.confirmed]
    binding = confirmed[0] if confirmed else None
    uses_model = any(e.source_id == DERIVED_SOURCE.id for k in constraints for e in k.evidence)
    return ConstraintReport(
        binding=binding,
        confirmed=confirmed,
        candidates=pending,
        unresolved=unresolved,
        discovery_actions=_discovery_actions(heat, constraints, unresolved, graph),
        next_constraint=_predict_next(graph, binding, cfg.util_candidate),
        policy_audit=pa,
        direction=heat.direction.verdict,
        derived_sources=[DERIVED_SOURCE] if uses_model else [],
    )


def _quotes_from_graph(graph: FlowGraph | None) -> list[TextItem]:
    """Interview/document quotes attached as evidence in the flow model are text evidence too."""
    if graph is None:
        return []
    items, seen = [], set()
    for obj in [*graph.nodes, *graph.resources]:
        for e in obj.evidence:
            if e.quote and (e.source_id, e.quote) not in seen:
                seen.add((e.source_id, e.quote))
                items.append(
                    TextItem(
                        e.source_id,
                        e.locator or obj.id,
                        e.quote,
                        testimony=e.type is EvidenceType.interview_claim,
                    )
                )
    return items


__all__ = ["ConstraintReport", "NextConstraint", "Unresolved", "identify", "WAIT_THRESHOLD_H"]
