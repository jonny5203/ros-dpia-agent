from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Projects, Screenings
from app.schemas.dpia import (
    DpiaEvidenceSnapshot,
    DpiaRunStatus,
)
from app.schemas.screening import DpiaScreeningResult


class InvalidDpiaRunTransition(RuntimeError):
    """A screening lifecycle transition violates the persistence contract."""


class ScreeningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        rules_version: str,
        requested_by: UUID | None,
    ) -> Screenings:
        clean_rules_version = rules_version.strip()
        if not clean_rules_version:
            raise ValueError("rules_version must not be blank")

        project_lock = select(Projects.id).where(Projects.id == project_id).with_for_update()
        locked_project_id = await self.session.scalar(project_lock)
        if locked_project_id is None:
            raise ValueError("project does not exist")

        next_version_statement = select(func.coalesce(func.max(Screenings.version), 0) + 1).where(
            Screenings.project_id == project_id
        )

        next_version = await self.session.scalar(next_version_statement)

        if not isinstance(next_version, int):
            raise RuntimeError("could not allocate screening version")

        run = Screenings(
            project_id=project_id,
            requested_by=requested_by,
            job_id=job_id,
            version=next_version,
            status=DpiaRunStatus.PENDING.value,
            rules_version=clean_rules_version,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_for_project(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> Screenings | None:
        statement = select(Screenings).where(
            Screenings.id == run_id,
            Screenings.project_id == project_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_latest_for_project(
        self,
        project_id: UUID,
    ) -> Screenings | None:
        """Return the newest persisted run belonging to exactly one project."""

        statement = (
            select(Screenings)
            .where(Screenings.project_id == project_id)
            .order_by(Screenings.version.desc())
            .limit(1)
        )

        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: UUID,
    ) -> list[Screenings]:
        statement = (
            select(Screenings)
            .where(Screenings.project_id == project_id)
            .order_by(Screenings.version.desc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def mark_running(
        self,
        run: Screenings,
    ) -> Screenings:
        self._require_status(run, DpiaRunStatus.PENDING)
        run.status = DpiaRunStatus.RUNNING.value
        await self.session.flush()
        return run

    async def store_snapshot(
        self,
        run: Screenings,
        snapshot: DpiaEvidenceSnapshot,
    ) -> Screenings:
        self._require_status(run, DpiaRunStatus.RUNNING)
        if run.evidence_snapshot is not None:
            raise InvalidDpiaRunTransition("screening evidence snapshot is immutable")
        if snapshot.project_id != run.project_id:
            raise InvalidDpiaRunTransition("screening snapshot belongs to another project")

        run.evidence_snapshot = snapshot.model_dump(mode="json")
        await self.session.flush()
        return run

    async def complete(
        self,
        run: Screenings,
        *,
        result: DpiaScreeningResult,
        model: str,
        prompt_version: str,
    ) -> Screenings:
        self._require_status(run, DpiaRunStatus.RUNNING)
        if run.evidence_snapshot is None:
            raise InvalidDpiaRunTransition("screening cannot complete without an evidence snapshot")
        if run.result is not None:
            raise InvalidDpiaRunTransition("screening result is immutable")

        clean_model = model.strip()
        clean_prompt_version = prompt_version.strip()
        if not clean_model:
            raise ValueError("model must not be blank")
        if not clean_prompt_version:
            raise ValueError("prompt_version must not be blank")

        run.result = result.model_dump(mode="json")
        run.conclusion = result.conclusion.value
        run.model = clean_model
        run.prompt_version = clean_prompt_version
        run.error = None
        run.status = DpiaRunStatus.READY_FOR_REVIEW.value
        await self.session.flush()
        return run

    async def fail(
        self,
        run: Screenings,
        *,
        error: str,
    ) -> Screenings:
        self._require_status(
            run,
            DpiaRunStatus.PENDING,
            DpiaRunStatus.RUNNING,
        )
        if run.result is not None:
            raise InvalidDpiaRunTransition("completed screening cannot be failed")

        clean_error = error.strip()
        if not clean_error:
            raise ValueError("failed screening requires an error")

        run.result = None
        run.conclusion = None
        run.model = None
        run.prompt_version = None
        run.error = clean_error
        run.status = DpiaRunStatus.FAILED.value
        await self.session.flush()
        return run

    @staticmethod
    def _require_status(
        run: Screenings,
        *allowed: DpiaRunStatus,
    ) -> None:
        allowed_values = {status.value for status in allowed}
        if run.status not in allowed_values:
            expected = ", ".join(sorted(allowed_values))
            raise InvalidDpiaRunTransition(f"screening status must be one of: {expected}")
