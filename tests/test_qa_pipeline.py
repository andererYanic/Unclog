import json
from pathlib import Path

from unclog import cli
from unclog.build.templates import TEMPLATES
from unclog.deploy import PackageSpec, package
from unclog.evals.cases import load_case
from unclog.evals.harness import AgentCase, Grade, System, run_eval
from unclog.llm import LLMClient
from unclog.llm.backends import FakeBackend
from unclog.orchestrator import State, run_pipeline
from unclog.qa import critique, run_gates, specificity
from unclog.schemas.design import FindingSeverity
from unclog.store import ClientStore

CASES = Path(__file__).parent.parent / "evals" / "cases"

TREE = {
    "nodes": [
        {
            "id": "a0",
            "parent_id": "opt-policy",
            "statement": "Freigabegrenze von 5.000 auf 20.000 EUR anheben (4-Wochen-Pilot)",
            "kind": "base_action",
            "constraint_link": "acts_on",
            "focus_step": "exploit",
            "tag": "non_ai",
            "effort_days": 1,
        },
        {
            "id": "a1",
            "parent_id": "opt-batch",
            "statement": "Angebote täglich um 16 Uhr freigeben statt freitags (30 pro Woche)",
            "kind": "base_action",
            "constraint_link": "acts_on",
            "focus_step": "exploit",
            "tag": "non_ai",
            "effort_days": 1,
        },
        {
            "id": "a2",
            "parent_id": "opt-prepare",
            "statement": "Angebots-Check (Marge, Risiko, fehlende Angaben) für 30 Angebote/Woche "
            "automatisch vorbereiten",
            "kind": "base_action",
            "constraint_link": "protects",
            "focus_step": "exploit",
            "tag": "ai_doable",
            "effort_days": 5,
        },
    ],
    "confidence": 0.7,
}


def opps(owner="Vertriebsleitung"):
    sc = {"score": 4, "justification": "because"}
    return {
        "judgements": [
            {
                "seed_id": "a2",
                "pattern_id": "decision-brief",
                "title": "Entscheidungsvorlage für 30 Angebote/Woche aus dem CRM-Export",
                "ai_role": "assist",
                "human_in_loop_design": "Inhaber liest Vorlage, entscheidet",
                "release_gate_design": "genau eine Vorlage je Angebot",
                "items_per_week": 30,
                "review_minutes_per_item": 1,
                "reviewer_resource_id": "owner",
                "output_verification": "Stichprobe 5/Woche",
                "cost_of_error": "medium",
                "client_owner_role": owner,
                "tech_approach": "CRM-Export + Prompt",
                "build_vs_buy": "build",
                "risks": [
                    {
                        "description": "Marge falsch gelesen",
                        "category": "data",
                        "likelihood": 2,
                        "impact": 3,
                        "mitigation": "Regelprüfung",
                    }
                ],
                "scores": {
                    k: sc
                    for k in (
                        "throughput_impact",
                        "feasibility",
                        "data_readiness",
                        "risk",
                        "effort",
                        "strategic_fit",
                    )
                },
            }
        ],
        "confidence": 0.7,
    }


def fake_factory(*responses):
    fake = FakeBackend([json.dumps(r) for r in responses])
    return fake, (lambda: LLMClient(fake))


# ---- gates -----------------------------------------------------------------------------------
def test_specificity():
    assert specificity("KI einsetzen im Kundenservice")[0] < 3
    assert "generic phrase" in specificity("Use AI to improve efficiency")[1]
    good = "Pre-fill 410 refund tickets for the 3 Tier-2 approvers from the helpdesk export"
    assert specificity(good) == (3, [])


def test_gates_on_diagnosis_only():
    run = run_pipeline(load_case(CASES / "race_speed_to_lead"), lang="en")
    res = {g.gate: g for g in run.gates["report"]}
    assert res["G1"].status == "pass" and res["G2"].status == "pass"
    assert res["G3"].status == "pass" and res["G4"].detail == "work mode: full"
    assert res["G5"].status == "pass" and res["G13"].status == "n/a"
    assert run.status == "awaiting_review" and run.state.roadmap is not None


def test_no_goal_blocks_at_g3():
    run = run_pipeline(load_case(CASES / "no_tracking"), lang="de")
    assert run.status == "stopped" and "G3" in run.reason
    assert run.state.tree is None


def test_g4_blocks_design_without_constraint():
    s = State("e", "t", phase=6)
    run = run_pipeline(load_case(CASES / "race_speed_to_lead"), lang="en")
    s.report = run.state.report.__class__(
        **{**vars(run.state.report), "binding": None, "confirmed": []}
    )
    s.tree = object()  # any design artifact
    g4 = run_gates(s, {"G4"})[0]
    assert g4.status == "fail" and "without a confirmed constraint" in g4.problems[0]


# ---- full pipeline with agents (scripted model) ----------------------------------------------
def test_pipeline_with_agents_checkpoints_and_report(tmp_path):
    case = load_case(CASES / "hidden_policy_approval")
    store = ClientStore(tmp_path / "clients", "kitchen")
    fake, factory = fake_factory(TREE, opps())
    run = run_pipeline(case, lang="de", llm_factory=factory, store=store, out_dir=tmp_path / "out")
    assert run.status == "awaiting_review", run.reason
    assert len(fake.requests) == 2
    assert run.state.opportunities.opportunities[0].priority.value == "exploit-now"
    assert run.state.feasibility and run.state.roadmap.wave("exploit")
    names = {p.name for p in run.report_paths}
    assert {
        "03-goal-tree.md",
        "06-opportunity-map.md",
        "08-risk-register.md",
        "10-quality-gates.md",
    } <= names
    g = {r.gate: r.status for r in run.gates["report"]}
    assert g["G6"] == g["G8"] == g["G12"] == g["G16"] == "pass"
    # resume: no further model calls, same result
    fake2, factory2 = fake_factory()
    run2 = run_pipeline(case, lang="de", llm_factory=factory2, store=store)
    assert not fake2.requests and run2.status == "awaiting_review"
    assert "resumed from checkpoint" in " ".join(run2.state.log)
    # changed input (language) invalidates the checkpoint
    fake3, factory3 = fake_factory(TREE, opps())
    run_pipeline(case, lang="en", llm_factory=factory3, store=store)
    assert len(fake3.requests) == 2


def test_unowned_opportunity_is_deferred_not_blocking(tmp_path):
    case = load_case(CASES / "hidden_policy_approval")
    _, factory = fake_factory(TREE, opps(owner=None))
    run = run_pipeline(case, lang="de", llm_factory=factory)
    o = run.state.opportunities.opportunities[0]
    assert o.priority.value == "defer" and run.status == "awaiting_review"


def test_critic_blocks_twice_escalates(monkeypatch):
    case = load_case(CASES / "hidden_policy_approval")
    from unclog.orchestrator import pipeline as pl
    from unclog.schemas.design import Finding

    def always_block(state):
        return [
            Finding(
                id="x",
                phase=6,
                statement="nope",
                severity=FindingSeverity.blocking,
                assumption=True,
                confidence=0.5,
            )
        ]

    monkeypatch.setattr(pl, "critique", always_block)
    fake, factory = fake_factory(TREE, opps(), opps())
    run = run_pipeline(case, lang="de", llm_factory=factory)
    assert run.status == "escalated" and "critic blocked twice" in run.reason
    assert len(fake.requests) == 3  # tree + two opportunity attempts


def test_agent_escalation_stops_pipeline():
    case = load_case(CASES / "hidden_policy_approval")
    bad = {"nodes": [], "confidence": 0.2}
    _, factory = fake_factory(bad, bad, bad)
    run = run_pipeline(case, lang="de", llm_factory=factory)
    assert run.status == "escalated" and "goal_factoring" in run.reason


def test_critic_findings():
    run = run_pipeline(load_case(CASES / "race_speed_to_lead"), lang="en")
    texts = [f.statement for f in critique(run.state)]
    assert any(t.startswith("Local optimum") for t in texts)


# ---- delivery gates G13-G15 ------------------------------------------------------------------
def test_delivery_gates(tmp_path):
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
    system, _, issues = package(spec, store, actor="d")
    s = State("acme", "t", phase=10)
    s.deployed = [(system, spec, issues)]
    res = {r.gate: r for r in run_gates(s, {"G11", "G13", "G14", "G15"})}
    assert res["G13"].status == "pass"
    assert res["G14"].status == "fail" and "no eval report" in res["G14"].problems[0]
    assert res["G15"].status == "fail" and res["G11"].status == "fail"
    report = run_eval(
        System("brief", lambda c, i: 9.0), [AgentCase("c1", {}, {})], [lambda c, o: Grade(o)], n=10
    )
    s.eval_reports["brief"] = report
    assert run_gates(s, {"G14"})[0].status == "pass"


def test_cli_pipeline(tmp_path, capsys):
    assert (
        cli.main(
            [
                "pipeline",
                "--case",
                str(CASES / "market_after_elevation"),
                "--out",
                str(tmp_path),
                "--lang",
                "en",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "status: awaiting_review" in out and "| G9 |" in out
    assert (
        cli.main(["pipeline", "--case", str(CASES / "no_tracking"), "--out", str(tmp_path / "x")])
        == 1
    )
