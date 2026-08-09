"""Two-pass, citation-gated project-profile extraction."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from qdrant_client import AsyncQdrantClient

from app.ai.citations.evidence import EvidenceBlock
from app.ai.citations.gate import verify_profile
from app.ai.citations.refs import CitedProjectProfile
from app.ai.prompts.profile import (
    PROFILE_PROMPT_VERSION,
    OutputLanguage,
    gap_messages,
    profile_messages,
)
from app.ai.providers.base import ProfileAIClient
from app.ai.retrieval import (
    DEFAULT_EVIDENCE_LIMIT,
    DocumentNameLookup,
    NoRetrievedEvidenceError,
    RetrievalError,
    merge_ranked_results,
    retrieve_project_evidence,
)
from app.db.models import ProjectProfiles
from app.schemas.profile import GapReport

_PER_QUERY_LIMIT = 8

RETRIEVAL_QUERIES = (
    (
        "prosjektformål behandlingsaktiviteter registrerte personopplysninger "
        "project purpose processing activities data subjects"
    ),
    (
        "personopplysningskategorier særlige kategorier behandlingsgrunnlag "
        "personal data categories special categories"
    ),
    (
        "systemarkitektur leverandører databehandlere underleverandører "
        "data location international transfer systems processors"
    ),
    (
        "lagringstid sletting tilgangsstyring autentisering logging sikkerhet "
        "retention deletion access control authentication security"
    ),
)

__all__ = [
    "DEFAULT_EVIDENCE_LIMIT",
    "RETRIEVAL_QUERIES",
    "NoEvidenceError",
    "ProfileExtractionError",
    "extract_profile",
    "merge_ranked_results",
]


class ProfileExtractionError(RuntimeError):
    """Profile extraction could not safely produce a persisted result."""


class NoEvidenceError(ProfileExtractionError):
    """The project has no usable indexed evidence."""


class ProfileWriter(Protocol):
    async def create(
        self,
        *,
        project_id: UUID,
        profile: dict,
        overall_confidence: str,
        model: str,
        prompt_version: str,
    ) -> ProjectProfiles: ...


async def _retrieve_evidence(
    *,
    project_id: UUID,
    qdrant: AsyncQdrantClient,
    client: ProfileAIClient,
    documents: DocumentNameLookup,
) -> EvidenceBlock:
    try:
        return await retrieve_project_evidence(
            project_id=project_id,
            queries=RETRIEVAL_QUERIES,
            qdrant=qdrant,
            client=client,
            documents=documents,
            per_query_limit=_PER_QUERY_LIMIT,
            evidence_limit=DEFAULT_EVIDENCE_LIMIT,
        )
    except NoRetrievedEvidenceError as exc:
        raise NoEvidenceError(str(exc)) from exc
    except RetrievalError as exc:
        raise ProfileExtractionError(str(exc)) from exc


async def extract_profile(
    *,
    project_id: UUID,
    model: str,
    qdrant: AsyncQdrantClient,
    client: ProfileAIClient,
    documents: DocumentNameLookup,
    profiles: ProfileWriter,
    output_language: OutputLanguage = "nb",
) -> ProjectProfiles:
    """Run both passes and stage one safe profile row.

    The caller owns the database transaction and must commit on success or
    roll back on failure.
    """

    evidence = await _retrieve_evidence(
        project_id=project_id,
        qdrant=qdrant,
        client=client,
        documents=documents,
    )

    cited_profile = await client.structured_completion(
        profile_messages(evidence.text, output_language),
        response_model=CitedProjectProfile,
        model=model,
        max_retries=2,
        temperature=0,
    )
    gate_result = verify_profile(cited_profile, evidence.token_map)

    gap_report = await client.structured_completion(
        gap_messages(gate_result.profile, evidence.text, output_language),
        response_model=GapReport,
        model=model,
        max_retries=2,
        temperature=0,
    )

    safe_profile = gate_result.profile.model_copy(
        update={
            "missingInfo": gap_report.missingInfo,
            "openQuestions": gap_report.openQuestions,
        }
    )

    return await profiles.create(
        project_id=project_id,
        profile=safe_profile.model_dump(mode="json"),
        overall_confidence=safe_profile.overallConfidence,
        model=model,
        prompt_version=PROFILE_PROMPT_VERSION,
    )
