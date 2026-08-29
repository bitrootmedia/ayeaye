"""Personal pins on a task — a bookmark, not a property of the task.

Two rules, mirroring `services/notes.py`:

1. **Yours to set, yours alone to see.** Pinning is what *you* want on *your*
   dashboard. Nobody else's dashboard changes because you pinned something,
   and there is no admin override — the same absence-of-a-branch discipline
   as private notes, though pins carry no content worth protecting the way a
   note's body does.

2. **`read` is enough.** Pinning isn't a change to the work — it's a record of
   what *you* find worth watching, the same reasoning that lets read-only
   access log your own time. You still need to be able to see the task: a pin
   on a task that becomes invisible to you stops appearing anywhere, and comes
   back if you regain access, because the row itself is untouched.
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskPin, User
from app.services import access
from app.services.organisations import OrgContext


async def is_pinned(db: AsyncSession, task_id: uuid.UUID, user: User) -> bool:
    row = (
        await db.execute(
            select(TaskPin.id).where(TaskPin.task_id == task_id, TaskPin.user_id == user.id)
        )
    ).scalar_one_or_none()
    return row is not None


async def pinned_ids(db: AsyncSession, task_ids: list[uuid.UUID], user: User) -> set[uuid.UUID]:
    """Which of these tasks the caller has pinned. One lookup for a whole page,
    never one per row."""
    if not task_ids:
        return set()
    rows = (
        await db.execute(
            select(TaskPin.task_id).where(
                TaskPin.task_id.in_(task_ids), TaskPin.user_id == user.id
            )
        )
    ).scalars().all()
    return set(rows)


async def set_pinned(db: AsyncSession, task_id: uuid.UUID, user: User, *, pinned: bool) -> None:
    """Idempotent either way: pinning twice, or unpinning something that was
    never pinned, is a no-op rather than an error."""
    if pinned:
        stmt = (
            insert(TaskPin)
            .values(task_id=task_id, user_id=user.id)
            .on_conflict_do_nothing(constraint="uq_task_pins_task_user")
        )
        await db.execute(stmt)
    else:
        await db.execute(
            TaskPin.__table__.delete().where(
                TaskPin.task_id == task_id, TaskPin.user_id == user.id
            )
        )
    await db.commit()


def my_pinned_tasks_stmt(*, user_id: uuid.UUID, ctx: OrgContext) -> Select:
    """Every open task the caller has pinned, that they can still see.

    The visibility expression is ANDed in here rather than applied afterwards
    — the same discipline as `notes_stmt`, and for the same reason: a pin
    outlives whatever access justified it, so trusting the join to `tasks`
    alone would let a task that's since gone private (or hidden) stay visible
    in its own pinned card.
    """
    return (
        select(Task, TaskPin.created_at)
        .join(TaskPin, TaskPin.task_id == Task.id)
        .where(
            TaskPin.user_id == user_id,
            Task.organisation_id == ctx.organisation.id,
            Task.closed_at.is_(None),
            Task.id.in_(
                access.visible_task_ids_stmt(
                    user_id=user_id, org_id=ctx.organisation.id, org_role=ctx.role
                )
            ),
        )
        .order_by(TaskPin.created_at.desc())
    )
