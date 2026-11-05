"""Ingest one file: parse -> scrub PII -> chunk -> detect event logs -> IngestResult."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from ..schemas.common import Source, SourceKind
from .eventlog import detect_event_log
from .models import Chunk, IngestResult, TableData
from .parsers import PARSERS
from .pii import scrub, scrub_cell

MAX_CHUNK_CHARS = 4000

_KIND_BY_EXT = {
    ".vtt": SourceKind.interview,
    ".srt": SourceKind.interview,
    ".csv": SourceKind.export,
    ".tsv": SourceKind.export,
    ".xlsx": SourceKind.export,
    ".xlsm": SourceKind.export,
    ".json": SourceKind.export,
}


class UnsupportedFormat(ValueError):
    pass


def supported_extensions() -> list[str]:
    return sorted(PARSERS)


def _split(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for sentence in text.replace("\n", " \n").split(". "):
        piece = sentence if sentence.endswith(".") else sentence + ". "
        if len(buf) + len(piece) > limit and buf:
            parts.append(buf.strip())
            buf = ""
        while len(piece) > limit:
            parts.append(piece[:limit])
            piece = piece[limit:]
        buf += piece
    if buf.strip():
        parts.append(buf.strip())
    return parts


def ingest_bytes(
    data: bytes,
    filename: str,
    *,
    kind: SourceKind | None = None,
    title: str | None = None,
    scrub_pii: bool = True,
) -> IngestResult:
    ext = Path(filename).suffix.lower()
    parser = PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormat(
            f"{filename}: unsupported type {ext!r}; supported: {', '.join(supported_extensions())}"
        )
    sha = hashlib.sha256(data).hexdigest()
    source_id = f"src-{sha[:16]}"
    parsed = parser(data, filename)
    redactions = 0

    tables: list[TableData] = []
    for name, locator, cols, rows in parsed.tables:
        if scrub_pii:
            clean_rows = []
            for row in rows:
                new = {}
                for k, v in row.items():
                    new[k], n = scrub_cell(v)
                    redactions += n
                clean_rows.append(new)
            rows = clean_rows
        tables.append(
            TableData(source_id=source_id, name=name, columns=cols, rows=rows, locator=locator)
        )

    chunks: list[Chunk] = []
    for locator, text in parsed.texts:
        if scrub_pii:
            text, n = scrub(text)
            redactions += n
        pieces = _split(text)
        for j, piece in enumerate(pieces, start=1):
            loc = locator if len(pieces) == 1 else f"{locator} part {j}"
            chunks.append(
                Chunk(
                    id=f"{source_id}-c{len(chunks) + 1}",
                    source_id=source_id,
                    locator=loc,
                    text=piece,
                )
            )

    # Event logs are detected on scrubbed tables; case ids that look like PII get redacted.
    event_logs = [log for t in tables if (log := detect_event_log(t)) is not None]

    source = Source(
        id=source_id,
        kind=kind
        or (SourceKind.event_log if event_logs else _KIND_BY_EXT.get(ext, SourceKind.document)),
        title=title or Path(filename).name,
        uri=f"upload://{Path(filename).name}",
        collected_at=datetime.now(UTC),
        pii_scrubbed=scrub_pii,
    )
    return IngestResult(
        source=source,
        sha256=sha,
        chunks=chunks,
        tables=tables,
        event_logs=event_logs,
        pii_redactions=redactions,
        warnings=parsed.warnings,
    )


def ingest_file(path: str | Path, **kwargs) -> IngestResult:
    p = Path(path)
    return ingest_bytes(p.read_bytes(), p.name, **kwargs)
