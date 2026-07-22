from __future__ import annotations
import logging
from app.ingestion.parser.base import Parser
from app.ingestion.types import ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)

class DoclingPdfParser(Parser):
    name = "docling"
    version = "docling-slim>=2.111" # temporarily

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat

        conv = DocumentConverter()

        import io
        from docling.document_converter import PdfFormatOption
        result = conv.convert(data)
        sections: list[ParsedSection] = []

        for item in result.document.iterate_items():
            sections.append(ParsedSection(text=item.text, page=item.page))
        return ParsedDocument(section=sections, parser=self.name,
                              parser_version=self.version, extraction_quality="high")

class PypdfFallbackParser(Parser):
    """Clearly-labelled degraded mode for born-digital PDFs when Docling fails."""
    name = "pypdf"
    version = "pypdf>=6.14"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        sections = [
            ParsedSection(text=(page.extract_text() or ""), page=i + 1)
            for i, page in enumerate(reader.pages)
        ]
        logger.warning("pypdf degraded fallback used for %s — no layout/OCR", filename)
        return ParsedDocument(
            sections=sections, parser=self.name,
            parser_version=self.version, extraction_quality="degraded",
        )

def parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    """ Docling primary, pydf explicit degraded fallback. Never Silent. """
    try:
        return DoclingPdfParser().parse(data=data, filename=filename)
    except Exception as exc:
        logger.exception("Dockling failed for %s: %s falling back to pypdf", filename, exc)
        return PypdfFallbackParser().parse(data, filename)
