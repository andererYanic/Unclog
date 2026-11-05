"""Quality gates G1–G17 (brief §16). Each gate returns pass / fail / not applicable.

Many rules are already enforced by the schemas at construction time (an invalid record cannot
exist). Gates add the cross-artifact checks and report coverage numbers, so every phase can be
blocked on failure and every report says which gates passed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..deploy import check_g13
from ..evals.agents import RUBRICS
from ..evals.harness import gate_g14
from ..orchestrator.state import State
from ..schemas.common import Grounded
from ..schemas.delivery import EvalCase, EvalSuite
from ..schemas.design import Position, Priority
from ..schemas.diagnosis import ConstraintStatus

NA, PASS, FAIL = "n/a", "pass", "fail"


@dataclass
class GateResult:
    gate: str
    status: str
    problems: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == FAIL


def _res(gate: str, problems: list[str], detail: str = "") -> GateResult:
    return GateResult(gate, FAIL if problems else PASS, problems, detail)


def _grounded(s: State) -> list[Grounded]:
    out: list[Grounded] = []
    if s.goal:
        out.append(s.goal)
    if s.graph:
        out += [*s.graph.nodes, *s.graph.resources]
    if s.report:
        out += [*s.report.confirmed, *s.report.candidates, *s.report.policy_audit.policies]
    if s.tree:
        out += s.tree.nodes
    if s.opportunities:
        out += [*s.opportunities.opportunities, *s.opportunities.risks]
    out += s.findings
    return out


def g1(s: State) -> GateResult:
    problems = []
    for obj in _grounded(s):
        try:
            type(obj).model_validate(obj.model_dump())
        except ValidationError as exc:
            problems.append(
                f"{type(obj).__name__} {getattr(obj, 'id', '')}: {str(exc).splitlines()[0]}"
            )
    return _res("G1", problems)


def g2(s: State) -> GateResult:
    objs = _grounded(s)
    if not objs:
        return GateResult("G2", NA)
    covered = sum(1 for o in objs if o.evidence or o.assumption)
    backed = sum(1 for o in objs if o.evidence)
    share = covered / len(objs)
    detail = f"{covered}/{len(objs)} grounded; {backed / len(objs):.0%} backed by evidence"
    return _res("G2", [] if share >= 0.9 else [f"only {share:.0%} grounded (< 90%)"], detail)


def g3(s: State) -> GateResult:
    if s.phase < 2:
        return GateResult("G3", NA)
    return _res(
        "G3", [] if s.goal else ["no goal / unit of throughput defined before flow modeling"]
    )


def g4(s: State) -> GateResult:
    if s.report is None:
        return GateResult("G4", NA)
    b = s.report.binding
    problems = []
    if b is None and (s.tree or s.opportunities):
        problems.append("design work exists without a confirmed constraint")
    if b is not None and b.status is not ConstraintStatus.confirmed:
        problems.append("binding constraint not confirmed")
    if s.opportunities and b is not None:
        problems += [
            f"{o.id}: linked to {o.constraint_id}, not the binding constraint"
            for o in s.opportunities.opportunities
            if o.constraint_id and o.constraint_id != b.id
        ]
    detail = "work mode: " + s.report.work_mode
    return _res("G4", problems, detail)


def g5(s: State) -> GateResult:
    if s.heat is None:
        return GateResult("G5", NA)
    return _res("G5", s.heat.coverage_issues())


def g6(s: State) -> GateResult:
    if not s.opportunities:
        return GateResult("G6", NA)
    p = []
    for o in s.opportunities.opportunities:
        if not o.human_in_loop_design:
            p.append(f"{o.id}: no human-in-loop design")
        if not o.risk_ids:
            p.append(f"{o.id}: no risk entry")
    return _res("G6", p)


def g7(s: State) -> GateResult:
    if s.value is None:
        return GateResult("G7", NA)
    p = []
    for pv in s.value.per_opportunity:
        for _lvl, (_dt, _di, doe) in pv.delta.items():
            if doe.realization_path is None and doe.realized_amount != 0:
                p.append(f"{pv.opportunity_id}: OE counted without realization path")
    claimed = {
        pv.opportunity_id
        for pv in s.value.per_opportunity
        for (_, _, doe) in pv.delta.values()
        if doe.is_mirage
    }
    ledger = {m.opportunity_id for m in s.value.model.mirage_ledger}
    p += [f"{o}: claimed savings missing from mirage ledger" for o in claimed - ledger]
    return _res("G7", p)


def g8(s: State) -> GateResult:
    if not s.opportunities:
        return GateResult("G8", NA)
    p = []
    for o in s.opportunities.opportunities:
        if o.position is Position.upstream and not o.release_gate_design:
            p.append(f"{o.id}: upstream without release gate design")
        if (
            o.wip_side_effects
            and "new constraint" in o.wip_side_effects
            and o.priority not in (Priority.defer, Priority.do_not_pursue)
        ):
            p.append(f"{o.id}: review would create a new constraint but is prioritized")
    return _res("G8", p)


def g9(s: State) -> GateResult:
    if s.value is None:
        return GateResult("G9", NA)
    p = [
        f"{pv.opportunity_id}/{lvl.value}: ΔT {dt.amount:g} not backed by simulation"
        for pv in s.value.per_opportunity
        for lvl, (dt, _, _) in pv.delta.items()
        if dt.amount != 0 and (dt.validated_by.value != "simulation" or not dt.sim_run_id)
    ]
    return _res("G9", p)


def g10(s: State) -> GateResult:
    if s.roadmap is None:
        return GateResult("G10", NA)
    p = list(s.roadmap.warnings)
    p += [
        f"elevate item without start condition: {i.title}"
        for i in s.roadmap.wave("elevate")
        if not i.start_condition
    ]
    if s.report:
        p += [
            f"KPI rewards local efficiency without replacement: {pol.statement[:60]}"
            for pol in s.report.policy_audit.local_optima()
            if not pol.recommendation
        ]
    return _res("G10", p)


def g11(s: State) -> GateResult:
    if not s.deployed:
        return GateResult("G11", NA)
    if s.roadmap is None:
        return _res("G11", ["build started without a roadmap / baseline"])
    open_measure = [i for i in s.roadmap.wave("measure") if "G11" in (i.reason or "")]
    return _res("G11", [f"baseline missing before build: {i.title}" for i in open_measure])


def g12(s: State) -> GateResult:
    if not s.opportunities:
        return GateResult("G12", NA)
    p = []
    for o in s.opportunities.opportunities:
        if o.priority in (Priority.exploit_now, Priority.subordinate, Priority.elevate):
            if not o.client_owner:
                p.append(f"{o.id}: prioritized without a named client owner")
            if not o.process_health_ok:
                p.append(f"{o.id}: prioritized on a broken process")
            if o.rd_label:
                p.append(f"{o.id}: R&D item sold as consulting outcome")
    return _res("G12", p)


def g13(s: State) -> GateResult:
    if not s.deployed:
        return GateResult("G13", NA)
    return _res("G13", [f"{d.id}: {x}" for d, spec, _ in s.deployed for x in check_g13(spec, d)])


def g14(s: State) -> GateResult:
    ai = [(d, spec) for d, spec, _ in s.deployed if spec.template.uses_ai]
    if not ai:
        return GateResult("G14", NA)
    p = []
    for d, spec in ai:
        rep = s.eval_reports.get(d.id)
        if rep is None:
            p.append(f"{d.id}: no eval report")
            continue
        suite = EvalSuite(
            id=f"suite-{d.id}",
            system_id=d.id,
            rubric=RUBRICS.get(spec.template.id, "system rubric"),
            pass_mean=7,
            pass_worst_case=5,
            cases=[EvalCase(id=c, input_ref=c) for c in rep.per_case],
        )
        p += [f"{d.id}: {x}" for x in gate_g14(rep, suite)]
    return _res("G14", p)


def g15(s: State) -> GateResult:
    if not s.deployed:
        return GateResult("G15", NA)
    return _res("G15", [f"{d.id}: {x}" for d, _, issues in s.deployed for x in issues])


GENERIC = re.compile(
    r"^\s*(use|apply|leverage|implement|introduce)\s+(ai|ki|automation)\b|"
    r"\b(improve|increase|optimi[sz]e)\s+(efficiency|processes|productivity)\b|"
    r"\b(ki|ai)\s+(einsetzen|nutzen)\b|\beffizienz\s+steigern\b|\bprozesse\s+optimieren\b",
    re.IGNORECASE,
)


def specificity(text: str) -> tuple[int, list[str]]:
    """0-3: names a number/volume, a concrete object/system, and is not a generic phrase."""
    missing = []
    score = 0
    if re.search(r"\d", text):
        score += 1
    else:
        missing.append("no number/volume")
    if len(re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", text)) >= 4:
        score += 1
    else:
        missing.append("too short to name inputs/outputs")
    if not GENERIC.search(text):
        score += 1
    else:
        missing.append("generic phrase")
    return score, missing


def g16(s: State) -> GateResult:
    texts: list[tuple[str, str]] = []
    if s.tree:
        texts.append(("goal", s.tree.root.statement))
        texts += [(a.id, a.statement) for a in s.tree.ranked_actions()[:5]]
    if s.opportunities:
        texts += [(o.id, o.title) for o in s.opportunities.opportunities]
    if not texts:
        return GateResult("G16", NA)
    p = []
    for ref, t in texts:
        sc, missing = specificity(t)
        if "generic phrase" in missing or sc < 2:
            p.append(f"{ref}: not specific ({', '.join(missing)}): {t[:70]}")
    return _res("G16", p, f"{len(texts)} statements checked")


def g17(s: State) -> GateResult:
    p = []
    known = {src.id for src in s.sources}
    if s.graph:
        known |= {e.source_id for n in s.graph.nodes for e in n.evidence}
    for m in s.metrics:
        if m.measured and known and m.source_id not in known:
            p.append(f"metric {m.id}: source {m.source_id} not in the engagement's sources")
    if s.value is not None and len(s.value.per_opportunity) > 1:
        from ..schemas.design import ValueScenario

        base = ValueScenario.base
        if (
            abs(s.value.portfolio[base] - s.value.portfolio_sum_of_parts[base]) > 0.01
            and not s.value.model.dedup_notes
        ):
            p.append("overlapping gains without de-duplication note")
    if not s.metrics and s.value is None:
        return GateResult("G17", NA)
    return _res("G17", p)


GATES: dict[str, Callable[[State], GateResult]] = {
    "G1": g1,
    "G2": g2,
    "G3": g3,
    "G4": g4,
    "G5": g5,
    "G6": g6,
    "G7": g7,
    "G8": g8,
    "G9": g9,
    "G10": g10,
    "G11": g11,
    "G12": g12,
    "G13": g13,
    "G14": g14,
    "G15": g15,
    "G16": g16,
    "G17": g17,
}

#: Gates whose failure blocks progression past diagnosis (others report but don't block yet)
DIAGNOSIS_BLOCKING = {"G1", "G3", "G4"}


def run_gates(s: State, only: set[str] | None = None) -> list[GateResult]:
    return [fn(s) for name, fn in GATES.items() if only is None or name in only]


def to_markdown(results: list[GateResult]) -> str:
    out = ["| Gate | Status | Detail / problems |", "|---|---|---|"]
    for r in results:
        detail = "; ".join([r.detail, *r.problems]).strip("; ")
        out.append(f"| {r.gate} | {r.status} | {detail or '–'} |")
    return "\n".join(out)
