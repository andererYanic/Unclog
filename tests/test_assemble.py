import json
from pathlib import Path

from unclog import cli
from unclog.evals.cases import load_case
from unclog.orchestrator import run_pipeline
from unclog.orchestrator.assemble import assemble
from unclog.store import ClientStore

CASES = Path(__file__).parent.parent / "evals" / "cases"


def test_real_client_from_store_to_pipeline(tmp_path, capsys):
    root = str(tmp_path / "clients")
    up = tmp_path / "uploads"
    up.mkdir()
    src_case = load_case(CASES / "backend_fulfillment_flood")
    (up / "orders.csv").write_bytes(src_case.raw_path("orders_events.csv").read_bytes())
    assert cli.main(["--clients-root", root, "ingest", "moebel", str(up)]) == 0
    store = ClientStore(root, "moebel")
    sid = store.list_sources()[0]

    # nothing but an event log yet: assemble reports the gaps instead of inventing data
    rep = assemble(store, "Möbelwerkstatt")
    assert any("event log" in g and "flow-from-log" in g for g in rep.gaps)
    assert any("G3" in g for g in rep.gaps)

    assert (
        cli.main(
            [
                "--clients-root",
                root,
                "flow-from-log",
                "moebel",
                sid,
                "--domain",
                "fulfillment",
                "--save",
            ]
        )
        == 0
    )
    capsys.readouterr()
    # consultant adds who does the work (manual fragment overrides the measured node)
    (store.root / "flow" / "manual.json").write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "id": "workshop",
                        "name": "4 Tischler",
                        "kind": "team",
                        "count": 4,
                        "hours_per_period": 38,
                        "assumption": True,
                        "confidence": 0.7,
                    }
                ],
                "nodes": [
                    {
                        "id": "log-production-start",
                        "name": "production start",
                        "domain_id": "fulfillment",
                        "resource_ids": ["workshop"],
                        "service": {
                            "kind": "lognormal",
                            "params": {"mean": 8, "cv": 0.35},
                            "unit": "hour",
                        },
                    }
                ],
            }
        )
    )
    (store.root / "reviews").mkdir(exist_ok=True)
    (store.root / "reviews" / "src-call-1-extraction.json").write_text(
        json.dumps(
            {
                "goal_statement": "Mehr Maßmöbel profitabel ausliefern",
                "unit_of_throughput": "ausgelieferter Auftrag",
                "confidence": 0.7,
            }
        )
    )

    assert (
        cli.main(
            [
                "--clients-root",
                root,
                "assemble-case",
                "moebel",
                "--title",
                "Möbelwerkstatt",
                "--kind",
                "backend",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "case written" in out and "G3" not in out
    case = load_case(store.root / "case")
    assert case.goal.unit_of_throughput == "ausgelieferter Auftrag"
    assert case.event_log_domains == {sid: "fulfillment"}
    assert case.activity_nodes["production_start"] == "log-production-start"
    prod = case.graph().node("log-production-start")
    assert prod.resource_ids == ["workshop"] and prod.queue_length == 74  # merged fragments

    run = run_pipeline(case, lang="de", store=store, out_dir=tmp_path / "out")
    b = run.state.report.binding
    assert b is not None and b.resource_id == "workshop", run.reason
    assert run.status == "awaiting_review"
    assert any(t.kind.value == "queue" and t.passed for t in b.tests_run)
    raw = list((store.root / "raw").iterdir())
    assert raw  # originals stay in the store; the case only references source ids
    assert not any(p.suffix == ".csv" for p in (store.root / "case").iterdir())
