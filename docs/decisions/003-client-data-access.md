# 003 — Client data access: file uploads first, live connectors later

**Status:** accepted · 2026-11-05 (owner decision; answers the "data access" question in 000)

Both routes are supported:

1. **File uploads (now).** The client exports files (CSV/XLSX from CRM, ads, ticketing; PDFs/DOCX
   of SOPs; transcripts; email; event logs) and we ingest them.
2. **Live connectors (later).** We pull from the client's tools directly, read-only by default,
   using scoped credentials in the client's own accounts (brief §9.4, §14).

**Design consequence:** both routes produce the same output: a `Source` plus `TableData` /
`Chunk` / `EventLog` records in the per-client store. Everything downstream (flow modeling,
domain scan, results ledger) is blind to which route the data took. `connectors/base.py` defines the
`Connector` interface now. `FileDropConnector` is its first implementation, so a future HubSpot or
Zendesk connector is one new class, with no downstream changes.

Connector write actions (e.g. creating ads) are draft-only by default (G13) and live in the
interface from day one.
