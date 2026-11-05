"""Run synthetic cases through the diagnosis pipeline and score them (brief §18).

``unclog eval-cases [root]`` prints per-case checks and accuracy split by RACE vs back-end
cases; the brief requires the two to stay within a small gap, else the RACE prior is
over-weighted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..constraint import ConstraintReport, TextItem, identify
from ..domains import HeatTable, build_heat_table
from ..flow import compute
from ..flow.eventlog_stats import EventLogStats
from ..ingestion import ingest_file
from ..schemas.common import SourceKind
from .cases import SyntheticCase, load_all

MAX_RACE_BACKEND_GAP = 0.15


@dataclass
class CaseResult:
    case: SyntheticCase
    heat: HeatTable
    report: ConstraintReport
    logs: list[tuple[str, EventLogStats, str]]
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def run_case(case: SyntheticCase) -> CaseResult:
    logs: list[tuple[str, EventLogStats, str]] = []
    texts: list[TextItem] = []
    for f in case.raw_files:
        r = ingest_file(case.raw_path(f))
        for log in r.event_logs:
            dom = case.event_log_domains.get(f)
            if dom is None:
                raise ValueError(f"{case.id}: event log {f} needs event_log_domains entry")
            logs.append((dom, compute(log), r.source.id))
        testimony = r.source.kind is SourceKind.interview
        texts += [TextItem(c.source_id, c.locator, c.text, testimony) for c in r.chunks]
    graph = case.graph()
    heat = build_heat_table(case.metrics, graph, event_logs=logs)
    report = identify(heat, graph, event_logs=logs, texts=texts, activity_nodes=case.activity_nodes)
    res = CaseResult(case, heat, report, logs)
    res.checks = score(res)
    return res


def score(res: CaseResult) -> dict[str, bool]:
    exp, heat, rep = res.case.expected, res.heat, res.report
    checks: dict[str, bool] = {}
    if "top_domain" in exp:
        top = heat.candidates()[0].domain.value if heat.candidates() else None
        checks["heat_top_domain"] = top == exp["top_domain"]
    if "direction" in exp:
        checks["direction"] = heat.direction.verdict.value == exp["direction"]
    if "binding" in exp:
        want, got = exp["binding"], rep.binding
        if want is None:
            checks["binding"] = got is None
        else:
            checks["binding"] = (
                got is not None
                and got.type.value == want["type"]
                and ("domain" not in want or got.domain_id == want["domain"])
                and (
                    "target_contains" not in want
                    or want["target_contains"].lower()
                    in (
                        (got.resource_id or got.policy_id or got.market_segment or "")
                        + " "
                        + got.description
                    ).lower()
                )
            )
    if "work_mode" in exp:
        checks["work_mode"] = rep.work_mode == exp["work_mode"]
    if "next_constraint_kind" in exp:
        nk = rep.next_constraint.kind if rep.next_constraint else None
        checks["next_constraint"] = nk == exp["next_constraint_kind"]
    for d in exp.get("must_not_confirm", []):
        checks[f"not_confirmed:{d}"] = all(c.domain_id != d for c in rep.confirmed)
    for d in exp.get("must_rank_below_top", []):
        ranked = [r.domain.value for r in heat.ranked()]
        checks[f"below_top:{d}"] = ranked.index(d) > 0
    if "coverage_issues" in exp:
        checks["coverage_issues"] = len(heat.coverage_issues()) == exp["coverage_issues"]
    if "min_coverage_issues" in exp:
        checks["min_coverage_issues"] = len(heat.coverage_issues()) >= exp["min_coverage_issues"]
    if "eventlog_slowest_wait" in exp:
        checks["eventlog_slowest_wait"] = bool(res.logs) and (
            res.logs[0][1].slowest_wait().activity == exp["eventlog_slowest_wait"]
        )
    if exp.get("local_optimum_flagged"):
        checks["local_optimum_flagged"] = bool(rep.policy_audit.local_optima())
    return checks


@dataclass
class EvalSummary:
    results: list[CaseResult]

    def accuracy(self, kind: str | None = None) -> float | None:
        rs = [
            r
            for r in self.results
            if "binding" in r.case.expected and (kind is None or r.case.kind == kind)
        ]
        if not rs:
            return None
        return sum(r.checks.get("binding", False) for r in rs) / len(rs)

    @property
    def race_backend_gap(self) -> float | None:
        a, b = self.accuracy("race"), self.accuracy("backend")
        return None if a is None or b is None else abs(a - b)

    def to_text(self) -> str:
        lines = []
        for r in self.results:
            bad = [k for k, v in r.checks.items() if not v]
            b = r.report.binding
            got = f"{b.type.value}@{b.domain_id}" if b else "none"
            lines.append(
                f"{'PASS' if r.passed else 'FAIL'}  {r.case.id:<28} [{r.case.kind}] "
                f"binding={got}" + (f"  failed: {', '.join(bad)}" if bad else "")
            )
        fmt = lambda x: "n/a" if x is None else f"{x:.0%}"  # noqa: E731
        lines.append(
            f"binding accuracy: all {fmt(self.accuracy())}, race "
            f"{fmt(self.accuracy('race'))}, backend {fmt(self.accuracy('backend'))}, "
            f"gap {fmt(self.race_backend_gap)} (max {MAX_RACE_BACKEND_GAP:.0%})"
        )
        return "\n".join(lines)


def run_all(root: str | Path) -> EvalSummary:
    return EvalSummary([run_case(c) for c in load_all(root)])
