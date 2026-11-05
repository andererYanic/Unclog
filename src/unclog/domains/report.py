"""Render the domain heat table for the Constraint Report (brief §4.3, §15.2)."""

from __future__ import annotations

from ..schemas.diagnosis import DomainVerdict
from .heat import HeatTable

_ICON = {
    DomainVerdict.candidate: "candidate",
    DomainVerdict.clear: "clear",
    DomainVerdict.not_assessed: "not assessed",
    DomainVerdict.constraint: "CONSTRAINT",
}


def to_markdown(table: HeatTable) -> str:
    lines = [
        "| Rank | Domain | Prior | Signals | Max util. | Score | Verdict | Key evidence |",
        "|---:|---|---:|---|---:|---:|---|---|",
    ]
    for i, r in enumerate(table.ranked(), start=1):
        sig = ", ".join(sorted(k.value for k in r.signal_kinds)) or "–"
        util = f"{r.max_utilization:.0%}" if r.max_utilization is not None else "–"
        lines.append(
            f"| {i} | {r.domain.value} | {r.prior:.2f} | {sig} | {util} | {r.score:.2f} | "
            f"{_ICON[r.verdict]} | {r.rationale.replace('|', '/')} |"
        )
    d = table.direction
    lines += ["", f"**Demand vs capacity:** {d.verdict.value}. {d.note}"]
    issues = table.coverage_issues()
    if issues:
        lines += ["", "**Coverage gaps (G5):**", *[f"- {x}" for x in issues]]
    return "\n".join(lines)
