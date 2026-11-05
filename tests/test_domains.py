import pytest

from unclog.domains import (
    DirectionVerdict,
    SignalKind,
    build_heat_table,
    conversions,
    to_markdown,
    worst_step,
)
from unclog.flow import FlowGraph
from unclog.schemas import FlowEdge, FlowNode, Resource, StageMetric
from unclog.schemas.diagnosis import Distribution as D
from unclog.schemas.diagnosis import DomainVerdict

A = dict(assumption=True, confidence=0.5)


def metric(id_, dom, value, bm=None, hib=None, measured=True, src="src1"):
    return StageMetric(
        id=id_,
        domain_id=dom,
        name=id_,
        value=value,
        unit="u",
        period="p",
        benchmark=bm,
        higher_is_better=hib,
        measured=measured,
        source_id=src if (measured or src) else None,
    )


def graph(util_hours, svc_h=1.0, dom="fulfillment", evidence=True):
    """One resource at util_hours/40 utilization; resource grounded by evidence if asked."""
    from unclog.schemas import Evidence

    grounding = (
        {"evidence": [Evidence(id="e1", source_id="src-log", type="log_data")]} if evidence else A
    )
    return FlowGraph(
        [
            FlowNode(
                id="in",
                name="in",
                domain_id="RACE-R",
                arrival=D(kind="poisson", params={"rate": util_hours / svc_h}, unit="week"),
                **A,
            ),
            FlowNode(
                id="work",
                name="work",
                domain_id=dom,
                resource_ids=["r"],
                service=D(kind="fixed", params={"value": svc_h}, unit="hour"),
                **grounding,
            ),
        ],
        [FlowEdge(source="in", target="work")],
        [Resource(id="r", name="r", kind="team", hours_per_period=40, **grounding)],
    )


def test_funnel():
    steps = conversions(
        [("leads", 400), ("booked", 36), ("won", 11)], {"booked": 0.25, "won": 0.30}
    )
    assert steps[0].rate == pytest.approx(0.09) and steps[0].relative_gap == pytest.approx(0.64)
    assert worst_step(steps).to_stage == "booked"
    assert conversions([("a", 0), ("b", 1)])[0].rate is None


def test_measured_backend_beats_race_estimate_despite_prior():
    t = build_heat_table(
        [metric("conv", "RACE-C", 0.01, bm=0.02, hib=True, measured=False, src=None)], graph(46)
    )
    assert t.ranked()[0].domain.value == "fulfillment"
    assert t.row("RACE-C").verdict is DomainVerdict.candidate
    assert t.direction.verdict is DirectionVerdict.capacity_limited
    assert "flooding" in t.direction.note


def test_prior_only_breaks_ties():
    t = build_heat_table(
        [
            metric("a", "RACE-A", 0.1, bm=0.2, hib=True),
            metric("s", "support", 0.1, bm=0.2, hib=True),
        ]
    )
    ranked = [r.domain.value for r in t.ranked()[:2]]
    assert ranked == ["RACE-A", "support"]
    assert t.row("RACE-A").score - t.row("support").score == pytest.approx(0.15 - 0.04)


def test_verdicts_never_auto_constraint_and_clear_needs_source():
    t = build_heat_table(
        [
            metric("ok", "finance", 30, bm=30, hib=False),
            metric("guess", "hr", 5, measured=False, src=None),
        ],
        graph(20),
    )
    assert all(r.verdict is not DomainVerdict.constraint for r in t.rows)
    assert t.row("finance").verdict is DomainVerdict.clear
    assert t.row("hr").verdict is DomainVerdict.not_assessed
    assert "unsourced" in t.row("hr").rationale
    for r in t.rows:
        r.to_domain()  # every row is a valid Domain record


def test_lower_is_better_gap_and_text():
    t = build_heat_table([metric("speed", "RACE-A", 52, bm=1, hib=False)])
    s = t.row("RACE-A").signals[0]
    assert s.kind is SignalKind.conversion and s.severity == 1.0 and "52x" in s.detail


def test_direction_check_variants():
    assert build_heat_table([], graph(20)).direction.verdict is DirectionVerdict.market_limited
    assert build_heat_table([], graph(34)).direction.verdict is DirectionVerdict.inconclusive
    assert build_heat_table([], None).direction.verdict is DirectionVerdict.no_flow_data
    front = build_heat_table([], graph(50, dom="RACE-A"))
    assert front.direction.verdict is DirectionVerdict.capacity_limited
    assert "flooding" not in front.direction.note


def test_unmeasured_capacity_signal_weighs_less():
    measured = build_heat_table([], graph(46)).row("fulfillment").score
    estimated = build_heat_table([], graph(46, evidence=False)).row("fulfillment").score
    assert measured > estimated


def test_coverage_and_markdown():
    t = build_heat_table([metric("a", "RACE-A", 1)])
    issues = t.coverage_issues()
    assert any(i.startswith("fulfillment") for i in issues)
    assert any("both-direction" in i for i in issues)
    md = to_markdown(t)
    assert md.startswith("| Rank |") and "Coverage gaps (G5)" in md


def test_unknown_domain_rejected():
    with pytest.raises(ValueError, match="DomainName"):
        build_heat_table([metric("x", "marketing", 1)])
