"""Recurring tasks: a template that regenerates on a cadence.

Three rules:

1. **A series is its own thing, attached to a task, not a property of one.**
   `attach()` snapshots the task's current title, description, project,
   owner and priority into a new `TaskSeries` row and points the task at it.
   Editing the task afterwards never edits the series — the two are
   deliberately decoupled, the same way a reminder's note doesn't track a
   task's own description.

2. **Generation is on schedule, not on close.** The next occurrence appears
   when its date arrives, whether or not the previous one is done — like a
   calendar event, not a checklist. Two open occurrences of the same series
   can coexist; that's an honest backlog, not a bug to hide. See
   `models/task_series.py`.

3. **The sweep claims before it creates.** `try_claim` is a conditional
   `UPDATE … WHERE next_due_on = <the value just read> RETURNING …` — the
   same idempotency discipline as `services/reminders.py` and
   `services/deadlines.py`, adapted because the amount to advance by differs
   per series (a week here, a month there) and so can't be one shared value
   in a single statement the way `func.now()` is for the other two sweeps.
   If generation then fails (a project access problem, say), the occurrence
   is skipped rather than retried — the same trade `tasks/reminders.py`
   accepts, and for the identical reason: repeating on failure risks a
   duplicate, and a duplicate is the worse failure of the two.
"""

import calendar
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskSeries, User
from app.models.task_series import INTERVAL_UNITS
from app.services import access
from app.services.organisations import OrgContext


def advance(d: date, unit: str, count: int) -> date:
    """The next occurrence's date. Calendar-aware for months — `+1 month` on
    the 31st lands on the last day of the next month, not six days into the
    one after, which naive `timedelta(days=30)` arithmetic would do."""
    if unit == "day":
        return date.fromordinal(d.toordinal() + count)
    if unit == "week":
        return date.fromordinal(d.toordinal() + count * 7)
    month = d.month - 1 + count
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def can_manage(series: TaskSeries, *, user_id: uuid.UUID, org_role: str) -> bool:
    """Whoever set it up, or an admin. Not the same rule as editing the task
    it's attached to — a series can outlive that particular task, and by the
    time it does there may be no one task's access level to check against."""
    return series.created_by_user_id == user_id or access.administers_organisation(org_role)


async def attach(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    task: Task,
    *,
    interval_unit: str,
    interval_count: int,
) -> TaskSeries:
    """Turn a task into the first occurrence of a series.

    The task needs a due date already — that's what "the day it's due"
    means, and a series with no anchor date has nothing to advance from.
    """
    if interval_unit not in INTERVAL_UNITS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"interval must be one of {', '.join(INTERVAL_UNITS)}",
        )
    if interval_count < 1:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="interval must be at least 1",
        )
    if task.due_on is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="set a due date before making this repeat",
        )
    if task.series_id is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="this task already repeats"
        )

    series = TaskSeries(
        organisation_id=ctx.organisation.id,
        title=task.title,
        description=task.description,
        project_id=task.project_id,
        priority=task.priority,
        owner_user_id=task.owner_user_id,
        created_by_user_id=user.id,
        interval_unit=interval_unit,
        interval_count=interval_count,
        next_due_on=advance(task.due_on, interval_unit, interval_count),
    )
    db.add(series)
    await db.flush()
    task.series_id = series.id
    await db.commit()
    await db.refresh(series)
    # The commit expires every object in the session, `task` included — the
    # caller (`_task_response`) reads `task.updated_at` and friends right
    # after this returns, and an expired attribute triggers a lazy SELECT
    # that async SQLAlchemy can't run outside an awaited call, raising
    # `MissingGreenlet` instead of quietly refetching the way sync ORM would.
    await db.refresh(task)
    return series


async def stop(db: AsyncSession, ctx: OrgContext, user: User, series: TaskSeries) -> TaskSeries:
    """Stop generating future occurrences. Already-generated tasks are
    untouched — the same non-destructive default as un-pinning or hiding."""
    if not can_manage(series, user_id=user.id, org_role=ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="only whoever set this up, or an organisation admin, can stop it",
        )
    series.active = False
    await db.commit()
    await db.refresh(series)
    return series


async def get_or_404(db: AsyncSession, series_id: uuid.UUID, org_id: uuid.UUID) -> TaskSeries:
    row = (
        await db.execute(
            select(TaskSeries).where(
                TaskSeries.id == series_id, TaskSeries.organisation_id == org_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="not found")
    return row


async def for_tasks(db: AsyncSession, tasks: list[Task]) -> dict[uuid.UUID, TaskSeries]:
    """One lookup for a whole page — the same discipline as `_tags_for` and
    `_pinned_for`, so a task list never costs one query per row."""
    series_ids = {t.series_id for t in tasks if t.series_id}
    if not series_ids:
        return {}
    rows = (
        (await db.execute(select(TaskSeries).where(TaskSeries.id.in_(series_ids))))
        .scalars()
        .all()
    )
    return {s.id: s for s in rows}


# --- offboarding --------------------------------------------------------------


async def reassign_owned_series(
    db: AsyncSession, *, org_id: uuid.UUID, from_user_id: uuid.UUID, to_user_id: uuid.UUID
) -> int:
    """`task_series.owner_user_id` is RESTRICT, same as `tasks.owner_user_id`
    — without this, removing a member who owns a series fails the DELETE with
    a raw foreign-key error. Called from
    `organisations._reassign_everything_owned_by` alongside the task and
    project reassignment it already does."""
    rows = (
        (
            await db.execute(
                select(TaskSeries).where(
                    TaskSeries.organisation_id == org_id, TaskSeries.owner_user_id == from_user_id
                )
            )
        )
        .scalars()
        .all()
    )
    for series in rows:
        series.owner_user_id = to_user_id
    if rows:
        await db.commit()
    return len(rows)


# --- the sweep ------------------------------------------------------------------


async def timezones_in_use(db: AsyncSession) -> list[str]:
    """Distinct timezones of owners with an active series — same reasoning as
    `reminders.timezones_in_use` and `deadlines.timezones_in_use`: there's no
    single global "today" to check a due date against."""
    rows = (
        await db.execute(
            select(func.coalesce(User.timezone, "UTC"))
            .join(TaskSeries, TaskSeries.owner_user_id == User.id)
            .where(TaskSeries.active.is_(True))
            .distinct()
        )
    ).scalars().all()
    return list(rows)


async def due_in_zone(db: AsyncSession, *, tz_name: str) -> list[TaskSeries]:
    """Active series, owned by someone in this timezone, whose next
    occurrence has arrived — read-only; `try_claim` does the actual claim."""
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except (ZoneInfoNotFoundError, ValueError):
        today = datetime.now(ZoneInfo("UTC")).date()
    owner_in_zone = TaskSeries.owner_user_id.in_(
        select(User.id).where(func.coalesce(User.timezone, "UTC") == tz_name)
    )
    rows = (
        await db.execute(
            select(TaskSeries).where(
                TaskSeries.active.is_(True), TaskSeries.next_due_on <= today, owner_in_zone
            )
        )
    ).scalars().all()
    return list(rows)


async def try_claim(db: AsyncSession, series: TaskSeries) -> date | None:
    """Claim this occurrence and advance the pointer, or lose the race.

    `WHERE next_due_on = <the value already on `series`>` is the claim: it
    only succeeds if nothing has advanced this row since it was read, so two
    schedulers racing (or a retry after one crashes mid-sweep) produce one
    generated task, not two. Returns the due date the new task should carry
    — the value *before* this call advanced it — or `None` if the claim was
    lost, in which case the caller generates nothing.
    """
    due_on = series.next_due_on
    new_next = advance(due_on, series.interval_unit, series.interval_count)
    result = await db.execute(
        update(TaskSeries)
        .where(TaskSeries.id == series.id, TaskSeries.next_due_on == due_on)
        .values(next_due_on=new_next)
    )
    await db.commit()
    return due_on if result.rowcount else None


__all__ = [
    "advance",
    "attach",
    "can_manage",
    "due_in_zone",
    "for_tasks",
    "get_or_404",
    "reassign_owned_series",
    "stop",
    "timezones_in_use",
    "try_claim",
]
