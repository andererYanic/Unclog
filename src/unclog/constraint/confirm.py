"""Confirmation tests (brief §8.2): relief, starvation, queue, expedite, absence.

Each test returns a ``ConfirmationTest`` plus the Evidence it produced. Tests that cannot run
(no data, not applicable) return ``None`` so they never count as failures or passes. Static flow
math is an approximation; the simulation engine (step 6) will re-run relief/starvation under
variability.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..flow.eventlog_stats import EventLogStats
from ..flow.graph import FlowGraph
from ..i18n import t as tr
from ..schemas.common import Evidence, EvidenceType, Source, SourceKind
from ..schemas.diagnosis import ConfirmationTest, ConstraintType, DomainName, TestKind
from .policy_audit import TextItem
from .text import ABSENCE, DOMAIN_KEYWORDS, EXPEDITE, mentions

DERIVED_SOURCE = Source(
    id="derived-flow-model",
    kind=SourceKind.measurement,
    title="Unclog flow model: load/capacity and what-if calculations (deterministic)",
)

RELIEF_FACTOR = 1.10
WAIT_THRESHOLD_H = 24.0
STARVED_BELOW = 0.85


def _eid(prefix: str, *content: object) -> str:
    """Deterministic evidence id from its content: same input, same id (reproducible runs,
    checkpoint keys stay stable; no hidden global counter)."""
    digest = hashlib.sha1("|".join(map(str, content)).encode()).hexdigest()[:10]
    return f"ev-{prefix}-{digest}"


@dataclass
class Candidate:
    """A constraint hypothesis being tested; becomes a schema Constraint in the analyst."""

    domain: DomainName
    type: ConstraintType
    target: str  # resource id | policy id | market segment
    node_ids: set[str]
    terms: list[str]
    heat_score: float
    description: str
    evidence: list[Evidence] = field(default_factory=list)
    tests: list[ConfirmationTest] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TestContext:
    graph: FlowGraph | None
    event_logs: list[tuple[str, EventLogStats, str]]  # (domain, stats, source_id)
    activity_nodes: dict[str, str]  # event-log activity -> node id
    texts: list[TextItem]
    sim_replications: int = 0  # >0: relief test by simulation (G9) instead of static math
    sim_horizon_weeks: float = 16
    lang: str = "en"


TestResult = tuple[ConfirmationTest, list[Evidence]] | None


def _sim_relief(c: Candidate, ctx: TestContext) -> TestResult:
    from ..simulation import Scenario, simulate  # local import: simulation depends on flow only

    if c.type is ConstraintType.physical:
        relief = Scenario(f"relief +10% {c.target}", capacity={c.target: RELIEF_FACTOR})
        what = tr("t_cap_plus", ctx.lang, p=f"{RELIEF_FACTOR - 1:.0%}", r=c.target)
    elif c.type is ConstraintType.market:
        relief = Scenario("relief +10% demand", arrival_scale=RELIEF_FACTOR)
        what = f"+{RELIEF_FACTOR - 1:.0%} demand"
    else:
        return None
    kw = {
        "replications": ctx.sim_replications,
        "horizon_weeks": ctx.sim_horizon_weeks,
        "warmup_weeks": 2,
    }
    base = simulate(ctx.graph, **kw)
    after = simulate(ctx.graph, relief, **kw)
    gain = (after.throughput.mean or 0) / max(base.throughput.mean or 1e-9, 1e-9) - 1
    # Significant: the relief scenario's 5th percentile beats the baseline mean.
    passed = gain > 0.02 and (after.throughput.p05 or 0) > (base.throughput.mean or 0)
    note = tr(
        "t_sim_relief",
        ctx.lang,
        what=what,
        a=base.throughput.fmt("/wk"),
        b=after.throughput.fmt("/wk"),
        g=f"{gain:+.1%}",
        n=ctx.sim_replications,
    )
    ev = Evidence(
        id=_eid("simrelief", c.target, note),
        source_id=DERIVED_SOURCE.id,
        type=EvidenceType.simulation,
        note=note,
    )
    return ConfirmationTest(kind=TestKind.relief, passed=passed, evidence_ids=[ev.id], note=note), [
        ev
    ]


def relief_test(c: Candidate, ctx: TestContext) -> TestResult:
    g = ctx.graph
    if g is None:
        return None
    if ctx.sim_replications > 0:
        return _sim_relief(c, ctx)
    before = g.effective_throughput()
    if c.type is ConstraintType.physical:
        after = g.with_capacity_scale(c.target, RELIEF_FACTOR).effective_throughput()
        passed = after > before * 1.005
        what = tr("t_cap_plus", ctx.lang, p=f"{RELIEF_FACTOR - 1:.0%}", r=c.target)
        why = "" if passed else tr("t_not_saturated", ctx.lang)
    elif c.type is ConstraintType.market:
        after = g.with_arrival_scale(RELIEF_FACTOR).effective_throughput()
        passed = after >= before * (1 + (RELIEF_FACTOR - 1) * 0.9)
        what = tr("t_demand_plus", ctx.lang, p=f"{RELIEF_FACTOR - 1:.0%}")
        why = "" if passed else tr("t_saturates", ctx.lang)
    else:
        return None
    note = tr("t_relief", ctx.lang, what=what, a=f"{before:.2f}", b=f"{after:.2f}", why=why)
    ev = Evidence(
        id=_eid("relief", c.target, note),
        source_id=DERIVED_SOURCE.id,
        type=EvidenceType.load_capacity_calc,
        note=note,
    )
    return ConfirmationTest(kind=TestKind.relief, passed=passed, evidence_ids=[ev.id], note=note), [
        ev
    ]


def _idle_capacity_test(c: Candidate, g: FlowGraph, lang: str = "en") -> TestResult:
    """Market version of starvation: every resource has slack and nothing waits internally."""
    loads = [r for r in g.resource_loads().values() if r.load_h > 0]
    waits = {n: w for n, w in _node_wait(g).items() if w >= WAIT_THRESHOLD_H}
    busiest = max(loads, key=lambda r: r.utilization) if loads else None
    passed = bool(loads) and busiest.utilization < STARVED_BELOW and not waits
    note = (
        tr("t_idle_busiest", lang, r=busiest.resource_id, u=f"{busiest.utilization:.0%}")
        if busiest
        else tr("t_idle_none", lang)
    )
    note += (
        tr("t_idle_ok", lang) if not waits else tr("t_idle_waits", lang, x=", ".join(sorted(waits)))
    )
    ev = Evidence(
        id=_eid("idle", c.target, note),
        source_id=DERIVED_SOURCE.id,
        type=EvidenceType.load_capacity_calc,
        note=note,
    )
    return ConfirmationTest(
        kind=TestKind.starvation, passed=passed, evidence_ids=[ev.id], note=note
    ), [ev]


def starvation_test(c: Candidate, ctx: TestContext) -> TestResult:
    g = ctx.graph
    if g is not None and c.type is ConstraintType.market:
        return _idle_capacity_test(c, g, ctx.lang)
    if g is None or c.type is not ConstraintType.physical:
        return None
    loads = g.resource_loads()
    u_c = loads[c.target].utilization
    down_nodes = g.downstream_nodes(c.node_ids)
    down_res = {r for n in down_nodes for r in g.node(n).resource_ids} - {c.target}
    if not down_res:
        return None
    eff = {r: loads[r].utilization / max(1.0, u_c) for r in down_res}
    passed = all(u < STARVED_BELOW for u in eff.values()) and all(u < u_c for u in eff.values())
    detail = ", ".join(f"{r} {u:.0%}" for r, u in sorted(eff.items()))
    note = tr("t_starve", ctx.lang, r=c.target, u=f"{u_c:.0%}", detail=detail) + (
        tr("t_starved", ctx.lang) if passed else tr("t_busier", ctx.lang)
    )
    ev = Evidence(
        id=_eid("starve", c.target, note),
        source_id=DERIVED_SOURCE.id,
        type=EvidenceType.load_capacity_calc,
        note=note,
    )
    return ConfirmationTest(
        kind=TestKind.starvation, passed=passed, evidence_ids=[ev.id], note=note
    ), [ev]


def _node_wait(g: FlowGraph) -> dict[str, float]:
    out = {}
    for nid, nl in g.node_loads().items():
        if nl.observed_wait_h is not None:
            out[nid] = nl.observed_wait_h
    return out


def queue_test(c: Candidate, ctx: TestContext) -> TestResult:
    if c.type is ConstraintType.market:
        return None  # a market constraint has no internal queue; see _idle_capacity_test
    evidence: list[Evidence] = []
    found: list[str] = []
    best_here = 0.0
    g = ctx.graph
    if g is not None:
        waits = _node_wait(g)
        for nid in sorted(c.node_ids):
            node = g.node(nid)
            w = waits.get(nid)
            q = node.queue_length or 0
            if (w is not None and w >= WAIT_THRESHOLD_H) or q > 0:
                best_here = max(best_here, w or 0.0)
                data_src = next(
                    (
                        e.source_id
                        for e in node.evidence
                        if e.type
                        in (
                            EvidenceType.queue_observation,
                            EvidenceType.log_data,
                            EvidenceType.measurement,
                        )
                    ),
                    None,
                )
                desc = f"{node.name}: " + ", ".join(
                    x
                    for x in (
                        tr("queued", ctx.lang, q=f"{q:g}") if q else "",
                        tr("wait", ctx.lang, w=f"{w:.0f}") if w is not None else "",
                    )
                    if x
                )
                found.append(desc)
                if data_src and not node.assumption:
                    evidence.append(
                        Evidence(
                            id=_eid("queue", data_src, nid, desc),
                            source_id=data_src,
                            type=EvidenceType.queue_observation,
                            locator=f"node {nid}",
                            note=desc,
                        )
                    )
    for _dom, st, src in ctx.event_logs:
        for act, a in st.activities.items():
            if (
                ctx.activity_nodes.get(act) in c.node_ids
                and (a.wait_median_h or 0) >= WAIT_THRESHOLD_H
            ):
                best_here = max(best_here, a.wait_median_h)
                desc = tr(
                    "t_log_wait",
                    ctx.lang,
                    w=f"{a.wait_median_h:.0f}",
                    a=act,
                    p90=f"{a.wait_p90_h:.0f}",
                    n=a.count,
                )
                found.append(desc)
                evidence.append(
                    Evidence(
                        id=_eid("queue", src, act, desc),
                        source_id=src,
                        type=EvidenceType.log_data,
                        locator=f"activity {act}",
                        note=desc,
                    )
                )
    if not found:
        if g is None and not ctx.event_logs:
            return None
        note = tr("t_queue_none", ctx.lang)
        return ConfirmationTest(kind=TestKind.queue, passed=False, note=note), []
    passed = True
    note = "; ".join(found)
    if g is not None:
        waits = _node_wait(g)
        others = {n: w for n, w in waits.items() if n not in c.node_ids}
        if others:
            top, w_top = max(others.items(), key=lambda kv: kv[1])
            if best_here and w_top > 2 * best_here:
                passed = False
                note += tr("t_queue_longer", ctx.lang, n=top, w=f"{w_top:.0f}")
    return ConfirmationTest(
        kind=TestKind.queue, passed=passed, evidence_ids=[e.id for e in evidence], note=note
    ), evidence


def _text_test(
    c: Candidate, ctx: TestContext, rx, kind: TestKind, etype: EvidenceType
) -> TestResult:
    if not ctx.texts:
        return None
    terms = c.terms
    evidence = []
    for item in ctx.texts:
        for sentence in item.text.replace("\n", " ").split(". "):
            if rx.search(sentence) and mentions(sentence, terms):
                evidence.append(
                    Evidence(
                        id=_eid(kind.value, item.source_id, item.locator, sentence.strip()),
                        source_id=item.source_id,
                        type=etype if item.testimony else EvidenceType.document,
                        locator=item.locator,
                        quote=sentence.strip()[:300],
                    )
                )
    if not evidence:
        return None  # absence of a quote is not evidence against the candidate
    note = tr("t_statements", ctx.lang, n=len(evidence), q=evidence[0].quote)
    return ConfirmationTest(
        kind=kind, passed=True, evidence_ids=[e.id for e in evidence], note=note
    ), evidence


def expedite_test(c: Candidate, ctx: TestContext) -> TestResult:
    return _text_test(c, ctx, EXPEDITE, TestKind.expedite, EvidenceType.expedite_signal)


def absence_test(c: Candidate, ctx: TestContext) -> TestResult:
    if c.type is not ConstraintType.physical:
        return None
    return _text_test(c, ctx, ABSENCE, TestKind.absence, EvidenceType.absence_test)


ALL_TESTS = (relief_test, starvation_test, queue_test, expedite_test, absence_test)


def candidate_terms(domain: DomainName, *names: str) -> list[str]:
    words = [w for n in names for w in n.replace("-", " ").replace("_", " ").split() if len(w) > 3]
    return sorted({*words, *DOMAIN_KEYWORDS.get(domain, ())})
