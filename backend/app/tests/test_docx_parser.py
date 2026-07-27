from __future__ import annotations

import io

from docx import Document

from app.ingestion.parser.docx import DocxParser

def _docx_bytes(paragraphs: list[tuple[str, str]]):
    """ Build a DOCX in memory from (style, text) pairs. """
    doc = Document()
    for style, text in paragraphs:
        p = doc.add_paragraph(text, style=style)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

def test_norwegian_headings_create_section_path():
    paragraphs = [
        ("Heading 1", "Innledning"),
        ("Normal", "Dette er en test av systemet."),
        ("Heading 2", "Bakgrunn"),
        ("Normal", "Kommunen har behov for ROS."),
    ]

    parsed = DocxParser().parse(_docx_bytes(paragraphs), "test.docx")

    assert parsed.parser == "python-docx"
    assert len(parsed.sections) == 2
    s1, s2 = parsed.sections
    assert s1.text == "Dette er en test av systemet."
    assert s1.section_title == "Innledning"
    assert s1.section_path == "Innledning"
    assert s2.text == "Kommunen har behov for ROS."
    assert s2.section_title == "Bakgrunn"
    assert s2.section_path == "Innledning > Bakgrunn"
