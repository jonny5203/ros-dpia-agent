"""Admin-only test scaffold to prove global-role RBAC (Phase 1).

The require_role() dependency resolves the caller from the session JWT and
rejects anyone whose AppRole isn't in the allowed set. This router exists to
exercise that mechanism end-to-end; real project-scoped routes land with the
domain layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, require_role
from app.auth.models import AppRole

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/whoami")
async def whoami(
    user: CurrentUser = Depends(require_role(AppRole.ADMIN)),
) -> dict:
    return {
        "sub": user.sub,
        "role": user.role.value,
        "message": "admin access granted",
    }
