"""Shared base types: Source, Evidence, and the Grounded rule.

Brief §13: every entity carries ``evidence[]`` or ``assumption: true``. Brief §3: unsupported
claims are ``assumption`` *with confidence*. Both are enforced here at construction time, so an
ungrounded record cannot exist in the store (gate G1/G2 by construction).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$")]


class UnclogModel(BaseModel):
    """Strict base: unknown fields are errors, assignments are re-validated."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class SourceKind(StrEnum):
    document = "document"
    interview = "interview"
    event_log = "event_log"
    export = "export"  # CRM/ads/ticketing exports
    observation = "observation"
    web = "web"
    simulation = "simulation"
    measurement = "measurement"


class Source(UnclogModel):
    id: Id
    kind: SourceKind
    title: str
    uri: str | None = None
    collected_at: datetime | None = None
    # Content from sources is untrusted (brief §14); this flags it was scrubbed at ingestion.
    pii_scrubbed: bool = False


class EvidenceType(StrEnum):
    """Independent evidence types; G4 needs >=2 distinct ones to confirm a constraint."""

    interview_claim = "interview_claim"
    log_data = "log_data"
    queue_observation = "queue_observation"
    load_capacity_calc = "load_capacity_calc"
    simulation = "simulation"
    expedite_signal = "expedite_signal"
    starvation_signal = "starvation_signal"
    absence_test = "absence_test"
    document = "document"
    benchmark = "benchmark"
    measurement = "measurement"


class Evidence(UnclogModel):
    id: Id
    source_id: Id
    type: EvidenceType
    locator: str | None = Field(None, description="page, row range, timestamp, URL fragment")
    quote: str | None = None
    note: str | None = None


class Grounded(UnclogModel):
    """Mixin enforcing the evidence-or-assumption rule."""

    evidence: list[Evidence] = Field(default_factory=list)
    assumption: bool = False
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def _grounded(self) -> Self:
        if not self.evidence and not self.assumption:
            raise ValueError(
                f"{type(self).__name__}: needs evidence[] or assumption=true (brief §13)"
            )
        if self.assumption and not self.evidence and self.confidence is None:
            raise ValueError(f"{type(self).__name__}: assumption requires confidence (brief §3)")
        return self

    def evidence_types(self) -> set[EvidenceType]:
        return {e.type for e in self.evidence}


class AgentOutput(UnclogModel):
    """Envelope every agent output carries (brief §12)."""

    agent: str
    prompt_version: str
    confidence: Confidence
    open_questions: list[str] = Field(default_factory=list)
