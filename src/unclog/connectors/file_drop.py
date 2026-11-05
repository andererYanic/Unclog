"""Route 1: client-uploaded files, exposed through the common Connector interface."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..ingestion import IngestResult, ingest_bytes, supported_extensions
from .base import Connector, DatasetInfo, register


@register
class FileDropConnector(Connector):
    """Reads files from an upload folder. Read-only; never writes back to the client."""

    name = "file_drop"
    scopes = ()

    def __init__(self, folder: str | Path, scrub_pii: bool = True) -> None:
        self.folder = Path(folder).resolve()
        self.scrub_pii = scrub_pii
        if not self.folder.is_dir():
            raise NotADirectoryError(self.folder)

    def _files(self) -> list[Path]:
        exts = set(supported_extensions())
        return sorted(
            p
            for p in self.folder.rglob("*")
            if p.is_file() and p.suffix.lower() in exts and not p.name.startswith(".")
        )

    def list_datasets(self) -> list[DatasetInfo]:
        return [
            DatasetInfo(
                name=str(p.relative_to(self.folder)),
                updated_at=datetime.fromtimestamp(p.stat().st_mtime, UTC),
            )
            for p in self._files()
        ]

    def unsupported(self) -> list[str]:
        """Files in the folder we can't ingest yet, so nothing is dropped silently."""
        exts = set(supported_extensions())
        return sorted(
            str(p.relative_to(self.folder))
            for p in self.folder.rglob("*")
            if p.is_file() and p.suffix.lower() not in exts and not p.name.startswith(".")
        )

    def _resolve(self, dataset: str) -> Path:
        path = (self.folder / dataset).resolve()
        if not path.is_relative_to(self.folder) or not path.is_file():
            raise FileNotFoundError(dataset)
        return path

    def read_bytes(self, dataset: str) -> bytes:
        return self._resolve(dataset).read_bytes()

    def fetch(self, dataset: str, since: datetime | None = None) -> IngestResult:
        path = self._resolve(dataset)
        return ingest_bytes(path.read_bytes(), path.name, scrub_pii=self.scrub_pii)
