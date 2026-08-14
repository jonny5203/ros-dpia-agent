"""Create pollable jobs and linked DPIA run versions before queue submission."""

from __future__ import annotations

from uuid import UUID

from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dpia import DPIA_RULES_VERSION
from app.repositories.dpia import ScreeningRepository
from app.repositories.job import JobRepository
from app.schemas.dpia import DpiaRunAccepted, DpiaRunStatus

DPIA_JOB_KIND = "run_dpia_screening"
DPIA_QUEUE_FAILURE_ERROR = "DPIA screening could not be queued"


class DpiaRunEnqueueError(RuntimeError):
    """The persisted DPIA run could not be submitted to the worker queue."""


class DpiaRunService:
    """Creates one job and one linked DPIA screening run.

    The service commits both rows before giving their identifiers to arq. If
    queue submission fails, it records a safe failure on both persisted rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.jobs = JobRepository(session)
        self.screenings = ScreeningRepository(session)

    async def enqueue_dpia_run(
        self,
        *,
        project_id: UUID,
        requested_by: UUID,
        arq_pool: ArqRedis,
    ) -> DpiaRunAccepted:
        """Persist one run and job before submitting their identifiers to arq."""

        job = await self.jobs.create_job(
            project_id=project_id,
            kind=DPIA_JOB_KIND,
        )
        run = await self.screenings.create_pending(
            project_id=project_id,
            job_id=job.id,
            rules_version=DPIA_RULES_VERSION,
            requested_by=requested_by,
        )

        job_id = job.id
        run_id = run.id
        version = run.version

        # worker must never receive identifiers for rows that are not committed
        await self.session.commit()

        try:
            queued_job = await arq_pool.enqueue_job(
                DPIA_JOB_KIND,
                job_id=str(job_id),
                run_id=str(run_id),
                project_id=str(project_id),
            )
            if queued_job is None:
                raise RuntimeError("queue rejected the DPIA screening job")
        except Exception as exc:
            await self.session.rollback()

            persisted_job = await self.jobs.get_job(job_id)
            persisted_run = await self.screenings.get_for_project(
                project_id=project_id,
                run_id=run_id,
            )
            state_changed = False

            if persisted_run is not None and persisted_run.status in {
                DpiaRunStatus.PENDING.value,
                DpiaRunStatus.RUNNING.value,
            }:
                await self.screenings.fail(
                    persisted_run,
                    error=DPIA_QUEUE_FAILURE_ERROR,
                )
                state_changed = True

            if persisted_job is not None:
                await self.jobs.update(
                    persisted_job,
                    status="failed",
                    error=DPIA_QUEUE_FAILURE_ERROR,
                )
                state_changed = True

            if state_changed:
                await self.session.commit()

            raise DpiaRunEnqueueError("DPIA screening could not be queued") from exc

        await self.jobs.update(
            job,
            arq_job_id=queued_job.job_id,
        )
        await self.session.commit()

        return DpiaRunAccepted(
            run_id=run_id,
            job_id=job_id,
            version=version,
        )
