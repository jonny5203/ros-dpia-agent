from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunks


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_insert(self, chunks: list[Chunks]) -> None:
        self.session.add_all(chunks)
        await self.session.flush()

    async def delete_for_document(self, document_id: UUID) -> None:
        stmt = select(Chunks).where(Chunks.document_id == document_id)
        rows = await self.session.execute(stmt)

        for row in rows:
            await self.session.delete(row)
        await self.session.flush()

    async def get(self, chunk_id: UUID) -> Chunks | None:
        return await self.session.get(Chunks, chunk_id)
