"""Contract tests for two-pass profile extraction."""

from __future__ import annotations

from typing import Any, TypeVar, cast
from uuid import UUID

import pytest
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient

from app.ai.agents.extract_profile import (
    RETRIEVAL_QUERIES,
    NoEvidenceError,
    ProfileExtractionError,
    extract_profile,
    merge_ranked_results,
)
from app.ai.citations.refs import (
    Cited,
    CitedItem,
    CitedNamed,
    CitedProjectProfile,
    CitedRef,
)
from app.ai.prompts.profile import PROFILE_PROMPT_VERSION
from app.db.models import ProjectProfiles
from app.schemas.profile import Gap, GapReport, OpenQuestion

ModelT = TypeVar("ModelT", bound=BaseModel)

PROJECT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _chunk(number: int, text: str) -> dict[str, Any]:
    return {
        "chunk_id": str(UUID(int=number)),
        "document_id": str(DOCUMENT_ID),
        "page": number,
        "section_title": f"Section {number}",
        "text": text,
        "score": 1.0 / number,
    }


def _empty_scalar() -> Cited:
    return Cited(value=None, sourceReferences=[])


def _empty_list() -> CitedNamed:
    return CitedNamed(items=[])


def _pass_a_profile() -> CitedProjectProfile:
    return CitedProjectProfile(
        purpose=Cited(
            value="Oppdiktet formål",
            sourceReferences=[CitedRef(citation="C999")],
        ),
        dataSubjects=_empty_list(),
        personalDataCategories=_empty_list(),
        specialCategories=_empty_list(),
        systems=CitedNamed(
            items=[
                CitedItem(
                    value="Azure OpenAI",
                    sourceReferences=[CitedRef(citation="C1")],
                )
            ]
        ),
        processors=_empty_list(),
        retention=_empty_scalar(),
        accessControl=_empty_scalar(),
        internationalTransfer=_empty_scalar(),
        overallConfidence="low",
    )


def _gap_report() -> GapReport:
    return GapReport(
        missingInfo=[
            Gap(
                field="retention",
                description="Lagringstid og sletterutine er ikke dokumentert",
                severity="warning",
            )
        ],
        openQuestions=[
            OpenQuestion(
                question="Hvor lenge skal personopplysninger lagres?",
                rationale="En fastsatt lagringstid er nødvendig for videre vurdering.",
            )
        ],
    )


class FakeAI:
    def __init__(
        self,
        pass_a: CitedProjectProfile,
        gaps: GapReport,
        *,
        fail_on_gap: bool = False,
    ) -> None:
        self.pass_a = pass_a
        self.gaps = gaps
        self.fail_on_gap = fail_on_gap
        self.embedding_text: list[str] = []
        self.structured_models: list[type[BaseModel]] = []
        self.messages: list[list[dict[str, str]]] = []

    async def embed(
        self,
        text: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        self.embedding_text.extend(text)
        return [[0.0] * 3072 for _ in text]

    async def structured_completion(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[ModelT],
        model: str | None = None,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> ModelT:
        self.structured_models.append(response_model)
        self.messages.append(messages)

        if response_model is CitedProjectProfile:
            result: BaseModel = self.pass_a
        elif response_model is GapReport:
            if self.fail_on_gap:
                raise RuntimeError("gap pass failed")
            result = self.gaps
        else:
            raise AssertionError(f"unexpected response model: {response_model}")

        return cast(ModelT, result)


class FakeDocumentNames:
    def __init__(self, names: dict[UUID, str]) -> None:
        self.names = names
        self.calls: list[tuple[UUID, set[UUID]]] = []

    async def filenames_by_ids(
        self,
        project_id: UUID,
        document_ids: set[UUID],
    ) -> dict[UUID, str]:
        self.calls.append((project_id, document_ids))
        return {
            document_id: self.names[document_id]
            for document_id in document_ids
            if document_id in self.names
        }


class FakeProfiles:
    def __init__(self):
        self.created: dict[str, Any] | None = None

    async def create(
        self,
        *,
        project_id: UUID,
        profile: dict,
        overall_confidence: str,
        model: str,
        prompt_version: str,
    ) -> ProjectProfiles:
        self.created = {
            "project_id": project_id,
            "profile": profile,
            "overall_confidence": overall_confidence,
            "model": model,
            "prompt_version": prompt_version,
        }
        return ProjectProfiles(**self.created)


def _qdrant() -> AsyncQdrantClient:
    return cast(AsyncQdrantClient, object())


def test_merge_ranked_results_interleaved_and_deduplicates() -> None:
    first = [_chunk(1, "first"), _chunk(2, "second")]
    second = [_chunk(2, "duplicate"), _chunk(3, "third")]

    merged = merge_ranked_results([first, second], limit=3)

    assert [item["chunk_id"] for item in merged] == [
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
    ]


@pytest.mark.asyncio
async def test_extracted_gates_finds_gaps_and_stages_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranked = {
        RETRIEVAL_QUERIES[0]: [
            _chunk(1, "Systemet bruker Azure OpenAI."),
            _chunk(2, "Prosjektet behandler ansattdata"),
        ],
        RETRIEVAL_QUERIES[1]: [
            _chunk(2, "Prosjektet behandler ansattdata."),
            _chunk(3, "Ingen largigstid er angitt."),
        ],
        RETRIEVAL_QUERIES[2]: [
            _chunk(4, "Microsoft er databehandler."),
        ],
        RETRIEVAL_QUERIES[3]: [
            _chunk(5, "Tilgang krever autentiserig."),
        ],
    }

    query_calls: list[str] = []

    async def fake_hybrid_query(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query_calls.append(query_text)
        return ranked[query_text][:limit]

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        fake_hybrid_query,
    )

    ai = FakeAI(_pass_a_profile(), _gap_report())
    documents = FakeDocumentNames({DOCUMENT_ID: "Systembeskrivelse.pdf"})
    profiles = FakeProfiles()

    row = await extract_profile(
        project_id=PROJECT_ID,
        model="anthropic/claude-sonnet-4.5",
        qdrant=_qdrant(),
        client=ai,
        documents=documents,
        profiles=profiles,
        output_language="nb",
    )

    assert row is not None
    assert query_calls == list(RETRIEVAL_QUERIES)
    assert ai.embedding_text == list(RETRIEVAL_QUERIES)
    assert ai.structured_models == [CitedProjectProfile, GapReport]
    assert documents.calls == [(PROJECT_ID, {DOCUMENT_ID})]

    assert profiles.created is not None
    stored = profiles.created["profile"]

    assert stored["purpose"]["value"] is None
    assert stored["needsReview"][0]["fieldPath"] == "purpose"
    assert stored["needsReview"][0]["unverifiedCitations"] == ["C999"]
    assert stored["systems"]["items"][0]["value"] == "Azure OpenAI"
    assert (
        stored["systems"]["items"][0]["sourceReferences"][0]["documentName"]
        == "Systembeskrivelse.pdf"
    )
    assert stored["missingInfo"][0]["field"] == "retention"
    assert stored["openQuestions"][0]["question"].startswith("Hvor lenge")
    assert profiles.created["prompt_version"] == PROFILE_PROMPT_VERSION

    gap_input = ai.messages[1][1]["content"]
    assert '"value": null' in gap_input
    assert '"fieldPath": "purpose"' in gap_input


@pytest.mark.asyncio
async def test_no_evidence_skips_models_and_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_result(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        no_result,
    )

    ai = FakeAI(_pass_a_profile(), _gap_report())
    profiles = FakeProfiles()

    with pytest.raises(NoEvidenceError, match="no indexed evidence"):
        await extract_profile(
            project_id=PROJECT_ID,
            model="anthropic/claude-sonnet-4.5",
            qdrant=_qdrant(),
            client=ai,
            documents=FakeDocumentNames({}),
            profiles=profiles,
        )

    assert ai.structured_models == []
    assert profiles.created is None


@pytest.mark.asyncio
async def test_missing_project_document_provenance_fails_before_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def one_result(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [_chunk(1, "Evidence")]

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        one_result,
    )

    ai = FakeAI(_pass_a_profile(), _gap_report())
    profiles = FakeProfiles()

    with pytest.raises(
        ProfileExtractionError,
        match="available project document",
    ):
        await extract_profile(
            project_id=PROJECT_ID,
            model="anthropic/claude-sonnet-4.5",
            qdrant=_qdrant(),
            client=ai,
            documents=FakeDocumentNames({}),
            profiles=profiles,
        )

    assert ai.structured_models == []
    assert profiles.created is None


@pytest.mark.asyncio
async def test_gap_failure_does_not_stage_pass_a_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def one_result(
        qdrant: AsyncQdrantClient,
        *,
        project_id: UUID,
        query_text: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return [_chunk(1, "Systemet bruker Azure OpenAI.")]

    monkeypatch.setattr(
        "app.ai.retrieval.hybrid_query",
        one_result,
    )

    ai = FakeAI(
        _pass_a_profile(),
        _gap_report(),
        fail_on_gap=True,
    )
    profiles = FakeProfiles()

    with pytest.raises(RuntimeError, match="gap pass failed"):
        await extract_profile(
            project_id=PROJECT_ID,
            model="anthropic/claude-sonnet-4.5",
            qdrant=_qdrant(),
            client=ai,
            documents=FakeDocumentNames({DOCUMENT_ID: "Systembeskrivelse.pdf"}),
            profiles=profiles,
        )

    assert ai.structured_models == [CitedProjectProfile, GapReport]
    assert profiles.created is None
