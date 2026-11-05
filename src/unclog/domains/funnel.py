"""Funnel conversion math for the RACE walk (deterministic; brief §4.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepConversion:
    from_stage: str
    to_stage: str
    rate: float | None
    benchmark: float | None
    relative_gap: float | None  # (benchmark - rate) / benchmark; positive = worse


def conversions(
    counts: list[tuple[str, float]], benchmarks: dict[str, float] | None = None
) -> list[StepConversion]:
    """Stage-to-stage conversion rates from ordered funnel counts.

    ``benchmarks`` is keyed by the *to* stage, e.g. {"booked": 0.25} for leads -> booked.
    """
    benchmarks = benchmarks or {}
    out = []
    for (a, ca), (b, cb) in zip(counts, counts[1:], strict=False):
        rate = cb / ca if ca > 0 else None
        bm = benchmarks.get(b)
        gap = (bm - rate) / bm if (bm and rate is not None) else None
        out.append(StepConversion(a, b, rate, bm, gap))
    return out


def worst_step(steps: list[StepConversion]) -> StepConversion | None:
    """Worst *relative* conversion is the usual RACE candidate (brief §4.1)."""
    scored = [s for s in steps if s.relative_gap is not None]
    return max(scored, key=lambda s: s.relative_gap) if scored else None
