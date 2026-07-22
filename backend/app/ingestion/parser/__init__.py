from __future__ import annotations
from app.ingestion.types import ParsedDocument
from .pdf import parse_pdf
from .docx import DocxParser
from .xlsx import XlsxParser
from .markdown import MarkdownParser
from .image import ImageParser

_PARSERS = {
    ".pdf": lambda b, f: parse_pdf(b, f),
    ".docx": DocxParser().parse,
    ".xlsx": XlsxParser().parse,
    ".md":   MarkdownParser().parse,
    ".png":  ImageParser().parse,
}


def parse(data: bytes, ext: str, filename: str) -> ParsedDocument:
    parser = _PARSERS.get(ext.lower())
    if parser is None:
        raise ValueError(f"No parser for extension '{ext}'")
    return parser(data, filename)
