from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Projects


class ProjectRepository:
    def __init__(self, session:AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        name: str,
        description: str,
        owner_id: UUID,
        created_by: UUID,
        status: str,
        classification_id: UUID,
        embed_id: UUID,
        preferred_model: str,
    ) -> Projects:
        project = Projects(
            name=name,
            description=description,
            owner_id=owner_id,
            created_by=created_by,
            status=status,
            classification_id=classification_id,
            embed_id=embed_id,
            preferred_model=preferred_model,
        )
        self.session.add(project)
        await self.session.flush()
        return project

    async def get_by_id(self, project_id: UUID) -> Projects | None:
        return await self.session.get(Projects, project_id)

    async def list_all(self, user_id: UUID) -> list[Projects]:
        stmt = select(Projects).order_by(Projects.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_users(self, user_id: UUID) -> list[Projects]:
        stmt = (
            select(Projects)
            .where(Projects.owner_id == user_id)
            .order_by(Projects.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, project: Projects) -> None:
        await self.session.delete(project)
        await self.session.flush()

    async def update(self, project: Projects, **fields: object) -> Projects:
        for key, value in fields.items():
            setattr(project, key, value)
        await self.session.flush()
        return project

