from __future__ import annotations

import io
from email.message import EmailMessage

import pytest

from unclog.schemas import Evidence, EvidenceType


@pytest.fixture
def ev():
    def make(type_: EvidenceType = EvidenceType.log_data, i: int = 1) -> Evidence:
        return Evidence(id=f"ev{i}", source_id="src1", type=type_, locator="row 1-40")

    return make


CRM_CSV = (
    "Lead ID;Name;E-Mail;Created;First Response (h);Stage\n"
    "L-1001;Anna Schmidt;anna@acme.de;2026-10-01;52;Contacted\n"
    "L-1002;Ben Ott;ben@ott.de;2026-10-02;71.5;New\n"
    "L-1003;Cara Wu;cara@wu.io;2026-10-02;;New\n"
).encode("cp1252")

EVENTS_CSV = (
    b"ticket_id,activity,timestamp,assignee\n"
    b"T-1,created,2026-10-01T09:00:00,bot\n"
    b"T-1,tier2_approval,2026-10-04T11:00:00,Mara\n"
    b"T-2,created,2026-10-01T10:00:00,bot\n"
    b"T-1,closed,2026-10-04T12:00:00,Mara\n"
)

VTT = b"""WEBVTT

00:00:01.000 --> 00:00:05.000
Interviewer: Where does work pile up?

00:00:05.500 --> 00:00:12.000
COO: Refund tickets wait for the three Tier-2 approvers, usually three days.
"""


def make_xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(["Month", "Leads", "Booked"])
    ws.append(["2026-09", 410, 38])
    ws.append(["2026-10", 455, 41])
    ws2 = wb.create_sheet("Notes")
    ws2.append(["Note"])
    ws2.append(["contact: ops@client.de"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_docx() -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph("Refund SOP v3")
    d.add_paragraph(
        "Every refund above 50 EUR needs Tier-2 sign-off. Batches are reviewed Fridays."
    )
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Step", "Owner"
    t.cell(1, 0).text, t.cell(1, 1).text = "Approve", "Tier-2"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pdf(text: str = "Weekly approval batch policy") -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def make_eml() -> bytes:
    m = EmailMessage()
    m["Subject"] = "Re: refund backlog"
    m["From"] = "coo@client.de"
    m["Date"] = "Mon, 02 Nov 2026 09:00:00 +0100"
    m.set_content("We are 410 tickets behind.\n\nCall me on +49 171 2345678.")
    m.add_attachment(b"x", maintype="application", subtype="octet-stream", filename="dump.bin")
    return m.as_bytes()


@pytest.fixture
def upload_dir(tmp_path):
    d = tmp_path / "uploads"
    (d / "crm").mkdir(parents=True)
    (d / "crm" / "leads.csv").write_bytes(CRM_CSV)
    (d / "ticket_events.csv").write_bytes(EVENTS_CSV)
    (d / "interview_coo.vtt").write_bytes(VTT)
    (d / "funnel.xlsx").write_bytes(make_xlsx())
    (d / "refund_sop.docx").write_bytes(make_docx())
    (d / "policy.pdf").write_bytes(make_pdf())
    (d / "mail.eml").write_bytes(make_eml())
    (d / "deck.pptx").write_bytes(b"not supported yet")
    (d / ".DS_Store").write_bytes(b"")
    return d
