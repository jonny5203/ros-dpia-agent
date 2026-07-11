"""Tests for global-role RBAC via require_role().

Uses the same dependency_overrides pattern as test_auth.py: mock
get_current_user to inject a user with a specific role, without needing
a live Keycloak + JWKS.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.api.deps import CurrentUser, get_current_user, require_role
from app.auth.models import AppRole
from app.main import create_app


def _make_user(role: AppRole) -> CurrentUser:
    return CurrentUser(
        sub=f"user-{role.value}",
        email=f"{role.value}@kommune.example",
        name=role.value.replace("-", " ").title(),
        role=role,
    )


def _client_with_user(user: CurrentUser | None) -> TestClient:
    """Create a TestClient with get_current_user overridden.

    Pass user=None to simulate an unauthenticated request (get_current_user
    raises 401).
    """
    from fastapi import HTTPException

    app = create_app()

    if user is None:
        async def _deny() -> CurrentUser:
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides[get_current_user] = _deny
    else:
        app.dependency_overrides[get_current_user] = lambda: user

    return TestClient(app)


def _cleanup(app):
    app.dependency_overrides.clear()


# ── Admin-only endpoint (/api/v1/admin/whoami) ──────────────────────────────

class TestAdminEndpoint:
    def test_admin_can_access(self):
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.ADMIN)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/admin/whoami")
            assert r.status_code == 200
            body = r.json()
            assert body["role"] == "admin"
            assert body["message"] == "admin access granted"
        finally:
            _cleanup(app)

    def test_viewer_denied(self):
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.VIEWER)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/admin/whoami")
            assert r.status_code == 403
        finally:
            _cleanup(app)

    def test_privacy_officer_denied(self):
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.PRIVACY_OFFICER)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/admin/whoami")
            assert r.status_code == 403
        finally:
            _cleanup(app)

    def test_unauthenticated_denied(self):
        app = create_app()
        from fastapi import HTTPException

        async def _deny() -> CurrentUser:
            raise HTTPException(status_code=401, detail="Not authenticated")

        app.dependency_overrides[get_current_user] = _deny
        client = TestClient(app)
        try:
            r = client.get("/api/v1/admin/whoami")
            assert r.status_code == 401
        finally:
            _cleanup(app)


# ── Multi-role endpoint (admin OR privacy-officer) ──────────────────────────

def _build_multi_role_app() -> tuple:
    """Create an app with an extra route allowing admin OR privacy-officer."""
    from fastapi import FastAPI

    app: FastAPI = create_app()
    extra = APIRouter()

    @extra.get("/api/v1/officer-only/check")
    async def check(
        user: CurrentUser = Depends(
            require_role(AppRole.ADMIN, AppRole.PRIVACY_OFFICER)
        ),
    ) -> dict:
        return {"role": user.role.value}

    app.include_router(extra)
    return app, extra


class TestMultiRoleEndpoint:
    def test_admin_allowed(self):
        app, _ = _build_multi_role_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.ADMIN)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/officer-only/check")
            assert r.status_code == 200
        finally:
            _cleanup(app)

    def test_privacy_officer_allowed(self):
        app, _ = _build_multi_role_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.PRIVACY_OFFICER)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/officer-only/check")
            assert r.status_code == 200
        finally:
            _cleanup(app)

    def test_viewer_denied(self):
        app, _ = _build_multi_role_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.VIEWER)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/officer-only/check")
            assert r.status_code == 403
        finally:
            _cleanup(app)

    def test_it_security_denied(self):
        app, _ = _build_multi_role_app()
        app.dependency_overrides[get_current_user] = lambda: _make_user(AppRole.IT_SECURITY)
        client = TestClient(app)
        try:
            r = client.get("/api/v1/officer-only/check")
            assert r.status_code == 403
        finally:
            _cleanup(app)
