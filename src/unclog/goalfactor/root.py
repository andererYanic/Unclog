"""Root goal and starter skeleton per constraint type (brief §7 steps 1-2).

The root is a measurable outcome computed from the constraint and the data (never by a model).
The skeleton gives the Goal Factoring agent the focusing-step branches to expand; the agent may
add branches, but the policy branch of a policy constraint must keep a live action.
"""

from __future__ import annotations

from ..flow.graph import FlowGraph
from ..schemas.design import ConstraintLink, GoalNode, GoalNodeKind
from ..schemas.diagnosis import Constraint, ConstraintType, FocusStep, Policy, StageMetric

POLICY_BRANCH_ID = "opt-policy"

_TXT = {
    "phys_root": {
        "en": "Raise throughput through {who} from {a:.1f} to {b:.1f} units/week",
        "de": "Durchsatz bei {who} von {a:.1f} auf {b:.1f} Einheiten/Woche steigern",
    },
    "phys_metric": {
        "en": "completions/week through {who}",
        "de": "Fertigstellungen/Woche bei {who}",
    },
    "pol_root": {
        "en": "Cut the wait at '{node}' from ~{a:.0f} h to <= {b:.0f} h",
        "de": "Wartezeit bei '{node}' von ~{a:.0f} h auf <= {b:.0f} h senken",
    },
    "pol_metric": {
        "en": "median wait before '{node}' (h)",
        "de": "Median-Wartezeit vor '{node}' (h)",
    },
    "mkt_root": {
        "en": "Move '{m}' from {a:g} to {b:g} {u}",
        "de": "'{m}' von {a:g} auf {b:g} {u} bringen",
    },
}

_SKELETON = {
    ConstraintType.physical: [
        (
            "opt-exploit-idle",
            FocusStep.exploit,
            ConstraintLink.acts_on,
            {
                "en": "Never let {who} wait for input or do non-constraint work",
                "de": "{who} nie auf Input warten oder Nebenarbeit machen lassen",
            },
        ),
        (
            "opt-exploit-quality",
            FocusStep.exploit,
            ConstraintLink.protects,
            {
                "en": "Catch errors and missing information before work reaches {who}",
                "de": "Fehler und fehlende Infos abfangen, bevor Arbeit bei {who} ankommt",
            },
        ),
        (
            "opt-subordinate",
            FocusStep.subordinate,
            ConstraintLink.gates_flow,
            {
                "en": "Release work at {who}'s pace (rope, WIP limit, smaller batches)",
                "de": "Arbeit im Takt von {who} freigeben (Seil, WIP-Limit, kleinere Lose)",
            },
        ),
        (
            "opt-elevate",
            FocusStep.elevate,
            ConstraintLink.acts_on,
            {
                "en": "Add capacity at {who} (people, tools, AI assistance)",
                "de": "Kapazität bei {who} erhöhen (Personal, Werkzeuge, KI-Unterstützung)",
            },
        ),
        (
            POLICY_BRANCH_ID,
            FocusStep.exploit,
            ConstraintLink.acts_on,
            {
                "en": "Change rules and KPIs that waste {who}'s time",
                "de": "Regeln und Kennzahlen ändern, die Zeit von {who} verschwenden",
            },
        ),
    ],
    ConstraintType.policy: [
        (
            POLICY_BRANCH_ID,
            FocusStep.exploit,
            ConstraintLink.acts_on,
            {
                "en": "Remove, narrow or re-time the rule",
                "de": "Regel abschaffen, eingrenzen oder anders takten",
            },
        ),
        (
            "opt-batch",
            FocusStep.exploit,
            ConstraintLink.acts_on,
            {
                "en": "Release items continuously or in much smaller batches",
                "de": "Vorgänge laufend oder in viel kleineren Mengen freigeben",
            },
        ),
        (
            "opt-prepare",
            FocusStep.exploit,
            ConstraintLink.protects,
            {
                "en": "Prepare each item so the decision takes minutes",
                "de": "Jeden Vorgang so vorbereiten, dass die Entscheidung Minuten dauert",
            },
        ),
        (
            "opt-delegate",
            FocusStep.elevate,
            ConstraintLink.acts_on,
            {
                "en": "Delegate the decision within clear thresholds",
                "de": "Entscheidung mit klaren Schwellen delegieren",
            },
        ),
    ],
    ConstraintType.market: [
        (
            "opt-convert",
            FocusStep.exploit,
            ConstraintLink.acts_on,
            {
                "en": "Convert more of the demand that already reaches {stage}",
                "de": "Mehr aus der Nachfrage machen, die {stage} schon erreicht",
            },
        ),
        (
            "opt-reliability",
            FocusStep.subordinate,
            ConstraintLink.protects,
            {
                "en": "Keep delivery promises fast and reliable so they help sell",
                "de": "Lieferzusagen schnell und verlässlich halten, damit sie verkaufen helfen",
            },
        ),
        (
            "opt-demand",
            FocusStep.elevate,
            ConstraintLink.acts_on,
            {
                "en": "Increase qualified demand at {stage}",
                "de": "Qualifizierte Nachfrage bei {stage} erhöhen",
            },
        ),
        (
            POLICY_BRANCH_ID,
            FocusStep.exploit,
            ConstraintLink.acts_on,
            {
                "en": "Change offers, pricing rules or policies that block buying",
                "de": "Angebote, Preisregeln oder Vorgaben ändern, die den Kauf bremsen",
            },
        ),
    ],
}


def _target_label(c: Constraint) -> str:
    return c.resource_id or c.market_segment or c.domain_id


def root_goal(
    constraint: Constraint,
    graph: FlowGraph | None = None,
    metrics: list[StageMetric] = (),
    policies: list[Policy] = (),
    lang: str = "en",
    target_gain: float = 0.25,
    target_wait_h: float = 24.0,
) -> GoalNode:
    grounding = (
        {"evidence": constraint.evidence}
        if constraint.evidence
        else {"assumption": True, "confidence": constraint.confidence or 0.5}
    )
    t = constraint.type
    who = _target_label(constraint)
    if constraint.resource_id and graph is not None:  # people read names, not ids
        who = next((r.name for r in graph.resources if r.id == constraint.resource_id), who)
    if t is ConstraintType.physical and graph is not None:
        a = graph.effective_throughput()
        b = (
            min(graph.throughput(), a * (1 + target_gain))
            if graph.throughput() > a
            else a * (1 + target_gain)
        )
        stmt = _TXT["phys_root"][lang].format(who=who, a=a, b=b)
        metric = _TXT["phys_metric"][lang].format(who=who)
    elif t is ConstraintType.policy:
        pol = next((p for p in policies if p.id == constraint.policy_id), None)
        node_id = pol.affects_node_ids[0] if pol and pol.affects_node_ids else None
        node = graph.node(node_id) if graph is not None and node_id else None
        wait = (graph.node_loads()[node_id].observed_wait_h if node is not None else None) or 0
        name = node.name if node is not None else constraint.domain_id
        # A stage benchmark in hours (e.g. speed-to-lead 1 h) beats the generic default.
        bench = [
            m.benchmark
            for m in metrics
            if m.domain_id == constraint.domain_id
            and m.unit.strip().lower() in ("h", "hour", "hours", "std")
            and m.higher_is_better is False
            and m.benchmark is not None
        ]
        target = min([target_wait_h, *bench])
        if wait and target >= wait:
            target = wait / 2
        stmt = _TXT["pol_root"][lang].format(node=name, a=wait, b=target)
        metric = _TXT["pol_metric"][lang].format(node=name)
    elif t is ConstraintType.market:
        cands = [
            m
            for m in metrics
            if m.domain_id == constraint.domain_id
            and m.benchmark is not None
            and m.higher_is_better is not None
        ]
        m = max(
            cands, key=lambda m: abs(m.benchmark - m.value) / abs(m.benchmark or 1), default=None
        )
        if m is not None:
            stmt = _TXT["mkt_root"][lang].format(m=m.name, a=m.value, b=m.benchmark, u=m.unit)
            metric = m.name
        else:
            stmt, metric = f"Raise conversion at {constraint.domain_id}", "stage conversion"
    else:
        stmt, metric = f"Relieve: {constraint.description}", "constraint throughput"
    return GoalNode(
        id="root",
        kind=GoalNodeKind.root,
        statement=stmt,
        metric=metric,
        rationale=constraint.description,
        **grounding,
    )


def skeleton(constraint: Constraint, lang: str = "en") -> list[GoalNode]:
    who = _target_label(constraint)
    out = []
    for oid, step, link, txt in _SKELETON.get(constraint.type, []):
        out.append(
            GoalNode(
                id=oid,
                parent_id="root",
                kind=GoalNodeKind.option,
                statement=txt[lang].format(who=who, stage=constraint.domain_id),
                focus_step=step,
                constraint_link=link,
                assumption=True,
                confidence=0.6,
                rationale="Unclog focusing-step skeleton",
            )
        )
    return out
