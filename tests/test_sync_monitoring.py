import json
from datetime import date, datetime, timedelta

import pytest

from unclog.llm import LLMClient
from unclog.llm.backends import FakeBackend
from unclog.monitoring import Ledger, WeekSnapshot, evaluate, status, summary
from unclog.monitoring.buffers import to_markdown as buffers_md
from unclog.schemas.diagnosis import Buffer
from unclog.store import ClientStore
from unclog.sync import LogEntry, Outcome, PrivacyError, SyncPolicy, pseudonym, rank, run_sync

SALT = "acme-salt-2026-very-secret"
SKILL = """---
name: angebots-check
description: Angebot prüfen
---

# angebots-check

## Ablauf

1. Angebot öffnen.
2. Marge prüfen.

## Verantwortlich

Vertrieb
"""
SOP = {
    "steps": [
        "CRM-Export des Angebots laden",
        "Marge und Risiko gegen Regeln prüfen",
        "Fehlende Angaben als Liste an den Vertrieb",
    ],
    "tips": ["Zuerst Aufmaß prüfen, dann Marge (ref-1)", "Kontakt: anna@acme.de"],
    "pitfalls": ["Rabatte nicht doppelt rechnen"],
    "changes_vs_current": ["Export statt manuell öffnen", "Aufmaß zuerst"],
    "confidence": 0.7,
}


def team(n=6):
    people = [f"person{i}" for i in range(n)]
    logs = [
        LogEntry(
            p,
            "vertrieb",
            "sales",
            "angebots-check",
            f"{p}: Ich lade zuerst den CRM-Export, dann prüfe ich das Aufmaß. Tel 0171 1234567",
        )
        for p in people
    ]
    outcomes = [Outcome(p, "angebots-check", float(i)) for i, p in enumerate(people)]
    return logs, outcomes


def policy(**kw):
    base = dict(consent_ref="BV-2026-07 Betriebsvereinbarung KI", salt=SALT)
    base.update(kw)
    return SyncPolicy(**base)


# ---- team sync ---------------------------------------------------------------------------------
def test_privacy_gate():
    logs, outcomes = team()
    llm = LLMClient(FakeBackend([json.dumps(SOP)]))
    with pytest.raises(PrivacyError, match="consent"):
        run_sync(
            llm,
            "vertrieb",
            logs,
            outcomes,
            {"angebots-check": ("1.0.0", SKILL)},
            policy(consent_ref=None),
            date(2026, 11, 6),
        )
    small, out_small = team(3)
    with pytest.raises(PrivacyError, match="< 5"):
        run_sync(
            llm,
            "vertrieb",
            small,
            out_small,
            {"angebots-check": ("1.0.0", SKILL)},
            policy(),
            date(2026, 11, 6),
        )
    with pytest.raises(PrivacyError, match="salt"):
        run_sync(llm, "vertrieb", logs, outcomes, {}, policy(salt="short"), date(2026, 11, 6))


def test_pseudonyms_and_ranking():
    assert pseudonym("anna", SALT) == pseudonym("anna", SALT) != pseudonym("anna", SALT + "x")
    _, outcomes = team()
    r = rank(outcomes, "angebots-check", SALT)
    assert r[0] == (pseudonym("person5", SALT), 5.0) and len(r) == 6


def test_sync_proposes_skill_update_without_personal_data():
    logs, outcomes = team()
    fake = FakeBackend([json.dumps(SOP)])
    res = run_sync(
        LLMClient(fake),
        "vertrieb",
        logs,
        outcomes,
        {"angebots-check": ("1.0.0", SKILL)},
        policy(),
        date(2026, 11, 6),
    )
    u = res.updates[0]
    assert u.new_version == "1.1.0" and "1. CRM-Export des Angebots laden" in u.new_skill
    assert "## Verantwortlich" in u.new_skill and "## Tipps aus dem Team" in u.new_skill
    assert "+1. CRM-Export" in u.diff and "-1. Angebot öffnen." in u.diff
    assert "anna@acme.de" not in u.new_skill and "[EMAIL]" in u.new_skill  # scrubbed output
    sent = fake.requests[0].messages[0].content
    assert "person5" not in sent and "0171" not in sent and "untrusted-" in sent
    assert pseudonym("person5", SALT) in sent  # only top performers, pseudonymised
    assert "person0" not in sent and pseudonym("person0", SALT) not in sent
    s = res.session
    assert s.used_log_mining and s.consent_ref and s.top_performer_ids == []  # no ranking shared
    assert "ranking" not in res.pod_report
    shared = run_sync(
        LLMClient(FakeBackend([json.dumps(SOP)])),
        "vertrieb",
        logs,
        outcomes,
        {"angebots-check": ("1.0.0", SKILL)},
        policy(share_individual_ranking=True),
        date(2026, 11, 6),
    )
    assert shared.session.top_performer_ids and "ranking" in shared.pod_report


# ---- monitoring --------------------------------------------------------------------------------
def test_results_ledger(tmp_path):
    led = Ledger(ClientStore(tmp_path, "acme"))
    led.record(
        "median first response (h)",
        52,
        9,
        date(2026, 10, 1),
        date(2026, 11, 5),
        True,
        "monitor",
        lag_note="booked-meeting rate follows in 2-4 weeks",
    )
    led.record(
        "median first response (h)", 52, 4, date(2026, 10, 1), date(2026, 11, 12), True, "monitor"
    )
    led.record(
        "signed projects / month",
        2.0,
        2.4,
        date(2026, 10, 1),
        date(2026, 11, 12),
        False,
        "monitor",
        lang="de",
    )
    latest = led.latest()
    assert latest["median first response (h)"].current == 4
    md = led.to_markdown(higher_is_better={"median first response (h)": False})
    assert "-92% ✓" in md and "+20% ✓" in md and "Zeitlicher Zusammenhang" in md
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="baseline_date"):
        led.record("x", 1, 2, date(2026, 11, 5), date(2026, 10, 1), True, "m")  # date order


def test_buffer_zones():
    buf = Buffer(id="b", protects="c", size_h=168)
    now = datetime(2026, 11, 10, 12)
    orders = [
        ("O-1", now + timedelta(hours=150)),
        ("O-2", now + timedelta(hours=80)),
        ("O-3", now + timedelta(hours=20)),
        ("O-4", now - timedelta(hours=5)),
    ]
    items = status(buf, orders, now)
    zones = {o.order_id: o.zone for o in items}
    assert zones == {"O-1": "green", "O-2": "yellow", "O-3": "red", "O-4": "late"}
    assert summary(items) == {"green": 1, "yellow": 1, "red": 1, "late": 1}
    assert items[0].order_id == "O-4" and "O-3" in buffers_md(items)


def test_constraint_shift_alerts():
    weeks = [
        WeekSnapshot(
            f"W{i}",
            {"workshop": u, "designer": d},
            {"workshop": qw, "designer": qd},
            demand=dem,
            throughput=thr,
        )
        for i, (u, d, qw, qd, dem, thr) in enumerate(
            [
                (1.10, 0.80, 60, 2, 22, 19),
                (0.78, 0.83, 10, 5, 22, 21),
                (0.76, 0.86, 4, 9, 23, 21),
                (0.75, 0.88, 3, 14, 27, 21),
                (0.74, 0.90, 2, 20, 28, 18),
            ]
        )
    ]
    alerts = {
        a.kind: a for a in evaluate(weeks, "workshop", baseline_demand=22, next_resource="designer")
    }
    assert alerts["constraint_relieved"].severity == "action"
    assert "designer" in alerts["queue_moved"].message
    assert "+27%" in alerts["demand_shift"].message
    assert alerts["next_constraint"].severity == "action"
    assert "starved" in alerts["starving"].message
    calm = evaluate(weeks[:2], "workshop", baseline_demand=22, next_resource="designer")
    assert not any(a.kind == "constraint_relieved" for a in calm)


def test_cli_monitoring_and_sync(tmp_path, monkeypatch, capsys):
    from unclog import cli

    root = str(tmp_path / "clients")
    assert (
        cli.main(
            [
                "--clients-root",
                root,
                "ledger",
                "acme",
                "add",
                "--metric",
                "wait (h)",
                "--baseline",
                "96",
                "--current",
                "20",
                "--baseline-date",
                "2026-10-01",
                "--date",
                "2026-11-05",
                "--lang",
                "en",
            ]
        )
        == 0
    )
    assert "wait (h)" in capsys.readouterr().out
    orders = tmp_path / "o.csv"
    orders.write_text("order_id,due\nO-1,2026-11-10T13:00:00\nO-2,2026-11-20T00:00:00\n")
    assert (
        cli.main(
            ["buffers", "--orders", str(orders), "--now", "2026-11-10T12:00:00", "--lang", "en"]
        )
        == 0
    )
    assert "O-1" in capsys.readouterr().out
    weeks = tmp_path / "w.json"
    weeks.write_text(json.dumps([{"week": f"W{i}", "utilization": {"r": 0.7}} for i in range(4)]))
    assert cli.main(["monitor", "--weeks", str(weeks), "--constraint", "r"]) == 1  # action
    assert "constraint_relieved" in capsys.readouterr().out
    logs, outcomes = team()
    lf = tmp_path / "logs.jsonl"
    lf.write_text("\n".join(json.dumps(vars(e)) for e in logs))
    of = tmp_path / "out.csv"
    of.write_text(
        "person,task,score\n" + "\n".join(f"{o.person},{o.task},{o.score}" for o in outcomes)
    )
    sk = tmp_path / "SKILL.md"
    sk.write_text(SKILL)
    monkeypatch.setenv("UNCLOG_SYNC_SALT", SALT)
    monkeypatch.setattr(
        cli,
        "make_llm",
        lambda budget=None, cache=True, model=None: LLMClient(FakeBackend([json.dumps(SOP)])),
    )
    assert (
        cli.main(
            [
                "--clients-root",
                root,
                "sync",
                "acme",
                "--pod",
                "vertrieb",
                "--logs",
                str(lf),
                "--outcomes",
                str(of),
                "--skill",
                f"angebots-check=1.0.0:{sk}",
                "--consent",
                "BV-2026-07",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "v1.0.0 → v1.1.0" in out and "proposals" in out
