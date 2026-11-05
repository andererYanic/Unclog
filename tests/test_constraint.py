import pytest

from unclog.constraint import TextItem, audit, identify, to_markdown
from unclog.constraint.text import domains_mentioned, scan
from unclog.domains import build_heat_table
from unclog.flow import FlowGraph
from unclog.schemas import Evidence, FlowEdge, FlowNode, Resource, StageMetric
from unclog.schemas.diagnosis import ConstraintStatus, DomainName, PolicyKind
from unclog.schemas.diagnosis import Distribution as D

LOG = [Evidence(id="e-log", source_id="src-log", type="log_data")]


def chain(
    rate=20,
    svc=8,
    count=4,
    hours=38,
    queue=None,
    wait=None,
    batch=None,
    dom="fulfillment",
    down=False,
):
    nodes = [
        FlowNode(
            id="in",
            name="Orders in",
            domain_id="RACE-C",
            arrival=D(kind="poisson", params={"rate": rate}, unit="week"),
            evidence=LOG,
        ),
        FlowNode(
            id="work",
            name="Production",
            domain_id=dom,
            resource_ids=["team"],
            service=D(kind="fixed", params={"value": svc}, unit="hour"),
            queue_length=queue,
            wait_time_h=wait,
            batch_size=batch,
            evidence=LOG,
        ),
    ]
    edges = [FlowEdge(source="in", target="work")]
    resources = [
        Resource(
            id="team",
            name="Workshop team",
            kind="team",
            count=count,
            hours_per_period=hours,
            evidence=LOG,
        )
    ]
    if down:
        nodes.append(
            FlowNode(
                id="ship",
                name="Shipping",
                domain_id="fulfillment",
                resource_ids=["ship"],
                service=D(kind="fixed", params={"value": 1}, unit="hour"),
                evidence=LOG,
            )
        )
        edges.append(FlowEdge(source="work", target="ship"))
        resources.append(
            Resource(id="ship", name="Shipping", kind="team", hours_per_period=40, evidence=LOG)
        )
    return FlowGraph(nodes, edges, resources)


def run(graph, metrics=(), texts=()):
    heat = build_heat_table(list(metrics), graph)
    return identify(heat, graph, texts=list(texts))


# ---- text signals ---------------------------------------------------------------------------
def test_text_scan_en_de():
    hits = scan(
        "s",
        "p1",
        "Every quote above 5k needs sign-off by the owner. "
        "Rechnungen werden einmal pro Woche gesammelt freigegeben.",
    )
    kinds = {(h.kind, h.locator) for h in hits}
    assert ("approval", "p1") in kinds and ("batching", "p1") in kinds
    assert DomainName.finance in domains_mentioned("Rechnungen werden gesammelt")
    assert scan("s", "p", "Nothing unusual here.") == []


def test_audit_text_policies_and_local_optima():
    items = [
        TextItem(
            "doc",
            "para 2",
            "Support agents are measured on tickets closed per day.",
            testimony=False,
        ),
        TextItem("intv", "t=1", "We send invoices once a week, on Fridays.", testimony=True),
    ]
    pa = audit(None, items)
    lo = pa.local_optima()
    assert len(lo) == 1 and lo[0].domain_id == "support" and "lead time" in lo[0].recommendation
    batch = [p for p in pa.policies if p.kind is PolicyKind.batch_rule]
    assert batch and batch[0].domain_id == "finance"
    assert batch[0].evidence[0].type == "interview_claim"
    assert lo[0].evidence[0].type == "document"


def test_structural_batch_policy_corroborated_by_text():
    g = chain(rate=5, svc=1, wait=72, batch=10)
    pa = audit(g, [TextItem("intv", "t=2", "We start production orders on Mondays only.", True)])
    sp = [p for p in pa.policies if p.affects_node_ids == ["work"]]
    assert len(sp) == 1 and "Rule found" in sp[0].statement
    assert {e.type for e in sp[0].evidence} >= {"log_data", "interview_claim"}


# ---- confirmation and status ----------------------------------------------------------------
def test_overloaded_resource_confirmed_with_relief_and_queue():
    r = run(chain(queue=40), texts=[TextItem("i", "t", "The workshop team works Saturdays.", True)])
    b = r.binding
    assert b is not None and b.type == "physical" and b.resource_id == "team"
    kinds = {t.kind.value: t.passed for t in b.tests_run}
    assert kinds["relief"] and kinds["queue"] and kinds["expedite"]
    assert r.work_mode == "full"
    assert r.derived_sources and r.derived_sources[0].id == "derived-flow-model"


def test_model_only_is_not_enough():
    # overloaded on paper, but no queue data and no testimony: model family only
    g = chain(queue=None)
    g.nodes[1] = g.nodes[1].model_copy(
        update={"evidence": [], "assumption": True, "confidence": 0.3}
    )
    g = FlowGraph(g.nodes, g.edges, g.resources)
    r = run(g)
    assert r.binding is None and r.work_mode == "discovery_only"
    cand = r.candidates[0]
    assert cand.status is ConstraintStatus.candidate
    assert any("export timestamps" in a for a in r.discovery_actions)
    assert any("took a day off" in a for a in r.discovery_actions)


def test_starvation_test_downstream():
    r = run(chain(queue=10, down=True))
    t = {t.kind.value: t for t in r.binding.tests_run}
    assert t["starvation"].passed and "ship" in t["starvation"].note


def test_testimony_alone_never_confirms():
    m = StageMetric(
        id="cyc",
        domain_id="RACE-C",
        name="sales cycle",
        value=60,
        unit="days",
        period="p",
        benchmark=30,
        higher_is_better=False,
        measured=False,
        source_id="intv",
    )
    r = run(chain(rate=5, svc=4), metrics=[m])  # capacity ample
    assert all(c.domain_id != "RACE-C" for c in r.confirmed)


def test_market_contradicted_by_internal_queue():
    m = StageMetric(
        id="reach",
        domain_id="RACE-R",
        name="sessions",
        value=500,
        unit="wk",
        period="p",
        benchmark=2000,
        higher_is_better=True,
        measured=True,
        source_id="src-ads",
    )
    clean = run(chain(rate=5, svc=4), metrics=[m])
    assert clean.binding is not None and clean.binding.type == "market"
    queued = run(chain(rate=5, svc=4, wait=80), metrics=[m])
    market = [c for c in [*queued.confirmed, *queued.candidates] if c.type == "market"]
    assert market and market[0].status is ConstraintStatus.candidate
    assert "contradict" in market[0].description


def test_no_flow_means_discovery_only():
    r = run(
        None,
        metrics=[
            StageMetric(
                id="g", domain_id="RACE-R", name="x", value=1, unit="u", period="p", measured=False
            )
        ],
    )
    assert r.binding is None and r.work_mode == "discovery_only"
    assert r.discovery_actions[0].startswith("Map one unit of throughput")
    assert "No confirmed constraint" in to_markdown(r)


@pytest.mark.parametrize("ship_hours,expected", [(40, "market"), (24, "physical")])
def test_next_constraint_prediction(ship_hours, expected):
    # workshop 160 h vs 152 h (overloaded); shipping needs 20 h/week
    g = chain(queue=10, down=True)
    resources = [
        r.model_copy(update={"hours_per_period": ship_hours}) if r.id == "ship" else r
        for r in g.resources
    ]
    r = run(FlowGraph(g.nodes, g.edges, resources))
    nk = r.next_constraint
    assert r.binding.resource_id == "team" and nk is not None and nk.kind == expected
    if expected == "physical":
        assert nk.resource_id == "ship"  # 20 h of 24 h = 83% once the workshop is relieved
    else:
        assert "headroom" in nk.description
