from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import embed_chunks
from app.ai.providers.openrouter import OpenRouterClient
from app.ai.store.qdrant import upsert_chunks
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.chunker import chunk_document
from app.ingestion.parser import parse
from app.ingestion.pii import LEXICON_VERSION, scan
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


async def ingest_document(ctx: dict[str, Any], *, job_id: str, document_id: str) -> None:
    """
    This is the ingestion pipeline, and the order is the privacy contract:
    parse (local) -> PII scan (local) -> [gate] -> embed (cloud) -> upsert
    """

    settings = get_settings()
    or_client: OpenRouterClient = ctx["openrouter"]
    qdrant: AsyncQdrantClient = ctx["qdrant"]
    storage: StorageService = ctx["storage"]

    from app.db.models import Chunks, DocumentFindings
    from app.repositories.chunk import ChunkRepository
    from app.repositories.document import DocumentRepository
    from app.repositories.finding import FindingRepository
    from app.repositories.index_manifest import IndexManifestRepository
    from app.repositories.lookup import LookupRepository

    async with SessionLocal() as session:
        docs_repo = DocumentRepository(session)
        doc = await docs_repo.get_by_id(uuid.UUID(document_id))
        if doc is None:
            logger.error("ingest: document %s not found", document_id)
            return

        content = await storage.get(doc.s3_key)
        parsed = await asyncio.to_thread(parse, content, doc.ext, doc.filename)
        scan_result = await asyncio.to_thread(scan, parsed)

        lookups = LookupRepository(session)
        findings_repo = FindingRepository(session)
        if scan_result.findings:
            await findings_repo.delete_findings_for_document(doc.id)
            await findings_repo.bulk_insert_findings([
                DocumentFindings(
                    document_id=doc.id,
                    type=f.type,
                    category=f.category,
                    severity=f.severity,
                    count=f.count,
                    sample_offsets=[list(o) for o in f.sample_offsets],
                    checksum_valid=f.checksum_valid,
                )
                for f in scan_result.findings
            ])
            max_sev = max(
                (f.severity for f in scan_result.findings),
                key=lambda s: _SEVERITY_RANK[s],
            )
            await docs_repo.set_max_severity(doc, max_sev, LEXICON_VERSION)

        # Per-document ack policy: an acked doc is treated as cleared even on re-scan.
        already_acked = doc.acked_at is not None
        if scan_result.has_critical and not already_acked:
            blocked_id = await lookups.processing_status_id("blocked")
            await docs_repo.set_status(doc, blocked_id)
            await _mark_job(session, job_id, status="blocked", pct=50)
            await session.commit()
            logger.warning("ingest: doc %s BLOCKED (critical PII) - not embedded", doc.id)
            return

        chunks = chunk_document(parsed, document_id=doc.id, project_id=doc.project_id)
        if not chunks:
            ready_id = await lookups.processing_status_id("ready")
            await docs_repo.set_status(doc, ready_id)
            await _mark_job(session, job_id, status="complete", pct=100)
            await session.commit()
            return

        # Embed — text now leaves the box (gate passed). Asserts dim drift.
        vectors = await embed_chunks([c.text for c in chunks], or_client)

        # Upsert Qdrant + write chunk rows + index_manifest.
        # 1.13+ shape: dense only. BM25 is built server-side from payload.text.
        points = [
            {
                "id": c.id,
                "dense": vectors[i],
                "payload": {
                    "chunk_id": c.id,
                    "document_id": str(doc.id),
                    "page": c.page,
                    "section_title": c.section_title,
                    "section_path": c.section_path,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                },
            }
            for i, c in enumerate(chunks)
        ]
        await upsert_chunks(qdrant, project_id=doc.project_id, points=points)

        chunk_repo = ChunkRepository(session)
        await chunk_repo.delete_for_document(doc.id)
        await chunk_repo.bulk_insert([
            Chunks(
                id=uuid.UUID(c.id),
                project_id=doc.project_id,
                document_id=doc.id,
                chunk_index=c.chunk_index,
                page=c.page,
                section_title=c.section_title,
                section_path=c.section_path,
                char_start=c.char_start,
                char_end=c.char_end,
                sha8=c.sha8,
                qdrant_point_id=uuid.UUID(c.id),
            )
            for c in chunks
        ])

        await IndexManifestRepository(session).upsert(
            project_id=doc.project_id,
            embed_model=settings.embed_model,
            embed_dim=settings.embed_dim,
            chunk_count=len(chunks),
        )

        ready_id = await lookups.processing_status_id("ready")
        await docs_repo.set_status(doc, ready_id)
        await _mark_job(session, job_id, status="complete", pct=100)
        await session.commit()


async def _mark_job(session: AsyncSession, job_id: str, *, status: str, pct: int) -> None:
    """Best-effort job progress update. Never fails the pipeline over bookkeeping."""
    from app.repositories.job import JobRepository
    try:
        repo = JobRepository(session)
        job = await repo.get_job(uuid.UUID(job_id))
        if job:
            await repo.update(job, status=status, progress_pct=pct)
    except Exception as exc:
        logger.warning("could not update job %s: %s", job_id, exc)
