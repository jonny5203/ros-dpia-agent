from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectMembers


class ProjectMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project_id: UUID, user_id: UUID, role: str) -> ProjectMembers:
        member = ProjectMembers(project_id=project_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.flush()
        return member

    async def get(self, project_id: UUID, user_id: UUID) -> ProjectMembers | None:
        stmt = select(ProjectMembers).where(
            ProjectMembers.project_id == project_id,
            ProjectMembers.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_members_in_project(self, project_id: UUID) -> list[ProjectMembers]:
        stmt = select(ProjectMembers).where(ProjectMembers.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_all_members_for_projects(self, project_id: UUID) -> None:
        stmt = select(ProjectMembers).where(
            ProjectMembers.project_id == project_id
        )
        result = await self.session.execute(stmt)
        for member in result.scalars().all():
            await self.session.delete(member)
        await self.session.flush()

    async def delete_one_member_for_Project(self, project_id: UUID, user_id: UUID) -> None:
        stmt = select(ProjectMembers).where(
            ProjectMembers.project_id == project_id
        )
        result = await self.session.execute(stmt)
        for member in result.scalars().all():
            if member.user_id == user_id:
                await self.session.delete(member)
        await self.session.flush()
