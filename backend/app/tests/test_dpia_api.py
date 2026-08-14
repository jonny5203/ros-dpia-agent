"""API contract tests for versioned DPIA screening runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from arq import ArqRedis
from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.dpia as dpia_api
from app.api.deps import CurrentUser, ProjectContext
from app.auth.models import AppRole
from app.db.models import Projects
from app.schemas.dpia import DpiaRunAccepted, DpiaRunStatus
from app.services.dpia_runs import DpiaRunEnqueueError


def _project_context(project_id: UUID) -> ProjectContext:
    return ProjectContext(
        project=cast(Projects, SimpleNamespace(id=project_id)),
        user_db_id=uuid4(),
        member_role="member",
    )


def _current_user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        sub="user-sub",
        email="user@example.com",
        name="User",
        role=role,
    )


def _pending_row(project_id: UUID) -> SimpleNamespace:
    timestamp = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        requested_by=uuid4(),
        job_id=uuid4(),
        version=2,
        status=DpiaRunStatus.PENDING.value,
        evidence_snapshot=None,
        result=None,
        conclusion=None,
        model=None,
        prompt_version=None,
        rules_version="dpia-rules.v1",
        error=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _start_route() -> APIRoute:
    return next(
        route
        for route in dpia_api.router.routes
        if isinstance(route, APIRoute)
        and route.path.endswith("/dpia/runs")
        and route.methods is not None
        and "POST" in route.methods
    )


async def _check_start_role(role: AppRole) -> CurrentUser:
    route = _start_route()
    starter_dependency = next(
        dependency for dependency in route.dependant.dependencies if dependency.name == "starter"
    )
    role_checker = cast(
        Callable[..., Awaitable[CurrentUser]],
        starter_dependency.call,
    )
    return await role_checker(user=_current_user(role))


@pytest.mark.parametrize(
    "role",
    [
        AppRole.PROJECT_MANAGER,
        AppRole.PRIVACY_OFFICER,
        AppRole.ADMIN,
    ],
)
@pytest.mark.asyncio
async def test_start_role_dependency_allows_authorized_roles(
    role: AppRole,
) -> None:
    user = await _check_start_role(role)

    assert user.role is role


@pytest.mark.parametrize(
    "role",
    [
        AppRole.VIEWER,
        AppRole.IT_SECURITY,
    ],
)
@pytest.mark.asyncio
async def test_start_role_dependency_rejects_unauthorized_roles(
    role: AppRole,
) -> None:
    with pytest.raises(HTTPException) as caught:
        await _check_start_role(role)

    assert caught.value.status_code == 403
    assert caught.value.detail == "Insufficient role"


@pytest.mark.asyncio
async def test_start_returns_linked_run_and_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    job_id = uuid4()
    project = _project_context(project_id)
    captured: dict[str, object] = {}

    class FakeDpiaRunService:
        def __init__(self, session: AsyncSession) -> None:
            captured["session"] = session

        async def enqueue_dpia_run(
            self,
            **kwargs: object,
        ) -> DpiaRunAccepted:
            captured.update(kwargs)
            return DpiaRunAccepted(
                run_id=run_id,
                job_id=job_id,
                version=4,
            )

    monkeypatch.setattr(
        dpia_api,
        "DpiaRunService",
        FakeDpiaRunService,
    )

    response = await dpia_api.start_dpia_run(
        project_id=project_id,
        project=project,
        starter=_current_user(AppRole.PROJECT_MANAGER),
        session=cast(AsyncSession, object()),
        arq_pool=cast(ArqRedis, object()),
    )

    assert response == DpiaRunAccepted(
        run_id=run_id,
        job_id=job_id,
        version=4,
    )
    assert captured["project_id"] == project_id
    assert captured["requested_by"] == project.user_db_id
    assert _start_route().status_code == 202
    assert _start_route().response_model is DpiaRunAccepted


@pytest.mark.asyncio
async def test_start_maps_queue_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    class FailingDpiaRunService:
        def __init__(self, session: AsyncSession) -> None:
            pass

        async def enqueue_dpia_run(
            self,
            **kwargs: object,
        ) -> DpiaRunAccepted:
            raise DpiaRunEnqueueError("redis unavailable")

    monkeypatch.setattr(
        dpia_api,
        "DpiaRunService",
        FailingDpiaRunService,
    )

    with pytest.raises(HTTPException) as caught:
        await dpia_api.start_dpia_run(
            project_id=project_id,
            project=_project_context(project_id),
            starter=_current_user(AppRole.PROJECT_MANAGER),
            session=cast(AsyncSession, object()),
            arq_pool=cast(ArqRedis, object()),
        )

    assert caught.value.status_code == 503
    assert caught.value.detail == "DPIA screening queue unavailable"


@pytest.mark.asyncio
async def test_latest_returns_newest_project_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    row = _pending_row(project_id)
    requested_projects: list[UUID] = []

    class FakeScreeningRepository:
        def __init__(self, session: AsyncSession) -> None:
            pass

        async def get_latest_for_project(
            self,
            requested_project_id: UUID,
        ) -> object:
            requested_projects.append(requested_project_id)
            return row

    monkeypatch.setattr(
        dpia_api,
        "ScreeningRepository",
        FakeScreeningRepository,
    )

    response = await dpia_api.get_latest_dpia_run(
        project_id=project_id,
        project=_project_context(project_id),
        session=cast(AsyncSession, object()),
    )

    assert response.id == row.id
    assert response.job_id == row.job_id
    assert response.version == 2
    assert requested_projects == [project_id]


@pytest.mark.asyncio
async def test_exact_run_returns_404_when_not_owned_by_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    requested: list[tuple[UUID, UUID]] = []

    class FakeScreeningRepository:
        def __init__(self, session: AsyncSession) -> None:
            pass

        async def get_for_project(
            self,
            *,
            project_id: UUID,
            run_id: UUID,
        ) -> None:
            requested.append((project_id, run_id))
            return None

    monkeypatch.setattr(
        dpia_api,
        "ScreeningRepository",
        FakeScreeningRepository,
    )

    with pytest.raises(HTTPException) as caught:
        await dpia_api.get_dpia_run(
            project_id=project_id,
            run_id=run_id,
            project=_project_context(project_id),
            session=cast(AsyncSession, object()),
        )

    assert caught.value.status_code == 404
    assert caught.value.detail == "DPIA run not found"
    assert requested == [(project_id, run_id)]


def test_latest_literal_route_precedes_dynamic_run_id_route() -> None:
    paths = [route.path for route in dpia_api.router.routes if isinstance(route, APIRoute)]

    latest_index = paths.index("/v1/projects/{project_id}/dpia/runs/latest")
    exact_index = paths.index("/v1/projects/{project_id}/dpia/runs/{run_id}")

    assert latest_index < exact_index
