"""Render the constraint section of the Constraint Report (brief §15.2)."""

from __future__ import annotations

from .analyst import ConstraintReport


def to_markdown(r: ConstraintReport) -> str:
    out: list[str] = []
    if r.binding is not None:
        b = r.binding
        out += [
            f"## Binding constraint ({b.type.value}, {b.domain_id}) — confirmed",
            "",
            b.description,
            "",
            f"Confidence {b.confidence:.2f}. Tests:",
        ]
        out += [
            f"- {t.kind.value}: {'pass' if t.passed else 'fail'} — {t.note}" for t in b.tests_run
        ]
    else:
        out += [
            "## No confirmed constraint yet",
            "",
            "Work is limited to discovery actions until a constraint is confirmed (G4).",
        ]
    if r.next_constraint:
        out += ["", f"**Predicted next constraint:** {r.next_constraint.description}"]
    others = [*r.confirmed[1:], *r.candidates]
    if others:
        out += ["", "### Other candidates"]
        out += [
            f"- {c.id} ({c.status.value}, {c.type.value}, conf {c.confidence:.2f}): {c.description}"
            for c in others
        ]
    if r.unresolved:
        out += ["", "### Unresolved signals"]
        out += [f"- {u.domain.value}: {u.reason}" for u in r.unresolved]
    lo = r.policy_audit.local_optima()
    if lo:
        out += ["", "### Policies / KPIs rewarding local efficiency"]
        out += [f"- {p.statement} → {p.recommendation}" for p in lo]
    if r.discovery_actions:
        out += ["", "### Discovery actions"]
        out += [f"- {a}" for a in r.discovery_actions]
    return "\n".join(out)
