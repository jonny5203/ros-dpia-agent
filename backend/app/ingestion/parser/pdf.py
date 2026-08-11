from __future__ import annotations

import io
import logging

from app.ingestion.parser.base import Parser
from app.ingestion.types import ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)


class DoclingPdfParser(Parser):
    """Primary PDF parser: layout + reading-order + table + OCR extraction.

    Uses docling-slim with the rapidocr-onnx local OCR extra. Model artifacts
    are pinned via docling's own versioning; first run downloads them.
    """

    name = "docling"
    version = "docling-slim>=2.111"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        # Imported lazily so the module imports cleanly in tests that don't
        # need Docling's (heavy) torch stack.
        from docling.document_converter import DocumentConverter
        from docling_core.types.io import DocumentStream

        doc_stream = DocumentStream(
            name=filename or "input.pdf",
            stream=io.BytesIO(data),
        )
        conv = DocumentConverter()
        result = conv.convert(doc_stream)
        dl_doc = result.document

        sections: list[ParsedSection] = []
        # export_to_markdown preserves heading hierarchy as "#"/"##"; keep
        # page numbers from the items for citation. iterate_items() yields
        # elements with .text and a page provenance.
        for item, _level in dl_doc.iterate_items():
            page_no = None
            prov = getattr(item, "prov", None)
            if prov:
                page_no = prov[0].page_no if isinstance(prov, list) else prov.page_no
            text = getattr(item, "text", None) or ""
            if text.strip():
                sections.append(ParsedSection(text=text.strip(), page=page_no))

        return ParsedDocument(
            sections=sections,
            parser=self.name,
            parser_version=self.version,
            extraction_quality="high",
        )


class PypdfFallbackParser(Parser):
    """Clearly-labelled degraded fallback for born-digital PDFs.

    Text-only, no layout/reading-order/OCR. Always flagged `extraction_quality
    ="degraded"` so the UI can badge it — never silent.
    """

    name = "pypdf"
    version = "pypdf>=6.14"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        sections = [
            ParsedSection(text=(page.extract_text() or ""), page=i + 1)
            for i, page in enumerate(reader.pages)
        ]
        logger.warning("pypdf degraded fallback used for %s — no layout/OCR", filename)
        return ParsedDocument(
            sections=sections,
            parser=self.name,
            parser_version=self.version,
            extraction_quality="degraded",
        )


def parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    """Docling primary; pypdf explicit degraded fallback. Never silent."""
    try:
        return DoclingPdfParser().parse(data, filename)
    except Exception as exc:
        logger.exception("Docling failed for %s (%s); falling back to pypdf", filename, exc)
        return PypdfFallbackParser().parse(data, filename)
