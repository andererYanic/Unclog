import json
from pathlib import Path

import pytest

from unclog import cli
from unclog.agents import AgentEscalation, factor_goal
from unclog.evals.cases import load_case
from unclog.evals.runner import run_case
from unclog.goalfactor import POLICY_BRANCH_ID, GoalTree, root_goal, skeleton
from unclog.llm import LLMClient
from unclog.llm.backends import FakeBackend
from unclog.schemas import GoalNode
from unclog.schemas.design import GoalNodeStatus

CASES = Path(__file__).parent.parent / "evals" / "cases"
A = dict(assumption=True, confidence=0.5)


def n(
    id_, parent, kind="base_action", link="acts_on", step="exploit", tag="non_ai", days=1.0, **kw
):
    if kind == "root":
        return GoalNode(id=id_, kind="root", statement="root goal", metric="m", **A)
    extra = {} if kind == "option" else {"tag": tag, "effort_days": days}
    return GoalNode(
        id=id_,
        parent_id=parent,
        kind=kind,
        statement=id_,
        constraint_link=link,
        focus_step=step,
        **extra,
        **A,
        **kw,
    )


def base_tree(*extra):
    return GoalTree(
        [
            n("root", None, "root"),
            n("o1", "root", "option"),
            n("o2", "root", "option", step="elevate"),
            *extra,
        ]
    )


def case(cid):
    c = load_case(CASES / cid)
    return c, run_case(c)


# ---- tree mechanics -----------------------------------------------------------------------
def test_structure_problems():
    t = base_tree(n("a1", "ghost"))
    assert any("does not exist" in p for p in t.structure_problems())
    two = GoalTree(
        [n("root", None, "root"), GoalNode(id="r2", kind="root", statement="x", metric="m", **A)]
    )
    assert any("exactly one root" in p for p in two.structure_problems())
    assert base_tree(n("a1", "o1")).structure_problems() == []


def test_prune_and_rank():
    t = base_tree(
        n("a-elev", "o2", step="elevate", tag="ai_assisted", days=5),
        n("a-prot", "o1", link="protects", tag="ai_doable", days=3),
        n("a-act", "o1", tag="non_ai", days=2),
        n("a-off", "o2", link="off_constraint", tag="ai_doable"),
        n("o3", "root", "option", link="off_constraint"),
        n("a-off2", "o3", link="off_constraint"),
    ).prune()
    status = {x.id: x.status for x in t.nodes}
    assert status["a-off"] is GoalNodeStatus.pruned and status["o3"] is GoalNodeStatus.pruned
    assert status["o1"] is GoalNodeStatus.chosen
    assert [a.id for a in t.ranked_actions()] == ["a-act", "a-prot", "a-elev"]
    assert [a.id for a in t.opportunity_seeds()] == ["a-prot", "a-elev"]
    assert t.quality_problems() == []
    md = t.to_markdown()
    assert "(pruned)" in md and "1. [non_ai] a-act" in md
    assert t.to_mermaid().startswith("graph TD") and "stroke-dasharray" in t.to_mermaid()


@pytest.mark.parametrize(
    "extra,msg",
    [
        (
            (
                n("a1", "o1", tag="ai_doable"),
                n("a2", "o1", tag="ai_doable"),
                n("a3", "o1", tag="human"),
            ),
            "no non-AI fix",
        ),
        ((n("a1", "o1"), n("a2", "o1"), n("a3", "o1", days=30)), "doable in days"),
        (
            (
                n("a1", "o2", step="elevate"),
                n("a2", "o2", step="elevate"),
                n("a3", "o2", step="elevate"),
            ),
            "no exploit-step",
        ),
        (
            (
                n("a1", "o1"),
                n("a2", "o1, ".strip(", ")),
            ),
            "only 2 live",
        ),
    ],
)
def test_quality_problems(extra, msg):
    problems = base_tree(*extra).prune().quality_problems()
    assert any(msg in p for p in problems), problems


def test_policy_branch_required():
    t = GoalTree(
        [
            n("root", None, "root"),
            n(POLICY_BRANCH_ID, "root", "option"),
            n("o1", "root", "option"),
            n("a1", "o1"),
            n("a2", "o1"),
            n("a3", "o1"),
        ]
    ).prune()
    assert any("policy branch" in p for p in t.quality_problems(POLICY_BRANCH_ID))


# ---- root goals ------------------------------------------------------------------------------
def test_root_goals_from_data():
    c, r = case("backend_fulfillment_flood")
    root = root_goal(r.report.binding, c.graph(), c.metrics, lang="en")
    assert "4 carpenters" in root.statement and "19.0 to 22.0" in root.statement
    assert root.evidence  # grounded in the constraint's evidence
    c, r = case("race_speed_to_lead")
    root = root_goal(r.report.binding, c.graph(), c.metrics, r.report.policy_audit.policies)
    assert "~52 h to <= 1 h" in root.statement  # stage benchmark beats the 24 h default
    c, r = case("market_after_elevation")
    root = root_goal(r.report.binding, c.graph(), c.metrics, lang="de")
    assert root.statement == "'shop sessions' von 1200 auf 2000 per week bringen"


def test_skeleton_per_type_bilingual():
    _, r = case("hidden_policy_approval")
    de, en = skeleton(r.report.binding, "de"), skeleton(r.report.binding, "en")
    assert [s.id for s in de] == [s.id for s in en] and de[0].id == POLICY_BRANCH_ID
    assert de[0].statement != en[0].statement
    _, r = case("backend_fulfillment_flood")
    steps = {s.focus_step.value for s in skeleton(r.report.binding)}
    assert steps == {"exploit", "subordinate", "elevate"}


# ---- agent -----------------------------------------------------------------------------------
def N(id_, parent, kind="base_action", link="acts_on", step="exploit", tag="non_ai", days=1):
    return {
        "id": id_,
        "parent_id": parent,
        "statement": f"do {id_}",
        "kind": kind,
        "constraint_link": link,
        "focus_step": step,
        "tag": tag if kind == "base_action" else None,
        "effort_days": days if kind == "base_action" else None,
    }


GOOD = {
    "nodes": [
        N("a0", "opt-policy"),
        N("a1", "opt-batch"),
        N("a2", "opt-prepare", link="protects", tag="ai_doable", days=5),
        N("a3", "opt-delegate", step="elevate", tag="human", days=2),
        N("x1", "root", link="off_constraint", tag="ai_doable", days=5),
    ],
    "open_questions": [],
    "confidence": 0.6,
}


def test_factor_goal_retries_then_succeeds():
    c, r = case("hidden_policy_approval")
    bad = {"nodes": [N("root", "opt-batch"), N("a2", "opt-prepare", days=30)], "confidence": 0.5}
    fake = FakeBackend([json.dumps(bad), json.dumps(GOOD)])
    run = factor_goal(
        LLMClient(fake),
        r.report.binding,
        c.graph(),
        c.metrics,
        r.report.policy_audit.policies,
        lang="de",
    )
    assert run.attempts == 2
    feedback = fake.requests[1].messages[-1].content
    assert "reserved" in feedback and "doable in days" in feedback
    first = fake.requests[0].messages[0].content
    assert "Root goal (id root, do not change)" in first and "opt-policy" in first
    tree = run.result
    assert [a.id for a in tree.opportunity_seeds()] == ["a2"]
    assert tree.node("x1").status is GoalNodeStatus.pruned


def test_factor_goal_escalates():
    c, r = case("hidden_policy_approval")
    junk = {"nodes": [N("a1", "opt-batch", tag="ai_doable")], "confidence": 0.3}
    with pytest.raises(AgentEscalation):
        factor_goal(
            LLMClient(FakeBackend(lambda q: json.dumps(junk))),
            r.report.binding,
            c.graph(),
            c.metrics,
            r.report.policy_audit.policies,
        )


def test_cli_goal_tree(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "make_llm", lambda budget=None, **kw: LLMClient(FakeBackend([json.dumps(GOOD)]))
    )
    assert (
        cli.main(
            [
                "goal-tree",
                "--case",
                str(CASES / "hidden_policy_approval"),
                "--lang",
                "en",
                "--mermaid",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "## Ranked actions" in out and "graph TD" in out
    assert cli.main(["goal-tree", "--case", str(CASES / "no_tracking")]) == 1
