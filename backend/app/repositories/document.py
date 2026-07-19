from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Documents


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        project_id: UUID,
        filename: str,
        mime: str,
        ext: str,
        sha256: str,
        classification_id: UUID,
        processing_status_id: UUID,
        uploaded_by: UUID,
    ) -> Documents:
        doc = Documents(
            project_id=project_id,
            filename=filename,
            mime=mime,
            ext=ext,
            # s3_key set after flush, when the doc id is known
            s3_key="",
            sha256=sha256,
            classification_id=classification_id,
            processing_status_id=processing_status_id,
            uploaded_by=uploaded_by,
        )
        self.session.add(doc)
        await self.session.flush()

        s3_key = f"projects/{project_id}/{doc.id}{ext}"
        doc.s3_key = s3_key
        await self.session.flush()
        return doc

    async def get_by_id(self, doc_id: UUID) -> Documents | None:
        return await self.session.get(Documents, doc_id)

    async def list_documents_for_projects(self, project_id: UUID) -> list[Documents]:
        stmt = select(Documents).where(Documents.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, doc: Documents) -> None:
        await self.session.delete(doc)
        await self.session.flush()

    async def get_doc_by_sha256(
        self, project_id: UUID, sha256: str
    ) -> Documents | None:
        stmt = select(Documents).where(
            Documents.project_id == project_id, Documents.sha256 == sha256
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
