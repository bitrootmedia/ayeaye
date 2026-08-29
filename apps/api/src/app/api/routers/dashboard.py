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
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Project, Task, User
from app.schemas.structure import PersonOut
from app.services import access as access_service
from app.services import pins as pins_service
from app.services import presence as presence_service
from app.services import reminders as reminders_service
from app.services.organisations import OrgContext

# How close a due date has to be to earn a place on the dashboard. Two days:
# close enough to actually change what you do today, not a whole sprint's
# worth of "coming up".
DUE_SOON_DAYS = 2

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


class DashboardTaskOut(BaseModel):
    id: str
    title: str
    status: str
    project_id: str | None
    project_name: str | None
    due_on: date | None
    is_owner: bool
    # The one that actually needs you, as opposed to work of yours that's
    # merely on one of these cards. Mutually exclusive in practice with
    # `waiting_on` being set: if it's yours to act on, there's nobody else to
    # wait for.
    is_action_required: bool
    # Who the owner is waiting on — set only when the caller owns the task,
    # somebody's been asked, and it isn't the caller. `None` covers both
    # "nobody's been asked yet" and "it's on me" (`is_action_required` already
    # says the second one).
    waiting_on: PersonOut | None
    # Coloured on the client: red past due, amber due today. Computed here,
    # against the same per-timezone `today` the whole dashboard resolves once
    # — the alternative is the browser guessing a "today" that disagrees with
    # the server's, which is exactly wrong the one day it matters, at midnight.
    is_overdue: bool
    is_due_today: bool


class RecentTaskOut(BaseModel):
    """One row of 'what changed' — organisation-wide, not narrowed to the
    caller's own work, which is what makes it a different card from the
    escalation ones above. A comment, a file, a status change: anything that
    calls `tasks_service.announce()` bumps the `updated_at` this sorts by."""

    id: str
    title: str
    status: str
    project_id: str | None
    project_name: str | None
    owner: PersonOut | None
    is_open: bool
    updated_at: datetime


class DashboardOut(BaseModel):
    announcements: list[AnnouncementOut]
    away: list[AbsenceOut]
    can_announce: bool
    # Open and mine — either I own it or I'm asked to act — one list per
    # priority shown, each its own card. Not "critical/urgent in the
    # organisation": an admin sees everything already, and mailing them every
    # critical task in the company is exactly the notification-fatigue
    # mistake the comment socket avoids elsewhere.
    critical: list[DashboardTaskOut]
    urgent: list[DashboardTaskOut]
    due_soon: list[DashboardTaskOut]
    # The caller's own bookmarks — see services/pins.py. Nobody else's
    # dashboard shows these, the same way nobody else's shows their planner.
    pinned: list[DashboardTaskOut]
    # Org-wide, not "mine" — the one card on this screen that answers "what
    # is everybody up to" rather than "what needs me".
    recent: list[RecentTaskOut]


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


async def _build_dashboard_tasks(
    db: DbSession, user: User, tasks: list[Task], *, today: date
) -> list[DashboardTaskOut]:
    """Shared shaping for every escalation card — Critical, Urgent, Due soon,
    Pinned. One function so the four cards can't quietly drift into four
    slightly different answers for "is this waiting on someone else"."""
    if not tasks:
        return []

    project_ids = {t.project_id for t in tasks if t.project_id}
    project_names: dict = {}
    if project_ids:
        rows = (
            await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
        ).all()
        project_names = {pid: name for pid, name in rows}

    # Only for tasks the caller owns, where somebody else has been asked —
    # the same set `waiting_on` gets filled in for below.
    waiting_ids = {
        t.action_required_user_id
        for t in tasks
        if t.owner_user_id == user.id
        and t.action_required_user_id
        and t.action_required_user_id != user.id
    }
    waiting_people: dict = {}
    if waiting_ids:
        rows = (await db.execute(select(User).where(User.id.in_(waiting_ids)))).scalars().all()
        waiting_people = {u.id: u for u in rows}

    out = []
    for t in tasks:
        is_owner = t.owner_user_id == user.id
        waiting_for = (
            waiting_people.get(t.action_required_user_id)
            if is_owner and t.action_required_user_id and t.action_required_user_id != user.id
            else None
        )
        out.append(
            DashboardTaskOut(
                id=str(t.id),
                title=t.title,
                status=t.status,
                project_id=str(t.project_id) if t.project_id else None,
                project_name=project_names.get(t.project_id) if t.project_id else None,
                due_on=t.due_on,
                is_owner=is_owner,
                is_action_required=t.action_required_user_id == user.id,
                waiting_on=_person(waiting_for),
                is_overdue=bool(t.due_on and t.due_on < today),
                is_due_today=bool(t.due_on and t.due_on == today),
            )
        )
    return out


async def _priority_tasks(
    db: DbSession, ctx: OrgContext, user: User, *, priority: str, today: date
) -> list[DashboardTaskOut]:
    stmt = access_service.my_priority_tasks_stmt(
        user_id=user.id, org_id=ctx.organisation.id, org_role=ctx.role, priority=priority
    )
    tasks = [t for t, _level in (await db.execute(stmt)).all()]
    return await _build_dashboard_tasks(db, user, tasks, today=today)


async def _due_soon_tasks(
    db: DbSession, ctx: OrgContext, user: User, *, today: date
) -> list[DashboardTaskOut]:
    stmt = access_service.my_due_soon_tasks_stmt(
        user_id=user.id,
        org_id=ctx.organisation.id,
        org_role=ctx.role,
        today=today,
        horizon_days=DUE_SOON_DAYS,
    )
    tasks = [t for t, _level in (await db.execute(stmt)).all()]
    return await _build_dashboard_tasks(db, user, tasks, today=today)


async def _pinned_tasks(
    db: DbSession, ctx: OrgContext, user: User, *, today: date
) -> list[DashboardTaskOut]:
    stmt = pins_service.my_pinned_tasks_stmt(user_id=user.id, ctx=ctx)
    tasks = [t for t, _pinned_at in (await db.execute(stmt)).all()]
    return await _build_dashboard_tasks(db, user, tasks, today=today)


async def _recent_tasks(
    db: DbSession, ctx: OrgContext, user: User, *, limit: int = 10
) -> list[RecentTaskOut]:
    stmt = access_service.visible_tasks_stmt(
        user_id=user.id,
        org_id=ctx.organisation.id,
        org_role=ctx.role,
        include_closed=True,
        sort="updated_at",
        descending=True,
    ).limit(limit)
    tasks = [t for t, _level in (await db.execute(stmt)).all()]
    if not tasks:
        return []

    project_ids = {t.project_id for t in tasks if t.project_id}
    project_names: dict = {}
    if project_ids:
        rows = (
            await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
        ).all()
        project_names = {pid: name for pid, name in rows}

    owner_ids = {t.owner_user_id for t in tasks}
    owners: dict = {}
    if owner_ids:
        rows = (await db.execute(select(User).where(User.id.in_(owner_ids)))).scalars().all()
        owners = {u.id: u for u in rows}

    return [
        RecentTaskOut(
            id=str(t.id),
            title=t.title,
            status=t.status,
            project_id=str(t.project_id) if t.project_id else None,
            project_name=project_names.get(t.project_id) if t.project_id else None,
            owner=_person(owners.get(t.owner_user_id)),
            is_open=t.closed_at is None,
            updated_at=t.updated_at,
        )
        for t in tasks
    ]


# --- the organisation's -----------------------------------------------------------


@router.get("/organisations/{org_id}/dashboard", response_model=DashboardOut)
async def dashboard(ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """What you need to know before you ask anyone for anything.

    One request rather than several: it is the landing screen, and rendering
    it in stages looks broken.
    """
    today = datetime.now(ZoneInfo(user.timezone or "UTC")).date()
    away = await presence_service.away_in_org(db, ctx, today=today)
    notices = await presence_service.announcements(db, ctx, today=today)
    critical = await _priority_tasks(db, ctx, user, priority="critical", today=today)
    urgent = await _priority_tasks(db, ctx, user, priority="urgent", today=today)
    due_soon = await _due_soon_tasks(db, ctx, user, today=today)
    pinned = await _pinned_tasks(db, ctx, user, today=today)
    recent = await _recent_tasks(db, ctx, user)
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
        critical=critical,
        urgent=urgent,
        due_soon=due_soon,
        pinned=pinned,
        recent=recent,
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
