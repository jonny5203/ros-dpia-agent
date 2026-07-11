"""Auth-related Pydantic models: app roles + the current-user shape.

Kept separate from jwks.py so routers/deps can import these without pulling in
the JWKS client (which hits the network on first use).
"""

from __future__ import annotations

from enum import StrEnum


class AppRole(StrEnum):
    """Application-level roles. Order matters for priority resolution.

    Higher in the enum = higher privilege. resolve_role() walks the enum in
    this order and returns the first group the user belongs to.
    """

    ADMIN = "admin"
    PRIVACY_OFFICER = "privacy-officer"
    IT_SECURITY = "it-security"
    PROJECT_MANAGER = "project-manager"
    VIEWER = "viewer"


# Priority order — most privileged first. Matches the enum declaration order.
_ROLE_PRIORITY: list[AppRole] = [
    AppRole.ADMIN,
    AppRole.PRIVACY_OFFICER,
    AppRole.IT_SECURITY,
    AppRole.PROJECT_MANAGER,
    AppRole.VIEWER,
]


def resolve_role(groups: list[str]) -> AppRole:
    """Map Keycloak groups to a single app role by priority.

    A user in [admin, viewer] resolves to admin. A user with no recognized
    group defaults to VIEWER (least privilege — safe failure mode).
    """
    group_set = set(groups)
    for role in _ROLE_PRIORITY:
        # Keycloak group mapper may emit "/admin" or "admin" depending on
        # the full.path config — handle both.
        if role.value in group_set or f"/{role.value}" in group_set:
            return role
    return AppRole.VIEWER


# Session-cookie keys. Declared here so both router.py (writes) and deps.py
# (reads) depend on a neutral module rather than each other (avoids a circular
# import between the auth router and the deps that consume it).
SK_VERIFIER = "pkce_verifier"
SK_STATE = "oauth_state"
SK_ACCESS = "access_token"
SK_REFRESH = "refresh_token"
SK_ID = "id_token"
SK_EXP = "expires_at"
