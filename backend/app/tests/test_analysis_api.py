from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from arq import ArqRedis
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.analysis as analysis_api
import app.api.v1.ingest as ingest_api
from app.api.deps import CurrentUser, ProjectContext
from app.auth.models import AppRole
from app.db.models import Projects
from app.schemas.analysis import AnalysisRequest
from app.schemas.profile import NamedReferencedList, ProjectProfile, ReferencedValue
from app.services.analysis import AnalysisEnqueueError


def _project_context(project_id: UUID) -> ProjectContext:
    return ProjectContext(
        project=cast(Projects, SimpleNamespace(id=project_id)),
        user_db_id=uuid4(),
        member_role="owner",
    )


def _empty_profile() -> dict[str, object]:
    return ProjectProfile(
        purpose=ReferencedValue(value=None),
        dataSubjects=NamedReferencedList(),
        personalDataCategories=NamedReferencedList(),
        specialCategories=NamedReferencedList(),
        systems=NamedReferencedList(),
        processors=NamedReferencedList(),
        retention=ReferencedValue(value=None),
        accessControl=ReferencedValue(value=None),
        internationalTransfer=ReferencedValue(value=None),
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_analyze_enqueues_selected_language(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    job_id = uuid4()
    captured: dict[str, object] = {}

    class FakeAnalysisService:
        def __init__(self, session: AsyncSession) -> None:
            captured["session"] = session

        async def enqueue(self, **kwargs: object) -> UUID:
            captured.update(kwargs)
            return job_id

    monkeypatch.setattr(analysis_api, "AnalysisService", FakeAnalysisService)

    response = await analysis_api.analyze_project(
        project_id=project_id,
        request=AnalysisRequest(output_language="en"),
        project=_project_context(project_id),
        session=cast(AsyncSession, object()),
        arq_pool=cast(ArqRedis, object()),
    )

    assert response.job_id == job_id
    assert captured["project_id"] == project_id
    assert captured["output_language"] == "en"


@pytest.mark.asyncio
async def test_analyze_maps_queue_failure_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()

    class FailingAnalysisService:
        def __init__(self, session: AsyncSession) -> None:
            pass

        async def enqueue(self, **kwargs: object) -> UUID:
            raise AnalysisEnqueueError("redis unavailable")

    monkeypatch.setattr(analysis_api, "AnalysisService", FailingAnalysisService)

    with pytest.raises(HTTPException) as caught:
        await analysis_api.analyze_project(
            project_id=project_id,
            request=AnalysisRequest(),
            project=_project_context(project_id),
            session=cast(AsyncSession, object()),
            arq_pool=cast(ArqRedis, object()),
        )

    assert caught.value.status_code == 503
    assert caught.value.detail == "Analysis queue unavailable"


@pytest.mark.asyncio
async def test_get_profile_returns_latest_persisted_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        profile=_empty_profile(),
        overall_confidence="medium",
        model="model-v1",
        prompt_version="profile-v1",
        created_at=datetime.now(UTC),
    )

    class FakeProfileRepository:
        def __init__(self, session: AsyncSession) -> None:
            pass

        async def get_latest_for_project(self, requested: UUID) -> object:
            assert requested == project_id
            return row

    monkeypatch.setattr(analysis_api, "ProfileRepository", FakeProfileRepository)

    response = await analysis_api.get_profile(
        project_id=project_id,
        project=_project_context(project_id),
        session=cast(AsyncSession, object()),
    )

    assert response.id == row.id
    assert response.project_id == project_id
    assert response.profile.overallConfidence == "medium"


@pytest.mark.asyncio
async def test_job_polling_checks_project_membership(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid4()
    job_id = uuid4()
    checked: dict[str, object] = {}
    job = SimpleNamespace(
        id=job_id,
        project_id=project_id,
        kind="analyze_project",
        status="queued",
        progress_pct=0,
        error=None,
        arq_job_id="arq-123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class FakeJobRepository:
        def __init__(self, session: AsyncSession) -> None:
            pass

        async def get_job(self, requested: UUID) -> object:
            assert requested == job_id
            return job

    async def fake_project_context(**kwargs: object) -> ProjectContext:
        checked.update(kwargs)
        return _project_context(project_id)

    monkeypatch.setattr(ingest_api, "JobRepository", FakeJobRepository)
    monkeypatch.setattr(ingest_api, "get_project_context", fake_project_context)

    user = CurrentUser("sub", "user@example.com", "User", AppRole.VIEWER)
    response = await ingest_api.get_job(
        job_id=job_id,
        user=user,
        session=cast(AsyncSession, object()),
    )

    assert response.id == job_id
    assert checked["project_id"] == project_id
    assert checked["user"] is user
