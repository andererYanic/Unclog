"""Pull data from any connector into a client store. Same code path for both routes."""

from __future__ import annotations

from datetime import datetime

from ..schemas.common import UnclogModel
from ..store import ClientStore
from .base import Connector
from .file_drop import FileDropConnector


class PullReport(UnclogModel):
    connector: str
    ingested: list[str] = []
    duplicates: list[str] = []
    failed: dict[str, str] = {}
    skipped_unsupported: list[str] = []
    warnings: list[str] = []
    pii_redactions: int = 0


def pull(
    connector: Connector,
    store: ClientStore,
    actor: str,
    datasets: list[str] | None = None,
    since: datetime | None = None,
) -> PullReport:
    report = PullReport(connector=connector.name)
    if isinstance(connector, FileDropConnector):
        report.skipped_unsupported = connector.unsupported()
    names = datasets if datasets is not None else [d.name for d in connector.list_datasets()]
    for name in names:
        try:
            result = connector.fetch(name, since=since)
        except Exception as exc:  # one bad file must not stop the batch; it is reported
            report.failed[name] = f"{type(exc).__name__}: {exc}"
            continue
        if isinstance(connector, FileDropConnector):
            store.put_raw(connector.read_bytes(name), result.sha256, name, actor)
        new = store.put_source(result, actor)
        (report.ingested if new else report.duplicates).append(name)
        report.pii_redactions += result.pii_redactions
        report.warnings += [f"{name}: {w}" for w in result.warnings]
    return report
