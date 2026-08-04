"""Project-profile analysis endpoints."""

from __future__ import annotations

from uuid import UUID

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, get_arq_pool, get_project_context, get_session
from app.repositories.profile import ProfileRepository
from app.schemas.analysis import AnalysisJobResponse, AnalysisRequest
from app.schemas.profile import ProjectProfileRead
from app.services.analysis import AnalysisEnqueueError, AnalysisService

router = APIRouter(prefix="/v1/projects", tags=["analysis"])


@router.post(
    "/{project_id}/analyze",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_project(
    project_id: UUID,
    request: AnalysisRequest,
    project: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> AnalysisJobResponse:
    del project  # dependency enforces project membership before enqueueing
    try:
        job_id = await AnalysisService(session).enqueue(
            project_id=project_id,
            arq_pool=arq_pool,
            output_language=request.output_language,
        )
    except AnalysisEnqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis queue unavailable",
        ) from exc
    return AnalysisJobResponse(job_id=job_id)


@router.get("/{project_id}/profile", response_model=ProjectProfileRead)
async def get_profile(
    project_id: UUID,
    project: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> ProjectProfileRead:
    del project  # dependency enforces project membership before reading the profile
    profile = await ProfileRepository(session).get_latest_for_project(project_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return ProjectProfileRead.model_validate(profile)
