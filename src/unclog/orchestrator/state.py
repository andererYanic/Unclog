"""Pipeline state: everything one engagement run has produced so far (brief §6, §12)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.opportunity_analyst import OpportunityAnalysis
from ..constraint.analyst import ConstraintReport
from ..deploy import PackageSpec
from ..domains.heat import HeatTable
from ..evals.harness import EvalReport
from ..flow.graph import FlowGraph
from ..goalfactor import GoalTree
from ..reporting.roadmap import Roadmap
from ..schemas.common import Source
from ..schemas.delivery import DeployedSystem
from ..schemas.design import Finding
from ..schemas.diagnosis import StageMetric
from ..schemas.engagement import Goal
from ..scoring.feasibility import Feasibility
from ..scoring.value import ValueReport


@dataclass
class State:
    engagement_id: str
    title: str
    lang: str = "de"
    phase: int = 0
    goal: Goal | None = None
    sources: list[Source] = field(default_factory=list)
    metrics: list[StageMetric] = field(default_factory=list)
    graph: FlowGraph | None = None
    heat: HeatTable | None = None
    report: ConstraintReport | None = None
    tree: GoalTree | None = None
    opportunities: OpportunityAnalysis | None = None
    feasibility: list[Feasibility] = field(default_factory=list)
    value: ValueReport | None = None
    roadmap: Roadmap | None = None
    deployed: list[tuple[DeployedSystem, PackageSpec, list[str]]] = field(default_factory=list)
    eval_reports: dict[str, EvalReport] = field(default_factory=dict)  # system id -> report
    findings: list[Finding] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
