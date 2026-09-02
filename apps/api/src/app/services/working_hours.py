"""Working hours: yours to set, and any colleague's to see.

Two rules, and they mirror `services/presence.py`'s own out-of-office rules
almost exactly — this is the same shape of feature, a personal weekly
pattern rather than a personal date range.

1. **Only you can set your own.** `set_cell`/`clear_cell` take the caller's
   own `User`, never a target id — there is no admin override here, the same
   absence-of-a-branch discipline `services/notes.py` documents for private
   notes, just applied to a fact this product doesn't actually keep private.

2. **Visible to anyone who shares an organisation with you.** Not private,
   deliberately — the whole value of recording this rather than leaving it
   in someone's head is a colleague checking it before they ask when to
   expect a reply. `for_member` is scoped to membership, the identical
   pattern `presence.away_between` uses, not to any finer-grained access.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrganisationMember, User, WorkingHour
from app.models.organisation import STATUS_ACTIVE
from app.services.organisations import OrgContext


async def mine(db: AsyncSession, user: User) -> list[WorkingHour]:
    return list(
        (await db.execute(select(WorkingHour).where(WorkingHour.user_id == user.id)))
        .scalars()
        .all()
    )


async def set_cell(db: AsyncSession, user: User, *, weekday: int, hour: int) -> None:
    """Idempotent — marking an already-marked hour is a no-op, not a second
    row or a 409 somebody has to interpret. The identical `ON CONFLICT DO
    NOTHING` idiom `sheets.check_cell` uses."""
    await db.execute(
        pg_insert(WorkingHour)
        .values(user_id=user.id, weekday=weekday, hour=hour)
        .on_conflict_do_nothing(constraint="uq_working_hours_user_weekday_hour")
    )
    await db.commit()


async def clear_cell(db: AsyncSession, user: User, *, weekday: int, hour: int) -> None:
    await db.execute(
        delete(WorkingHour).where(
            WorkingHour.user_id == user.id,
            WorkingHour.weekday == weekday,
            WorkingHour.hour == hour,
        )
    )
    await db.commit()


async def for_member(
    db: AsyncSession, ctx: OrgContext, member_user_id: uuid.UUID
) -> tuple[User, list[WorkingHour]]:
    """A colleague's grid. No access reads as 404 here exactly as everywhere
    else: a stranger's id and a real person outside this organisation look
    identical from the caller's side, and there's nothing to distinguish
    them by that isn't itself a leak."""
    target = (
        await db.execute(
            select(User)
            .join(OrganisationMember, OrganisationMember.user_id == User.id)
            .where(
                User.id == member_user_id,
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")
    cells = list(
        (await db.execute(select(WorkingHour).where(WorkingHour.user_id == member_user_id)))
        .scalars()
        .all()
    )
    return target, cells
