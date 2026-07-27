"""Chunker tests — deterministic IDs and token-budget invariants (acceptance §452)."""

from __future__ import annotations

from app.ingestion.chunker import chunk_document
from app.ingestion.types import ParsedDocument, ParsedSection

_DOC_ID = "11111111-1111-1111-1111-111111111111"
_PROJECT_ID = "22222222-2222-2222-2222-222222222222"


def test_re_chunking_same_doc_yields_identical_ids():
    """Same document_id → same chunk IDs → idempotent overwrite (§452)."""
    parsed = ParsedDocument(sections=[
        ParsedSection(text="of text " * 500, page=1, section_title="S1"),
    ])
    a = chunk_document(parsed, document_id=_DOC_ID, project_id=_PROJECT_ID)
    b = chunk_document(parsed, document_id=_DOC_ID, project_id=_PROJECT_ID)

    assert [c.id for c in a] == [c.id for c in b]
    assert len(a) > 0


def test_different_doc_yields_different_ids():
    """Different document_id → different chunk IDs (no cross-doc collision)."""
    other_doc = "33333333-3333-3333-3333-333333333333"
    parsed = ParsedDocument(sections=[ParsedSection(text="hello world", page=1)])
    a = chunk_document(parsed, document_id=_DOC_ID, project_id=_PROJECT_ID)
    b = chunk_document(parsed, document_id=other_doc, project_id=_PROJECT_ID)

    assert a[0].id != b[0].id


def test_chunk_index_is_sequential_within_document():
    parsed = ParsedDocument(sections=[
        ParsedSection(text=f"section {i} " * 200, section_title=f"S{i}")
        for i in range(5)
    ])
    chunks = chunk_document(parsed, document_id=_DOC_ID, project_id=_PROJECT_ID)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_empty_sections_are_skipped():
    parsed = ParsedDocument(sections=[
        ParsedSection(text="", page=1),
        ParsedSection(text="   ", page=2),
        ParsedSection(text="real content", page=3),
    ])
    chunks = chunk_document(parsed, document_id=_DOC_ID, project_id=_PROJECT_ID)
    assert len(chunks) == 1
    assert chunks[0].text == "real content"


def test_section_provenance_propagates_to_chunks():
    """Citation drill-down needs section_title + page on every chunk."""
    parsed = ParsedDocument(sections=[
        ParsedSection(text="body", page=42, section_title="Methods",
                      section_path="Intro > Methods"),
    ])
    chunk = chunk_document(parsed, document_id=_DOC_ID, project_id=_PROJECT_ID)[0]
    assert chunk.page == 42
    assert chunk.section_title == "Methods"
    assert chunk.section_path == "Intro > Methods"
