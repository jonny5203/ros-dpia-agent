from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, get_session, get_storage
from app.db.models import Documents
from app.repositories import UserRepository
from app.schemas import DocumentRead
from app.services.document import DocumentService
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["documents"])

def _to_read(doc: Documents) -> DocumentRead:
    return DocumentRead(
        id=doc.id,
        filename=doc.filename,
        mime=doc.mime,
        ext=doc.ext,
        sha256=doc.sha256,
        classification="open",
        processing_status="pending",
        uploaded_by=doc.uploaded_by,
        uploaded_at=doc.uploaded_at,
    )

@router.post("/{project_id}/documents", response_model=DocumentRead, status_code=201)
async def upload_document(
    project_id: UUID,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
) -> DocumentRead:
    content = await file.read()
    svc = DocumentService(session, storage)

    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.sub)
    if db_user is None:
        raise HTTPException(status_code=403, detail="User not registered")

    try:
        doc = await svc.upload(
            project_id=project_id,
            filename=file.filename or "unnamed",
            content=content,
            uploaded_by=db_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_read(doc)

@router.get("/{project_id}/documents", response_model=list[DocumentRead])
async def list_documents(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
) -> list[DocumentRead]:
    svc = DocumentService(session, storage)
    docs = await svc.list_for_project(project_id)
    return [_to_read(d) for d in docs]

@router.delete("/{project_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    project_id: UUID,
    doc_id: UUID,
    user:CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
) -> None:
    svc = DocumentService(session, storage)
    await svc.delete(doc_id, project_id)
