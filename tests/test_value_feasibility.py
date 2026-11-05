from pathlib import Path

import pytest

from unclog.build.library import by_id
from unclog.evals.cases import load_case
from unclog.schemas import Opportunity
from unclog.schemas.design import RealizationPath, ValueScenario
from unclog.scoring.feasibility import DISCLAIMER, assess
from unclog.scoring.value import (
    CostInputs,
    Economics,
    Effect,
    OpportunityInput,
    SimSettings,
    _ramped,
    apply_effects,
    mirage_ledger,
    to_markdown,
    value_portfolio,
)

CASES = Path(__file__).parent.parent / "evals" / "cases"
A = dict(assumption=True, confidence=0.5)
SIMS = SimSettings(replications=4, horizon_weeks=14, warmup_weeks=2)
ECON = Economics(throughput_per_unit=1200, inventory_value_per_unit=900, hourly_cost=55)


def opp(i, pos="upstream", link="protects", **kw):
    base = dict(
        id=i,
        title=i,
        ai_role="assist",
        position=pos,
        focus_step="exploit",
        constraint_id="c",
        constraint_link=link,
        proven=True,
        proof_refs=["lib:x"],
        process_health_ok=True,
        release_gate_required=pos == "upstream",
        release_gate_design="gate" if pos == "upstream" else None,
        client_owner="Werkstattleitung",
    )
    base.update(kw)
    return Opportunity(**base, **A)


@pytest.fixture(scope="module")
def flood():
    return load_case(CASES / "backend_fulfillment_flood").graph()


@pytest.fixture(scope="module")
def report(flood):
    items = [
        OpportunityInput(
            opp("opp-prestage"),
            (Effect("capacity", "workshop", 0.05, 0.10, 0.15),),
            CostInputs(
                build_cost=6000,
                monthly_license=50,
                inference_cost_per_item=0.05,
                items_per_week=22,
                review_h_per_week=1,
            ),
        ),
        OpportunityInput(
            opp("opp-strip", "at_constraint", "acts_on"),
            (Effect("capacity", "workshop", 0.03, 0.06, 0.10),),
            CostInputs(build_cost=3000),
        ),
        OpportunityInput(
            opp("opp-copilot", "off_flow", "off_constraint"),
            (Effect("service", "design", 0.2, 0.3, 0.4),),
            CostInputs(build_cost=8000),
            claimed_oe_saving=-2000,
            capacity_released_h=10,
        ),
    ]
    return value_portfolio(flood, items, ECON, SIMS)


# ---- value model --------------------------------------------------------------------------
def test_constraint_effect_has_simulated_value(report):
    p = next(x for x in report.per_opportunity if x.opportunity_id == "opp-prestage")
    dt, di, doe = p.delta[ValueScenario.base]
    assert dt.validated_by == "simulation" and dt.sim_run_id in p.sim_runs  # G9
    assert dt.amount > 0
    lows, highs = (
        next(ln for ln in p.lines if ln.scenario is s).delta_t
        for s in (ValueScenario.low, ValueScenario.high)
    )
    assert lows <= dt.amount <= highs
    line = next(ln for ln in p.lines if ln.scenario is ValueScenario.base)
    expected_run = 50 + 0.05 * 22 * 52 / 12 + 1 * 55 * 52 / 12
    assert line.run_cost == pytest.approx(expected_run, abs=0.05)
    assert line.amortized_build == 500
    assert line.delta_profit == pytest.approx(
        line.delta_t - line.delta_oe_realized - line.delta_i_carrying - line.run_cost - 500,
        abs=0.05,
    )


def test_non_constraint_effect_is_zero_and_mirage_logged(report):
    p = next(x for x in report.per_opportunity if x.opportunity_id == "opp-copilot")
    assert all(ln.delta_t == 0 for ln in p.lines)  # NCX-10: noise is not value
    assert all(ln.delta_oe_realized == 0 for ln in p.lines)  # no realization path
    assert any("does not move the constraint" in n for n in p.notes)
    m = report.model.mirage_ledger
    assert len(m) == 1 and m[0].opportunity_id == "opp-copilot"
    assert m[0].capacity_released_h == 10


def test_portfolio_is_deduplicated(report):
    base = ValueScenario.base
    assert report.portfolio[base] > 0
    assert report.portfolio[base] < report.portfolio_sum_of_parts[base]
    assert report.model.dedup_notes and "overlap" in report.model.dedup_notes[0]
    md = to_markdown(report, ECON)
    assert "Mirage ledger" in md and "Portfolio ΔT/mo" in md


def test_realization_path_counts_with_probability(flood):
    path = RealizationPath(kind="contractor_reduction", owner="COO", timing="Q1", probability=0.5)
    item = OpportunityInput(
        opp("o", "at_constraint", "acts_on"), (), claimed_oe_saving=-1000, realization_path=path
    )
    r = value_portfolio(flood, [item], ECON, SIMS)
    line = next(ln for ln in r.model.lines if ln.scenario is ValueScenario.base)
    assert line.delta_oe_realized == -500 and line.delta_profit == 500
    assert mirage_ledger([item]) == []


def test_apply_effects_kinds(flood):
    g, batch = apply_effects(
        flood,
        (
            Effect("conversion", "visitors->checkout", 0.1, 0.1, 0.1),
            Effect("batch", "production", 5, 5, 5),
            Effect("demand", "*", 0.2, 0.2, 0.2),
        ),
        ValueScenario.base,
    )
    edge = next(e for e in g.edges if e.source == "visitors")
    assert edge.probability == pytest.approx(0.011 * 1.1)
    assert batch == {"production": 5} and g.arrival_scale["visitors"] == pytest.approx(1.2)
    g2, _ = apply_effects(
        flood, (Effect("service", "production", 0.25, 0.25, 0.25),), ValueScenario.base
    )
    from unclog.flow.distributions import service_hours

    assert service_hours(g2.node("production").service) == pytest.approx(6.0)
    with pytest.raises(ValueError, match="no edge"):
        apply_effects(flood, (Effect("conversion", "a->b", 0.1, 0.1, 0.1),), ValueScenario.base)


def test_ramp():
    # 1000/month benefit, no build, 2-month ramp, 3 months: 500 + 1000 + 1000
    assert _ramped(1000, 0, 2, 3) == pytest.approx(2500)
    # amortization (100) runs from month 1
    assert _ramped(900, 100, 1, 2) == pytest.approx(1800)


# ---- feasibility ---------------------------------------------------------------------------
def test_feasibility_flags():
    o = opp(
        "o1", title="Antwortentwürfe auf neue Anfragen per E-Mail mit Follow-up", client_owner=None
    )
    f = assess(o, by_id("speed-to-lead-responder"))
    areas = {(fl.area, fl.severity) for fl in f.flags}
    assert ("compliance", "condition") in areas  # GDPR + UWG
    assert ("safety", "condition") in areas  # external effect -> draft only
    assert ("data", "condition") in areas  # only file uploads today
    assert ("ownership", "block") in areas and f.status == "blocked"
    assert f.risks() and all(r.category in {"compliance", "change", "data"} for r in f.risks())
    assert "legal advice" in DISCLAIMER["en"]


def test_feasibility_employment_and_ok_case():
    hr = assess(opp("o2", title="Bewerber-Ranking vorbereiten"), domain="hr")
    assert any("AI Act" in fl.text for fl in hr.flags)
    clean = assess(
        opp(
            "o3", title="Produktionsreihenfolge nach Termin vorschlagen", tech_approach="ERP-Export"
        )
    )
    assert clean.status == "ok"
