"""Goal tree, opportunities, value model, risks, findings, simulation runs (brief §7, §8.4-8.7)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from .common import Confidence, Grounded, Id, UnclogModel
from .diagnosis import FocusStep


class GoalNodeStatus(StrEnum):
    open = "open"
    chosen = "chosen"
    pruned = "pruned"


class GoalNodeKind(StrEnum):
    root = "root"
    option = "option"
    base_action = "base_action"


class ActionTag(StrEnum):
    ai_doable = "ai_doable"
    ai_assisted = "ai_assisted"
    human = "human"
    non_ai = "non_ai"


class ConstraintLink(StrEnum):
    """How a node relates to the constraint (brief §7 step 5)."""

    acts_on = "acts_on"
    gates_flow = "gates_flow"
    protects = "protects"
    off_constraint = "off_constraint"


class GoalNode(Grounded):
    id: Id
    parent_id: Id | None = None
    statement: str
    metric: str | None = None
    status: GoalNodeStatus = GoalNodeStatus.open
    kind: GoalNodeKind
    tag: ActionTag | None = None
    constraint_link: ConstraintLink | None = None
    owner: str | None = None
    focus_step: FocusStep | None = None
    effort_days: float | None = Field(None, gt=0, description="base actions: doable in days")
    rationale: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind is GoalNodeKind.root:
            if self.parent_id is not None:
                raise ValueError(f"GoalNode {self.id}: root cannot have a parent")
            if not self.metric:
                raise ValueError(f"GoalNode {self.id}: root must be a measurable outcome (metric)")
        elif self.parent_id is None:
            raise ValueError(f"GoalNode {self.id}: non-root node needs parent_id")
        if self.kind is GoalNodeKind.base_action:
            if self.tag is None:
                raise ValueError(f"GoalNode {self.id}: base_action needs a tag")
            if self.constraint_link is None:
                raise ValueError(f"GoalNode {self.id}: base_action needs constraint_link")
        return self


class AIRole(StrEnum):
    assist = "assist"
    automate = "automate"
    augment = "augment"
    decide = "decide"
    gate = "gate"
    monitor = "monitor"
    none = "none"


class Position(StrEnum):
    at_constraint = "at_constraint"
    upstream = "upstream"
    downstream = "downstream"
    off_flow = "off_flow"
    market = "market"
    policy = "policy"


class Priority(StrEnum):
    exploit_now = "exploit-now"
    subordinate = "subordinate"
    elevate = "elevate"
    policy_change = "policy-change"
    fix_process_first = "fix-process-first"
    strategic_bet = "strategic bet"
    defer = "defer"
    do_not_pursue = "do not pursue"


class Validation(StrEnum):
    simulation = "simulation"
    measurement = "measurement"
    none = "none"


class RealizationKind(StrEnum):
    attrition = "attrition"
    contractor_reduction = "contractor_reduction"
    overtime_reduction = "overtime_reduction"
    license_termination = "license_termination"
    redeployment_to_constraint = "redeployment_to_constraint"


class RealizationPath(UnclogModel):
    kind: RealizationKind
    owner: str
    timing: str
    probability: Confidence
    target_role: str | None = Field(None, description="required for redeployment")

    @model_validator(mode="after")
    def _redeploy_target(self) -> Self:
        if self.kind is RealizationKind.redeployment_to_constraint and not self.target_role:
            raise ValueError(
                "RealizationPath: redeployment needs a defined constrained target_role"
            )
        return self


class DeltaT(UnclogModel):
    amount: float = 0.0
    validated_by: Validation = Validation.none
    sim_run_id: Id | None = None
    demand_can_absorb: bool | None = None
    lag: str | None = None

    @model_validator(mode="after")
    def _sim_ref(self) -> Self:
        if self.validated_by is Validation.simulation and self.sim_run_id is None:
            raise ValueError("DeltaT: validated_by=simulation requires sim_run_id")
        return self


class DeltaOE(UnclogModel):
    """Negative amount = OE reduction. Without a realization path it is a mirage (brief §8.6)."""

    amount: float = 0.0
    capacity_released_h: float = Field(0.0, ge=0)
    realization_path: RealizationPath | None = None
    lag: str | None = None

    @property
    def is_mirage(self) -> bool:
        return self.realization_path is None and (self.amount != 0 or self.capacity_released_h > 0)

    @property
    def realized_amount(self) -> float:
        return 0.0 if self.realization_path is None else self.amount


class DeltaI(UnclogModel):
    amount: float = 0.0
    carrying_cost_rate: float = Field(0.0, ge=0, description="annual fraction")
    measurement_method: str | None = None


class Delta(UnclogModel):
    T: DeltaT = Field(default_factory=DeltaT)
    I: DeltaI = Field(default_factory=DeltaI)  # noqa: E741
    OE: DeltaOE = Field(default_factory=DeltaOE)
    currency: str = "EUR"
    period: str = "month"


Score = Annotated[int, Field(ge=1, le=5)]


class ScoreItem(UnclogModel):
    score: Score
    justification: str = Field(min_length=3)


class Scores(UnclogModel):
    """Brief §8.5. Risk and effort are scored inversely (5 = low risk / low effort)."""

    constraint_relevance: ScoreItem
    throughput_impact: ScoreItem
    feasibility: ScoreItem
    data_readiness: ScoreItem
    risk: ScoreItem
    effort: ScoreItem
    proven_ness: ScoreItem
    ownership_clarity: ScoreItem
    strategic_fit: ScoreItem


class Opportunity(Grounded):
    id: Id
    goal_node_ids: list[Id] = Field(default_factory=list)
    task_ids: list[Id] = Field(default_factory=list)
    title: str
    pattern: str | None = Field(None, description="technique-library pattern id")
    ai_role: AIRole
    position: Position
    focus_step: FocusStep
    constraint_id: Id | None = None
    constraint_link: ConstraintLink
    proven: bool
    proof_refs: list[str] = Field(default_factory=list)
    rd_label: bool = False
    process_health_ok: bool
    client_owner: str | None = None
    delta: Delta = Field(default_factory=Delta)
    wip_side_effects: str | None = None
    release_gate_required: bool = False
    release_gate_design: str | None = None
    human_in_loop_design: str | None = None
    tech_approach: str | None = None
    build_vs_buy: str | None = None
    risk_ids: list[Id] = Field(default_factory=list)
    scores: Scores | None = None
    priority: Priority | None = None
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        # §9.3 proven-first: novel work must carry the R&D label.
        if not self.proven and not self.rd_label:
            raise ValueError(f"Opportunity {self.id}: unproven pattern must set rd_label=true")
        if self.proven and not self.proof_refs:
            raise ValueError(f"Opportunity {self.id}: proven=true requires proof_refs")
        # §9.8: don't automate a broken process.
        if not self.process_health_ok and self.priority not in (
            None,
            Priority.fix_process_first,
            Priority.do_not_pursue,
            Priority.defer,
        ):
            raise ValueError(
                f"Opportunity {self.id}: unhealthy process must be fix-process-first/defer"
            )
        # §2.4 flooding trap: upstream accelerators ship with a release gate.
        if self.position is Position.upstream and not self.release_gate_required:
            raise ValueError(f"Opportunity {self.id}: upstream position requires a release gate")
        if (
            self.release_gate_required
            and not self.release_gate_design
            and self.priority
            not in (
                None,
                Priority.defer,
                Priority.do_not_pursue,
            )
        ):
            raise ValueError(f"Opportunity {self.id}: release gate required but not designed")
        # §2.4 NCX-10: off-constraint work defaults to defer unless OE is realized.
        if (
            self.constraint_link is ConstraintLink.off_constraint
            and self.priority not in (None, Priority.defer, Priority.do_not_pursue)
            and self.delta.OE.realization_path is None
        ):
            raise ValueError(
                f"Opportunity {self.id}: off-constraint work must be defer "
                "without a realization path"
            )
        if self.constraint_link is not ConstraintLink.off_constraint and self.constraint_id is None:
            raise ValueError(f"Opportunity {self.id}: constraint_link set but no constraint_id")
        return self


class Risk(Grounded):
    id: Id
    description: str
    category: str = Field(description="data | integration | compliance | change | model | security")
    likelihood: Score
    impact: Score
    mitigation: str | None = None
    owner: str | None = None


class FindingSeverity(StrEnum):
    info = "info"
    warning = "warning"
    blocking = "blocking"


class Finding(Grounded):
    id: Id
    phase: int = Field(ge=0, le=14)
    statement: str
    severity: FindingSeverity = FindingSeverity.info
    gate: str | None = Field(None, pattern=r"^G([1-9]|1[0-7])$")


class SimRun(UnclogModel):
    id: Id
    scenario: str
    seed: int
    replications: int = Field(ge=1)
    horizon: str
    inputs_ref: str
    throughput: float
    lead_time_p50_h: float | None = None
    lead_time_p90_h: float | None = None
    wip_by_stage: dict[str, float] = Field(default_factory=dict)
    utilization_by_resource: dict[str, float] = Field(default_factory=dict)
    constraint_location: Id | None = None
    created: datetime


class ValueScenario(StrEnum):
    low = "low"
    base = "base"
    high = "high"


class ValueLine(UnclogModel):
    opportunity_id: Id
    scenario: ValueScenario
    delta_t: float
    delta_oe_realized: float
    delta_i_carrying: float
    run_cost: float = Field(ge=0)
    amortized_build: float = Field(ge=0)
    delta_profit: float


class MirageEntry(UnclogModel):
    opportunity_id: Id
    capacity_released_h: float = Field(ge=0)
    claimed_amount: float
    reason: str


class ValueModel(Grounded):
    id: Id
    lines: list[ValueLine] = Field(default_factory=list)
    mirage_ledger: list[MirageEntry] = Field(default_factory=list)
    dedup_notes: list[str] = Field(default_factory=list)
    expected_lag: str | None = None
    as_of: date | None = None
