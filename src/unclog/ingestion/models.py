"""Normalized ingestion output. Both data routes (uploads, connectors) produce these."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ..schemas.common import Id, Source, UnclogModel

Cell = str | int | float | bool | None


class Chunk(UnclogModel):
    """A piece of text with a locator so findings can cite it as Evidence."""

    id: Id
    source_id: Id
    locator: str
    text: str


class TableData(UnclogModel):
    source_id: Id
    name: str
    columns: list[str]
    rows: list[dict[str, Cell]]
    locator: str = Field(description="e.g. 'sheet Leads' or 'file'")


class Event(UnclogModel):
    case_id: str
    activity: str
    timestamp: datetime
    resource: str | None = None
    row: int


class EventLog(UnclogModel):
    """Process-mining shaped log (case, activity, timestamp) derived from a table."""

    source_id: Id
    table_name: str
    events: list[Event]


class IngestResult(UnclogModel):
    source: Source
    sha256: str
    chunks: list[Chunk] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    event_logs: list[EventLog] = Field(default_factory=list)
    pii_redactions: int = 0
    warnings: list[str] = Field(default_factory=list)
