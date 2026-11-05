"""Render the domain heat table for the Constraint Report (brief §4.3, §15.2)."""

from __future__ import annotations

from ..i18n import domain_label, t
from .heat import HeatTable


def to_markdown(table: HeatTable, lang: str | None = None) -> str:
    lang = lang or table.lang
    lines = [t("heat_header", lang), "|---:|---|---:|---|---:|---:|---|---|"]
    for i, r in enumerate(table.ranked(), start=1):
        sig = ", ".join(sorted(k.value for k in r.signal_kinds)) or "–"
        util = f"{r.max_utilization:.0%}" if r.max_utilization is not None else "–"
        lines.append(
            f"| {i} | {domain_label(r.domain.value, lang)} | {r.prior:.2f} | {sig} | {util} | "
            f"{r.score:.2f} | "
            f"{t('verdict_' + r.verdict.value, lang)} | {r.rationale.replace('|', '/')} |"
        )
    d = table.direction
    lines += ["", f"**{t('demand_vs_capacity', lang)}:** {d.verdict.value}. {d.note}"]
    issues = table.coverage_issues()
    if issues:
        lines += ["", f"**{t('coverage_gaps', lang)}:**", *[f"- {x}" for x in issues]]
    return "\n".join(lines)
