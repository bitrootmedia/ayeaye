"""Timers, manual entries and rollups.

Two prefixes on purpose. The running timer is **per person, globally** — one
per human across the whole installation — so it lives under `/me`, next to
notifications. Everything that hangs off a task is organisation-scoped like the
rest of the API.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Task, TimeEntry, User
from app.schemas.structure import PersonOut
from app.schemas.time import (
    ManualEntryIn,
    StartTimerOut,
    TimeEntryOut,
    TimeEntryUpdate,
    TimerOut,
    TimeSummaryOut,
)
from app.services import time_tracking

me_router = APIRouter(prefix="/me", tags=["time"])
router = APIRouter(prefix="/organisations/{org_id}", tags=["time"])


def _person(user: User | None) -> PersonOut | None:
    if user is None:
        return None
    return PersonOut(id=str(user.id), email=user.email, display_name=user.display_name)


def _entry_out(
    entry: TimeEntry,
    *,
    who: User | None = None,
    task_title: str | None = None,
    project_name: str | None = None,
) -> TimeEntryOut:
    return TimeEntryOut(
        id=str(entry.id),
        task_id=str(entry.task_id),
        task_title=task_title,
        project_name=project_name,
        user=_person(who),
        started_at=entry.started_at,
        ended_at=entry.ended_at,
        seconds=time_tracking.duration_seconds(
            entry.started_at, entry.ended_at, now=datetime.now(UTC)
        ),
        note=entry.note,
        edited_at=entry.edited_at,
    )


# --- the running timer, per person ------------------------------------------


@me_router.get("/timer", response_model=TimerOut)
async def my_timer(user: CurrentUser, db: DbSession):
    """What you're timing right now, in any organisation.

    Polled by the shell so a timer left running yesterday is visible today,
    whichever organisation you happen to open.
    """
    entry = await time_tracking.running_for(db, user)
    if entry is None:
        return TimerOut(entry=None)

    task = (await db.execute(select(Task).where(Task.id == entry.task_id))).scalar_one()
    return TimerOut(
        entry=_entry_out(entry, who=user, task_title=task.title),
        organisation_id=str(task.organisation_id),
    )


@me_router.post("/timer/stop", response_model=TimerOut)
async def stop_timer(user: CurrentUser, db: DbSession):
    """Stop it. Idempotent — nothing running is not an error, because the
    button may well have been clicked twice."""
    entry = await time_tracking.stop(db, user)
    return TimerOut(entry=_entry_out(entry, who=user) if entry else None)


# --- against a task -----------------------------------------------------------


@router.post("/tasks/{task_id}/time/start", response_model=StartTimerOut)
async def start_timer(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Start timing this task.

    **Starting stops whatever was already running**, rather than refusing.
    Switching tasks is the commonest thing anyone does with a tracker, and a
    409 there means the answer to "why won't it start" is a modal. The
    displaced entry comes back in the response so the UI can say so.

    `read` on the task is enough: time is a record of what *you* did.
    """
    entry, stopped = await time_tracking.start(db, ctx, user, task_id)
    return StartTimerOut(
        entry=_entry_out(entry, who=user),
        stopped=_entry_out(stopped, who=user) if stopped else None,
    )


@router.get("/tasks/{task_id}/time", response_model=list[TimeEntryOut])
async def task_time(task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    """Everyone's entries on this task, with names. A work log that hides who
    did what can't answer the question it exists for."""
    return [
        _entry_out(entry, who=who)
        for entry, who in await time_tracking.list_for_task(db, ctx, user, task_id)
    ]


@router.post(
    "/tasks/{task_id}/time", response_model=TimeEntryOut, status_code=status.HTTP_201_CREATED
)
async def log_time(
    task_id: uuid.UUID, body: ManualEntryIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """Record time already spent."""
    entry = await time_tracking.log_manual(
        db,
        ctx,
        user,
        task_id,
        minutes=body.minutes,
        started_at=body.started_at,
        note=body.note,
    )
    return _entry_out(entry, who=user)


@router.patch("/time/{entry_id}", response_model=TimeEntryOut)
async def edit_entry(
    entry_id: uuid.UUID,
    body: TimeEntryUpdate,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
):
    """Correct an entry. Yours, or anyone's if you administer the organisation.

    Deliberately **not** the task owner: someone else's timesheet is not theirs
    to edit, even on work they're responsible for. Every correction writes a
    `task_events` row, so a rollup that changes has an explanation.
    """
    entry = await time_tracking.get_entry(db, ctx, user, entry_id)
    updated = await time_tracking.edit(
        db,
        ctx,
        user,
        entry,
        minutes=body.minutes,
        note=body.note,
        note_set="note" in body.model_fields_set,
    )
    return _entry_out(updated, who=user)


@router.delete("/time/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession):
    entry = await time_tracking.get_entry(db, ctx, user, entry_id)
    await time_tracking.delete(db, ctx, user, entry)


# --- rollups and history --------------------------------------------------------


@router.get("/time/summary", response_model=TimeSummaryOut)
async def summary(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    project_id: uuid.UUID | None = None,
    days: int | None = None,
):
    """Totals by person, project and task — over what the caller can see.

    Three aggregates over one visible-task subquery, so they always agree with
    each other and with the board.
    """
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    data = await time_tracking.rollups(db, ctx, user, project_id=project_id, since=since)
    return TimeSummaryOut(**data)


@router.get("/time/entries", response_model=list[TimeEntryOut])
async def entries(
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    mine: bool = False,
    project_id: uuid.UUID | None = None,
    days: int | None = None,
    limit: int = 200,
):
    """The work history — what was done, by whom, against what."""
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    return [
        _entry_out(entry, who=who, task_title=task.title, project_name=project_name)
        for entry, who, task, project_name in await time_tracking.history(
            db,
            ctx,
            user,
            mine_only=mine,
            project_id=project_id,
            since=since,
            limit=min(limit, 500),
        )
    ]
