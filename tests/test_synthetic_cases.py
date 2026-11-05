"""Run every synthetic case end to end and check it against its expected answer (brief §18)."""

from pathlib import Path

import pytest

from unclog.domains import build_heat_table
from unclog.evals.cases import load_all
from unclog.flow import compute
from unclog.ingestion import ingest_file

CASES = load_all(Path(__file__).parent.parent / "evals" / "cases")


def run(case):
    logs = []
    for f in case.raw_files:
        r = ingest_file(case.raw_path(f))
        assert r.event_logs, f"{f} should be detected as an event log"
        logs.append(("fulfillment", compute(r.event_logs[0]), r.source.id))
    return build_heat_table(case.metrics, case.graph(), event_logs=logs), logs


def test_cases_cover_race_and_backend():
    kinds = {c.kind for c in CASES}
    assert {"race", "backend"} <= kinds


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_case(case):
    table, logs = run(case)
    exp = case.expected
    top = table.candidates()[0].domain.value if table.candidates() else None
    assert top == exp["top_domain"]
    assert table.direction.verdict.value == exp["direction"]
    ranked = [r.domain.value for r in table.ranked()]
    for d in exp.get("must_rank_below_top", []):
        assert ranked.index(d) > 0
    if "coverage_issues" in exp:
        assert len(table.coverage_issues()) == exp["coverage_issues"]
    if "min_coverage_issues" in exp:
        assert len(table.coverage_issues()) >= exp["min_coverage_issues"]
    if "eventlog_slowest_wait" in exp:
        assert logs[0][1].slowest_wait().activity == exp["eventlog_slowest_wait"]


def test_flooding_what_if_on_backend_case():
    """RACE-vs-back-end what-if: +30% demand makes the back-end constraint worse, not better."""
    case = next(c for c in CASES if c.id == "backend_fulfillment_flood")
    g = case.graph()
    before = g.bottleneck()
    after = g.with_arrival_scale(1.3).bottleneck()
    assert after.resource_id == before.resource_id == "workshop"
    assert after.utilization == pytest.approx(before.utilization * 1.3)
