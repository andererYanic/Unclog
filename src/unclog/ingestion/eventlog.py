"""Detect process-mining event logs in tables (case id + activity + timestamp)."""

from __future__ import annotations

from datetime import datetime

from .models import Event, EventLog, TableData

# English and German column names (German exports: DATEV, Lexware, CRM, Shop systems)
CASE = (
    "case_id",
    "case",
    "caseid",
    "ticket_id",
    "order_id",
    "lead_id",
    "deal_id",
    "id_case",
    "vorgang_id",
    "vorgangsnummer",
    "vorgang_nr",
    "vorgang",
    "auftrag_id",
    "auftragsnummer",
    "auftrag_nr",
    "anfrage_id",
    "anfragenummer",
    "ticket_nr",
    "ticketnummer",
    "fall_id",
    "projekt_id",
    "projektnummer",
    "bestellnummer",
    "bestell_nr",
)
ACTIVITY = (
    "activity",
    "event",
    "status",
    "stage",
    "step",
    "action",
    "aktivitaet",
    "aktivität",
    "ereignis",
    "schritt",
    "phase",
    "statusname",
    "bearbeitungsstatus",
)
TIMESTAMP = (
    "timestamp",
    "time",
    "datetime",
    "date",
    "created_at",
    "event_time",
    "changed_at",
    "zeitpunkt",
    "zeitstempel",
    "datum",
    "datum_uhrzeit",
    "zeit",
    "erstellt_am",
    "geaendert_am",
    "geändert_am",
    "aenderungsdatum",
    "änderungsdatum",
)
RESOURCE = (
    "resource",
    "user",
    "owner",
    "agent",
    "assignee",
    "employee",
    "bearbeiter",
    "mitarbeiter",
    "zustaendig",
    "zuständig",
    "verantwortlich",
    "benutzer",
)


def _norm(c: str) -> str:
    return c.strip().lower().replace(" ", "_").replace("-", "_")


def _find(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    by_norm = {_norm(c): c for c in columns}
    for a in aliases:
        if a in by_norm:
            return by_norm[a]
    return None


def _parse_ts(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def detect_event_log(table: TableData, min_parse_rate: float = 0.9) -> EventLog | None:
    case_c = _find(table.columns, CASE)
    act_c = _find(table.columns, ACTIVITY)
    ts_c = _find(table.columns, TIMESTAMP)
    if not (case_c and act_c and ts_c) or not table.rows:
        return None
    res_c = _find(table.columns, RESOURCE)
    events: list[Event] = []
    for i, row in enumerate(table.rows, start=1):
        ts = _parse_ts(row.get(ts_c))
        case, act = row.get(case_c), row.get(act_c)
        if ts is None or case in (None, "") or act in (None, ""):
            continue
        res = row.get(res_c) if res_c else None
        events.append(
            Event(
                case_id=str(case),
                activity=str(act),
                timestamp=ts,
                resource=None if res in (None, "") else str(res),
                row=i,
            )
        )
    if len(events) / len(table.rows) < min_parse_rate:
        return None
    events.sort(key=lambda e: (e.case_id, e.timestamp))
    return EventLog(source_id=table.source_id, table_name=table.name, events=events)
