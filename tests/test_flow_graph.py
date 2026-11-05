import math

import pytest

from unclog.flow import FlowGraph, FlowGraphError
from unclog.schemas import FlowEdge, FlowNode, Resource, Task
from unclog.schemas.diagnosis import Distribution as D

A = dict(assumption=True, confidence=0.5)


def res(id_, count=1, hours=40, period="week"):
    return Resource(
        id=id_, name=id_, kind="team", count=count, hours_per_period=hours, period=period, **A
    )


def node(id_, dom="fulfillment", rs=(), svc_h=None, arrivals=None, **kw):
    return FlowNode(
        id=id_,
        name=id_,
        domain_id=dom,
        resource_ids=list(rs),
        service=D(kind="exponential", params={"mean": svc_h}, unit="hour") if svc_h else None,
        arrival=D(kind="poisson", params={"rate": arrivals}, unit="week") if arrivals else None,
        **A,
        **kw,
    )


def edge(a, b, p=1.0):
    return FlowEdge(source=a, target=b, probability=p)


def test_funnel_demand_and_throughput():
    g = FlowGraph(
        [node("lead", "RACE-R", arrivals=100), node("meet", "RACE-A"), node("won", "RACE-C")],
        [edge("lead", "meet", 0.2), edge("meet", "won", 0.25)],
        [],
    )
    assert g.demand() == pytest.approx({"lead": 100, "meet": 20, "won": 5})
    assert g.sinks() == ["won"] and g.throughput() == pytest.approx(5)


def test_rework_loop_inflates_demand():
    # 25% of QA output goes back to build: build sees 100 / 0.75
    g = FlowGraph(
        [node("in", arrivals=100), node("build"), node("qa"), node("out")],
        [
            edge("in", "build"),
            edge("build", "qa"),
            edge("qa", "build", 0.25),
            edge("qa", "out", 0.75),
        ],
        [],
    )
    d = g.demand()
    assert d["build"] == pytest.approx(133.333, rel=1e-3) and d["out"] == pytest.approx(100)
    assert g.has_cycle()


@pytest.mark.parametrize(
    "nodes,edges,resources,msg",
    [
        ([node("a", arrivals=1), node("a")], [], [], "duplicate node"),
        ([node("a", arrivals=1)], [edge("a", "zz")], [], "unknown node"),
        ([node("a", arrivals=1, rs=["ghost"])], [], [], "unknown resource"),
        (
            [node("a", arrivals=1), node("b"), node("c")],
            [edge("a", "b", 0.7), edge("a", "c", 0.6)],
            [],
            "sum to",
        ),
        ([node("a")], [], [], "external arrivals"),
        ([node("a", dom="marketing", arrivals=1)], [], [], "DomainName"),
    ],
)
def test_validation(nodes, edges, resources, msg):
    with pytest.raises(FlowGraphError, match=msg):
        FlowGraph(nodes, edges, resources)


def test_closed_loop_rejected():
    g = FlowGraph(
        [node("in", arrivals=1), node("a"), node("b")],
        [edge("in", "a"), edge("a", "b"), edge("b", "a")],
        [],
    )
    with pytest.raises(FlowGraphError, match="closed loop"):
        g.demand()


def test_load_capacity_and_pooling():
    # 20 orders/week x 8 h = 160 h demanded; 4 people x 38 h = 152 h -> 105%
    g = FlowGraph(
        [node("in", arrivals=20), node("make", rs=["shop"], svc_h=8)],
        [edge("in", "make")],
        [res("shop", count=4, hours=38)],
    )
    rl = g.resource_loads()["shop"]
    assert rl.load_h == pytest.approx(160) and rl.utilization == pytest.approx(160 / 152)
    assert g.bottleneck().resource_id == "shop"
    assert g.demand_headroom() == pytest.approx(152 / 160 - 1)
    # pooled team: two resources share a node's service time by headcount
    g2 = FlowGraph(
        [node("in", arrivals=10), node("x", rs=["a", "b"], svc_h=4)],
        [edge("in", "x")],
        [res("a", count=1), res("b", count=3)],
    )
    loads = g2.resource_loads()
    assert loads["a"].load_h == pytest.approx(10) and loads["b"].load_h == pytest.approx(30)


def test_monthly_capacity_period_converted():
    g = FlowGraph(
        [node("in", arrivals=10), node("x", rs=["r"], svc_h=1)],
        [edge("in", "x")],
        [res("r", hours=160, period="month")],
    )
    assert g.resource_loads()["r"].capacity_h == pytest.approx(160 * 12 / 52)


def test_tasks_with_setup_and_batches():
    # 40/week, batches of 10 -> 4 setups x 2 h = 8 h, plus 40 x 0.5 h = 20 h
    n = node("approve", rs=["mgr"], batch_size=10)
    t = Task(
        id="t1",
        node_id="approve",
        name="review",
        resource_id="mgr",
        service=D(kind="fixed", params={"value": 0.5}, unit="hour"),
        setup_time_h=2,
        **A,
    )
    g = FlowGraph([node("in", arrivals=40), n], [edge("in", "approve")], [res("mgr")], [t])
    assert g.resource_loads()["mgr"].load_h == pytest.approx(28)


def test_what_if_scaling_moves_utilization():
    g = FlowGraph(
        [node("in", "RACE-R", arrivals=10), node("x", rs=["r"], svc_h=3)],
        [edge("in", "x")],
        [res("r", hours=40)],
    )
    assert g.bottleneck().utilization == pytest.approx(0.75)
    g2 = g.with_arrival_scale(1.3)
    assert g2.bottleneck().utilization == pytest.approx(0.975)
    assert g.bottleneck().utilization == pytest.approx(0.75)  # original untouched


def test_node_loads_wait_estimates():
    over = FlowGraph(
        [node("in", arrivals=20), node("x", rs=["r"], svc_h=3, queue_length=30)],
        [edge("in", "x")],
        [res("r")],
    )
    nl = over.node_loads()["x"]
    assert math.isinf(nl.est_wait_h)  # 150% utilization: queue grows without bound
    assert nl.observed_wait_h == pytest.approx(30 / 20 * 168)  # Little's law, calendar hours
    ok = FlowGraph(
        [node("in", arrivals=5), node("x", rs=["r"], svc_h=4, wait_time_h=36)],
        [edge("in", "x")],
        [res("r")],
    )
    nl2 = ok.node_loads()["x"]
    assert 0 < nl2.est_wait_h < math.inf
    assert nl2.flow_efficiency == pytest.approx(4 / 40)
