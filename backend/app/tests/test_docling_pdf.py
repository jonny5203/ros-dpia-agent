"""Integration test: Docling parses a born-digital PDF with a table.

Generates the PDF in-memory with reportlab so the test is self-contained.
Marked slow because Docling model load takes ~5s cold.

Skips if reportlab is not installed (dev-only dependency) or if Docling's
models aren't available (CI without the model cache).
"""

from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.slow

reportlab = pytest.importorskip("reportlab")


@pytest.fixture
def born_digital_pdf_with_table() -> bytes:
    """A minimal PDF with text + a simple table, generated in-memory."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [["System", "Leverandør"], ["Azure OpenAI", "Microsoft"]]
    table = Table(data)
    table.setStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])
    doc.build([
        Paragraph("Behandlingsoversikt", styles["Heading1"]),
        Paragraph("Dette er en test av PDF-parsing.", styles["Normal"]),
        table,
    ])
    return buf.getvalue()


def test_docling_extracts_text_and_table(born_digital_pdf_with_table):
    """Docling parses the heading + body + table cells without silent failure."""
    from app.ingestion.parser.pdf import DoclingPdfParser

    parsed = DoclingPdfParser().parse(born_digital_pdf_with_table, "test.pdf")
    assert parsed.parser == "docling"
    assert parsed.extraction_quality == "high"
    # The combined text should include at least one cell from the table.
    combined = " ".join(s.text for s in parsed.sections)
    assert "Azure OpenAI" in combined or "Microsoft" in combined
    assert len(parsed.sections) > 0


def test_docling_records_page_provenance(born_digital_pdf_with_table):
    """Citations need page numbers; Docling must preserve them."""
    from app.ingestion.parser.pdf import DoclingPdfParser

    parsed = DoclingPdfParser().parse(born_digital_pdf_with_table, "test.pdf")
    # At least one section should carry a page number.
    assert any(s.page is not None for s in parsed.sections)


def test_docling_records_parser_version(born_digital_pdf_with_table):
    """Parser version travels into document metadata for audit (§441)."""
    from app.ingestion.parser.pdf import DoclingPdfParser

    parsed = DoclingPdfParser().parse(born_digital_pdf_with_table, "test.pdf")
    assert parsed.parser_version.startswith("docling")
