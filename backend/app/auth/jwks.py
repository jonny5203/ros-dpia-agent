"""JWKS-backed JWT validation against Keycloak.

A process-wide PyJWKClient fetches + caches Keycloak's public signing keys.
decode_access_token() verifies signature, expiry, issuer, and audience.
"""

from __future__ import annotations

import logging

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Process-wide singleton: PyJWKClient caches keys (default lifespan 300s) and
# refetches on cache miss / key rotation. Created lazily so tests can patch it.
_jwks_client: PyJWKClient | None = None


def get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        _jwks_client = PyJWKClient(settings.keycloak_jwks_uri)
        logger.info("JWKS client initialized against %s", settings.keycloak_jwks_uri)
    return _jwks_client


class TokenClaims(BaseModel):
    """The subset of JWT claims we rely on for authz + identity."""

    # Keycloak 26 omits `sub` from access tokens unless explicitly mapped;
    # fall back to azp/preferred_username for identity.
    sub: str | None = None
    azp: str | None = None
    email: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    preferred_username: str | None = None
    groups: list[str] = []
    exp: int
    iat: int
    iss: str
    aud: str | list[str]


class TokenError(Exception):
    """Raised when a JWT fails validation. Callers map this to HTTP 401."""


def decode_access_token(token: str) -> TokenClaims:
    """Validate an access token against Keycloak's JWKS.

    Verifies: RS256 signature (via JWKS), exp, iss (== public Keycloak issuer),
    aud (must include 'dpia-api' — set by the realm's audience mapper).
    Raises TokenError on any failure.
    """
    settings = get_settings()
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience="dpia-api",
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
        return TokenClaims(**payload)
    except jwt.PyJWTError as exc:
        logger.debug("Token validation failed: %s", exc)
        raise TokenError(str(exc)) from exc
