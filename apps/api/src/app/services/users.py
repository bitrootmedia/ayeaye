"""Local mirror of SuperTokens identity.

SuperTokens owns the credentials; this keeps a row per person in OUR database so
other tables can foreign-key to a user and so we can address people by email —
which is how organisation invites work.
"""

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security.authn import get_user_email

logger = logging.getLogger("app.services.users")


async def get_or_create(db: AsyncSession, *, supertokens_user_id: str) -> User:
    """Return the local row for a SuperTokens user, creating it on first sight.

    Lazily, rather than via a SuperTokens signup override, because the override
    would miss anyone created through the dashboard or before this table existed.
    """
    user = await _by_supertokens_id(db, supertokens_user_id)
    if user is not None:
        return user

    email = (await get_user_email(supertokens_user_id) or "").lower()

    # ON CONFLICT rather than check-then-insert: a freshly logged-in SPA fires
    # several requests at once, so two of them racing to create the same user
    # is the normal case, not an edge case.
    await db.execute(
        pg_insert(User)
        .values(supertokens_user_id=supertokens_user_id, email=email)
        .on_conflict_do_nothing(index_elements=["supertokens_user_id"])
    )
    await db.commit()

    user = await _by_supertokens_id(db, supertokens_user_id)
    if user is None:  # pragma: no cover - only reachable if the insert vanished
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not establish local user",
        )

    # Claim any invitation addressed to this email but sent before they had an
    # account. It must happen here, on the first authenticated request, or the
    # person signs up from an invite link and lands on an empty shell that
    # gives no sign the invitation ever existed.
    #
    # Attaches only — it does not join them. See models/organisation.py.
    #
    # Imported inside the function: services.invites imports
    # services.organisations, which has no business being pulled in by every
    # module that just wants a user row.
    from app.services import invites as invites_service

    bound = await invites_service.bind_pending_for_user(db, user)
    if bound:
        logger.info("bound %d pending invitation(s) to new user %s", bound, user.id)

    return user


async def _by_supertokens_id(db: AsyncSession, supertokens_user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.supertokens_user_id == supertokens_user_id))
    return result.scalar_one_or_none()


async def get_by_local_id(db: AsyncSession, user_id) -> User | None:
    """By our own id. The realtime socket resolves the SuperTokens id once at
    connect time and then only has the local one."""
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


# Alias kept explicit rather than clever: the socket asks for "or create" by
# habit, but a local id that doesn't exist is a bug, not a first sighting.
get_or_create_by_local_id = get_by_local_id


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def update_profile(
    db: AsyncSession,
    user: User,
    *,
    display_name: str | None = None,
    timezone: str | None = None,
    status_message: str | None = None,
    daily_summary_enabled: bool | None = None,
) -> User:
    if display_name is not None:
        user.display_name = display_name.strip() or None
    if timezone is not None:
        user.timezone = _valid_timezone(timezone)
    if status_message is not None:
        user.status_message = status_message.strip()[:140] or None
    if daily_summary_enabled is not None:
        user.daily_summary_enabled = daily_summary_enabled
    await db.commit()
    await db.refresh(user)
    return user


def _valid_timezone(name: str) -> str | None:
    """Accept an IANA name, ignore anything else.

    The browser sends this automatically, so a value nobody typed must never
    be able to fail a request — and a junk one must never be stored, because
    the reminder sweep groups by this column and would then run a whole extra
    pass for a timezone that doesn't exist.
    """
    name = (name or "").strip()
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.info("ignoring unknown timezone %r", name)
        return None
    return name[:64]
