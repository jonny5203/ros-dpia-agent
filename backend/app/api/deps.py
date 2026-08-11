"""FastAPI dependencies shared by routers."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from uuid import UUID

import httpx
from arq import ArqRedis
from fastapi import Depends, HTTPException, Request
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.openrouter import OpenRouterClient
from app.auth.jwks import TokenError, decode_access_token
from app.auth.models import SK_ACCESS, SK_EXP, SK_REFRESH, AppRole, resolve_role
from app.core.config import get_settings
from app.db.models import Projects
from app.db.session import get_session
from app.repositories.member import ProjectMemberRepository
from app.repositories.project import ProjectRepository
from app.repositories.user import UserRepository
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


def get_openrouter(request: Request) -> OpenRouterClient:
    """The lifespan-created OpenRouter client (see app.main.create_app)."""
    return request.app.state.openrouter


class CurrentUser:
    """Resolved identity for the current request.

    Constructed by get_current_user from the validated JWT claims. Passed to
    routers as a dependency; project-scoped routers additionally resolve a
    ProjectContext (Phase 1 domain layer) on top of this.
    """

    def __init__(self, sub: str, email: str | None, name: str, role: AppRole):
        self.sub = sub
        self.email = email
        self.name = name
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == AppRole.ADMIN

    def __repr__(self) -> str:
        return f"CurrentUser(sub={self.sub!r}, role={self.role.value!r})"


async def _maybe_refresh(request: Request) -> None:
    """Refresh the access token if it expires within the next 60 seconds.

    Mutates the session in place. On refresh failure, clears the session so the
    next request 401s cleanly rather than carrying a dead token.
    """
    session = request.session
    access = session.get(SK_ACCESS)
    refresh = session.get(SK_REFRESH)
    expires_at = session.get(SK_EXP, 0)

    if not access or not refresh:
        return
    if time.time() < expires_at - 60:
        return  # still fresh

    settings = get_settings()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": settings.keycloak_client_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.keycloak_token_endpoint, data=data)
        if resp.status_code != 200:
            raise TokenError(f"refresh failed: {resp.status_code}")
        tokens = resp.json()
    except (httpx.HTTPError, TokenError) as exc:
        logger.info("Token refresh failed, clearing session: %s", exc)
        session.clear()
        return

    session[SK_ACCESS] = tokens["access_token"]
    session[SK_REFRESH] = tokens.get("refresh_token", refresh)
    session[SK_EXP] = int(time.time()) + int(tokens.get("expires_in", 300))


async def get_current_user(request: Request) -> CurrentUser:
    """Resolve the authenticated user from the session's JWT.

    Pipeline: read access token from session → refresh if near expiry → validate
    via JWKS → resolve app role from groups claim.
    Raises HTTPException(401) if no session, token invalid, or refresh failed.
    """
    await _maybe_refresh(request)

    access = request.session.get(SK_ACCESS)
    if not access:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        claims = decode_access_token(access)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail="Token invalid or expired") from exc

    name = " ".join(filter(None, [claims.given_name, claims.family_name]))
    sub = claims.sub or claims.preferred_username or "unknown"
    return CurrentUser(
        sub=sub,
        email=claims.email,
        name=name or claims.preferred_username or sub,
        role=resolve_role(claims.groups),
    )


def require_role(*allowed: AppRole):
    """Dependency factory: require the caller's role to be in `allowed`.

    Usage: `@router.post(..., dependencies=[Depends(require_role(AppRole.ADMIN))])`
    """

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return _check

def get_qdrant(request: Request) -> AsyncQdrantClient:
    return request.app.state.qdrant

def get_storage(request: Request) -> StorageService:
    return request.app.state.storage

@dataclass
class ProjectContext:
    project: Projects
    user_db_id: UUID
    member_role: str

async def get_project_context(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectContext:
    """ Resolve a project + verify the user is a member.
    Returns 404(not 403) on non-membership to prevent enumeration.
    """

    user_repo = UserRepository(session)
    db_user = await user_repo.get_by_oidc_sub(user.sub)

    if db_user is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project_repo = ProjectRepository(session)
    project = await project_repo.get_by_id(project_id)

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    member_repo = ProjectMemberRepository(session)
    member = await member_repo.get(project_id, db_user.id)

    if member is None and not user.is_admin:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectContext(
        project=project,
        user_db_id=db_user.id,
        member_role=member.role if member else "admin",
    )

def get_arq_pool(request: Request) -> ArqRedis:
    """The lifespan created ar producer pool"""
    return request.app.state.arq_pool
