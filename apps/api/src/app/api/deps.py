"""Shared route dependencies.

The `Annotated` aliases below keep router signatures short and consistent —
`db: DbSession` instead of repeating `Depends(get_session)` on every endpoint.
"""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security.authn import VerifiedSession
from app.services import organisations as orgs_service
from app.services import users as users_service
from app.services.organisations import OrgContext

# One database session per request.
DbSession = Annotated[AsyncSession, Depends(get_session)]

# A verified SuperTokens session. Use CurrentUser unless you need the container.
CurrentSession = VerifiedSession


async def get_current_user_id(session: CurrentSession) -> str:
    return session.get_user_id()


CurrentUserId = Annotated[str, Depends(get_current_user_id)]


async def get_current_user(user_id: CurrentUserId, db: DbSession) -> User:
    """The local user row, created on first sight."""
    return await users_service.get_or_create(db, supertokens_user_id=user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_org_context(org_id: uuid.UUID, user: CurrentUser, db: DbSession) -> OrgContext:
    """The organisation named in the path, plus the caller's membership of it.

    Every organisation-scoped route depends on this, so the "are you even in
    here" question is asked exactly once, in one place, and answers **404**
    rather than 403 — see `services.organisations.context_for`.

    Routes then ask `ctx.require(...)` for the finer question of whether their
    role is enough, which is the only thing that legitimately answers 403.
    """
    return await orgs_service.context_for(db, org_id, user)


CurrentOrg = Annotated[OrgContext, Depends(get_org_context)]
