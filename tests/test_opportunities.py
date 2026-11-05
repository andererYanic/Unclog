import json
from pathlib import Path

import pytest

from unclog.agents.opportunity_analyst import (
    AnalystOutput,
    analyse_opportunities,
    assemble,
    make_seeds,
    position_for,
)
from unclog.build.library import MATCH_THRESHOLD, by_id, load_library, match
from unclog.evals.cases import load_case
from unclog.evals.runner import run_case
from unclog.llm import LLMClient
from unclog.llm.backends import FakeBackend
from unclog.schemas import GoalNode
from unclog.schemas.design import ConstraintLink, Position, Priority
from unclog.schemas.diagnosis import ConstraintType
from unclog.schemas.engagement import ProcessHealth
from unclog.scoring.opportunity import WEIGHTS, rank_score, weighted_score

CASES = Path(__file__).parent.parent / "evals" / "cases"
A = dict(assumption=True, confidence=0.6)


def seed(id_, statement, tag="ai_doable", step="exploit", link="protects"):
    return GoalNode(
        id=id_,
        parent_id="opt-x",
        kind="base_action",
        statement=statement,
        tag=tag,
        focus_step=step,
        constraint_link=link,
        effort_days=3,
        **A,
    )


def ctx(cid):
    c = load_case(CASES / cid)
    r = run_case(c)
    return c, r.report.binding, r.report.policy_audit.policies


def J(
    seed_id,
    pattern=None,
    owner="Vertriebsleitung",
    gate="max. 1 Vorlage je Angebot",
    items=30,
    minutes=2,
    reviewer=None,
    score=4,
):
    sc = {"score": score, "justification": "because"}
    return {
        "seed_id": seed_id,
        "pattern_id": pattern,
        "title": f"system for {seed_id}",
        "ai_role": "assist",
        "human_in_loop_design": "Inhaber prüft jede Vorlage",
        "release_gate_design": gate,
        "items_per_week": items,
        "review_minutes_per_item": minutes,
        "reviewer_resource_id": reviewer,
        "output_verification": "Stichprobe",
        "cost_of_error": "medium",
        "client_owner_role": owner,
        "tech_approach": "CRM-Export + Prompt",
        "build_vs_buy": "build",
        "risks": [
            {
                "description": "falsche Marge",
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


POLICY_SEEDS = [
    seed("a2", "Angebots-Check (Marge, Risiko, fehlende Angaben) automatisch vorbereiten"),
    seed(
        "a4",
        "Vertriebsleitung darf bis 20.000 EUR freigeben, KI routet nach Risikostufe",
        tag="ai_assisted",
        step="elevate",
        link="acts_on",
    ),
    seed("a5", "KI-Avatar telefoniert mit Kunden über Kündigungsgründe", link="acts_on"),
]


# ---- library -----------------------------------------------------------------------------
def test_library_entries_are_honest():
    lib = load_library()
    assert len(lib) >= 15
    for p in lib:
        assert p.proven_status in {"established", "field-reported", "emerging"}
        assert p.references and p.raw["typical_uplift"] is None  # no invented numbers
        assert p.name["en"] and p.name["de"]
    assert by_id("speed-to-lead-responder").external_effect


def test_match_explains_and_rejects_wrong_domain():
    _, b, _ = ctx("hidden_policy_approval")
    m = match(POLICY_SEEDS[1], b)
    assert m[0].pattern.id == "tiered-delegation" and m[0].score >= MATCH_THRESHOLD
    assert any(r.startswith("keywords") for r in m[0].reasons)
    assert match(POLICY_SEEDS[2], b) == []  # novel
    ad = seed("x", "Anzeigen-Varianten für Kampagne erzeugen", step="elevate", link="acts_on")
    assert all(x.pattern.id != "ad-creative-variant-factory" for x in match(ad, b))  # RACE-R only


@pytest.mark.parametrize(
    "link,ctype,pos",
    [
        ("acts_on", "physical", "at_constraint"),
        ("protects", "physical", "upstream"),
        ("gates_flow", "policy", "upstream"),
        ("acts_on", "policy", "policy"),
        ("acts_on", "market", "market"),
        ("off_constraint", "physical", "off_flow"),
    ],
)
def test_position(link, ctype, pos):
    assert position_for(ConstraintLink(link), ConstraintType(ctype)) is Position(pos)


# ---- analyst ---------------------------------------------------------------------------------
def run_policy(judgements, health=None, confidence=0.7):
    c, b, pols = ctx("hidden_policy_approval")
    seeds = make_seeds(POLICY_SEEDS, b)
    out = AnalystOutput.model_validate({"judgements": judgements, "confidence": confidence})
    return assemble(out, seeds, b, c.graph(), pols, health or {})


def test_proven_novel_and_owner_rules():
    a = run_policy(
        [
            J("a2", "decision-brief", reviewer="owner"),
            J("a4", "tiered-delegation", gate=None, owner=None),
            J("a5", None),
        ]
    )
    o = {x.id: x for x in a.opportunities}
    assert o["opp-a2"].proven and "lib:decision-brief" in o["opp-a2"].proof_refs
    assert o["opp-a2"].position is Position.upstream and o["opp-a2"].release_gate_required
    assert o["opp-a2"].priority is Priority.exploit_now
    assert o["opp-a4"].priority is Priority.defer  # nobody owns it (G12)
    assert "owner" in o["opp-a4"].assumptions[0]
    assert o["opp-a5"].rd_label and o["opp-a5"].priority is Priority.strategic_bet
    assert o["opp-a2"].scores.constraint_relevance.score == 4
    assert len(a.risks) == 3 and o["opp-a2"].risk_ids == ["risk-a2-1"]
    assert any("process health" in q for q in a.open_questions)  # not assessed: asked, not assumed
    assert [x.id for x in a.ranked()][0] in {"opp-a2", "opp-a4"}


def test_broken_process_means_fix_first():
    a = run_policy(
        [J("a2", "decision-brief"), J("a4", "tiered-delegation"), J("a5")],
        health={"mgmt": ProcessHealth.broken},
    )
    assert all(o.priority is Priority.fix_process_first for o in a.opportunities)
    assert not any(o.process_health_ok for o in a.opportunities)


def test_review_flooding_the_constraint_is_caught():
    c, b, pols = ctx("backend_fulfillment_flood")
    s = seed("f1", "Auftragsdaten vor der Produktion automatisch auf Vollständigkeit prüfen")
    seeds = make_seeds([s], b)
    j = J(
        "f1",
        seeds[0].candidates[0].pattern.id,
        items=22,
        minutes=10,
        reviewer="workshop",
        gate="nur vollständige Aufträge gehen in die Werkstatt-Warteschlange",
    )
    a = assemble(
        AnalystOutput.model_validate({"judgements": [j], "confidence": 0.7}),
        seeds,
        b,
        c.graph(),
        pols,
        {},
    )
    o = a.opportunities[0]
    assert o.review_load_h_per_week == pytest.approx(22 * 10 / 60, abs=0.01)
    assert "at the constraint" in o.wip_side_effects and "new constraint" in o.wip_side_effects
    assert o.priority is Priority.defer and a.findings and a.findings[0].startswith("G8")


def test_check_failures_go_back_to_model():
    c, b, pols = ctx("hidden_policy_approval")
    bad = {
        "judgements": [
            J("a2", "speed-to-lead-responder", gate=None),
            J("a4", "tiered-delegation", reviewer="ghost"),
        ],
        "confidence": 0.6,
    }
    good = {
        "judgements": [J("a2", "decision-brief"), J("a4", "tiered-delegation"), J("a5")],
        "confidence": 0.6,
    }
    fake = FakeBackend([json.dumps(bad), json.dumps(good)])
    run = analyse_opportunities(LLMClient(fake), POLICY_SEEDS, b, c.graph(), pols, lang="de")
    fb = fake.requests[1].messages[-1].content
    assert "not among its candidates" in fb and "release_gate_design is required" in fb
    assert "ghost" in fb and "missing judgements" in fb
    assert run.attempts == 2 and len(run.result.opportunities) == 3
    first = fake.requests[0].messages[0].content
    assert "tiered-delegation [established]" in first and "none (novel)" in first


def test_scoring_math():
    a = run_policy(
        [
            J("a2", "decision-brief", score=4),
            J("a4", "tiered-delegation", score=2),
            J("a5", score=5),
        ],
        confidence=0.5,
    )
    o = {x.id: x for x in a.opportunities}
    s = o["opp-a2"].scores
    expected = (4 * 3 + 4 * 2 + 4 * 1.5 + 4 + 4 + 4 + 4 * 1.5 + 4 * 1.5 + 4 * 0.5) / sum(
        WEIGHTS.values()
    )
    assert weighted_score(s) == pytest.approx(expected, abs=1e-3)
    assert rank_score(o["opp-a2"]) == pytest.approx(
        round(expected, 3) * o["opp-a2"].confidence, abs=1e-3
    )


def test_cli_opportunities(monkeypatch, capsys):
    from unclog import cli

    N = lambda i, p, link="acts_on", step="exploit", tag="non_ai", days=1: {  # noqa: E731
        "id": i,
        "parent_id": p,
        "statement": f"do {i}",
        "kind": "base_action",
        "constraint_link": link,
        "focus_step": step,
        "tag": tag,
        "effort_days": days,
    }
    tree = {
        "nodes": [
            N("a0", "opt-policy"),
            N("a1", "opt-batch"),
            {
                **N("a2", "opt-prepare", "protects", tag="ai_doable", days=5),
                "statement": POLICY_SEEDS[0].statement,
            },
            N("a3", "opt-delegate", step="elevate", tag="human", days=2),
        ],
        "confidence": 0.6,
    }
    opps = {"judgements": [J("a2", "decision-brief", reviewer="owner")], "confidence": 0.7}
    monkeypatch.setattr(
        cli,
        "make_llm",
        lambda budget=None, **kw: LLMClient(FakeBackend([json.dumps(tree), json.dumps(opps)])),
    )
    assert (
        cli.main(["opportunities", "--case", str(CASES / "hidden_policy_approval"), "--lang", "en"])
        == 0
    )
    out = capsys.readouterr().out
    assert "## Ranked actions" in out and "| Opportunity | Position |" in out
    assert "decision-brief" in out and "exploit-now" in out
