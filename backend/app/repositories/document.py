from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
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

    async def set_status(self, doc: Documents, status_id: UUID) -> None:
        doc.processing_status_id = status_id
        await self.session.flush()

    async def set_max_severity(self, doc: Documents, severity: str | None,
                               lexicon_version: str | None) -> None:
        doc.max_severity = severity
        doc.lexicon_version = lexicon_version
        await self.session.flush()

    async def acknowledge(self, doc: Documents, user_id: UUID) -> None:
        doc.acked_by = user_id
        doc.acked_at = func.now()
        await self.session.flush()

    async def filenames_by_ids(
        self,
        project_id: UUID,
        document_ids: set[UUID],
    ) -> dict[UUID, str]:
        if not document_ids:
            return {}

        stmt = select(Documents.id, Documents.filename).where(
            Documents.project_id == project_id,
            Documents.id.in_(document_ids)
        )
        result = await self.session.execute(stmt)
        # returns document_id as key and filename as value
        return {document_id: filename for document_id, filename in result.all()}
