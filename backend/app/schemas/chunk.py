from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class ChunkRef(BaseModel):
    """ Model that references a chunk passed back from RAF queries """
    chunkId: UUID
    documentId: UUID
    documentName: str | None = None
    page: int | None = None
    sectionTitle: str | None = None

class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    chunk_index: int
    page: int | None
    section_title: str | None
    section_path: str | None
    char_start: int
    char_end: int
    sha8: str
    text: str
