"""Ingestion: pdf, docx, xlsx, csv, json, email, transcripts, event logs (brief §19 step 3).

Output is route-neutral (decision 003): uploads and future live connectors both yield
:class:`IngestResult` records.
"""

from .models import Chunk, Event, EventLog, IngestResult, TableData
from .pipeline import UnsupportedFormat, ingest_bytes, ingest_file, supported_extensions

__all__ = [
    "Chunk",
    "Event",
    "EventLog",
    "IngestResult",
    "TableData",
    "UnsupportedFormat",
    "ingest_bytes",
    "ingest_file",
    "supported_extensions",
]
