"""Time tracking: timers, manual entries, corrections and rollups.

Four rules, and the first is a database constraint rather than a convention:

1. **One running timer per person, globally.** A partial unique index on
   `(user_id) WHERE ended_at IS NULL`. Not scoped per organisation — you are
   only doing one thing at a time, and a per-org constraint would let someone
   run three timers by belonging to three organisations.

2. **Starting a timer stops the one already running.** Not an error. Switching
   tasks is the commonest thing anyone does with a time tracker, and refusing
   with a 409 means the answer to "why won't it start" is a modal. The stopped
   entry is kept and both tasks get a history row.

3. **`read` on a task is enough to log your own time.** Time is a record of
   what *you* did. Refusing to let a contractor with view access record their
   own hours is the wrong failure — and they still cannot change the task.

4. **Entries stay editable, with a trail.** PLAN.md §9 settles this: people
   forget to stop timers, and a timesheet everyone knows is wrong is worse than
   one that records its own corrections. Every edit writes a `task_events` row
   and stamps `edited_at`.

Only the person who logged an entry, or an organisation admin, may change it.
A task's owner cannot edit someone else's timesheet — it isn't theirs.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Task, TimeEntry, User
from app.models.task import EVENT_TIME_DELETED, EVENT_TIME_EDITED, EVENT_TIME_LOGGED
from app.services import access
from app.services import tasks as tasks_service
from app.services.organisations import OrgContext

# A single entry longer than this is almost always a forgotten timer or a typo
# in a manual entry. Rejected on manual input, and flagged (not rejected) when
# a timer is stopped — by then the time has genuinely passed and refusing to
# record it would just lose the data.
MAX_ENTRY_HOURS = 24

# --- pure. no database, no request. -----------------------------------------


def duration_seconds(started_at: datetime, ended_at: datetime | None, *, now: datetime) -> int:
    """How long an entry has run. A running entry is measured against `now`."""
    end = ended_at or now
    return max(0, int((end - started_at).total_seconds()))


def format_duration(seconds: int) -> str:
    """`"1h 30m"`. Minutes only below an hour, and never "0h 5m"."""
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def validate_manual(
    *, started_at: datetime, ended_at: datetime, now: datetime
) -> None:
    """Reject the three ways a manual entry is wrong.

    All three are mistakes rather than intentions, and each one poisons every
    rollup it lands in — which is discovered a month later when the numbers
    don't add up.
    """
    if ended_at <= started_at:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="that entry ends before it starts",
        )
    if started_at > now + timedelta(minutes=5):
        # Five minutes of slack for clock skew between browser and server.
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="you can't log time in the future",
        )
    if (ended_at - started_at) > timedelta(hours=MAX_ENTRY_HOURS):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"a single entry can't be longer than {MAX_ENTRY_HOURS} hours",
        )


def can_edit_entry(*, entry_user_id: uuid.UUID, actor_id: uuid.UUID, org_role: str) -> bool:
    """Your own, or an organisation admin's override.

    Deliberately **not** the task owner: someone else's timesheet is not theirs
    to correct, even on work they're responsible for.
    """
    return entry_user_id == actor_id or access.administers_organisation(org_role)


# --- reads -------------------------------------------------------------------


def entries_in_scope(*, user_id: uuid.UUID, ctx: OrgContext):
    """Which entries this person may see — **theirs, plus everyone's on tasks
    they can see.**

    The first half of that OR is not redundant, and it is not a leak.
    `visible_task_ids_stmt` composes the task access expression, so the moment
    a task is hidden — or a grant revoked — every entry on it disappears from
    the rollups. Without the OR, **your own logged hours vanish from your own
    timesheet** because somebody else changed the task's visibility. A
    contractor watching their week's total drop overnight has no way to tell
    that from a bug.

    What it exposes is your own row about your own work: a task title you
    demonstrably could see at the time you logged against it. Losing the hours
    is the worse failure of the two, so the OR stays.

    Other people's entries still require task visibility. That half is
    unchanged.
    """
    return or_(
        and_(
            TimeEntry.user_id == user_id,
            # Still this organisation. Timers are global — one per person
            # across the installation — so without this your hours from
            # another organisation would land in this one's rollups.
            TimeEntry.task_id.in_(
                select(Task.id).where(Task.organisation_id == ctx.organisation.id)
            ),
        ),
        TimeEntry.task_id.in_(
            access.visible_task_ids_stmt(
                user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role
            )
        ),
    )


def _visible_entries_stmt(*, user_id: uuid.UUID, ctx: OrgContext) -> Select:
    """Every entry the caller may see, as a statement."""
    return select(TimeEntry).where(entries_in_scope(user_id=user_id, ctx=ctx))


async def running_for(db: AsyncSession, user: User) -> TimeEntry | None:
    """The caller's running timer, wherever it is.

    Not organisation-scoped: there is one per person across the whole
    installation, and the header needs to show it even when you've switched
    organisations — otherwise you find it still running tomorrow.
    """
    return (
        await db.execute(
            select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.ended_at.is_(None))
        )
    ).scalar_one_or_none()


async def list_for_task(
    db: AsyncSession, ctx: OrgContext, user: User, task_id: uuid.UUID
) -> list[tuple[TimeEntry, User]]:
    """Everyone's entries on one task.

    Anyone who can read the task sees them all, with names. A work log that
    hides who did what can't answer the question it exists for.
    """
    await tasks_service.context_for(db, ctx, task_id, user)
    rows = (
        await db.execute(
            select(TimeEntry, User)
            .join(User, User.id == TimeEntry.user_id)
            .where(TimeEntry.task_id == task_id)
            .order_by(TimeEntry.started_at.desc())
        )
    ).all()
    return [(entry, who) for entry, who in rows]


async def history(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    mine_only: bool = False,
    project_id: uuid.UUID | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[tuple[TimeEntry, User, Task, str | None]]:
    """The work history: entries, newest first, with what they were against."""
    stmt = (
        select(TimeEntry, User, Task, Project.name)
        .join(User, User.id == TimeEntry.user_id)
        .join(Task, Task.id == TimeEntry.task_id)
        .outerjoin(Project, Project.id == Task.project_id)
        .where(entries_in_scope(user_id=user.id, ctx=ctx))
        .order_by(TimeEntry.started_at.desc())
        .limit(limit)
    )
    if mine_only:
        stmt = stmt.where(TimeEntry.user_id == user.id)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if since is not None:
        stmt = stmt.where(TimeEntry.started_at >= since)
    return [(e, u, t, p) for e, u, t, p in (await db.execute(stmt)).all()]


async def rollups(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    *,
    project_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> dict:
    """Totals by person, by project and by task.

    Three aggregates rather than one grouped result, because they answer three
    different questions and the UI shows them side by side. Each is a single
    statement over the same visible-task subquery, so they always agree.

    Running entries are counted up to `now()` — a timer going since this
    morning is real work, and excluding it makes today's total look wrong all
    day.
    """
    elapsed = func.sum(
        func.extract("epoch", func.coalesce(TimeEntry.ended_at, func.now()) - TimeEntry.started_at)
    )
    in_scope = entries_in_scope(user_id=user.id, ctx=ctx)

    def base(*extra_columns):
        stmt = (
            select(*extra_columns, elapsed.label("seconds"))
            .select_from(TimeEntry)
            .join(Task, Task.id == TimeEntry.task_id)
            .where(in_scope)
        )
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        if since is not None:
            stmt = stmt.where(TimeEntry.started_at >= since)
        return stmt

    total = (await db.execute(base())).scalar_one() or 0

    by_person = (
        await db.execute(
            base(User.id, User.display_name, User.email)
            .join(User, User.id == TimeEntry.user_id)
            .group_by(User.id, User.display_name, User.email)
            .order_by(elapsed.desc())
        )
    ).all()

    by_project = (
        await db.execute(
            base(Project.id, Project.name)
            .outerjoin(Project, Project.id == Task.project_id)
            .group_by(Project.id, Project.name)
            .order_by(elapsed.desc())
        )
    ).all()

    by_task = (
        await db.execute(
            base(Task.id, Task.title)
            .group_by(Task.id, Task.title)
            .order_by(elapsed.desc())
            .limit(20)
        )
    ).all()

    return {
        "total_seconds": int(total),
        "by_person": [
            {"id": str(r[0]), "name": r[1] or r[2], "seconds": int(r[-1] or 0)} for r in by_person
        ],
        "by_project": [
            # A null project id is the loose tasks, grouped together rather
            # than dropped — that time was still spent.
            {
                "id": str(r[0]) if r[0] else None,
                "name": r[1] or "No project",
                "seconds": int(r[-1] or 0),
            }
            for r in by_project
        ],
        "by_task": [
            {"id": str(r[0]), "name": r[1], "seconds": int(r[-1] or 0)} for r in by_task
        ],
    }


# --- writes --------------------------------------------------------------------


async def _readable_task(
    db: AsyncSession, ctx: OrgContext, user: User, task_id: uuid.UUID
) -> Task:
    """Rule 3: `read` is enough to log your own time against something."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    return tctx.task


async def start(
    db: AsyncSession, ctx: OrgContext, user: User, task_id: uuid.UUID
) -> tuple[TimeEntry, TimeEntry | None]:
    """Start a timer, stopping whatever was already running.

    Returns the new entry and the one it displaced, so the UI can say "stopped
    your timer on X" rather than silently swallowing it.
    """
    task = await _readable_task(db, ctx, user, task_id)

    stopped = await running_for(db, user)
    if stopped is not None:
        if stopped.task_id == task.id:
            # Already timing this exact task. Not an error, and definitely not
            # a reason to restart the clock and lose the elapsed time.
            return stopped, None
        stopped.ended_at = func.now()
        # The displaced task gets its own history row — otherwise time appears
        # on it with nothing saying where it came from.
        db.add(
            _event(stopped.task_id, user, EVENT_TIME_LOGGED, reason="switched to another task")
        )

    entry = TimeEntry(task_id=task.id, user_id=user.id, started_at=func.now())
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # The partial unique index. Two tabs, two clicks, same instant.
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="a timer is already running — stop it first",
        ) from exc
    await db.refresh(entry)
    if stopped is not None:
        await db.refresh(stopped)
    return entry, stopped


def _event(task_id: uuid.UUID, actor: User, kind: str, **data):
    from app.models import TaskEvent

    return TaskEvent(task_id=task_id, actor_user_id=actor.id, kind=kind, data=data)


async def stop(db: AsyncSession, user: User) -> TimeEntry | None:
    """Stop the running timer. Idempotent — nothing running is not an error."""
    entry = await running_for(db, user)
    if entry is None:
        return None
    entry.ended_at = func.now()
    db.add(_event(entry.task_id, user, EVENT_TIME_LOGGED))
    await db.commit()
    await db.refresh(entry)
    return entry


async def log_manual(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    task_id: uuid.UUID,
    *,
    minutes: int,
    started_at: datetime | None = None,
    note: str | None = None,
) -> TimeEntry:
    """Record time already spent.

    Takes a duration rather than two timestamps: "I did 90 minutes on this" is
    how people actually think about it, and it removes a whole class of
    end-before-start mistakes at the door. `started_at` is only needed to
    backdate.
    """
    task = await _readable_task(db, ctx, user, task_id)
    if minutes <= 0:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="how long did it take?",
        )

    now = datetime.now(UTC)
    began = started_at or (now - timedelta(minutes=minutes))
    if began.tzinfo is None:
        began = began.replace(tzinfo=UTC)
    finished = began + timedelta(minutes=minutes)
    validate_manual(started_at=began, ended_at=finished, now=now)

    entry = TimeEntry(
        task_id=task.id,
        user_id=user.id,
        started_at=began,
        ended_at=finished,
        note=(note or "").strip() or None,
    )
    db.add(entry)
    db.add(_event(task.id, user, EVENT_TIME_LOGGED, minutes=minutes, manual=True))
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_entry(
    db: AsyncSession, ctx: OrgContext, user: User, entry_id: uuid.UUID
) -> TimeEntry:
    entry = (
        await db.execute(
            _visible_entries_stmt(user_id=user.id, ctx=ctx).where(TimeEntry.id == entry_id)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="time entry not found"
        )
    return entry


async def edit(
    db: AsyncSession,
    ctx: OrgContext,
    user: User,
    entry: TimeEntry,
    *,
    minutes: int | None = None,
    note: str | None = None,
    note_set: bool = False,
) -> TimeEntry:
    """Correct an entry after the fact, leaving a trail."""
    if not can_edit_entry(entry_user_id=entry.user_id, actor_id=user.id, org_role=ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you can only change your own time entries",
        )

    changed = {}
    if minutes is not None:
        if entry.ended_at is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="stop the timer before changing its length",
            )
        if minutes <= 0:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="how long did it take?",
            )
        was = duration_seconds(entry.started_at, entry.ended_at, now=datetime.now(UTC)) // 60
        new_end = entry.started_at + timedelta(minutes=minutes)
        validate_manual(started_at=entry.started_at, ended_at=new_end, now=datetime.now(UTC))
        entry.ended_at = new_end
        changed = {"was_minutes": was, "now_minutes": minutes}

    if note_set:
        entry.note = (note or "").strip() or None

    if changed or note_set:
        entry.edited_at = func.now()
        db.add(_event(entry.task_id, user, EVENT_TIME_EDITED, **changed))
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete(db: AsyncSession, ctx: OrgContext, user: User, entry: TimeEntry) -> None:
    if not can_edit_entry(entry_user_id=entry.user_id, actor_id=user.id, org_role=ctx.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="you can only remove your own time entries",
        )
    minutes = duration_seconds(entry.started_at, entry.ended_at, now=datetime.now(UTC)) // 60
    # The event outlives the entry, so a rollup that shrinks has an explanation.
    db.add(_event(entry.task_id, user, EVENT_TIME_DELETED, minutes=minutes))
    await db.delete(entry)
    await db.commit()
