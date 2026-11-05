import io
import shutil

import pytest

from unclog.ingestion import ingest_bytes
from unclog.ingestion.parsers import ocr_available


def make_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Auftragsrückstand Q3"
    s1.placeholders[1].text = "64 Aufträge warten auf die Werkstatt. Kontakt: chef@firma.de"
    s1.notes_slide.notes_text_frame.text = "Samstagsarbeit seit August."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Zahlen"
    tbl = s2.shapes.add_table(3, 2, Inches(1), Inches(2), Inches(6), Inches(1.5)).table
    for r, (a, b) in enumerate([("Monat", "Aufträge"), ("Sep", "88"), ("Okt", "94")]):
        tbl.cell(r, 0).text, tbl.cell(r, 1).text = a, b
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_scanned_pdf(text: str) -> bytes:
    """An image-only PDF (no text layer), like a scanned page."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1700, 600), "white")
    font = ImageFont.load_default(size=56)
    ImageDraw.Draw(img).multiline_text((60, 80), text, fill="black", font=font, spacing=24)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=200)
    return buf.getvalue()


def test_pptx_slides_tables_notes_scrubbed():
    r = ingest_bytes(make_pptx(), "rueckstand.pptx")
    loc = {c.locator: c.text for c in r.chunks}
    assert "64 Aufträge warten" in loc["slide 1"] and "[EMAIL]" in loc["slide 1"]
    assert loc["slide 1 notes"] == "Samstagsarbeit seit August."
    assert r.tables[0].locator == "slide 2"
    assert r.tables[0].rows == [{"Monat": "Sep", "Aufträge": 88}, {"Monat": "Okt", "Aufträge": 94}]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_scanned_pdf_is_ocred():
    assert ocr_available()
    pdf = make_scanned_pdf("Freigabe nur freitags\nRueckstand 64 Auftraege")
    r = ingest_bytes(pdf, "scan.pdf")
    assert r.chunks and r.chunks[0].locator == "page 1 (OCR)"
    text = r.chunks[0].text.lower()
    assert "freitags" in text and "64" in text
    assert any("OCR used" in w for w in r.warnings)


def test_ocr_can_be_disabled(monkeypatch):
    monkeypatch.setenv("UNCLOG_OCR", "0")
    r = ingest_bytes(make_scanned_pdf("nichts"), "scan.pdf")
    assert not r.chunks and any("install tesseract" in w for w in r.warnings)
