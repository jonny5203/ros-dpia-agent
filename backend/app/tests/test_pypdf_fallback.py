"""Tests that the pypdf fallback is clearly labelled as degraded (§453).

Builds minimal valid PDFs in memory with pypdf's PdfWriter rather than shipping
binary fixtures, so the test is self-contained and self-documenting.
"""

from __future__ import annotations

import io

from app.ingestion.parser.pdf import PypdfFallbackParser, parse_pdf


def _make_blank_pdf(num_pages: int = 1) -> bytes:
    """Build a minimal valid PDF with N blank pages.

    Blank pages yield empty extract_text() — fine for testing the parser shape
    (extraction_quality badge, page-number provenance), not extraction correctness.
    """
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pypdf_parser_marks_quality_degraded():
    """The pypdf parser always sets extraction_quality='degraded' (§453 'never silent')."""
    parsed = PypdfFallbackParser().parse(_make_blank_pdf(), "x.pdf")
    assert parsed.parser == "pypdf"
    assert parsed.extraction_quality == "degraded"


def test_pypdf_fallback_is_used_when_docling_fails(monkeypatch):
    """parse_pdf falls back to pypdf when Docling raises."""
    pdf_bytes = _make_blank_pdf()

    # Force DoclingPdfParser.parse to raise, simulating a Docling failure.
    from app.ingestion.parser import pdf as pdf_module

    def _boom(self, data, filename):
        raise RuntimeError("docling unavailable in test")

    monkeypatch.setattr(pdf_module.DoclingPdfParser, "parse", _boom)

    result = parse_pdf(pdf_bytes, "test.pdf")
    assert result.parser == "pypdf"
    assert result.extraction_quality == "degraded"


def test_pypdf_preserves_page_numbers():
    """Each PDF page becomes a ParsedSection with page=i+1."""
    parsed = PypdfFallbackParser().parse(_make_blank_pdf(num_pages=3), "multi.pdf")
    assert len(parsed.sections) == 3
    assert [s.page for s in parsed.sections] == [1, 2, 3]


def test_pypdf_records_parser_version():
    """Parser version travels into document metadata for audit (§441)."""
    parsed = PypdfFallbackParser().parse(_make_blank_pdf(), "x.pdf")
    assert parsed.parser_version.startswith("pypdf")
