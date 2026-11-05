"""Render the constraint section of the Constraint Report (brief §15.2)."""

from __future__ import annotations

from ..i18n import domain_label
from ..i18n import t as tr
from .analyst import ConstraintReport


def to_markdown(r: ConstraintReport, lang: str | None = None) -> str:
    lang = lang or r.lang
    out: list[str] = []
    if r.binding is not None:
        b = r.binding
        out += [
            "## "
            + tr(
                "rep_binding",
                lang,
                t=tr("type_" + b.type.value, lang),
                d=domain_label(b.domain_id, lang),
            ),
            "",
            b.description,
            "",
            tr("rep_conf_tests", lang, c=f"{b.confidence:.2f}"),
        ]
        out += [
            f"- {x.kind.value}: {tr('rep_pass' if x.passed else 'rep_fail', lang)} — {x.note}"
            for x in b.tests_run
        ]
    else:
        out += [f"## {tr('rep_none', lang)}", "", tr("rep_g4", lang)]
    if r.next_constraint:
        out += ["", f"**{tr('rep_next', lang)}:** {r.next_constraint.description}"]
    others = [*r.confirmed[1:], *r.candidates]
    if others:
        out += ["", f"### {tr('rep_others', lang)}"]
        out += [
            f"- {c.id} ({tr('status_' + c.status.value, lang)}, "
            f"{tr('type_' + c.type.value, lang)}, {tr('conf', lang)} {c.confidence:.2f}): "
            f"{c.description}"
            for c in others
        ]
    if r.unresolved:
        out += ["", f"### {tr('rep_unresolved', lang)}"]
        out += [f"- {domain_label(u.domain.value, lang)}: {u.reason}" for u in r.unresolved]
    lo = r.policy_audit.local_optima()
    if lo:
        out += ["", f"### {tr('rep_local', lang)}"]
        out += [f"- {p.statement} → {p.recommendation}" for p in lo]
    if r.discovery_actions:
        out += ["", f"### {tr('rep_discovery', lang)}"]
        out += [f"- {a}" for a in r.discovery_actions]
    return "\n".join(out)
