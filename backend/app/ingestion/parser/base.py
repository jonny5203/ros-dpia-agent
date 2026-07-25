from __future__ import annotations

from app.ingestion.types import ParsedDocument

class Parser:
    """Common contract for every format parser.

    Each subclass exposes `name`, `version` (preserved into document metadata
    so extraction provenance is auditable), and a synchronous `parse` that
    turns raw bytes into a ParsedDocument. Parsers are deliberately sync —
    Docling/python-docx/openpyxl are blocking CPU work, and the arq worker
    runs them off the event loop via `run_in_executor`.
    """

    name: str = ""
    version: str = ""

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        raise NotImplementedError
