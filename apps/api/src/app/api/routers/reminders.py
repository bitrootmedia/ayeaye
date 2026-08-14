"""Reminders — personal, and therefore mostly outside an organisation.

Two surfaces:

* **`/organisations/{id}/tasks/{id}/reminders`** — setting one needs the task,
  so it lives under the organisation like everything else about a task.
* **`/reminders`** — reading them does not. The list and the badge are
  cross-organisation on purpose, the same way the notification inbox is: a
  reminder you set in one place must not be invisible because you happen to
  be looking at another.
"""

import uuid
from datetime import date

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models import Organisation
from app.models.reminder import MAX_NOTE_LENGTH
from app.services import reminders as reminders_service
from app.services import tasks as tasks_service

router = APIRouter(tags=["reminders"])


class ReminderIn(BaseModel):
    remind_on: date
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class ReminderUpdate(BaseModel):
    remind_on: date | None = None
    note: str | None = None
    done: bool | None = None


class ReminderOut(BaseModel):
    id: str
    remind_on: date
    note: str | None
    # Resolved server-side against the caller's own timezone: "is it today
    # yet" is not a question the browser can answer for somebody who set the
    # reminder on their phone in another country.
    overdue: bool
    task_id: str
    task_title: str | None = None
    organisation_id: str | None = None
    organisation_name: str | None = None


def _out(reminder, *, today: date, task=None, org_name: str | None = None) -> ReminderOut:
    return ReminderOut(
        id=str(reminder.id),
        remind_on=reminder.remind_on,
        note=reminder.note,
        overdue=reminders_service.is_overdue(reminder.remind_on, today=today),
        task_id=str(reminder.task_id),
        task_title=task.title if task is not None else None,
        organisation_id=str(task.organisation_id) if task is not None else None,
        organisation_name=org_name,
    )


# --- on a task ---------------------------------------------------------------


@router.get(
    "/organisations/{org_id}/tasks/{task_id}/reminders", response_model=list[ReminderOut]
)
async def task_reminders(
    task_id: uuid.UUID, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """**Yours** on this task. There is no way to see anybody else's."""
    await tasks_service.context_for(db, ctx, task_id, user)
    today = reminders_service.today_for(user)
    return [_out(r, today=today) for r in await reminders_service.for_task(db, task_id, user)]


@router.post(
    "/organisations/{org_id}/tasks/{task_id}/reminders",
    response_model=ReminderOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_reminder(
    task_id: uuid.UUID, body: ReminderIn, ctx: CurrentOrg, user: CurrentUser, db: DbSession
):
    """`read` on the task is enough — it's a note to self about work you can
    see, not a change to the work."""
    tctx = await tasks_service.context_for(db, ctx, task_id, user)
    row = await reminders_service.create(
        db, tctx.task, user, remind_on=body.remind_on, note=body.note
    )
    return _out(row, today=reminders_service.today_for(user))


# --- yours, across everything -------------------------------------------------


@router.get("/reminders", response_model=list[ReminderOut])
async def my_reminders(user: CurrentUser, db: DbSession):
    """Every live reminder of yours, soonest first, across organisations."""
    from sqlalchemy import select

    rows = (await db.execute(reminders_service.mine_stmt(user_id=user.id))).all()
    org_names = dict(
        (
            await db.execute(select(Organisation.id, Organisation.name))
        ).all()
    )
    today = reminders_service.today_for(user)
    return [
        _out(r, today=today, task=t, org_name=org_names.get(t.organisation_id))
        for r, t in rows
    ]


@router.get("/reminders/due-count")
async def my_due_count(user: CurrentUser, db: DbSession):
    """Just the number, for the red badge.

    Its own endpoint rather than a field on `/me`, because the shell polls
    this and `/me` is the request everything else blocks on.
    """
    return {"count": await reminders_service.due_count(db, user)}


@router.patch("/reminders/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: uuid.UUID, body: ReminderUpdate, user: CurrentUser, db: DbSession
):
    """Move it, re-word it, or mark it done.

    Moving it to a new day clears the two "already notified" stamps, which is
    what makes snoozing actually notify again — see services/reminders.py.
    """
    row = await reminders_service.get_or_404(db, reminder_id, user)
    row = await reminders_service.update_one(
        db, row, user, fields=body.model_dump(exclude_unset=True)
    )
    return _out(row, today=reminders_service.today_for(user))


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(reminder_id: uuid.UUID, user: CurrentUser, db: DbSession):
    row = await reminders_service.get_or_404(db, reminder_id, user)
    await reminders_service.remove(db, row)
