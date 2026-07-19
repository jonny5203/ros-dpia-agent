"""BFF auth endpoints: /auth/{login,callback,logout,me}.

Implements Authorization Code flow with PKCE (RFC 7636). Tokens live only in
the signed httpOnly session cookie; the SPA never sees them.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Any

from app.auth.jwks import decode_access_token
from app.repositories.user import UserRepository
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.auth.models import SK_ACCESS, SK_EXP, SK_ID, SK_REFRESH, SK_STATE, SK_VERIFIER, AppRole, resolve_role
from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Scopes requested from Keycloak. openid is mandatory; profile+email populate
# /auth/me; groups comes via the realm's protocol mapper (no scope needed).
_SCOPES = "openid profile email"


# ── PKCE helpers (RFC 7636) ────────────────────────────────────────────────
def _b64url(data: bytes) -> str:
    """Base64-url-encode without padding (RFC 7636 §4.2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge). Challenge is S256 per RFC 7636 §4.2."""
    # 43-128 chars; 64 url-safe bytes → 86 chars, comfortably in range.
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ── /auth/login ────────────────────────────────────────────────────────────
@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    """Begin the Authorization Code + PKCE flow.

    Generates a verifier + state, stores them in the session (so /auth/callback
    can verify them), then 302s the browser to Keycloak's authorization endpoint.
    """
    settings = get_settings()
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    # Stash for callback verification. The session cookie is signed + httpOnly,
    # so these can't be read or tampered with by the browser.
    request.session[SK_STATE] = state
    request.session[SK_VERIFIER] = verifier

    params = {
        "client_id": settings.keycloak_client_id,
        "response_type": "code",
        "scope": _SCOPES,
        "redirect_uri": settings.public_callback_url,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = httpx.URL(settings.keycloak_authorization_endpoint, params=params)
    logger.debug("Redirecting to Keycloak authz endpoint")
    return RedirectResponse(url=str(auth_url), status_code=302)


# ── /auth/callback ─────────────────────────────────────────────────────────
async def _exchange_code_for_tokens(
    settings: Any, code: str, verifier: str
) -> dict[str, Any]:
    """POST to Keycloak's token endpoint. Returns the token bundle."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.public_callback_url,
        "client_id": settings.keycloak_client_id,
        "code_verifier": verifier,
    }
    # Public PKCE client — no client_secret. If we ever add a confidential
    # client, append client_secret here.
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(settings.keycloak_token_endpoint, data=data)
    if resp.status_code != 200:
        logger.warning("Token exchange failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=400, detail="Token exchange failed")
    return resp.json()


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Keycloak's redirect back to us.

    Verifies state (CSRF defense), exchanges the auth code for tokens, stores
    the bundle in the session, then 302s to the SPA root.
    """
    settings = get_settings()

    # Keycloak reports auth errors (user cancelled, access denied) as query params.
    if error:
        logger.info("OAuth error from Keycloak: %s", error)
        return RedirectResponse(url=f"{settings.public_base_url}/login?error=oauth")

    # State check: prevents CSRF where an attacker tricks the browser into
    # completing someone else's OAuth flow.
    expected_state = request.session.pop(SK_STATE, None)
    verifier = request.session.pop(SK_VERIFIER, None)
    if not state or state != expected_state or not verifier:
        logger.warning("OAuth state mismatch or missing verifier")
        raise HTTPException(status_code=400, detail="Invalid state")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    tokens = await _exchange_code_for_tokens(settings, code, verifier)
    _store_token_bundle(request, tokens)

    logger.info("OAuth callback completed, user logged in")
    return RedirectResponse(url=settings.public_base_url)


def _store_token_bundle(request: Request, tokens: dict[str, Any]) -> None:
    """Persist the token bundle into the signed session cookie."""
    import time

    request.session[SK_ACCESS] = tokens["access_token"]
    request.session[SK_REFRESH] = tokens.get("refresh_token", "")
    request.session[SK_ID] = tokens.get("id_token", "")
    request.session[SK_EXP] = int(time.time()) + int(tokens.get("expires_in", 300))


# ── /auth/me ───────────────────────────────────────────────────────────────
@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Return the current user's identity + resolved global role.

    The SPA calls this on boot to hydrate its auth state. 401 if not logged in.
    """
    return {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "is_admin": user.is_admin,
    }


# ── /auth/logout ───────────────────────────────────────────────────────────
@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Log out: clear the BFF session, then redirect to Keycloak's end-session.

    Keycloak's end-session kills the SSO session too, so a subsequent /auth/login
    re-prompts for credentials rather than silently re-issuing tokens.
    id_token_hint makes the logout flow skip the "are you sure?" confirmation.
    """
    settings = get_settings()
    id_token = request.session.get(SK_ID, "")
    request.session.clear()

    params: dict[str, str] = {
        "post_logout_redirect_uri": settings.public_base_url,
        "client_id": settings.keycloak_client_id,
    }
    if id_token:
        params["id_token_hint"] = id_token

    end_session = httpx.URL(settings.keycloak_end_session_endpoint, params=params)
    return RedirectResponse(url=str(end_session), status_code=302)


async def _persist_user(request: Request, session: AsyncSession) -> None:
    """ Upsert the logged-in user into the users table."""
    access = request.session.get(SK_ACCESS)
    if not access:
        return
    claims = decode_access_token(access)
    role = resolve_role(claims.groups)
    user_repo = UserRepository(session)

    await user_repo.upsert(
        oidc_sub=claims.sub or claims.preferred_username or "unknown",
        email=claims.email or "",
        display_name=" ".join(filter(None, [claims.given_name, claims.family_name])) or claims.preferred_username or "unknown",
        app_role=role.value,
        is_admin=(role == AppRole.ADMIN)
    )
    await session.commit()
