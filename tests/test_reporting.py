import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from unclog import cli
from unclog.agents.opportunity_analyst import AnalystOutput, assemble, make_seeds
from unclog.evals.cases import load_case
from unclog.evals.runner import run_case
from unclog.goalfactor import GoalTree, root_goal, skeleton
from unclog.reporting import Bundle, design_dbr, plan, write
from unclog.schemas import GoalNode
from unclog.schemas.design import Priority
from unclog.scoring.value import (
    CostInputs,
    Economics,
    Effect,
    OpportunityInput,
    SimSettings,
    value_portfolio,
)

CASES = Path(__file__).parent.parent / "evals" / "cases"
A = dict(assumption=True, confidence=0.6)


def diag(cid, lang="en"):
    c = load_case(CASES / cid)
    r = run_case(c, lang=lang)  # includes raw files (event logs, policy documents)
    return c, c.graph(), r.heat, r.report


def tree_for(rep, c, g, lang="en"):
    b = rep.binding
    nodes = [root_goal(b, g, c.metrics, rep.policy_audit.policies, lang), *skeleton(b, lang)]
    act = lambda i, p, st, tag="non_ai", step="exploit", link="acts_on": GoalNode(  # noqa
        id=i,
        parent_id=p,
        kind="base_action",
        statement=st,
        tag=tag,
        focus_step=step,
        constraint_link=link,
        effort_days=2,
        **A,
    )
    first = nodes[1].id
    elevate = next(n.id for n in nodes if n.focus_step and n.focus_step.value == "elevate")
    nodes += [
        act("a1", first, "Remove admin work from the workshop team"),
        act(
            "a2",
            first,
            "Check orders for missing data before production",
            tag="ai_doable",
            link="protects",
        ),
        act("a3", elevate, "Hire a fifth carpenter", tag="human", step="elevate"),
    ]
    return GoalTree(nodes).prune()


# ---- roadmap ---------------------------------------------------------------------------------
def test_dbr_by_constraint_type():
    c, g, heat, rep = diag("backend_fulfillment_flood")
    d = design_dbr(rep.binding, g)
    assert d.drum == "4 carpenters" and d.buffer.size_h == 168 and "≤ 19" in d.rope
    _, _, _, rep2 = diag("hidden_policy_approval")
    assert "rule" in design_dbr(rep2.binding, None).notes[0]
    _, _, _, rep3 = diag("market_after_elevation")
    assert "protective capacity" in design_dbr(rep3.binding, None).rope


def test_plan_sequences_waves_and_gates_elevate():
    c, g, heat, rep = diag("backend_fulfillment_flood")
    t = tree_for(rep, c, g)
    rm = plan(rep, t, None, g, c.metrics)
    waves = [i.wave for i in rm.items]
    assert waves == sorted(
        waves, key=["measure", "exploit", "subordinate", "elevate", "backlog"].index
    )
    elev = rm.wave("elevate")
    assert elev and all("results ledger" in (i.start_condition or "") for i in elev)
    assert any(i.title.startswith("Remove admin") for i in rm.wave("exploit"))
    assert any("designer" in t for t in rm.rebaseline_triggers)
    assert rm.kpis[0].baseline == pytest.approx(g.effective_throughput(), abs=0.01)
    with pytest.raises(ValueError, match="G4"):
        plan(diag("no_tracking")[3])


def test_plan_with_opportunities_and_fix_first():
    c, g, heat, rep = diag("hidden_policy_approval")
    b = rep.binding
    seed = GoalNode(
        id="s1",
        parent_id="opt-prepare",
        kind="base_action",
        statement="Angebots-Check (Marge, Risiko, fehlende Angaben) vorbereiten",
        tag="ai_doable",
        focus_step="exploit",
        constraint_link="protects",
        effort_days=3,
        **A,
    )
    seeds = make_seeds([seed], b)
    sc = {"score": 4, "justification": "because"}
    j = {
        "seed_id": "s1",
        "pattern_id": seeds[0].candidates[0].pattern.id,
        "title": "Brief",
        "ai_role": "assist",
        "human_in_loop_design": "owner reviews",
        "release_gate_design": "one per quote",
        "items_per_week": 27,
        "review_minutes_per_item": 1,
        "reviewer_resource_id": "owner",
        "output_verification": "spot check",
        "cost_of_error": "low",
        "client_owner_role": "Sales lead",
        "tech_approach": "CRM export",
        "build_vs_buy": "build",
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
    out = AnalystOutput.model_validate({"judgements": [j], "confidence": 0.7})
    from unclog.schemas.engagement import ProcessHealth

    broken = assemble(out, seeds, b, g, rep.policy_audit.policies, {"mgmt": ProcessHealth.broken})
    rm = plan(rep, None, broken, g, c.metrics)
    fix = [i for i in rm.items if i.kind == "fix_process"]
    assert fix and fix[0].wave == "exploit" and fix[0].title.startswith("Fix process before")
    assert broken.opportunities[0].priority is Priority.fix_process_first


# ---- writer ----------------------------------------------------------------------------------
def test_diagnosis_only_package_de(tmp_path):
    c, g, heat, rep = diag("no_tracking", "de")
    paths = write(Bundle("Dienstleister", "de", heat, rep, None, c.metrics), tmp_path)
    names = [p.name for p in paths]
    assert names == ["01-executive-summary.md", "02-constraint-report.md", "export.json"]
    text = (tmp_path / "01-executive-summary.md").read_text()
    assert text.startswith("> ENTWURF") and "Noch kein Engpass bestätigt" in text
    assert "Einen Vorgang vom Markt bis zum Geldeingang abbilden" in text
    exp = json.loads((tmp_path / "export.json").read_text())
    assert exp["binding_constraint"] is None and len(exp["domains"]) == 15


def test_full_package_en(tmp_path):
    c, g, heat, rep = diag("backend_fulfillment_flood")
    t = tree_for(rep, c, g)
    econ = Economics(throughput_per_unit=1200, inventory_value_per_unit=900)
    from unclog.schemas import Opportunity

    opp = Opportunity(
        id="opp-a2",
        title="Order pre-check",
        ai_role="gate",
        position="upstream",
        focus_step="exploit",
        constraint_id=rep.binding.id,
        constraint_link="protects",
        proven=True,
        proof_refs=["lib:x"],
        process_health_ok=True,
        release_gate_required=True,
        release_gate_design="only complete orders enter",
        client_owner="Shop lead",
        **A,
    )
    value = value_portfolio(
        g,
        [
            OpportunityInput(
                opp, (Effect("capacity", "workshop", 0.05, 0.1, 0.15),), CostInputs(build_cost=6000)
            )
        ],
        econ,
        SimSettings(replications=3, horizon_weeks=10),
    )
    rm = plan(rep, t, None, g, c.metrics)
    b = Bundle(
        "Furniture shop",
        "en",
        heat,
        rep,
        g,
        c.metrics,
        tree=t,
        value=value,
        economics=econ,
        roadmap=rm,
        open_decisions=["Pick runner platform (012)"],
    )
    paths = write(b, tmp_path)
    names = {p.name for p in paths}
    assert {
        "01-executive-summary.md",
        "03-goal-tree.md",
        "04-roadmap-dbr.md",
        "07-value.md",
        "07-value-workbook.xlsx",
        "export.json",
    } <= names
    summary = (tmp_path / "01-executive-summary.md").read_text()
    assert "4 carpenters cannot keep up" in summary and "Raise throughput" in summary
    assert "- [ ] Pick runner platform (012)" in summary and "Monthly profit effect" in summary
    road = (tmp_path / "04-roadmap-dbr.md").read_text()
    assert "**Drum:** 4 carpenters" in road and "Wave 3 — elevate" in road
    assert "```mermaid" in (tmp_path / "03-goal-tree.md").read_text()
    wb = load_workbook(tmp_path / "07-value-workbook.xlsx")
    assert wb.sheetnames == ["value lines", "mirage ledger", "assumptions"]
    assert wb["value lines"].max_row == 4  # header + low/base/high
    assert "| workshop |" in (tmp_path / "02-constraint-report.md").read_text()


def test_cli_report(tmp_path, capsys):
    assert (
        cli.main(
            [
                "report",
                "--case",
                str(CASES / "hidden_policy_approval"),
                "--out",
                str(tmp_path),
                "--lang",
                "de",
                "--replications",
                "2",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "04-roadmap-dbr.md" in out and "09-simulation.md" in out
    assert "Eine Regel bremst das Unternehmen" in (tmp_path / "01-executive-summary.md").read_text()
