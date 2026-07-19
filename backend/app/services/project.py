from __future__ import annotations

import logging
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Projects
from app.repositories import DocumentRepository, LookupRepository, ProjectMemberRepository, ProjectRepository
from qdrant_client.http import models as qdrant_models
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

class ProjectService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageService,
        qdrant: AsyncQdrantClient | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.qdrant = qdrant
        self.projects = ProjectRepository(session)
        self.members = ProjectMemberRepository(session)
        self.documents = DocumentRepository(session)
        self.lookups = LookupRepository(session)

    async def create(
        self,
        name: str,
        description: str,
        owner_db_id: UUID,
        preferred_model: str,
        classification: str = "open",
    ) -> Projects:
        settings = get_settings()
        classification_id = await self.lookups.classification_id(classification)
        embed_id = await self.lookups.embed_id(settings.embed_model)

        project = await self.projects.create(
            name=name,
            description=description or "",
            owner_id=owner_db_id,
            created_by=owner_db_id,
            status="active",
            classification_id=classification_id,
            embed_id=embed_id,
            preferred_model=preferred_model,
        )

        await self.members.add(project.id, owner_db_id, "owner")

        if self.qdrant is not None:
            await self.qdrant.create_collection(
                collection_name=f"chunks_{project.id}",
                vectors_config={
                    "dense": qdrant_models.VectorParams(size=3072, distance=qdrant_models.Distance.COSINE)
                },
                sparse_vectors_config={
                    "bm25": qdrant_models.SparseVectorParams(index=qdrant_models.SparseIndexParams())
                },
            )

        await self.session.commit()
        return project

    async def delete(self, project_id: UUID) -> None:
        project = await self.projects.get_by_id(project_id)
        if project is None:
            return

        await self.storage.delete_prefix(f"projects/{project_id}/")

        docs = await self.documents.list_documents_for_projects(project_id)
        for doc in docs:
            await self.session.delete(doc)

        await self.members.delete_all_members_for_projects(project_id)
        await self.projects.delete(project)

        if self.qdrant is not None:
            await self.qdrant.delete_collection(f"chunks_{project_id}")

        await self.session.commit()

    async def list_for_user(self, user_id: UUID) -> list[Projects]:
        return await self.projects.list_for_users(user_id)

    async def get_by_id(self, project_id: UUID) -> Projects | None:
        return await self.projects.get_by_id(project_id)

    async def update(self, project_id: UUID, **fields: object) -> Projects | None:
        current_project = await self.projects.get_by_id(project_id)
        if current_project is None:
            return

        await self.projects.update(current_project, **fields)
        await self.session.commit()
