"""Policy & measurement audit (brief §8.3; "policies can be the bottleneck", §2.2).

Two deterministic detectors:
- **structural**: flow nodes that release work in batches (batch_size > 1) and show long waits
- **textual**: batching / approval / KPI statements in ingested documents and interview quotes

KPIs that reward local efficiency (utilization, units per hour, per-department cost) are flagged
``local_optimum`` with a throughput-world replacement. Findings stay hypotheses: the auditor
agent and the client confirm them (brief §11 "Why weekly batches? Why this sign-off?").
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..flow.graph import FlowGraph
from ..i18n import t as tr
from ..schemas.common import Evidence, EvidenceType
from ..schemas.diagnosis import DomainName, Policy, PolicyKind
from .text import TextHit, domains_mentioned, scan

WAIT_THRESHOLD_H = 24.0

REPLACEMENT_KPIS = (
    "constraint throughput (units/week through the binding constraint)",
    "lead time (order to cash, median and p90)",
    "due-date performance",
    "WIP in front of the constraint",
    "T/I/OE at system level",
)


@dataclass(frozen=True)
class TextItem:
    source_id: str
    locator: str
    text: str
    testimony: bool  # interview/transcript/quote vs document


@dataclass
class PolicyAudit:
    policies: list[Policy] = field(default_factory=list)
    hits: list[TextHit] = field(default_factory=list)

    def by_domain(self, domain: DomainName | str) -> list[Policy]:
        d = DomainName(domain).value
        return [p for p in self.policies if p.domain_id == d]

    def local_optima(self) -> list[Policy]:
        return [p for p in self.policies if p.local_optimum]

    def flow_capping(self) -> list[Policy]:
        """Policies that can cap flow: batch rules and approvals (constraint candidates)."""
        return [p for p in self.policies if p.kind in (PolicyKind.batch_rule, PolicyKind.approval)]


def _pid(*parts: str) -> str:
    return "pol-" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def _evidence(item_source: str, locator: str, quote: str, testimony: bool, n: int) -> Evidence:
    return Evidence(
        id=f"ev-{_pid(item_source, locator, quote)[4:]}-{n}",
        source_id=item_source,
        type=EvidenceType.interview_claim if testimony else EvidenceType.document,
        locator=locator,
        quote=quote,
    )


def structural_batch_policies(graph: FlowGraph, lang: str = "en") -> list[Policy]:
    out = []
    loads = graph.node_loads()
    for node in graph.nodes:
        batch = node.batch_size or 1
        wait = loads[node.id].observed_wait_h
        if batch > 1 and wait is not None and wait >= WAIT_THRESHOLD_H:
            grounding = (
                {"evidence": list(node.evidence)}
                if node.evidence
                else {"assumption": True, "confidence": 0.4}
            )
            out.append(
                Policy(
                    id=_pid("batch", node.id),
                    kind=PolicyKind.batch_rule,
                    statement=tr(
                        "pol_batch", lang, node=node.name, b=f"{batch:g}", w=f"{wait:.0f}"
                    ),
                    rewards_behavior=tr("pol_batch_rewards", lang),
                    raises_system_t=False,
                    local_optimum=True,
                    recommendation=tr("pol_batch_rec", lang),
                    domain_id=node.domain_id,
                    affects_node_ids=[node.id],
                    **grounding,
                )
            )
    return out


def text_policies(items: list[TextItem], lang: str = "en") -> tuple[list[Policy], list[TextHit]]:
    policies: dict[str, Policy] = {}
    all_hits: list[TextHit] = []
    for item in items:
        hits = scan(item.source_id, item.locator, item.text)
        all_hits += hits
        for h in hits:
            if h.kind not in ("batching", "approval", "kpi", "local_efficiency"):
                continue
            kind = {
                "batching": PolicyKind.batch_rule,
                "approval": PolicyKind.approval,
                "kpi": PolicyKind.kpi,
                "local_efficiency": PolicyKind.kpi,
            }[h.kind]
            domain = h.domains[0].value if h.domains else None
            pid = _pid(kind.value, h.quote.lower())
            ev = _evidence(item.source_id, item.locator, h.quote, item.testimony, len(policies))
            if pid in policies:
                p = policies[pid]
                policies[pid] = p.model_copy(update={"evidence": [*p.evidence, ev]})
                continue
            local = h.kind == "local_efficiency" or (
                kind is PolicyKind.kpi
                and any(x.kind == "local_efficiency" and x.quote == h.quote for x in hits)
            )
            policies[pid] = Policy(
                id=pid,
                kind=kind,
                statement=h.quote,
                rewards_behavior=tr("pol_local_rewards", lang) if local else None,
                raises_system_t=False if local else None,
                local_optimum=local,
                recommendation=(
                    tr("pol_replace", lang, x=tr("kpi_replacements", lang))
                    if local
                    else tr("pol_challenge", lang)
                ),
                domain_id=domain,
                evidence=[ev],
            )
    return list(policies.values()), all_hits


def audit(graph: FlowGraph | None, items: list[TextItem], lang: str = "en") -> PolicyAudit:
    structural = structural_batch_policies(graph, lang) if graph is not None else []
    textual, hits = text_policies(items, lang)
    # Attach text evidence to a structural batch policy in the same domain (corroboration).
    merged: list[Policy] = []
    used: set[str] = set()
    for sp in structural:
        corroborating = [
            tp
            for tp in textual
            if tp.kind in (PolicyKind.batch_rule, PolicyKind.approval)
            and sp.domain_id in {d.value for d in domains_mentioned(tp.statement)}
        ]
        if corroborating:
            used |= {tp.id for tp in corroborating}
            extra = [e for tp in corroborating for e in tp.evidence]
            quotes = " ".join(f'"{tp.statement}"' for tp in corroborating[:2])
            sp = sp.model_copy(
                update={
                    "evidence": [*sp.evidence, *extra],
                    "assumption": False if extra else sp.assumption,
                    "statement": f"{sp.statement}. {tr('pol_rule_found', lang)} {quotes}",
                }
            )
        merged.append(sp)
    merged += [tp for tp in textual if tp.id not in used]
    return PolicyAudit(policies=merged, hits=hits)
