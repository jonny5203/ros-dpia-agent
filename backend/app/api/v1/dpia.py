"""Create and read project-scoped DPIA screening runs."""

from __future__ import annotations

from uuid import UUID

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    ProjectContext,
    get_arq_pool,
    get_project_context,
    get_session,
    require_role,
)
from app.auth.models import AppRole
from app.repositories.dpia import ScreeningRepository
from app.schemas.dpia import DpiaRunAccepted, DpiaScreeningRunRead
from app.services.dpia_runs import DpiaRunEnqueueError, DpiaRunService

router = APIRouter(prefix="/v1/projects", tags=["dpia"])

_DPIA_RUN_START_ROLES = (
    AppRole.PROJECT_MANAGER,
    AppRole.PRIVACY_OFFICER,
    AppRole.ADMIN,
)


@router.post(
    "/{project_id}/dpia/runs",
    response_model=DpiaRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_dpia_run(
    project_id: UUID,
    project: ProjectContext = Depends(get_project_context),
    starter: CurrentUser = Depends(require_role(*_DPIA_RUN_START_ROLES)),
    session: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> DpiaRunAccepted:
    """Persist and enqueue a new immutable DPIA run version."""

    del starter  # the dependency enforces the allowed application roles

    try:
        return await DpiaRunService(session).enqueue_dpia_run(
            project_id=project_id,
            requested_by=project.user_db_id,
            arq_pool=arq_pool,
        )
    except DpiaRunEnqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DPIA screening queue unavailable",
        ) from exc


@router.get(
    "/{project_id}/dpia/runs/latest",
    response_model=DpiaScreeningRunRead,
)
async def get_latest_dpia_run(
    project_id: UUID,
    project: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> DpiaScreeningRunRead:
    """Return the newest persisted DPIA run for the authorized project."""

    del project
    run = await ScreeningRepository(session).get_latest_for_project(project_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DPIA run not found")
    return DpiaScreeningRunRead.model_validate(run)


@router.get(
    "/{project_id}/dpia/runs/{run_id}",
    response_model=DpiaScreeningRunRead,
)
async def get_dpia_run(
    project_id: UUID,
    run_id: UUID,
    project: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> DpiaScreeningRunRead:
    """Return one run only when it belongs to the authorized project."""

    del project

    run = await ScreeningRepository(session).get_for_project(
        project_id=project_id,
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DPIA run not found")

    return DpiaScreeningRunRead.model_validate(run)
