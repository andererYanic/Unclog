from datetime import datetime, timedelta

import pytest

from unclog.flow import compute, to_stage_metrics
from unclog.ingestion.models import Event, EventLog


def _log(rows):
    t0 = datetime(2026, 10, 1, 9)
    return EventLog(
        source_id="src-x",
        table_name="t",
        events=[
            Event(case_id=c, activity=a, timestamp=t0 + timedelta(hours=h), resource=r, row=i)
            for i, (c, a, h, r) in enumerate(rows, 1)
        ],
    )


def test_waits_lead_times_wip():
    log = _log(
        [
            ("A", "created", 0, None),
            ("A", "approved", 10, "mara"),
            ("A", "closed", 12, "mara"),
            ("B", "created", 1, None),
            ("B", "approved", 31, "jo"),
            ("B", "closed", 32, "jo"),
            ("C", "created", 300, None),
        ]
    )
    st = compute(log)
    assert st.end_activities == ("closed",)
    assert st.cases == 3 and st.completed_cases == 2 and st.open_cases == 1
    a = st.activities["approved"]
    assert a.wait_median_h == pytest.approx(20) and a.resources == ("jo", "mara")
    assert st.slowest_wait().activity == "approved"
    assert st.lead_time_median_h == pytest.approx(21.5)
    assert st.span_days == pytest.approx(300 / 24)
    ms = to_stage_metrics(st, "support", "src-x", "2026-10")
    assert all(m.measured and m.source_id == "src-x" for m in ms)
    assert {m.id for m in ms} >= {"support-maxwait", "support-leadtime", "support-wip"}


def test_explicit_end_activities_and_empty():
    st = compute(_log([("A", "x", 0, None), ("A", "y", 5, None)]), end_activities=["x"])
    assert st.completed_cases == 0
    with pytest.raises(ValueError):
        compute(EventLog(source_id="s", table_name="t", events=[]))
