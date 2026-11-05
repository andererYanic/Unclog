"""Report Writer: renders the deliverables package (brief §15) in German or English.

Deterministic: figures come from the analysis objects, text from Jinja templates in
``templates/``. Every document is marked as a draft that needs human review before client
delivery (brief §16). Sections render only when their inputs exist, so a diagnosis-only package
is possible before any model call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..agents.opportunity_analyst import OpportunityAnalysis
from ..agents.opportunity_analyst import to_markdown as opp_md
from ..constraint.analyst import ConstraintReport
from ..constraint.report import to_markdown as constraint_md
from ..domains.heat import HeatTable
from ..domains.report import to_markdown as heat_md
from ..flow.graph import FlowGraph
from ..goalfactor import GoalTree
from ..paths import knowledge_dir
from ..schemas.design import Risk, ValueScenario
from ..schemas.diagnosis import ConstraintType, DomainVerdict, StageMetric
from ..scoring.feasibility import DISCLAIMER, Feasibility
from ..scoring.value import Economics, ValueReport
from ..scoring.value import to_markdown as value_md
from ..simulation import SimResult
from ..simulation import to_markdown as sim_md
from .roadmap import WAVES, Roadmap

L10N = {
    "en": {
        "draft": "DRAFT — requires human review before client delivery (brief §16).",
        "exec_title": "Executive summary",
        "as_of": "As of",
        "goal": "Goal",
        "goal_missing": "Goal not yet defined (G3).",
        "constraint": "The constraint",
        "confidence": "confidence",
        "no_constraint": "No constraint is confirmed yet. Until it is, we only measure: see "
        "the actions below (G4).",
        "heat_headline": "Where we looked",
        "top_moves": "Top moves",
        "value": "Value (T/I/OE)",
        "value_range": "Monthly profit effect, low–high",
        "value_note": "Simulated; effects are assumptions until a pilot measures them.",
        "value_missing": "Not yet modelled.",
        "risks": "Main risks",
        "decisions": "Decisions needed",
        "constraint_title": "Constraint report",
        "flow": "Load and capacity",
        "resource": "Resource",
        "load": "Load/week",
        "capacity": "Capacity/week",
        "util": "Utilization",
        "no_flow": "No flow model yet.",
        "heat_table": "Domain heat table (RACE + back-end)",
        "roadmap_title": "Roadmap",
        "buffer_zones": "green/yellow/red by thirds",
        "wave_measure": "Wave 0 — measure",
        "wave_exploit": "Wave 1 — exploit",
        "wave_subordinate": "Wave 2 — subordinate",
        "wave_elevate": "Wave 3 — elevate",
        "wave_backlog": "Backlog (not now)",
        "days": "days",
        "kpis": "KPIs",
        "baseline": "Baseline",
        "unit": "Unit",
        "leading": "Leading",
        "yes": "yes",
        "no": "no",
        "triggers": "Re-baseline triggers",
        "risk_title": "Risk & governance register",
        "plain": {
            ConstraintType.physical: "{who} cannot keep up: every hour there is an hour for "
            "the whole business.",
            ConstraintType.policy: "A rule holds the business back: {what}.",
            ConstraintType.market: "Demand is the limit: capacity is there, buyers are not "
            "({where}).",
            ConstraintType.paradigm: "A way of thinking holds the business back.",
        },
    },
    "de": {
        "draft": "ENTWURF — vor Weitergabe an den Kunden durch einen Menschen zu prüfen "
        "(Brief §16).",
        "exec_title": "Zusammenfassung",
        "as_of": "Stand",
        "goal": "Ziel",
        "goal_missing": "Ziel noch nicht festgelegt (G3).",
        "constraint": "Der Engpass",
        "confidence": "Konfidenz",
        "no_constraint": "Noch kein Engpass bestätigt. Bis dahin wird nur gemessen: siehe "
        "Maßnahmen unten (G4).",
        "heat_headline": "Wo wir hingeschaut haben",
        "top_moves": "Wichtigste Schritte",
        "value": "Wert (T/I/OE)",
        "value_range": "Monatlicher Gewinneffekt, niedrig–hoch",
        "value_note": "Simuliert; Effekte sind Annahmen, bis ein Pilot sie misst.",
        "value_missing": "Noch nicht modelliert.",
        "risks": "Wichtigste Risiken",
        "decisions": "Offene Entscheidungen",
        "constraint_title": "Engpass-Bericht",
        "flow": "Last und Kapazität",
        "resource": "Ressource",
        "load": "Last/Woche",
        "capacity": "Kapazität/Woche",
        "util": "Auslastung",
        "no_flow": "Noch kein Ablaufmodell.",
        "heat_table": "Bereichs-Übersicht (RACE + Back-End)",
        "roadmap_title": "Fahrplan",
        "buffer_zones": "grün/gelb/rot in Dritteln",
        "wave_measure": "Welle 0 — messen",
        "wave_exploit": "Welle 1 — ausschöpfen",
        "wave_subordinate": "Welle 2 — unterordnen",
        "wave_elevate": "Welle 3 — erweitern",
        "wave_backlog": "Zurückgestellt",
        "days": "Tage",
        "kpis": "Kennzahlen",
        "baseline": "Ausgangswert",
        "unit": "Einheit",
        "leading": "Frühindikator",
        "yes": "ja",
        "no": "nein",
        "triggers": "Auslöser für Neubewertung",
        "risk_title": "Risiko- und Governance-Register",
        "plain": {
            ConstraintType.physical: "{who} kommt nicht hinterher: jede Stunde dort ist eine "
            "Stunde für das ganze Unternehmen.",
            ConstraintType.policy: "Eine Regel bremst das Unternehmen: {what}.",
            ConstraintType.market: "Die Nachfrage ist die Grenze: Kapazität ist da, Käufer "
            "fehlen ({where}).",
            ConstraintType.paradigm: "Eine Denkweise bremst das Unternehmen.",
        },
    },
}


@dataclass
class Bundle:
    title: str
    lang: str
    heat: HeatTable
    report: ConstraintReport
    graph: FlowGraph | None = None
    metrics: list[StageMetric] = field(default_factory=list)
    tree: GoalTree | None = None
    opportunities: OpportunityAnalysis | None = None
    value: ValueReport | None = None
    economics: Economics | None = None
    feasibility: list[Feasibility] = field(default_factory=list)
    roadmap: Roadmap | None = None
    sims: list[SimResult] = field(default_factory=list)
    open_decisions: list[str] = field(default_factory=list)


def _env() -> Environment:
    root = knowledge_dir().parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(root)),
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def _plain(b: Bundle, L: dict) -> str:
    c = b.report.binding
    if c is None:
        return ""
    what = (
        c.description.split("Rule found:")[-1].strip()
        if c.type is ConstraintType.policy
        else c.description
    )
    return L["plain"][c.type].format(who=c.resource_id or c.domain_id, what=what, where=c.domain_id)


def _risks(b: Bundle) -> list[Risk]:
    out: list[Risk] = list(b.opportunities.risks) if b.opportunities else []
    for f in b.feasibility:
        out += f.risks()
    return sorted(out, key=lambda r: -(r.likelihood * r.impact))


def write(b: Bundle, out_dir: str | Path) -> list[Path]:
    L = L10N[b.lang]
    env = _env()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    def put(name: str, text: str) -> None:
        p = out / name
        p.write_text(text)
        paths.append(p)

    heat_top = [r for r in b.heat.ranked() if r.verdict is not DomainVerdict.not_assessed][:4]
    moves = [
        i for i in (b.roadmap.items if b.roadmap else []) if i.wave in ("exploit", "subordinate")
    ][:5]
    value_range = None
    if b.value is not None and b.economics is not None:
        lines = [ln for ln in b.value.model.lines]
        tot = {
            s: sum(ln.delta_profit for ln in lines if ln.scenario is s)
            for s in (ValueScenario.low, ValueScenario.high)
        }
        cur = b.economics.currency
        value_range = (
            f"{tot[ValueScenario.low]:,.0f} – {tot[ValueScenario.high]:,.0f} {cur} "
            f"(sum of lines; joint ΔT base "
            f"{b.value.portfolio[ValueScenario.base]:,.0f} {cur})"
        )
    risks = [f"{r.description} (L{r.likelihood}×I{r.impact})" for r in _risks(b)]
    decisions = list(b.open_decisions)
    if b.opportunities:
        decisions += b.opportunities.open_questions
    goal = b.tree.root.statement if b.tree else None
    put(
        "01-executive-summary.md",
        env.get_template("executive_summary.md.j2").render(
            L=L,
            title=b.title,
            today=date.today().isoformat(),
            goal=goal,
            binding=b.report.binding,
            binding_plain=_plain(b, L),
            heat_top=heat_top,
            direction_note=b.heat.direction.note,
            moves=moves,
            discovery=b.report.discovery_actions,
            value_range=value_range,
            risks=risks,
            decisions=list(dict.fromkeys(decisions)),
        ),
    )

    resources = (
        sorted(b.graph.resource_loads().values(), key=lambda r: -r.utilization)
        if b.graph is not None
        else []
    )
    put(
        "02-constraint-report.md",
        env.get_template("constraint_report.md.j2").render(
            L=L,
            title=b.title,
            resources=[r for r in resources if r.load_h > 0],
            heat_md=heat_md(b.heat),
            constraint_md=constraint_md(b.report),
        ),
    )

    if b.tree is not None:
        put(
            "03-goal-tree.md",
            f"> {L['draft']}\n\n"
            + b.tree.to_markdown(b.lang)
            + "\n\n```mermaid\n"
            + b.tree.to_mermaid()
            + "\n```\n",
        )
    if b.roadmap is not None:
        put(
            "04-roadmap-dbr.md",
            env.get_template("roadmap.md.j2").render(L=L, title=b.title, rm=b.roadmap, waves=WAVES),
        )
    pa = b.report.policy_audit
    if pa.policies:
        lines = [
            f"> {L['draft']}",
            "",
            f"# {'Regeln und Kennzahlen' if b.lang == 'de' else 'Policy & measurement audit'}",
            "",
        ]
        for p in pa.policies:
            flag = " ⚠" if p.local_optimum else ""
            lines.append(f"- **{p.kind.value}**{flag}: {p.statement}")
            if p.recommendation:
                lines.append(f"  - → {p.recommendation}")
        put("05-policy-audit.md", "\n".join(lines) + "\n")
    if b.opportunities is not None:
        put("06-opportunity-map.md", f"> {L['draft']}\n\n" + opp_md(b.opportunities, b.lang) + "\n")
    if b.value is not None and b.economics is not None:
        put("07-value.md", f"> {L['draft']}\n\n" + value_md(b.value, b.economics, b.lang) + "\n")
        paths.append(write_workbook(b, out / "07-value-workbook.xlsx"))
    all_risks = _risks(b)
    if all_risks:
        lines = [
            f"> {L['draft']}",
            "",
            f"# {L['risk_title']}",
            "",
            f"_{DISCLAIMER[b.lang]}_",
            "",
            "| ID | Risk | Category | L | I | Mitigation |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {r.id} | {r.description} | {r.category} | {r.likelihood} | {r.impact} | "
            f"{r.mitigation or '–'} |"
            for r in all_risks
        ]
        put("08-risk-register.md", "\n".join(lines) + "\n")
    if b.sims:
        put("09-simulation.md", f"> {L['draft']}\n\n" + sim_md(b.sims) + "\n")
    put("export.json", json.dumps(export(b), indent=2, ensure_ascii=False, default=str))
    return paths


def export(b: Bundle) -> dict:
    """Structured JSON export of everything in the bundle (brief §15.13)."""
    d: dict = {
        "title": b.title,
        "lang": b.lang,
        "domains": [r.to_domain().model_dump(mode="json") for r in b.heat.rows],
        "direction": {"verdict": b.heat.direction.verdict.value, "note": b.heat.direction.note},
        "binding_constraint": b.report.binding.model_dump(mode="json")
        if b.report.binding
        else None,
        "candidates": [c.model_dump(mode="json") for c in b.report.candidates],
        "discovery_actions": b.report.discovery_actions,
        "policies": [p.model_dump(mode="json") for p in b.report.policy_audit.policies],
    }
    if b.tree:
        d["goal_tree"] = [n.model_dump(mode="json") for n in b.tree.nodes]
    if b.opportunities:
        d["opportunities"] = [o.model_dump(mode="json") for o in b.opportunities.opportunities]
        d["risks"] = [r.model_dump(mode="json") for r in b.opportunities.risks]
    if b.value:
        d["value_model"] = b.value.model.model_dump(mode="json")
    if b.roadmap:
        d["roadmap"] = [vars(i) for i in b.roadmap.items]
    return d


def write_workbook(b: Bundle, path: Path) -> Path:
    """Value workbook (brief §15.13): lines, mirage ledger, assumptions."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "value lines"
    head = [
        "opportunity",
        "scenario",
        "delta_T",
        "delta_OE_realized",
        "delta_I_carrying",
        "run_cost",
        "amortized_build",
        "delta_profit",
    ]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for ln in b.value.model.lines:
        ws.append(
            [
                ln.opportunity_id,
                ln.scenario.value,
                ln.delta_t,
                ln.delta_oe_realized,
                ln.delta_i_carrying,
                ln.run_cost,
                ln.amortized_build,
                ln.delta_profit,
            ]
        )
    m = wb.create_sheet("mirage ledger")
    m.append(["opportunity", "capacity_released_h_per_week", "claimed_per_month", "reason"])
    for e in b.value.model.mirage_ledger:
        m.append([e.opportunity_id, e.capacity_released_h, e.claimed_amount, e.reason])
    a = wb.create_sheet("assumptions")
    a.append(["item", "value"])
    econ = b.economics
    for k, v in vars(econ).items():
        a.append([k, v])
    for note in b.value.model.dedup_notes:
        a.append(["dedup", note])
    for p in b.value.per_opportunity:
        for n in p.notes:
            a.append([p.opportunity_id, n])
    wb.save(path)
    return path
