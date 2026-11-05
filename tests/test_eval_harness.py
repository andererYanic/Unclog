import itertools
import json
from pathlib import Path

import pytest

from unclog import cli
from unclog.evals.agents import (
    extractor_system,
    goal_factoring_system,
    grade_extraction,
    grade_goal_tree,
)
from unclog.evals.harness import (
    AgentCase,
    EvalReport,
    Grade,
    System,
    collect_ratings,
    compare,
    gate_g14,
    llm_judge,
    load_cases,
    log_decision,
    run_eval,
    suite_for,
)
from unclog.llm import LLMClient, LLMRequest
from unclog.llm.backends import FakeBackend
from unclog.llm.types import Message

ROOT = Path(__file__).parent.parent
AGENTS = ROOT / "evals" / "agents"


def toy(scores_by_case: dict[str, list[float]]) -> tuple[System, list[AgentCase]]:
    def run(case, i):
        s = scores_by_case[case.id][i % len(scores_by_case[case.id])]
        if s < 0:
            raise RuntimeError("boom")
        return s

    cases = [AgentCase(cid, {}, {}) for cid in scores_by_case]
    return System("toy", run), cases


def by_value(case, out) -> Grade:
    return Grade(out, () if out >= 5 else ("low",))


def test_run_eval_distribution_and_errors():
    system, cases = toy({"a": [8, 9, 7, 10], "b": [6, -1]})
    r = run_eval(system, cases, [by_value], n=10)
    a, b = r.per_case["a"], r.per_case["b"]
    assert len(a.scores) == 10 and a.worst == 7 and a.spread == 3
    assert b.worst == 0 and b.failures["error: RuntimeError"] == 5  # crashes score 0, not skip
    assert r.run.n == 20 and r.run.worst_case == 0
    back = EvalReport.from_json(r.to_json())
    assert back.run.mean == pytest.approx(r.run.mean) and back.per_case["b"].failures
    assert "| a |" in r.to_markdown()


def test_gate_g14():
    system, cases = toy({"a": [8, 9], "b": [7, 8]})
    suite = suite_for("toy", cases, "rubric", pass_mean=7, pass_worst_case=5)
    assert gate_g14(run_eval(system, cases, [by_value], n=10), suite) == []
    short = gate_g14(run_eval(system, cases, [by_value], n=3), suite)
    assert any("3 runs < 10" in p for p in short)
    system2, _ = toy({"a": [9, 9, 9, 2], "b": [8]})
    floor = gate_g14(run_eval(system2, cases, [by_value], n=10), suite)
    assert any("worst case 2.00 < floor" in p for p in floor)


def test_compare_mean_and_worst_case(tmp_path):
    s1, cases = toy({"a": [6, 7], "b": [6, 6]})
    s2, _ = toy({"a": [8, 9], "b": [7, 8]})
    s3, _ = toy({"a": [10, 10, 10, 3], "b": [9, 9]})  # better mean, worse worst case
    base = run_eval(s1, cases, [by_value], n=10)
    better = run_eval(s2, cases, [by_value], n=10)
    risky = run_eval(s3, cases, [by_value], n=10)
    assert compare(base, better).accept
    d = compare(base, risky)
    assert not d.accept and any("worst case of a degraded" in r for r in d.reasons)
    assert not compare(better, base).accept
    log = tmp_path / "hill.jsonl"
    log_decision(log, base, better, compare(base, better), "prompt v2")
    entry = json.loads(log.read_text())
    assert entry["accept"] and entry["change"] == "prompt v2"


def test_human_ratings():
    system, cases = toy({"a": [8]})
    r = run_eval(system, cases, [by_value], n=3)
    answers = iter(["7", "", "9"])
    shown = []
    rated = collect_ratings(r, ask=lambda _: next(answers), show=shown.append)
    assert rated.run.human_ratings == [7.0, 9.0] and len(shown) == 3
    assert "Human ratings: mean 8.00" in rated.to_markdown()


def test_llm_judge_grader():
    fake = FakeBackend(['{"score": 4, "reasons": "vague actions"}'])
    g = llm_judge(LLMClient(fake), "be concrete")(AgentCase("c", {}, {"x": 1}), "output text")
    assert g.score == 4 and g.failures and "vague" in g.failures[0]
    assert "<output>" in fake.requests[0].messages[0].content


def test_default_model_override():
    fake = FakeBackend(["ok"])
    LLMClient(fake, default_model="claude-sonnet-5-5").complete(
        LLMRequest(messages=[Message(role="user", content="hi")])
    )
    assert fake.requests[0].model == "claude-sonnet-5-5"


# ---- real agents under the harness (scripted model) ----------------------------------------
def de_good() -> dict:
    return {
        "metrics": [
            {
                "domain": "RACE-A",
                "name": "Anfragen",
                "value": 45,
                "unit": "pro Woche",
                "is_estimate": True,
                "quote": "so 40 bis 50 Anfragen pro Woche",
                "locator": "t=00:01:00.000",
            },
            {
                "domain": "RACE-C",
                "name": "Angebot -> Auftrag",
                "value": 0.333,
                "unit": "ratio",
                "is_estimate": True,
                "quote": "Ungefähr jedes dritte Angebot wird zum Auftrag",
                "locator": "t=00:01:20.000",
            },
        ],
        "policies": [
            {
                "kind": "approval",
                "statement": "Inhaber unterschreibt freitags",
                "quote": "Die Angebote unterschreibe ich selbst, immer freitags",
                "locator": "t=00:02:10.000",
            }
        ],
        "confidence": 0.7,
    }


def test_extractor_under_harness_shows_spread():
    good = de_good()
    partial = de_good()
    partial["metrics"] = partial["metrics"][:1]
    partial["policies"] = []
    outputs = itertools.cycle([json.dumps(good), json.dumps(partial)])
    fake = FakeBackend(lambda req: next(outputs))
    cases = [c for c in load_cases(AGENTS / "transcript_extractor") if c.id == "de_kitchen_owner"]
    report = run_eval(extractor_system(lambda: LLMClient(fake)), cases, [grade_extraction], n=10)
    st = report.per_case["de_kitchen_owner"]
    assert max(st.scores) == pytest.approx(10.0) and st.worst < 7
    assert st.failures["missed RACE-C=0.333"] == 5 and st.failures["missed policy approval"] == 5
    assert gate_g14(report, suite_for("x", cases, "r", pass_worst_case=5)) == []  # 6 >= 5
    strict = gate_g14(report, suite_for("x", cases, "r", pass_worst_case=7))
    assert any("worst case 6.00 < floor 7" in p for p in strict)


def test_goal_factoring_under_harness():
    N = lambda i, p, link="acts_on", step="exploit", tag="non_ai", days=1, st=None: {  # noqa
        "id": i,
        "parent_id": p,
        "statement": st or f"do {i}",
        "kind": "base_action",
        "constraint_link": link,
        "focus_step": step,
        "tag": tag,
        "effort_days": days,
    }
    tree = {
        "nodes": [
            N("a0", "opt-policy", st="Freigabegrenze auf 20.000 EUR anheben"),
            N("a1", "opt-batch", st="Freigaben täglich statt freitags"),
            N(
                "a2",
                "opt-prepare",
                "protects",
                tag="ai_doable",
                days=5,
                st="Angebots-Check automatisch vorbereiten",
            ),
            N("x1", "root", "off_constraint", tag="ai_doable", st="Chatbot für die Website"),
        ],
        "confidence": 0.6,
    }
    fake = FakeBackend(lambda req: json.dumps(tree))
    cases = [c for c in load_cases(AGENTS / "goal_factoring") if c.id == "policy_owner_signoff"]
    report = run_eval(
        goal_factoring_system(lambda: LLMClient(fake), ROOT / "evals" / "cases"),
        cases,
        [grade_goal_tree],
        n=10,
    )
    st = report.per_case["policy_owner_signoff"]
    assert st.worst == pytest.approx(10.0), st.failures  # pruned chatbot is not "live"
    assert "## Ranked actions" in report.samples[0]["output"]


def test_cli_eval_agent_compare_and_rate(tmp_path, monkeypatch, capsys):
    tree = {
        "nodes": [
            {
                "id": "a0",
                "parent_id": "opt-policy",
                "statement": "Freigabegrenze anheben",
                "kind": "base_action",
                "constraint_link": "acts_on",
                "focus_step": "exploit",
                "tag": "non_ai",
                "effort_days": 1,
            },
            {
                "id": "a1",
                "parent_id": "opt-batch",
                "statement": "täglich freigeben",
                "kind": "base_action",
                "constraint_link": "acts_on",
                "focus_step": "exploit",
                "tag": "non_ai",
                "effort_days": 1,
            },
            {
                "id": "a2",
                "parent_id": "opt-prepare",
                "statement": "Angebots-Check vorbereiten",
                "kind": "base_action",
                "constraint_link": "protects",
                "focus_step": "exploit",
                "tag": "ai_doable",
                "effort_days": 3,
            },
        ],
        "confidence": 0.6,
    }
    monkeypatch.setattr(
        cli,
        "make_llm",
        lambda budget=None, **kw: LLMClient(FakeBackend(lambda req: json.dumps(tree))),
    )
    root = tmp_path / "agents"
    (root / "goal_factoring").mkdir(parents=True)
    src = AGENTS / "goal_factoring" / "policy_owner_signoff.json"
    (root / "goal_factoring" / src.name).write_text(src.read_text())
    out = tmp_path / "results"
    args = [
        "eval-agent",
        "goal_factoring",
        "--n",
        "10",
        "--root",
        str(root),
        "--cases-root",
        str(ROOT / "evals" / "cases"),
        "--out",
        str(out),
    ]
    assert cli.main(args) == 0
    text = capsys.readouterr().out
    assert "G14: pass" in text
    reports = sorted((out / "goal_factoring").glob("*.json"))
    assert cli.main(args) == 0
    capsys.readouterr()
    reports = sorted((out / "goal_factoring").glob("*.json"))
    assert len(reports) == 2
    log = tmp_path / "hill.jsonl"
    assert (
        cli.main(
            [
                "eval-compare",
                str(reports[0]),
                str(reports[1]),
                "--log",
                str(log),
                "--change",
                "rerun",
            ]
        )
        == 1
    )  # identical means: no improvement -> reject
    assert "REJECT" in capsys.readouterr().out and log.exists()
    answers = iter(["8", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.main(["eval-rate", str(reports[0]), "--limit", "3"]) == 0
    assert EvalReport.from_json(reports[0].read_text()).run.human_ratings == [8.0]
