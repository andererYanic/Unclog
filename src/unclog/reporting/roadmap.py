"""Roadmap Planner: Five-Focusing-Steps sequencing and Drum-Buffer-Rope design (brief §2.3, §8.7,
§8.8; gates G10, G11).

Deterministic. Waves:
  0 measure   — if the constraint's own numbers are not measured yet (G11: baseline before build)
  1 exploit   — non-AI fixes and policy changes first, then exploit-now opportunities;
                fix-process-first items before anything is automated on that process
  2 subordinate — rope / WIP limit, batch reduction, gated upstream systems
  3 elevate   — starts only after wave-1 results are in the results ledger (G10)
  backlog     — defer, strategic bets (R&D), do-not-pursue, with reasons
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.opportunity_analyst import OpportunityAnalysis
from ..constraint.analyst import ConstraintReport
from ..flow.graph import FlowGraph
from ..goalfactor import GoalTree
from ..schemas.design import ActionTag, Priority
from ..schemas.diagnosis import Buffer, Constraint, ConstraintType, FocusStep, StageMetric
from ..scoring.opportunity import rank_score
from ..simulation.scenarios import rope_limit

WAVES = ("measure", "exploit", "subordinate", "elevate", "backlog")


@dataclass(frozen=True)
class RoadmapItem:
    wave: str
    title: str
    kind: str  # instrumentation | non_ai | policy | opportunity | fix_process
    ref: str | None = None
    owner: str | None = None
    effort_days: float | None = None
    start_condition: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class DBRDesign:
    drum: str
    buffer: Buffer | None
    rope: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class KPI:
    name: str
    baseline: float | None
    unit: str
    leading: bool
    source: str


@dataclass
class Roadmap:
    constraint: Constraint
    items: list[RoadmapItem]
    dbr: DBRDesign
    kpis: list[KPI]
    rebaseline_triggers: list[str]
    warnings: list[str] = field(default_factory=list)

    def wave(self, name: str) -> list[RoadmapItem]:
        return [i for i in self.items if i.wave == name]


def _constraint_measured(c: Constraint, metrics: list[StageMetric]) -> bool:
    if any(e.type.value in ("log_data", "queue_observation", "measurement") for e in c.evidence):
        return True
    return any(m.measured and m.domain_id == c.domain_id for m in metrics)


def design_dbr(
    c: Constraint, graph: FlowGraph | None, buffer_weeks: float = 1.0, lang: str = "en"
) -> DBRDesign:
    de = lang == "de"
    if c.type is ConstraintType.physical and c.resource_id:
        limit = rope_limit(graph, buffer_weeks) if graph is not None else None
        buf = Buffer(id=f"buffer-{c.resource_id}", protects=c.id, size_h=168.0 * buffer_weeks)
        rope = (
            (
                f"Neue Arbeit nur freigeben, solange WIP ab Freigabe ≤ {limit} "
                f"(Drum-Durchsatz × {buffer_weeks:g} Woche)"
                if de
                else f"Release new work only while WIP from release ≤ {limit} "
                f"(drum throughput × {buffer_weeks:g} week)"
            )
            if limit
            else ("Freigabe im Takt des Engpasses" if de else "Release at the constraint's pace")
        )
        return DBRDesign(
            drum=f"{c.resource_id}",
            buffer=buf,
            rope=rope,
            notes=(
                (
                    "Puffer grün/gelb/rot nach Eindringen; Rot = beschleunigen und Ursache notieren"
                    if de
                    else "Buffer green/yellow/red by penetration; red = expedite and log cause"
                ),
            ),
        )
    if c.type is ConstraintType.policy:
        return DBRDesign(
            drum=("Entscheidungstakt der Regel" if de else "decision cadence of the rule"),
            buffer=None,
            rope=(
                "Warteschlange vor der Entscheidung sichtbar machen und begrenzen"
                if de
                else "make the queue in front of the decision visible and capped"
            ),
            notes=(
                (
                    "Erst Regel ändern; DBR für die Regel entfällt, wenn sie fällt"
                    if de
                    else "Change the rule first; DBR for the rule disappears if the rule goes"
                ),
            ),
        )
    return DBRDesign(
        drum=("Marktnachfrage" if de else "market demand"),
        buffer=None,
        rope=(
            "Verlässliche Lieferzusagen; Schutzkapazität erhalten"
            if de
            else "reliable delivery promises; keep protective capacity"
        ),
        notes=(
            (
                "Nicht Kapazität abbauen: sie ist der Schutz für Zusagen"
                if de
                else "Do not cut capacity: it protects delivery promises"
            ),
        ),
    )


def plan(
    report: ConstraintReport,
    tree: GoalTree | None = None,
    opportunities: OpportunityAnalysis | None = None,
    graph: FlowGraph | None = None,
    metrics: list[StageMetric] = (),
    lang: str = "en",
) -> Roadmap:
    c = report.binding
    if c is None:
        raise ValueError("no confirmed constraint: plan discovery actions only (G4)")
    de = lang == "de"
    items: list[RoadmapItem] = []
    warnings: list[str] = []

    if not _constraint_measured(c, list(metrics)):
        items.append(
            RoadmapItem(
                "measure",
                (
                    "Messung am Engpass einrichten: Durchsatz, Warteschlange, Wartezeit"
                    if de
                    else "Instrument the constraint: throughput, queue, wait time"
                ),
                "instrumentation",
                reason="G11 baseline before build",
            )
        )
    for a in report.discovery_actions[:6]:
        items.append(RoadmapItem("measure", a, "instrumentation", reason="coverage gap (G5)"))

    after_wave1 = (
        "startet, wenn Ergebnisse aus Welle 1 im Results Ledger stehen"
        if de
        else "starts when wave-1 results are in the results ledger"
    )
    if tree is not None:
        for a in tree.ranked_actions():
            if a.tag in (ActionTag.ai_doable, ActionTag.ai_assisted) and opportunities:
                continue  # covered by the opportunity
            wave = {
                FocusStep.exploit: "exploit",
                FocusStep.subordinate: "subordinate",
                FocusStep.elevate: "elevate",
            }.get(a.focus_step, "backlog")
            kind = (
                "policy"
                if any(p.id == "opt-policy" for p in tree.path(a.id))
                else ("non_ai" if a.tag in (ActionTag.non_ai, ActionTag.human) else "opportunity")
            )
            items.append(
                RoadmapItem(
                    wave,
                    a.statement,
                    kind,
                    a.id,
                    a.owner,
                    a.effort_days,
                    after_wave1 if wave == "elevate" else None,
                )
            )
    if opportunities is not None:
        for o in sorted(opportunities.opportunities, key=lambda o: -rank_score(o)):
            wave = {
                Priority.exploit_now: "exploit",
                Priority.policy_change: "exploit",
                Priority.fix_process_first: "exploit",
                Priority.subordinate: "subordinate",
                Priority.elevate: "elevate",
            }.get(o.priority, "backlog")
            kind = "fix_process" if o.priority is Priority.fix_process_first else "opportunity"
            title = (
                (f"Prozess reparieren vor: {o.title}" if de else f"Fix process before: {o.title}")
                if kind == "fix_process"
                else o.title
            )
            cond = (
                after_wave1
                if wave == "elevate"
                else (
                    ("nach Freigabe-Tor-Design" if de else "after release gate design")
                    if o.release_gate_required
                    else None
                )
            )
            reason = o.assumptions[0] if wave == "backlog" and o.assumptions else None
            items.append(RoadmapItem(wave, title, kind, o.id, o.client_owner, None, cond, reason))

    order = {w: i for i, w in enumerate(WAVES)}
    kind_order = {
        "instrumentation": 0,
        "fix_process": 1,
        "policy": 2,
        "non_ai": 3,
        "opportunity": 4,
    }
    items.sort(key=lambda i: (order[i.wave], kind_order.get(i.kind, 9)))
    if (tree is not None or opportunities is not None) and not any(
        i.wave == "exploit" for i in items
    ):
        warnings.append("no exploit actions: elevate would come before exploiting (G10)")

    dbr = design_dbr(c, graph, lang=lang)
    kpis = _kpis(c, graph, report, metrics, de)
    triggers = _triggers(c, report, de)
    return Roadmap(c, items, dbr, kpis, triggers, warnings)


def _kpis(c: Constraint, graph, report, metrics, de: bool) -> list[KPI]:
    out = []
    if graph is not None:
        out.append(
            KPI(
                "Durchsatz am Engpass" if de else "constraint throughput",
                round(graph.effective_throughput(), 2),
                "units/week",
                True,
                "flow model",
            )
        )
        if c.resource_id:
            u = graph.resource_loads()[c.resource_id].utilization
            out.append(
                KPI(
                    f"Auslastung {c.resource_id}" if de else f"{c.resource_id} load",
                    round(u, 2),
                    "ratio",
                    True,
                    "flow model",
                )
            )
    for m in metrics:
        if m.domain_id == c.domain_id and m.measured:
            out.append(KPI(m.name, m.value, m.unit, True, m.source_id or "data"))
    out.append(
        KPI(
            "Durchlaufzeit Auftrag bis Geld" if de else "lead time order to cash",
            None,
            "days",
            True,
            "to instrument",
        )
    )
    out.append(KPI("T/I/OE (Monat)" if de else "T/I/OE (month)", None, "EUR", False, "finance"))
    return out


def _triggers(c: Constraint, report: ConstraintReport, de: bool) -> list[str]:
    t = [
        (
            "Auslastung des Engpasses < 80 % für 4 Wochen → Schritt 1 neu"
            if de
            else "constraint utilization < 80% for 4 weeks → re-run step 1"
        ),
        (
            "Größte Warteschlange liegt woanders als am Engpass → neu diagnostizieren"
            if de
            else "the largest queue moves away from the constraint → re-diagnose"
        ),
        (
            "Nachfrage ändert sich um mehr als ±20 % → neu simulieren"
            if de
            else "demand changes by more than ±20% → re-simulate"
        ),
    ]
    nxt = report.next_constraint
    if nxt is not None and nxt.resource_id:
        t.append(
            f"{nxt.resource_id} über 85 % Auslastung → nächster Engpass"
            if de
            else f"{nxt.resource_id} above 85% utilization → next constraint"
        )
    t.append(
        "Nach jeder Regeländerung: alte Regeln auf Trägheit prüfen"
        if de
        else "after each policy change: audit inherited rules for inertia"
    )
    return t
