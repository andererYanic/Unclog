import json
import os
import time
from pathlib import Path

import pytest

from unclog import cli
from unclog.connectors import FileDropConnector, pull
from unclog.llm import BudgetExceeded, LLMClient, LLMRequest
from unclog.llm.backends import FakeBackend
from unclog.llm.types import Message
from unclog.qa.security import scan
from unclog.store import ClientStore
from unclog.store.crypto import EncryptionRequired, generate_key_file
from unclog.store.governance import ClientPolicy, EngagementBudget, apply_retention, audit_hook

ROOT = Path(__file__).parent.parent


def req(agent="intake"):
    return LLMRequest(messages=[Message(role="user", content="hi")], agent=agent)


# ---- encryption at rest ----------------------------------------------------------------------
def test_raw_uploads_encrypted_with_client_key(tmp_path, monkeypatch):
    keys = tmp_path / "vault"
    monkeypatch.setenv("UNCLOG_KEYS_DIR", str(keys))
    key_path = generate_key_file("acme", keys)
    assert oct(key_path.stat().st_mode)[-3:] == "600"
    with pytest.raises(FileExistsError):
        generate_key_file("acme", keys)
    store = ClientStore(tmp_path / "clients", "acme")
    data = b"order_id,email\n1,anna@acme.de\n"
    path = store.put_raw(data, "ab" * 32, "orders.csv", actor="intake")
    assert path.name.endswith(".csv.enc") and b"anna@acme.de" not in path.read_bytes()
    assert store.get_raw("ab" * 32, ".csv", actor="analyst") == data
    monkeypatch.delenv("UNCLOG_KEYS_DIR")
    with pytest.raises(PermissionError, match="key"):
        store.get_raw("ab" * 32, ".csv", actor="analyst")
    events = [e["action"] for e in store.audit_log()]
    assert events.count("read_raw") == 2 and store.audit_log()[0]["encrypted"] is True


def test_encryption_can_be_required(tmp_path, monkeypatch):
    monkeypatch.setenv("UNCLOG_REQUIRE_ENCRYPTION", "1")
    monkeypatch.delenv("UNCLOG_KEYS_DIR", raising=False)
    store = ClientStore(tmp_path, "nokey")
    with pytest.raises(EncryptionRequired):
        store.put_raw(b"x", "cd" * 32, "a.csv", actor="intake")


def test_env_key_and_pull_end_to_end(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("UNCLOG_KEY_ACME_GMBH", Fernet.generate_key().decode())
    up = tmp_path / "up"
    up.mkdir()
    (up / "leads.csv").write_text("id,email\n1,x@y.de\n")
    store = ClientStore(tmp_path / "clients", "acme-gmbh")
    report = pull(FileDropConnector(up), store, actor="intake")
    assert report.ingested == ["leads.csv"]
    assert all(p.suffix == ".enc" for p in (store.root / "raw").iterdir())


# ---- governance -------------------------------------------------------------------------------
def test_retention_dry_run_and_apply(tmp_path):
    store = ClientStore(tmp_path, "acme")
    ClientPolicy(raw_days=30, derived_days=60).save(store, "admin")
    old = store.put_raw(b"old", "ef" * 32, "a.csv", actor="intake")
    new = store.put_raw(b"new", "aa" * 32, "b.csv", actor="intake")
    (store.root / "pipeline").mkdir()
    cp = store.root / "pipeline" / "goal_factoring.json"
    cp.write_text("{}")
    past = time.time() - 90 * 86400
    os.utime(old, (past, past))
    os.utime(cp, (past, past))
    plan = apply_retention(store, "admin")
    assert plan == sorted([f"raw/{old.name}", "pipeline/goal_factoring.json"])
    assert old.exists()  # dry run deletes nothing
    apply_retention(store, "admin", dry_run=False)
    assert not old.exists() and new.exists() and not cp.exists()
    assert any(e["action"] == "retention_apply" for e in store.audit_log())


def test_engagement_budget_persists_across_runs(tmp_path):
    store = ClientStore(tmp_path, "acme")
    ClientPolicy(max_usd=0.02).save(store, "admin")
    llm = LLMClient(
        FakeBackend(lambda r: "ok"), cost=EngagementBudget(store), on_call=audit_hook(store)
    )
    llm.complete(req())  # 1000 in / 200 out on opus = $0.008
    llm.complete(req())
    assert (store.root / "costs.jsonl").read_text().count("\n") == 2
    later = LLMClient(FakeBackend(lambda r: "ok"), cost=EngagementBudget(store))
    later.complete(req())  # 0.016 spent so far -> one more call allowed
    with pytest.raises(BudgetExceeded, match="engagement budget"):
        later.complete(req())
    calls = [e for e in store.audit_log() if e["action"] == "model_call"]
    assert len(calls) == 2 and calls[0]["model"] and "content" not in calls[0]


def test_audit_hook_logs_cache_hits(tmp_path):
    from unclog.llm.cache import MemoryCache

    store = ClientStore(tmp_path, "acme")
    llm = LLMClient(FakeBackend(["a"]), cache=MemoryCache(), on_call=audit_hook(store))
    llm.complete(req())
    llm.complete(req())
    calls = [e for e in store.audit_log() if e["action"] == "model_call"]
    assert [c["cached"] for c in calls] == [False, True]


# ---- secret scan -------------------------------------------------------------------------------
def test_repository_is_free_of_secrets():
    assert scan(ROOT) == []


def test_scan_finds_planted_secrets(tmp_path):
    planted = "API" + "_KEY" + ' = "' + "abcdef1234567890abcd" + '"\n'  # built at runtime
    (tmp_path / "config.py").write_text(planted)
    (tmp_path / ".env").write_text("X=1\n")
    (tmp_path / "ok.py").write_text('k = "sk-ant-' + "x" * 24 + '"  # secret-scan: allow\n')
    kinds = {f.kind for f in scan(tmp_path)}
    assert kinds == {"credential assignment", "env file in tree"}


def test_cli_governance(tmp_path, monkeypatch, capsys):
    root = str(tmp_path / "clients")
    assert (
        cli.main(["--clients-root", root, "policy", "acme", "--raw-days", "14", "--max-usd", "25"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["raw_days"] == 14
    assert cli.main(["--clients-root", root, "retention", "acme"]) == 0
    assert "would delete 0" in capsys.readouterr().out
    assert cli.main(["keygen", "acme", "--keys-dir", str(tmp_path / "vault")]) == 0
    assert "never commit" in capsys.readouterr().out
    assert cli.main(["security-scan", str(ROOT / "src")]) == 0
