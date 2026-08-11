from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentFindings


class FindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_insert_findings(self, finding: list[DocumentFindings]) -> None:
        self.session.add_all(finding)
        await self.session.flush()

    async def list_findings_for_document(self, document_id: UUID) -> list[DocumentFindings]:
        stmt = select(DocumentFindings).where(DocumentFindings.document_id == document_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete_findings_for_document(self, document_id: UUID) -> None:
        stmt = select(DocumentFindings).where(DocumentFindings.document_id == document_id)
        rows = await self.session.execute(stmt)
        read_result = rows.scalars().all()

        for rr in read_result:
            await self.session.delete(rr)

        await self.session.flush()
