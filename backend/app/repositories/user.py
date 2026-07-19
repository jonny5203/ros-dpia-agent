from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Users

class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_oidc_sub(self, oidc_sub: str) -> Users | None:
        stmt = select(Users).where(Users.oidc_sub == oidc_sub)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> Users | None:
        return await self.session.get(Users, user_id)

    async def upsert(
        self,
        oidc_sub: str,
        email: str,
        display_name: str,
        app_role: str,
        is_admin: bool,
    ) -> Users:
        existing = await self.get_by_oidc_sub(oidc_sub)
        if existing:
            existing.email = email
            existing.display_name = display_name
            existing.app_role = app_role
            existing.is_admin = is_admin
            await self.session.flush()
            return existing
        user = Users(
            oidc_sub=oidc_sub,
            email=email,
            display_name=display_name,
            app_role=app_role,
            is_admin=is_admin
        )
        self.session.add(user)
        await self.session.flush()
        return user
