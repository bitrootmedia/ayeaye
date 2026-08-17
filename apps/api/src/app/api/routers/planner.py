"""The day planner: a pool of open, unplanned tasks and five fixed buckets.

Thin, like tasks.py — the rules live in services/planner.py. Purely
organisation-scoped, unlike reminders.py's global/org split: there is no
cross-organisation planner, because "today" only means something once you
know which organisation's tasks you're looking at.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentOrg, CurrentUser, DbSession
from app.models.planner import BUCKETS
from app.models.task import Task
from app.schemas.planner import PlannerEntryOut, PlannerOut, PlannerPlaceIn, PlannerTaskOut
from app.services import planner as planner_service

router = APIRouter(prefix="/organisations/{org_id}", tags=["planner"])


def _task_out(task: Task) -> PlannerTaskOut:
    return PlannerTaskOut(
        id=str(task.id),
        title=task.title,
        priority=task.priority,
        status=task.status,
        is_open=task.closed_at is None,
    )


@router.get("/planner", response_model=PlannerOut)
async def get_planner(
    ctx: CurrentOrg, user: CurrentUser, db: DbSession, user_id: uuid.UUID | None = None
):
    """Somebody's planner — the caller's by default, or `?user_id=` if the
    caller administers this organisation. See `planner_service.resolve_target`
    for the 403 a plain member gets for asking about anyone else."""
    target_id, target_role = await planner_service.resolve_target(db, ctx, user, user_id=user_id)

    pool_rows = (
        await db.execute(
            planner_service.pool_stmt(
                target_user_id=target_id, org_id=ctx.organisation.id, org_role=target_role
            )
        )
    ).all()
    bucket_rows = (
        await db.execute(
            planner_service.buckets_stmt(
                target_user_id=target_id, org_id=ctx.organisation.id, org_role=target_role
            )
        )
    ).all()

    buckets: dict[str, list[PlannerEntryOut]] = {b: [] for b in BUCKETS}
    for entry, task in bucket_rows:
        buckets[entry.bucket].append(
            PlannerEntryOut(task=_task_out(task), bucket=entry.bucket, position=entry.position)
        )
    return PlannerOut(pool=[_task_out(t) for t, _rank in pool_rows], buckets=buckets)


@router.put("/planner/{task_id}", response_model=PlannerEntryOut)
async def place_task(
    task_id: uuid.UUID,
    body: PlannerPlaceIn,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    user_id: uuid.UUID | None = None,
):
    """Place a task into a bucket, or move it — an upsert either way. Dropped
    on the pool instead? That's `DELETE`, not this."""
    target_id, target_role = await planner_service.resolve_target(db, ctx, user, user_id=user_id)
    entry, task = await planner_service.place(
        db,
        target_user_id=target_id,
        target_org_role=target_role,
        org_id=ctx.organisation.id,
        task_id=task_id,
        bucket=body.bucket,
        position=body.position,
    )
    return PlannerEntryOut(task=_task_out(task), bucket=entry.bucket, position=entry.position)


@router.delete("/planner/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unplan_task(
    task_id: uuid.UUID,
    ctx: CurrentOrg,
    user: CurrentUser,
    db: DbSession,
    user_id: uuid.UUID | None = None,
):
    """Back to the pool."""
    target_id, _role = await planner_service.resolve_target(db, ctx, user, user_id=user_id)
    await planner_service.remove(db, target_user_id=target_id, task_id=task_id)
