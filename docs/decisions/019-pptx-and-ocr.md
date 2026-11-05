# 019 — PowerPoint ingestion and OCR for scanned PDFs

**Status:** accepted · 2026-11-05

- **PowerPoint (`.pptx`).** Text per slide (locator `slide N`), speaker notes (`slide N notes`)
  and tables (as tables, locator `slide N`). Uses python-pptx. Everything passes through the
  same PII scrubbing as other formats.
- **Scanned PDFs.** Pages without a text layer are OCR'd with Tesseract (German and English by
  default, `UNCLOG_OCR_LANGS`), rendered at 200 dpi with pypdfium2. Their locator is
  `page N (OCR)`, and the result carries a warning to check numbers against the original. OCR
  errors on digits are the main risk.
- **Requires the `tesseract` binary** on the machine (`apt-get install tesseract-ocr
  tesseract-ocr-deu`; CI installs it). Without it, or with `UNCLOG_OCR=0`, the old warning stays
  and nothing is guessed.
- Still not ingested: email attachments (listed in warnings), legacy `.ppt` and `.doc`, images
  outside PDFs.
