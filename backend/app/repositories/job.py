from __future__ import annotations
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Jobs

class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(
        self,
        *,
        project_id: UUID,
        kind: str,
        arq_job_id: str | None = None,
    ) -> Jobs:
        job = Jobs(
            project_id=project_id,
            kind=kind,
            status="queued",
            arq_job_id=arq_job_id,
            progress_pct=0,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: UUID) -> Jobs | None:
        return await self.session.get(Jobs, job_id)

    async def update(self, job: Jobs, **fields: object) -> Jobs:
        for key, value in fields.items():
            setattr(job, key, value)
        await self.session.flush()
        return job
