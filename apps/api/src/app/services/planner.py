"""A personal day planner: a pool of unplanned work, and five fixed buckets.

Two rules:

1. **One entry per task per person.** Unplanned is "no row", not a bucket of
   its own — `uq_planner_entries_task_user` is what the upsert in `place()`
   relies on, the same way `services/notes.py` relies on its own unique
   constraint.

2. **Yours, or an organisation admin's override — same escape hatch as time
   entries, narrower than none at all.** An admin may view and rearrange
   *any* member's planner: which bucket a task is in, and in what order. What
   an admin's override does **not** do is grant them access to a task the
   *target* doesn't already have — placing or reading always resolves
   visibility against the target's own membership and role, never the
   caller's. A task that's hidden, or no longer shared with the target, drops
   out of their buckets exactly the way it drops out of their board, and an
   admin looking at someone else's planner sees precisely what that person
   would see — nothing more. That's the same boundary `hidden_at` already
   draws everywhere else; this file doesn't get to redraw it. That is why
   `buckets_stmt` re-applies `visible_task_ids_stmt` rather than trusting the
   join: a `planner_entries` row outlives whatever access justified it, same
   as a note or a reminder, and the read has to re-check rather than the
   write having to clean up after every possible way access can be taken away
   later.
"""

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrganisationMember, PlannerEntry, Task, User
from app.models.organisation import STATUS_ACTIVE
from app.services import access
from app.services.organisations import OrgContext


async def _member_role_or_404(db: AsyncSession, ctx: OrgContext, user_id: uuid.UUID) -> str:
    role = (
        await db.execute(
            select(OrganisationMember.role).where(
                OrganisationMember.organisation_id == ctx.organisation.id,
                OrganisationMember.user_id == user_id,
                OrganisationMember.status == STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="that person is not a member of this organisation",
        )
    return role


async def resolve_target(
    db: AsyncSession, ctx: OrgContext, actor: User, *, user_id: uuid.UUID | None
) -> tuple[uuid.UUID, str]:
    """Whose planner this request is about, and their org role.

    Defaults to the caller. Resolving anyone else requires the caller to
    administer the organisation — `ctx.require` is what turns that into a
    403, not a 404: the organisation is real, the caller just may not do
    this.
    """
    if user_id is None or user_id == actor.id:
        return actor.id, ctx.role
    ctx.require(
        access.administers_organisation(ctx.role),
        "only an organisation admin may view or edit another member's planner",
    )
    role = await _member_role_or_404(db, ctx, user_id)
    return user_id, role


# --- reads -------------------------------------------------------------------


def pool_stmt(*, target_user_id: uuid.UUID, org_id: uuid.UUID, org_role: str) -> Select:
    """Open, visible tasks the target hasn't planned yet.

    `visible_tasks_stmt` already gives open-only, off-board-excluded,
    priority-first ordering for free when no `sort=` is passed — that is the
    pool's default order.
    """
    entered = exists().where(
        PlannerEntry.task_id == Task.id, PlannerEntry.user_id == target_user_id
    )
    pool = access.visible_tasks_stmt(user_id=target_user_id, org_id=org_id, org_role=org_role)
    return pool.where(~entered)


def buckets_stmt(*, target_user_id: uuid.UUID, org_id: uuid.UUID, org_role: str) -> Select:
    """Every planned task of the target's, in every bucket, in manual order.

    One statement for all five buckets — sorting the rows into columns
    happens in the router, in Python, which is fine here and would not be
    for the board: this is one person's list, never paginated, never large
    enough to need `board_stmt`'s windowed bounding.
    """
    visible = access.visible_task_ids_stmt(user_id=target_user_id, org_id=org_id, org_role=org_role)
    return (
        select(PlannerEntry, Task)
        .join(Task, Task.id == PlannerEntry.task_id)
        .where(PlannerEntry.user_id == target_user_id, Task.id.in_(visible))
        .order_by(PlannerEntry.bucket, PlannerEntry.position, PlannerEntry.id)
    )


# --- writes ------------------------------------------------------------------


async def place(
    db: AsyncSession,
    *,
    target_user_id: uuid.UUID,
    target_org_role: str,
    org_id: uuid.UUID,
    task_id: uuid.UUID,
    bucket: str,
    position: int,
) -> tuple[PlannerEntry, Task]:
    """Put a task in a bucket, moving it if it's already in one.

    Visibility is checked against the **target**, not the caller — an admin
    placing something into someone else's planner cannot place a task that
    person couldn't otherwise see; this 404s exactly as it would for them
    acting alone.

    Upsert on `(task_id, user_id)`, same shape as `services/notes.py`'s save:
    a double-submit from a fast drag must not create two rows for one task.
    """
    row = (
        await db.execute(
            access.visible_task_stmt(
                user_id=target_user_id, org_id=org_id, org_role=target_org_role, task_id=task_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="task not found")
    task, _rank = row

    stmt = (
        insert(PlannerEntry)
        .values(task_id=task_id, user_id=target_user_id, bucket=bucket, position=position)
        .on_conflict_do_update(
            constraint="uq_planner_entries_task_user",
            # `onupdate` doesn't fire on a Core upsert — it is an ORM-flush
            # hook — so the timestamp is set here explicitly.
            set_={"bucket": bucket, "position": position, "updated_at": func.now()},
        )
        .returning(PlannerEntry)
    )
    entry = (await db.execute(stmt)).scalar_one()
    await db.commit()
    await db.refresh(entry)
    return entry, task


async def remove(db: AsyncSession, *, target_user_id: uuid.UUID, task_id: uuid.UUID) -> None:
    """Back to the pool.

    Idempotent: dropping an already-unplanned task, or racing another remove,
    is a no-op success — not a 404. Dragging to the pool and finding it
    already there is not an error a person caused.
    """
    await db.execute(
        PlannerEntry.__table__.delete().where(
            PlannerEntry.task_id == task_id, PlannerEntry.user_id == target_user_id
        )
    )
    await db.commit()
