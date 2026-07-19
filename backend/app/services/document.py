from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Documents
from app.repositories.document import DocumentRepository
from app.repositories.lookup import LookupRepository
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".png"}

class DocumentService:
    def __init__(self, session: AsyncSession, storage: StorageService):
        self.session = session
        self.storage = storage
        self.documents = DocumentRepository(session)
        self.lookups = LookupRepository(session)

    async def upload(
        self,
        project_id: UUID,
        filename: str,
        content: bytes,
        uploaded_by: UUID,
        classification: str = "open",
    ) -> Documents:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"File type '{ext}' not allowed")

        sha256 = hashlib.sha256(content).hexdigest()
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        existing = await self.documents.get_doc_by_sha256(project_id, sha256)
        if existing:
            return existing

        classification_id = await self.lookups.classification_id(classification)
        status_id = await self.lookups.processing_status_id("pending")

        doc = await self.documents.create(
            project_id=project_id,
            filename=filename,
            mime=mime,
            ext=ext,
            sha256=sha256,
            classification_id=classification_id,
            processing_status_id=status_id,
            uploaded_by=uploaded_by,
        )

        await self.storage.put(doc.s3_key, content, mime)
        await self.session.commit()
        return doc

    async def list_for_project(self, project_id: UUID) -> list[Documents]:
        return await self.documents.list_documents_for_projects(project_id)

    async def delete(self, doc_id: UUID, project_id: UUID) -> None:
        doc = await self.documents.get_by_id(doc_id)
        if doc is None or doc.project_id != project_id:
            return
        if doc.s3_key:
            await self.storage.delete(doc.s3_key)

        await self.documents.delete(doc)
        await self.session.commit()
