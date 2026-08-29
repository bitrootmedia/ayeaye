"""Out-of-office and announcements — the two things a dashboard is for.

Three rules:

1. **Out-of-office is yours to set and everyone's to see.** Only you can add
   or remove your own; every member of an organisation you belong to can see
   it. A private OOO would be a diary — the whole value is that a colleague
   knows before they ask you for something.

2. **Announcements are per organisation and admin-authored.** There is no
   global administrator in this product — no staff tier, no backoffice — so
   there is nobody who *could* write to every installation. That's the
   architecture deciding, not a preference.

3. **Anything shown on a dashboard has to be able to expire.** A noticeboard
   nobody prunes is a noticeboard nobody reads, so an announcement can carry
   an end date and OOO is bounded by its own dates.
"""

import uuid
from datetime import date, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Announcement, OrganisationMember, OutOfOffice, User
from app.models.organisation import STATUS_ACTIVE
from app.services import access
from app.services.organisations import OrgContext

# How far ahead the dashboard looks. Two weeks is the horizon on which someone
# else's absence changes what you do today.
UPCOMING_DAYS = 14


# --- out of office ----------------------------------------------------------


async def mine(db: AsyncSession, user: User) -> list[OutOfOffice]:
    return list(
        (
            await db.execute(
                select(OutOfOffice)
                .where(OutOfOffice.user_id == user.id)
                .order_by(OutOfOffice.starts_on.desc())
            )
        )
        .scalars()
        .all()
    )


async def add_absence(
    db: AsyncSession, user: User, *, starts_on: date, ends_on: date, note: str | None
) -> OutOfOffice:
    if ends_on < starts_on:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="that period ends before it starts",
        )
    row = OutOfOffice(
        user_id=user.id,
        starts_on=starts_on,
        ends_on=ends_on,
        note=(note or "").strip()[:200] or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def remove_absence(db: AsyncSession, user: User, absence_id: uuid.UUID) -> None:
    """Yours, or it doesn't exist. 404 rather than 403: somebody else's diary
    is not something you're being told about."""
    row = (
        await db.execute(
            select(OutOfOffice).where(
                OutOfOffice.id == absence_id, OutOfOffice.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")
    await db.delete(row)
    await db.commit()


async def away_between(
    db: AsyncSession, ctx: OrgContext, *, start: date, end: date
) -> list[tuple[OutOfOffice, User]]:
    """Who is away at any point in `[start, end]`, among this organisation's
    members.

    Scoped to membership, not to task access: OOO is about people, and the
    people in your organisation are exactly who you might be waiting on. One
    statement, joined through the membership table. The window is a plain
    overlap test — started before the window ends, hasn't ended before the
    window starts — written that way rather than as two branches so a period
    spanning the whole window can't fall between them.
    """
    rows = (
        await db.execute(
            select(OutOfOffice, User)
            .join(User, User.id == OutOfOffice.user_id)
            .join(OrganisationMember, OrganisationMember.user_id == User.id)
            .where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.status == STATUS_ACTIVE,
                OutOfOffice.starts_on <= end,
                OutOfOffice.ends_on >= start,
            )
            .order_by(OutOfOffice.starts_on)
        )
    ).all()
    return [(a, u) for a, u in rows]


async def away_in_org(
    db: AsyncSession, ctx: OrgContext, *, today: date
) -> list[tuple[OutOfOffice, User]]:
    """Who is away now or soon — the dashboard's own fortnight-ahead window,
    on top of the general-purpose `away_between`."""
    return await away_between(db, ctx, start=today, end=today + timedelta(days=UPCOMING_DAYS))


def is_away(absence: OutOfOffice, *, today: date) -> bool:
    """Away *right now*, as opposed to away at some point in the window."""
    return absence.starts_on <= today <= absence.ends_on


# --- announcements -------------------------------------------------------------


def can_announce(org_role: str) -> bool:
    return access.administers_organisation(org_role)


async def announcements(
    db: AsyncSession, ctx: OrgContext, *, today: date
) -> list[tuple[Announcement, User | None]]:
    """Live notices, sticky ones first, newest first within each.

    An expired one is filtered here rather than deleted, so taking a notice
    down doesn't destroy the record that it was up.
    """
    rows = (
        await db.execute(
            select(Announcement, User)
            .outerjoin(User, User.id == Announcement.author_user_id)
            .where(
                Announcement.organisation_id == ctx.organisation.id,
                or_(Announcement.expires_on.is_(None), Announcement.expires_on >= today),
            )
            .order_by(Announcement.sticky.desc(), Announcement.created_at.desc())
        )
    ).all()
    return [(a, u) for a, u in rows]


async def post_announcement(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    body: str,
    sticky: bool,
    expires_on: date | None,
) -> Announcement:
    if not can_announce(ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only an organisation admin can post an announcement",
        )
    body = (body or "").strip()
    if not body:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="an announcement needs something to say",
        )
    row = Announcement(
        organisation_id=ctx.organisation.id,
        author_user_id=user.id,
        body=body,
        sticky=sticky,
        expires_on=expires_on,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def remove_announcement(
    db: AsyncSession, ctx: OrgContext, announcement_id: uuid.UUID
) -> None:
    if not can_announce(ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only an organisation admin can take an announcement down",
        )
    row = (
        await db.execute(
            select(Announcement).where(
                and_(
                    Announcement.id == announcement_id,
                    Announcement.organisation_id == ctx.organisation.id,
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="announcement not found"
        )
    await db.delete(row)
    await db.commit()
