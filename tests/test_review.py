import json
from pathlib import Path

import pytest

from unclog import cli
from unclog.build.templates import TEMPLATES
from unclog.deploy import PackageSpec, package
from unclog.evals.harness import AgentCase, Grade, System, run_eval
from unclog.orchestrator.review import Review
from unclog.schemas import DeployedSystem
from unclog.store import ClientStore

CASES = Path(__file__).parent.parent / "evals" / "cases"


@pytest.fixture
def pkg(tmp_path):
    store = ClientStore(tmp_path / "clients", "acme")
    out = tmp_path / "deliverables"
    assert (
        cli.main(
            [
                "pipeline",
                "--case",
                str(CASES / "race_speed_to_lead"),
                "--out",
                str(out),
                "--lang",
                "en",
            ]
        )
        == 0
    )
    return store, out


def test_approval_bound_to_content_and_release(pkg, capsys):
    store, out = pkg
    rv = Review(store)
    files = sorted(p for p in out.iterdir() if p.is_file())
    assert all(s.state == "unreviewed" for s in rv.status(out))
    with pytest.raises(PermissionError):
        rv.release(out, "anna")
    for f in files:
        rv.approve(f, "anna")
    summary = out / "01-executive-summary.md"
    summary.write_text(summary.read_text() + "\nEdited by hand.\n")
    st = {s.name: s.state for s in rv.status(out)}
    assert st["01-executive-summary.md"] == "stale"
    with pytest.raises(PermissionError, match="stale"):
        rv.release(out, "anna")
    rv.approve(summary, "anna", "re-checked after edit")
    manifest = json.loads(rv.release(out, "anna").read_text())
    assert manifest["released_by"] == "anna" and len(manifest["files"]) == len(files)
    assert {e["action"] for e in store.audit_log()} >= {"review_approve", "review_release"}


def test_changes_requested_and_comments(pkg):
    store, out = pkg
    rv = Review(store)
    f = out / "04-roadmap-dbr.md"
    rv.comment(f.name, "ben", "Rope limit looks low", line=7)
    rv.request_changes(f, "ben", "Add the owner for wave 1 items")
    st = rv.file_status(f)
    assert st.state == "changes_requested" and st.comments == 1 and st.by == "ben"
    with pytest.raises(ValueError):
        rv.request_changes(f, "ben", "  ")
    with pytest.raises(PermissionError):
        rv.approve(f, "agent")  # only named humans review


def test_rerun_drops_downstream_checkpoints(tmp_path):
    store = ClientStore(tmp_path, "acme")
    cp = Path(store.root) / "pipeline"
    cp.mkdir()
    for ph in ("goal_factoring", "opportunities"):
        (cp / f"{ph}.json").write_text("{}")
    rv = Review(store)
    assert rv.rerun("opportunities", "anna") == ["opportunities"]
    assert (cp / "goal_factoring.json").exists()
    (cp / "opportunities.json").write_text("{}")
    assert rv.rerun("goal_factoring", "anna", "tree too generic") == [
        "goal_factoring",
        "opportunities",
    ]
    with pytest.raises(ValueError):
        rv.rerun("diagnose", "anna")


def test_go_live_requires_gates(tmp_path):
    store = ClientStore(tmp_path, "acme")
    spec = PackageSpec(
        client_id="acme",
        system_id="brief",
        template=TEMPLATES["decision-brief"],
        opportunity_id="opp-a2",
        client_owner="Sales lead",
        environment="client workspace",
        config={"rules": "margin >= 18%"},
    )
    package(spec, store, actor="deployment_agent")
    rv = Review(store)
    rec, problems = rv.go_live("brief", "anna", None, owner_trained=False, client_accounts=False)
    assert problems and any("G14" in p for p in problems) and rec.go_live_approval_ref is None
    report = run_eval(
        System("brief", lambda c, i: 9.0), [AgentCase("c1", {}, {})], [lambda c, o: Grade(o)], n=10
    )
    path = tmp_path / "eval.json"
    path.write_text(report.to_json())
    rec, problems = rv.go_live("brief", "anna", path, owner_trained=True, client_accounts=True)
    assert problems == [] and rec.go_live_approval_ref.startswith("review:brief:anna")
    assert rec.draft_safe  # external actions stay drafts unless explicitly allowed
    assert store.get(DeployedSystem, "brief").go_live_approval_ref == rec.go_live_approval_ref
    folder = sorted((Path(store.root) / "systems" / "brief").glob("v*"))[-1]
    assert json.loads((folder / "GO_LIVE.json").read_text())["approved_by"] == "anna"


def test_cli_review(pkg, capsys):
    store, out = pkg
    root = str(store.root.parent)
    assert cli.main(["--clients-root", root, "review", "acme", "status", str(out)]) == 0
    assert "unreviewed" in capsys.readouterr().out
    assert (
        cli.main(
            ["--clients-root", root, "review", "acme", "release", str(out), "--reviewer", "anna"]
        )
        == 1
    )
    assert "cannot release" in capsys.readouterr().out
