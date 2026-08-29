"""Reminders, and the sweep that fires them.

Four rules:

1. **A reminder is personal.** Yours to set, yours to see, yours to dismiss.
   No endpoint takes a user id, and every statement filters on the caller.
   Putting something in someone else's queue is what action-required is for.

2. **You need `read` on the task.** Same as logging time: it's a note to self
   about work you can see. Losing access takes the reminder out of your list
   with the task — it isn't deleted, and it comes back if access does.

3. **The sweep is idempotent.** It claims each row with a conditional UPDATE
   before sending anything, so a scheduler that restarts mid-run, or two of
   them racing, produces one notification rather than two. This is the rule
   that fails *silently* in the worst direction: nobody notices a duplicate
   until it has happened to everyone at once.

4. **"The day before" needs a timezone.** A date has no instant attached, so
   whose Friday it is has to come from somewhere. `users.timezone` is filled
   in automatically from the browser (see `GET /me`), and falls back to UTC —
   which is wrong by at most a few hours for anyone who has never opened the
   app, and those people have no reminders.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder, Task, User
from app.models.reminder import MAX_NOTE_LENGTH, MAX_TITLE_LENGTH
from app.services import access
from app.services.organisations import OrgContext

logger = logging.getLogger("app.services.reminders")

# How far ahead the "coming up" nudge goes out. One day, because that is what
# makes a reminder useful for something you have to prepare for.
AHEAD_DAYS = 1


def today_for(user: User) -> date:
    """What day it is *for this person*.

    The whole reason `users.timezone` exists. A reminder set for the 14th
    should fire on their 14th, not on UTC's — which for anyone west of London
    means an evening reminder arriving the day before.
    """
    return datetime.now(zone_for(user)).date()


def zone_for(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        # A junk timezone from a client must not stop somebody's reminders.
        logger.warning("unknown timezone %r for user %s", user.timezone, user.id)
        return ZoneInfo("UTC")


def is_overdue(remind_on: date, *, today: date) -> bool:
    """Today counts as due. A reminder for today that reads as "upcoming"
    is one you don't act on until tomorrow."""
    return remind_on <= today


# --- reads ---------------------------------------------------------------------


def mine_stmt(*, user_id: uuid.UUID, ctx: OrgContext | None = None) -> Select:
    """The caller's reminders — task-anchored ones on tasks they can still
    see, plus standalone ones. `Task` comes back `None` for a standalone row;
    every caller has to handle that rather than assuming a task exists.

    Organisation-scoped when a context is given, and across everything when
    it isn't: the badge in the rail is a personal, cross-organisation count,
    the same way the notification bell is. You don't want to discover a missed
    reminder by switching organisation.
    """
    stmt = (
        select(Reminder, Task)
        .outerjoin(Task, Task.id == Reminder.task_id)
        .where(Reminder.user_id == user_id, Reminder.done_at.is_(None))
        .order_by(Reminder.remind_on, Reminder.id)
    )
    if ctx is not None:
        stmt = stmt.where(
            or_(
                and_(
                    Reminder.task_id.isnot(None),
                    Task.organisation_id == ctx.organisation.id,
                    Task.id.in_(
                        access.visible_task_ids_stmt(
                            user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role
                        )
                    ),
                ),
                Reminder.organisation_id == ctx.organisation.id,
            )
        )
    return stmt


async def for_task(db: AsyncSession, task_id: uuid.UUID, user: User) -> list[Reminder]:
    return list(
        (
            await db.execute(
                select(Reminder)
                .where(
                    Reminder.task_id == task_id,
                    Reminder.user_id == user.id,
                    Reminder.done_at.is_(None),
                )
                .order_by(Reminder.remind_on)
            )
        )
        .scalars()
        .all()
    )


async def due_count(db: AsyncSession, user: User) -> int:
    """How many are due or overdue, across every organisation.

    Drives the red badge. Cross-organisation on purpose — a reminder you set
    in one place must not be invisible because you're looking at another.

    **Not scoped by task visibility**, and that is deliberate: this is a count,
    not a list, and a badge that silently under-reports is worse than one that
    occasionally points at a task you can no longer open. The list endpoint
    does apply visibility, so clicking through is always honest.
    """
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(Reminder)
                .where(
                    Reminder.user_id == user.id,
                    Reminder.done_at.is_(None),
                    Reminder.remind_on <= today_for(user),
                )
            )
        ).scalar_one()
    )


# --- writes ----------------------------------------------------------------------


def _new_reminder(
    *, user: User, remind_on: date, note: str | None, task_id=None, organisation_id=None, title=None
) -> Reminder:
    if remind_on is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a reminder needs a date",
        )
    row = Reminder(
        task_id=task_id,
        organisation_id=organisation_id,
        user_id=user.id,
        remind_on=remind_on,
        title=title,
        note=(note or "").strip()[:MAX_NOTE_LENGTH] or None,
    )
    # A reminder set for today or the past is legitimate — "remind me about
    # this, I've already let it slip" — and it shows as due immediately. What
    # it must NOT do is send a "coming up tomorrow" nudge for a day that has
    # already gone, so both stamps are pre-set for windows already passed.
    if remind_on <= today_for(user):
        row.notified_ahead_at = func.now()
    return row


async def create(
    db: AsyncSession, task: Task, user: User, *, remind_on: date, note: str | None
) -> Reminder:
    row = _new_reminder(user=user, remind_on=remind_on, note=note, task_id=task.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def create_standalone(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    remind_on: date,
    title: str,
    note: str | None,
) -> Reminder:
    """A reminder about nothing in particular — no task behind it, just a
    date and what it's about. Still organisation-scoped (`ck_reminders_org_iff_standalone`),
    because the calendar reads reminders one organisation at a time and needs
    somewhere to filter from."""
    title = (title or "").strip()[:MAX_TITLE_LENGTH]
    if not title:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="a standalone reminder needs something to call it",
        )
    row = _new_reminder(
        user=user,
        remind_on=remind_on,
        note=note,
        organisation_id=ctx.organisation.id,
        title=title,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_or_404(db: AsyncSession, reminder_id: uuid.UUID, user: User) -> Reminder:
    """Yours, or it doesn't exist. Not 403 — somebody else's reminder is not
    something you are being told about."""
    row = (
        await db.execute(
            select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="reminder not found"
        )
    return row


async def update_one(
    db: AsyncSession, reminder: Reminder, user: User, *, fields: dict
) -> Reminder:
    if "remind_on" in fields and fields["remind_on"] != reminder.remind_on:
        reminder.remind_on = fields["remind_on"]
        # Moved to a new day, so the old firings no longer apply. Clearing
        # these is what makes "snooze until next week" actually notify again.
        reminder.notified_ahead_at = None
        reminder.notified_due_at = None
        if reminder.remind_on <= today_for(user):
            reminder.notified_ahead_at = func.now()
    if "note" in fields:
        reminder.note = (fields["note"] or "").strip()[:MAX_NOTE_LENGTH] or None
    # Only meaningful for a standalone reminder — a task-anchored one has no
    # `title` column value to change (see `ck_reminders_one_anchor`), and the
    # router never sends this field for one.
    if "title" in fields and reminder.task_id is None:
        title = (fields["title"] or "").strip()[:MAX_TITLE_LENGTH]
        if not title:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="a standalone reminder needs something to call it",
            )
        reminder.title = title
    if "done" in fields:
        reminder.done_at = func.now() if fields["done"] else None
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def remove(db: AsyncSession, reminder: Reminder) -> None:
    await db.delete(reminder)
    await db.commit()


# --- the sweep --------------------------------------------------------------------


async def timezones_in_use(db: AsyncSession) -> list[str]:
    """The distinct timezones of people with a live reminder.

    The sweep can't use one global "today": a reminder set for the 14th has to
    fire on *that person's* 14th. Doing it per user would be a query per row,
    so it's done per timezone instead — in practice one or two, and never more
    than the number of places the team actually sits.
    """
    rows = (
        await db.execute(
            select(func.coalesce(User.timezone, "UTC"))
            .join(Reminder, Reminder.user_id == User.id)
            .where(Reminder.done_at.is_(None))
            .distinct()
        )
    ).scalars().all()
    return [tz for tz in rows]


def _in_timezone(tz_name: str):
    """Users whose local day is the one being swept. NULL means UTC."""
    return Reminder.user_id.in_(
        select(User.id).where(func.coalesce(User.timezone, "UTC") == tz_name)
    )


async def claim(db: AsyncSession, *, tz_name: str, ahead: bool) -> list[uuid.UUID]:
    """Claim every reminder in this timezone whose window has arrived.

    **One conditional UPDATE that both selects and marks.** `WHERE <stamp> IS
    NULL` is the claim: whoever runs it first sets the stamp, and a second run
    matches nothing and sends nothing. Select-then-update would leave a window
    where two runners each think the row is theirs — which is precisely the
    duplicate email this exists to prevent, and it only shows up under exactly
    the conditions nobody tests by hand (a restart, a retry, two containers).

    `<=` rather than `==` on the date, so a sweep that missed its slot — the
    machine was asleep, the container was down — still fires what it slept
    through instead of skipping it forever.
    """
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        today = datetime.now(ZoneInfo("UTC")).date()

    column = Reminder.notified_ahead_at if ahead else Reminder.notified_due_at
    when = today + timedelta(days=AHEAD_DAYS) if ahead else today

    rows = (
        await db.execute(
            update(Reminder)
            .where(
                Reminder.done_at.is_(None),
                column.is_(None),
                Reminder.remind_on <= when,
                _in_timezone(tz_name),
            )
            .values({column: func.now()})
            .returning(Reminder.id)
        )
    ).scalars().all()
    await db.commit()
    return list(rows)


def visible_and_due(reminders: list[tuple[Reminder, Task | None]], *, today: date):
    """Split a list into due-or-overdue and upcoming. Pure, so the boundary
    ("today counts as due") is testable without a database."""
    due = [(r, t) for r, t in reminders if is_overdue(r.remind_on, today=today)]
    upcoming = [(r, t) for r, t in reminders if not is_overdue(r.remind_on, today=today)]
    return due, upcoming


__all__ = [
    "AHEAD_DAYS",
    "claim",
    "create",
    "create_standalone",
    "due_count",
    "for_task",
    "get_or_404",
    "is_overdue",
    "mine_stmt",
    "remove",
    "timezones_in_use",
    "today_for",
    "update_one",
    "visible_and_due",
    "zone_for",
]
