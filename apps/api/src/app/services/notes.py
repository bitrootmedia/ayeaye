"""Private notes on a task.

Two rules, and the first is the feature:

1. **Only the author, ever.** Every statement in this module filters on
   `user_id == the caller`. Not "unless they're an admin", not "unless they
   own the task" — there is no branch. The absence of an override is the
   thing being promised, so there is nothing here to read except that.

2. **You still need to be able to see the task.** A note hangs off work; if
   the work becomes invisible to you, so does your note about it. The
   consequence, stated because it will surprise somebody: if a task's owner
   hides it, your note on that task stops appearing anywhere. It is not
   deleted, and it comes back if you get access again.

Saving an empty note deletes it, so "clear the box" and "remove the note" are
the same gesture and no empty rows accumulate.
"""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskNote, User
from app.services import access
from app.services.organisations import OrgContext


async def get(db: AsyncSession, task_id: uuid.UUID, user: User) -> TaskNote | None:
    """The caller's note on this task, if they've written one."""
    return (
        await db.execute(
            select(TaskNote).where(TaskNote.task_id == task_id, TaskNote.user_id == user.id)
        )
    ).scalar_one_or_none()


async def save(
    db: AsyncSession, task_id: uuid.UUID, user: User, *, body: str
) -> TaskNote | None:
    """Write the note, or delete it if the body is now empty.

    An upsert on `(task_id, user_id)` rather than select-then-insert: the
    editor autosaves, so two saves can overlap, and the second would otherwise
    hit the unique index with a 500 in the middle of typing.
    """
    body = (body or "").strip()
    if not body:
        existing = await get(db, task_id, user)
        if existing is not None:
            await db.delete(existing)
            await db.commit()
        return None

    stmt = (
        insert(TaskNote)
        .values(task_id=task_id, user_id=user.id, body=body)
        .on_conflict_do_update(
            constraint="uq_task_notes_task_user",
            # `onupdate` doesn't fire on a Core upsert — it is an ORM-flush
            # hook — so the timestamp is set here explicitly.
            set_={"body": body, "updated_at": func.now()},
        )
        .returning(TaskNote)
    )
    row = (await db.execute(stmt)).scalar_one()
    await db.commit()
    await db.refresh(row)
    return row


def notes_stmt(*, user_id: uuid.UUID, ctx: OrgContext) -> Select:
    """Every note of the caller's, on a task they can still see.

    The visibility expression is ANDed in here rather than applied afterwards,
    the same as everything else that lists — see `services/search.py` for why
    that matters even when the rows are the caller's own.
    """
    return (
        select(TaskNote, Task)
        .join(Task, Task.id == TaskNote.task_id)
        .where(
            TaskNote.user_id == user_id,
            Task.organisation_id == ctx.organisation.id,
            Task.id.in_(
                access.visible_task_ids_stmt(
                    user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role
                )
            ),
        )
    )
