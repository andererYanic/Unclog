"""Domain heat table: RACE + back-end, evidence-ranked (brief §4, §8.2, gate G5).

Signals per domain (each independent):
- **capacity**: a resource serving the domain's flow nodes is highly utilized
- **queue**: work waits in front of the domain's nodes (queue length or long observed waits)
- **conversion**: a stage metric is materially worse than its benchmark

Event logs add *measured* queue evidence (long median waits before an activity) and backlog
growth (open cases well above what Little's law predicts at the observed completion rate).

A domain may only be marked ``clear`` on a sourced metric (measured, or an estimate traced to a
documented source such as an interview) or sourced flow data. Unsourced guesses leave it
``not_assessed`` (brief §4.3: dismissal needs evidence).

Ranking = evidence first (measured signals weigh 1.0, estimates 0.5, plus severity), prior
second. Verdicts are only ``candidate | clear | not_assessed``: promoting a candidate to
``constraint`` requires confirmation tests and belongs to the Constraint Analyst (step 5, G4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from ..flow.eventlog_stats import EventLogStats
from ..flow.graph import FlowGraph, NodeLoad, ResourceLoad
from ..i18n import domain_label, t
from ..schemas.diagnosis import REQUIRED_DOMAINS, Domain, DomainName, DomainVerdict, StageMetric
from .priors import ORDER, default_prior


@dataclass(frozen=True)
class HeatConfig:
    util_candidate: float = 0.85
    util_overload: float = 1.0
    gap_candidate: float = 0.25
    wait_candidate_h: float = 24.0
    measured_weight: float = 1.0
    estimate_weight: float = 0.5
    prior_weight: float = 1.0
    ample_capacity: float = 0.8


DEFAULT_CONFIG = HeatConfig()


class SignalKind(StrEnum):
    capacity = "capacity"
    queue = "queue"
    conversion = "conversion"


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    measured: bool
    severity: float  # 0..1
    detail: str
    refs: tuple[str, ...] = ()  # node/resource/metric ids


@dataclass
class HeatRow:
    domain: DomainName
    prior: float
    metrics: list[StageMetric] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    max_utilization: float | None = None
    has_flow_data: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    score: float = 0.0
    verdict: DomainVerdict = DomainVerdict.not_assessed
    rationale: str = ""

    @property
    def signal_kinds(self) -> set[SignalKind]:
        return {s.kind for s in self.signals}

    def to_domain(self) -> Domain:
        return Domain(
            id=f"domain-{self.domain.value}",
            name=self.domain,
            prior=self.prior,
            metrics=self.metrics,
            verdict=self.verdict,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
        )


class DirectionVerdict(StrEnum):
    capacity_limited = "capacity_limited"  # back-end can't keep up: more demand makes it worse
    market_limited = "market_limited"  # capacity ample: demand (RACE) is the limit
    inconclusive = "inconclusive"
    no_flow_data = "no_flow_data"


@dataclass(frozen=True)
class DirectionCheck:
    """Both-direction check (brief §4.3): demand vs capacity."""

    verdict: DirectionVerdict
    bottleneck_resource: str | None
    bottleneck_domain: str | None
    max_utilization: float | None
    demand_headroom: float | None  # e.g. 0.25 = +25% demand before the first resource saturates
    note: str


@dataclass
class HeatTable:
    rows: list[HeatRow]
    direction: DirectionCheck
    config: HeatConfig
    lang: str = "en"

    def ranked(self) -> list[HeatRow]:
        return sorted(self.rows, key=lambda r: (-r.score, ORDER.index(r.domain)))

    def candidates(self) -> list[HeatRow]:
        return [r for r in self.ranked() if r.verdict is DomainVerdict.candidate]

    def row(self, name: DomainName | str) -> HeatRow:
        name = DomainName(name)
        return next(r for r in self.rows if r.domain is name)

    def coverage_issues(self) -> list[str]:
        """G5: every required domain assessed; dismissal backed by evidence; direction done."""
        issues = []
        for r in self.rows:
            if r.domain in REQUIRED_DOMAINS and r.verdict is DomainVerdict.not_assessed:
                issues.append(
                    t(
                        "cov_not_assessed",
                        self.lang,
                        d=domain_label(r.domain.value, self.lang),
                        why=r.rationale.lower(),
                    )
                )
            if r.verdict is DomainVerdict.clear and not (r.metrics or r.evidence_ids):
                issues.append(
                    t("cov_clear_noev", self.lang, d=domain_label(r.domain.value, self.lang))
                )
        if self.direction.verdict in (DirectionVerdict.no_flow_data,):
            issues.append(t("cov_no_flow", self.lang))
        return issues


def _metric_gap(m: StageMetric) -> float | None:
    if m.benchmark is None or m.higher_is_better is None or m.benchmark == 0:
        return None
    if m.higher_is_better:
        return (m.benchmark - m.value) / abs(m.benchmark)
    return (m.value - m.benchmark) / abs(m.benchmark)


def _severity_util(u: float, cfg: HeatConfig) -> float:
    if math.isinf(u):
        return 1.0
    return max(0.0, min(1.0, (u - cfg.util_candidate) / 0.3))


def direction_check(
    graph: FlowGraph | None, cfg: HeatConfig = DEFAULT_CONFIG, lang: str = "en"
) -> DirectionCheck:
    if graph is None:
        return DirectionCheck(
            DirectionVerdict.no_flow_data,
            None,
            None,
            None,
            None,
            t("dir_no_graph", lang),
        )
    b = graph.bottleneck()
    if b is None:
        return DirectionCheck(
            DirectionVerdict.no_flow_data,
            None,
            None,
            None,
            None,
            t("dir_no_load", lang),
        )
    dom_of = {n.id: n.domain_id for n in graph.nodes}
    b_domains = sorted({dom_of[n] for n in b.node_ids})
    b_dom = ", ".join(b_domains)
    headroom = graph.demand_headroom()
    u = b.utilization
    backend = any(not DomainName(d).is_race for d in b_domains)
    if u >= cfg.util_overload:
        where = t("where_backend", lang) if backend else t("where_front", lang)
        flood = t("flood", lang) if backend else ""
        return DirectionCheck(
            DirectionVerdict.capacity_limited,
            b.resource_id,
            b_dom,
            u,
            headroom,
            t("dir_cap", lang, r=b.resource_id, where=where, dom=b_dom, u=f"{u:.0%}") + flood,
        )
    if u < cfg.ample_capacity:
        return DirectionCheck(
            DirectionVerdict.market_limited,
            b.resource_id,
            b_dom,
            u,
            headroom,
            t("dir_market", lang, r=b.resource_id, u=f"{u:.0%}", h=f"{headroom:.0%}"),
        )
    return DirectionCheck(
        DirectionVerdict.inconclusive,
        b.resource_id,
        b_dom,
        u,
        headroom,
        t("dir_inconclusive", lang, r=b.resource_id, u=f"{u:.0%}"),
    )


def build_heat_table(
    metrics: list[StageMetric],
    graph: FlowGraph | None = None,
    priors: dict[DomainName, float] | None = None,
    cfg: HeatConfig = DEFAULT_CONFIG,
    event_logs: list[tuple[DomainName | str, EventLogStats, str]] = (),
    lang: str = "en",
) -> HeatTable:
    """``event_logs``: (domain, stats, source_id) triples from ``flow.compute``."""
    priors = priors or {}
    rows = {d: HeatRow(domain=d, prior=priors.get(d, default_prior(d))) for d in ORDER}

    for m in metrics:
        try:
            d = DomainName(m.domain_id)
        except ValueError as exc:
            raise ValueError(
                f"metric {m.id}: domain_id {m.domain_id!r} is not a DomainName"
            ) from exc
        row = rows[d]
        row.metrics.append(m)
        if m.source_id:
            row.evidence_ids.append(m.source_id)
        gap = _metric_gap(m)
        if gap is not None and gap >= cfg.gap_candidate:
            how = (
                t("gap_x", lang, x=f"{m.value / m.benchmark:.0f}")
                if gap >= 1 and not m.higher_is_better
                else t("gap_pct", lang, p=f"{gap:.0%}")
            )
            est = "" if m.measured else t("estimate", lang)
            row.signals.append(
                Signal(
                    SignalKind.conversion,
                    m.measured,
                    min(1.0, gap),
                    t(
                        "sig_conv",
                        lang,
                        name=m.name,
                        v=f"{m.value:g}",
                        unit=m.unit,
                        b=f"{m.benchmark:g}",
                        how=how,
                        est=est,
                    ),
                    (m.id,),
                )
            )

    if graph is not None:
        rl: dict[str, ResourceLoad] = graph.resource_loads()
        nl: dict[str, NodeLoad] = graph.node_loads()
        for node in graph.nodes:
            row = rows[DomainName(node.domain_id)]
            row.has_flow_data = True
            row.evidence_ids += [e.source_id for e in node.evidence]
            load = nl[node.id]
            node_measured = bool(node.evidence) and not node.assumption
            for rid in node.resource_ids:
                r = rl[rid]
                u = r.utilization
                row.max_utilization = (
                    u if row.max_utilization is None else max(row.max_utilization, u)
                )
                if u >= cfg.util_candidate and not any(
                    s.kind is SignalKind.capacity and rid in s.refs for s in row.signals
                ):
                    res = next(x for x in graph.resources if x.id == rid)
                    row.signals.append(
                        Signal(
                            SignalKind.capacity,
                            bool(res.evidence) and not res.assumption,
                            _severity_util(u, cfg),
                            t(
                                "sig_cap",
                                lang,
                                r=rid,
                                u=f"{u:.0%}",
                                load=f"{r.load_h:.0f}",
                                cap=f"{r.capacity_h:.0f}",
                            ),
                            (rid,),
                        )
                    )
            wait = load.observed_wait_h
            if (load.queue_length or 0) > 0 or (wait is not None and wait >= cfg.wait_candidate_h):
                parts = []
                if load.queue_length:
                    parts.append(t("queued", lang, q=f"{load.queue_length:g}"))
                if wait is not None:
                    parts.append(t("wait", lang, w=f"{wait:.0f}"))
                sev = min(1.0, (wait or cfg.wait_candidate_h) / (cfg.wait_candidate_h * 5))
                row.signals.append(
                    Signal(
                        SignalKind.queue,
                        node_measured,
                        sev,
                        f"{node.name}: " + ", ".join(parts),
                        (node.id,),
                    )
                )

    for dom, st, source_id in event_logs:
        row = rows[DomainName(dom)]
        row.evidence_ids.append(source_id)
        slow = st.slowest_wait()
        if slow is not None and slow.wait_median_h >= cfg.wait_candidate_h:
            row.signals.append(
                Signal(
                    SignalKind.queue,
                    True,
                    min(1.0, slow.wait_median_h / (cfg.wait_candidate_h * 5)),
                    t(
                        "sig_log_wait",
                        lang,
                        w=f"{slow.wait_median_h:.0f}",
                        a=slow.activity,
                        p90=f"{slow.wait_p90_h:.0f}",
                        n=slow.count,
                    ),
                    (source_id, slow.activity),
                )
            )
        if st.lead_time_median_h is not None and st.completions_per_week > 0:
            expected_wip = st.completions_per_week * st.lead_time_median_h / 168
            if (
                st.open_cases > 1.5 * expected_wip
                and st.arrivals_per_week > 1.1 * st.completions_per_week
            ):
                ratio = st.arrivals_per_week / st.completions_per_week
                row.signals.append(
                    Signal(
                        SignalKind.capacity,
                        True,
                        min(1.0, (ratio - 1)),
                        t(
                            "sig_backlog",
                            lang,
                            i=f"{st.arrivals_per_week:.1f}",
                            o=f"{st.completions_per_week:.1f}",
                            open=st.open_cases,
                            exp=f"{expected_wip:.0f}",
                        ),
                        (source_id,),
                    )
                )

    for row in rows.values():
        row.evidence_ids = sorted(set(row.evidence_ids))
        ev = 0.0
        for kind in SignalKind:
            sigs = [s for s in row.signals if s.kind is kind]
            if sigs:
                best = max(sigs, key=lambda s: (s.measured, s.severity))
                w = cfg.measured_weight if best.measured else cfg.estimate_weight
                ev += w * (1 + best.severity)
        row.score = round(ev + cfg.prior_weight * row.prior, 4)
        if row.signals:
            row.verdict = DomainVerdict.candidate
            row.rationale = "; ".join(s.detail for s in row.signals)
        elif any(m.source_id for m in row.metrics) or row.evidence_ids:
            row.verdict = DomainVerdict.clear
            util = (
                t("max_util", lang, u=f"{row.max_utilization:.0%}")
                if row.max_utilization is not None
                else ""
            )
            row.rationale = t("no_signal", lang) + (f" ({util})" if util else "")
        elif row.metrics:
            row.verdict = DomainVerdict.not_assessed
            row.rationale = t("only_estimates", lang)
        else:
            row.verdict = DomainVerdict.not_assessed
            row.rationale = t("no_data", lang)

    return HeatTable(
        rows=list(rows.values()),
        direction=direction_check(graph, cfg, lang),
        config=cfg,
        lang=lang,
    )
