"""Critic / QA agent, deterministic part (brief §12): Local-Optima Critic, Mirage Check,
Domain-Coverage Check, Ownership / Proven-First Check. Produces Finding records; ``blocking``
findings stop the pipeline. Two blocks in a row on the same phase escalate to a human (§16).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..schemas.common import Evidence, EvidenceType
from ..schemas.design import Finding, FindingSeverity, Priority

if TYPE_CHECKING:  # avoid qa <-> orchestrator import cycle
    from ..orchestrator.state import State


def _f(i: int, phase: int, text: str, sev: FindingSeverity, gate: str | None = None) -> Finding:
    return Finding(
        id=f"critic-{phase}-{i}",
        phase=phase,
        statement=text,
        severity=sev,
        gate=gate,
        assumption=False,
        evidence=[
            Evidence(
                id=f"ev-critic-{phase}-{i}",
                source_id="derived-critic",
                type=EvidenceType.document,
                note="critic rule",
            )
        ],
    )


def critique(s: State) -> list[Finding]:
    out: list[Finding] = []
    n = 0

    def add(text: str, sev: FindingSeverity, gate: str | None = None) -> None:
        nonlocal n
        n += 1
        out.append(_f(n, s.phase, text, sev, gate))

    if s.report is not None:
        for p in s.report.policy_audit.local_optima():
            add(
                f"Local optimum: '{p.statement[:80]}' rewards local efficiency; replace with "
                "constraint throughput / lead time",
                FindingSeverity.warning,
                "G10",
            )
    if s.heat is not None:
        for issue in s.heat.coverage_issues():
            add(f"Domain coverage: {issue}", FindingSeverity.warning, "G5")
    if s.value is not None:
        for m in s.value.model.mirage_ledger:
            add(
                f"Mirage: {m.opportunity_id} claims {m.capacity_released_h:g} h/week without a "
                "realization path; valued at 0",
                FindingSeverity.info,
                "G7",
            )
    if s.opportunities is not None:
        for o in s.opportunities.opportunities:
            if o.priority in (Priority.exploit_now, Priority.subordinate, Priority.elevate):
                if not o.client_owner:
                    add(
                        f"Ownership: {o.id} is prioritized but nobody owns it",
                        FindingSeverity.blocking,
                        "G12",
                    )
                if o.rd_label:
                    add(
                        f"Proven-first: {o.id} is R&D but prioritized as an outcome",
                        FindingSeverity.blocking,
                        "G12",
                    )
            if o.rd_label and o.priority is Priority.strategic_bet:
                add(f"R&D: {o.id} must be scoped and sold separately", FindingSeverity.info, "G12")
        if s.report and s.report.binding and not s.opportunities.opportunities:
            add(
                "No AI opportunity at the constraint: plan is non-AI fixes only (valid)",
                FindingSeverity.info,
            )
    return out
