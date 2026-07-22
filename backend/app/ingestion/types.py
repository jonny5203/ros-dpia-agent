from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ParsedSection:
    """ A paper or heading bounded block of text from a parser """
    text: str
    page: int | None = None
    section_title: str | None = None
    section_path: str | None = None

@dataclass
class ParsedDocument:
    sections: list[ParsedSection] = field(default_factory=list)
    parser: str = ""
    parser_version: str = ""
    extraction_quality: str = "high"

@dataclass
class Finding:
    type: str
    category: str
    severity: str
    count: int
    sample_offsets: list[tuple[int, int]]
    checksum_valid: bool | None = None

@dataclass
class Chunk:
    """ Output of the chunker. The chunk.id is uuid5, set in chunker, not here. """
    id: str
    text: str
    chunk_index: int
    page: int | None
    section_title: int
    section_path: str | None
    char_start: int
    char_end: int
    sha8: str
