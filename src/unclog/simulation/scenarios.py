"""Scenarios, Monte Carlo replications and comparison (brief §10).

Standard scenario set: baseline; exploit (shrink a batch); elevate (+capacity at the
constraint); demand what-if (+X% arrivals, the RACE-vs-back-end question); flooding
counterfactual (demand up without a rope) vs subordinate (same demand with a rope gate).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..flow.graph import FlowGraph
from ..schemas.design import SimRun
from .engine import RepResult, Simulator, percentile


@dataclass(frozen=True)
class Scenario:
    name: str
    arrival_scale: float = 1.0
    arrival_entries: tuple[str, ...] | None = None
    capacity: dict[str, float] = field(default_factory=dict)  # resource -> factor
    batch: dict[str, float] = field(default_factory=dict)  # node -> batch size
    rope: tuple[str, int] | None = None  # (gate node, WIP limit)

    def apply(self, graph: FlowGraph) -> FlowGraph:
        g = graph
        if self.arrival_scale != 1.0:
            g = g.with_arrival_scale(self.arrival_scale, list(self.arrival_entries or []) or None)
        for rid, f in self.capacity.items():
            g = g.with_capacity_scale(rid, f)
        return g


@dataclass(frozen=True)
class Band:
    mean: float | None
    p05: float | None
    p95: float | None

    @staticmethod
    def of(values: list[float | None]) -> Band:
        vs = [v for v in values if v is not None]
        if not vs:
            return Band(None, None, None)
        return Band(statistics.fmean(vs), percentile(vs, 0.05), percentile(vs, 0.95))

    def fmt(self, unit: str = "", digits: int = 1) -> str:
        if self.mean is None:
            return "–"
        return f"{self.mean:.{digits}f}{unit} [{self.p05:.{digits}f}–{self.p95:.{digits}f}]"


@dataclass
class SimResult:
    scenario: Scenario
    seed: int
    replications: int
    horizon_weeks: float
    warmup_weeks: float
    reps: list[RepResult]
    throughput: Band
    lead_p50_h: Band
    lead_p90_h: Band
    internal_p50_h: Band
    internal_p90_h: Band
    wip_total: Band
    wip_by_node: dict[str, float]
    queue_by_node: dict[str, float]
    utilization: dict[str, float]
    constraint_location: str | None
    gate_backlog_end: Band
    gate_wait_p50_h: Band
    reneged_per_week: Band | None = None

    def to_simrun(self, run_id: str, inputs_ref: str) -> SimRun:
        return SimRun(
            id=run_id,
            scenario=self.scenario.name,
            seed=self.seed,
            replications=self.replications,
            horizon=f"{self.horizon_weeks:g} weeks (warm-up {self.warmup_weeks:g})",
            inputs_ref=inputs_ref,
            throughput=round(self.throughput.mean or 0.0, 4),
            lead_time_p50_h=self.lead_p50_h.mean,
            lead_time_p90_h=self.lead_p90_h.mean,
            wip_by_stage={k: round(v, 3) for k, v in self.wip_by_node.items()},
            utilization_by_resource={k: round(v, 4) for k, v in self.utilization.items()},
            constraint_location=self.constraint_location,
            created=datetime.now(UTC),
        )


def simulate(
    graph: FlowGraph,
    scenario: Scenario | None = None,
    replications: int = 10,
    horizon_weeks: float = 26,
    warmup_weeks: float = 4,
    seed: int = 42,
) -> SimResult:
    scenario = scenario or Scenario("baseline")
    g = scenario.apply(graph)
    reps = [
        Simulator(g, seed=seed + i, rope=scenario.rope, batch_override=scenario.batch).run(
            horizon_weeks, warmup_weeks
        )
        for i in range(replications)
    ]

    def avg(dicts: list[dict[str, float]]) -> dict[str, float]:
        keys = {k for d in dicts for k in d}
        return {k: statistics.fmean(d.get(k, 0.0) for d in dicts) for k in sorted(keys)}

    util = avg([r.utilization for r in reps])
    locs = [r.constraint_location for r in reps if r.constraint_location]
    return SimResult(
        scenario=scenario,
        seed=seed,
        replications=replications,
        horizon_weeks=horizon_weeks,
        warmup_weeks=warmup_weeks,
        reps=reps,
        throughput=Band.of([r.throughput_per_week for r in reps]),
        lead_p50_h=Band.of([percentile(r.lead_times_h, 0.5) for r in reps]),
        lead_p90_h=Band.of([percentile(r.lead_times_h, 0.9) for r in reps]),
        internal_p50_h=Band.of([percentile(r.internal_lead_times_h, 0.5) for r in reps]),
        internal_p90_h=Band.of([percentile(r.internal_lead_times_h, 0.9) for r in reps]),
        wip_total=Band.of([sum(r.wip_by_node.values()) for r in reps]),
        wip_by_node=avg([r.wip_by_node for r in reps]),
        queue_by_node=avg([r.queue_by_node for r in reps]),
        utilization=util,
        constraint_location=max(set(locs), key=locs.count) if locs else None,
        gate_backlog_end=Band.of([float(r.gate_backlog_end) for r in reps]),
        gate_wait_p50_h=Band.of([percentile(r.gate_wait_h, 0.5) for r in reps]),
        reneged_per_week=Band.of([r.reneged / ((horizon_weeks - warmup_weeks) or 1) for r in reps]),
    )


def standard_scenarios(
    graph: FlowGraph,
    constraint_resource: str | None = None,
    gate_node: str | None = None,
    demand_factor: float = 1.3,
    elevate_factor: float = 1.25,
    batch_node: str | None = None,
    buffer_weeks: float = 1.0,
) -> list[Scenario]:
    """Baseline + the focusing-step scenarios that apply to this graph.

    The rope's WIP limit follows Drum-Buffer-Rope: constraint throughput x buffer time
    (Little's law), not current WIP, which grows without bound when the system is overloaded.
    """
    out = [Scenario("baseline")]
    if batch_node:
        out.append(Scenario(f"exploit: batch 1 at {batch_node}", batch={batch_node: 1}))
    if constraint_resource:
        out.append(
            Scenario(
                f"elevate: +{elevate_factor - 1:.0%} {constraint_resource}",
                capacity={constraint_resource: elevate_factor},
            )
        )
    out.append(Scenario(f"demand +{demand_factor - 1:.0%} (no rope)", arrival_scale=demand_factor))
    if gate_node:
        limit = rope_limit(graph, buffer_weeks, constraint_resource)
        out.append(
            Scenario(
                f"demand +{demand_factor - 1:.0%} with rope at {gate_node} (WIP≤{limit})",
                arrival_scale=demand_factor,
                rope=(gate_node, limit),
            )
        )
    return out


def rope_limit(graph: FlowGraph, buffer_weeks: float = 1.0, resource_id: str | None = None) -> int:
    """WIP limit = drum rate x time buffer (Little's law). With the constraint resource known,
    the drum rate is the items/week through its own steps (not finished units at the end of
    the flow, which can be fewer after drop-offs)."""
    rate = graph.drum_rate(resource_id) if resource_id else graph.effective_throughput()
    return max(1, round(rate * buffer_weeks))


def compare(graph: FlowGraph, scenarios: list[Scenario], **kw) -> list[SimResult]:
    return [simulate(graph, s, **kw) for s in scenarios]


def to_markdown(results: list[SimResult]) -> str:
    lines = [
        "| Scenario | Throughput/wk | Customer lead p50 (h) | In-shop lead p50 (h) | "
        "In-shop lead p90 (h) | WIP | Busiest | Release backlog |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        busiest = (
            f"{r.constraint_location} {r.utilization[r.constraint_location]:.0%}"
            if r.constraint_location
            else "–"
        )
        backlog = r.gate_backlog_end.fmt(digits=0) if r.scenario.rope else "–"
        lines.append(
            f"| {r.scenario.name} | {r.throughput.fmt()} | {r.lead_p50_h.fmt(digits=0)} "
            f"| {r.internal_p50_h.fmt(digits=0)} | {r.internal_p90_h.fmt(digits=0)} | "
            f"{r.wip_total.fmt(digits=0)} | {busiest} | {backlog} |"
        )
    lines.append("")
    lines.append(
        f"{results[0].replications} replications × {results[0].horizon_weeks:g} weeks "
        f"(warm-up {results[0].warmup_weeks:g}), seed {results[0].seed}; "
        "ranges are 5th–95th percentile across replications. Customer lead time "
        "includes waiting in the release backlog; in-shop lead time starts at release."
    )
    return "\n".join(lines)
