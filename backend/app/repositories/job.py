from __future__ import annotations
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Jobs

class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_job(self, *, project_id: UUID | None, kind: str, arq_job_id: str):
        job = Jobs(project_id=project_id, kind=kind, status="queued", arq_job_id=arq_job_id, process_pct=0)
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job(self, job_id: UUID) -> Jobs | None:
        return await self.session.get(Jobs, job_id)

    async def update(self, job: Jobs, **fileds: object) -> Jobs:
        for k, v in fileds.items():
            setattr(job, k, v)
        await self.session.flush()
        return job
