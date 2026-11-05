"""Constraint-shift alerts (brief §8.8, POOGI). Evaluates weekly measurements against the
roadmap's re-baseline triggers and says when to go back to Step 1."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeekSnapshot:
    week: str  # e.g. "2026-W46"
    utilization: dict[str, float]  # resource -> load/capacity
    queues: dict[str, float] = field(default_factory=dict)  # node/resource -> items waiting
    demand: float | None = None  # arrivals per week (unit of throughput)
    throughput: float | None = None


@dataclass(frozen=True)
class Alert:
    kind: str  # constraint_relieved | queue_moved | demand_shift | next_constraint | starving
    severity: str  # info | warning | action
    message: str


def evaluate(
    weeks: list[WeekSnapshot],
    constraint_resource: str | None,
    baseline_demand: float | None = None,
    next_resource: str | None = None,
    low_util: float = 0.80,
    low_weeks: int = 4,
    demand_change: float = 0.20,
    high_util: float = 0.85,
) -> list[Alert]:
    if not weeks:
        return []
    out: list[Alert] = []
    latest = weeks[-1]
    if constraint_resource:
        recent = [w.utilization.get(constraint_resource) for w in weeks[-low_weeks:]]
        if len(recent) == low_weeks and all(u is not None and u < low_util for u in recent):
            out.append(
                Alert(
                    "constraint_relieved",
                    "action",
                    f"{constraint_resource} below {low_util:.0%} for {low_weeks} weeks: "
                    "the constraint has likely moved. Re-run Step 1 (incl. market).",
                )
            )
        if latest.queues:
            top, q = max(latest.queues.items(), key=lambda kv: kv[1])
            own = latest.queues.get(constraint_resource, 0.0)
            if top != constraint_resource and q > max(own, 0) * 1.5 and q > 0:
                out.append(
                    Alert(
                        "queue_moved",
                        "warning",
                        f"largest queue is now at {top} ({q:g}) vs {own:g} at "
                        f"{constraint_resource}: check for a new constraint",
                    )
                )
    if baseline_demand and latest.demand is not None:
        change = latest.demand / baseline_demand - 1
        if abs(change) > demand_change:
            out.append(
                Alert(
                    "demand_shift",
                    "warning",
                    f"demand {change:+.0%} vs baseline: re-simulate the roadmap",
                )
            )
    if next_resource:
        u = latest.utilization.get(next_resource)
        if u is not None and u > high_util:
            out.append(
                Alert(
                    "next_constraint",
                    "action",
                    f"{next_resource} at {u:.0%} (> {high_util:.0%}): predicted next "
                    "constraint is forming",
                )
            )
    if constraint_resource and latest.throughput is not None and len(weeks) >= 2:
        prev = weeks[-2].throughput
        u = latest.utilization.get(constraint_resource)
        if prev and latest.throughput < prev * 0.9 and u is not None and u < low_util:
            out.append(
                Alert(
                    "starving",
                    "warning",
                    f"throughput fell {latest.throughput / prev - 1:.0%} while "
                    f"{constraint_resource} has slack: is the constraint starved?",
                )
            )
    return out
