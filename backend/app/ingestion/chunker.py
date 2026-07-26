from __future__ import annotations

import hashlib
from uuid import NAMESPACE_URL, uuid5

from app.ingestion.types import Chunk, ParsedDocument, ParsedSection

CHUNK_NAMESPACE = uuid5(NAMESPACE_URL, "kommune-dpia-chunks")

CHUNK_TOKENS = 800
CHUNK_OVERLAP = 150

def _encoder_for(model: str) -> "tiktoken.Encoding":
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")

def _split_section(section: ParsedSection, enc) -> list[tuple[int, int, str]]:
    """ Recursively splut one section by tokens. Returns (char_start, char_end, text)
    truples expressed in *section-loca* cxharacter offsets. """

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=CHUNK_TOKENS,
        chunk_overlap=CHUNK_OVERLAP,
    )

    pieces = splitter.split_text(section.text)
    out: list[tuple[int, int, str]] = []
    cursor = 0
    for piece in pieces:
        start = section.text.find(piece, cursor)
        if start == -1:
            start = cursor
        end = start + len(piece)
        cursor = end
        out.append((start, end, piece))
    return out

def chunk_document(parsed: ParsedDocument, *, document_id, project_id) -> list[Chunk]:
    """ Turn a ParsedDocument into deterministic, citation-bearing Chunks.

    structural: one section → 1..N chunks (preserves section_title/path/page)
    deterministic IDs: uuid5(CHUNK_NAMESPACE, f"{document_id}:{chunk_index}")
      so the same bytes on re-upload overwrite the same rows/Qdrant points.
    """

    enc = _encoder_for("")  # encoding is fixed; model arg kept for future swap
    chunks: list[Chunk] = []
    idx = 0

    for section in parsed.sections:
        if not section.text.strip():
            continue
        for char_start, char_end, text in _split_section(section, enc):
            sha8 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
            chunk_id = str(uuid5(CHUNK_NAMESPACE, f"{document_id}:{idx}"))
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=text,
                    chunk_index=idx,
                    page=section.page,
                    section_title=section.section_title,
                    section_path=section.section_path,
                    char_start=char_start,
                    char_end=char_end,
                    sha8=sha8,
                )
            )
            idx += 1
    return chunks


