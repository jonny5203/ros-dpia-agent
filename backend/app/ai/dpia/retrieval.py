"""DPIA-spesific retrieval and immutable evidence snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qdrant_client import AsyncQdrantClient

from app.ai.citations.evidence import EvidenceBlock, EvidenceEntry
from app.ai.providers.base import EmbeddingClient
from app.ai.retrieval import (
    DocumentNameLookup,
    RetrievalError,
    retrieve_project_evidence,
)
from app.core.config import get_settings
from app.schemas.dpia import (
    DpiaEvidenceSnapshot,
    DpiaEvidenceSnapshotEntry,
)

DPIA_RETRIEVAL_VERSION = "dpia-retrieval.v1"
DPIA_PER_QUERY_LIMIT = 8
DPIA_EVIDENCE_LIMIT = 24

DPIA_RETRIEVAL_QUERIES = (
    (
        "evaluering poengsetting profilering automatiserte beslutninger "
        "evaluation scoring profiling automated decisions significant effect"
    ),
    (
        "systematisk monitorering observasjon sporing offentlig område "
        "systematic monitoring tracking observation public area"
    ),
    (
        "særlige kategorier helseopplysninger biometriske straffedommer "
        "special category health biometric criminal conviction data"
    ),
    (
        "stor skala antall registrerte datamengde varighet geografisk omfang "
        "large scale number of data subjects volume duration geographical extent"
    ),
    (
        "matching sammenstilling kobling berikelse av datasett "
        "matching combining linking enriching datasets"
    ),
    (
        "sårbare registrerte barn pasienter ansatte maktubalanse "
        "vulnerable data subjects children patients employees power imbalance"
    ),
    (
        "ny teknologi innovativ bruk kunstig intelligens hindrer rettighet "
        "tjeneste eller avtale new technology prevents right service contract"
    ),
)


@dataclass(frozen=True)
class RetrievedDpiaEvidence:
    block: EvidenceBlock
    snapshot: DpiaEvidenceSnapshot


def _snapshot_entry(
    entry: EvidenceEntry,
) -> DpiaEvidenceSnapshotEntry:
    if entry.document_id is None or entry.document_name is None:
        raise RetrievalError("DPIA evidence snapshot requires complete document provenance")

    return DpiaEvidenceSnapshotEntry(
        token=entry.token,
        chunk_id=entry.chunk_id,
        document_id=entry.document_id,
        document_name=entry.document_name,
        page=entry.page,
        section_title=entry.section_title,
        text=entry.text,
    )


async def retrieve_dpia_evidence(
    *,
    project_id: UUID,
    qdrant: AsyncQdrantClient,
    client: EmbeddingClient,
    documents: DocumentNameLookup,
    retrieved_at: datetime | None = None,
) -> RetrievedDpiaEvidence:
    """Retrieve the exact bounded evidence input for one future DPIA run."""

    block = await retrieve_project_evidence(
        project_id=project_id,
        queries=DPIA_RETRIEVAL_QUERIES,
        qdrant=qdrant,
        client=client,
        documents=documents,
        per_query_limit=DPIA_PER_QUERY_LIMIT,
        evidence_limit=DPIA_EVIDENCE_LIMIT,
    )

    settings = get_settings()
    snapshot = DpiaEvidenceSnapshot(
        project_id=project_id,
        retrieval_version=DPIA_RETRIEVAL_VERSION,
        embedding_model=settings.embed_model,
        embedding_dimensions=settings.embed_dim,
        queries=DPIA_RETRIEVAL_QUERIES,
        per_query_limit=DPIA_PER_QUERY_LIMIT,
        evidence_limit=DPIA_EVIDENCE_LIMIT,
        retrieved_at=retrieved_at or datetime.now(UTC),
        evidence_text=block.text,
        entries=tuple(_snapshot_entry(entry) for entry in block.token_map.values()),
    )

    return RetrievedDpiaEvidence(
        block=block,
        snapshot=snapshot,
    )
