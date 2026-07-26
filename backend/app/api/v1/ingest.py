from __future__ import annotations

from uuid import UUID

from app.ai.providers.openrouter import OpenRouterClient
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import embed_chunks
from app.ai.store.qdrant import hybrid_query
from app.db.models import Documents
from app.repositories.chunk import ChunkRepository
from app.repositories.document import DocumentRepository
from app.repositories.finding import FindingRepository
from app.repositories.job import JobRepository
from app.repositories.user import UserRepository
from app.schemas import ChunkRead, DocumentWithFindings, FindingRead, JobRead
from qdrant_client import AsyncQdrantClient

from app.api.deps import (
    CurrentUser,
    get_arq_pool,
    get_current_user,
    get_qdrant,
    get_session,
    ProjectContext,
    get_openrouter,
    get_project_context,
)
from arq import ArqRedis

router = APIRouter(prefix="/v1", tags=["ingest"])

@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(
    job_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JobRead:
    job = await JobRepository(session).get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return JobRead.model_validate(job)

@router.post("/documents/{doc_id}/acknowledge", response_model=DocumentWithFindings)
async def acknowledge_findings(
    doc_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool)
) -> DocumentWithFindings:
    """ Acknowledge CRITICAL PII -> unblocks embedding+indexing. Audited. """
    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.sub)
    if db_user is None:
        raise HTTPException(403, "User not registered")

    docs = DocumentRepository(session)
    doc = await docs.get_by_id(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")

    await docs.acknowledge(doc, user_id=db_user.id)
    await session.commit()

    await arq_pool.enqueue_job(
        "ingest_document",
        document_id=str(doc.id),
    )

    findings = await FindingRepository(session).list_findings_for_document(doc.id)
    return DocumentWithFindings(
        document_id=doc.id,
        filename=doc.filename,
        processing_status="acknowledged",
        max_severity=doc.max_severity,
        finding=[FindingRead.model_validate(f) for f in findings],
        acked_at=doc.acked_at.isoformat() if doc.acked_at else None,
    )

@router.get("/documents/{doc_id}/chunks/{chunk_id}", response_model=ChunkRead)
async def get_chunk(
    doc_id: UUID,
    chunk_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChunkRead:
    """ Citation drill down, full chunk text + provenance. """
    chunk = await ChunkRepository(session).get(chunk_id)
    if chunk is None or chunk.document_id != doc_id:
        raise HTTPException(404, "Chunk not found")
    return ChunkRead.model_validate(chunk)

@router.get("/projects/{project_id}/search")
async def search(
    project_id: UUID,
    q: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    qdrant: AsyncQdrantClient = Depends(get_qdrant),
    or_client: OpenRouterClient = Depends(get_openrouter),
    ctx: ProjectContext = Depends(get_project_context),
) -> list[dict]:
    """
        Hybrid RRF search scoped to one project.
        Embeds the query via openrouter, then runs hybrid_query (dense + bm25, RRF).
    """

    vectors = await embed_chunks([q], or_client)
    query_vector: list[float] = vectors[0]
    return await hybrid_query(
        qdrant,
        project_id=project_id,
        query_text=q,
        query_vector=query_vector,
        limit=10,
    )

