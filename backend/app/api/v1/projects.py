from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from qdrant_client import AsyncQdrantClient

from app.api.deps import CurrentUser, get_current_user, get_session, get_storage, get_qdrant
from app.core.config import get_settings
from app.db.models import Projects
from app.repositories.user import UserRepository
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project import ProjectService
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["projects"])

def _to_read(project: Projects) -> ProjectRead:
    settings = get_settings()
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.status,
        classification="open",
        embed_model=settings.embed_model,
        embed_dim=settings.embed_dim,
        preferred_model=project.preferred_model,
        created_at=project.created_at,
        created_by=project.created_by
    )

@router.post("", response_model=ProjectRead, status_code=201)
async def create_project(
    dto: ProjectCreate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
    qdrant: AsyncQdrantClient = Depends(get_qdrant),
) -> ProjectRead:
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.sub)
    if db_user is None:
        raise HTTPException(status_code=403, detail="User not registered")

    settings = get_settings()
    svc = ProjectService(session, storage, qdrant=qdrant)
    project = await svc.create(
        name=dto.name,
        description=dto.description or "",
        owner_db_id=db_user.id,
        preferred_model=dto.dto.preferred_model or settings.llm_model,
        classification=dto.classification
    )
    return _to_read(project)

@router.post("", response_model=list[ProjectRead])
async def list_project(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
) -> list[ProjectRead]:
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.id)
    if db_user is None:
        return

    svc = ProjectService(session, storage)
    projects = await svc.list_for_user(db_user.id)
    return [_to_read(p) for p in projects]

@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
) -> ProjectRead:
    svc = ProjectService(session, storage)
    project = await svc.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.sub)
    if db_user is None or project.owner_id != db_user.id:
        if not user.is_admin:
            raise HTTPException(status_code=404, detail="Project not found")
    return _to_read(project)



@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID,
    dto: ProjectUpdate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
) -> ProjectUpdate:
    svc = ProjectService(session, storage)
    project = await svc.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updated = await svc.update(
        project_id,
        name=dto.name,
        description=dto.description,
        status=dto.status,
        preferred_model=dto.preferred_model,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_read(updated)

@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
    qdrant: AsyncQdrantClient = Depends(get_qdrant),
) -> None:
    svc = ProjectService(session, storage, qdrant=qdrant)
    project = await svc.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.sub)
    if db_user is None or (project.owner_id != db_user.id and not user.is_admin):
        raise HTTPException(status_code=403, detail="Only owner can delete")
    await svc.delete(project_id)
