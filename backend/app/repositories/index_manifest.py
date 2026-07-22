from __future__ import annotations
from uuid import UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import IndexManifest

class IndexManifestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, *, project_id: UUID, embed_model: str,
                     embed_dim: int, chunk_count: int) -> None:
        stmt = insert(IndexManifest).values(
            project_id=project_id,
            embed_model=embed_model,
            embed_dim=embed_dim,
            chunk_count=chunk_count,
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=[IndexManifest.project_id],
            set={
                "embed_model": stmt.excluded.embed_model,
                "embed_dim": stmt.excluded.embed_dim,
                "chunk_count": stmt.excluded.chunk_count,
            }
        )

        await self.session.execute(stmt)
