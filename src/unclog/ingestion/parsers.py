"""File parsers. Each returns raw (unscrubbed) tables and text segments.

Optional formats (xlsx, pdf, docx) need ``pip install unclog[ingest]``; a missing library
produces a clear error rather than a silent skip.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from pathlib import Path

from .models import Cell


@dataclass
class Parsed:
    tables: list[tuple[str, str, list[str], list[dict[str, Cell]]]] = field(default_factory=list)
    # (name, locator, columns, rows)
    texts: list[tuple[str, str]] = field(default_factory=list)  # (locator, text)
    warnings: list[str] = field(default_factory=list)


class MissingDependency(RuntimeError):
    pass


def _coerce(v: str) -> Cell:
    s = v.strip()
    if s == "":
        return None
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_csv(data: bytes, name: str) -> Parsed:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows_raw = [r for r in reader if any(c.strip() for c in r)]
    out = Parsed()
    if not rows_raw:
        out.warnings.append(f"{name}: empty table")
        return out
    header = [h.strip() or f"col_{i + 1}" for i, h in enumerate(rows_raw[0])]
    rows = []
    for r in rows_raw[1:]:
        if len(r) != len(header):
            out.warnings.append(f"{name}: row with {len(r)} cells, header has {len(header)}")
        rows.append({h: _coerce(r[i]) if i < len(r) else None for i, h in enumerate(header)})
    out.tables.append((Path(name).stem, "file", header, rows))
    return out


def parse_xlsx(data: bytes, name: str) -> Parsed:
    try:
        import openpyxl
    except ImportError as exc:
        raise MissingDependency("xlsx needs openpyxl: pip install unclog[ingest]") from exc
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = Parsed()
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        header_row = next(it, None)
        if header_row is None:
            continue
        header = [
            str(h).strip() if h is not None else f"col_{i + 1}" for i, h in enumerate(header_row)
        ]
        rows = []
        for r in it:
            if r is None or all(v is None for v in r):
                continue
            row: dict[str, Cell] = {}
            for i, h in enumerate(header):
                v = r[i] if i < len(r) else None
                row[h] = v if isinstance(v, (int, float, bool)) or v is None else str(v)
            rows.append(row)
        out.tables.append((ws.title, f"sheet {ws.title}", header, rows))
    return out


def parse_text(data: bytes, name: str) -> Parsed:
    text = _decode(data)
    out = Parsed()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for i, p in enumerate(paras, start=1):
        out.texts.append((f"para {i}", p))
    return out


_VTT_TS = re.compile(r"^\s*(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*")


def parse_transcript(data: bytes, name: str) -> Parsed:
    """WebVTT/SRT: one segment per cue, located by its start timestamp (interview evidence)."""
    text = _decode(data)
    out = Parsed()
    blocks = re.split(r"\n\s*\n", text)
    for b in blocks:
        lines = [ln for ln in b.strip().splitlines() if ln.strip()]
        ts_line = next((ln for ln in lines if _VTT_TS.match(ln)), None)
        if ts_line is None:
            continue
        start = ts_line.split("-->")[0].strip()
        body = " ".join(ln for ln in lines[lines.index(ts_line) + 1 :]).strip()
        if body:
            out.texts.append((f"t={start}", body))
    if not out.texts:
        return parse_text(data, name)
    return out


def parse_json(data: bytes, name: str) -> Parsed:
    obj = json.loads(_decode(data))
    out = Parsed()
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        cols: list[str] = []
        for x in obj:
            cols += [k for k in x if k not in cols]
        rows = [
            {
                c: (
                    x.get(c)
                    if isinstance(x.get(c), (str, int, float, bool)) or x.get(c) is None
                    else json.dumps(x.get(c))
                )
                for c in cols
            }
            for x in obj
        ]
        out.tables.append((Path(name).stem, "file", cols, rows))
    else:
        out.texts.append(("document", json.dumps(obj, indent=2, ensure_ascii=False)))
    return out


def parse_pdf(data: bytes, name: str) -> Parsed:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise MissingDependency("pdf needs pypdf: pip install unclog[ingest]") from exc
    out = Parsed()
    reader = PdfReader(io.BytesIO(data))
    for i, page in enumerate(reader.pages, start=1):
        t = (page.extract_text() or "").strip()
        if t:
            out.texts.append((f"page {i}", t))
    if not out.texts:
        out.warnings.append(f"{name}: no extractable text (scanned PDF? needs OCR)")
    return out


def parse_docx(data: bytes, name: str) -> Parsed:
    try:
        import docx
    except ImportError as exc:
        raise MissingDependency("docx needs python-docx: pip install unclog[ingest]") from exc
    d = docx.Document(io.BytesIO(data))
    out = Parsed()
    for i, p in enumerate(d.paragraphs, start=1):
        if p.text.strip():
            out.texts.append((f"para {i}", p.text.strip()))
    for ti, t in enumerate(d.tables, start=1):
        grid = [[c.text.strip() for c in row.cells] for row in t.rows]
        if len(grid) < 2:
            continue
        header = [h or f"col_{i + 1}" for i, h in enumerate(grid[0])]
        rows = [
            {h: _coerce(r[i]) if i < len(r) else None for i, h in enumerate(header)}
            for r in grid[1:]
        ]
        out.tables.append((f"{Path(name).stem}_table{ti}", f"table {ti}", header, rows))
    return out


def parse_eml(data: bytes, name: str) -> Parsed:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    out = Parsed()
    header = f"Subject: {msg.get('subject', '')}\nDate: {msg.get('date', '')}"
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    out.texts.append(("headers", header))
    for i, p in enumerate([p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()], 1):
        out.texts.append((f"body para {i}", p))
    attachments = [a.get_filename() for a in msg.iter_attachments()]
    if attachments:
        out.warnings.append(f"{name}: attachments not ingested: {attachments}")
    return out


PARSERS: dict[str, Callable[[bytes, str], Parsed]] = {
    ".csv": parse_csv,
    ".tsv": parse_csv,
    ".xlsx": parse_xlsx,
    ".xlsm": parse_xlsx,
    ".txt": parse_text,
    ".md": parse_text,
    ".vtt": parse_transcript,
    ".srt": parse_transcript,
    ".json": parse_json,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".eml": parse_eml,
}
