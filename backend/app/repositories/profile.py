from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectProfiles


class ProfileRepository:
    """Persisted project profiles.

    One row per analysis run; the latest `created_at` for a project is the
    current profile surfaced by `GET /projects/{id}/profile`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        project_id: UUID,
        profile: dict,
        overall_confidence: str,
        model: str,
        prompt_version: str,
    ) -> ProjectProfiles:
        row = ProjectProfiles(
            project_id=project_id,
            profile=profile,
            overall_confidence=overall_confidence,
            model=model,
            prompt_version=prompt_version,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_latest_for_project(self, project_id: UUID) -> ProjectProfiles | None:
        stmt = (
            select(ProjectProfiles)
            .where(ProjectProfiles.project_id == project_id)
            .order_by(ProjectProfiles.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
