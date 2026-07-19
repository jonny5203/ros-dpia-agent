from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Classification, Embed, ProcessingStatus


class LookupRepository:
    """Resolves normalized lookup-table names to their UUIDs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def classification_id(self, name: str) -> UUID:
        stmt = select(Classification.id).where(Classification.name == name)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"Classification: '{name}' not found")
        return row

    async def embed_id(self, model:str) -> UUID:
        stmt = select(Embed.id).where(Embed.model == model)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"Model: '{model}' not found")
        return row

    async def processing_status_id(self, name: str) -> UUID:
        stmt = select(ProcessingStatus.id).where(ProcessingStatus.name == name)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"Name: '{name}' not found")
        return row
