from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path
from app.ingestion.parsers.base import Parser
from app.ingestion.types import ParsedDocument, ParsedSection


class ImageParser(Parser):
    """Tesseract OCR with Norwegian+English; vision captioning is post-MVP."""
    name = "tesseract"
    version = "tesseract-nor+eng"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as f:
            f.write(data)
            f.flush()
            result = subprocess.run(
                ["tesseract", f.name, "-", "-l", "nor+eng"],
                capture_output=True, text=True, check=True,
            )
        return ParsedDocument(
            sections=[ParsedSection(text=result.stdout.strip(), page=1)],
            parser=self.name, parser_version=self.version,
        )
