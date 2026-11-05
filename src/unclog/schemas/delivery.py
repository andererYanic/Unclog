"""Deployed systems, evals, team sync, results ledger (brief §9, §13)."""

from __future__ import annotations

import statistics
from datetime import date, datetime
from typing import Self

from pydantic import Field, computed_field, model_validator

from .common import Id, UnclogModel


class DeployedSystem(UnclogModel):
    id: Id
    opportunity_id: Id
    skill_ref: str | None = None
    routine_ref: str | None = None
    connectors: list[str] = Field(default_factory=list)
    schedule: str | None = Field(None, description="cron expression")
    trigger: str | None = None
    environment: str
    client_owner: str
    runbook_ref: str
    rollback: str
    version: str
    external_effect: bool = Field(description="ads, emails, invoices, posts, purchases ...")
    draft_safe: bool = True
    go_live_approval_ref: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.schedule and self.trigger:
            raise ValueError(f"DeployedSystem {self.id}: use schedule or trigger, not both")
        # G13: external effects stay draft/paused until a human approves go-live.
        if self.external_effect and not self.draft_safe and not self.go_live_approval_ref:
            raise ValueError(
                f"DeployedSystem {self.id}: external effect without draft_safe needs approval ref"
            )
        return self


class EvalCase(UnclogModel):
    id: Id
    input_ref: str
    checks: list[str] = Field(default_factory=list)
    kind: str = Field("representative", description="representative | edge | adversarial")


class EvalSuite(UnclogModel):
    id: Id
    system_id: Id
    cases: list[EvalCase] = Field(min_length=1)
    rubric: str
    pass_mean: float
    pass_worst_case: float = Field(description="worst-case floor (G14)")
    min_runs_per_case: int = Field(10, ge=10)


class EvalRun(UnclogModel):
    """Statistics are computed here, deterministically, never by an LLM (brief §17)."""

    id: Id
    suite_id: Id
    model: str
    harness_version: str
    scores: list[float] = Field(min_length=1)
    human_ratings: list[float] = Field(default_factory=list)
    cost_usd: float = Field(0.0, ge=0)
    timestamp: datetime

    @computed_field
    @property
    def n(self) -> int:
        return len(self.scores)

    @computed_field
    @property
    def mean(self) -> float:
        return statistics.fmean(self.scores)

    @computed_field
    @property
    def variance(self) -> float:
        return statistics.pvariance(self.scores) if len(self.scores) > 1 else 0.0

    @computed_field
    @property
    def worst_case(self) -> float:
        return min(self.scores)

    def passes(self, suite: EvalSuite) -> bool:
        return (
            self.n >= suite.min_runs_per_case * len(suite.cases)
            and self.mean >= suite.pass_mean
            and self.worst_case >= suite.pass_worst_case
        )


class SyncSession(UnclogModel):
    id: Id
    pod: str
    date: date
    top_performer_ids: list[str] = Field(default_factory=list, description="pseudonymous ids only")
    extracted_sop_ref: str | None = None
    skill_changes: list[str] = Field(default_factory=list)
    consent_ref: str | None = None
    used_log_mining: bool = False

    @model_validator(mode="after")
    def _privacy(self) -> Self:
        # §9.6 / §14: log mining or individual attribution requires recorded consent.
        if (self.used_log_mining or self.top_performer_ids) and not self.consent_ref:
            raise ValueError(f"SyncSession {self.id}: log mining/individual ids need consent_ref")
        return self


class ResultsLedgerEntry(UnclogModel):
    metric: str
    stage_metric_id: Id | None = None
    baseline: float
    current: float
    baseline_date: date
    date: date
    leading: bool = Field(description="leading indicator vs lagging money metric")
    lag_note: str | None = None
    attribution_caveat: str

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.date < self.baseline_date:
            raise ValueError("ResultsLedgerEntry: date precedes baseline_date")
        return self
