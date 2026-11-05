"""Domains, flow model, constraints, policies, buffers (brief §4, §8.1-8.3, §13)."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from .common import Confidence, Grounded, Id, UnclogModel


class DomainName(StrEnum):
    race_r = "RACE-R"
    race_a = "RACE-A"
    race_c = "RACE-C"
    race_e = "RACE-E"
    fulfillment = "fulfillment"
    ops = "ops"
    support = "support"
    finance = "finance"
    hr = "hr"
    procurement = "procurement"
    product = "product"
    it = "it"
    legal = "legal"
    mgmt = "mgmt"
    other = "other"

    @property
    def is_race(self) -> bool:
        return self.value.startswith("RACE-")


#: Every domain G5 requires to be assessed (``other`` is optional).
REQUIRED_DOMAINS: frozenset[DomainName] = frozenset(
    d for d in DomainName if d is not DomainName.other
)


class DomainVerdict(StrEnum):
    constraint = "constraint"
    candidate = "candidate"
    clear = "clear"
    not_assessed = "not_assessed"


class StageMetric(UnclogModel):
    id: Id
    domain_id: Id
    name: str
    value: float
    unit: str
    period: str
    benchmark: float | None = None
    benchmark_source_id: Id | None = None
    higher_is_better: bool | None = Field(
        None, description="direction for benchmark gaps; None = not comparable"
    )
    source_id: Id | None = None
    measured: bool = Field(description="True = from data/logs; False = interview estimate")

    @model_validator(mode="after")
    def _measured_needs_source(self) -> Self:
        if self.measured and self.source_id is None:
            raise ValueError(f"StageMetric {self.id}: measured=true requires source_id (G17)")
        return self


class Domain(UnclogModel):
    """Domain heat-table row. Not Grounded: ``not_assessed`` rows legitimately have no evidence."""

    id: Id
    name: DomainName
    prior: Confidence
    metrics: list[StageMetric] = Field(default_factory=list)
    verdict: DomainVerdict = DomainVerdict.not_assessed
    evidence_ids: list[Id] = Field(default_factory=list)
    rationale: str | None = None

    @model_validator(mode="after")
    def _dismissal_needs_evidence(self) -> Self:
        # Brief §4.3 / G5: no "clear" verdict without a metric or documented source.
        if self.verdict is DomainVerdict.clear and not (self.metrics or self.evidence_ids):
            raise ValueError(f"Domain {self.name}: verdict 'clear' requires a metric or evidence")
        if self.verdict in (DomainVerdict.constraint, DomainVerdict.candidate) and not (
            self.metrics or self.evidence_ids
        ):
            raise ValueError(f"Domain {self.name}: verdict '{self.verdict}' requires evidence")
        return self


class Distribution(UnclogModel):
    """Parametric distribution for arrivals/service times; fitted from data where possible."""

    kind: str = Field(description="exponential | lognormal | gamma | normal | empirical | fixed")
    params: dict[str, float] = Field(default_factory=dict)
    samples: list[float] | None = None
    unit: str = "hours"


class Resource(Grounded):
    id: Id
    name: str
    kind: str = Field(description="person | team | role | system | vendor | machine")
    count: float = Field(1, gt=0)
    hours_per_period: float = Field(gt=0)
    period: str = "week"


class FlowNode(Grounded):
    id: Id
    name: str
    domain_id: Id
    resource_ids: list[Id] = Field(default_factory=list)
    arrival: Distribution | None = None
    service: Distribution | None = None
    queue_length: float | None = Field(None, ge=0)
    touch_time_h: float | None = Field(None, ge=0)
    wait_time_h: float | None = Field(None, ge=0)
    batch_size: float | None = Field(None, gt=0)
    patience_h: float | None = Field(
        None,
        gt=0,
        description="items waiting longer than this (calendar h) are lost, e.g. "
        "customers who stop waiting for an appointment; simulation only",
    )


class FlowEdge(UnclogModel):
    source: Id
    target: Id
    probability: float = Field(1.0, ge=0, le=1)
    label: str | None = None


class Task(Grounded):
    id: Id
    node_id: Id
    name: str
    resource_id: Id | None = None
    service: Distribution | None = None
    setup_time_h: float = Field(0, ge=0, description="context-switch/handoff prep (TOC setup)")
    adds_value_at_constraint: bool = False


class ConstraintType(StrEnum):
    physical = "physical"
    policy = "policy"
    market = "market"
    paradigm = "paradigm"


class ConstraintStatus(StrEnum):
    candidate = "candidate"
    confirmed = "confirmed"
    broken = "broken"
    moved = "moved"


class TestKind(StrEnum):
    relief = "relief"
    starvation = "starvation"
    queue = "queue"
    expedite = "expedite"
    absence = "absence"


class ConfirmationTest(UnclogModel):
    kind: TestKind
    passed: bool
    evidence_ids: list[Id] = Field(default_factory=list)
    note: str | None = None


class Constraint(Grounded):
    id: Id
    type: ConstraintType
    domain_id: Id
    resource_id: Id | None = None
    policy_id: Id | None = None
    market_segment: str | None = None
    description: str
    load_capacity_ratio: float | None = Field(None, ge=0)
    queue_evidence: str | None = None
    status: ConstraintStatus = ConstraintStatus.candidate
    tests_run: list[ConfirmationTest] = Field(default_factory=list)
    demand_vs_capacity_checked: bool = Field(
        False, description="both-direction check done (brief §4.3)"
    )

    @model_validator(mode="after")
    def _target_matches_type(self) -> Self:
        need = {
            ConstraintType.physical: self.resource_id,
            ConstraintType.policy: self.policy_id,
            ConstraintType.market: self.market_segment,
        }.get(self.type, "n/a")
        if need is None:
            field = {"physical": "resource_id", "policy": "policy_id", "market": "market_segment"}
            raise ValueError(
                f"Constraint {self.id}: type '{self.type}' requires {field[self.type]}"
            )
        return self

    @model_validator(mode="after")
    def _confirmation_rule(self) -> Self:
        # G4: confirmed needs >=2 independent evidence families and a passed confirmation test.
        if self.status is ConstraintStatus.confirmed:
            if len(self.confirming_families()) < 2:
                raise ValueError(
                    f"Constraint {self.id}: 'confirmed' needs >=2 independent evidence "
                    f"families (has {sorted(self.confirming_families())})"
                )
            if not any(t.passed for t in self.tests_run):
                raise ValueError(f"Constraint {self.id}: 'confirmed' needs a passed test")
            if not self.demand_vs_capacity_checked:
                raise ValueError(f"Constraint {self.id}: 'confirmed' needs both-direction check")
        return self


class PolicyKind(StrEnum):
    kpi = "kpi"
    incentive = "incentive"
    batch_rule = "batch_rule"
    approval = "approval"
    rule = "rule"


class Policy(Grounded):
    id: Id
    kind: PolicyKind
    statement: str
    rewards_behavior: str | None = None
    raises_system_t: bool | None = None
    local_optimum: bool = False
    inherited_from_constraint_id: Id | None = Field(None, description="inertia tracking")
    recommendation: str | None = None
    domain_id: Id | None = None
    affects_node_ids: list[Id] = Field(default_factory=list)


class Buffer(UnclogModel):
    id: Id
    protects: Id = Field(description="constraint id")
    size_h: float = Field(gt=0)
    green_pct: float = Field(33.3, gt=0, lt=100)
    red_pct: float = Field(66.7, gt=0, lt=100)

    @model_validator(mode="after")
    def _zones(self) -> Self:
        if self.green_pct >= self.red_pct:
            raise ValueError("Buffer: green_pct must be < red_pct")
        return self


class FocusStep(StrEnum):
    identify = "identify"
    exploit = "exploit"
    subordinate = "subordinate"
    elevate = "elevate"
    repeat = "repeat"


class FocusingAction(Grounded):
    id: Id
    constraint_id: Id
    step: FocusStep
    description: str
    owner: str | None = None
    done: bool = False
