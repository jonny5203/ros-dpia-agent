"""Queue boundary for project-profile analysis jobs."""

from __future__ import annotations

from uuid import UUID

from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.profile import OutputLanguage
from app.repositories.job import JobRepository


class AnalysisEnqueueError(RuntimeError):
    """The analysis job row was created, but queue submission failed."""


class AnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.jobs = JobRepository(session)

    async def enqueue(
        self,
        *,
        project_id: UUID,
        arq_pool: ArqRedis,
        output_language: OutputLanguage = "nb",
    ) -> UUID:
        """Persist a pollable job before making it visible to the worker."""

        job = await self.jobs.create_job(
            project_id=project_id,
            kind="analyze_project",
        )
        await self.session.commit()

        try:
            arq_job = await arq_pool.enqueue_job(
                "analyze_project",
                job_id=str(job.id),
                project_id=str(project_id),
                output_language=output_language,
            )
            if arq_job is None:
                raise RuntimeError("queue rejected the analysis job")
        except Exception as exc:
            await self.session.rollback()
            persisted_job = await self.jobs.get_job(job.id)
            if persisted_job is not None:
                await self.jobs.update(
                    persisted_job,
                    status="failed",
                    error="Analysis could not be queued",
                )
                await self.session.commit()
            raise AnalysisEnqueueError("analysis could not be queued") from exc

        await self.jobs.update(job, arq_job_id=arq_job.job_id)
        await self.session.commit()
        return job.id
