"""Run every synthetic case end to end and check it against its expected answer (brief §18)."""

from pathlib import Path

import pytest

from unclog.cli import main
from unclog.evals.cases import load_all
from unclog.evals.runner import MAX_RACE_BACKEND_GAP, run_all, run_case

ROOT = Path(__file__).parent.parent / "evals" / "cases"
CASES = load_all(ROOT)


def test_cases_cover_race_and_backend():
    kinds = [c.kind for c in CASES]
    assert kinds.count("race") >= 2 and kinds.count("backend") >= 2


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_case(case):
    res = run_case(case)
    failed = [k for k, v in res.checks.items() if not v]
    assert res.checks and not failed, f"{case.id}: failed checks {failed}"


def test_race_backend_accuracy_gap():
    s = run_all(ROOT)
    assert s.race_backend_gap is not None and s.race_backend_gap <= MAX_RACE_BACKEND_GAP


def test_flooding_what_if_on_backend_case():
    """RACE-vs-back-end what-if: +30% demand makes the back-end constraint worse, not better."""
    case = next(c for c in CASES if c.id == "backend_fulfillment_flood")
    g = case.graph()
    before = g.bottleneck()
    after = g.with_arrival_scale(1.3).bottleneck()
    assert after.resource_id == before.resource_id == "workshop"
    assert after.utilization == pytest.approx(before.utilization * 1.3)
    assert g.with_arrival_scale(1.3).effective_throughput() == pytest.approx(
        g.effective_throughput()
    )  # more leads, same output


def test_cli_eval_cases(capsys):
    assert main(["eval-cases", str(ROOT)]) == 0
    assert "binding accuracy" in capsys.readouterr().out
