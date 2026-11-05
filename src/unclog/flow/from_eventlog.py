"""Draft a measured flow fragment from an event log (no model; brief §8.1 "prefer logs").

One node per activity, ordered by typical position within a case. Edge probability = share of
cases reaching the next activity. ``wait_time_h`` = median wait before the activity; ``queue
length`` = open cases whose last event is the previous activity (they wait in front of this
one). Resources are not in most logs: they are left empty for the Flow Modeler or consultant.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from ..ingestion.models import EventLog
from ..schemas.common import Evidence, EvidenceType
from ..schemas.diagnosis import Distribution, FlowEdge, FlowNode
from .eventlog_stats import compute


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "step"


def flow_from_event_log(
    log: EventLog, domain: str, source_id: str, prefix: str = "log"
) -> tuple[list[FlowNode], list[FlowEdge]]:
    stats = compute(log)
    by_case: dict[str, list] = defaultdict(list)
    for e in log.events:
        by_case[e.case_id].append(e)
    rank: dict[str, list[int]] = defaultdict(list)
    reached: dict[str, int] = defaultdict(int)
    last_of_open: dict[str, int] = defaultdict(int)
    ends = set(stats.end_activities)
    for evs in by_case.values():
        evs.sort(key=lambda e: e.timestamp)
        seen = set()
        for i, e in enumerate(evs):
            rank[e.activity].append(i)
            if e.activity not in seen:
                reached[e.activity] += 1
                seen.add(e.activity)
        if evs[-1].activity not in ends:
            last_of_open[evs[-1].activity] += 1
    order = sorted(rank, key=lambda a: (statistics.median(rank[a]), -reached[a]))
    ids = {a: f"{prefix}-{_slug(a)}" for a in order}

    nodes: list[FlowNode] = []
    for i, a in enumerate(order):
        st = stats.activities[a]
        prev = order[i - 1] if i > 0 else None
        ev = Evidence(
            id=f"ev-{source_id}-{_slug(a)}",
            source_id=source_id,
            type=EvidenceType.log_data,
            locator=f"activity {a}",
            note=f"{st.count} events",
        )
        nodes.append(
            FlowNode(
                id=ids[a],
                name=a.replace("_", " "),
                domain_id=domain,
                arrival=Distribution(
                    kind="poisson", params={"rate": round(stats.arrivals_per_week, 3)}, unit="week"
                )
                if i == 0
                else None,
                wait_time_h=round(st.wait_median_h, 2) if st.wait_median_h is not None else None,
                queue_length=float(last_of_open.get(prev, 0)) if prev else None,
                evidence=[ev],
            )
        )
    edges = []
    for a, b in zip(order, order[1:], strict=False):
        # Cases still waiting after `a` are in progress, not lost: exclude them.
        decided = reached[a] - last_of_open.get(a, 0)
        p = min(1.0, reached[b] / decided) if decided > 0 else 1.0
        edges.append(
            FlowEdge(source=ids[a], target=ids[b], probability=round(p, 4), label="measured")
        )
    return nodes, edges
