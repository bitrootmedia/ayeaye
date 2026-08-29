"""The calendar: every visible task's due date, and your own reminders.

Two different scopes on one grid, and that's deliberate rather than
inconsistent:

* **Tasks are team-wide** — every task the caller can see with a due date in
  the window, the same access as the Tasks list and board. A calendar is a
  shared "what's due when", not a personal agenda; narrowing it to
  owner/action-required the way the dashboard's escalation cards do would
  make it too quiet to be useful in a team of more than one.
* **Reminders stay private** — `reminders_service.mine_stmt` is the same
  statement every other reminder surface uses, and there is no version of it
  that shows anyone else's. Two people looking at the same calendar in the
  same organisation see the same task dots and different reminder dots.
"""

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Project, Reminder
from app.services import reminders as reminders_service
from app.services import tasks as tasks_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["calendar"])

# A month grid is never more than six weeks. A caller asking for a wider
# window than that is asking for something this endpoint isn't — the Tasks
# list already answers "everything due, unbounded" with actual paging.
MAX_WINDOW_DAYS = 42


class CalendarTaskOut(BaseModel):
    id: str
    title: str
    due_on: date
    status: str
    priority: str
    project_name: str | None


class CalendarReminderOut(BaseModel):
    id: str
    remind_on: date
    note: str | None
    task_id: str
    task_title: str


class CalendarOut(BaseModel):
    tasks: list[CalendarTaskOut]
    reminders: list[CalendarReminderOut]


async def _project_names(db: DbSession, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = (
        await db.execute(select(Project.id, Project.name).where(Project.organisation_id == org_id))
    ).all()
    return {pid: name for pid, name in rows}


@router.get("/calendar", response_model=CalendarOut)
async def calendar(
    ctx: CurrentOrg, user: CurrentUser, db: DbSession, start: date, end: date
):
    """Everything with a date in `[start, end]`, both inclusive.

    One request for the whole visible grid, the same reasoning as the
    dashboard: a month view that renders in two stages — tasks, then a
    reminder popping in a moment later — looks broken.
    """
    if end < start:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end must not be before start",
        )
    if (end - start).days > MAX_WINDOW_DAYS:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"that's more than {MAX_WINDOW_DAYS} days — ask for a narrower window",
        )

    visible = await tasks_service.list_visible(db, ctx, user, due_after=start, due_before=end)
    names = await _project_names(db, ctx.organisation.id)

    reminder_rows = (
        await db.execute(
            reminders_service.mine_stmt(user_id=user.id, ctx=ctx).where(
                Reminder.remind_on >= start,
                Reminder.remind_on <= end,
            )
        )
    ).all()

    return CalendarOut(
        tasks=[
            CalendarTaskOut(
                id=str(task.id),
                title=task.title,
                due_on=task.due_on,
                status=task.status,
                priority=task.priority,
                project_name=names.get(task.project_id) if task.project_id else None,
            )
            for task, _level in visible
            # `due_after`/`due_before` already excludes a NULL due_on — SQL's
            # three-valued logic makes `NULL >= start` neither true nor
            # matched — so every row here already has one. This is just what
            # tells the type checker that.
            if task.due_on is not None
        ],
        reminders=[
            CalendarReminderOut(
                id=str(reminder.id),
                remind_on=reminder.remind_on,
                note=reminder.note,
                task_id=str(reminder_task.id),
                task_title=reminder_task.title,
            )
            for reminder, reminder_task in reminder_rows
        ],
    )
