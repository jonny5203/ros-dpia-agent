"""Tests for auth: PKCE generation, role resolution, endpoint behavior.

Token exchange + JWKS validation are integration concerns (need a live Keycloak);
here we unit-test the deterministic pieces and the session/cookie plumbing.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi.testclient import TestClient

from app.auth.models import AppRole, resolve_role
from app.auth.router import generate_pkce_pair
from app.main import create_app


# ── Role resolution (the priority-hierarchy decision) ──────────────────────
class TestResolveRole:
    def test_single_group_maps_directly(self):
        assert resolve_role(["privacy-officer"]) == AppRole.PRIVACY_OFFICER
        assert resolve_role(["it-security"]) == AppRole.IT_SECURITY
        assert resolve_role(["admin"]) == AppRole.ADMIN

    def test_admin_wins_over_everything(self):
        """Priority: admin > privacy-officer > it-security > pm > viewer."""
        assert resolve_role(["admin", "viewer"]) == AppRole.ADMIN
        assert resolve_role(["viewer", "admin", "it-security"]) == AppRole.ADMIN

    def test_privacy_officer_beats_lower_roles(self):
        assert resolve_role(["privacy-officer", "viewer"]) == AppRole.PRIVACY_OFFICER

    def test_no_group_defaults_to_viewer(self):
        """Fail-closed: unknown/missing group → least privilege."""
        assert resolve_role([]) == AppRole.VIEWER
        assert resolve_role(["not-a-real-group"]) == AppRole.VIEWER

    def test_handles_leading_slash_from_keycloak_fullpath(self):
        """Keycloak may emit '/admin' if the mapper's full.path is true."""
        assert resolve_role(["/admin"]) == AppRole.ADMIN
        assert resolve_role(["/privacy-officer", "viewer"]) == AppRole.PRIVACY_OFFICER


# ── PKCE generation (RFC 7636 compliance) ──────────────────────────────────
class TestPkce:
    def test_verifier_is_urlsafe_base64_without_padding(self):
        verifier, _ = generate_pkce_pair()
        # No padding characters
        assert "=" not in verifier
        # Only url-safe chars
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        assert set(verifier) <= allowed

    def test_verifier_length_in_rfc_range(self):
        # RFC 7636 §4.1: 43-128 chars
        verifier, _ = generate_pkce_pair()
        assert 43 <= len(verifier) <= 128

    def test_challenge_is_sha256_of_verifier(self):
        verifier, challenge = generate_pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert challenge == expected

    def test_unique_each_call(self):
        v1, _ = generate_pkce_pair()
        v2, _ = generate_pkce_pair()
        assert v1 != v2


# ── Endpoint behavior ──────────────────────────────────────────────────────
class TestAuthEndpoints:
    def setup_method(self):
        self.client = TestClient(create_app(), follow_redirects=False)

    def test_login_redirects_to_keycloak_with_pkce(self):
        r = self.client.get("/auth/login")
        assert r.status_code == 302
        loc = r.headers["location"]
        assert "localhost:8080/realms/sandefjord/protocol/openid-connect/auth" in loc
        assert "client_id=dpia-bff" in loc
        assert "code_challenge=" in loc
        assert "code_challenge_method=S256" in loc
        assert "state=" in loc
        # Session cookie should be set (holds verifier + state)
        assert "dpia_session" in r.cookies

    def test_callback_rejects_missing_state(self):
        # No prior /auth/login → no stored state → 400
        r = self.client.get("/auth/callback", params={"code": "x", "state": "y"})
        assert r.status_code == 400

    def test_me_returns_401_without_session(self):
        r = self.client.get("/auth/me")
        assert r.status_code == 401

    def test_logout_clears_session_and_redirects(self):
        r = self.client.get("/auth/logout")
        assert r.status_code == 302
        assert "protocol/openid-connect/logout" in r.headers["location"]
        assert "post_logout_redirect_uri" in r.headers["location"]


# ── /auth/me with a mocked token (proves the full pipeline) ────────────────
class TestAuthMeWithMockedToken:
    def test_me_returns_resolved_role_for_valid_token(self):
        """Override the get_current_user dependency so we don't need a live
        Keycloak + JWKS. Proves /auth/me maps CurrentUser → response JSON."""
        from app.api.deps import CurrentUser, get_current_user
        from app.auth.models import AppRole

        fake_user = CurrentUser(
            sub="user-123",
            email="po@kommune.example",
            name="Privacy Officer",
            role=AppRole.PRIVACY_OFFICER,
        )
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: fake_user
        client = TestClient(app)
        try:
            r = client.get("/auth/me")
            assert r.status_code == 200
            body = r.json()
            assert body["sub"] == "user-123"
            assert body["role"] == "privacy-officer"
            assert body["is_admin"] is False
        finally:
            app.dependency_overrides.clear()


    def test_me_reflects_admin_role(self):
        from app.api.deps import CurrentUser, get_current_user
        from app.auth.models import AppRole

        fake_admin = CurrentUser(
            sub="admin-sub",
            email="admin@kommune.example",
            name="App Admin",
            role=AppRole.ADMIN,
        )
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: fake_admin
        client = TestClient(app)
        try:
            r = client.get("/auth/me")
            assert r.status_code == 200
            body = r.json()
            assert body["role"] == "admin"
            assert body["is_admin"] is True
        finally:
            app.dependency_overrides.clear()
