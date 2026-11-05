"""Connector interface shared by both data routes (decision 003).

Route 1 (now): :class:`~unclog.connectors.file_drop.FileDropConnector` reads uploaded files.
Route 2 (later): one class per client tool (HubSpot, Google Ads, Zendesk, ...) implementing the
same interface. Downstream code only ever sees :class:`IngestResult` records in the store.

Safety (brief §9.3, §14, G13):
- Connectors are read-only unless they declare ``supports_write``.
- Writes go through :meth:`Connector.write`, which takes a :class:`WriteAction` that defaults
  to ``draft=True``. Live (non-draft) writes need an approval reference.
- Credentials are never passed in prompts or stored in the repo; connectors get them from a
  :class:`CredentialProvider` (vault-backed in production).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar, Protocol, Self

from pydantic import Field, model_validator

from ..ingestion.models import IngestResult
from ..schemas.common import UnclogModel


class CredentialProvider(Protocol):
    def get(self, connector: str, key: str) -> str: ...


class DatasetInfo(UnclogModel):
    """Something a connector can fetch: a file, a CRM object type, an ads report."""

    name: str
    description: str | None = None
    updated_at: datetime | None = None
    approx_rows: int | None = None


class WriteAction(UnclogModel):
    connector: str
    operation: str = Field(description="e.g. 'create_ad', 'send_email', 'update_deal'")
    payload: dict[str, Any]
    change_summary: str = Field(min_length=10, description="what changes and why (brief §9.3)")
    draft: bool = True
    approval_ref: str | None = None

    @model_validator(mode="after")
    def _approval(self) -> Self:
        if not self.draft and not self.approval_ref:
            raise ValueError("WriteAction: live (draft=false) writes need approval_ref (G13)")
        return self


class WriteResult(UnclogModel):
    action: WriteAction
    external_id: str | None = None
    state: str = Field(description="draft | paused | live")


class Connector(ABC):
    #: Stable identifier, e.g. "file_drop", "hubspot".
    name: ClassVar[str]
    #: Least-privilege scopes this connector requests (documented for client consent).
    scopes: ClassVar[tuple[str, ...]] = ()
    supports_write: ClassVar[bool] = False

    @abstractmethod
    def list_datasets(self) -> list[DatasetInfo]: ...

    @abstractmethod
    def fetch(self, dataset: str, since: datetime | None = None) -> IngestResult: ...

    def write(self, action: WriteAction) -> WriteResult:
        raise NotImplementedError(f"{self.name} is read-only")


_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    if cls.name in _REGISTRY:
        raise ValueError(f"connector {cls.name!r} already registered")
    _REGISTRY[cls.name] = cls
    return cls


def available() -> dict[str, type[Connector]]:
    return dict(_REGISTRY)
