"""Engagement, Goal, Function, Process (brief §2.1, §13)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .common import Grounded, Id, UnclogModel


class CompanySize(StrEnum):
    micro = "micro"
    smb = "smb"
    mid_market = "mid_market"
    enterprise = "enterprise"


class EngagementStatus(StrEnum):
    intake = "intake"
    diagnose = "diagnose"
    design = "design"
    deliver = "deliver"
    sustain = "sustain"
    closed = "closed"


class Stakeholder(UnclogModel):
    id: Id
    role: str
    name: str | None = None  # may be pseudonymous
    decision_authority: bool = False


class Engagement(UnclogModel):
    id: Id
    client: str
    industry: str
    size: CompanySize
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    status: EngagementStatus = EngagementStatus.intake
    created: datetime
    non_profit: bool = False


class TIOE(UnclogModel):
    """Throughput / Inventory / Operating Expense, in currency per period (brief §2.1)."""

    T: float | None = None
    I: float | None = None  # noqa: E741 - TOC notation
    OE: float | None = None
    currency: str = "EUR"
    period: str = "month"


class Goal(Grounded):
    statement: str = Field(min_length=10)
    unit_of_throughput: str
    t_definition: str
    i_definition: str
    oe_definition: str
    baseline: TIOE
    horizon: str
    mission_metric: str | None = Field(None, description="non-profit/public goal metric")


class Function(UnclogModel):
    id: Id
    name: str
    head_role: str | None = None
    headcount: int | None = Field(None, ge=0)


class ProcessHealth(StrEnum):
    sound = "sound"
    fragile = "fragile"
    broken = "broken"


class Process(Grounded):
    id: Id
    name: str
    function_id: Id | None = None
    description: str | None = None
    process_health: ProcessHealth
    owner: str | None = None
