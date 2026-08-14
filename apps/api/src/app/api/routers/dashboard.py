"""The organisation dashboard, and the personal bits that feed it.

Two surfaces again, for the same reason as reminders: what you *set* is
personal (`/me/out-of-office`), and what you *see* is an organisation's
(`/organisations/{id}/dashboard`).
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.schemas.structure import PersonOut
from app.services import presence as presence_service
from app.services import reminders as reminders_service

router = APIRouter(tags=["dashboard"])


class AbsenceIn(BaseModel):
    starts_on: date
    ends_on: date
    note: str | None = Field(default=None, max_length=200)


class AbsenceOut(BaseModel):
    id: str
    starts_on: date
    ends_on: date
    note: str | None
    person: PersonOut | None = None
    # Away right now, as opposed to away somewhere in the next fortnight.
    away_now: bool = False


class AnnouncementIn(BaseModel):
    body: str = Field(min_length=1)
    sticky: bool = False
    expires_on: date | None = None


class AnnouncementOut(BaseModel):
    id: str
    body: str
    sticky: bool
    expires_on: date | None
    author: PersonOut | None
    created_at: datetime


class DashboardOut(BaseModel):
    announcements: list[AnnouncementOut]
    away: list[AbsenceOut]
    can_announce: bool


def _person(user) -> PersonOut | None:
    if user is None:
        return None
    return PersonOut(id=str(user.id), email=user.email, display_name=user.display_name)


def _absence(row, *, today: date, person=None) -> AbsenceOut:
    return AbsenceOut(
        id=str(row.id),
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        note=row.note,
        person=_person(person),
        away_now=presence_service.is_away(row, today=today),
    )


# --- mine -----------------------------------------------------------------------


@router.get("/me/out-of-office", response_model=list[AbsenceOut])
async def my_absences(user: CurrentUser, db: DbSession):
    today = reminders_service.today_for(user)
    return [_absence(a, today=today) for a in await presence_service.mine(db, user)]


@router.post(
    "/me/out-of-office", response_model=AbsenceOut, status_code=status.HTTP_201_CREATED
)
async def add_absence(body: AbsenceIn, user: CurrentUser, db: DbSession):
    """Yours to set. Colleagues in your organisations will see it — that is
    the point of recording it rather than remembering it."""
    row = await presence_service.add_absence(
        db, user, starts_on=body.starts_on, ends_on=body.ends_on, note=body.note
    )
    return _absence(row, today=reminders_service.today_for(user))


@router.delete("/me/out-of-office/{absence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_absence(absence_id: uuid.UUID, user: CurrentUser, db: DbSession):
    await presence_service.remove_absence(db, user, absence_id)


# --- the organisation's -----------------------------------------------------------


@router.get("/organisations/{org_id}/dashboard", response_model=DashboardOut)
async def dashboard(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """What you need to know before you ask anyone for anything.

    One request rather than three: it is the landing screen, and three
    round-trips to render one page is three chances to show it half-built.
    """
    today = datetime.now(ZoneInfo(user.timezone or "UTC")).date()
    away = await presence_service.away_in_org(db, ctx, today=today)
    notices = await presence_service.announcements(db, ctx, today=today)
    return DashboardOut(
        announcements=[
            AnnouncementOut(
                id=str(a.id),
                body=a.body,
                sticky=a.sticky,
                expires_on=a.expires_on,
                author=_person(author),
                created_at=a.created_at,
            )
            for a, author in notices
        ],
        away=[_absence(a, today=today, person=who) for a, who in away],
        can_announce=presence_service.can_announce(ctx.role),
    )


@router.post(
    "/organisations/{org_id}/announcements",
    response_model=AnnouncementOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_announcement(
    body: AnnouncementIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    row = await presence_service.post_announcement(
        db, ctx, user, body=body.body, sticky=body.sticky, expires_on=body.expires_on
    )
    return AnnouncementOut(
        id=str(row.id),
        body=row.body,
        sticky=row.sticky,
        expires_on=row.expires_on,
        author=_person(user),
        created_at=row.created_at,
    )


@router.delete(
    "/organisations/{org_id}/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_announcement(
    announcement_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    await presence_service.remove_announcement(db, ctx, announcement_id)
