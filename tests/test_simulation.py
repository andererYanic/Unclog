import statistics
from pathlib import Path

import numpy as np
import pytest

from unclog.constraint import identify
from unclog.domains import build_heat_table
from unclog.evals.cases import load_case
from unclog.flow import FlowGraph
from unclog.schemas import FlowEdge, FlowNode, Resource
from unclog.schemas.diagnosis import Distribution as D
from unclog.simulation import Scenario, compare, simulate, standard_scenarios, to_markdown
from unclog.simulation.sampling import interarrival_hours, sample
from unclog.simulation.scenarios import rope_limit

A = dict(assumption=True, confidence=0.5)
CASES = Path(__file__).parent.parent / "evals" / "cases"


def mm1(lam_per_h=0.8, svc_h=1.0, hours=168, batch=None):
    return FlowGraph(
        [
            FlowNode(
                id="in",
                name="in",
                domain_id="ops",
                arrival=D(kind="poisson", params={"rate": lam_per_h}, unit="hour"),
                **A,
            ),
            FlowNode(
                id="s",
                name="s",
                domain_id="ops",
                resource_ids=["r"],
                batch_size=batch,
                service=D(kind="exponential", params={"mean": svc_h}, unit="hour"),
                **A,
            ),
        ],
        [FlowEdge(source="in", target="s")],
        [Resource(id="r", name="r", kind="machine", hours_per_period=hours, **A)],
    )


@pytest.mark.parametrize(
    "d,expected",
    [
        (D(kind="fixed", params={"value": 3}), 3),
        (D(kind="exponential", params={"mean": 2}), 2),
        (D(kind="gamma", params={"shape": 4, "scale": 0.5}), 2),
        (D(kind="lognormal", params={"mean": 30, "cv": 0.4}), 30),
        (D(kind="triangular", params={"low": 1, "mode": 2, "high": 6}), 3),
        (D(kind="empirical", samples=[1, 2, 3]), 2),
    ],
)
def test_sampling_means(d, expected):
    rng = np.random.default_rng(1)
    assert statistics.fmean(sample(d, rng) for _ in range(20000)) == pytest.approx(
        expected, rel=0.03
    )


def test_interarrival_units():
    rng = np.random.default_rng(2)
    d = D(kind="poisson", params={"rate": 455}, unit="month")
    mean_h = statistics.fmean(interarrival_hours(d, rng) for _ in range(20000))
    assert mean_h == pytest.approx(168 * 52 / 12 / 455, rel=0.03)


def test_mm1_matches_theory():
    r = simulate(mm1(), replications=6, horizon_weeks=30, warmup_weeks=2)
    lead = statistics.fmean(x for rep in r.reps for x in rep.lead_times_h)
    assert lead == pytest.approx(5.0, rel=0.15)  # W = 1 / (mu - lambda)
    assert r.utilization["r"] == pytest.approx(0.8, abs=0.03)
    assert r.throughput.mean == pytest.approx(0.8 * 168, rel=0.03)


def test_availability_matches_static_utilization():
    # 38 h/week worker: simulated utilization equals static load/capacity
    g = mm1(lam_per_h=20 / 168, svc_h=1.5, hours=38)
    static = g.resource_loads()["r"].utilization
    r = simulate(g, replications=4, horizon_weeks=40, warmup_weeks=4)
    assert r.utilization["r"] == pytest.approx(static, abs=0.04)


def test_deterministic_per_seed():
    a = simulate(mm1(), replications=2, horizon_weeks=4, warmup_weeks=1, seed=7)
    b = simulate(mm1(), replications=2, horizon_weeks=4, warmup_weeks=1, seed=7)
    c = simulate(mm1(), replications=2, horizon_weeks=4, warmup_weeks=1, seed=8)
    assert a.throughput == b.throughput and a.lead_p50_h == b.lead_p50_h
    assert a.lead_p50_h != c.lead_p50_h


def test_batching_adds_wait():
    kw = dict(replications=3, horizon_weeks=10, warmup_weeks=1)
    base = simulate(mm1(lam_per_h=0.3), **kw)
    batched = simulate(mm1(lam_per_h=0.3), Scenario("batch 20", batch={"s": 20}), **kw)
    assert batched.lead_p50_h.mean > base.lead_p50_h.mean + 20  # ~half a batch fill time


def test_flooding_and_rope_on_backend_case():
    g = load_case(CASES / "backend_fulfillment_flood").graph()
    limit = rope_limit(g, buffer_weeks=1.0)
    assert limit == round(g.effective_throughput())
    kw = dict(replications=3, horizon_weeks=16, warmup_weeks=2)
    base, flood, roped = compare(
        g,
        [
            Scenario("baseline"),
            Scenario("demand +30%", arrival_scale=1.3),
            Scenario("demand +30% + rope", arrival_scale=1.3, rope=("design", limit)),
        ],
        **kw,
    )
    # more demand, same output: the workshop is the drum
    assert flood.throughput.mean == pytest.approx(base.throughput.mean, rel=0.05)
    assert flood.lead_p50_h.mean > base.lead_p50_h.mean
    # rope: throughput kept, in-shop WIP capped, in-shop lead time far lower than flooded
    assert roped.throughput.mean == pytest.approx(flood.throughput.mean, rel=0.05)
    assert roped.wip_total.mean <= limit + 1
    assert roped.internal_p50_h.mean < flood.internal_p50_h.mean / 3
    assert roped.gate_backlog_end.mean > 0
    assert roped.constraint_location == "workshop"


def test_standard_scenarios_and_markdown():
    g = load_case(CASES / "race_speed_to_lead").graph()
    sc = standard_scenarios(
        g, constraint_resource="sdr-team", gate_node="first-response", batch_node="first-response"
    )
    names = [s.name for s in sc]
    assert names[0] == "baseline" and any(n.startswith("exploit") for n in names)
    assert any("rope" in n for n in names) and any(n.startswith("elevate") for n in names)
    res = compare(g, sc[:2], replications=2, horizon_weeks=8, warmup_weeks=1)
    exploit = res[1]
    # Removing the batch empties the queue at first response (few won deals in a short run make
    # end-to-end lead time too noisy to assert on; the queue is the direct effect).
    assert res[0].wip_by_node["first-response"] > 10
    assert exploit.wip_by_node["first-response"] < 4  # only items in service remain
    md = to_markdown(res)
    assert md.startswith("| Scenario |") and "replications" in md
    run = res[0].to_simrun("sim-race-baseline", inputs_ref="evals/cases/race_speed_to_lead")
    assert run.replications == 2 and run.constraint_location == "sdr-team"


def test_simulation_backed_relief_test():
    case = load_case(CASES / "backend_fulfillment_flood")
    g = case.graph()
    rep = identify(build_heat_table(case.metrics, g), g, sim_replications=3)
    relief = next(t for t in rep.binding.tests_run if t.kind.value == "relief")
    assert relief.passed and "simulated" in relief.note
    assert any(e.type == "simulation" for e in rep.binding.evidence)


def test_cli_simulate(capsys):
    from unclog.cli import main

    assert (
        main(
            [
                "simulate",
                str(CASES / "backend_fulfillment_flood"),
                "--gate",
                "design",
                "--replications",
                "2",
                "--weeks",
                "8",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "elevate: +25% workshop" in out and "rope at design" in out
