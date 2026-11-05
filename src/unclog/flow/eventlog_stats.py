"""Process-mining-lite statistics from an EventLog (brief §8.1: prefer logs over estimates).

Waiting time before an activity = time since the previous event in the same case. For most
business processes this is queue + touch time; it is where "elapsed time is mostly waiting"
shows up in the data.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from ..ingestion.models import EventLog
from ..schemas.diagnosis import StageMetric


def _pct(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass(frozen=True)
class ActivityStats:
    activity: str
    count: int
    wait_median_h: float | None
    wait_p90_h: float | None
    resources: tuple[str, ...]


@dataclass(frozen=True)
class EventLogStats:
    cases: int
    completed_cases: int
    open_cases: int  # WIP at end of log
    span_days: float
    arrivals_per_week: float
    completions_per_week: float
    lead_time_median_h: float | None
    lead_time_p90_h: float | None
    activities: dict[str, ActivityStats]
    end_activities: tuple[str, ...]

    def slowest_wait(self) -> ActivityStats | None:
        waits = [a for a in self.activities.values() if a.wait_median_h is not None]
        return max(waits, key=lambda a: a.wait_median_h) if waits else None


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def compute(log: EventLog, end_activities: list[str] | None = None) -> EventLogStats:
    if not log.events:
        raise ValueError("empty event log")
    by_case: dict[str, list] = defaultdict(list)
    for e in log.events:
        by_case[e.case_id].append(e)
    for evs in by_case.values():
        evs.sort(key=lambda e: e.timestamp)

    if end_activities is None:
        # default: activities that are the last event of most cases they occur in
        last_counts: dict[str, int] = defaultdict(int)
        occur: dict[str, int] = defaultdict(int)
        for evs in by_case.values():
            last_counts[evs[-1].activity] += 1
            for a in {e.activity for e in evs}:
                occur[a] += 1
        if len(by_case) == 1:
            end_activities = list(last_counts)
        else:
            end_activities = sorted(a for a, n in last_counts.items() if n / occur[a] >= 0.8)
    ends = set(end_activities)

    waits: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    res: dict[str, set[str]] = defaultdict(set)
    lead_times: list[float] = []
    completed = 0
    for evs in by_case.values():
        for prev, cur in zip(evs, evs[1:], strict=False):
            waits[cur.activity].append(_hours(prev.timestamp, cur.timestamp))
        for e in evs:
            counts[e.activity] += 1
            if e.resource:
                res[e.activity].add(e.resource)
        if evs[-1].activity in ends:
            completed += 1
            lead_times.append(_hours(evs[0].timestamp, evs[-1].timestamp))

    t0 = min(e.timestamp for e in log.events)
    t1 = max(e.timestamp for e in log.events)
    span_days = max(_hours(t0, t1) / 24, 1.0)
    weeks = span_days / 7
    # Arrivals are counted over the window in which cases *started*; the tail of the log
    # (late steps of old cases) would otherwise dilute the rate.
    starts = sorted(evs[0].timestamp for evs in by_case.values())
    arrival_weeks = max(_hours(starts[0], starts[-1]) / 168, 1 / 7) if len(starts) > 1 else weeks
    arrival_weeks *= len(starts) / max(len(starts) - 1, 1)  # n arrivals span n-1 gaps
    activities = {
        a: ActivityStats(
            activity=a,
            count=counts[a],
            wait_median_h=statistics.median(waits[a]) if waits[a] else None,
            wait_p90_h=_pct(waits[a], 0.9) if waits[a] else None,
            resources=tuple(sorted(res[a])),
        )
        for a in counts
    }
    return EventLogStats(
        cases=len(by_case),
        completed_cases=completed,
        open_cases=len(by_case) - completed,
        span_days=span_days,
        arrivals_per_week=len(by_case) / arrival_weeks,
        completions_per_week=completed / weeks,
        lead_time_median_h=statistics.median(lead_times) if lead_times else None,
        lead_time_p90_h=_pct(lead_times, 0.9) if lead_times else None,
        activities=activities,
        end_activities=tuple(sorted(ends)),
    )


def to_stage_metrics(
    stats: EventLogStats, domain: str, source_id: str, period: str, prefix: str = ""
) -> list[StageMetric]:
    """Measured StageMetrics for the domain heat table, traced to the log's Source (G17)."""
    p = f"{prefix}-" if prefix else ""
    out = [
        StageMetric(
            id=f"{p}{domain}-arrivals",
            domain_id=domain,
            name="case arrivals",
            value=round(stats.arrivals_per_week, 3),
            unit="cases/week",
            period=period,
            source_id=source_id,
            measured=True,
        ),
        StageMetric(
            id=f"{p}{domain}-completions",
            domain_id=domain,
            name="case completions",
            value=round(stats.completions_per_week, 3),
            unit="cases/week",
            period=period,
            source_id=source_id,
            measured=True,
            higher_is_better=True,
        ),
        StageMetric(
            id=f"{p}{domain}-wip",
            domain_id=domain,
            name="open cases (WIP)",
            value=stats.open_cases,
            unit="cases",
            period=period,
            source_id=source_id,
            measured=True,
            higher_is_better=False,
        ),
    ]
    if stats.lead_time_median_h is not None:
        out.append(
            StageMetric(
                id=f"{p}{domain}-leadtime",
                domain_id=domain,
                name="lead time (median)",
                value=round(stats.lead_time_median_h, 2),
                unit="h",
                period=period,
                source_id=source_id,
                measured=True,
                higher_is_better=False,
            )
        )
    slow = stats.slowest_wait()
    if slow is not None:
        out.append(
            StageMetric(
                id=f"{p}{domain}-maxwait",
                domain_id=domain,
                name=f"median wait before '{slow.activity}'",
                value=round(slow.wait_median_h, 2),
                unit="h",
                period=period,
                source_id=source_id,
                measured=True,
                higher_is_better=False,
            )
        )
    return out
