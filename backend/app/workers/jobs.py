from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.extract_profile import ProfileExtractionError, extract_profile
from app.ai.dpia.extraction import extract_dpia_screening
from app.ai.dpia.retrieval import retrieve_dpia_evidence
from app.ai.embeddings.service import embed_chunks
from app.ai.prompts.dpia import DPIA_PROMPT_VERSION
from app.ai.prompts.profile import OutputLanguage
from app.ai.providers.openrouter import OpenRouterClient
from app.ai.retrieval import NoRetrievedEvidenceError
from app.ai.store.qdrant import upsert_chunks
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.ingestion.chunker import chunk_document
from app.ingestion.parser import parse
from app.ingestion.pii import LEXICON_VERSION, scan
from app.schemas.dpia import DpiaRunStatus
from app.services.dpia_runs import DPIA_JOB_KIND
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class AnalysisJobError(RuntimeError):
    """The queued analysis request does not match a persisted job."""


def _analysis_error(exc: Exception) -> str:
    if isinstance(exc, ProfileExtractionError):
        return str(exc)
    return "Profile analysis failed"


async def analyze_project(
    ctx: dict[str, Any],
    *,
    job_id: str,
    project_id: str,
    output_language: OutputLanguage = "nb",
) -> None:
    """Run both profile passes and persist one profile or one failed job state."""

    parsed_job_id = uuid.UUID(job_id)
    parsed_project_id = uuid.UUID(project_id)
    settings = get_settings()
    client: OpenRouterClient = ctx["openrouter"]
    qdrant: AsyncQdrantClient = ctx["qdrant"]

    from app.repositories.document import DocumentRepository
    from app.repositories.job import JobRepository
    from app.repositories.profile import ProfileRepository

    async with SessionLocal() as session:
        jobs = JobRepository(session)
        job = await jobs.get_job(parsed_job_id)
        if job is None or job.project_id != parsed_project_id:
            raise AnalysisJobError("analysis job does not match the requested project")

        await jobs.update(job, status="running", progress_pct=10, error=None)
        await session.commit()

        try:
            await extract_profile(
                project_id=parsed_project_id,
                model=settings.llm_model,
                qdrant=qdrant,
                client=client,
                documents=DocumentRepository(session),
                profiles=ProfileRepository(session),
                output_language=output_language,
            )
            await jobs.update(job, status="complete", progress_pct=100, error=None)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.exception("analysis job %s failed", parsed_job_id)
            try:
                failed_job = await jobs.get_job(parsed_job_id)
                if failed_job is not None:
                    await jobs.update(
                        failed_job,
                        status="failed",
                        error=_analysis_error(exc),
                    )
                    await session.commit()
            except Exception:
                logger.exception("could not mark analysis job %s failed", parsed_job_id)
            raise


class DpiaRunJobError(RuntimeError):
    """The queued identifiers do not describe one matching DPIA run and job."""


def _dpia_run_failure_message(exc: Exception) -> str:
    """Return a safe persisted error without exposing provider details."""

    if isinstance(exc, NoRetrievedEvidenceError):
        return "No indexed evidence is available for DPIA screening"

    return "DPIA screening failed"


async def run_dpia_screening(
    ctx: dict[str, Any],
    *,
    job_id: str,
    run_id: str,
    project_id: str,
) -> None:
    """Freeze evience, extract assessments,and complete one linked DPIA run."""

    parsed_job_id = uuid.UUID(job_id)
    parsed_run_id = uuid.UUID(run_id)
    parsed_project_id = uuid.UUID(project_id)
    settings = get_settings()
    client: OpenRouterClient = ctx["openrouter"]
    qdrant: AsyncQdrantClient = ctx["qdrant"]

    from app.repositories.document import DocumentRepository
    from app.repositories.dpia import ScreeningRepository
    from app.repositories.job import JobRepository

    async with SessionLocal() as session:
        jobs = JobRepository(session)
        screenings = ScreeningRepository(session)

        job = await jobs.get_job(parsed_job_id)
        run = await screenings.get_for_project(
            project_id=parsed_project_id,
            run_id=parsed_run_id,
        )

        if (
            job is None
            or job.project_id != parsed_project_id
            or job.kind != DPIA_JOB_KIND
            or run is None
            or run.job_id != parsed_job_id
        ):
            raise DpiaRunJobError("DPIA job, run, and project identifiers do not match")

        await jobs.update(
            job,
            status="running",
            progress_pct=10,
            error=None,
        )
        await screenings.mark_running(run)
        await session.commit()

        try:
            retrieved = await retrieve_dpia_evidence(
                project_id=parsed_project_id,
                qdrant=qdrant,
                client=client,
                documents=DocumentRepository(session),
            )

            await screenings.store_snapshot(run, retrieved.snapshot)
            await jobs.update(
                job,
                progress_pct=50,
            )

            # Commit frozen evidence before any provider call can fail
            await session.commit()

            result = await extract_dpia_screening(
                snapshot=retrieved.snapshot,
                model=settings.llm_model,
                client=client,
            )

            await screenings.complete(
                run,
                result=result,
                model=settings.llm_model,
                prompt_version=DPIA_PROMPT_VERSION,
            )

            await jobs.update(
                job,
                status="complete",
                progress_pct=100,
                error=None,
            )
            await session.commit()

        except Exception as exc:
            await session.rollback()
            logger.exception("DPIA screening run %s failed", parsed_run_id)

            try:
                failed_job = await jobs.get_job(parsed_job_id)
                failed_run = await screenings.get_for_project(
                    project_id=parsed_project_id,
                    run_id=parsed_run_id,
                )
                safe_error = _dpia_run_failure_message(exc)

                if failed_run is not None and failed_run.status in {
                    DpiaRunStatus.PENDING.value,
                    DpiaRunStatus.RUNNING.value,
                }:
                    await screenings.fail(
                        failed_run,
                        error=safe_error,
                    )

                if failed_job is not None:
                    await jobs.update(
                        failed_job,
                        status="failed",
                        error=safe_error,
                    )

                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception(
                    "could not persist failure for DPIA screening run %s",
                    parsed_run_id,
                )

            raise


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
