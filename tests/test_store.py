import pytest
from conftest import CRM_CSV

from unclog.ingestion import ingest_bytes
from unclog.schemas import Domain, Process
from unclog.store import ClientStore, OwnershipError, delete_client


def _proc(ev, health="sound"):
    return Process(id="p-refunds", name="Refunds", process_health=health, evidence=[ev()])


def test_put_get_and_versions(tmp_path, ev):
    s = ClientStore(tmp_path, "acme")
    assert s.put(_proc(ev), produced_by="flow_modeler") == 1
    assert s.put(_proc(ev, "fragile"), produced_by="flow_modeler") == 2
    assert s.get(Process, "p-refunds").process_health == "fragile"
    assert s.get(Process, "p-refunds", version=1).process_health == "sound"
    assert [e.version for e in s.history(Process, "p-refunds")] == [1, 2]
    assert len(s.list(Process)) == 1 and s.list(Domain) == []


def test_agents_cannot_overwrite_each_other(tmp_path, ev):
    s = ClientStore(tmp_path, "acme")
    s.put(_proc(ev), produced_by="flow_modeler")
    with pytest.raises(OwnershipError):
        s.put(_proc(ev, "broken"), produced_by="opportunity_analyst")


def test_only_registered_entities(tmp_path):
    from unclog.schemas.common import UnclogModel

    class Scratch(UnclogModel):
        id: str

    with pytest.raises(TypeError):
        ClientStore(tmp_path, "acme").put(Scratch(id="x"), produced_by="a")


@pytest.mark.parametrize("bad", ["../other", "a/b", "..", "x y", ""])
def test_unsafe_client_ids(tmp_path, bad):
    with pytest.raises(ValueError):
        ClientStore(tmp_path, bad)


def test_clients_are_isolated(tmp_path, ev):
    a, b = ClientStore(tmp_path, "acme"), ClientStore(tmp_path, "globex")
    a.put(_proc(ev), produced_by="flow_modeler")
    with pytest.raises(KeyError):
        b.get(Process, "p-refunds")


def test_sources_dedupe_and_audit(tmp_path):
    s = ClientStore(tmp_path, "acme")
    r = ingest_bytes(CRM_CSV, "leads.csv")
    assert s.put_source(r, actor="intake") is True
    assert s.put_source(r, actor="intake") is False
    assert s.get_source(r.source.id).tables[0].rows[0]["Lead ID"] == "L-1001"
    actions = [e["action"] for e in s.audit_log()]
    assert actions == ["put_source", "put_source"]


def test_delete_client_removes_everything(tmp_path, ev):
    s = ClientStore(tmp_path, "acme")
    r = ingest_bytes(CRM_CSV, "leads.csv")
    s.put_raw(CRM_CSV, r.sha256, "leads.csv", actor="intake")
    s.put_source(r, actor="intake")
    s.put(_proc(ev), produced_by="flow_modeler")
    delete_client(tmp_path, "acme", actor="owner")
    assert not (tmp_path / "acme").exists()
    assert "acme" in (tmp_path / "deletions.jsonl").read_text()
